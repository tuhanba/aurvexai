#!/usr/bin/env bash
# Tail logs. Optional arg: engine | dashboard
set -e
cd "$(dirname "$0")/.."
if [ -n "$1" ]; then
  docker compose logs -f --tail=200 "$1"
else
  docker compose logs -f --tail=200
fi
