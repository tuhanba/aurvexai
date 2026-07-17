"""
Shared logging setup (P0.2 — log hygiene + rotation).

One place both entrypoints (engine, dashboard) configure logging so:

* the level/format is consistent and env-driven (LOG_LEVEL);
* an optional ROTATING file log (LOG_FILE + LOG_MAX_BYTES/LOG_BACKUP_COUNT)
  captures history without unbounded growth — during the 2026-07-16 triage the
  container logs were the only record and dashboard debug spam drowned them;
* noisy third-party loggers (werkzeug per-request lines, urllib3/ccxt wire
  chatter) are capped at WARNING unless LOG_LEVEL=DEBUG is explicitly set, so
  the engine's own INFO lines stay readable.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_NOISY_LOGGERS = ("werkzeug", "urllib3", "requests", "ccxt", "waitress")

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(cfg, component: str = "engine") -> None:
    """Configure root logging for a process. Idempotent enough to call once
    per entrypoint; never raises (a logging misconfig must not stop trading
    safety code from running)."""
    level = getattr(logging, str(cfg.log_level).upper(), logging.INFO)
    logging.basicConfig(level=level, format=_FORMAT)

    # Cap noisy libraries unless the operator explicitly asked for DEBUG.
    if level > logging.DEBUG:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    log_file = getattr(cfg, "log_file", "") or ""
    if not log_file:
        return
    try:
        # Per-component file so engine and dashboard never interleave:
        # LOG_FILE=data/logs/aurvex.log → data/logs/aurvex.engine.log
        root_part, ext = os.path.splitext(log_file)
        path = f"{root_part}.{component}{ext or '.log'}"
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=max(1_000_000, int(cfg.log_max_bytes)),
            backupCount=max(1, int(cfg.log_backup_count)))
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.setLevel(level)
        logging.getLogger().addHandler(handler)
        logging.getLogger("aurvex.logging").info(
            "rotating file log enabled: %s (maxBytes=%d backups=%d)",
            path, cfg.log_max_bytes, cfg.log_backup_count)
    except Exception as exc:  # pragma: no cover - defensive
        logging.getLogger("aurvex.logging").error(
            "file logging setup failed (continuing on stderr): %s", exc)
