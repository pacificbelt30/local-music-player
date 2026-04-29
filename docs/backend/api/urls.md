# URL 管理 API

`/api/v1/urls` — YouTube URL の登録・一覧・削除を管理します。

## エンドポイント

### POST `/api/v1/urls` — URL 登録

YouTube URL を登録し、バックグラウンドで解決タスクを開始します。

**リクエストボディ**

```json
{
  "url": "https://www.youtube.com/watch?v=xxxx",
  "audio_format": "mp3",
  "audio_quality": "192",
  "sync_enabled": true
}
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `url` | string | ✓ | YouTube URL（動画・プレイリスト・チャンネル） |
| `audio_format` | string | — | `mp3` / `flac` / `aac` / `ogg`（デフォルト: `mp3`） |
| `audio_quality` | string | — | `192` / `320` / `best`（デフォルト: `192`） |
| `sync_enabled` | boolean | — | 定期同期の有効化（デフォルト: `true`） |

**レスポンス** `201 Created`

```json
{
  "id": 1,
  "url": "https://www.youtube.com/watch?v=xxxx",
  "url_type": "video",
  "audio_format": "mp3",
  "audio_quality": "192",
  "title": null,
  "added_at": "2024-01-01T00:00:00",
  "last_synced": null,
  "sync_enabled": true
}
```

**エラー**

| コード | 条件 |
|--------|------|
| `409` | 同じ URL がすでに登録済み |

**動作**

1. `UrlSource` レコードを `url_type="video"`（仮）で作成
2. `resolve_url` Celery タスクを非同期投入
3. ワーカーが URL を解決し、`url_type`・`title` を更新して各動画の `DownloadJob` を生成

---

### GET `/api/v1/urls` — URL 一覧

登録済み URL を登録日の新しい順に返します。

**レスポンス** `200 OK`

```json
[
  {
    "id": 1,
    "url": "https://www.youtube.com/playlist?list=xxxx",
    "url_type": "playlist",
    "audio_format": "mp3",
    "audio_quality": "192",
    "title": "My Playlist",
    "added_at": "2024-01-01T00:00:00",
    "last_synced": "2024-01-01T01:00:00",
    "sync_enabled": true
  }
]
```

---

### DELETE `/api/v1/urls/{url_id}` — URL 削除

URL ソースと、それに紐づくジョブ・プレイリストリンクを削除します。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `url_id` | URL ソース ID |

**クエリパラメータ**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `delete_files` | boolean | `false` | `true` の場合、関連する音声ファイルとサムネイルもディスクから削除 |

**レスポンス** `204 No Content`

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID の URL が存在しない |
