# API 概要

すべての REST API は `/api/v1` プレフィックスを持ちます。

## エンドポイント一覧

| プレフィックス | モジュール | 説明 |
|--------------|---------|------|
| `/api/v1/urls` | `api/urls.py` | YouTube URL の登録・一覧・削除 |
| `/api/v1/queue` | `api/queue.py` | ダウンロードキュー管理・SSE イベント |
| `/api/v1/tracks` | `api/tracks.py` | トラックライブラリの検索・編集・削除 |
| `/api/v1/stream/{id}` | `api/stream.py` | 音声ストリーミング（Range リクエスト対応） |
| `/api/v1/thumbnails/{id}` | `api/stream.py` | サムネイル画像取得 |
| `/api/v1/files/{id}/download` | `api/stream.py` | 音声ファイルダウンロード |
| `/api/v1/syncthing/status` | `api/syncthing.py` | Syncthing 同期状態 |
| `/api/v1/youtube/*` | `api/youtube_playlists.py` | YouTube OAuth2・プレイリスト同期 |
| `/api/v1/settings` | `api/settings.py` | アプリ設定 |
| `/api/v1/health` | `main.py` | ヘルスチェック |
| `/api/v1/admin/rescan` | `main.py` | DB とファイルシステムの同期 |

!!! tip "対話型ドキュメント"
    サーバー起動後に以下の URL で API を試せます。
    
    - **Swagger UI**: `http://localhost:8000/api/docs`
    - **ReDoc**: `http://localhost:8000/api/redoc`

---

## 共通仕様

### エラーレスポンス

```json
{
  "detail": "エラーメッセージ"
}
```

| HTTP ステータス | 意味 |
|---------------|------|
| `400` | リクエスト不正（設定不足など） |
| `401` | 認証が必要 |
| `404` | リソースが見つからない |
| `409` | 重複（URL 登録済みなど） |
| `502` | 外部 API エラー（YouTube API など） |

### ページネーション

- `/api/v1/tracks`: `limit`・`offset` クエリパラメータをサポート
- `/api/v1/queue`: 最大 200 件を返す
