#!/bin/bash
# olcrtc-watchdog — checks all olcrtc-* services for errors and restarts them
set -euo pipefail

RESTARTED=false
REPORT=""

for unit in $(systemctl list-units --all --no-legend 'olcrtc-*' 2>/dev/null | awk '{print $1}'); do
    # Skip wrapper/bot itself
    [[ "$unit" == olcrtc-manager* ]] && continue
    [[ "$unit" == olcrtc-wrapper* ]] && continue

    # Get last 15 log lines since 2 minutes ago
    ERRORS=$(journalctl --no-pager -u "$unit" --since "2 min ago" 2>/dev/null | grep -iE "reconnect limit reached|fatal|panic|context canceled.*reconnect|signalEnded|shutting down" || true)

    if [ -n "$ERRORS" ]; then
        echo "[watchdog] $unit: errors detected, restarting..."
        echo "$ERRORS"
        systemctl restart "$unit" 2>/dev/null || true
        REPORT+="$unit: перезапущен из-за ошибок в логах"$'\n'
        RESTARTED=true
    fi
done

if $RESTARTED; then
    echo "[watchdog] Summary:"
    echo "$REPORT"
else
    echo "[watchdog] All clear"
fi
