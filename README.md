# local-music-player

YouTube から yt-dlp でダウンロードし、Syncthing でスマホに同期するローカル音楽プレイヤーです。

## 機能

- YouTube の URL（動画・プレイリスト・チャンネル）を登録
- バックグラウンドで yt-dlp が自動ダウンロード
- 毎時プレイリストを再スキャンして新着動画を追加
- ブラウザからストリーミング再生（PWA対応、スマホのホーム画面に追加可能）
- 音声フォーマットを URL ごとに選択（MP3/FLAC/AAC/OGG）
- Syncthing で `downloads/` フォルダをスマホに同期

## システム構成

```
Browser/Phone UI
       │
       ▼
FastAPI (port 8000)  ←→  Celery Worker (yt-dlp)
       │                         │
       └── Redis ────────────────┘
                                 │
                          downloads/ ←→ Syncthing ←→ スマホ
```

## セットアップ

### Docker（推奨）

```bash
cp .env.example .env
# .env を編集（Syncthing APIキーなど）
docker compose up -d
```

### ローカル実行

**前提条件**: Python 3.11+, ffmpeg, Redis

```bash
cp .env.example .env
./start.sh
```

ブラウザで http://localhost:8000 を開く。

## Syncthing 連携

1. [Syncthing](https://syncthing.net/) をサーバーとスマホにインストール
2. サーバー側で `downloads/` フォルダを Syncthing の共有フォルダに追加
3. Syncthing の API キーを `.env` の `SYNCTHING_API_KEY` に設定
4. スマホの Syncthing でサーバーとペアリング

## API ドキュメント

サーバー起動後: http://localhost:8000/api/docs

## 音声フォーマット

| 値 | 説明 |
|---|---|
| mp3 + 192kbps | デフォルト。互換性が最も高い |
| mp3 + 320kbps | 高音質 MP3 |
| flac | ロスレス |
| aac | AAC ベスト品質 |
| ogg | OGG Vorbis ベスト品質 |
