#!/bin/bash
# Connect paired BT speaker if disconnected. Args: [retry_count]
MAC="${AWARE_BT_SPEAKER_MAC:-15:D2:D2:C5:6B:0C}"
TRIES="${1:-1}"

for _ in $(seq 1 "$TRIES"); do
    if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
        exit 0
    fi
    bluetoothctl connect "$MAC" >/dev/null 2>&1 || true
    sleep 2
done
# Exit 0 so periodic timers do not mark the unit failed.
exit 0
