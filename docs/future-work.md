# 今後の課題・未実装箇所

現在の実装で機能しているが不完全・制限がある箇所、および未実装の機能をまとめます。

## 優先度まとめ

| 課題 | カテゴリ | 影響 | 難度 |
|------|---------|------|------|
| CORS オリジン制限（本番設定） | セキュリティ | 高 | 低 |
| OAuth トークン暗号化 | セキュリティ | 高 | 中 |
| URL バリデーション拡張（YouTube 以外） | API | 中 | 低 |
| `admin/rescan` の双方向対応 | API | 中 | 中 |
| DB バックアップ機能 | 運用 | 中 | 低 |
| ダウンロード完了通知 | UX | 低 | 中 |
| フロントエンドテスト | 品質 | 低 | 高 |

---

## バックエンド API

### URL バリデーションが YouTube のみ

**場所**: `backend/app/schemas.py:17-19`

```python
if "youtube.com" not in v and "youtu.be" not in v:
    raise ValueError("URL must be a YouTube URL")
```

yt-dlp 自体は SoundCloud・Vimeo・ニコニコ動画等に対応していますが、バリデーションを緩和する変更が必要です。

### `/api/v1/urls` にページネーション・検索がない

**場所**: `backend/app/api/urls.py:33-35`

登録 URL の一覧 API は全件返すのみです。検索・ソート・ページネーションに未対応です。

### トラックの編集可能フィールドが限定的

**場所**: `backend/app/schemas.py:73-77`

`TrackUpdate` で更新できるのは `title`・`artist`・`album` の 3 フィールドのみです。

### ダウンロード済みトラックの重複管理

`url_sources` 経由でダウンロードした `tracks` と、YouTube 同期の `playlist_sync_tracks` は別テーブルで管理されており、同じ動画が両方に存在しうる状態です。統合・deduplication の仕組みがありません。

---

## データベース・ストレージ

### DB バックアップ機能がない

SQLite ファイルのバックアップ・エクスポートを行う API やスクリプトが存在しません。

### `admin/rescan` が一方向のみ

**場所**: `backend/app/main.py:82-98`

`POST /api/v1/admin/rescan` はファイルが存在しないトラックを DB から削除しますが、DB に存在しないが `downloads/` に存在するファイルを取り込む機能はありません。

---

## タスク・ワーカー

### リトライ回数が UI から見えない

`DownloadJob` テーブルにリトライ回数フィールドがなく、何回目のリトライかを UI で確認できません。

### 永続的な失敗の扱いが未定義

最大リトライ（`resolve_url`: 2 回、`download_track`: 3 回）を超えた場合、ジョブは `failed` のままです。デッドレターキューへの移動・アラート通知はありません。

### ダウンロード完了通知がない

ダウンロード完了時に Web Notifications API や Webhook 等の通知機能がありません。SSE のキューイベントで確認する必要があります。

---

## セキュリティ

### CORS がデフォルトで全許可

**場所**: `backend/app/config.py:19`

```python
allowed_origins: list[str] = ["*"]
```

本番環境では `ALLOWED_ORIGINS` 環境変数で適切なオリジンに制限してください。

### YouTube OAuth トークンが暗号化されていない

`YouTubeOAuthToken` テーブルのアクセストークン・リフレッシュトークンはプレーンテキストで SQLite に保存されています。DB ファイルへのアクセスがあれば直接読み取れます。

---

## Syncthing

### Syncthing フォルダの設定が手動

Syncthing でフォルダを共有するには Syncthing Web GUI を別途操作する必要があります。アプリから Syncthing フォルダを設定・管理する機能はありません。

---

## テスト

### フロントエンドのテストがない

`frontend/` 以下に JavaScript のユニットテスト・E2E テストが存在しません。

### Celery タスクの結合テストがない

`backend/tests/` のタスクテストはすべてモックベースです。実際の Redis やファイルシステムを使った結合テストはありません。

### CI で yt-dlp のネットワークテストがない

`.github/workflows/test.yml` のテストは実際の YouTube へのネットワークアクセスを行わず、yt-dlp の動作はモックで代替されています。
