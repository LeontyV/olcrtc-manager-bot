#!/bin/bash
# olcrtc-manager-bot — one-command installer
# Usage: curl -sSL https://.../install.sh | bash
# Env vars (optional): BOT_TOKEN=... ALLOWED_USER_ID=...
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
INSTALL_DIR="/root/olcrtc-manager-bot"
SERVICE_NAME="olcrtc-manager"
OLCRTC_REPO_DIR="/root/olcrtc"
OLCRTC_BIN_DEFAULT="${OLCRTC_REPO_DIR}/build/olcrtc-linux-amd64"

# ── 1. Prerequisites ──────────────────────────────────
echo -e "${YELLOW}[1/7]${NC} Checking prerequisites..."

dpkg -s python3-venv >/dev/null 2>&1 || apt-get install -y -qq python3-venv
command -v git >/dev/null 2>&1 || apt-get install -y -qq git
command -v openssl >/dev/null 2>&1 || apt-get install -y -qq openssl
command -v wget >/dev/null 2>&1 || apt-get install -y -qq wget

# ── 2. Install Go (if not present) ────────────────────
echo -e "${YELLOW}[2/7]${NC} Checking Go..."

_need_go=false
if ! command -v go >/dev/null 2>&1; then
    _need_go=true
else
    _go_ver=$(go version 2>/dev/null | grep -oP 'go\d+\.\d+' | head -1 || true)
    if [ -z "$_go_ver" ]; then
        _need_go=true
    elif ! printf '%s\n' "1.22" "$(echo "$_go_ver" | sed 's/^go//')" | sort -V -c 2>/dev/null; then
        _need_go=true
    fi
fi

if $_need_go; then
    GO_TAR="go1.26.0.linux-amd64.tar.gz"
    echo "  Installing Go 1.26..."
    wget -q "https://go.dev/dl/${GO_TAR}" -O "/tmp/${GO_TAR}"
    rm -rf /usr/local/go
    tar -C /usr/local -xzf "/tmp/${GO_TAR}"
    rm -f "/tmp/${GO_TAR}"
    export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin
    # Persist PATH for this script and future systemd services
    grep -q '/usr/local/go/bin' ~/.bashrc 2>/dev/null || \
        echo 'export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin' >> ~/.bashrc
fi

export PATH=$PATH:/usr/local/go/bin:$HOME/go/bin
echo -e "  ✓ Go: ${GREEN}$(go version)${NC}"

# ── 3. Build olcrtc (if not found) ────────────────────
echo -e "${YELLOW}[3/7]${NC} Checking olcrtc binary..."

_olcrtc="${OLCRTC_BIN:-}"
if [ -z "$_olcrtc" ] || [ ! -f "$_olcrtc" ]; then
    # Check known paths
    for candidate in \
        "$OLCRTC_BIN_DEFAULT" \
        "${OLCRTC_REPO_DIR}/olcrtc" \
        /usr/local/bin/olcrtc; do
        if [ -f "$candidate" ] && [ -x "$candidate" ]; then
            _olcrtc="$candidate"
            break
        fi
    done
fi

if [ -z "$_olcrtc" ] || [ ! -f "$_olcrtc" ]; then
    echo "  Building olcrtc from source..."

    # Install mage
    if ! command -v mage >/dev/null 2>&1; then
        echo "  Installing mage..."
        go install github.com/magefile/mage@latest
        export PATH=$PATH:$HOME/go/bin
    fi

    # Clone repo if not exists
    if [ ! -d "$OLCRTC_REPO_DIR" ]; then
        echo "  Cloning olcrtc..."
        git clone -q https://github.com/openlibrecommunity/olcrtc --recurse-submodules "$OLCRTC_REPO_DIR"
    else
        echo "  Updating olcrtc repo..."
        cd "$OLCRTC_REPO_DIR"
        git pull -q origin main 2>/dev/null || true
        git submodule update --init --recursive -q 2>/dev/null || true
    fi

    cd "$OLCRTC_REPO_DIR"
    echo "  mage build..."
    mage build

    if [ -f "$OLCRTC_BIN_DEFAULT" ]; then
        _olcrtc="$OLCRTC_BIN_DEFAULT"
        # Also symlink for convenience
        ln -sf "$OLCRTC_BIN_DEFAULT" "${OLCRTC_REPO_DIR}/olcrtc"
    else
        echo -e "${RED}Build failed — binary not found at ${OLCRTC_BIN_DEFAULT}${NC}"
        exit 1
    fi
