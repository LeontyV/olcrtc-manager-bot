#!/bin/bash
# olcrtc wrapper — exits with code 1 on "reconnect limit reached"
# systemd Restart=always picks this up and restarts the service
set -m
trap 'exit 1' TERM

BIN="$1"
shift

"$BIN" "$@" > >(
    while IFS= read -r line; do
        echo "$line"
        if [[ "$line" == *"reconnect limit reached"* ]]; then
            echo "[olcrtc-wrapper] reconnect limit reached — requesting restart" >&2
            kill -TERM $$ 2>/dev/null
        fi
    done
) 2>&1 &

wait $!
