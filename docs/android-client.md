# Android クライアント設定

Android からこのシステムを利用する方法は 2 種類あります。

| 利用方法 | 説明 |
|---------|------|
| **ブラウザ（PWA）** | サーバーの Web UI に接続してストリーミング再生 |
| **Syncthing 同期** | 音楽ファイルをスマホに転送してオフライン再生 |

---

## 1. ブラウザ（PWA）でアクセスする

### サーバーへの接続

同じローカルネットワーク（Wi-Fi）上にある場合、サーバーの IP アドレスでアクセスできます。

1. サーバーの IP アドレスを確認する（例: `192.168.1.10`）
2. Android の Chrome などのブラウザで `http://192.168.1.10:8000` を開く

!!! tip "IP アドレスの確認方法（サーバー側）"
    ```bash
    # Linux
    ip addr show | grep "inet " | grep -v 127.0.0.1
    # または
    hostname -I
    ```

### ホーム画面への追加（PWA インストール）

Android の Chrome ではアプリとしてインストールできます。

1. Chrome でサーバーの URL を開く
2. アドレスバー右端の「インストール」アイコンをタップ、または
   メニュー（⋮）→「ホーム画面に追加」をタップ
3. アプリ名を確認して「追加」をタップ

インストール後はホーム画面のアイコンからブラウザの UI を非表示にしてアプリ風に起動できます。

### SECRET_TOKEN を設定している場合

サーバーで `SECRET_TOKEN` を設定している場合、フロントエンドの `api.js` にトークンが埋め込まれているため、ブラウザからのアクセスは通常どおり動作します。追加の設定は不要です。

---

## 2. Syncthing でファイルを同期してオフライン再生する

Syncthing を使うと `downloads/` フォルダの音楽ファイルをスマホに自動転送できます。

### 2-1. Android に Syncthing をインストールする

[Google Play](https://play.google.com/store/apps/details?id=com.nutomic.syncthingandroid) または [F-Droid](https://f-droid.org/packages/com.nutomic.syncthingandroid/) から **Syncthing** をインストールします。

!!! note
    公式 Syncthing アプリ（`com.nutomic.syncthingandroid`）を使用してください。

### 2-2. サーバー側の Syncthing を設定する

サーバーの Syncthing Web GUI（デフォルト: `http://localhost:8384`）で操作します。

1. **デバイスを追加する**
    - 「デバイスを追加」をクリック
    - Android の Syncthing で表示されている「デバイス ID」を入力
    - デバイス名（例: `My Android`）を入力して保存

2. **共有フォルダを設定する**
    - 「フォルダを追加」または既存の `downloads/` フォルダを編集
    - 「共有」タブで追加した Android デバイスにチェックを入れて保存

3. **API キーを `.env` に設定する**
    ```dotenv
    SYNCTHING_URL=http://localhost:8384
    SYNCTHING_API_KEY=（Syncthing GUI → 設定 → 一般 → API キー）
    ```

### 2-3. Android 側の Syncthing を設定する

1. Android の Syncthing アプリを開く
2. サーバーからのデバイス追加リクエストが届いていたら「承認」をタップ
3. サーバーからのフォルダ共有リクエストが届いたら「承認」をタップ
4. 同期先のフォルダをスマホ内のパス（例: `/storage/emulated/0/Music/SyncTuneHub`）に設定して保存

同期が開始されると `downloads/` の音楽ファイルが Android に転送されます。

### 2-4. バッテリーと同期タイミングの設定

Android の Syncthing アプリには、同期タイミングを制限する設定があります。

| 設定項目 | 推奨値 | 説明 |
|---------|--------|------|
| **Wi-Fi のみで同期** | 有効 | モバイル通信でのデータ消費を防ぐ |
| **充電中のみ同期** | 任意 | バッテリーを節約したい場合に有効 |
| **常に実行** | 任意 | バックグラウンド同期を継続する |

設定場所: Syncthing アプリ → メニュー（⋮）→ 設定 → 同期条件

### 2-5. 音楽プレイヤーアプリで再生する

同期した音楽ファイルは、以下のようなプレイヤーアプリで再生できます。

| アプリ | 特徴 |
|-------|------|
| **VLC for Android** | 無料・多フォーマット対応（MP3/FLAC/AAC/OGG すべて対応） |
| **Poweramp** | 高音質・多機能（有料） |
| **Musicolet** | 軽量・広告なし・無料 |

同期先フォルダ（例: `/storage/emulated/0/Music/SyncTuneHub`）を音楽プレイヤーのライブラリに追加してください。

---

## 3. ネットワーク設定（外出先からアクセスする場合）

自宅 LAN 外からアクセスする場合は、VPN や Tailscale などを利用してください。

### Tailscale を使う場合（推奨）

1. [Tailscale](https://tailscale.com/) をサーバーと Android 両方にインストール
2. 同じアカウントでログイン
3. Tailscale が割り当てた IP アドレス（例: `100.64.x.x`）でアクセス

### ALLOWED_ORIGINS の設定

外部からアクセスする場合は `.env` の `ALLOWED_ORIGINS` に接続元のオリジンを追加してください。

```dotenv
ALLOWED_ORIGINS=http://100.64.x.x:8000,http://192.168.1.10:8000
```

---

## まとめ

| やりたいこと | 設定 |
|------------|------|
| スマホのブラウザから再生したい | サーバーの IP を Chrome で開く、PWA としてインストール |
| オフラインで再生したい | Syncthing でスマホに同期 → VLC などで再生 |
| 外出先からアクセスしたい | Tailscale などの VPN を利用 |
| バッテリーを節約したい | Syncthing を「充電中のみ・Wi-Fi のみ」に設定 |
