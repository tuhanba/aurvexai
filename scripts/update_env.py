#!/usr/bin/env python3
"""
Safe, idempotent .env updater for the AurvexAI aggressive-paper profile.

This is the ONLY supported way to flip the 200 USDT / 2% / 10% aggressive-paper
knobs without hand-editing .env on the server. It is deliberately conservative:

  * DRY-RUN by default — prints exactly what would change and exits. Pass
    ``--apply`` to write.
  * Backs up the existing .env to ``.env.backup.<UTC timestamp>`` before writing.
  * Only ever touches the REAL config keys below. It never invents keys and never
    reads, writes, prints, or logs any secret (Binance keys, Telegram token).
  * Idempotent: an existing key's value is replaced in place (its inline comment
    is preserved); a missing key is appended once. Running twice is a no-op.

Key-name reconciliation (the task brief used fictional names — these are the
REAL keys config.py actually reads; fictional names are NOT written):

    fictional brief name        real config key            this script's flag
    ------------------------    -----------------------    ------------------
    INITIAL_PAPER_BALANCE       INITIAL_PAPER_BALANCE      --paper-balance
    RISK_PCT                    RISK_PCT                   --risk-pct
    DAILY_MAX_LOSS_PCT          MAX_DAILY_LOSS_PCT         --daily-loss
    (epoch)                     EPOCH_LABEL                --epoch-label
    MAX_OPEN_TRADES             MAX_OPEN_TRADES            --max-open-trades
    (exposure cap)              MAX_PORTFOLIO_EXPOSURE_PCT --max-exposure-pct

    EXECUTION_MODE        -> AX_MODE         (already "paper"; not touched)
    LIVE_TRADING_ENABLED  -> LIVE_ENABLED    (already false;  not touched)
    RISK_PROFILE          -> (no such key — aggression IS RISK_PCT; not written)
    MIN_RISK_PCT/MAX_RISK_PCT -> (no such key — band is RISK_PCT x modulation
                                  clamp [0.5,1.5]; not written)
    SHADOW_MODE=observer  -> SHADOW_APPLY=false (already false; not touched)
    SHADOW_AUTO_APPLY     -> SHADOW_APPLY       (already false; not touched)

Aggressive-paper safety rails this script enforces (it refuses --apply if any
fails, so a typo can't silently arm something unsafe):
    * RISK_PCT in (0, 5]            (config.validate() bound)
    * MAX_DAILY_LOSS_PCT in (0, 100]
    * INITIAL_PAPER_BALANCE > 0
    * MAX_OPEN_TRADES >= 1
It NEVER sets AX_MODE=live or LIVE_ENABLED=true.

Usage (Termius: one command per line, no && chaining):

    python3 scripts/update_env.py --paper-balance 200 --risk-pct 2.0 --daily-loss 10.0 --dry-run
    python3 scripts/update_env.py --paper-balance 200 --risk-pct 2.0 --daily-loss 10.0 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

# Real config keys this script is allowed to write, in a stable order. Anything
# not in this map is rejected — the script cannot create fictional/dead keys.
ALLOWED_KEYS = (
    "INITIAL_PAPER_BALANCE",
    "RISK_PCT",
    "MAX_DAILY_LOSS_PCT",
    "MAX_OPEN_TRADES",
    "MAX_PORTFOLIO_EXPOSURE_PCT",
    "EPOCH_LABEL",
    "MIN_QUOTE_VOLUME_24H",
    "DAILY_PROFIT_LOCK_PCT",
    "DAILY_PROFIT_FLATTEN",
    "DAILY_PROFIT_ADAPTIVE",
    "DAILY_PROFIT_PCT_CEILING",
    "REGIME_EDGE_WEIGHT_ENABLED",
    "DAY_BOUNDARY_OFFSET_HOURS",
)

# Keys whose values are secrets — this script must never touch or print them.
SECRET_KEYS = frozenset({
    "BINANCE_API_KEY", "BINANCE_API_SECRET",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LIVE_HUMAN_CONFIRM",
})

_LINE_RE = re.compile(r"^(?P<key>[A-Z0-9_]+)\s*=(?P<rest>.*)$")


def _value_and_comment(rest: str) -> Tuple[str, str]:
    """Robustly split the part after '=' into (value, comment_suffix).

    comment_suffix includes the original whitespace + '# ...' or is ''.
    """
    hash_idx = rest.find("#")
    if hash_idx == -1:
        return rest.strip(), ""
    value = rest[:hash_idx].strip()
    comment_suffix = rest[len(rest[:hash_idx].rstrip()):]  # whitespace + comment
    return value, comment_suffix


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Idempotently update the AurvexAI .env aggressive-paper knobs "
                    "(dry-run by default). Never touches secrets or live flags.")
    p.add_argument("--env-file", default=".env",
                   help="path to the .env file to update (default: .env)")
    p.add_argument("--paper-balance", type=float, default=None,
                   help="INITIAL_PAPER_BALANCE, e.g. 200")
    p.add_argument("--risk-pct", type=float, default=None,
                   help="RISK_PCT (max NET %% loss per trade), e.g. 2.0")
    p.add_argument("--daily-loss", type=float, default=None,
                   help="MAX_DAILY_LOSS_PCT (kill-switch), e.g. 10.0")
    p.add_argument("--max-open-trades", type=int, default=None,
                   help="MAX_OPEN_TRADES, e.g. 4")
    p.add_argument("--max-exposure-pct", type=float, default=None,
                   help="MAX_PORTFOLIO_EXPOSURE_PCT (total notional cap). "
                        "Raise (e.g. 400) so 4 full-size 2%% trades coexist.")
    p.add_argument("--epoch-label", type=str, default=None,
                   help="EPOCH_LABEL for a clean forward-test epoch, e.g. aggr200_v1. "
                        "Apply, then run `python main.py reset` (shadow history is "
                        "preserved; open paper trades + ledger reset).")
    p.add_argument("--min-quote-volume", type=float, default=None,
                   help="MIN_QUOTE_VOLUME_24H liquidity floor in USDT, e.g. "
                        "10000000 (10M). The f_liquidity safety filter rejects "
                        "signals on coins below this 24h quote volume.")
    p.add_argument("--profit-lock-pct", type=float, default=None,
                   help="DAILY_PROFIT_LOCK_PCT — daily profit target %% of "
                        "balance (e.g. 4).")
    p.add_argument("--profit-flatten", dest="profit_flatten",
                   action="store_const", const=True, default=None,
                   help="DAILY_PROFIT_FLATTEN=true — at the target, CLOSE all "
                        "positions on a mark-to-market basis (don't wait for "
                        "trades to close) and lock entries for the day.")
    p.add_argument("--no-profit-flatten", dest="profit_flatten",
                   action="store_const", const=False,
                   help="DAILY_PROFIT_FLATTEN=false — realized-only lock that "
                        "blocks new entries but never closes open trades.")
    p.add_argument("--profit-adaptive", dest="profit_adaptive",
                   action="store_const", const=True, default=None,
                   help="DAILY_PROFIT_ADAPTIVE=true — scale the daily target "
                        "between the profit-lock %% (floor) and the ceiling by "
                        "the measured BTC-4h trend regime.")
    p.add_argument("--no-profit-adaptive", dest="profit_adaptive",
                   action="store_const", const=False,
                   help="DAILY_PROFIT_ADAPTIVE=false — flat daily target.")
    p.add_argument("--profit-ceiling-pct", type=float, default=None,
                   help="DAILY_PROFIT_PCT_CEILING — the target %% used in a "
                        "strong trend when adaptive is on (e.g. 10).")
    p.add_argument("--regime-edge-weight", dest="regime_edge",
                   action="store_const", const=True, default=None,
                   help="REGIME_EDGE_WEIGHT_ENABLED=true — tilt per-entry risk "
                        "by BTC-4h trend regime and per-leg validated Sharpe "
                        "(holdout-validated; sizing only, within the band).")
    p.add_argument("--no-regime-edge-weight", dest="regime_edge",
                   action="store_const", const=False,
                   help="REGIME_EDGE_WEIGHT_ENABLED=false — flat risk sizing.")
    p.add_argument("--day-offset-hours", type=float, default=None,
                   help="DAY_BOUNDARY_OFFSET_HOURS — shift ALL daily counters "
                        "off UTC. 3 = daily window resets at 00:00 Türkiye "
                        "saati (UTC+3). 0 = UTC midnight.")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--apply", action="store_true",
                     help="actually write the file (default is dry-run)")
    grp.add_argument("--dry-run", action="store_true",
                     help="explicitly request a dry-run (the default)")
    p.add_argument("--no-backup", action="store_true",
                   help="skip the .env.backup.<ts> copy on --apply (not recommended)")
    return p.parse_args(argv)


def collect_changes(args: argparse.Namespace) -> Dict[str, str]:
    """Map provided flags to {REAL_KEY: value_str}. Only set keys are returned."""
    changes: Dict[str, str] = {}
    if args.paper_balance is not None:
        changes["INITIAL_PAPER_BALANCE"] = _fmt_num(args.paper_balance)
    if args.risk_pct is not None:
        changes["RISK_PCT"] = _fmt_num(args.risk_pct)
    if args.daily_loss is not None:
        changes["MAX_DAILY_LOSS_PCT"] = _fmt_num(args.daily_loss)
    if args.max_open_trades is not None:
        changes["MAX_OPEN_TRADES"] = str(int(args.max_open_trades))
    if args.max_exposure_pct is not None:
        changes["MAX_PORTFOLIO_EXPOSURE_PCT"] = _fmt_num(args.max_exposure_pct)
    if args.epoch_label is not None:
        changes["EPOCH_LABEL"] = args.epoch_label.strip()
    if args.min_quote_volume is not None:
        changes["MIN_QUOTE_VOLUME_24H"] = _fmt_num(args.min_quote_volume)
    if args.profit_lock_pct is not None:
        changes["DAILY_PROFIT_LOCK_PCT"] = _fmt_num(args.profit_lock_pct)
    if args.profit_flatten is not None:
        changes["DAILY_PROFIT_FLATTEN"] = "true" if args.profit_flatten else "false"
    if args.profit_adaptive is not None:
        changes["DAILY_PROFIT_ADAPTIVE"] = "true" if args.profit_adaptive else "false"
    if args.profit_ceiling_pct is not None:
        changes["DAILY_PROFIT_PCT_CEILING"] = _fmt_num(args.profit_ceiling_pct)
    if args.regime_edge is not None:
        changes["REGIME_EDGE_WEIGHT_ENABLED"] = ("true" if args.regime_edge
                                                 else "false")
    if args.day_offset_hours is not None:
        changes["DAY_BOUNDARY_OFFSET_HOURS"] = _fmt_num(args.day_offset_hours)
    return changes


def _fmt_num(v: float) -> str:
    """Render a float without a trailing '.0' when it is integral (200.0 -> 200)."""
    if float(v).is_integer():
        return str(int(v))
    return repr(float(v))


def validate_changes(changes: Dict[str, str]) -> List[str]:
    """Return a list of human-readable errors (empty = OK). Safety rails only."""
    errors: List[str] = []
    for k in changes:
        if k not in ALLOWED_KEYS:
            errors.append(f"refusing to write non-allowed key {k!r}")
        if k in SECRET_KEYS:
            errors.append(f"refusing to write secret key {k!r}")
    if "RISK_PCT" in changes:
        v = float(changes["RISK_PCT"])
        if not (0 < v <= 5):
            errors.append(f"RISK_PCT={v} out of safe range (0, 5] (config.validate bound)")
    if "MAX_DAILY_LOSS_PCT" in changes:
        v = float(changes["MAX_DAILY_LOSS_PCT"])
        if not (0 < v <= 100):
            errors.append(f"MAX_DAILY_LOSS_PCT={v} out of range (0, 100]")
    if "INITIAL_PAPER_BALANCE" in changes:
        if float(changes["INITIAL_PAPER_BALANCE"]) <= 0:
            errors.append("INITIAL_PAPER_BALANCE must be > 0")
    if "MAX_OPEN_TRADES" in changes:
        if int(changes["MAX_OPEN_TRADES"]) < 1:
            errors.append("MAX_OPEN_TRADES must be >= 1")
    if "MAX_PORTFOLIO_EXPOSURE_PCT" in changes:
        if float(changes["MAX_PORTFOLIO_EXPOSURE_PCT"]) <= 0:
            errors.append("MAX_PORTFOLIO_EXPOSURE_PCT must be > 0")
    if "MIN_QUOTE_VOLUME_24H" in changes:
        v = float(changes["MIN_QUOTE_VOLUME_24H"])
        if not (1_000_000 <= v <= 1_000_000_000):
            errors.append(f"MIN_QUOTE_VOLUME_24H={v:,.0f} outside sane range "
                          "[1M, 1B] USDT — the liquidity floor exists for "
                          "fill quality, refusing")
    if "DAILY_PROFIT_LOCK_PCT" in changes:
        v = float(changes["DAILY_PROFIT_LOCK_PCT"])
        if not (0 < v <= 100):
            errors.append(f"DAILY_PROFIT_LOCK_PCT={v} out of range (0, 100]")
    if "DAY_BOUNDARY_OFFSET_HOURS" in changes:
        v = float(changes["DAY_BOUNDARY_OFFSET_HOURS"])
        if not (-12 <= v <= 14):
            errors.append(f"DAY_BOUNDARY_OFFSET_HOURS={v} out of range [-12, 14]")
    if "DAILY_PROFIT_PCT_CEILING" in changes:
        v = float(changes["DAILY_PROFIT_PCT_CEILING"])
        if not (0 < v <= 100):
            errors.append(f"DAILY_PROFIT_PCT_CEILING={v} out of range (0, 100]")
    return errors


def apply_to_lines(lines: List[str], changes: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Return (new_lines, change_log). Idempotent in-place upsert.

    Secret lines are passed through untouched and never logged.
    """
    seen = set()
    out: List[str] = []
    change_log: List[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        m = _LINE_RE.match(line.strip()) if line.strip() and not line.lstrip().startswith("#") else None
        if not m:
            out.append(raw)
            continue
        key = m.group("key")
        if key in SECRET_KEYS:
            out.append(raw)              # never touch / inspect secret values
            continue
        if key in changes:
            old_value, comment_suffix = _value_and_comment(m.group("rest"))
            new_value = changes[key]
            seen.add(key)
            if old_value == new_value:
                out.append(raw)          # idempotent: unchanged
                change_log.append(f"  = {key} already {new_value} (no change)")
            else:
                newline_ending = "\n" if raw.endswith("\n") else ""
                out.append(f"{key}={new_value}{comment_suffix}{newline_ending}")
                change_log.append(f"  ~ {key}: {old_value} -> {new_value}")
        else:
            out.append(raw)
    # Append any keys not already present.
    appended = [k for k in ALLOWED_KEYS if k in changes and k not in seen]
    if appended:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append("\n# -- aggressive-paper profile (added by scripts/update_env.py) --\n")
        for k in appended:
            out.append(f"{k}={changes[k]}\n")
            change_log.append(f"  + {k}={changes[k]} (appended)")
    return out, change_log


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    apply = bool(args.apply)  # default (no flag, or --dry-run) => dry-run

    changes = collect_changes(args)
    if not changes:
        print("No changes requested. Pass e.g. --paper-balance 200 --risk-pct 2.0 "
              "--daily-loss 10.0 [--apply]. Nothing to do.")
        return 0

    errors = validate_changes(changes)
    if errors:
        print("REFUSING to proceed — validation failed:")
        for e in errors:
            print(f"  ! {e}")
        return 2

    env_path = args.env_file
    if not os.path.exists(env_path):
        # Seed from .env.example if available so a fresh server still gets the
        # real (secret-free) key set. .env.example carries blank secrets only.
        example = os.path.join(os.path.dirname(env_path) or ".", ".env.example")
        if os.path.exists(example):
            print(f"{env_path} not found — seeding from {example} (secrets stay blank).")
            base_lines = _read_lines(example)
        else:
            print(f"{env_path} not found and no .env.example to seed from; "
                  f"a new {env_path} will be created with only the requested keys.")
            base_lines = []
    else:
        base_lines = _read_lines(env_path)

    new_lines, change_log = apply_to_lines(base_lines, changes)

    print(f"Target file : {env_path}")
    print(f"Mode        : {'APPLY (writing)' if apply else 'DRY-RUN (no write)'}")
    print("Reconciled keys (real config keys only; no fictional keys, no secrets):")
    for k in ALLOWED_KEYS:
        if k in changes:
            print(f"  {k} = {changes[k]}")
    print("Planned changes:")
    if change_log:
        for c in change_log:
            print(c)
    else:
        print("  (none — file already matches; idempotent no-op)")

    if not apply:
        print("\nDry-run only. Re-run with --apply to write. A backup "
              ".env.backup.<timestamp> is made before writing.")
        return 0

    # Backup then write.
    if os.path.exists(env_path) and not args.no_backup:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = f"{env_path}.backup.{ts}"
        shutil.copy2(env_path, backup)
        print(f"\nBacked up {env_path} -> {backup}")

    with open(env_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    print(f"Wrote {env_path}.")
    if "EPOCH_LABEL" in changes:
        print("\nEPOCH_LABEL changed. To start the clean forward-test epoch run "
              "`python main.py reset` (IRREVERSIBLE: open paper trades + ledger "
              "reset to the new balance; shadow learning history is PRESERVED).")
    return 0


def _read_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.readlines()


if __name__ == "__main__":
    sys.exit(main())
