"""Group failures by the action a person can take, without repeating one outage."""

from collections import defaultdict
import json
from pathlib import Path
from datetime import datetime, timezone

from app.models import (
    AppSetting,
    DownloadJob,
    PlaylistSyncTrack,
    YoutubePlaylistSync,
)

LABELS = {
    "intake": (
        "追加が完了していません",
        "画面を閉じた追加処理も、重複登録せずに再開できます。",
    ),
    "missing": (
        "保存済みファイルが見つかりません",
        "サーバーから消えた曲を再取得できます。",
    ),
    "auth": (
        "YouTubeへの再接続が必要です",
        "再接続後、対象の同期をまとめて再試行します。",
    ),
    "unavailable": (
        "取得できない動画があります",
        "削除・非公開・地域制限など。今後の取得から除外できます。",
    ),
    "network": (
        "通信が一時的に失敗しています",
        "自動再試行に加え、ここからまとめて再試行できます。",
    ),
    "configuration": (
        "接続や取得設定を確認してください",
        "設定を見直してから再試行してください。",
    ),
    "other": (
        "確認が必要な処理があります",
        "詳細を確認し、対象をまとめて再試行できます。",
    ),
}


def classify(message, api=False):
    text = (message or "").lower()
    if any(word in text for word in ("invalid_client", "unauthorized_client")):
        return "configuration"
    if api and any(
        word in text
        for word in ("invalid_grant", "認証", "token", "401", "unauthorized")
    ):
        return "auth"
    if any(
        word in text
        for word in (
            "video unavailable",
            "private video",
            "removed",
            "deleted",
            "copyright",
            "not available",
            "非公開",
            "削除済",
            "地域制限",
        )
    ):
        return "unavailable"
    if any(
        word in text
        for word in (
            "timed out",
            "timeout",
            "connection",
            "network",
            "503",
            "502",
            "429",
            "一時",
            "通信",
        )
    ):
        return "network"
    if any(
        word in text
        for word in (
            "invalid_client",
            "configuration",
            "not configured",
            "ffmpeg",
            "permission denied",
            "設定",
        )
    ):
        return "configuration"
    return "other"


def members(db):
    values = []
    syncs = {s.id: s for s in db.query(YoutubePlaylistSync).all()}
    for sync in syncs.values():
        if sync.last_error:
            values.append(
                {
                    "kind": "sync",
                    "id": sync.id,
                    "sync_id": sync.id,
                    "title": sync.playlist_name,
                    "category": classify(sync.last_error, sync.source_type == "api"),
                    "message": sync.last_error,
                }
            )
    for track in (
        db.query(PlaylistSyncTrack).filter_by(status="failed", excluded=False).all()
    ):
        sync = syncs.get(track.playlist_sync_id)
        if sync:
            values.append(
                {
                    "kind": "track",
                    "id": track.id,
                    "sync_id": sync.id,
                    "title": track.title,
                    "category": classify(track.error_message, False),
                    "message": track.error_message,
                }
            )
    for track in (
        db.query(PlaylistSyncTrack).filter_by(status="complete", excluded=False).all()
    ):
        if track.file_path and not Path(track.file_path).is_file():
            values.append(
                {
                    "kind": "track",
                    "id": track.id,
                    "sync_id": track.playlist_sync_id,
                    "title": track.title,
                    "category": "missing",
                    "message": "保存済みファイルが見つかりません",
                }
            )
    for job in db.query(DownloadJob).filter_by(status="failed").all():
        values.append(
            {
                "kind": "job",
                "id": job.id,
                "title": job.title or job.youtube_id,
                "category": classify(job.error_message),
                "message": job.error_message,
            }
        )
    now = datetime.now(timezone.utc)
    plans = db.query(AppSetting).filter(AppSetting.key.like("plan:%")).all()
    for plan in plans:
        try:
            data = json.loads(plan.value)
        except (ValueError, TypeError):
            continue
        if data.get("kind") != "intake" or data.get("complete"):
            continue
        outstanding = [
            value
            for value in data.get("results", {}).values()
            if value.get("state") == "created"
            and not value.get("dispatched")
            and value.get("retryable", True)
        ]
        old = (
            plan.updated_at is not None
            and (now - plan.updated_at.replace(tzinfo=timezone.utc)).total_seconds()
            > 120
        )
        if outstanding and (old or any(value.get("error") for value in outstanding)):
            values.append(
                {
                    "kind": "intake",
                    "id": plan.key.split(":", 1)[1],
                    "title": f"追加の再開（{len(outstanding)}件）",
                    "category": "intake",
                    "message": "登録後のキュー追加が完了していません。",
                }
            )
    return values


