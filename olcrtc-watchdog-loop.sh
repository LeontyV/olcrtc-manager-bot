#!/bin/bash
# olcrtc-watchdog-loop — checks all olcrtc-* services every 15s
set -euo pipefail

echo "[watchdog] started, checking every 15s..."

while true; do
    for unit in $(systemctl list-units --all --no-legend 'olcrtc-*' 2>/dev/null | awk '{print $1}'); do
        [[ "$unit" == olcrtc-manager* ]] && continue

        ERRORS=$(journalctl --no-pager -u "$unit" --since "20 sec ago" 2>/dev/null | grep -iE "reconnect limit reached|fatal|panic|tearing down|signalEnded|shutting down" || true)

        if [ -n "$ERRORS" ]; then
            echo "[watchdog] $(date '+%H:%M:%S') $unit: errors detected, restarting..."
            echo "$ERRORS"
            systemctl restart "$unit" 2>/dev/null || true
        fi
    done
    sleep 15
done
