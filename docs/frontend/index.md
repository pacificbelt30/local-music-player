# フロントエンド概要

フロントエンドはフレームワークを使わない **バニラ JavaScript（ES6 モジュール）** と **プレーン CSS** で構築されています。

## ディレクトリ構成

```
frontend/
├── index.html        # メイン UI（3 パネルレイアウト）
├── manifest.json     # PWA マニフェスト
├── sw.js             # Service Worker
├── css/
│   └── app.css       # レスポンシブ CSS
└── js/
    ├── api.js        # HTTP クライアント + SSE
    ├── queue.js      # キューパネルロジック
    ├── library.js    # ライブラリパネルロジック
    ├── playlists.js  # プレイリストパネルロジック
    └── player.js     # オーディオプレイヤー
```

## UI 構成

### デスクトップ（3 カラムレイアウト）

```
┌──────────────┬──────────────┬──────────────┐
│  左: Queue   │ 中: Playlists│  右: Library │
│              │              │              │
│ URL 入力     │ YouTube Auth │ 検索ボックス │
│ 登録 URL 一覧│ プレイリスト │ トラックグリッド│
│ DLキュー     │ 同期設定     │              │
└──────────────┴──────────────┴──────────────┘
┌───────────────────────────────────────────┐
│           固定プレイヤーバー              │
│  [サムネ] タイトル/アーティスト  ◁ ▷ ▶  │
│  シークバー                   00:00/03:33 │
└───────────────────────────────────────────┘
```

### モバイル（タブ切り替え）

画面下部にタブバーが表示され、1 パネルずつ切り替えます。

## JavaScript モジュール構成

### `api.js`

バックエンド API のラッパーを提供します。すべてのモジュールがこれを `import` します。

```javascript
import { api, subscribeQueueEvents } from './api.js';
```

詳細は [API クライアント](#api-クライアント) を参照。

### モジュール依存関係

```
index.html
  ├── js/api.js       ← 全モジュールが利用
  ├── js/queue.js     ← api.js, player.js
  ├── js/library.js   ← api.js, player.js
  ├── js/playlists.js ← api.js
  └── js/player.js    ← api.js
```

## API クライアント (`api.js`)

### `api` オブジェクト

```javascript
api.addUrl(payload)                  // POST /urls
api.listUrls()                       // GET /urls
api.deleteUrl(id, deleteFiles)       // DELETE /urls/{id}

api.listQueue(status)                // GET /queue
api.cancelJob(id)                    // DELETE /queue/{id}
api.retryJob(id)                     // POST /queue/{id}/retry

api.listTracks(params)               // GET /tracks
api.updateTrack(id, data)            // PATCH /tracks/{id}
api.deleteTrack(id, deleteFile)      // DELETE /tracks/{id}

api.syncthingStatus()                // GET /syncthing/status
api.health()                         // GET /health

api.youtubeAuthUrl()                 // GET /youtube/auth/url
api.youtubeAuthStatus()              // GET /youtube/auth/status
api.youtubeRevokeAuth()              // DELETE /youtube/auth
api.youtubeListAccountPlaylists()    // GET /youtube/playlists
api.youtubeListSyncs()               // GET /youtube/syncs
api.youtubeCreateSync(payload)       // POST /youtube/syncs
api.youtubeUpdateSync(id, payload)   // PATCH /youtube/syncs/{id}
api.youtubeDeleteSync(id, delFiles)  // DELETE /youtube/syncs/{id}
api.youtubeSyncNow(id)               // POST /youtube/syncs/{id}/run
api.youtubeListSyncTracks(syncId)    // GET /youtube/syncs/{syncId}/tracks

api.getSettings()                    // GET /settings
api.updateSettings(payload)          // PATCH /settings
```

### `subscribeQueueEvents(onData)`

SSE でキュー進捗を購読します。

```javascript
const es = subscribeQueueEvents((jobs) => {
  jobs.forEach(job => updateProgressUI(job));
});
// 停止: es.close();
```

### エラーハンドリング

API エラー時はレスポンスの `detail` フィールドから `Error` を throw します。
