# ── SOCA Edge Container ───────────────────────────────────────────────────────
# Runs soca-engine (FastAPI, port 8001) + soca-dashboard (Django, port 8080)
# in a single container managed by supervisord.
# Build context: repo root (soca-client-server/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps:
#   libgl1, libglib2.0-0, libgomp1  — OpenCV / ultralytics
#   supervisor                       — multi-process manager
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────────────
# Engine first (heavy: torch via ultralytics, opencv, easyocr)
COPY soca-engine/requirements.txt /tmp/engine-requirements.txt
RUN pip install --no-cache-dir -r /tmp/engine-requirements.txt

# Dashboard + gunicorn (gunicorn not in requirements.txt, add here)
COPY soca-dashboard/requirements.txt /tmp/dashboard-requirements.txt
RUN pip install --no-cache-dir -r /tmp/dashboard-requirements.txt gunicorn

# ── Copy service source ────────────────────────────────────────────────────────
COPY soca-engine/  /app/soca-engine/
COPY soca-dashboard/ /app/soca-dashboard/

# ── Create persistent data directories ────────────────────────────────────────
RUN mkdir -p \
    /app/soca-engine/yolo \
    /app/soca-engine/snapshots \
    /app/soca-engine/dlq \
    /app/soca-engine/credentials \
    /app/data \
    /var/log/supervisor

# ── Django: collect static files ──────────────────────────────────────────────
# Use a dummy SECRET_KEY so collectstatic runs at build time without failing
RUN cd /app/soca-dashboard && \
    SECRET_KEY=build-dummy python manage.py collectstatic --noinput 2>/dev/null || true

# ── Supervisor & entrypoint ────────────────────────────────────────────────────
COPY docker/edge/supervisord.conf /etc/supervisor/conf.d/soca-edge.conf
COPY docker/edge/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# soca-engine API | soca-dashboard UI
EXPOSE 8001 8080

ENTRYPOINT ["/entrypoint.sh"]
