# データフロー

## 1. URL 登録からダウンロードまで

```
ユーザー
  │ POST /api/v1/urls  { url, audio_format, audio_quality }
  ▼
FastAPI: urls.py
  │ UrlSource レコード作成 (url_type="video" 仮置き)
  │ resolve_url.apply_async([source.id])
  ▼
Celery Worker: tasks/download.py::resolve_url
  │ ytdlp_service.resolve_url(url)
  │   └─ yt-dlp --extract-flat で動画 ID リストを取得
  │ UrlSource.url_type・title を更新
  │ 各 youtube_id に DownloadJob 作成
  │ download_track.apply_async([job.id]) を各 job に投入
  ▼
Celery Worker: tasks/download.py::download_track
  │ DownloadJob.status = "downloading"
  │ ytdlp_service.download_track(youtube_id, format, quality)
  │   ├─ yt-dlp で bestaudio をダウンロード
  │   ├─ FFmpeg で指定フォーマットに変換
  │   ├─ サムネイル・info.json を保存
  │   └─ metadata dict を返す
  │ Track レコードを upsert
  │ PlaylistTrack リンクを作成
  │ DownloadJob.status = "complete"
  │ Redis: job:{id}:progress キーを削除
  ▼
ブラウザ (SSE)
  GET /api/v1/queue/events
  └─ 1 秒ごとに pending/downloading ジョブをポーリング
     Redis から最新進捗を読み取り → JSON イベント送信
```

## 2. YouTube プレイリスト同期フロー

```
ユーザー
  │ Google OAuth 認証 → GET /api/v1/youtube/auth/url
  │ リダイレクト → Google OAuth 同意画面
  │ コールバック → GET /api/v1/youtube/auth/callback?code=...
  │ YouTubeOAuthToken をDBに保存
  ▼
ユーザー
  │ GET /api/v1/youtube/playlists  (アカウントのプレイリスト一覧)
  │ POST /api/v1/youtube/syncs  { playlist_id, audio_format, ... }
  │ YoutubePlaylistSync 作成
  │ sync_youtube_playlist.apply_async([sync.id])
  ▼
Celery Worker: tasks/sync_playlist.py::sync_youtube_playlist
  │ youtube_api_service.get_fresh_access_token(db)
  │   └─ トークンが期限切れなら refresh_token で再取得
  │ youtube_api_service.get_playlist_items(playlist_id, token)
  │ DB の PlaylistSyncTrack と差分比較
  │   ├─ 新規: PlaylistSyncTrack 作成 → download_playlist_sync_track.apply_async
  │   ├─ 復活: status="pending" に戻す → download_playlist_sync_track.apply_async
  │   └─ 削除: ファイル削除 → status="removed"
  ▼
Celery Worker: tasks/sync_playlist.py::download_playlist_sync_track
  │ ytdlp_service.download_track(..., base_path=playlists/{playlist_id}/)
  │ PlaylistSyncTrack を complete に更新

─ 定期実行 ─────────────────────────────────────
Celery Beat (5 分ごと)
  ├─ periodic_playlist_refresh
  │   └─ playlist/channel 型 UrlSource を再 resolve
  └─ periodic_youtube_playlist_sync
      └─ 有効な YoutubePlaylistSync を再同期
```

## 3. 音楽再生フロー

```
ブラウザ
  │ GET /api/v1/tracks?search=...  (ライブラリ検索)
  ▼
FastAPI: api/tracks.py
  │ Track テーブルを検索
  │ stream_url / thumbnail_url / download_url を生成して返す
  ▼
ブラウザ (Audio 要素)
  │ GET /api/v1/stream/{track_id}
  │   Range: bytes=... ヘッダー付きでシーク
  ▼
FastAPI: api/stream.py
  │ Track.file_path からファイルを読み込み
  │ Range リクエスト: 206 Partial Content で部分レスポンス
  │ 通常リクエスト: 200 で全体をストリーミング
  │ Track.play_count++ / last_played_at を更新
  └─ audio/mpeg 等の Content-Type で返却
```

## 4. Syncthing 同期フロー

```
Celery Worker
  └─ downloads/{artist}/{title}.{ext} に保存
       │
       ▼（Syncthing が監視）
  Syncthing デーモン
       │ フォルダ差分を検出
       ▼
  モバイル端末の Syncthing
       └─ ファイルを受信・保存
```

## 状態遷移: DownloadJob

```
pending ──→ downloading ──→ complete
              │
              └──→ failed ──→ (retry) ──→ pending
                   │
                   └──→ skipped
```

| 状態 | 説明 |
|------|------|
| `pending` | キュー待ち |
| `downloading` | yt-dlp ダウンロード中 |
| `complete` | ダウンロード完了、Track レコードあり |
| `failed` | エラー発生（`error_message` に詳細） |
| `skipped` | 重複等でスキップ |

## 状態遷移: PlaylistSyncTrack

```
pending ──→ downloading ──→ complete
              │
              └──→ failed
                
(プレイリストから削除された場合)
any ──→ removed
```
