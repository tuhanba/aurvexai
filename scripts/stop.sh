#!/usr/bin/env bash
# Stop and remove containers (named volume / data is preserved).
set -e
cd "$(dirname "$0")/.."
docker compose down
echo "Stopped. Data volume preserved."
