# サービス層概要

`backend/app/services/` — 外部サービスや I/O 処理を抽象化するビジネスロジック層です。

## サービス一覧

| モジュール | 説明 |
|-----------|------|
| `ytdlp_service.py` | yt-dlp による URL 解決・音声ダウンロード |
| `youtube_api_service.py` | YouTube Data API v3 クライアント（OAuth2 対応） |
| `syncthing_service.py` | Syncthing REST API クライアント |
| `file_service.py` | ファイルシステム操作（ファイル削除） |

## 設計方針

- サービス関数は純粋な Python 関数として実装（クラスなし）
- 外部 API 呼び出しは `httpx` を使用（同期・非同期の両方）
- エラーは例外として上位に伝播させ、各呼び出し元で処理
- 設定は `app.config.settings` から取得
