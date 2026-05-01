# 設定・環境変数

設定は `pydantic-settings` の `BaseSettings` で管理されており、`.env` ファイルまたは環境変数から読み込まれます。

## 設定クラス (`app/config.py`)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    ...

settings = Settings()
```

## 環境変数一覧

### データベース

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `DATABASE_URL` | `sqlite:////home/user/SyncTuneHub/data/music.db` | SQLAlchemy 接続 URL |

### Redis

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `REDIS_URL` | `redis://localhost:6379/0` | Celery ブローカー兼進捗キャッシュ |
| `REDIS_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery リザルトバックエンド |

### ファイルパス

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `DOWNLOADS_PATH` | `/home/user/SyncTuneHub/downloads` | URL 経由でダウンロードした音声ファイルの保存先 |
| `DATA_PATH` | `/home/user/SyncTuneHub/data` | データベースファイルの保存先 |
| `PLAYLISTS_PATH` | `/home/user/SyncTuneHub/playlists` | YouTube 同期プレイリストの保存先 |

### Syncthing

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `SYNCTHING_URL` | `http://localhost:8384` | Syncthing REST API のベース URL |
| `SYNCTHING_API_KEY` | `""` | Syncthing API キー（空の場合は Syncthing 連携無効） |

### CORS・セキュリティ

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `ALLOWED_ORIGINS` | `["*"]` | CORS 許可オリジン（カンマ区切りリスト） |
| `SECRET_TOKEN` | `""` | Bearer トークン認証（空の場合は認証なし） |

### YouTube OAuth2

| 変数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `YOUTUBE_CLIENT_ID` | `""` | Google Cloud Console の OAuth2 クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | `""` | OAuth2 クライアントシークレット |
| `YOUTUBE_REDIRECT_URI` | `http://localhost:8000/api/v1/youtube/auth/callback` | OAuth2 リダイレクト URI |

## `.env.example`

```dotenv
# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_RESULT_BACKEND=redis://localhost:6379/1

# Database (SQLite)
DATABASE_URL=sqlite:////home/user/SyncTuneHub/data/music.db

# File paths
DOWNLOADS_PATH=/home/user/SyncTuneHub/downloads
DATA_PATH=/home/user/SyncTuneHub/data
PLAYLISTS_PATH=/home/user/SyncTuneHub/playlists

# Syncthing (optional — leave blank to disable)
SYNCTHING_URL=http://localhost:8384
SYNCTHING_API_KEY=

# CORS (comma-separated origins, * for all)
ALLOWED_ORIGINS=*

# Optional: set a Bearer token to protect the UI
SECRET_TOKEN=

# YouTube OAuth2 (Google Cloud Console)
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=http://localhost:8000/api/v1/youtube/auth/callback
```

## Docker Compose での設定

`docker-compose.yml` では `env_file: .env` を指定しつつ、コンテナ内のパスに合わせて一部を上書きしています。

```yaml
environment:
  - REDIS_URL=redis://redis:6379/0
  - REDIS_RESULT_BACKEND=redis://redis:6379/1
  - DATABASE_URL=sqlite:////data/music.db
  - DOWNLOADS_PATH=/downloads
  - DATA_PATH=/data
```

## YouTube OAuth2 のセットアップ

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. 「OAuth 2.0 クライアント ID」を作成（アプリケーションの種類: Web アプリケーション）
3. 承認済みリダイレクト URI に `http://localhost:8000/api/v1/youtube/auth/callback` を追加
4. クライアント ID とシークレットを `.env` に設定
