# キューパネル (`queue.js`)

`frontend/js/queue.js` — YouTube URL の登録と、ダウンロードキューのリアルタイム表示を担当します。

## 主な機能

### URL 登録フォーム

ユーザーが YouTube URL（動画・プレイリスト・チャンネル）を入力して登録します。

**入力フィールド**

| フィールド | 種類 | デフォルト | 説明 |
|-----------|------|-----------|------|
| URL | テキスト | — | YouTube URL |
| フォーマット | セレクト | `mp3` | `mp3` / `flac` / `aac` / `ogg` |
| 品質 | セレクト | `192` | `192` / `320` / `best` |

**送信時の動作**

1. `api.addUrl({ url, audio_format, audio_quality })` を呼び出す
2. 成功後、URL リストを更新
3. エラー時はアラート表示

### 登録済み URL 一覧

登録済みの `UrlSource` を一覧表示します。

**表示情報**

- タイトル（解決後）または URL
- URL タイプ（video / playlist / channel）
- フォーマット・品質
- 削除ボタン（ファイルも削除するオプション付き）

**操作**

- **削除**: `api.deleteUrl(id, deleteFiles)` を呼び出し

### ダウンロードキュー表示

SSE でリアルタイム進捗を表示します。

**表示情報**

| 状態 | 表示 |
|------|------|
| `pending` | 待機中インジケーター |
| `downloading` | プログレスバー（`progress_pct` %） |
| `complete` | 完了表示 |
| `failed` | エラーメッセージ + リトライボタン |
| `skipped` | スキップ表示 + リトライボタン |

**操作**

- **キャンセル**: `api.cancelJob(id)` — `pending`/`downloading` ジョブを停止
- **リトライ**: `api.retryJob(id)` — `failed`/`skipped` ジョブを再試行

### 同期間隔セレクター

`app_settings` の `url_sync_interval_minutes` を変更します。

| 選択肢 | 値 |
|--------|-----|
| 手動のみ | `0` |
| 30 分 | `30` |
| 1 時間 | `60` |
| 6 時間 | `360` |
| 12 時間 | `720` |
| 24 時間 | `1440` |

変更時に `api.updateSettings({ url_sync_interval_minutes: value })` を呼び出します。

## SSE 購読

```javascript
subscribeQueueEvents((jobs) => {
  // jobs: [{job_id, youtube_id, status, progress_pct}]
  renderQueueItems(jobs);
});
```

ページロード時に購読を開始し、コンポーネントのライフサイクル全体で維持します。
