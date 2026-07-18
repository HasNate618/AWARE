#!/bin/bash
# Deploy AWARE to the board via SSH
set -e

BOARD="${BOARD:-arduino@10.255.228.240}"
REMOTE_DIR="~/aware"

echo "Syncing to $BOARD..."
tar czf /tmp/aware-sync.tar.gz \
    --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
    --exclude='*.pyc' --exclude='models/*.gguf' \
    -C "$(dirname "$0")/.." aware/ dashboard/ scripts/ pyproject.toml AGENTS.md

scp "$BOARD:/tmp/aware-sync.tar.gz" "$BOARD:/tmp/aware-sync.tar.gz"
ssh "$BOARD" "cd $REMOTE_DIR && tar xzf /tmp/aware-sync.tar.gz"

echo "Installing services..."
ssh "$BOARD" "bash $REMOTE_DIR/scripts/install-services.sh"

echo "Restarting service..."
ssh "$BOARD" "sudo systemctl restart aware.service && echo 'Service restarted'"

echo "Deploy complete."
