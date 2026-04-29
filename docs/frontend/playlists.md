# プレイリストパネル (`playlists.js`)

`frontend/js/playlists.js` — YouTube OAuth2 認証とプレイリスト同期設定の UI を担当します。

## 主な機能

### YouTube 認証状態表示

ページロード時に `api.youtubeAuthStatus()` を呼び出し、認証状態に応じて UI を切り替えます。

| 状態 | 表示 |
|------|------|
| 未認証 | 「YouTube でログイン」ボタン |
| 認証済み | アカウントのプレイリスト一覧 + ログアウトボタン |

### OAuth2 認証フロー

1. 「YouTube でログイン」ボタンクリック
2. `api.youtubeAuthUrl()` で認証 URL を取得
3. `window.location.href` で Google OAuth 同意画面にリダイレクト
4. コールバック後、`/?youtube_auth=success` にリダイレクト
5. URL パラメータを検知して認証済み状態を表示

### アカウントプレイリスト一覧

認証済みの場合、`api.youtubeListAccountPlaylists()` でプレイリストを取得して表示します。

**表示情報**

| 項目 | 説明 |
|------|------|
| サムネイル | プレイリストのサムネイル画像 |
| プレイリスト名 | `title` |
| トラック数 | `item_count` |
| 同期ボタン | 同期設定が未作成なら「同期追加」、作成済みなら「設定済み」 |

### 同期設定作成

「同期追加」ボタンクリック時にフォームを表示します。

**フォーム**

| フィールド | デフォルト |
|-----------|-----------|
| フォーマット | `mp3` |
| 品質 | `192` |

送信時: `api.youtubeCreateSync({ playlist_id, playlist_name, audio_format, audio_quality })` を呼び出します。

### 同期設定一覧

`api.youtubeListSyncs()` で設定済みの同期プレイリストを表示します。

**表示情報**

| 項目 | 説明 |
|------|------|
| プレイリスト名 | |
| 進捗 | `downloaded_count` / `track_count` |
| 最終同期日時 | `last_synced` |
| 有効/無効トグル | `enabled` の切り替え |
| 今すぐ同期 | `api.youtubeSyncNow(id)` を呼び出し |
| トラック一覧 | 展開して `api.youtubeListSyncTracks(id)` の結果を表示 |
| 削除ボタン | 同期設定を削除（ファイル削除オプション付き） |

### 同期トラック一覧

各同期設定のトラックリストを表示します（`status != "removed"` のみ）。

**表示情報**

| 項目 | 説明 |
|------|------|
| タイトル | |
| ステータス | `pending` / `downloading` / `complete` / `failed` |
| 再生ボタン | `status == "complete"` の場合に表示（`stream_url` を使用） |

### 同期間隔設定

`api.updateSettings({ youtube_sync_interval_minutes: value })` でYouTube 自動同期間隔を変更します。

### ログアウト

`api.youtubeRevokeAuth()` でトークンを削除し、未認証状態に戻します。
