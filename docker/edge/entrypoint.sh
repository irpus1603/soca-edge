#!/bin/sh
set -e

# ── soca-dashboard: run Django migrations ─────────────────────────────────────
echo "[entrypoint] Running soca-dashboard migrations..."
cd /app/soca-dashboard
python manage.py migrate --noinput

# ── soca-engine: ensure data directory exists ─────────────────────────────────
mkdir -p /app/data /app/soca-engine/yolo /app/soca-engine/snapshots /app/soca-engine/dlq

# ── Start both services via supervisord ───────────────────────────────────────
echo "[entrypoint] Starting soca-engine and soca-dashboard via supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
