# 今後の課題・未実装箇所

現在の実装で機能しているが不完全・制限がある箇所、および未実装のままの機能をまとめます。

---

## バグ・動作上の問題

### プレイリストパネルからの再生が機能しない

**場所**: `frontend/js/playlists.js:300`、`frontend/js/player.js`

`playlists.js` は同期済みトラックのクリック時に `play-playlist-track` カスタムイベントをウィンドウに dispatch しますが、`player.js` にこのイベントのリスナーが存在しません。

```javascript
// playlists.js:300 — イベントを発火するが受け取り手がない
window.dispatchEvent(new CustomEvent("play-playlist-track", { detail: track }));
```

`player.js` に以下のようなリスナーを追加する必要があります:

```javascript
window.addEventListener("play-playlist-track", (e) => {
  play([e.detail], 0);
});
```

### ダウンロードキューにトラックタイトルが表示されない

**場所**: `frontend/js/queue.js:86`、`backend/app/schemas.py`

`DownloadJobResponse` に `title` フィールドがないため、キュー表示では `youtube_id`（例: `dQw4w9WgXcQ`）がそのまま表示されます。URL 解決後にタイトルを `DownloadJob` に保存するか、`resolve_url` タスクで取得した title を `DownloadJob` テーブルに追加する必要があります。

### Bearer トークン認証が実装されていない

**場所**: `backend/app/config.py:21`

`SECRET_TOKEN` 環境変数は定義されていますが、実際に認証を強制するミドルウェアやデペンデンシーが存在しません。設定しても API は保護されません。

---

## フロントエンド

### ライブラリのページネーションが未実装

**場所**: `frontend/js/library.js:15`

```javascript
tracks = await api.listTracks({ limit: 100, ...params });
```

最大 100 件しか表示しません。スクロール末端での追加取得（infinite scroll）や「もっと読み込む」ボタンは未実装です。

### プレイリスト同期追加時にフォーマット選択ができない

**場所**: `frontend/js/playlists.js:112-118`

「+ 同期追加」ボタンは `audio_format` と `audio_quality` をデフォルト値（MP3 / 192 kbps）で固定送信します。プレイリストごとにフォーマット・品質を選択するフォームがありません。

### プレイヤーにボリューム調整がない

**場所**: `frontend/js/player.js`

HTML `<audio>` 要素のボリュームコントロール UI がありません。`audio.volume` の操作は実装されていますが、スライダー等の UI 要素がありません。

### シャッフル・リピートが未実装

**場所**: `frontend/js/player.js`

プレイヤーコントロールに「シャッフル」「リピート（1曲/全曲）」ボタンがありません。

### 再生状態がページリロードで失われる

ページをリロードすると現在再生中のトラック・位置情報が消えます。`localStorage` や Session Storage への状態保存は実装されていません。

---

## バックエンド API

### URL 登録時のバリデーションが YouTube のみ

**場所**: `backend/app/schemas.py:17-19`

```python
if "youtube.com" not in v and "youtu.be" not in v:
    raise ValueError("URL must be a YouTube URL")
```

YouTube 以外のプラットフォーム（SoundCloud・Vimeo・ニコニコ動画等）は拒否されます。yt-dlp 自体は多数のサイトに対応していますが、バリデーションを緩和する変更が必要です。

### `/api/v1/urls` にページネーション・検索がない

**場所**: `backend/app/api/urls.py:33-35`

登録 URL の一覧 API は全件返すのみで、検索・ソート・ページネーションに対応していません。

### トラックの編集可能フィールドが限定的

**場所**: `backend/app/schemas.py:73-77`

`TrackUpdate` で更新できるのは `title`・`artist`・`album` の 3 フィールドのみです。`file_format`・`audio_quality` 等は変更できません。

### ダウンロード済みトラックの重複管理

`UrlSource` 経由でダウンロードした `tracks` と、YouTube 同期の `playlist_sync_tracks` は別テーブルで管理されており、同じ動画が両方に存在しうる状態です。統合・deduplication の仕組みがありません。

---

## データベース・ストレージ

### Alembic マイグレーションが未設定

**場所**: `backend/app/database.py`

起動時に `Base.metadata.create_all()` でスキーマを生成しますが、Alembic マイグレーションファイルが作成されていません。スキーマ変更時は手動での DB 操作が必要です。

### DB バックアップ機能がない

SQLite ファイルのバックアップ・エクスポートを行う API やスクリプトが存在しません。

### `admin/rescan` が一方向のみ

**場所**: `backend/app/main.py:82-98`

`POST /api/v1/admin/rescan` はファイルが存在しないトラックを DB から削除しますが、DB に存在しないが `downloads/` に存在するファイルをトラックとして取り込む機能はありません。

---

## タスク・ワーカー

### リトライ回数が UI から見えない

`DownloadJob` テーブルにリトライ回数（Celery の `self.request.retries`）を保存するフィールドがなく、何回目のリトライかを UI で確認できません。

### 永続的な失敗の扱いが未定義

最大リトライ（`resolve_url`: 2回、`download_track`: 3回）を超えた場合、ジョブは `failed` のままです。自動的なデッドレターキューへの移動・アラート通知はありません。

### ダウンロード完了通知がない

トラックのダウンロードが完了しても、ブラウザ通知（Web Notifications API）や Webhook 等の通知機能がありません。SSE のキューイベントで確認する必要があります。

---

## セキュリティ

### CORS がデフォルトで全許可

**場所**: `backend/app/config.py:19`

```python
allowed_origins: list[str] = ["*"]
```

デフォルトで全オリジンを許可しており、本番環境では適切なオリジンに制限する必要があります。

### YouTube OAuth トークンが暗号化されていない

`YouTubeOAuthToken` テーブルのアクセストークン・リフレッシュトークンはプレーンテキストで SQLite に保存されています。DB ファイルへのアクセスがあれば直接読み取れます。

---

## Syncthing

### Syncthing フォルダの設定が手動

Syncthing でフォルダを共有するには Syncthing Web GUI を別途操作する必要があります。アプリから Syncthing フォルダを設定・管理する機能はありません。

---

## テスト

### フロントエンドのテストがない

`frontend/` ディレクトリ以下に JavaScript のユニットテスト・E2E テストが存在しません。

### Celery タスクの結合テストがない

`backend/tests/` のタスクテストはすべてモックベースです。実際の Redis やファイルシステムを使った結合テストはありません。

### CI で yt-dlp のネットワークテストがない

`.github/workflows/test.yml` のテストは実際の YouTube へのネットワークアクセスを行わず、yt-dlp の動作はモックで代替されています。

---

## 優先度まとめ

| 課題 | 影響 | 対応難度 |
|------|------|---------|
| プレイリストパネルからの再生バグ | 高 | 低（数行の修正） |
| Bearer トークン認証の実装 | 高（セキュリティ） | 中 |
| Alembic マイグレーション整備 | 高（運用） | 中 |
| ダウンロードキューのタイトル表示 | 中 | 中 |
| ライブラリのページネーション | 中 | 低 |
| プレイリスト追加時のフォーマット選択 | 中 | 低 |
| プレイヤーのボリューム・シャッフル | 低 | 低 |
