#!/usr/bin/env python3
"""
AurvexAI entrypoint.

Usage:
    python main.py engine      # run the live paper engine loop (uses DATA_PROVIDER)
    python main.py dashboard   # run the Flask dashboard on DASHBOARD_PORT
    python main.py demo        # fast synthetic end-to-end run (offline, ~40 cycles)
    python main.py backtest    # offline seeded backtest, prints metrics JSON

All configuration comes from the environment / .env (see .env.example).
No secrets are read from anywhere but the environment. Live trading is OFF.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from aurvex.config import load_config  # noqa: E402


def _print_help() -> None:
    print(__doc__)


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    cmd = argv[0]
    cfg = load_config()
    cfg.validate()

    if cmd == "engine":
        from aurvex.engine import run_engine
        run_engine(cfg)
        return 0

    if cmd == "dashboard":
        from aurvex.dashboard.app import run_dashboard
        run_dashboard(cfg)
        return 0

    if cmd == "demo":
        # Force the synthetic provider so it runs with no network/keys.
        cfg.data_provider = "synthetic"
        from aurvex.engine import run_engine
        cycles = int(os.environ.get("DEMO_CYCLES", "40"))
        run_engine(cfg, max_cycles=cycles, sleep_override=0.0)
        return 0

    if cmd == "backtest":
        from aurvex.backtest import run_backtest_offline
        bars = int(os.environ.get("BACKTEST_BARS", "1500"))
        metrics = run_backtest_offline(cfg, bars=bars)
        print(json.dumps(metrics, indent=2, default=str))
        return 0

    print(f"unknown command: {cmd}\n")
    _print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
