#!/usr/bin/env bash
# install.sh — Local Music Player セットアップスクリプト (Debian/Ubuntu)
set -euo pipefail

###############################################################################
# 定数
###############################################################################
REPO_URL="https://github.com/pacificbelt30/local-music-player.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/local-music-player}"
MIN_PYTHON_MINOR=11

###############################################################################
# ヘルパー関数
###############################################################################
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
ask()     { echo -e "${YELLOW}[?]${NC} $*"; }

require_sudo() {
    if [[ $EUID -ne 0 ]]; then
        error "このスクリプトは sudo で実行してください: sudo bash $0"
    fi
}

check_os() {
    if ! command -v apt-get &>/dev/null; then
        error "apt-get が見つかりません。Debian/Ubuntu 系 OS で実行してください。"
    fi
    info "OS: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -a)"
}

yn_prompt() {
    local prompt="$1" default="${2:-y}"
    local yn
    while true; do
        if [[ "$default" == "y" ]]; then
            read -rp "$(echo -e "${YELLOW}[?]${NC} $prompt [Y/n]: ")" yn
            yn="${yn:-y}"
        else
            read -rp "$(echo -e "${YELLOW}[?]${NC} $prompt [y/N]: ")" yn
            yn="${yn:-n}"
        fi
        case "${yn,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *) echo "  y または n で答えてください。" ;;
        esac
    done
}

###############################################################################
# インストール関数
###############################################################################
install_base_packages() {
    info "システムパッケージを更新しています..."
    apt-get update -qq

    info "必須パッケージをインストールしています..."
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        redis-server \
        ffmpeg \
        git \
        curl \
        ca-certificates \
        gnupg

    # Python バージョン確認
    local pyver
    pyver=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [[ "$pyver" -lt "$MIN_PYTHON_MINOR" ]]; then
        warn "Python 3.${pyver} が見つかりました。3.${MIN_PYTHON_MINOR} 以上を推奨します。"
        warn "deadsnakes PPA から Python 3.11 をインストールしますか？"
        if yn_prompt "Python 3.11 をインストールする"; then
            apt-get install -y software-properties-common
            add-apt-repository -y ppa:deadsnakes/ppa
            apt-get update -qq
            apt-get install -y python3.11 python3.11-venv python3.11-distutils
            update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
        fi
    fi

    info "Redis を起動・自動起動設定しています..."
    systemctl enable --now redis-server
    if redis-cli ping &>/dev/null; then
        info "Redis: 起動確認 OK"
    else
        warn "Redis の起動に失敗しました。手動で確認してください: systemctl status redis-server"
    fi
}

install_syncthing() {
    info "Syncthing をインストールしています..."
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://syncthing.net/release-key.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/syncthing-archive-keyring.gpg

    echo "deb [signed-by=/etc/apt/keyrings/syncthing-archive-keyring.gpg] \
https://apt.syncthing.net/ syncthing stable" \
        > /etc/apt/sources.list.d/syncthing.list

    apt-get update -qq
    apt-get install -y syncthing

    # 実行ユーザーで systemd サービスを有効化
    local target_user="${SUDO_USER:-$USER}"
    if systemctl enable --now "syncthing@${target_user}" 2>/dev/null; then
        info "Syncthing サービスを ${target_user} で起動しました。"
        info "Web GUI: http://localhost:8384"
    else
        warn "Syncthing の自動起動設定に失敗しました。手動で設定してください:"
        warn "  sudo systemctl enable --now syncthing@${target_user}"
    fi
}

install_docker() {
    info "Docker をインストールしています..."

    # 既存の古いパッケージを削除
    apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # GPG キーを追加
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # リポジトリを追加
    local arch
    arch=$(dpkg --print-architecture)
    local codename
    codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
    local os_id
    os_id=$(. /etc/os-release && echo "$ID")

    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${os_id} ${codename} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable --now docker

    # 実行ユーザーを docker グループに追加
    local target_user="${SUDO_USER:-$USER}"
    usermod -aG docker "$target_user"
    info "Docker インストール完了。'${target_user}' を docker グループに追加しました。"
    info "グループ変更を反映するには一度ログアウトして再ログインしてください。"
}

setup_app() {
    local target_user="${SUDO_USER:-$USER}"

    if [[ -d "$INSTALL_DIR" ]]; then
        info "インストール先ディレクトリが既に存在します: $INSTALL_DIR"
    else
        info "リポジトリをクローンしています: $INSTALL_DIR"
        sudo -u "$target_user" git clone "$REPO_URL" "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"

    # .env のコピー
    if [[ ! -f .env ]]; then
        sudo -u "$target_user" cp .env.example .env
        info ".env ファイルを作成しました。必要に応じて編集してください: $INSTALL_DIR/.env"
    else
        info ".env は既に存在します（上書きしません）。"
    fi

    # Python 仮想環境の作成
    if [[ ! -d .venv ]]; then
        info "Python 仮想環境を作成しています..."
        sudo -u "$target_user" python3 -m venv .venv
    fi

    info "依存パッケージをインストールしています..."
    sudo -u "$target_user" .venv/bin/pip install -q -r backend/requirements.txt

    info ""
    info "セットアップが完了しました！"
    info ""
    info "  起動コマンド:"
    info "    cd $INSTALL_DIR && bash start.sh"
    info ""
    info "  .env ファイルを編集して設定してください:"
    info "    $INSTALL_DIR/.env"
}

configure_firewall() {
    if ! command -v ufw &>/dev/null; then
        warn "ufw が見つかりません。ファイアウォール設定をスキップします。"
        return
    fi

    local ufw_status
    ufw_status=$(ufw status | head -1)
    if [[ "$ufw_status" != *"active"* ]]; then
        info "ufw は非アクティブです。ファイアウォール設定をスキップします。"
        return
    fi

    info "ufw でポート 8000 を LAN に開放します。"
    ufw allow from 192.168.0.0/16 to any port 8000 comment "local-music-player"
    ufw allow from 10.0.0.0/8 to any port 8000 comment "local-music-player"
    ufw reload
    info "ファイアウォール設定完了。"
}

###############################################################################
# メイン
###############################################################################
main() {
    echo ""
    echo "============================================"
    echo "  Local Music Player — Linux セットアップ"
    echo "============================================"
    echo ""

    require_sudo
    check_os

    # インストール方式の選択
    echo ""
    echo "インストール方式を選択してください:"
    echo "  1) 直接インストール（Python + Redis + FFmpeg）"
    echo "  2) Docker インストール"
    echo ""
    local mode
    while true; do
        read -rp "$(echo -e "${YELLOW}[?]${NC} 方式 [1/2]: ")" mode
        case "$mode" in
            1|2) break ;;
            *) echo "  1 または 2 を入力してください。" ;;
        esac
    done

    echo ""
    if [[ "$mode" == "1" ]]; then
        install_base_packages

        if yn_prompt "Syncthing もインストールする（スマホへのファイル同期）" "y"; then
            install_syncthing
        fi

        if yn_prompt "アプリをセットアップする（リポジトリのクローンと依存インストール）" "y"; then
            setup_app
        fi

    else
        install_docker

        if yn_prompt "Syncthing もインストールする（スマホへのファイル同期）" "y"; then
            install_syncthing
        fi

        if yn_prompt "アプリをセットアップする（リポジトリのクローンと .env の作成）" "y"; then
            setup_app
        fi
    fi

    if yn_prompt "ファイアウォール（ufw）でポート 8000 を LAN に開放する" "n"; then
        configure_firewall
    fi

    echo ""
    info "すべての処理が完了しました。"
    echo ""
}

main "$@"
