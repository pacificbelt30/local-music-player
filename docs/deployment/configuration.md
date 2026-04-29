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

SQLite 以外のデータベース（PostgreSQL など）を使用することも理論上可能ですが、テストは SQLite のみで実施されています。

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

`SYNCTHING_API_KEY` が空の場合、Syncthing 連携は無効になり `/api/v1/syncthing/status` は `{"available": false}` を返します。

**API キーの確認方法**: Syncthing Web GUI → 設定 → 一般 → API キー

### セキュリティ設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `ALLOWED_ORIGINS` | `["*"]` | CORS 許可オリジン |
| `SECRET_TOKEN` | `""` | Bearer トークン認証（空の場合は認証なし） |

`SECRET_TOKEN` を設定すると、すべての `/api/v1/` エンドポイントで `Authorization: Bearer <token>` ヘッダーが必須になります。フロントエンドからアクセスする場合は同じトークンを `api.js` 側でも設定してください。

`ALLOWED_ORIGINS` にカンマ区切りで複数のオリジンを指定できます:

```
ALLOWED_ORIGINS=http://localhost:3000,https://myserver.local
```

### YouTube OAuth2 設定

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `YOUTUBE_CLIENT_ID` | `""` | Google Cloud Console の OAuth2 クライアント ID |
| `YOUTUBE_CLIENT_SECRET` | `""` | OAuth2 クライアントシークレット |
| `YOUTUBE_REDIRECT_URI` | `http://localhost:8000/api/v1/youtube/auth/callback` | OAuth2 コールバック URI |

!!! info "設定が不要な場合"
    UI の **「トークンを直接入力」** フォームを使う場合、これらの変数は **不要** です。  
    `YOUTUBE_CLIENT_ID` が空のままでも YouTube プレイリスト同期は利用できます。  
    ただし、Refresh Token による自動更新は `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` が設定されている場合のみ動作します。

`YOUTUBE_CLIENT_ID` が空の場合、`/api/v1/youtube/auth/url`（ブラウザ OAuth2 フロー）は `400` エラーを返します。

## アプリケーション設定（DB 管理）

以下の設定は Web UI または `PATCH /api/v1/settings` API で変更します（`.env` ではなく DB に保存）。

| キー | デフォルト | 説明 |
|------|-----------|------|
| `url_sync_interval_minutes` | `60` | URL ソース自動同期間隔（分）、`0` で無効 |
| `youtube_sync_interval_minutes` | `60` | YouTube プレイリスト自動同期間隔（分）、`0` で無効 |

## 設定例

### 最小構成（ローカル開発）

```dotenv
# .env
REDIS_URL=redis://localhost:6379/0
REDIS_RESULT_BACKEND=redis://localhost:6379/1
```

### フル構成（本番・Syncthing + YouTube 連携あり）

```dotenv
# .env
REDIS_URL=redis://redis:6379/0
REDIS_RESULT_BACKEND=redis://redis:6379/1

DATABASE_URL=sqlite:////data/music.db
DOWNLOADS_PATH=/downloads
DATA_PATH=/data
PLAYLISTS_PATH=/playlists

SYNCTHING_URL=http://syncthing:8384
SYNCTHING_API_KEY=AbCdEfGhIjKlMnOpQrStUvWxYz

ALLOWED_ORIGINS=http://myserver.local
SECRET_TOKEN=長くてランダムなトークン文字列

YOUTUBE_CLIENT_ID=xxxx.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=GOCSPX-xxxx
YOUTUBE_REDIRECT_URI=http://myserver.local/api/v1/youtube/auth/callback
```
