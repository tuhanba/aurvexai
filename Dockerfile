# AurvexAI clean-core image (CPU-only, slim)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC

WORKDIR /app

# Dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application
COPY src/ ./src/
COPY main.py ./
# Analysis / ops scripts (e.g. scripts/decompose_edge.py — run via
# `docker compose exec engine python scripts/<name>.py`). Read-only tooling;
# the engine/dashboard CMDs do not depend on it.
COPY scripts/ ./scripts/

# Data dir (SQLite WAL lives here; mounted as a volume in compose)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 5000

# Default command runs the paper engine; compose overrides for the dashboard.
CMD ["python", "main.py", "engine"]
