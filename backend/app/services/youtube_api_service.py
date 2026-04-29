"""YouTube Data API v3 + OAuth2 helpers (uses httpx, no google-auth dependency)."""
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urljoin
from typing import Any

import httpx

from app.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
SCOPES = "https://www.googleapis.com/auth/youtube.readonly"


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


def get_fresh_access_token(db) -> str | None:
    """Return a valid access token, refreshing if necessary. Returns None if not authenticated."""
    from app.models import YouTubeOAuthToken
    record = db.query(YouTubeOAuthToken).first()
    if not record:
        return None

    now = datetime.now(timezone.utc)
    expiry = record.token_expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry and now >= expiry - timedelta(minutes=5):
        data = refresh_access_token(record.refresh_token)
        record.access_token = data["access_token"]
        if "refresh_token" in data:
            record.refresh_token = data["refresh_token"]
        if "expires_in" in data:
            record.token_expiry = now + timedelta(seconds=data["expires_in"])
        db.commit()

    return record.access_token


def get_my_playlists(access_token: str) -> list[dict[str, Any]]:
    """Fetch all playlists belonging to the authenticated user (handles pagination)."""
    playlists = []
    page_token = None

    while True:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
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
            playlists.append({
                "playlist_id": item["id"],
                "title": snippet.get("title", "Untitled"),
                "item_count": item.get("contentDetails", {}).get("itemCount", 0),
                "thumbnail_url": thumb_url,
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return playlists


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
