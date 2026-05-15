#!/bin/bash
# olcrtc-manager-bot — one-command installer
# Usage: curl -sSL https://.../install.sh | bash
# Env vars (optional): BOT_TOKEN=... ALLOWED_USER_ID=... OLCRTC_BIN=...
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
INSTALL_DIR="/root/olcrtc-manager-bot"
SERVICE_NAME="olcrtc-manager"

# ── 1. Prerequisites ──────────────────────────────────
echo -e "${YELLOW}[1/5]${NC} Checking prerequisites..."

dpkg -s python3-venv >/dev/null 2>&1 || apt-get install -y -qq python3-venv
command -v git >/dev/null 2>&1 || apt-get install -y -qq git
command -v openssl >/dev/null 2>&1 || apt-get install -y -qq openssl

# Auto-detect olcrtc binary
_olcrtc="${OLCRTC_BIN:-}"
if [ -z "$_olcrtc" ]; then
    for candidate in \
        /root/olcrtc/build/olcrtc-linux-amd64 \
        /root/olcrtc-server/olcrtc \
        /usr/local/bin/olcrtc; do
        if [ -f "$candidate" ] && [ -x "$candidate" ]; then
            _olcrtc="$candidate"
            break
        fi
    done
fi

if [ -z "$_olcrtc" ] || [ ! -f "$_olcrtc" ]; then
    echo -e "${RED}olcrtc binary not found.${NC}"
    echo "  Set manually: OLCRTC_BIN=/path/to/olcrtc bash install.sh"
    exit 1
fi
echo -e "  ✓ olcrtc: ${GREEN}${_olcrtc}${NC}"

# Check existing installation
if [ -d "$INSTALL_DIR" ]; then
    echo ""
    echo -e "${YELLOW}⚠${NC} Already installed at $INSTALL_DIR"
    # Only prompt if stdin is a TTY (not piped)
    if [ -t 0 ] || [ -c /dev/tty ]; then
        echo -ne "Update (keep profiles.db) or overwrite? [U/o]: "
        read -r _choice < /dev/tty
        if [ "${_choice,,}" = "o" ]; then
            rm -rf "$INSTALL_DIR"
            echo "  Removing old installation..."
        else
            echo "  Keeping existing installation, pulling updates..."
            cd "$INSTALL_DIR"
            git pull -q origin main 2>/dev/null || true
        fi
    else
        echo "  Pulling updates (use env OVERWRITE=1 to force clean install)..."
        cd "$INSTALL_DIR"
        git pull -q origin main 2>/dev/null || true
    fi
fi

# ── 2. Clone ──────────────────────────────────────────
echo -e "${YELLOW}[2/5]${NC} Installing..."
if [ ! -d "$INSTALL_DIR" ]; then
    git clone -q https://github.com/LeontyV/olcrtc-manager-bot.git "$INSTALL_DIR"
fi

# ── 3. Configure (.env) ───────────────────────────────
echo -e "${YELLOW}[3/5]${NC} Setting up .env..."

_token="${BOT_TOKEN:-}"
_uid="${ALLOWED_USER_ID:-}"
_olcrtc_data="${OLCRTC_DATA:-/root/olcrtc-server/data}"

# Try to preserve existing .env values
if [ -f "$INSTALL_DIR/.env" ]; then
    source "$INSTALL_DIR/.env" 2>/dev/null || true
    _token="${BOT_TOKEN:-${_token}}"
    _uid="${ALLOWED_USER_ID:-${_uid}}"
fi

if [ -z "$_token" ] && { [ -t 0 ] || [ -c /dev/tty ]; }; then
    echo -ne "Enter Telegram Bot Token (from @BotFather): "
    read -r _token < /dev/tty
fi
if [ -z "$_uid" ] && { [ -t 0 ] || [ -c /dev/tty ]; }; then
    echo -ne "Enter your Telegram User ID: "
    read -r _uid < /dev/tty
fi

if [ -z "$_token" ] || [ -z "$_uid" ]; then
    echo -e "${RED}Missing BOT_TOKEN or ALLOWED_USER_ID${NC}"
    echo "  Set: BOT_TOKEN=... ALLOWED_USER_ID=... bash install.sh"
    exit 1
fi

cat > "$INSTALL_DIR/.env" << EOF
BOT_TOKEN=${_token}
ALLOWED_USER_ID=${_uid}
OLCRTC_BIN=${_olcrtc}
OLCRTC_DATA=${_olcrtc_data}
EOF
chmod 600 "$INSTALL_DIR/.env"

# ── 4. Python venv + deps ─────────────────────────────
echo -e "${YELLOW}[4/5]${NC} Installing Python dependencies..."
cd "$INSTALL_DIR"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

# ── 5. systemd service ────────────────────────────────
echo -e "${YELLOW}[5/5]${NC} Installing systemd service..."

cat > /etc/systemd/system/olcrtc-manager.service << UNIT
[Unit]
Description=olcrtc Manager Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

# ── Done ──────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "\n${GREEN}✓ Installation complete!${NC}"
    echo -e "  Bot: systemctl status $SERVICE_NAME"
    echo -e "  Telegram: /start"
else
    echo -e "\n${RED}✗ Bot failed to start${NC}"
    journalctl --no-pager -u "$SERVICE_NAME" -n 10
    exit 1
fi
