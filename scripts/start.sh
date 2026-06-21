#!/usr/bin/env bash
# Build (if needed) and start engine + dashboard in the background.
set -e
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill it in."
  exit 1
fi
docker compose up -d --build
echo "Started. Dashboard: http://<server-ip>:5000"
