# ローカル開発

`start.sh` を使ったローカル開発環境のセットアップ方法です。

## 前提条件

以下のソフトウェアがインストールされている必要があります。

| ソフトウェア | 確認コマンド | 用途 |
|------------|------------|------|
| Python 3.11+ | `python3 --version` | バックエンド |
| Redis 7+ | `redis-cli ping` | タスクブローカー |
| FFmpeg | `ffmpeg -version` | 音声変換 |

Redis が起動していることを確認してください:

```bash
redis-cli ping  # PONG が返れば OK
```

## セットアップ

```bash
# 1. リポジトリをクローン
git clone https://github.com/pacificbelt30/SyncTuneHub.git
cd SyncTuneHub

# 2. 設定ファイルをコピー
cp .env.example .env
# 必要に応じて .env を編集

# 3. 起動
bash start.sh
```

## `start.sh` の動作

1. `ffmpeg` の存在確認
2. `redis-cli` の存在確認
3. Redis への疎通確認（`redis-cli ping`）
4. `backend/` に Python 仮想環境（`.venv`）を作成（初回のみ）
5. `pip install -r requirements.txt`
6. FastAPI サーバーをバックグラウンドで起動（ポート 8000）
7. Celery ワーカーをバックグラウンドで起動
8. Celery Beat をバックグラウンドで起動

## 手動起動（個別プロセス）

`start.sh` を使わず個別に起動する場合:

```bash
cd backend

# FastAPI
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Celery ワーカー（別ターミナル）
celery -A app.tasks.celery_app.celery_app worker \
    --loglevel=info \
    -Q downloads,scheduler

# Celery Beat（別ターミナル）
celery -A app.tasks.celery_app.celery_app beat --loglevel=info
```

## テスト実行

```bash
cd backend
pytest
```

テストは `tests/` ディレクトリに配置されており、`conftest.py` でインメモリ SQLite とモック Redis を使用します。

## ファイル構成（開発時）

```
SyncTuneHub/
├── downloads/     ← URL 経由ダウンロード先（自動作成）
├── data/          ← SQLite DB（自動作成）
├── playlists/     ← YouTube 同期先（自動作成）
├── .env           ← 設定（.env.example からコピー）
└── backend/
    └── .venv/     ← Python 仮想環境（start.sh が作成）
```

## アクセス

| URL | 説明 |
|-----|------|
| `http://localhost:8000` | Web UI |
| `http://localhost:8000/api/docs` | Swagger UI |
| `http://localhost:8000/api/redoc` | ReDoc |
