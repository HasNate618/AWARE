#!/bin/bash
# Install and enable all AWARE systemd services on the board
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo aware2026 | sudo -S cp "$SCRIPT_DIR"/llama-server.service /etc/systemd/system/
echo aware2026 | sudo -S cp "$SCRIPT_DIR"/aware-bt-connect.service /etc/systemd/system/
echo aware2026 | sudo -S cp "$SCRIPT_DIR"/aware.service /etc/systemd/system/

echo aware2026 | sudo -S systemctl daemon-reload
echo aware2026 | sudo -S systemctl enable llama-server.service
echo aware2026 | sudo -S systemctl enable aware-bt-connect.service
echo aware2026 | sudo -S systemctl enable aware.service

echo "All services installed and enabled."
echo "Reboot to verify, or run: sudo systemctl start llama-server aware-bt-connect aware"
