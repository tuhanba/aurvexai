#!/usr/bin/env bash
# Print container status and the dashboard health endpoint.
set -e
cd "$(dirname "$0")/.."
docker compose ps
echo "---"
curl -fsS http://localhost:5000/health || echo "dashboard /health not reachable"
echo
