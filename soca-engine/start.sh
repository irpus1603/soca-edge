#!/bin/sh
set -e

# Always run from the script's own directory
cd "$(dirname "$0")"

# Start MediaMTX in background (run from its own folder)
(cd MediaMTX && ./mediamtx mediamtx.yml) &

exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8001}"
