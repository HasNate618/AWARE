#!/bin/bash
# View AWARE service logs on the board
set -e

BOARD="${BOARD:-aware@uno-q.local}"

echo "Tailing AWARE logs on $BOARD (Ctrl+C to stop)..."
ssh "$BOARD" "journalctl -f -u aware.service"
