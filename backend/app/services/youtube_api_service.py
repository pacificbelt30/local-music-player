"""YouTube Data API v3 + OAuth2 helpers (uses httpx, no google-auth dependency)."""
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import urlencode, urljoin
from typing import Any

import httpx

from app.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
# Full youtube scope (read + write) so the app can both list playlists and
# flip a playlist's privacy (private -> unlisted) for share-link based sync.
SCOPES = "https://www.googleapis.com/auth/youtube"


def get_auth_url() -> str:
    params = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": settings.youtube_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    return GOOGLE_AUTH_URL + "?" + urlencode(params)


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange auth code for access + refresh tokens."""
    resp = httpx.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "redirect_uri": settings.youtube_redirect_uri,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Use a refresh token to get a new access token."""
    resp = httpx.post(GOOGLE_TOKEN_URL, data={
        "refresh_token": refresh_token,
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()


def revoke_token(token: str) -> None:
    httpx.post(GOOGLE_REVOKE_URL, params={"token": token})


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def record_authorization(record, data, now, issued_here=True):
    """Only a newly issued refresh token starts a new refresh-token lifetime."""
    if data.get("refresh_token"):
        record.refresh_token = data["refresh_token"]
        record.authorized_at = now if issued_here else None
        seconds = data.get("refresh_token_expires_in")
        record.refresh_token_expiry = now + timedelta(seconds=seconds) if seconds is not None else None
        record.last_refresh_at = None
        record.refresh_error = None


def token_status(record):
    from app.schemas import YouTubeAuthStatus
    if not record:
        return YouTubeAuthStatus(authenticated=False)
    now = datetime.now(timezone.utc)
    expiry = utc(record.refresh_token_expiry)
    estimated = False
    if not expiry and record.refresh_token and record.authorized_at and settings.youtube_oauth_publish_status == "testing":
        expiry = utc(record.authorized_at) + timedelta(days=7)
        estimated = True
    access_expiry = utc(record.token_expiry)
    expired = bool(access_expiry and access_expiry <= now)
    if record.refresh_error in ("invalid_grant", "invalid_client", "unauthorized_client"):
        status = "reauth_required" if record.refresh_error == "invalid_grant" else "configuration_error"
    elif expiry and expiry <= now:
        verified_after_estimate = record.last_refresh_at and utc(record.last_refresh_at) >= expiry
        status = ("available" if verified_after_estimate else "check_required") if estimated else "reauth_required"
    elif not record.refresh_token:
        status = "reauth_required" if expired else "unavailable"
    elif not settings.youtube_client_id or not settings.youtube_client_secret:
        status = "configuration_error"
    elif record.refresh_error:
        status = "temporary_error"
    else:
        status = "available"
    return YouTubeAuthStatus(
        authenticated=True, scope=record.scope, access_token_expiry=access_expiry,
        access_token_expired=expired, refresh_token_set=bool(record.refresh_token),
        refresh_token_expiry=expiry, refresh_expiry_estimated=estimated,
        authorized_at=utc(record.authorized_at), last_refresh_at=utc(record.last_refresh_at),
        refresh_status=status, refresh_error=record.refresh_error,
    )


def get_fresh_access_token(db, force=False) -> str | None:
    """Refresh on API use; keep safe diagnostic metadata without exposing tokens."""
    from app.models import YouTubeOAuthToken
    record = db.query(YouTubeOAuthToken).first()
    if not record:
        return None
    now = datetime.now(timezone.utc)
    expiry = utc(record.token_expiry)
    if force or (expiry and now >= expiry - timedelta(minutes=5)):
        if not record.refresh_token:
            if force or (expiry and now >= expiry):
                return None
            return record.access_token
        try:
            data = refresh_access_token(record.refresh_token)
        except httpx.HTTPStatusError as exc:
            try:
                error = exc.response.json().get("error")
            except (ValueError, AttributeError):
                error = None
            # Store only known codes, never provider messages or token values.
            record.refresh_error = error if error in ("invalid_grant", "invalid_client", "unauthorized_client") else "temporary_error"
            db.commit()
            raise
        except httpx.RequestError:
            record.refresh_error = "temporary_error"
            db.commit()
            raise
        record.access_token = data["access_token"]
        if data.get("refresh_token"):
            record.refresh_token = data["refresh_token"]
        if "refresh_token_expires_in" in data:
            record.refresh_token_expiry = now + timedelta(seconds=data["refresh_token_expires_in"])
        record.token_expiry = now + timedelta(seconds=data.get("expires_in", 3600))
        record.last_refresh_at = now
        record.refresh_error = None
        db.commit()
    return record.access_token


def get_my_playlists(access_token: str) -> list[dict[str, Any]]:
    """Fetch all playlists belonging to the authenticated user (handles pagination)."""
    playlists = []
    page_token = None

    while True:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,status",
            "mine": "true",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = httpx.get(
            f"{YOUTUBE_API_BASE}/playlists",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            total_duration_secs = _get_playlist_total_duration(item["id"], access_token)
            playlists.append({
                "playlist_id": item["id"],
                "title": snippet.get("title", "Untitled"),
                "item_count": item.get("contentDetails", {}).get("itemCount", 0),
                "thumbnail_url": thumb_url,
                "total_duration_secs": total_duration_secs,
                "privacy_status": item.get("status", {}).get("privacyStatus"),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return playlists


def _get_playlist_total_duration(playlist_id: str, access_token: str) -> int | None:
    items = get_playlist_items(playlist_id, access_token)
    video_ids = [i["youtube_id"] for i in items if i.get("youtube_id")]
    if not video_ids:
        return None

    total = 0
    known = 0
    for idx in range(0, len(video_ids), 50):
        chunk = video_ids[idx:idx + 50]
        resp = httpx.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={"part": "contentDetails", "id": ",".join(chunk), "maxResults": 50},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        for video in data.get("items", []):
            duration = video.get("contentDetails", {}).get("duration")
            secs = _parse_iso8601_duration(duration)
            if secs is None:
                continue
            total += secs
            known += 1

    return total if known else None


def _parse_iso8601_duration(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    return h * 3600 + mins * 60 + secs


def get_playlist_items(playlist_id: str, access_token: str) -> list[dict[str, Any]]:
    """Fetch all video entries in a playlist (handles pagination)."""
    items = []
    page_token = None
    position = 0

    while True:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = httpx.get(
            f"{YOUTUBE_API_BASE}/playlistItems",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            resource = snippet.get("resourceId", {})
            video_id = resource.get("videoId")
            if not video_id:
                continue

            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            items.append({
                "youtube_id": video_id,
                "title": snippet.get("title", "Unknown"),
                "position": position,
                "thumbnail_url": thumb_url,
            })
            position += 1

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return items


def update_playlist_privacy(
    playlist_id: str, access_token: str, privacy_status: str = "unlisted"
) -> dict[str, Any]:
    """Change a playlist's privacy status (e.g. private -> unlisted).

    Requires a token with write access (the full ``youtube`` scope); a
    read-only token will get a 403 from the API. YouTube's playlists.update
    endpoint replaces the mutable playlist resource for the parts sent, so keep
    the existing snippet in the update body to avoid 400 errors from partial
    status-only updates.
    """
    get_resp = httpx.get(
        f"{YOUTUBE_API_BASE}/playlists",
        params={"part": "snippet,status", "id": playlist_id, "maxResults": 1},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    get_resp.raise_for_status()
    items = get_resp.json().get("items", [])
    if not items:
        raise ValueError("YouTube playlist not found")

    item = items[0]
    snippet = item.get("snippet") or {}
    resp = httpx.put(
        f"{YOUTUBE_API_BASE}/playlists",
        params={"part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "id": playlist_id,
            "snippet": {
                "title": snippet.get("title", "Untitled"),
                "description": snippet.get("description", ""),
            },
            "status": {"privacyStatus": privacy_status},
        },
    )
    resp.raise_for_status()
    return resp.json()
