#!/bin/sh
# Stop all soca-engine processes gracefully

cd "$(dirname "$0")"

echo "Stopping soca-engine..."

pkill -TERM -f "uvicorn main:app" 2>/dev/null && echo "  stopped uvicorn" || true
pkill -TERM -f "mediamtx" 2>/dev/null && echo "  stopped mediamtx" || true

sleep 2
pkill -KILL -f "uvicorn main:app" 2>/dev/null || true
pkill -KILL -f "mediamtx" 2>/dev/null || true

echo "Done."
