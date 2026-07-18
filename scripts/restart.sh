#!/bin/bash
# Restart AWARE service on the board
set -e

BOARD="${BOARD:-aware@uno-q.local}"

echo "Restarting AWARE on $BOARD..."
ssh "$BOARD" "sudo systemctl restart aware.service && echo 'Service restarted'"

echo "Checking status..."
ssh "$BOARD" "sudo systemctl status aware.service --no-pager"
