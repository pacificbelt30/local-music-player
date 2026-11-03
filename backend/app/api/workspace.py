"""User workflows: add in batches, recover outages, retain changes and track delivery."""

from datetime import datetime, timezone, timedelta
import json
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AppSetting,
    MediaProfile,
    PlaylistSyncTrack,
    SyncEvent,
    UrlSource,
    YoutubePlaylistSync,
    DownloadJob,
)
from app.schemas import UrlSourceCreate, normalize_youtube_url, _is_youtube_url
from app.services import (
    delivery,
    recovery,
    sync_dirs,
    sync_history,
    youtube_api_service,
    ytdlp_service,
)
from app.services.profiles import BUILTINS, ProfileInput, profile, snapshot
from app.services.workspace_plans import fingerprint, save_plan, get_plan, update_plan

router = APIRouter(prefix="/workspace", tags=["workspace"])


def require_sync(db, sync_id):
    sync = db.get(YoutubePlaylistSync, sync_id)
    if sync is None:
        raise HTTPException(404, "同期が見つかりません")
    return sync


def lock(db, namespace, record_id):
    from app.tasks.sync_playlist import _redis

    value = _redis.lock(f"lmp:{namespace}:{record_id}", timeout=120, thread_local=False)
    if not value.acquire(blocking=False):
        raise HTTPException(409, "処理中です。完了後に再試行してください")
    return value


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return [profile(db, key) for key in BUILTINS] + [
        profile(db, row.id)
        for row in db.query(MediaProfile).order_by(MediaProfile.id).all()
    ]


@router.post("/profiles", status_code=201)
def create_profile(payload: ProfileInput, db: Session = Depends(get_db)):
    row = MediaProfile(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "同じ名前のプロファイルがあります")
    return profile(db, row.id)


@router.put("/profiles/{profile_id}")
def edit_profile(profile_id: int, payload: ProfileInput, db: Session = Depends(get_db)):
    row = db.get(MediaProfile, profile_id)
    if row is None:
        raise HTTPException(404, "標準プロファイルはコピーして保存してください")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "同じ名前のプロファイルがあります")
    return profile(db, row.id)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    row = db.get(MediaProfile, profile_id)
    if row is None:
        raise HTTPException(404, "プロファイルが見つかりません")
    db.delete(row)
    db.commit()  # Existing sync snapshots intentionally stay unchanged.


class ApplyInput(BaseModel):
    sync_ids: list[int] = Field(min_length=1, max_length=100)


def apply_state(db, profile_id, ids):
    selected = []
    for sync_id in sorted(set(ids)):
        sync = require_sync(db, sync_id)
        tracks = db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync_id).all()
        selected.append(
            {
                "id": sync.id,
                "title": sync.playlist_name,
                "format": sync.audio_format,
                "quality": sync.audio_quality,
                "target": [
                    sync.target_folder_id,
                    sync.target_device_id,
                    sync.target_scope,
                ],
                "tracks": [
                    (t.id, t.status, t.file_path, t.file_size_bytes, t.celery_task_id)
                    for t in tracks
                ],
            }
        )
    return {"profile": profile(db, profile_id), "syncs": selected}


@router.post("/profiles/{profile_id}/preview")
def preview_apply(profile_id: int, payload: ApplyInput, db: Session = Depends(get_db)):
    state = apply_state(db, profile_id, payload.sync_ids)
    values = state["profile"]
    files = 0
    size = 0
    for sync in state["syncs"]:
        changed = (sync["format"], sync["quality"]) != (
            values["audio_format"],
            values["audio_quality"],
        )
        if changed:
            for _, status, _, bytes_, _ in sync["tracks"]:
                if status not in ("removed", "skipped"):
                    files += 1
                    size += bytes_ or 0
    token, _ = save_plan(
        db, "profile", {"state": state, "fingerprint": fingerprint(state)}
    )
    return {
        "token": token,
        "sync_count": len(state["syncs"]),
        "redownload_count": files,
        "existing_bytes": size,
        "size_is_estimate": True,
        "profile": values,
    }


class TokenInput(BaseModel):
    token: str = Field(min_length=32, max_length=32, pattern="^[a-f0-9]+$")


