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
- 任意のLast.fm／YouTube Data API連携で人気の音楽を閲覧し、Last.fmで類似曲を検索

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

## 人気の音楽・類似曲を探す（任意）

「設定 → 音楽を見つける・外部連携」で、使いたいサービスのAPIキーと地域を指定し、
「この連携を有効にする」にチェックして保存します。「接続確認」は保存済みのキーを使います。
両サービスとも初期状態では無効です。一方だけでも利用でき、YouTubeのOAuth接続は不要です。
保存後は「見つける」で人気一覧を閲覧できます。
上部の「YouTube／Last.fm／似た曲を探す」で表示を切り替えます。
Last.fmの一覧にある「似た曲」を押すと、曲名を入力し直さずにその曲から検索できます。
未設定のサービスやキーのエラーからは該当する設定欄へ移動でき、保存後のリンクでそのサービスの一覧へ戻れます。

| サービス | キーの準備 | 表示する情報 |
| --- | --- | --- |
| YouTube Data API | [Google Cloud](https://console.cloud.google.com/apis/library/youtube.googleapis.com)でYouTube Data API v3を有効にし、[認証情報](https://console.cloud.google.com/apis/credentials)からAPIキーを作成 | 音楽カテゴリの人気動画。公式の週間楽曲チャートとは異なる |
| Last.fm | [APIアカウントの作成](https://www.last.fm/api/account/create)でAPI keyを発行。Shared secretは入力不要 | 日本・米国・英国の先週の人気曲と、入力したアーティスト・曲名からの類似曲 |

GoogleのキーにはYouTube Data API v3のAPI制限を設定できます。サーバーから照会するため、
ブラウザ用のHTTPリファラー制限付きキーは使えません。必要ならサーバーの送信元IPで制限してください。
Last.fmのログインやscrobbleは行いません。類似曲の照会ではフォームに入力した曲名・アーティスト名だけを送り、
音声・プレイリスト全体・再生履歴は送りません。各サービスの利用条件・割当の範囲で使用してください。

通常の人気一覧は最大50件、類似曲は最大20件です。人気一覧は20件ずつ表示します。
取得結果は通常6時間キャッシュし、画面の「更新」で再取得できます。取得に失敗したときは、
取得から24時間以内の前回情報をその旨とともに表示します。Last.fmが短い保存期限を指定した場合はそちらを優先します。
接続確認を含め、この機能からの呼出しは**各サービスにつきUTCの1日あたり100回、最短2秒間隔**に制限しています。
これはアプリ独自の上限で、提供元のAPI割当残量ではありません。上限・通信障害・キーの拒否は画面に表示します。
候補からはYouTube／Last.fmのページを開くか、Last.fmの類似曲を検索できます。自動ダウンロード・同期登録は行いません。
プレイリスト単位の自動推薦は今後の機能です。

APIキーはサーバー側で暗号化してDBに保存し、保存済みの値をブラウザへ返しません。
キー欄を空欄で保存すると既存のキーを保持し、「キーを削除」でその連携も無効にします。
キーの入力には、既存の[ローカルHTTPS設定](docs/deployment/https.md)を利用できます。
Docker Composeでは`data/`の永続化によりコンテナの再作成後も設定を維持します。
バックアップには**DBと`data/.discovery-key`を一緒に含めてください**。
暗号鍵を失った場合、保存済みAPIキーは復号できないため、利用する両サービスのキーを設定し直してください。

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
