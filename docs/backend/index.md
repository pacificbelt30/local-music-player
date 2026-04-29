# バックエンド概要

バックエンドは **Python / FastAPI** で構築されており、REST API・音声ストリーミング・非同期タスク処理を担います。

## ディレクトリ構成

```
backend/
├── app/
│   ├── main.py           # FastAPI アプリ初期化
│   ├── config.py         # 設定（環境変数）
│   ├── database.py       # SQLAlchemy セッション管理
│   ├── models.py         # ORM モデル（7 テーブル）
│   ├── schemas.py        # Pydantic スキーマ
│   ├── api/              # REST API ルーター
│   │   ├── router.py     # ルート集約
│   │   ├── urls.py       # URL 管理
│   │   ├── queue.py      # ダウンロードキュー + SSE
│   │   ├── tracks.py     # トラックライブラリ
│   │   ├── stream.py     # 音声ストリーミング
│   │   ├── syncthing.py  # Syncthing ステータス
│   │   ├── youtube_playlists.py  # YouTube OAuth + 同期
│   │   └── settings.py   # アプリ設定
│   ├── services/         # ビジネスロジック
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

## アプリケーション起動

### FastAPI (`app/main.py`)

```python
app = FastAPI(
    title="Local Music Player",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
```

**ライフスパン処理**

1. `downloads/`・`data/`・`playlists/` ディレクトリを作成
2. `init_db()` で DB スキーマを自動生成

**管理エンドポイント**

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/api/v1/health` | GET | Redis・DB・ワーカーの死活確認 |
| `/api/v1/admin/rescan` | POST | ファイル削除済みトラックを DB から除去 |

### ヘルスチェックレスポンス

```json
{
  "status": "ok",
  "redis_connected": true,
  "db_ok": true,
  "worker_active": true
}
```

`status` は Redis・DB が両方正常なら `"ok"`、いずれか障害時は `"degraded"`。