@router.post("/profiles/apply")
def apply_profile(payload: TokenInput, db: Session = Depends(get_db)):
    row, plan = get_plan(db, payload.token, "profile")
    if plan.get("complete"):
        return plan["result"]
    state = plan["state"]
    ids = [s["id"] for s in state["syncs"]]
    profile_id = state["profile"]["id"]
    from app.tasks.sync_playlist import enqueue_playlist_track, _redis

    locks = []
    try:
        for sync_id in sorted(ids):
            locks.append(lock(db, "playlist-sync", sync_id))
        current = apply_state(db, profile_id, ids)
        if fingerprint(current) != plan["fingerprint"]:
            raise HTTPException(
                409, "内容が変わりました。適用前にもう一度確認してください"
            )
        values = current["profile"]
        pending = []
        # Validate every target before mutating any of them.
        future = {
            (require_sync(db, i).playlist_id, values["audio_format"]) for i in ids
        }
        if len(future) != len(ids):
            raise HTTPException(409, "同じプレイリストの保存形式が重複します")
        for sync_id in ids:
            sync = require_sync(db, sync_id)
            conflict = (
                db.query(YoutubePlaylistSync)
                .filter(
                    YoutubePlaylistSync.playlist_id == sync.playlist_id,
                    YoutubePlaylistSync.audio_format == values["audio_format"],
                    YoutubePlaylistSync.id != sync_id,
                    YoutubePlaylistSync.id.notin_(ids),
                )
                .first()
            )
            if conflict:
                raise HTTPException(409, "既存の同期と保存形式が重複します")
            tracks = (
                db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync_id).all()
            )
            if any(
                t.status in ("pending", "downloading")
                or _redis.exists(f"lmp:playlist-track:{t.id}")
                for t in tracks
            ):
                raise HTTPException(409, "DLが完了してから適用してください")
        for sync_id in ids:
            sync = require_sync(db, sync_id)
            changed = (sync.audio_format, sync.audio_quality) != (
                values["audio_format"],
                values["audio_quality"],
            )
            sync.audio_format = values["audio_format"]
            sync.audio_quality = values["audio_quality"]
            for key, value in snapshot(db, profile_id).items():
                setattr(sync, key, value)
            if changed:
                for track in (
                    db.query(PlaylistSyncTrack)
                    .filter_by(playlist_sync_id=sync_id, excluded=False)
                    .all()
                ):
                    if track.status != "removed":
                        track.status = "pending"
                        track.error_message = None
                        pending.append(track)
            sync_history.record(
                db, sync_id, "profile", name=values["name"], redownload=changed
            )
        plan["complete"] = True
        plan["result"] = {"applied": len(ids), "queued": len(pending)}
        update_plan(db, row, plan)
        db.commit()
        errors = []
        for track in pending:
            try:
                enqueue_playlist_track(db, track, manual=True)
            except Exception:
                errors.append(track.id)
        plan["result"]["dispatch_errors"] = errors
        update_plan(db, row, plan)
        db.commit()
        return plan["result"]
    except Exception:
        db.rollback()
        raise
    finally:
        for value in reversed(locks):
            value.release()


class IntakeInput(BaseModel):
    text: str = Field(min_length=1, max_length=16000)
    profile_id: int | None = None


