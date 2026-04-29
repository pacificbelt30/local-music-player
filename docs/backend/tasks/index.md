# タスク概要

`backend/app/tasks/` — Celery による非同期タスクとスケジューラです。

## タスク一覧

| タスク名 | モジュール | キュー | 説明 |
|---------|---------|-------|------|
| `app.tasks.download.resolve_url` | `download.py` | `downloads` | URL を解析してジョブを生成 |
| `app.tasks.download.download_track` | `download.py` | `downloads` | 1 件の動画をダウンロード |
| `app.tasks.sync_playlist.sync_youtube_playlist` | `sync_playlist.py` | `downloads` | YouTube プレイリストと DB を同期 |
| `app.tasks.sync_playlist.download_playlist_sync_track` | `sync_playlist.py` | `downloads` | プレイリスト同期の 1 件をダウンロード |
| `app.tasks.scheduler.periodic_playlist_refresh` | `scheduler.py` | `scheduler` | URL ソースの定期再解決（Beat） |
| `app.tasks.scheduler.periodic_youtube_playlist_sync` | `scheduler.py` | `scheduler` | YouTube プレイリストの定期同期（Beat） |

## Celery 設定 (`celery_app.py`)

```python
celery_app = Celery(
    "music_player",
    broker=settings.redis_url,           # redis://...:/0
    backend=settings.redis_result_backend,  # redis://...:/1
    include=["app.tasks.download", "app.tasks.scheduler", "app.tasks.sync_playlist"],
)
```

**タスクルーティング**

```python
task_routes = {
    "app.tasks.download.*":      {"queue": "downloads"},
    "app.tasks.scheduler.*":     {"queue": "scheduler"},
    "app.tasks.sync_playlist.*": {"queue": "downloads"},
}
```

**Beat スケジュール**

| タスク | 実行間隔 |
|--------|---------|
| `periodic_playlist_refresh` | 5 分ごと |
| `periodic_youtube_playlist_sync` | 5 分ごと |

Beat が起動しても、各タスク内で `app_settings` の同期間隔設定を確認してから実際の処理を行います。

## ワーカー起動コマンド

```bash
# ワーカー
celery -A app.tasks.celery_app.celery_app worker \
    --loglevel=info \
    -Q downloads,scheduler

# Beat スケジューラ
celery -A app.tasks.celery_app.celery_app beat --loglevel=info
```
