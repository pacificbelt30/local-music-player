# バックエンド概要

**Python / FastAPI** で構築された REST API・音声ストリーミング・非同期タスク処理を担うサーバーです。

## ディレクトリ構成

```
backend/
├── app/
│   ├── main.py           # FastAPI アプリ初期化・ライフスパン処理
│   ├── config.py         # 環境変数設定
│   ├── database.py       # SQLAlchemy セッション管理
│   ├── models.py         # ORM モデル（7 テーブル）
│   ├── schemas.py        # Pydantic スキーマ
│   ├── api/              # REST API ルーター
│   │   ├── router.py
│   │   ├── urls.py       # URL 管理
│   │   ├── queue.py      # ダウンロードキュー + SSE
│   │   ├── tracks.py     # トラックライブラリ
│   │   ├── stream.py     # 音声ストリーミング
│   │   ├── syncthing.py  # Syncthing ステータス
│   │   ├── youtube_playlists.py  # YouTube OAuth + 同期
│   │   └── settings.py   # アプリ設定
│   ├── services/         # 外部サービス・I/O 抽象化
│   │   ├── ytdlp_service.py
│   │   ├── youtube_api_service.py
│   │   ├── syncthing_service.py
│   │   └── file_service.py
│   └── tasks/            # Celery 非同期タスク
│       ├── celery_app.py
│       ├── download.py
│       ├── sync_playlist.py
│       └── scheduler.py
├── tests/
└── requirements.txt
```

## 主要エンドポイント

| エンドポイント | 説明 |
|--------------|------|
| `/api/v1/health` | Redis・DB・ワーカーの死活確認 |
| `/api/v1/admin/rescan` | ファイル削除済みトラックを DB から除去 |
| `/api/docs` | Swagger UI |
| `/api/redoc` | ReDoc |

ヘルスチェックレスポンス:

```json
{
  "status": "ok",
  "redis_connected": true,
  "db_ok": true,
  "worker_active": true
}
```

`status` は Redis・DB が両方正常なら `"ok"`、いずれか障害時は `"degraded"`。

## 依存パッケージ

| パッケージ | バージョン | 用途 |
|-----------|-----------|------|
| `fastapi` | ≥0.111.0 | Web フレームワーク |
| `uvicorn[standard]` | ≥0.29.0 | ASGI サーバー |
| `sqlalchemy` | ≥2.0.30 | ORM |
| `alembic` | ≥1.13.1 | DB マイグレーション |
| `celery[redis]` | ≥5.4.0 | 非同期タスクキュー |
| `redis` | ≥5.0.4 | Redis クライアント |
| `yt-dlp` | ≥2024.5.1 | YouTube ダウンロード |
| `pydantic-settings` | ≥2.2.1 | 設定管理 |
| `aiofiles` | ≥23.2.1 | 非同期ファイル IO |
| `httpx` | ≥0.27.0 | HTTP クライアント |