@router.post("/intake/preview")
def preview_intake(payload: IntakeInput, db: Session = Depends(get_db)):
    if not payload.text.strip():
        raise HTTPException(422, "URLまたはプレイリスト名を入力してください")
    values = (
        profile(db, payload.profile_id)
        if payload.profile_id is not None
        else {
            "id": None,
            "name": "設定の既定値",
            "audio_format": "mp3",
            "audio_quality": "192",
            "target_folder_id": None,
            "target_device_id": None,
            "target_scope": "downloads",
        }
    )
    if payload.profile_id is None:
        from app.services.download_preferences import apply_download_defaults

        defaults = apply_download_defaults(
            UrlSourceCreate(url="https://youtu.be/defaults"), db
        )
        values.update(
            audio_format=defaults.audio_format, audio_quality=defaults.audio_quality
        )
    urls = re.findall(r'https?://[^\s,<>"\[\]]+', payload.text)
    items = []
    seen = set()
    account = None
    truncated = False

    def owned():
        nonlocal account
        if account is None:
            access = youtube_api_service.get_fresh_access_token(db)
            if not access:
                raise HTTPException(
                    401, "設定画面からYouTubeに接続すると、アカウント内を検索できます"
                )
            account = youtube_api_service.get_my_playlists(access)
        return account

    if not urls:
        matches = [
            p
            for p in owned()
            if payload.text.strip().casefold() in p["title"].casefold()
        ]
        truncated = len(matches) > 20
        items = [
            {
                "kind": "sync",
                "source_type": "api",
                "playlist_id": p["playlist_id"],
                "title": p["title"],
                "count": p.get("item_count"),
                "url": "",
                "state": "available",
            }
            for p in matches[:20]
        ]
        policy = db.get(AppSetting, "account_playlist_method")
        if policy is None or policy.value == "url":
            for item, match in zip(items, matches):
                if match.get("privacy_status") in ("public", "unlisted"):
                    item.update(
                        source_type="url",
                        url="https://www.youtube.com/playlist?list="
                        + item["playlist_id"],
                    )
    else:
        if len(urls) > 20:
            raise HTTPException(422, "一度に20件まで追加できます")
        for url in urls:
            item = {"url": url, "title": url, "state": "available", "count": None}
            try:
                if not _is_youtube_url(url):
                    raise ValueError("YouTubeのURLを入力してください")
                canonical = normalize_youtube_url(url)
                item["canonical"] = canonical
                if canonical in seen:
                    item["state"] = "duplicate"
                    items.append(item)
                    continue
                seen.add(canonical)
                if canonical.startswith("playlist:"):
                    pid = canonical.split(":", 1)[1]
                    item.update(kind="sync", source_type="url", playlist_id=pid)
                    try:
                        info = ytdlp_service.get_playlist_info(url)
                        item.update(
                            title=info["playlist_title"] or pid,
                            playlist_id=info["playlist_id"],
                            count=len(info["entries"]),
                        )
                    except Exception:
                        match = next(
                            (p for p in owned() if p["playlist_id"] == pid), None
                        )
                        if not match:
                            raise ValueError(
                                "共有URLから取得できません。非公開の場合は所有アカウントへの接続が必要です"
                            )
                        item.update(
                            source_type="api",
                            title=match["title"],
                            count=match.get("item_count"),
                        )
                else:
                    entries = ytdlp_service.resolve_url(url)
                    if not entries:
                        raise ValueError("取得できる動画がありません")
                    item.update(
                        kind="url",
                        title=entries[0].get("playlist_title")
                        or entries[0].get("title")
                        or url,
                        count=len(entries),
                        url_type=entries[0].get("url_type", "video"),
                    )
                if item["kind"] == "sync":
                    exists = (
                        db.query(YoutubePlaylistSync)
                        .filter_by(
                            playlist_id=item["playlist_id"],
                            audio_format=values["audio_format"],
                        )
                        .first()
                    )
                else:
                    exists = (
                        db.query(UrlSource).filter_by(canonical_url=canonical).first()
                    )
                if exists:
                    item["state"] = "registered"
                    item["existing_id"] = exists.id
            except HTTPException as exc:
                item.update(state="unavailable", error=str(exc.detail))
            except Exception as exc:
                item.update(state="unavailable", error=str(exc)[:300])
            items.append(item)
    for item in items:
        if item.get("kind") == "sync" and item["state"] == "available":
            existing = (
                db.query(YoutubePlaylistSync)
                .filter_by(
                    playlist_id=item["playlist_id"], audio_format=values["audio_format"]
                )
                .first()
            )
            if existing:
                item.update(state="registered", existing_id=existing.id)
    token, _ = save_plan(
        db, "intake", {"items": items, "profile": values, "results": {}}
    )
    return {
        "token": token,
        "items": items,
        "profile": values,
        "expires_in_seconds": 900,
        "truncated": truncated,
    }


class IntakeCommit(TokenInput):
    indices: list[int] = Field(min_length=1, max_length=20)


