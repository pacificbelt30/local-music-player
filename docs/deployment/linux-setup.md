# Linux セットアップガイド

Debian / Ubuntu 系ディストリビューションでのセットアップ手順です。  
Docker を使う方法と、直接インストールする方法の両方を説明します。

---

## 推奨スペック

### 最小構成

| 項目 | 要件 |
|------|------|
| **OS** | Ubuntu 22.04 LTS / Debian 12 以降 |
| **CPU** | 1 コア |
| **RAM** | 1 GB |
| **ストレージ** | 16 GB（OS + アプリ分）+ 音楽ライブラリ分 |
| **ネットワーク** | 10 Mbps 以上（ダウンロード） |

### 推奨構成

| 項目 | 要件 |
|------|------|
| **OS** | Ubuntu 22.04 LTS / Debian 12 以降 |
| **CPU** | 2 コア以上 |
| **RAM** | 2 GB 以上 |
| **ストレージ** | 32 GB（OS + アプリ）+ 音楽ライブラリ分 |
| **ネットワーク** | 50 Mbps 以上（並行ダウンロード時） |

### ストレージ目安（音楽ライブラリ）

| フォーマット | 1 曲あたり | 1,000 曲 |
|------------|-----------|---------|
| MP3 192 kbps | 約 5 MB | 約 5 GB |
| MP3 320 kbps | 約 8 MB | 約 8 GB |
| FLAC | 約 25〜40 MB | 約 30 GB |
| AAC / OGG | 約 5〜7 MB | 約 6 GB |

### Raspberry Pi での運用

| モデル | 実用性 |
|--------|--------|
| Raspberry Pi 4（2GB） | 軽量利用に対応（同時ダウンロードは 1〜2 件推奨） |
| Raspberry Pi 4（4GB） | 快適に動作（同時ダウンロード 3〜4 件対応） |
| Raspberry Pi 3 以前 | 非推奨（RAM・CPU 不足でタイムアウトが発生しやすい） |

---

## 必要なパッケージ

### 直接インストール（Docker を使わない場合）

| パッケージ | 最低バージョン | 用途 |
|-----------|--------------|------|
| `python3` | 3.11 | バックエンド実行 |
| `python3-venv` | — | 仮想環境作成 |
| `python3-pip` | — | Python パッケージ管理 |
| `redis-server` | 7.0 | タスクキュー / キャッシュ |
| `ffmpeg` | 5.0 | 音声フォーマット変換 |
| `git` | — | リポジトリ取得 |
| `curl` | — | 疎通確認 |

### Syncthing 連携を使う場合（追加）

| パッケージ | 用途 |
|-----------|------|
| `syncthing` | スマホへの音楽ファイル同期 |

### Docker を使う場合

| パッケージ | 用途 |
|-----------|------|
| `docker-ce` | コンテナランタイム |
| `docker-compose-plugin` | Compose v2 |

---

## セットアップ手順

### セットアップスクリプトを使う（推奨）

リポジトリに付属の `install.sh` を実行するとパッケージのインストールから起動までを自動化できます。

```bash
git clone https://github.com/pacificbelt30/local-music-player.git
cd local-music-player
sudo bash install.sh
```

スクリプトはインタラクティブにインストール内容を選択できます。詳細は次のセクションを参照してください。

---

### 手動セットアップ（直接インストール）

#### 1. システムパッケージのインストール

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    redis-server \
    ffmpeg \
    git \
    curl
```

#### 2. Redis の起動と自動起動設定

```bash
sudo systemctl enable --now redis-server
redis-cli ping  # PONG が返れば OK
```

#### 3. Syncthing のインストール（任意）

```bash
# 公式リポジトリを追加
sudo mkdir -p /etc/apt/keyrings
curl -L https://syncthing.net/release-key.gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/syncthing-archive-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] \
    https://apt.syncthing.net/ syncthing stable" \
    | sudo tee /etc/apt/sources.list.d/syncthing.list

sudo apt-get update
sudo apt-get install -y syncthing
```

サービスとして起動する場合（実行ユーザーを指定）:

```bash
sudo systemctl enable --now syncthing@$USER
```

Syncthing の Web GUI は `http://localhost:8384` で開けます。

#### 4. リポジトリのクローンと起動

```bash
git clone https://github.com/pacificbelt30/local-music-player.git
cd local-music-player
cp .env.example .env
# .env を編集して SYNCTHING_API_KEY などを設定
bash start.sh
```

---

### 手動セットアップ（Docker）

#### 1. Docker のインストール

```bash
# 必要なパッケージ
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Docker 公式 GPG キーを追加
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# リポジトリを追加（Ubuntu の場合）
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list

sudo apt-get update
sudo apt-get install -y docker-ce docker-compose-plugin

# 現在のユーザーを docker グループに追加（sudo なしで使えるようにする）
sudo usermod -aG docker $USER
newgrp docker
```

#### 2. 起動

```bash
git clone https://github.com/pacificbelt30/local-music-player.git
cd local-music-player
cp .env.example .env
docker compose up -d
```

詳細は [Docker デプロイ](docker.md) を参照してください。

---

## systemd サービス化（直接インストール時）

`start.sh` を使わずにシステム起動時に自動起動する場合は systemd ユニットを作成します。

### ユニットファイルの作成

`/etc/systemd/system/local-music-player.service` を作成します（パスと `User` は環境に合わせて変更してください）:

```ini
[Unit]
Description=Local Music Player
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=forking
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/local-music-player
EnvironmentFile=/home/YOUR_USER/local-music-player/.env
ExecStartPre=/home/YOUR_USER/local-music-player/.venv/bin/pip install -q -r /home/YOUR_USER/local-music-player/backend/requirements.txt
ExecStart=/home/YOUR_USER/local-music-player/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

!!! note "Celery ワーカーの systemd 管理"
    Celery ワーカーと Beat も個別のユニットファイルとして管理することを推奨します。  
    本番環境では `start.sh` よりも systemd 管理のほうが安定します。

### 有効化

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now local-music-player
sudo systemctl status local-music-player
```

---

## ファイアウォール設定

`ufw` を使っている場合は、ポート 8000 を開放します。

```bash
# 同一ネットワーク（LAN）からのみ許可する例
sudo ufw allow from 192.168.0.0/16 to any port 8000
sudo ufw allow from 10.0.0.0/8 to any port 8000

# 全体に開放する場合（非推奨）
sudo ufw allow 8000/tcp

sudo ufw reload
sudo ufw status
```

Syncthing を使う場合は追加で:

```bash
sudo ufw allow syncthing
```

---

## バージョン確認コマンド

セットアップ後に以下のコマンドで各コンポーネントのバージョンを確認できます。

```bash
python3 --version        # Python 3.11.x 以上
redis-server --version   # Redis 7.x 以上
ffmpeg -version          # FFmpeg 5.x 以上
syncthing --version      # Syncthing（インストールした場合）
docker --version         # Docker（Docker を使う場合）
docker compose version   # Docker Compose v2（Docker を使う場合）
```
