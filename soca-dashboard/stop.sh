#!/bin/sh
# Stop all soca-dashboard processes gracefully

cd "$(dirname "$0")"

echo "Stopping soca-dashboard..."

pkill -TERM -f "gunicorn dashboard.wsgi" 2>/dev/null && echo "  stopped gunicorn" || true
pkill -TERM -f "manage.py runserver" 2>/dev/null && echo "  stopped runserver" || true

sleep 2
pkill -KILL -f "gunicorn dashboard.wsgi" 2>/dev/null || true
pkill -KILL -f "manage.py runserver" 2>/dev/null || true

echo "Done."
