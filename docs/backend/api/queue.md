# ダウンロードキュー API

`/api/v1/queue` — ダウンロードジョブの管理とリアルタイム進捗通知を提供します。

## エンドポイント

### GET `/api/v1/queue` — ジョブ一覧

ダウンロードジョブを作成日の新しい順に最大 200 件返します。

**クエリパラメータ**

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `status` | string | カンマ区切りのステータスでフィルタ（例: `pending,downloading`） |

**レスポンス** `200 OK`

```json
[
  {
    "id": 1,
    "url_source_id": 1,
    "youtube_id": "dQw4w9WgXcQ",
    "status": "complete",
    "progress_pct": 100.0,
    "celery_task_id": "abc-123",
    "error_message": null,
    "created_at": "2024-01-01T00:00:00",
    "started_at": "2024-01-01T00:00:01",
    "finished_at": "2024-01-01T00:01:00"
  }
]
```

---

### GET `/api/v1/queue/events` — SSE イベントストリーム

Server-Sent Events で進行中のジョブ進捗をリアルタイム配信します。

**レスポンス** `text/event-stream`

1 秒間隔でイベントを送信します。`pending` または `downloading` 状態のジョブのみ配信されます。

```
data: [{"job_id":1,"youtube_id":"dQw4w9WgXcQ","status":"downloading","progress_pct":42.5}]

data: [{"job_id":1,"youtube_id":"dQw4w9WgXcQ","status":"complete","progress_pct":100.0}]
```

**進捗の取得方法**

1. DB の `DownloadJob.progress_pct` を参照
2. Redis に `job:{id}:progress` キーが存在する場合はそちらを優先（TTL 300 秒）

---

### DELETE `/api/v1/queue/{job_id}` — ジョブキャンセル

ジョブを削除し、実行中のタスクを Celery で取り消します。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `job_id` | ジョブ ID |

**動作**

- `pending` または `downloading` 状態かつ `celery_task_id` がある場合、`celery_app.control.revoke(terminate=True)` を呼び出してタスクを強制終了
- DB からジョブレコードを削除

**レスポンス** `204 No Content`

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID のジョブが存在しない |

---

### POST `/api/v1/queue/{job_id}/retry` — ジョブリトライ

`failed` または `skipped` 状態のジョブを再試行します。

**パスパラメータ**

| パラメータ | 説明 |
|-----------|------|
| `job_id` | ジョブ ID |

**動作**

1. ジョブを `pending` 状態にリセット（`error_message`・`progress_pct`・`started_at`・`finished_at` をクリア）
2. `download_track.apply_async([job.id])` を投入
3. 新しい `celery_task_id` を保存

**レスポンス** `200 OK` — 更新後のジョブ情報

**エラー**

| コード | 条件 |
|--------|------|
| `404` | 指定 ID のジョブが存在しない |
| `409` | ジョブが `failed`/`skipped` 以外の状態 |

## フロントエンドでの利用例

```javascript
const source = new EventSource('/api/v1/queue/events');
source.onmessage = (event) => {
  const jobs = JSON.parse(event.data);
  jobs.forEach(job => updateProgressBar(job.job_id, job.progress_pct));
};
```
