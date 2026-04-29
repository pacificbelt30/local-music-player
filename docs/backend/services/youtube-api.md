# YouTube API サービス

`backend/app/services/youtube_api_service.py` — YouTube Data API v3 と OAuth2 を扱うクライアントです。

## 主な機能

| 関数 | 説明 |
|------|------|
| `get_auth_url()` | OAuth2 認証 URL を生成 |
| `exchange_code(code)` | 認可コードをトークンと交換 |
| `revoke_token(token)` | アクセストークンを無効化 |
| `get_fresh_access_token(db)` | 有効なアクセストークンを取得（期限切れなら自動更新） |
| `get_my_playlists(access_token)` | アカウントのプレイリスト一覧を取得 |
| `get_playlist_items(playlist_id, access_token)` | プレイリスト内の動画一覧を取得 |

## OAuth2 フロー

### `get_auth_url() -> str`

Google OAuth2 の認証 URL を生成します。

- スコープ: `https://www.googleapis.com/auth/youtube.readonly`
- `access_type=offline`（リフレッシュトークン取得のため）
- リダイレクト URI: `settings.youtube_redirect_uri`

### `exchange_code(code: str) -> dict`

Google のトークンエンドポイントに POST してトークンを取得します。

**返り値**

```python
{
    "access_token": "...",
    "refresh_token": "...",   # 初回のみ
    "expires_in": 3600,
    "scope": "...",
    "token_type": "Bearer",
}
```

### `revoke_token(access_token: str) -> None`

`https://oauth2.googleapis.com/revoke` にリクエストしてトークンを無効化します。

### `get_fresh_access_token(db: Session) -> str | None`

DB から `YouTubeOAuthToken` を取得し、有効期限を確認します。

- 期限切れの場合: `refresh_token` を使って新しいアクセストークンを取得し DB を更新
- トークンが存在しない場合: `None` を返す

## プレイリスト取得

### `get_my_playlists(access_token: str) -> list[dict]`

YouTube Data API v3 の `playlists.list` を呼び出し、全ページを結合して返します。

**返り値の各要素**

```python
{
    "playlist_id": "PLxxxx",
    "title": "お気に入り",
    "thumbnail_url": "https://...",
    "item_count": 42,
}
```

### `get_playlist_items(playlist_id: str, access_token: str) -> list[dict]`

YouTube Data API v3 の `playlistItems.list` を呼び出し、全ページを結合して返します。

**返り値の各要素**

```python
{
    "youtube_id": "dQw4w9WgXcQ",
    "title": "Never Gonna Give You Up",
    "position": 0,
}
```

削除済み・非公開動画（`youtube_id` が空）はフィルタリングされます。
