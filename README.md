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


## 推奨スペック（使用ソフトウェアに基づく）

本アプリは `FastAPI + Celery Worker + Celery Beat + Redis + yt-dlp + FFmpeg + Syncthing` を常時または定期的に動かします。以下は、**実運用で待ち時間と安定性のバランスが良い推奨値**です。

### サーバー推奨スペック

| 項目 | 推奨 | 根拠（使用ソフトウェア） |
|---|---:|---|
| CPU | 4 vCPU 以上 | `yt-dlp` の取得処理と `FFmpeg` 変換がCPUを使い、並行して `FastAPI/Celery/Redis` が動作するため |
| メモリ | 8 GB 以上 | `FFmpeg` 変換 + `Celery` ワーカー常駐 + `Redis` キャッシュ/キューを同時利用するため |
| ストレージ | 100 GB 以上（SSD推奨） | 音楽ファイルを `downloads/` に蓄積し、`SQLite` DB とログも保持するため |
| ネットワーク | 上り/下り 50 Mbps 以上（安定回線） | `yt-dlp` の継続DLと `Syncthing` 同期を並行するため |
| OS | Linux x86_64（Ubuntu 22.04 LTS 以降推奨） | Docker運用、またはローカル実行要件（Python/Redis/FFmpeg）を満たしやすいため |

### 最低動作目安（小規模・個人利用）

- 2 vCPU / 4 GB RAM / 30 GB ストレージ
- ただし複数プレイリストの同時更新・同期では、変換待ちが増えやすくなります。

### ソフトウェア前提（再掲）

- Docker運用: Docker Engine + Docker Compose
- ローカル運用: Python 3.11+, Redis 7+, FFmpeg
- 機能連携: yt-dlp, Syncthing

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
