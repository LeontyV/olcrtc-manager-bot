#!/bin/bash
# olcrtc-manager-bot — one-command installer
# Usage: curl -sSL https://raw.githubusercontent.com/LeontyV/olcrtc-manager-bot/main/install.sh | bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
INSTALL_DIR="/root/olcrtc-manager-bot"
OLCRTC_DIR="/root/olcrtc-server"

# ── 1. Prerequisites ──────────────────────────────────
echo -e "${YELLOW}[1/5]${NC} Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}python3 not found${NC}"; exit 1; }
command -v git >/dev/null 2>&1 || apt-get install -y -qq git
command -v openssl >/dev/null 2>&1 || apt-get install -y -qq openssl

if [ ! -f "$OLCRTC_DIR/olcrtc" ]; then
    echo -e "${RED}olcrtc binary not found at $OLCRTC_DIR/olcrtc${NC}"
    echo "Build it first: https://github.com/LeontyV/olcrtc-manager-bot#readme"
    exit 1
fi

# ── 2. Clone ──────────────────────────────────────────
echo -e "${YELLOW}[2/5]${NC} Cloning repository..."
rm -rf "$INSTALL_DIR"
git clone -q https://github.com/LeontyV/olcrtc-manager-bot.git "$INSTALL_DIR"

# ── 3. Configure (.env) ───────────────────────────────
echo -e "${YELLOW}[3/5]${NC} Setting up .env..."

if [ -n "${BOT_TOKEN:-}" ]; then
    _token="$BOT_TOKEN"
elif [ -f "$INSTALL_DIR/.env" ]; then
    _token=$(grep BOT_TOKEN "$INSTALL_DIR/.env" | cut -d'=' -f2)
else
    echo -ne "Enter Telegram Bot Token (from @BotFather): "
    read -r _token
fi

if [ -n "${ALLOWED_USER_ID:-}" ]; then
    _uid="$ALLOWED_USER_ID"
elif [ -f "$INSTALL_DIR/.env" ]; then
    _uid=$(grep ALLOWED_USER_ID "$INSTALL_DIR/.env" | cut -d'=' -f2)
else
    echo -ne "Enter your Telegram User ID: "
    read -r _uid
fi

cat > "$INSTALL_DIR/.env" << EOF
BOT_TOKEN=${_token}
ALLOWED_USER_ID=${_uid}
EOF
chmod 600 "$INSTALL_DIR/.env"

# ── 4. Python venv + deps ─────────────────────────────
echo -e "${YELLOW}[4/5]${NC} Installing Python dependencies..."
cd "$INSTALL_DIR"
python3 -m venv venv
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
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now olcrtc-manager

# ── Done ──────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet olcrtc-manager; then
    echo -e "\n${GREEN}✓ Installation complete!${NC}"
    echo -e "  Bot is running: systemctl status olcrtc-manager"
    echo -e "  Open Telegram and send /start to your bot"
else
    echo -e "\n${RED}✗ Bot failed to start${NC}"
    journalctl --no-pager -u olcrtc-manager -n 10
    exit 1
fi
