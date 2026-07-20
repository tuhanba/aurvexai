#!/usr/bin/env python3
"""One-command five-gate LIVE arming/disarming for the owner (2026-07-17).

The owner asked for a single script instead of editing .env line by line.
This script sets the .env side of the five-gate lock in ONE command while
keeping every safety property of the gate design intact:

  * NOTHING is defaulted on. Arming requires the owner to explicitly type
    BOTH ``--token <TOKEN>`` (their human-confirm token) and the literal
    acknowledgement flag ``--yes-real-orders``. Omit either → refusal.
  * DRY-RUN by default; ``--apply`` writes (after a timestamped .env backup).
  * Gate 3 (engine mode = live) stays INTERACTIVE by design: this script
    never writes AX_MODE. The owner still confirms in Telegram
    (``/livemode confirm <TOKEN>``) and restarts — the human-confirm ritual
    is the point of that gate, not a formality.
  * Secrets: Binance keys are only CHECKED for presence (gate 5) and never
    read into logs/output; the token value is written but never echoed.
  * ``--disarm`` flips LIVE_ENABLED and LIVE_SEND_ORDERS back to false in
    one command (the reverse path must always be at least as easy).
  * No order-path code is touched anywhere — this edits configuration only;
    the adapter's gates in live_orders.py remain the enforcement.

Usage (Termius: one command per line):

    python3 scripts/arm_live_env.py --token MYTOKEN --yes-real-orders
    python3 scripts/arm_live_env.py --token MYTOKEN --yes-real-orders --apply
    python3 scripts/arm_live_env.py --disarm --apply

After --apply (arming), the remaining MANUAL steps are printed: recreate the
engine container, send the Telegram confirm, recreate again, verify /health.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))
from update_env import _LINE_RE, _read_lines  # noqa: E402


def _has_nonempty_secret(lines, key: str) -> bool:
    """True if .env assigns a non-empty value to ``key``. Value never leaves
    this function — presence is all we report."""
    for raw in lines:
        s = raw.strip()
        if s.startswith("#"):
            continue
        m = _LINE_RE.match(s)
        if m and m.group("key") == key:
            value = m.group("rest").split("#", 1)[0].strip()
            if value:
                return True
    return False


def _upsert_line(lines, key: str, value: str):
    """Upsert ``key=value`` regardless of whether the key already exists.

    apply_to_lines both refuses secret keys AND only appends keys from its
    own ALLOWED_KEYS list (a missing LIVE_* key would be silently dropped —
    found the hard way with LIVE_CANARY_RISK_PCT), so the arm script writes
    every key through this dedicated helper. Returns (new_lines, True)."""
    out, found = [], False
    for raw in lines:
        s = raw.strip()
        m = _LINE_RE.match(s) if s and not s.startswith("#") else None
        if m and m.group("key") == key:
            found = True
            ending = "\n" if raw.endswith("\n") else ""
            out.append(f"{key}={value}{ending}")
        else:
            out.append(raw)
    if not found:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"{key}={value}\n")
    return out, True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Arm (or disarm) the .env side of the five-gate LIVE lock "
                    "in one command. Dry-run by default.")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--token", default=None,
                   help="LIVE_HUMAN_CONFIRM token (min 6 chars, no spaces). "
                        "You will type the SAME token in Telegram: "
                        "/livemode confirm <TOKEN>")
    p.add_argument("--yes-real-orders", action="store_true",
                   help="required literal acknowledgement: this system will "
                        "send REAL orders to Binance USDT-M futures")
    p.add_argument("--full-size", action="store_true",
                   help="disable canary shrink: write LIVE_CANARY_RISK_PCT=100 "
                        "so live entries use FULL risk sizing (RISK_PCT) from "
                        "the first trade. Owner decision 2026-07-18 — on a "
                        "small account the 0.1%% canary produces sub-minimum-"
                        "notional orders the exchange refuses anyway.")
    p.add_argument("--canary-risk-pct", type=float, default=0.25,
                   help="LIVE_CANARY_RISK_PCT — per-trade risk %% for the FIRST "
                        "live trades (default 0.25; NOT 0.1, which is often "
                        "sub-minimum-notional). Ignored when --full-size is set. "
                        "The joint operating point (JOINT_OPERATING_POINT.md) puts "
                        "the base at 0.5%%, so 0.25%% is a half-size canary that "
                        "ramps to full base once live expectancy confirms.")
    p.add_argument("--disarm", action="store_true",
                   help="flip LIVE_ENABLED and LIVE_SEND_ORDERS back to false")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    args = p.parse_args(argv)

    env_path = args.env_file
    if not os.path.exists(env_path):
        print(f"REFUSING: {env_path} not found — create it from .env.example "
              f"first (secrets are owner-managed).")
        return 2
    lines = _read_lines(env_path)

    if args.disarm:
        new_lines, _ = _upsert_line(lines, "LIVE_ENABLED", "false")
        new_lines, _ = _upsert_line(new_lines, "LIVE_SEND_ORDERS", "false")
        print("DISARM plan:")
        print("  ~ LIVE_ENABLED=false")
        print("  ~ LIVE_SEND_ORDERS=false")
    else:
        # ---- arming: every gate input must be explicit -------------------
        if not args.token or len(args.token) < 6 or " " in args.token:
            print("REFUSING: --token <TOKEN> required (min 6 chars, no "
                  "spaces). Choose it yourself — you will confirm the SAME "
                  "token in Telegram.")
            return 2
        if not args.yes_real_orders:
            print("REFUSING: arming requires the explicit flag "
                  "--yes-real-orders (this system will place REAL orders).")
            return 2
        # Gate 5 precondition: Binance keys must already be present.
        for key in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
            if not _has_nonempty_secret(lines, key):
                print(f"REFUSING: {key} is empty/absent in {env_path}. Add a "
                      f"TRADE-ONLY (withdraw-disabled) key first — this "
                      f"script never writes secrets for you.")
                return 2
        new_lines, _ = _upsert_line(lines, "LIVE_ENABLED", "true")
        new_lines, _ = _upsert_line(new_lines, "LIVE_SEND_ORDERS", "true")
        print("ARM plan (gates 1/2/4 + token; gate 3 stays interactive):")
        print("  ~ LIVE_ENABLED=true")
        print("  ~ LIVE_SEND_ORDERS=true")
        if args.full_size:
            # LiveExecutor caps the multiplier at 1.0, so 100 simply means
            # "no shrink": live sizing == the shared RISK_PCT sizing.
            new_lines, _ = _upsert_line(new_lines, "LIVE_CANARY_RISK_PCT",
                                        "100")
            print("  ~ LIVE_CANARY_RISK_PCT=100 (FULL SIZE — canary shrink "
                  "disabled; live trades risk the full RISK_PCT)")
        else:
            cval = f"{args.canary_risk_pct:g}"
            new_lines, _ = _upsert_line(new_lines, "LIVE_CANARY_RISK_PCT", cval)
            print(f"  ~ LIVE_CANARY_RISK_PCT={cval} (half-size canary for the "
                  f"first live trades; ramp to base RISK_PCT once confirmed)")
        new_lines, _ = _upsert_line(new_lines, "LIVE_HUMAN_CONFIRM",
                                    args.token)
        print("  ~ LIVE_HUMAN_CONFIRM: set (hidden)")
        print("  ✓ BINANCE_API_KEY / SECRET present (values not read)")

    if not args.apply:
        print("\nDRY-RUN — nothing written. Re-run with --apply to write.")
        return 0

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{env_path}.backup.{ts}"
    shutil.copy2(env_path, backup)
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    print(f"\nWROTE {env_path} (backup: {backup})")

    if args.disarm:
        print("\nNext: docker compose up -d --force-recreate engine")
        return 0
    print("\nREMAINING MANUAL STEPS (gate 3 — the human confirm):")
    print("  1. docker compose up -d --force-recreate engine")
    print("  2. Telegram: /livemode confirm <your token>")
    print("  3. docker compose up -d --force-recreate engine")
    print("  4. curl -s http://127.0.0.1:5000/health   "
          "(expect \"engine_mode\": \"live\")")
    sizing = ("FULL SIZE (canary disabled — owner decision)" if args.full_size
              else "canary-sized (LIVE_CANARY_RISK_PCT)")
    print(f"First live entries are {sizing}; protective stops rest "
          f"on-exchange; reconcile enforcement + feed watchdog are active. "
          f"Watch Telegram for the first trades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
