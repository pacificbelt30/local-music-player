# Linux セットアップガイド

Debian / Ubuntu 系ディストリビューションでのセットアップ手順です。

## 推奨スペック

=== "最小構成"

    | 項目 | 要件 |
    |------|------|
    | OS | Ubuntu 22.04 LTS / Debian 12 以降 |
    | CPU | 1 コア |
    | RAM | 1 GB |
    | ストレージ | 16 GB（OS + アプリ）+ 音楽ライブラリ分 |
    | ネットワーク | 10 Mbps 以上 |

=== "推奨構成"

    | 項目 | 要件 |
    |------|------|
    | OS | Ubuntu 22.04 LTS / Debian 12 以降 |
    | CPU | 2 コア以上 |
    | RAM | 2 GB 以上 |
    | ストレージ | 32 GB（OS + アプリ）+ 音楽ライブラリ分 |
    | ネットワーク | 50 Mbps 以上（並行ダウンロード時） |

=== "Raspberry Pi"

    | モデル | 実用性 |
    |--------|--------|
    | Pi 4（2GB） | 軽量利用（同時ダウンロード 1〜2 件推奨） |
    | Pi 4（4GB） | 快適に動作（3〜4 件対応） |
    | Pi 3 以前 | 非推奨（タイムアウトが発生しやすい） |

### ストレージ目安

| フォーマット | 1 曲 | 1,000 曲 |
|------------|------|---------|
| MP3 192 kbps | 約 5 MB | 約 5 GB |
| MP3 320 kbps | 約 8 MB | 約 8 GB |
| FLAC | 約 25〜40 MB | 約 30 GB |
| AAC / OGG | 約 5〜7 MB | 約 6 GB |

---

## セットアップ手順

=== "Docker を使う（推奨）"

    ### 1. Docker のインストール

    ```bash
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-compose-plugin
    sudo usermod -aG docker $USER && newgrp docker
    ```

    ### 2. 起動

    ```bash
    git clone https://github.com/pacificbelt30/local-music-player.git
    cd local-music-player
    cp .env.example .env
    docker compose up -d
    ```

    詳細は [Docker デプロイ](docker.md) を参照してください。

=== "直接インストール"

    ### 1. システムパッケージのインストール

    ```bash
    sudo apt-get update
    sudo apt-get install -y \
        python3 python3-venv python3-pip \
        redis-server ffmpeg git curl
    ```

    ### 2. Redis の起動

    ```bash
    sudo systemctl enable --now redis-server
    redis-cli ping  # PONG が返れば OK
    ```

    ### 3. Syncthing のインストール（任意）

    ```bash
    sudo mkdir -p /etc/apt/keyrings
    curl -L https://syncthing.net/release-key.gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/syncthing-archive-keyring.gpg
    echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] \
        https://apt.syncthing.net/ syncthing stable" \
        | sudo tee /etc/apt/sources.list.d/syncthing.list
    sudo apt-get update && sudo apt-get install -y syncthing
    sudo systemctl enable --now syncthing@$USER
    ```

    Syncthing Web GUI: `http://localhost:8384`

    ### 4. アプリの起動

    ```bash
    git clone https://github.com/pacificbelt30/local-music-player.git
    cd local-music-player
    cp .env.example .env
    bash start.sh
    ```

---

## systemd サービス化（直接インストール時）

`start.sh` を使わずに自動起動させる場合は systemd ユニットを作成します。

`/etc/systemd/system/local-music-player.service`:

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
ExecStart=/home/YOUR_USER/local-music-player/.venv/bin/python \
    -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now local-music-player
```

!!! note "Celery も個別ユニットで管理推奨"
    本番環境では Celery ワーカーと Beat も個別の systemd ユニットとして管理すると安定します。

---

## ファイアウォール設定

```bash
# LAN からのみ許可（推奨）
sudo ufw allow from 192.168.0.0/16 to any port 8000
sudo ufw allow from 10.0.0.0/8 to any port 8000

# Syncthing を使う場合
sudo ufw allow syncthing

sudo ufw reload
```

---

## バージョン確認

```bash
python3 --version        # 3.11.x 以上
redis-server --version   # 7.x 以上
ffmpeg -version          # 5.x 以上
docker --version         # Docker を使う場合
docker compose version   # Compose v2
```
