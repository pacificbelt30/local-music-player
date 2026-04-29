# YouTube 連携 API

`/api/v1/youtube` — YouTube OAuth2 認証とプレイリスト同期を管理します。

## OAuth2 認証フロー

```
1. GET /api/v1/youtube/auth/url       → 認証 URL を取得
2. ブラウザを認証 URL にリダイレクト → Google OAuth 同意画面
3. GET /api/v1/youtube/auth/callback  → コールバック処理（トークン保存）
4. リダイレクト → /?youtube_auth=success
```

## エンドポイント一覧

### OAuth2 関連

#### GET `/api/v1/youtube/auth/url`

Google OAuth2 認証 URL を返します。

**レスポンス** `200 OK`

```json
{
  "url": "https://accounts.google.com/o/oauth2/auth?..."
}
```

**エラー**

| コード | 条件 |
|--------|------|
| `400` | `YOUTUBE_CLIENT_ID` が未設定 |

---

#### GET `/api/v1/youtube/auth/callback`

OAuth2 コールバック。認可コードをアクセストークンと交換し、`YouTubeOAuthToken` に保存します。

**クエリパラメータ**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `code` | string | ✓ | Google から受け取った認可コード |

**動作**

- 既存のトークンレコードがあれば更新、なければ新規作成
- `refresh_token` はレスポンスに含まれる場合のみ更新

**レスポンス** `302` → `/?youtube_auth=success`

---

#### GET `/api/v1/youtube/auth/status`

現在の認証状態を返します。

**レスポンス** `200 OK`

```json
{
  "authenticated": true,
  "scope": "https://www.googleapis.com/auth/youtube.readonly"
}
```

---

#### DELETE `/api/v1/youtube/auth`

認証を取り消し、トークンを削除します。

**動作**

1. Google のトークン無効化 API を呼び出す（失敗しても処理継続）
2. DB から `YouTubeOAuthToken` を削除

**レスポンス** `204 No Content`

---

### プレイリスト

#### GET `/api/v1/youtube/playlists`

認証済みアカウントのプレイリスト一覧を返します。

**レスポンス** `200 OK`

```json
[
  {
    "playlist_id": "PLxxxx",
    "title": "お気に入り",
    "thumbnail_url": "https://...",
    "item_count": 42
  }
]
```

**エラー**

| コード | 条件 |
|--------|------|
| `401` | YouTube 認証が完了していない |
| `502` | YouTube API エラー |

---

### 同期設定

#### GET `/api/v1/youtube/syncs`

設定済みの同期プレイリスト一覧を返します。

**レスポンス** `200 OK`

```json
[
  {
    "id": 1,
    "playlist_id": "PLxxxx",
    "playlist_name": "お気に入り",
    "audio_format": "mp3",
    "audio_quality": "192",
    "enabled": true,
    "last_synced": "2024-01-01T01:00:00",
    "created_at": "2024-01-01T00:00:00",
    "track_count": 40,
    "downloaded_count": 38
  }
]
```

---

#### POST `/api/v1/youtube/syncs` — 同期設定作成

**リクエストボディ**

```json
{
  "playlist_id": "PLxxxx",
  "playlist_name": "お気に入り",
  "audio_format": "mp3",
  "audio_quality": "192",
  "enabled": true
}
```

**動作**

- `enabled: true` の場合、即座に `sync_youtube_playlist` タスクを投入

**レスポンス** `201 Created`

**エラー**

| コード | 条件 |
|--------|------|
| `409` | 同じ `playlist_id` がすでに登録済み |

---

#### PATCH `/api/v1/youtube/syncs/{sync_id}` — 同期設定更新

`audio_format`・`audio_quality`・`enabled` を部分更新できます。

**レスポンス** `200 OK`

---

#### DELETE `/api/v1/youtube/syncs/{sync_id}` — 同期設定削除

**クエリパラメータ**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `delete_files` | boolean | `false` | `true` の場合、関連ファイルと `playlists/{playlist_id}/` ディレクトリを削除 |

**レスポンス** `204 No Content`

---

#### POST `/api/v1/youtube/syncs/{sync_id}/run` — 即時同期実行

同期タスクを即座に投入します。

**レスポンス** `202 Accepted`

```json
{ "queued": true }
```

**エラー**

| コード | 条件 |
|--------|------|
| `401` | YouTube 未認証 |

---

### 同期トラック

#### GET `/api/v1/youtube/syncs/{sync_id}/tracks`

同期プレイリストのトラック一覧（`removed` 以外）をプレイリスト順に返します。

**レスポンス** `200 OK`

```json
[
  {
    "id": 1,
    "youtube_id": "dQw4w9WgXcQ",
    "title": "Never Gonna Give You Up",
    "artist": "Rick Astley",
    "position": 0,
    "status": "complete",
    "file_format": "mp3",
    "thumbnail_url": "/api/v1/youtube/syncs/tracks/1/thumbnail",
    "stream_url": "/api/v1/youtube/syncs/tracks/1/stream"
  }
]
```

---

#### GET `/api/v1/youtube/syncs/tracks/{track_id}/stream`

同期トラックの音声をストリーミングします（Range リクエスト対応）。

---

#### GET `/api/v1/youtube/syncs/tracks/{track_id}/thumbnail`

同期トラックのサムネイル画像を返します。