def groups(db):
    grouped = defaultdict(list)
    for item in members(db):
        grouped[item["category"]].append(item)
    result = [
        {
            "category": key,
            "title": LABELS[key][0],
            "description": LABELS[key][1],
            "count": len(items),
            "items": items,
            "can_skip": key == "unavailable",
        }
        for key, items in grouped.items()
    ]
    excluded = [
        {
            "kind": "track",
            "id": t.id,
            "sync_id": t.playlist_sync_id,
            "title": t.title,
            "message": "取得から除外中",
        }
        for t in db.query(PlaylistSyncTrack).filter_by(excluded=True).all()
    ]
    excluded += [
        {
            "kind": "job",
            "id": j.id,
            "title": j.title or j.youtube_id,
            "message": "取得から除外中",
        }
        for j in db.query(DownloadJob).filter_by(status="skipped").all()
    ]
    if excluded:
        result.append(
            {
                "category": "excluded",
                "title": "取得から除外中",
                "description": "必要になったら個別に復元できます。",
                "count": len(excluded),
                "items": excluded,
                "can_skip": False,
                "can_restore": True,
            }
        )
    return result


def retry_category(db, category, verify=True, manual=True):
    from app.services import youtube_api_service
    from app.tasks.sync_playlist import (
        sync_youtube_playlist,
        enqueue_playlist_track,
        _redis,
    )
    from app.api.queue import retry_job
    from fastapi import HTTPException

    selected = [item for item in members(db) if item["category"] == category]
    if category == "intake":
        from app.api.workspace import commit_intake, IntakeCommit
        import json

        queued, errors = 0, []
        for item in selected:
            plan = json.loads(db.get(AppSetting, "plan:" + item["id"]).value)
            pending = sum(
                value.get("state") == "created" and not value.get("dispatched")
                for value in plan["results"].values()
            )
            try:
                result = commit_intake(
                    IntakeCommit(token=item["id"], indices=plan["selection"]), db
                )
                remaining = sum(
                    value.get("state") == "created" and not value.get("dispatched")
                    for value in result["results"].values()
                )
                queued += max(0, pending - remaining)
            except Exception:
                db.rollback()
                errors.append({"kind": "intake", "id": item["id"]})
        return {"queued": queued, "waiting": 0, "errors": errors}

    if category == "auth" and verify:
        try:
            access = youtube_api_service.get_fresh_access_token(db, force=False)
        except Exception:
            access = None
        if not access:
            raise HTTPException(409, "設定画面からYouTubeへ再接続してください")
    queued, waiting, errors = 0, 0, []
    if not manual:
        enabled = {
            s.id for s in db.query(YoutubePlaylistSync).filter_by(enabled=True).all()
        }
        selected = [item for item in selected if item.get("sync_id") in enabled]
    sync_ids = {item["id"] for item in selected if item["kind"] == "sync"}
    for sync_id in sync_ids:
        try:
            sync_youtube_playlist.apply_async(args=[sync_id], kwargs={"manual": manual})
            queued += 1
        except Exception:
            errors.append({"kind": "sync", "id": sync_id})
    for item in selected:
        try:
            if item["kind"] == "track" and item["sync_id"] not in sync_ids:
                track = db.get(PlaylistSyncTrack, item["id"])
                if _redis.exists(f"lmp:playlist-track:{track.id}"):
                    waiting += 1
                    continue
                track.status = "pending"
                track.error_message = None
                db.commit()
                enqueue_playlist_track(db, track, manual=manual)
                queued += 1
            elif item["kind"] == "job":
                retry_job(item["id"], db)
                queued += 1
        except Exception:
            db.rollback()
            errors.append({"kind": item["kind"], "id": item["id"]})
    return {"queued": queued, "waiting": waiting, "errors": errors}


def resume_after_authorization(db):
    # Persisted failures remain visible if the broker is down; never hide them.
    try:
        return retry_category(db, "auth", verify=False, manual=False)
    except Exception:
        return {"queued": 0}
