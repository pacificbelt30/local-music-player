# データベース仕様

SQLite を使用し、SQLAlchemy 2.0+ の Mapped 型アノテーションで定義されます。`init_db()` 呼び出し時に `Base.metadata.create_all()` でスキーマを自動生成します。

## テーブル一覧

| テーブル名 | 説明 |
|-----------|------|
| `url_sources` | 登録済み YouTube URL |
| `download_jobs` | ダウンロードジョブ |
| `tracks` | ダウンロード済みトラック |
| `playlist_tracks` | URL ソースとトラックの中間テーブル |
| `youtube_oauth_tokens` | YouTube OAuth2 トークン |
| `youtube_playlist_syncs` | YouTube プレイリスト同期設定 |
| `playlist_sync_tracks` | 同期プレイリストの個別トラック |
| `app_settings` | アプリケーション設定 KV ストア |

---

## `url_sources`

YouTube の動画・プレイリスト・チャンネル URL を管理します。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `url` | TEXT UNIQUE | YouTube URL（重複不可） |
| `url_type` | VARCHAR(20) | `video` / `playlist` / `channel` |
| `audio_format` | VARCHAR(10) | `mp3` / `flac` / `aac` / `ogg`（デフォルト: `mp3`） |
| `audio_quality` | VARCHAR(10) | `192` / `320` / `best`（デフォルト: `192`） |
| `title` | TEXT | プレイリスト・チャンネル名（ワーカーが解決後に設定） |
| `added_at` | DATETIME | 登録日時 |
| `last_synced` | DATETIME | 最終同期日時 |
| `sync_enabled` | BOOLEAN | 定期同期の有効/無効（デフォルト: `true`） |

**リレーション**

- `jobs` → `download_jobs`（1:N、カスケード削除）
- `playlist_tracks` → `playlist_tracks`（1:N、カスケード削除）

---

## `download_jobs`

ダウンロードキューの各ジョブを管理します。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `url_source_id` | INTEGER FK | `url_sources.id`（削除時カスケード） |
| `youtube_id` | VARCHAR(20) UNIQUE | YouTube 動画 ID |
| `status` | VARCHAR(20) | `pending` / `downloading` / `complete` / `failed` / `skipped` |
| `progress_pct` | FLOAT | 進捗率（0.0〜100.0） |
| `celery_task_id` | VARCHAR(64) | Celery タスク ID（キャンセル用） |
| `error_message` | TEXT | エラー時のメッセージ（最大 500 文字） |
| `created_at` | DATETIME | 作成日時 |
| `started_at` | DATETIME | 開始日時 |
| `finished_at` | DATETIME | 完了日時 |

---

## `tracks`

ダウンロード済み音声ファイルのメタデータを管理します。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `youtube_id` | VARCHAR(20) UNIQUE | YouTube 動画 ID |
| `title` | TEXT | 曲タイトル |
| `artist` | TEXT | アーティスト名（YouTube uploader） |
| `album` | TEXT | アルバム名（プレイリスト名） |
| `duration_secs` | INTEGER | 再生時間（秒） |
| `file_path` | TEXT | 音声ファイルの絶対パス |
| `file_format` | VARCHAR(10) | `mp3` / `flac` / `aac` / `ogg` |
| `file_size_bytes` | INTEGER | ファイルサイズ（バイト） |
| `thumbnail_path` | TEXT | サムネイル画像の絶対パス |
| `added_at` | DATETIME | 追加日時 |
| `last_played_at` | DATETIME | 最終再生日時 |
| `play_count` | INTEGER | 再生回数（デフォルト: 0） |

---

## `playlist_tracks`

`url_sources` と `tracks` の多対多中間テーブルです。

| カラム | 型 | 説明 |
|--------|-----|------|
| `url_source_id` | INTEGER PK,FK | `url_sources.id` |
| `track_id` | INTEGER PK,FK | `tracks.id` |
| `position` | INTEGER | プレイリスト内の順序 |

**制約**: `(url_source_id, track_id)` の複合ユニーク

---

## `youtube_oauth_tokens`

Google OAuth2 のアクセストークンを保存します（1 レコードのみ使用）。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `access_token` | TEXT | アクセストークン |
| `refresh_token` | TEXT | リフレッシュトークン |
| `token_expiry` | DATETIME | アクセストークンの有効期限 |
| `scope` | TEXT | 付与されたスコープ |
| `created_at` | DATETIME | 作成日時 |
| `updated_at` | DATETIME | 更新日時 |

---

## `youtube_playlist_syncs`

YouTube プレイリストの自動同期設定を管理します。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `playlist_id` | VARCHAR(64) UNIQUE | YouTube プレイリスト ID |
| `playlist_name` | TEXT | プレイリスト名 |
| `audio_format` | VARCHAR(10) | `mp3` / `flac` / `aac` / `ogg`（デフォルト: `mp3`） |
| `audio_quality` | VARCHAR(10) | `192` / `320` / `best`（デフォルト: `192`） |
| `enabled` | BOOLEAN | 有効/無効（デフォルト: `true`） |
| `last_synced` | DATETIME | 最終同期日時 |
| `created_at` | DATETIME | 作成日時 |

**リレーション**: `tracks` → `playlist_sync_tracks`（1:N、カスケード削除）

---

## `playlist_sync_tracks`

YouTube プレイリスト同期設定に紐づく個別トラックを管理します。

| カラム | 型 | 説明 |
|--------|-----|------|
| `id` | INTEGER PK | 自動採番 |
| `playlist_sync_id` | INTEGER FK | `youtube_playlist_syncs.id` |
| `youtube_id` | VARCHAR(20) | YouTube 動画 ID |
| `title` | TEXT | 曲タイトル |
| `artist` | TEXT | アーティスト名 |
| `duration_secs` | INTEGER | 再生時間（秒） |
| `position` | INTEGER | プレイリスト内の順序 |
| `status` | VARCHAR(20) | `pending` / `downloading` / `complete` / `failed` / `removed` |
| `file_path` | TEXT | 音声ファイルの絶対パス |
| `file_format` | VARCHAR(10) | ファイルフォーマット |
| `file_size_bytes` | INTEGER | ファイルサイズ |
| `thumbnail_path` | TEXT | サムネイル画像パス |
| `error_message` | TEXT | エラーメッセージ |
| `added_at` | DATETIME | 追加日時 |
| `downloaded_at` | DATETIME | ダウンロード完了日時 |

**制約**: `(playlist_sync_id, youtube_id)` の複合ユニーク

---

## `app_settings`

アプリケーション設定の KV ストアです。

| カラム | 型 | 説明 |
|--------|-----|------|
| `key` | VARCHAR(64) PK | 設定キー |
| `value` | TEXT | 設定値 |
| `updated_at` | DATETIME | 更新日時 |

**使用キー**

| キー | デフォルト | 説明 |
|------|-----------|------|
| `url_sync_interval_minutes` | `60` | URL ソース再解決の間隔（分）、`0` で無効 |
| `youtube_sync_interval_minutes` | `60` | YouTube プレイリスト同期の間隔（分）、`0` で無効 |
| `url_sync_last_run` | — | URL 同期の最終実行日時（ISO 形式） |
| `youtube_sync_last_run` | — | YouTube 同期の最終実行日時（ISO 形式） |
