#!/usr/bin/env bash
# Download the Kokoro ONNX model + voices into ./models (idempotent).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  if [ ! -s "models/$f" ]; then
    echo "downloading $f"; curl -sSL --retry 3 -o "models/$f" "$BASE/$f"
  fi
done
ls -la models
