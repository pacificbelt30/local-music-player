# 環境設定リファレンス

`.env` ファイルまたは環境変数で設定できる全パラメータの一覧です。

## 設定の優先順位

1. 環境変数（最優先）
2. `.env` ファイル
3. コード内のデフォルト値

## 全設定項目

### Redis 設定

| 変数名 | デフォルト | 必須 | 説明 |
|--------|-----------|------|------|
| `REDIS_URL` | `redis://localhost:6379/0` | — | Celery ブローカー兼進捗キャッシュ用 Redis URL |
| `REDIS_RESULT_BACKEND` | `redis://localhost:6379/1` | — | Celery リザルトバックエンド用 Redis URL |

### データベース設定

| 変数名 | デフォルト | 必須 | 説明 |
|--------|-----------|------|------|
| `DATABASE_URL` | `sqlite:////.../data/music.db` | — | SQLAlchemy 接続 URL |

### ファイルパス設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `DOWNLOADS_PATH` | `.../downloads` | URL 経由ダウンロードの保存先 |
| `DATA_PATH` | `.../data` | DB ファイルの保存先 |
| `PLAYLISTS_PATH` | `.../playlists` | YouTube 同期プレイリストの保存先 |

Docker 環境では通常 `/downloads`・`/data`・`/playlists` にマウントします。

### Syncthing 設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `SYNCTHING_URL` | `http://localhost:8384` | Syncthing Web GUI / REST API の URL |
| `SYNCTHING_API_KEY` | `""` | Syncthing の API キー |
| `SYNCTHING_GUI_USER` | `""` | GUI Basic 認証ユーザー（必要時のみ） |
| `SYNCTHING_GUI_PASSWORD` | `""` | GUI Basic 認証パスワード（必要時のみ） |

`SYNCTHING_API_KEY` が空の場合、Syncthing 連携は無効になります。

### セキュリティ設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `ALLOWED_ORIGINS` | `[*]` | CORS 許可オリジン（カンマ区切り指定可） |
| `SECRET_TOKEN` | `""` | Bearer トークン認証（空の場合は認証なし） |

### YouTube OAuth2 設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `YOUTUBE_CLIENT_ID` | `""` | Google Cloud Console の OAuth2 クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | `""` | OAuth2 クライアントシークレット |
| `YOUTUBE_REDIRECT_URI` | `http://localhost:8000/api/v1/youtube/auth/callback` | OAuth2 コールバック URI |

### 変換・リソース制御

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `FFMPEG_THREADS` | `1` | ffmpeg の `-threads` 値。`0` で ffmpeg 既定動作 |

## アプリケーション設定（DB 管理）

以下の設定は Web UI または `PATCH /api/v1/settings` API で変更します（`.env` ではなく DB に保存）。

| キー | デフォルト | 説明 |
|------|-----------|------|
| `url_sync_interval_minutes` | `60` | URL ソース自動同期間隔（分）、`0` で無効 |
| `youtube_sync_interval_minutes` | `60` | YouTube プレイリスト自動同期間隔（分）、`0` で無効 |

## 初期設定ガイド

- 最短導入: [はじめに（クイックスタート）](../getting-started.md)
- 初期設定（外部サービス連携）: [初期設定（外部サービス連携）](../setup/external-services.md)