@router.post("/intake/commit")
def commit_intake(payload: IntakeCommit, db: Session = Depends(get_db)):
    from app.tasks.sync_playlist import sync_youtube_playlist
    from app.tasks.download import resolve_url

    value = lock(db, "intake", payload.token)
    try:
        row, plan = get_plan(db, payload.token, "intake")
        indices = sorted(set(payload.indices))
        if any(index < 0 or index >= len(plan["items"]) for index in indices):
            raise HTTPException(422, "追加対象が不正です")
        if plan.get("selection") is not None and plan["selection"] != indices:
            raise HTTPException(409, "追加中の対象は変更できません。再確認してください")
        plan["selection"] = indices
        values = plan["profile"]
        for index in indices:
            item = plan["items"][index]
            key = str(index)
            old = plan["results"].get(key)
            if old and old["state"] == "cancelled":
                continue
            if (
                old
                and old["state"] in ("created", "registered")
                and old.get("dispatched", True)
            ):
                continue
            try:
                if datetime.fromisoformat(plan["expires_at"]) < datetime.now(
                    timezone.utc
                ) and not (old and old["state"] == "created"):
                    plan["results"][key] = {
                        "state": "cancelled",
                        "title": item["title"],
                        "error": "未登録の対象は内容を再確認してください。",
                        "retryable": False,
                    }
                    continue
                if item["state"] != "available":
                    plan["results"][key] = {
                        "state": item["state"],
                        "title": item["title"],
                    }
                    continue
                if old and old["state"] == "created":
                    record_id = old["id"]
                    current = db.get(
                        YoutubePlaylistSync if item["kind"] == "sync" else UrlSource,
                        record_id,
                    )
                    matches = current is not None and (
                        (
                            current.playlist_id == item["playlist_id"]
                            and current.audio_format == values["audio_format"]
                        )
                        if item["kind"] == "sync"
                        else current.canonical_url == item["canonical"]
                    )
                    if not matches:
                        plan["results"][key] = {
                            **old,
                            "state": "cancelled",
                            "error": "登録後に削除・変更されました。内容を再確認してください。",
                            "retryable": False,
                        }
                        continue
                else:
                    dest = {
                        k: values.get(k)
                        for k in (
                            "target_folder_id",
                            "target_device_id",
                            "target_scope",
                        )
                    }
                    dest.update(
                        profile_id=values["id"],
                        profile_name=values["name"]
                        if values["id"] is not None
                        else None,
                    )
                    if item["kind"] == "sync":
                        existing = (
                            db.query(YoutubePlaylistSync)
                            .filter_by(
                                playlist_id=item["playlist_id"],
                                audio_format=values["audio_format"],
                            )
                            .first()
                        )
                        record = existing or YoutubePlaylistSync(
                            playlist_id=item["playlist_id"],
                            playlist_name=item["title"],
                            dir_name=sync_dirs.allocate_sync_dir_name(
                                db, item["title"], values["audio_format"]
                            ),
                            source_type=item["source_type"],
                            source_url=item["url"],
                            audio_format=values["audio_format"],
                            audio_quality=values["audio_quality"],
                            **dest,
                        )
                    else:
                        existing = (
                            db.query(UrlSource)
                            .filter_by(canonical_url=item["canonical"])
                            .first()
                        )
                        record = existing or UrlSource(
                            url=item["url"],
                            canonical_url=item["canonical"],
                            url_type=item["url_type"],
                            title=item["title"],
                            audio_format=values["audio_format"],
                            audio_quality=values["audio_quality"],
                            **dest,
                        )
                    if existing:
                        plan["results"][key] = {
                            "state": "registered",
                            "id": existing.id,
                            "title": item["title"],
                        }
                        continue
                    db.add(record)
                    db.flush()
                    record_id = record.id
                    plan["results"][key] = {
                        "state": "created",
                        "id": record_id,
                        "title": item["title"],
                        "dispatched": False,
                        "task_id": uuid4().hex,
                    }
                    update_plan(db, row, plan)
                    db.commit()  # Creation and retry identity are atomic.
                result = plan["results"][key]
                task = sync_youtube_playlist if item["kind"] == "sync" else resolve_url
                task.apply_async(
                    args=[record_id], task_id=result["task_id"], retry=False
                )
                result["dispatched"] = True
                result.pop("error", None)
            except Exception as exc:
                db.rollback()
                result = plan["results"].get(
                    key, {"state": "error", "title": item["title"]}
                )
                result["error"] = "追加またはキュー登録に失敗しました。再試行できます。"
                plan["results"][key] = result
            update_plan(db, row, plan)
            db.commit()
        plan["complete"] = all(
            r["state"] in ("created", "registered", "duplicate") and not r.get("error")
            for r in plan["results"].values()
        )
        update_plan(db, row, plan)
        db.commit()
        return {"results": plan["results"], "complete": plan["complete"]}
    finally:
        value.release()


@router.get("/issues")
def issues(db: Session = Depends(get_db)):
    return recovery.groups(db)


@router.post("/issues/{category}/retry")
def retry_issues(category: str, db: Session = Depends(get_db)):
    if category not in recovery.LABELS:
        raise HTTPException(404, "対象がありません")
    return recovery.retry_category(db, category)


