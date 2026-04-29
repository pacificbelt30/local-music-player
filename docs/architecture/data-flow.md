# データフロー

## 1. URL 登録からダウンロードまで

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant API as FastAPI
    participant DB as SQLite
    participant Q as Redis
    participant W as Celery Worker
    participant YT as yt-dlp

    User->>API: POST /api/v1/urls<br>{url, audio_format, audio_quality}
    API->>DB: UrlSource レコード作成
    API->>Q: resolve_url.apply_async([source.id])

    Q->>W: resolve_url タスク
    W->>YT: --extract-flat（動画IDリスト取得）
    YT-->>W: 動画IDリスト
    W->>DB: UrlSource.url_type・title を更新
    W->>DB: DownloadJob を各動画に作成
    W->>Q: download_track.apply_async（各ジョブ）

    loop 各動画
        Q->>W: download_track タスク
        W->>YT: bestaudio ダウンロード → FFmpeg 変換
        YT-->>W: 音声ファイル + メタデータ
        W->>DB: Track レコード upsert
        W->>Q: job:{id}:progress を更新
    end

    User->>API: GET /api/v1/queue/events（SSE）
    API-->>User: 進捗イベント（1秒ごと）
```

---

## 2. YouTube プレイリスト同期フロー

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant API as FastAPI
    participant DB as SQLite
    participant Q as Redis
    participant W as Celery Worker
    participant YT as YouTube API

    User->>API: GET /api/v1/youtube/auth/url
    API-->>User: Google OAuth 同意画面 URL
    User->>API: GET /api/v1/youtube/auth/callback?code=...
    API->>DB: YouTubeOAuthToken を保存

    User->>API: GET /api/v1/youtube/playlists
    API-->>User: プレイリスト一覧
    User->>API: POST /api/v1/youtube/syncs<br>{playlist_id, audio_format}
    API->>DB: YoutubePlaylistSync 作成
    API->>Q: sync_youtube_playlist.apply_async([sync.id])

    Q->>W: sync_youtube_playlist タスク
    W->>YT: get_playlist_items（アクセストークンで取得）
    YT-->>W: 動画リスト
    W->>DB: PlaylistSyncTrack と差分比較
    W->>Q: download_playlist_sync_track（新規・復活トラック）

    Note over W,Q: Celery Beat が 5 分ごとに<br>periodic_youtube_playlist_sync を実行
```

---

## 3. 音楽再生フロー

```mermaid
sequenceDiagram
    actor User as ブラウザ
    participant API as FastAPI
    participant DB as SQLite
    participant FS as Filesystem

    User->>API: GET /api/v1/tracks?search=...
    API->>DB: Track テーブルを検索
    DB-->>API: トラック一覧
    API-->>User: stream_url / thumbnail_url を含むレスポンス

    User->>API: GET /api/v1/stream/{track_id}<br>Range: bytes=...（シーク）
    API->>FS: Track.file_path からファイル読み込み
    FS-->>API: バイトデータ
    API-->>User: 206 Partial Content（範囲レスポンス）
    API->>DB: play_count++ / last_played_at を更新
```

---

## 4. Syncthing 同期フロー

```mermaid
graph LR
    W["Celery Worker"] -->|"downloads/{artist}/{title}.mp3"| FS["Filesystem"]
    FS -->|"ファイル変更を検知"| ST["Syncthing デーモン"]
    ST -->|"差分を転送"| Mobile["モバイル端末の Syncthing"]
    Mobile -->|"保存"| MusicApp["音楽プレイヤーアプリ"]
```

---

## 状態遷移

### DownloadJob

```mermaid
stateDiagram-v2
    [*] --> pending : ジョブ作成
    pending --> downloading : ワーカーが取得
    downloading --> complete : ダウンロード成功
    downloading --> failed : エラー発生
    failed --> pending : リトライ
    downloading --> skipped : 重複検出
```

| 状態 | 説明 |
|------|------|
| `pending` | キュー待ち |
| `downloading` | yt-dlp ダウンロード中 |
| `complete` | 完了（Track レコードあり） |
| `failed` | エラー（`error_message` に詳細） |
| `skipped` | 重複等でスキップ |

### PlaylistSyncTrack

```mermaid
stateDiagram-v2
    [*] --> pending : トラック追加
    pending --> downloading : ワーカーが取得
    downloading --> complete : ダウンロード成功
    downloading --> failed : エラー発生
    complete --> removed : プレイリストから削除
    pending --> removed : プレイリストから削除
```
