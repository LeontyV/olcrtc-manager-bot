#!/bin/bash
# olcrtc-wrapper — exits with code 1 on "reconnect limit reached"
# systemd Restart=always picks this up and restarts the service
BIN="$1"
shift

found=0
while IFS= read -r line; do
    echo "$line"
    if [[ "$line" == *"reconnect limit reached"* ]]; then
        found=1
        break
    fi
done < <("$BIN" "$@" 2>&1)

if [ "$found" = "1" ]; then
    echo "[wrapper] reconnect limit reached, restarting..." >&2
    exit 1
fi
