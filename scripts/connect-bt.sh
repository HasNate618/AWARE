#!/bin/bash
# Connect BT speaker before AWARE starts
set -e
MAC="15:D2:D2:C5:6B:0C"
for i in $(seq 1 10); do
    if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
        exit 0
    fi
    bluetoothctl connect "$MAC" >/dev/null 2>&1
    sleep 2
done
exit 1
