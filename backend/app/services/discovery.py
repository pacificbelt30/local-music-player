"""Bounded discovery and explicit source lookup. No downloads are started here."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import re
from urllib.parse import quote

import httpx
import redis
from redis.exceptions import RedisError, LockError

from app.config import settings
from app.models import AppSetting
from app.services.discovery_config import (
    REGIONS,
    api_key,
    read_config,
    DiscoveryConfigurationError,
)

_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
DAILY_LIMIT = 100  # This feature's own budget, separate from the provider's quota.
CACHE_HOURS = 6
MAX_STALE_HOURS = 24


class _HideLastfmKey(logging.Filter):
    def filter(self, record):
        if "api_key=" in record.getMessage():
            record.msg = re.sub(
                r'(api_key=)[^&\s"\']+', r"\1[redacted]", record.getMessage()
            )
            record.args = ()
        return True


# HTTPX logs request URLs at INFO. Last.fm's documented read API puts the key
# in the query, so redact it before any handler sees the log record.
logging.getLogger("httpx").addFilter(_HideLastfmKey())


class DiscoveryError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def now():
    return datetime.now(timezone.utc)


def _request(provider, key, region, kind, artist="", track="", check=False):
    if kind == "source" and provider == "lastfm":
        from app.services.ytdlp_service import resolve_lastfm_track

        try:
            return {"youtube_url": resolve_lastfm_track(artist, track)}, {}
        except Exception:
            raise DiscoveryError(
                "source_unavailable",
                "Last.fmの曲に紐づく動画を確認できませんでした。「YouTubeで探す」から取得先を選べます。",
            ) from None
    headers = {"User-Agent": "SyncTuneHub/0.1 (music discovery)"}
    if provider == "youtube":
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "id" if check else "snippet",
            "chart": "mostPopular",
            "regionCode": region,
            "videoCategoryId": "10",
            "maxResults": 1 if check else 50,
        }
        headers["X-Goog-Api-Key"] = key
    else:
        url = "https://ws.audioscrobbler.com/2.0/"
        params = {
            "api_key": key,
            "format": "json",
            "limit": 1 if check else 20 if kind == "similar" else 50,
        }
        if kind == "similar":
            params.update(
                method="track.getSimilar", artist=artist, track=track, autocorrect="1"
            )
        else:
            params.update(method="geo.getTopTracks", country=REGIONS[region])
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10, connect=5), follow_redirects=False
        ) as client:
            response = client.get(url, params=params, headers=headers)
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = None
        if response.status_code == 429:
            raise DiscoveryError(
                "rate_limited",
                "提供元の呼出し上限に達しました。時間をおいて再試行してください。",
            )
        if provider == "youtube" and response.status_code in (400, 401, 403):
            reasons = (
                [
                    e.get("reason")
                    for e in (data or {}).get("error", {}).get("errors", [])
                    if isinstance(e, dict)
                ]
                if isinstance(data, dict) and isinstance(data.get("error"), dict)
                else []
            )
            if any(
                r in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")
                for r in reasons
            ):
                raise DiscoveryError(
                    "quota_exceeded",
                    "YouTubeの利用上限に達しました。割当が回復してから再試行してください。",
                )
            if "videoChartNotFound" in reasons:
                raise DiscoveryError(
                    "unsupported_region",
                    "この地域の音楽動画チャートは取得できません。地域を変更してください。",
                )
            raise DiscoveryError(
                "key_rejected",
                "APIキー、APIの有効化、キーの利用制限を設定画面で確認してください。",
            )
        if response.status_code != 200:
            raise DiscoveryError(
                "unavailable",
                "提供元に接続できません。時間をおいて再試行してください。",
            )
        if not isinstance(data, dict):
            raise DiscoveryError(
                "invalid_response",
                "提供元の応答を読み取れません。時間をおいて再試行してください。",
            )
        if provider == "lastfm" and data.get("error") is not None:
            code = str(data["error"])
            if code in ("10", "26"):
                raise DiscoveryError(
                    "key_rejected", "Last.fmのAPIキーを確認してください。"
                )
            if code == "29":
                raise DiscoveryError(
                    "rate_limited",
                    "Last.fmの呼出し上限に達しました。時間をおいて再試行してください。",
                )
            if code == "6" and kind == "similar":
                raise DiscoveryError(
                    "not_found",
                    "曲が見つかりません。曲名とアーティスト名を確認してください。",
                )
            raise DiscoveryError(
                "unavailable",
                "Last.fmから情報を取得できません。時間をおいて再試行してください。",
            )
        return data, response.headers
    except httpx.RequestError:
        # Never expose upstream exception messages/URLs: they may contain keys.
        raise DiscoveryError(
            "unavailable", "提供元に接続できません。通信状態を確認してください。"
        ) from None


def _text(value, limit=300):
    return value[:limit] if isinstance(value, str) else ""


def _items(provider, data, kind):
    if provider == "youtube":
        values = data.get("items")
    else:
        container = data.get(
            "similartracks"
            if kind == "similar"
            else "tracks"
            if "tracks" in data
            else "toptracks"
        )
        values = container.get("track") if isinstance(container, dict) else None
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        raise DiscoveryError(
            "invalid_response",
            "提供元の応答形式が変わった可能性があります。前回の情報を保持します。",
        )
    result, seen = [], set()
    for value in values[:50]:
        if not isinstance(value, dict):
            continue
        if provider == "youtube":
            video_id = value.get("id", "")
            if not isinstance(video_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{11}", video_id
            ):
                continue
            snippet = value.get("snippet")
            if not isinstance(snippet, dict):
                continue
            title = _text(snippet.get("title"))
            artist = _text(snippet.get("channelTitle"), 160)
            item = {
                "id": video_id,
                "title": title,
                "artist": artist,
                "artist_label": "投稿者",
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "youtube_id": video_id,
                "rank": None,
            }
        else:
            title = _text(value.get("name"))
            artist_value = value.get("artist")
            artist = _text(
                artist_value.get("name")
                if isinstance(artist_value, dict)
                else artist_value,
                160,
            )
            item_id = sha256((artist + "\0" + title).encode()).hexdigest()[:24]
            rank = (
                value.get("@attr", {}).get("rank")
                if isinstance(value.get("@attr"), dict)
                else None
            )
            rank = (
                int(rank)
                if isinstance(rank, (int, str))
                and str(rank).isdigit()
                and 0 < int(rank) < 10000
                else None
            )
            item = {
                "id": item_id,
                "title": title,
                "artist": artist,
                "artist_label": "アーティスト",
                "url": f"https://www.last.fm/music/{quote(artist, safe='')}/_/{quote(title, safe='')}",
                "youtube_id": None,
                "rank": rank if kind == "popular" else None,
            }
        if title and item["id"] not in seen:
            result.append(item)
            seen.add(item["id"])
    if values and not result:
        raise DiscoveryError(
            "invalid_response", "曲情報を読み取れません。前回の情報を保持します。"
        )
    return result


def _cache_policy(provider, headers, fetched):
    expires = fetched + timedelta(hours=CACHE_HOURS)
    stale = fetched + timedelta(hours=MAX_STALE_HOURS)
    if provider == "lastfm":
        control = headers.get("cache-control", "").lower()
        if any(flag in control for flag in ("no-store", "no-cache")):
            return fetched, fetched, False
        match = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)', control)
        if match:
            age = headers.get("age", "0")
            age = int(age) if str(age).isdigit() else 0
            expires = min(
                expires, fetched + timedelta(seconds=max(0, int(match.group(1)) - age))
            )
            stale = expires  # Do not extend an explicit upstream cache lifetime.
    return expires, stale, True


def _base(provider, config, kind):
    return {
        "provider": provider,
        "region": config["region"],
        "kind": kind,
        "source_url": "https://www.youtube.com/"
        if provider == "youtube"
        else "https://www.last.fm/charts",
        "source_label": "YouTubeの人気音楽動画"
        if provider == "youtube"
        else "Last.fmの再生リンク"
        if kind == "source"
        else "Last.fmの類似曲"
        if kind == "similar"
        else "Last.fmの国別人気曲（先週）",
        "items": [],
        "fetched_at": None,
        "expires_at": None,
        "cached": False,
        "stale": False,
        "error_code": None,
        "message": "",
    }


def _read_cache(db, key, generation):
    row = db.get(AppSetting, key)
    if row:
        cached = json.loads(row.value)
        if cached["generation"] == generation:
            return cached
    return None


def _reserve_call(db, provider):
    key = "discovery:usage:" + provider + ":" + now().date().isoformat()
    row = db.get(AppSetting, key)
    count = int(row.value) if row else 0
    if count >= DAILY_LIMIT:
        raise DiscoveryError(
            "daily_budget",
            "この機能の1日あたりの呼出し上限（100回）に達しました。明日以降に再試行してください。",
        )
    if row:
        row.value = str(count + 1)
    else:
        db.add(AppSetting(key=key, value=str(count + 1)))
    db.commit()


def _store_cache(db, key, cached, provider):
    db.merge(AppSetting(key=key, value=json.dumps(cached, ensure_ascii=False)))
    db.flush()
    rows = (
        db.query(AppSetting)
        .filter(AppSetting.key.like("discovery:cache:" + provider + ":%"))
        .all()
    )
    rows.sort(key=lambda row: json.loads(row.value)["data"]["fetched_at"], reverse=True)
    size = 0
    for index, row in enumerate(rows):
        data = json.loads(row.value)
        size += len(row.value.encode())
        if (
            index >= 50
            or size > 20 * 1024 * 1024
            or datetime.fromisoformat(data["stale_until"]) <= now()
        ):
            db.delete(row)
    db.commit()


def fetch(
    db, provider, *, kind="popular", artist="", track="", force=False, check=False
):
    config = read_config(db, provider)
    base = _base(provider, config, kind)
    if not check and not config["enabled"]:
        return {
            **base,
            "state": "disabled",
            "message": "設定から有効にすると利用できます。",
        }
    if not config["key_ciphertext"]:
        return {
            **base,
            "state": "needs_configuration",
            "message": "設定画面でAPIキーを保存してください。",
        }
    identity = sha256(
        json.dumps([config["region"], kind, artist, track], ensure_ascii=False).encode()
    ).hexdigest()[:24]
    cache_key = f"discovery:cache:{provider}:{identity}"
    cached = _read_cache(db, cache_key, config["generation"]) if not check else None
    if (
        cached
        and not force
        and datetime.fromisoformat(cached["data"]["expires_at"]) > now()
    ):
        return {**cached["data"], "cached": True}
    lock = _redis.lock("discovery:fetch:" + provider, timeout=45, thread_local=False)
    acquired = False
    try:
        acquired = lock.acquire(blocking=False)
        if not acquired:
            raise DiscoveryError(
                "refreshing",
                "同じ提供元を確認中です。少し待ってから再試行してください。",
            )
        db.expire_all()
        fresh_config = read_config(db, provider)
        if fresh_config["generation"] != config["generation"]:
            raise DiscoveryError(
                "settings_changed", "設定が変更されました。もう一度取得してください。"
            )
        if not check:
            cached = _read_cache(db, cache_key, config["generation"])
            if (
                cached
                and not force
                and datetime.fromisoformat(cached["data"]["expires_at"]) > now()
            ):
                return {**cached["data"], "cached": True}
        token = api_key(config)
        # A provider-wide cooldown also applies to forced refreshes and tests.
        last = db.get(AppSetting, "discovery:last-call:" + provider)
        if last and (now() - datetime.fromisoformat(last.value)).total_seconds() < 2:
            raise DiscoveryError("cooldown", "続けての確認は少し間をあけてください。")
        _reserve_call(db, provider)
        db.merge(
            AppSetting(key="discovery:last-call:" + provider, value=now().isoformat())
        )
        db.commit()
        data, headers = _request(
            provider, token, config["region"], kind, artist, track, check
        )
        db.expire_all()
        if (
            read_config(db, provider)["generation"] != config["generation"]
            or not lock.owned()
        ):
            raise DiscoveryError(
                "settings_changed",
                "設定が変更されたため、取得結果は保存しませんでした。",
            )
        if check:
            if provider == "youtube":
                if not isinstance(data.get("items"), list):
                    raise DiscoveryError(
                        "invalid_response", "提供元の応答を確認できませんでした。"
                    )
            else:
                _items(provider, data, "popular")
            return {**base, "state": "ready", "message": "接続できました。"}
        items = [] if kind == "source" else _items(provider, data, kind)
        if kind == "source" and (
            not isinstance(data.get("youtube_url"), str)
            or not re.fullmatch(
                r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}",
                data["youtube_url"],
            )
        ):
            raise DiscoveryError("invalid_response", "取得先を確認できませんでした。")
        fetched = now()
        expires, stale, store = _cache_policy(provider, headers, fetched)
        result = {
            **base,
            "state": "ready",
            "items": items,
            "fetched_at": fetched.isoformat(),
            "expires_at": expires.isoformat(),
        }
        if kind == "source":
            result["youtube_url"] = data["youtube_url"]
        if store:
            _store_cache(
                db,
                cache_key,
                {
                    "generation": config["generation"],
                    "stale_until": stale.isoformat(),
                    "data": result,
                },
                provider,
            )
        db.expire_all()
        if read_config(db, provider)["generation"] != config["generation"]:
            raise DiscoveryError(
                "settings_changed",
                "設定が変更されたため、取得結果は表示しませんでした。",
            )
        return result
    except DiscoveryConfigurationError as exc:
        error = DiscoveryError("key_unavailable", str(exc))
    except DiscoveryError as exc:
        error = exc
    except RedisError:
        error = DiscoveryError(
            "unavailable",
            "更新用の接続を確認できません。少し待ってから再試行してください。",
        )
    finally:
        if acquired:
            try:
                lock.release()
            except (RedisError, LockError):
                pass
    db.expire_all()
    if read_config(db, provider)["generation"] != config["generation"]:
        return {
            **base,
            "state": "settings_changed",
            "message": "設定が変更されました。もう一度取得してください。",
        }
    if cached and datetime.fromisoformat(cached["stale_until"]) > now():
        return {
            **cached["data"],
            "state": "stale",
            "cached": True,
            "stale": True,
            "error_code": error.code,
            "message": error.message + " 前回取得した情報を表示しています。",
        }
    return {
        **base,
        "state": "error",
        "error_code": error.code,
        "message": error.message,
    }


def purge_expired(db):
    """Remove expired provider data even if nobody visits discovery again."""
    removed = 0
    for row in (
        db.query(AppSetting).filter(AppSetting.key.like("discovery:cache:%")).all()
    ):
        data = json.loads(row.value)
        if datetime.fromisoformat(data["stale_until"]) <= now():
            db.delete(row)
            removed += 1
    cutoff = (now() - timedelta(days=7)).date().isoformat()
    for row in (
        db.query(AppSetting).filter(AppSetting.key.like("discovery:usage:%")).all()
    ):
        if row.key.rsplit(":", 1)[-1] < cutoff:
            db.delete(row)
    db.commit()
    return removed
