# SyncTuneHub

YouTube から yt-dlp でダウンロードし、Syncthing でスマホに同期するローカル音楽プレイヤーです。

## 機能

- YouTube の URL（動画・プレイリスト・チャンネル）を登録
- バックグラウンドで yt-dlp が自動ダウンロード
- 稼働中の yt-dlp 自動更新（候補版を検証してから切り替え、切り戻し対応）
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
- 設定・デバイスID・ペアリングは `./syncthing-config/`、その他のSyncthing領域は
  `./syncthing-state/` に保存します。`./downloads/` と合わせてコンテナ再作成後も維持します。
- Syncthingは検証済みの `2.1.6` に固定し、APIの準備完了後にアプリを起動します。

#### 既存環境で `/var/syncthing/Sync` を共有している場合

以前の構成では、このフォルダはコンテナ固有の領域にありました。**既存コンテナを削除する前に**、次の手順で移してください。すでに `/var/syncthing/downloads` を共有している場合、このコピーは不要です。

```bash
mkdir -p syncthing-state
docker compose stop syncthing
docker compose cp syncthing:/var/syncthing/Sync ./syncthing-state/Sync
docker compose up -d --build
```

コピー先にすでに `Sync` がある場合は上書きせず、内容を確認してから移行してください。
`/var/syncthing/` 配下の別の共有フォルダも、対応する `./syncthing-state/` の位置へ移してください。
`./syncthing-config/` にある証明書・鍵と `config.xml` はそのまま使い、削除しないでください。
既に旧コンテナを削除した場合、旧匿名ボリュームや同期先からの復旧が必要になることがあります。
フォルダ障害を隠すために空のフォルダや `.stfolder` を作ると、削除が同期される場合があるため、先に内容を復旧してください。

アプリの接続先はコンテナのIPではなく `http://syncthing:8384` を使います。
以前保存したURL/APIキーが環境設定を上書きしている場合は、アプリのSyncthing設定で
「環境設定に戻す」を選択できます。再作成時の一時的な切断は自動的に再接続され、画面も再取得します。
スマホ側でサーバーのアドレスを固定する場合は、コンテナのIPではなくホストの固定IPやDNS名の
`tcp://<server>:22000` を使ってください。

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
