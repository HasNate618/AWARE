#!/bin/bash
# Download Piper voice model for AWARE TTS (run on board).
set -euo pipefail

MODEL_DIR="${1:-models}"
VOICE="en_US-lessac-medium"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

mkdir -p "$MODEL_DIR"
for ext in onnx "onnx.json"; do
    file="${VOICE}.${ext}"
    dest="${MODEL_DIR}/${file}"
    if [[ -f "$dest" ]]; then
        echo "Already have $dest"
        continue
    fi
    echo "Downloading $file..."
    curl -fL "${BASE}/${file}" -o "$dest"
done
echo "Piper model ready in $MODEL_DIR"
