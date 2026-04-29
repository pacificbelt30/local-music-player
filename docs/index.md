# Local Music Player

Local Music Player は、YouTube から音楽をダウンロードし、ローカルネットワーク内でストリーミング再生するシステムです。Syncthing によるモバイル端末への自動同期にも対応しています。

## 主な機能

| 機能 | 説明 |
|------|------|
| **URLダウンロード** | YouTube の動画・プレイリスト・チャンネル URL を登録してバックグラウンドでダウンロード |
| **フォーマット選択** | MP3 / FLAC / AAC / OGG、品質 192kbps / 320kbps / best を選択可能 |
| **リアルタイム進捗** | Server-Sent Events によるダウンロード進捗のリアルタイム表示 |
| **YouTube OAuth** | Google アカウント連携でプレイリストを自動同期 |
| **ブラウザ再生** | Web UI からストリーミング再生（範囲リクエスト対応） |
| **Syncthing 連携** | `downloads/` フォルダをモバイル端末へ自動同期 |
| **PWA 対応** | オフライン再生・ホーム画面追加に対応 |
| **定期自動同期** | Celery Beat により 5 分ごとにプレイリスト更新をチェック |

## クイックスタート

### Docker を使う場合

```bash
cp .env.example .env
# .env を編集して必要な設定を行う
docker compose up -d
```

ブラウザで `http://localhost:8000` を開きます。

### ローカル開発の場合

```bash
cp .env.example .env
bash start.sh
```

詳細は [ローカル開発](deployment/local-dev.md) を参照してください。

## システム要件

- **Docker** 20.10+ と Docker Compose v2（本番環境推奨）
- または **Python** 3.11+、**Redis** 7+、**FFmpeg**（ローカル開発）
- **Syncthing**（モバイル同期を使う場合）
- YouTube OAuth 連携には Google Cloud Console でのアプリ登録が必要

## ドキュメント構成

```
アーキテクチャ   — システム全体の構造とデータフロー
バックエンド     — FastAPI・Celery・SQLAlchemy の仕様
フロントエンド   — バニラ JS / CSS による UI の仕様
デプロイ        — Docker・ローカル起動・環境変数の設定
```
