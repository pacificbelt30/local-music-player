# ダウンロードタスク

`backend/app/tasks/download.py` — URL 解決とトラックダウンロードの Celery タスクです。

## `resolve_url`

```python
@celery_app.task(name="app.tasks.download.resolve_url", bind=True, max_retries=2)
def resolve_url(self, url_source_id: int) -> None
```

**キュー**: `downloads`  
**最大リトライ**: 2 回（失敗時 60 秒後にリトライ）

**処理フロー**

1. `UrlSource` を DB から取得
2. `ytdlp_service.resolve_url(url)` で動画 ID リストを取得
3. `UrlSource.url_type`・`title` を更新（先頭エントリから判定、複数なら `playlist`）
4. `UrlSource.last_synced` を現在時刻で更新
5. 各動画 ID に対して（重複チェック後）:
   - `DownloadJob` を作成（status=`pending`）
   - `download_track.apply_async([job.id])` を投入
   - `celery_task_id` を保存

**重複処理**: 同じ `youtube_id` の `DownloadJob` が存在する場合はスキップ（`INSERT OR IGNORE` 相当）

---

## `download_track`

```python
@celery_app.task(name="app.tasks.download.download_track", bind=True, max_retries=3)
def download_track(self, job_id: int) -> None
```

**キュー**: `downloads`  
**最大リトライ**: 3 回（失敗時 30・60・120 秒後）

**処理フロー**

1. `DownloadJob` を DB から取得
2. 親 `UrlSource` から `audio_format`・`audio_quality` を取得（なければデフォルト: `mp3`/`192`）
3. `DownloadJob.status = "downloading"`、`started_at` を設定
4. 進捗フック定義: ダウンロード中に `job:{job_id}:progress`（TTL 300 秒）を Redis に書き込み
5. `ytdlp_service.download_track()` でダウンロード実行
   - 手動追加（単体 URL）は `DOWNLOADS_PATH/manual/` に保存
   - URL がプレイリスト/チャンネルの場合は `DOWNLOADS_PATH/{source.title}/` に保存（ファイル名安全化）
   - 保存ファイルは音声のみ（サムネイル・`.info.json` は生成しない）
6. `Track` レコードを upsert（`youtube_id` で検索、なければ新規作成）
7. `PlaylistTrack` リンクを作成（`url_source_id` がある場合）
8. `DownloadJob.status = "complete"`、`progress_pct = 100.0`、`finished_at` を設定
9. Redis の進捗キーを削除

**エラー時**

- `DownloadJob.status = "failed"`
- `error_message` に例外メッセージ（最大 500 文字）を保存
- Celery がリトライをスケジュール（指数バックオフ: 30, 60, 120 秒）

## 進捗キャッシュ

```
Redis キー: job:{job_id}:progress
値: 0.0〜100.0 の文字列
TTL: 300 秒
```

SSE エンドポイント (`/api/v1/queue/events`) がこのキーを 1 秒ごとに読み取り、フロントエンドに配信します。
