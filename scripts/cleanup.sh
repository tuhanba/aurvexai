#!/usr/bin/env bash
# ============================================================================
# AurvexAI server cleanup — SAFE, reversible, DATA-PROTECTED.
#
# Frees disk by removing regenerable build/test artifacts and docker dangling
# images + build cache. It MEASURES first, then cleans in layers.
#
# ABSOLUTE GUARANTEES — this script NEVER:
#   * touches the `aurvex-data` docker volume,
#   * deletes `data/` or any `*.db` / `*.db-wal` / `*.db-shm`,
#   * runs `docker volume prune` or `docker system prune --volumes`.
# All paper + shadow evidence lives in those, so they are off-limits.
#
# Usage:
#   scripts/cleanup.sh                # audit + safe cleanup (default)
#   scripts/cleanup.sh --destructive  # also TRUNCATE (not delete) large *.log
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTRUCTIVE=0
[ "${1:-}" = "--destructive" ] && DESTRUCTIVE=1

echo "=== AurvexAI cleanup ==="
echo "repo : $REPO_DIR"
echo "mode : $([ "$DESTRUCTIVE" -eq 1 ] && echo 'DESTRUCTIVE (audit + safe + truncate logs)' || echo 'safe (audit + safe layer)')"

# ---------------------------------------------------------------------------
# 1) AUDIT — measure, change nothing.
# ---------------------------------------------------------------------------
echo
echo "--- disk audit (no changes) ---"
df -h "$REPO_DIR" 2>/dev/null || true
du -sh "$REPO_DIR" 2>/dev/null || true
[ -d "$REPO_DIR/data" ] && du -sh "$REPO_DIR/data" 2>/dev/null || true
if command -v docker >/dev/null 2>&1; then
  docker system df 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 2) SAFE layer — regenerable artifacts only (always runs).
# ---------------------------------------------------------------------------
echo
echo "--- safe cleanup: repo build/test artifacts ---"
find "$REPO_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$REPO_DIR" -type f -name '*.py[cod]' -delete 2>/dev/null || true
rm -rf "$REPO_DIR/.pytest_cache" "$REPO_DIR/build" "$REPO_DIR/dist" \
       "$REPO_DIR"/*.egg-info 2>/dev/null || true
find "$REPO_DIR" -type f \( -name '.DS_Store' -o -name '*.swp' \) -delete 2>/dev/null || true
echo "  done (caches / pyc / build / dist)."

if command -v docker >/dev/null 2>&1; then
  echo "--- safe cleanup: docker dangling images + build cache (NOT volumes) ---"
  docker image prune -f 2>/dev/null || true
  docker builder prune -f 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 3) DESTRUCTIVE layer — opt-in. Truncate (never delete) large logs.
#    Explicitly excludes anything under data/ and never deletes a file.
# ---------------------------------------------------------------------------
if [ "$DESTRUCTIVE" -eq 1 ]; then
  echo
  echo "--- destructive: truncating *.log > 50M (excluding data/) ---"
  find "$HOME" -maxdepth 4 -type f -name '*.log' -size +50M \
       -not -path '*/data/*' -print -exec truncate -s 0 {} \; 2>/dev/null || true
  echo
  echo "NOTE: removing an old 'trade-engine' clone is NOT automated (it is the"
  echo "      biggest space win but irreversible). Review and delete it yourself:"
  echo "        du -sh ~/trade-engine 2>/dev/null"
fi

# ---------------------------------------------------------------------------
# Post-audit + protected-list reminder.
# ---------------------------------------------------------------------------
echo
echo "--- post-cleanup disk ---"
df -h "$REPO_DIR" 2>/dev/null || true
echo
echo "PROTECTED (never touched): aurvex-data volume, data/, *.db*"
echo "NEVER run:                 docker volume prune | docker system prune --volumes"
echo "=== done ==="
