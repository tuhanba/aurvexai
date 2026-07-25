#!/usr/bin/env python3
"""Apply THIS session's .env additions on top of the paper block.

Run AFTER scripts/apply_fast_paper_env.py --apply. Adds only what this session
introduced, on the same safety rails as update_env.py / apply_fast_paper_env.py:

  * DRY-RUN by default; pass --apply to write.
  * Backs up .env to .env.backup.<UTC timestamp> first.
  * Never reads/prints/writes secrets; secret lines pass through untouched.
  * NEVER arms live (re-asserts AX_MODE=paper / LIVE_* false is not even
    attempted here — this script simply refuses any live-ish key/value).
  * Idempotent: values replaced in place, missing keys appended once.

What it writes and WHY:

1. Data-fetch resilience — the real fix for "the engine never opens trades on a
   flaky link". A single failed fetch_order_book used to discard the whole
   snapshot (symbol skipped, no trade) and ccxt had no explicit timeout/retry.
   These give FRESHER data, so the stale-entry guard fires LESS. No safety guard
   is weakened.

2. Observational regime stack — the multi-dimensional regime read, its Telegram
   change alert and the advisory drift monitor. These are MONITORING only: the
   regime ensemble does not size or gate anything in this configuration.

DELIBERATELY NOT WRITTEN: REGIME_MATRIX_ENABLED / REGIME_MATRIX_TILT /
REGIME_DYNAMIC_RISK_ENABLED. The claim that regime allocation earns more was
RETRACTED after a corrected measurement (docs/research/
REGIME_ALLOCATION_RETRACTION.md): on the full 12-coin universe it is +0.01 mean
ΔSharpe in 2/5 folds, i.e. nothing, because a regime cell's past edge does not
predict its future edge (correlation −0.05). Those flags stay OFF.

Usage (Termius: one command per line, no && chaining):

    python3 scripts/apply_session_env.py            # dry-run, shows diff
    python3 scripts/apply_session_env.py --apply    # writes .env
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))
from update_env import SECRET_KEYS, apply_to_lines, _read_lines  # noqa: E402

BLOCK = {
    # --- 1) data-fetch resilience (network robustness) ---
    # Explicit HTTP timeout so a slow link fails fast enough to retry INSIDE the
    # cycle instead of hanging (ccxt's own default is 10s).
    "FETCH_TIMEOUT_MS": "15000",
    # Retries on a failed public fetch (klines / order book / tickers). A
    # transient blip no longer costs the whole snapshot. 0 = old behaviour.
    "FETCH_RETRIES": "2",
    "FETCH_RETRY_BACKOFF_MS": "400",

    # --- 2) observational regime stack (monitoring only) ---
    # Computes + stores the multi-dimensional regime read for the dashboard
    # Regime card, /api/regime and the governor's REGIME_ADVISORY section.
    # Sizing and gating are untouched by this flag.
    "REGIME_ENSEMBLE_ENABLED": "true",
    # Telegram alert on a CONFIRMED regime change (hysteresis-gated, so rare).
    "REGIME_ALERTS_ENABLED": "true",
    # Advisory per-leg health state machine (ACTIVE -> REDUCED -> SHADOW_ONLY ->
    # REVIEW). It only RECOMMENDS; it never flips a flag or blocks a trade.
    "DRIFT_MONITOR_ENABLED": "true",
}

# Never produce these, and never touch a live/secret key from this script.
FORBIDDEN_KEYS = {"AX_MODE", "LIVE_ENABLED", "LIVE_SEND_ORDERS",
                  "LIVE_HUMAN_CONFIRM"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Apply this session's .env additions (dry-run by default; "
                    "never touches secrets, never arms live).")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    args = p.parse_args(argv)

    for k in BLOCK:
        if k in SECRET_KEYS or k in FORBIDDEN_KEYS:
            print(f"REFUSING: unsafe key {k}")
            return 2

    env_path = args.env_file
    if not os.path.exists(env_path):
        print(f"ERROR: {env_path} not found. Run "
              f"scripts/apply_fast_paper_env.py --apply first.")
        return 2

    new_lines, change_log = apply_to_lines(_read_lines(env_path), dict(BLOCK))
    print(f"Target file : {env_path}")
    print(f"Mode        : {'APPLY (writing)' if args.apply else 'DRY-RUN (no write)'}")
    print("Planned changes:")
    for c in change_log or ["  (none — file already matches; no-op)"]:
        print(c)
    print("\nNOTE: regime matrix/tilt/dynamic-risk are intentionally NOT set — "
          "that earn-more claim was retracted (see "
          "docs/research/REGIME_ALLOCATION_RETRACTION.md).")
    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write "
              "(a .env.backup.<timestamp> is made first).")
        return 0
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = f"{env_path}.backup.{ts}"
    shutil.copy2(env_path, backup)
    print(f"Backed up {env_path} -> {backup}")
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    print(f"Wrote {env_path}. Restart to load: docker compose down, "
          "then docker compose up -d --build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