fi

echo -e "  ✓ olcrtc: ${GREEN}${_olcrtc}${NC}"

# ── 4. Data directory ─────────────────────────────────
echo -e "${YELLOW}[4/7]${NC} Checking data directory..."

_olcrtc_data="${OLCRTC_DATA:-}"
if [ -z "$_olcrtc_data" ] || [ ! -d "$_olcrtc_data" ]; then
    for candidate in \
        "${OLCRTC_REPO_DIR}/data" \
        /root/olcrtc-server/data; do
        if [ -d "$candidate" ]; then
            _olcrtc_data="$candidate"
            break
        fi
    done
fi

if [ -z "$_olcrtc_data" ]; then
    _olcrtc_data="${OLCRTC_REPO_DIR}/data"
    mkdir -p "$_olcrtc_data"
    echo -e "  ✓ data: ${YELLOW}created ${_olcrtc_data}${NC}"
else
    echo -e "  ✓ data: ${GREEN}${_olcrtc_data}${NC}"
fi

# ── 5. Install/update bot ──────────────────────────────
echo -e "${YELLOW}[5/7]${NC} Installing bot..."

if [ -d "$INSTALL_DIR" ]; then
    echo "  Already installed — pulling updates..."
    cd "$INSTALL_DIR"
    git pull -q origin main 2>/dev/null || true
    systemctl restart "$SERVICE_NAME" 2>/dev/null || true
fi

if [ ! -d "$INSTALL_DIR" ]; then
    git clone -q https://github.com/LeontyV/olcrtc-manager-bot.git "$INSTALL_DIR"
fi

chmod +x "$INSTALL_DIR/olcrtc-wrapper.sh"

# ── 6. Configure + Python deps ─────────────────────────
echo -e "${YELLOW}[6/7]${NC} Setting up .env and Python..."

_token="${BOT_TOKEN:-}"
_uid="${ALLOWED_USER_ID:-}"

# Preserve existing .env if present, but refresh paths
if [ -f "$INSTALL_DIR/.env" ]; then
    source "$INSTALL_DIR/.env" 2>/dev/null || true
    _token="${BOT_TOKEN:-${_token}}"
    _uid="${ALLOWED_USER_ID:-${_uid}}"
fi

# If tokens are missing, use placeholders — user fills them later
if [ -z "$_token" ]; then _token="ВАШ_ТОКЕН_БОТА"; fi
if [ -z "$_uid" ]; then _uid="ВАШ_TELEGRAM_ID"; fi

cat > "$INSTALL_DIR/.env" << EOF
BOT_TOKEN=${_token}
ALLOWED_USER_ID=${_uid}
OLCRTC_BIN=${_olcrtc}
OLCRTC_DATA=${_olcrtc_data}
EOF
chmod 600 "$INSTALL_DIR/.env"

cd "$INSTALL_DIR"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

# ── 7. systemd service ────────────────────────────────
echo -e "${YELLOW}[7/7]${NC} Installing systemd service..."

cat > /etc/systemd/system/olcrtc-manager.service << UNIT
[Unit]
Description=olcrtc Manager Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
Environment=PATH=/usr/local/go/bin:/root/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

# Only start if tokens are real (not placeholders)
if [[ "$_token" == "ВАШ_ТОКЕН_БОТА" ]] || [[ "$_uid" == "ВАШ_TELEGRAM_ID" ]]; then
    echo ""
    echo -e "${YELLOW}⚠ Токен бота и Telegram ID не заданы.${NC}"
    echo ""
    echo "  Открой .env и заполни поля:"
    echo -e "    ${GREEN}nano ${INSTALL_DIR}/.env${NC}"
    echo ""
    echo "  После этого запусти бота:"
    echo -e "    ${GREEN}systemctl start ${SERVICE_NAME}${NC}"
else
    systemctl enable --now "$SERVICE_NAME"
fi

# ── Done ──────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "\n${GREEN}✓ Installation complete!${NC}"
    echo -e "  Bot: systemctl status $SERVICE_NAME"
    echo -e "  Telegram: /start"
else
    if [[ "$_token" != "ВАШ_ТОКЕН_БОТА" ]] && [[ "$_uid" != "ВАШ_TELEGRAM_ID" ]]; then
        echo -e "\n${RED}✗ Bot failed to start${NC}"
        journalctl --no-pager -u "$SERVICE_NAME" -n 10
        exit 1
    fi
fi
