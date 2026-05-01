# PWA サポート

SyncTune Hub は **Progressive Web App（PWA）** として動作します。ホーム画面への追加とオフライン再生に対応しています。

## Web App Manifest (`manifest.json`)

ブラウザが PWA として認識するための設定ファイルです。

```json
{
  "name": "SyncTune Hub",
  "short_name": "Music Player",
  "display": "standalone",
  "start_url": "/",
  "theme_color": "#...",
  "background_color": "#..."
}
```

- iOS/Android のホーム画面に追加してネイティブアプリ風に起動可能
- スタンドアロンモードでブラウザの UI を非表示

## Service Worker (`sw.js`)

### キャッシュ戦略

**キャッシュ名**: `lmp-v1`

**シェルアセット（インストール時にプリキャッシュ）**

```javascript
const SHELL = [
  "/",
  "/css/app.css",
  "/js/api.js",
  "/js/queue.js",
  "/js/library.js",
  "/js/player.js",
];
```

### フェッチ戦略

| リクエスト | 戦略 | 説明 |
|-----------|------|------|
| `/api/*` | Network-first | API 呼び出しは常にネットワークを優先。失敗時は空の JSON `{}` を返す |
| その他（シェル・静的ファイル） | Cache-first | キャッシュがあれば返す。なければネットワークから取得してキャッシュに保存 |

### ライフサイクル

| イベント | 動作 |
|---------|------|
| `install` | シェルアセットをキャッシュ。`skipWaiting()` で即座にアクティベート |
| `activate` | 古いバージョン（`lmp-v1` 以外）のキャッシュを削除。`clients.claim()` で即座に制御 |
| `fetch` | 上記の戦略でリクエストを処理 |

## オフライン動作

- ネットワークが切断されていても UI は表示される（シェルがキャッシュ済みのため）
- 音声ファイルはストリーミング（Service Worker でキャッシュされない）
- API 呼び出し失敗時は空の JSON `{}` が返り、UI は空の状態で表示

## ホーム画面への追加

**iOS（Safari）**

1. ページを開く
2. 共有ボタン → 「ホーム画面に追加」

**Android（Chrome）**

1. ページを開く
2. アドレスバーの「インストール」ボタン、またはメニュー → 「ホーム画面に追加」
