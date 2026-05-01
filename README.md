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

### Docker で起動する場合

`docker compose up -d` で `syncthing` サービスも一緒に起動します。

- Web GUI: http://localhost:8384
- REST API キーは `.env` の `SYNCTHING_API_KEY` がそのままコンテナの
  `STGUIAPIKEY` として注入されるため、別途 GUI でコピーする必要はありません
  （`.env.example` の値は必ず長いランダム文字列に変更してください）。
- 同期対象の `downloads/` フォルダはコンテナ内の `/var/syncthing/downloads`
  にマウント済みです。Web GUI から「フォルダーの追加」で
  `/var/syncthing/downloads` を共有フォルダとして登録してください。
- 公開ポート: `8384`（Web GUI / REST API）、`22000/tcp`・`22000/udp`（同期）、
  `21027/udp`（ローカル探索）。

### スマホとペアリング

1. スマホに公式 Syncthing アプリをインストール
2. サーバーの Syncthing Web GUI（`http://<server>:8384`）でスマホをデバイス追加
3. `downloads` フォルダをスマホと共有

### ローカル実行（非Docker）の場合

1. [Syncthing](https://syncthing.net/) をサーバーにインストール
2. Web GUI（`http://localhost:8384`）→ 設定 → 一般 → API キーを
   `.env` の `SYNCTHING_API_KEY` に設定

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
