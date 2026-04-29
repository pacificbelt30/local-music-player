# 今後の課題・未実装箇所

現在の実装で機能しているが不完全・制限がある箇所、および未実装のままの機能をまとめます。

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

デフォルトで全オリジンを許可しており、本番環境では適切なオリジンに制限する必要があります。`ALLOWED_ORIGINS` 環境変数で上書き可能です。

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
| URL バリデーションの拡張（YouTube以外対応） | 中 | 低 |
| `admin/rescan` の双方向対応 | 中 | 中 |
| CORS オリジン制限（本番設定） | 高（セキュリティ） | 低 |
| OAuth トークン暗号化 | 高（セキュリティ） | 中 |
| DB バックアップ機能 | 中（運用） | 低 |
| ダウンロード完了通知 | 低 | 中 |
| フロントエンドテスト | 低（品質） | 高 |
