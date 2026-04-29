# トラックライブラリ API

`/api/v1/tracks` — ダウンロード済みトラックの検索・取得・編集・削除を提供します。

## レスポンス形式 (TrackResponse)

```json
{
  "id": 1,
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Never Gonna Give You Up",
  "artist": "Rick Astley",
  "album": null,
  "duration_secs": 213,
  "file_format": "mp3",
  "file_size_bytes": 5120000,
  "added_at": "2024-01-01T00:00:00",
  "last_played_at": null,
  "play_count": 0,
  "stream_url": "http://localhost:8000/api/v1/stream/1",
  "thumbnail_url": "http://localhost:8000/api/v1/thumbnails/1",
  "download_url": "http://localhost:8000/api/v1/files/1/download"
}
```

`stream_url`・`thumbnail_url`・`download_url` はリクエストのベース URL から動的に生成されます。

## エンドポイント

### GET `/api/v1/tracks` — トラック一覧・検索

**クエリパラメータ**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `search` | string | — | タイトルまたはアーティスト名で部分一致検索（大文字小文字区別なし） |
| `artist` | string | — | アーティスト名でフィルタ（部分一致） |
| `sort` | string | `added_at` | ソートカラム（`Track` の任意カラム名） |
| `limit` | integer | `50` | 最大取得件数 |
| `offset` | integer | `0` | スキップ件数（ページネーション） |

**動作**

- `search` と `artist` は AND 条件で組み合わせ可能
- ソートは指定カラムの降順

**レスポンス** `200 OK` — `TrackResponse` の配列

---

### GET `/api/v1/tracks/{track_id}` — トラック取得

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `track_id` | トラック ID |

**レスポンス** `200 OK` — `TrackResponse`

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID のトラックが存在しない |

---

### PATCH `/api/v1/tracks/{track_id}` — トラック更新

メタデータを部分更新します。

**リクエストボディ** (`TrackUpdate`)

```json
{
  "title": "新しいタイトル",
  "artist": "新しいアーティスト",
  "album": "アルバム名"
}
```

すべてのフィールドはオプションです。指定したフィールドのみ更新されます。

**レスポンス** `200 OK` — 更新後の `TrackResponse`

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID のトラックが存在しない |

---

### DELETE `/api/v1/tracks/{track_id}` — トラック削除

DB からトラックレコードを削除します。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `track_id` | トラック ID |

**クエリパラメータ**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `delete_file` | boolean | `false` | `true` の場合、音声ファイルとサムネイルもディスクから削除 |

**レスポンス** `204 No Content`

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID のトラックが存在しない |