@router.post("/issues/unavailable/skip")
def skip_unavailable(db: Session = Depends(get_db)):
    count = 0
    for item in recovery.members(db):
        if item["category"] != "unavailable":
            continue
        if item["kind"] == "track":
            track = db.get(PlaylistSyncTrack, item["id"])
            track.excluded = True
            track.status = "skipped"
            sync_history.record(
                db,
                track.playlist_sync_id,
                "skip",
                tracks=[{"id": track.id, "title": track.title}],
            )
            count += 1
        elif item["kind"] == "job":
            db.get(DownloadJob, item["id"]).status = "skipped"
            count += 1
    db.commit()
    return {"skipped": count}


@router.get("/syncs/{sync_id}/history")
def history(
    sync_id: int,
    retained_offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    require_sync(db, sync_id)
    events = (
        db.query(SyncEvent)
        .filter_by(sync_id=sync_id)
        .order_by(SyncEvent.id.desc())
        .limit(100)
        .all()
    )
    rows = db.query(PlaylistSyncTrack).filter_by(playlist_sync_id=sync_id).all()
    retained = [
        {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "excluded": t.excluded,
            "file_retained": sync_history.retained(t),
            "removed_at": t.removed_at.replace(tzinfo=timezone.utc)
            if t.removed_at
            else None,
            "expires_at": t.removed_at.replace(tzinfo=timezone.utc)
            + timedelta(days=sync_history.retention_days(db))
            if t.removed_at
            else None,
        }
        for t in rows
        if t.status == "removed" or t.excluded or t.keep_local
    ]
    summaries = []
    for event in events:
        details = json.loads(event.details)
        for name in ("added", "removed", "tracks"):
            if name in details:
                details[name + "_count"] = len(details[name])
                details[name] = details[name][:100]
        summaries.append(
            {
                "id": event.id,
                "kind": event.kind,
                "created_at": event.created_at.replace(tzinfo=timezone.utc)
                if event.created_at.tzinfo is None
                else event.created_at,
                "details": details,
            }
        )
    return {
        "events": summaries,
        "retained": retained[retained_offset : retained_offset + 200],
        "retained_total": len(retained),
        "retained_offset": retained_offset,
        "has_more": retained_offset + 200 < len(retained),
        "retention_days": sync_history.retention_days(db),
    }


@router.post("/syncs/{sync_id}/tracks/{track_id}/restore")
def restore_track(sync_id: int, track_id: int, db: Session = Depends(get_db)):
    require_sync(db, sync_id)
    value = lock(db, "playlist-track", track_id)
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        if track is None or track.playlist_sync_id != sync_id:
            raise HTTPException(404, "トラックが見つかりません")
        if track.status not in ("removed", "skipped") and not track.excluded:
            raise HTTPException(409, "このトラックは復元対象ではありません")
        track.excluded = False
        track.keep_local = True
        track.removed_at = None
        track.status = "complete" if sync_history.retained(track) else "pending"
        track.error_message = None
        sync_history.record(
            db, sync_id, "restore", tracks=[{"id": track.id, "title": track.title}]
        )
        db.commit()
        pending = track.status == "pending"
    finally:
        value.release()
    if pending:
        from app.tasks.sync_playlist import enqueue_playlist_track

        enqueue_playlist_track(db, track, manual=True)
    return {"restored": True, "redownload": pending}


@router.get("/syncs/{sync_id}/delivery")
async def sync_delivery(sync_id: int, db: Session = Depends(get_db)):
    return await delivery.readiness(db, require_sync(db, sync_id))


@router.post("/jobs/{job_id}/restore")
def restore_job(job_id: int, db: Session = Depends(get_db)):
    from app.api.queue import retry_job

    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(404, "対象が見つかりません")
    if job.status != "skipped":
        raise HTTPException(409, "この処理は除外されていません")
    retry_job(job_id, db)
    return {"restored": True}


@router.post("/syncs/{sync_id}/tracks/{track_id}/release")
def release_retained(sync_id: int, track_id: int, db: Session = Depends(get_db)):
    require_sync(db, sync_id)
    value = lock(db, "playlist-track", track_id)
    try:
        track = db.get(PlaylistSyncTrack, track_id)
        if track is None or track.playlist_sync_id != sync_id:
            raise HTTPException(404, "トラックが見つかりません")
        if not track.keep_local:
            raise HTTPException(409, "このトラックは保持対象ではありません")
        track.keep_local = False
        sync_history.record(
            db, sync_id, "release", tracks=[{"id": track.id, "title": track.title}]
        )
        db.commit()
    finally:
        value.release()
    return {"released": True}
