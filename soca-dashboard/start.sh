#!/bin/sh
set -e

# Always run from the script's own directory
cd "$(dirname "$0")"

python manage.py migrate --noinput

exec python manage.py runserver "0.0.0.0:${PORT:-8080}"
