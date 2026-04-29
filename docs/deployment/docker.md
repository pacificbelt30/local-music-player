# Docker デプロイ

Docker Compose を使った本番環境への展開方法です。

## サービス構成

`docker-compose.yml` は 4 つのサービスで構成されます。

| サービス | イメージ | 説明 |
|---------|---------|------|
| `redis` | `redis:7-alpine` | Celery ブローカー + リザルトバックエンド |
| `api` | `./` (ビルド) | FastAPI + 静的ファイル配信（ポート 8000） |
| `worker` | `./` (ビルド) | Celery ワーカー（downloads・scheduler キュー） |
| `beat` | `./` (ビルド) | Celery Beat スケジューラ |

## 起動手順

```bash
# 1. 設定ファイルをコピー
cp .env.example .env

# 2. .env を編集
#    - YouTube OAuth2 を使う場合: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET
#    - Syncthing 連携を使う場合: SYNCTHING_URL, SYNCTHING_API_KEY

# 3. 起動
docker compose up -d

# 4. ログ確認
docker compose logs -f
```

ブラウザで `http://localhost:8000` を開きます。

## ボリューム

| ホストパス | コンテナパス | 説明 |
|-----------|------------|------|
| `./downloads` | `/downloads` | ダウンロード済み音声ファイル |
| `./data` | `/data` | SQLite データベース |
| `./frontend` | `/app/frontend` | フロントエンド静的ファイル（読み取り専用） |
| `redis-data` | — | Redis データ永続化（名前付きボリューム） |

## コンテナ内の環境変数

`env_file: .env` で `.env` を読み込みつつ、コンテナパスに合わせて以下を上書きします。

```yaml
environment:
  - REDIS_URL=redis://redis:6379/0
  - REDIS_RESULT_BACKEND=redis://redis:6379/1
  - DATABASE_URL=sqlite:////data/music.db
  - DOWNLOADS_PATH=/downloads
  - DATA_PATH=/data
```

## コマンド例

```bash
# ワーカーのログを確認
docker compose logs -f worker

# コンテナを再起動
docker compose restart api

# 完全停止（データは保持）
docker compose down

# データも含めて削除
docker compose down -v
```

## ポート

| ポート | サービス |
|--------|---------|
| `8000` | FastAPI（UI + API） |

## Dockerfile

`backend/` ディレクトリをビルドコンテキストとして、Python 3.11 スリムイメージをベースに requirements.txt をインストールします。

## スケーリング

ダウンロードが遅い場合はワーカーを複数起動できます:

```bash
docker compose up -d --scale worker=3
```

Beat スケジューラは**必ず 1 インスタンスのみ**起動してください（重複実行防止）。
