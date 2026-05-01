# はじめに（クイックスタート）

このページは、最短で SyncTune Hub を起動するための導入手順です。詳細な設定値の意味は [環境設定リファレンス](deployment/configuration.md) を参照してください。

## 1. 事前準備

- Docker / Docker Compose を使う場合: [Docker セットアップ](deployment/docker.md)
- ローカル実行する場合: [ローカル開発](deployment/local-dev.md)

## 2. `.env` を作成

```bash
cp .env.example .env
```

最初は次の項目だけ埋めれば起動できます。

- `REDIS_URL`
- `REDIS_RESULT_BACKEND`

必要に応じて以下を追加します。

- Syncthing 連携: `SYNCTHING_URL`, `SYNCTHING_API_KEY`
- YouTube OAuth2: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`
- API 保護: `SECRET_TOKEN`

## 3. 起動

=== "Docker（推奨）"

    ```bash
    docker compose up -d
    ```

=== "ローカル実行"

    ```bash
    ./start.sh
    ```

## 4. アクセス確認

- Web UI: `http://localhost:8000`
- API Docs: `http://localhost:8000/api/docs`
- Health Check: `http://localhost:8000/api/v1/health`

## 5. 次に行うこと

- 操作方法を確認: [使い方ガイド](usage.md)
- 外部サービス連携を設定: [初期設定（外部サービス連携）](setup/external-services.md)
- 全 env 項目を確認: [環境設定リファレンス](deployment/configuration.md)
