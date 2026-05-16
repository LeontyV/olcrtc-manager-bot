#!/bin/bash
# olcrtc-watchdog-loop — checks all olcrtc-* services every 15s
set -euo pipefail

echo "[watchdog] $(date '+%H:%M:%S') started, checking every 15s..."

cycle=0
while true; do
    ((cycle++))
    while read -r unit; do
        [[ -z "$unit" ]] && continue
        [[ "$unit" == olcrtc-manager* ]] && continue
        [[ "$unit" == olcrtc-watchdog* ]] && continue

        ERRORS=$(journalctl --no-pager -u "$unit" --since "20 sec ago" 2>/dev/null | grep -iE "reconnect limit reached|fatal|panic|tearing down|signalEnded|shutting down|i/o timeout|connection refused|no route to host" || true)

        if [ -n "$ERRORS" ]; then
            echo "[watchdog] $(date '+%H:%M:%S') $unit: errors detected, restarting..."
            echo "$ERRORS"
            systemctl restart "$unit" 2>/dev/null || true
        fi
    done < <(systemctl list-units --all --no-legend 'olcrtc-*' 2>/dev/null | awk '{print $1}')

    sleep 15
done
