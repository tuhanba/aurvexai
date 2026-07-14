#!/usr/bin/env python3
"""One-command applier for the SYSTEM_STATE §6 paper block (fast variant).

Writes the owner-selected validated deployment .env block — donchian n=10 +
squeeze@4h q=30 ("more action" package) — without hand-editing .env.
Built on the same rails as scripts/update_env.py:

  * DRY-RUN by default; pass --apply to write.
  * Backs up .env to .env.backup.<UTC timestamp> before writing.
  * Never reads, prints or writes secrets (Binance keys, Telegram token,
    LIVE_HUMAN_CONFIRM) — those lines pass through untouched.
  * NEVER arms live: it only ever writes AX_MODE=paper, LIVE_ENABLED=false,
    LIVE_SEND_ORDERS=false (re-asserting the disarmed state is the point).
  * Idempotent: replaces values in place (inline comments preserved),
    appends missing keys once; running twice is a no-op.
  * --baseline writes the same block WITHOUT the :n=10 / :q=30 fast options.

Usage (Termius: one command per line, no && chaining):

    python3 scripts/apply_fast_paper_env.py            # dry-run, shows diff
    python3 scripts/apply_fast_paper_env.py --apply    # writes .env
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))
from update_env import SECRET_KEYS, apply_to_lines, _read_lines  # noqa: E402

U12 = "BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TON+TRX+DOT"
U17 = ("BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,"
       "XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,"
       "LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,"
       "NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,"
       "ATOM/USDT:USDT")

MAJORS = "BTC+ETH+SOL+BNB+XRP"

# Owner decision 2026-07-09: ichimoku ACTIVE (shadow-only removed) and the
# walkforward-ACCEPTED band_walk@4h added on its validated majors universe
# (net +0.082R, PF 1.17, DSR +2.43 — scripts/harness_bandwalk.py).
STRATEGIES_FAST = (
    "donchian_trend@4h/1d:n=10 "
    f"squeeze_breakout@1h/4h:ts=24:u={U12} "
    "squeeze_breakout@4h/1d:ts=24:q=30 "
    "ichimoku_trend@4h/1d "
    f"band_walk@4h/1d:ts=12:u={MAJORS}")
STRATEGIES_BASE = (
    "donchian_trend@4h/1d "
    f"squeeze_breakout@1h/4h:ts=24:u={U12} "
    "squeeze_breakout@4h/1d:ts=24 "
    "ichimoku_trend@4h/1d "
    f"band_walk@4h/1d:ts=12:u={MAJORS}")

BLOCK = {
    "RISK_PROFILE": "aggressive_paper",
    "INITIAL_PAPER_BALANCE": "200",
    "STRATEGIES": STRATEGIES_FAST,          # or STRATEGIES_BASE (--baseline)
    "SHADOW_ONLY_SETUPS": "",               # ichimoku promoted to active
    "GLOBAL_RANKING": "true",
    "RANK_KEY": "edge",
    "LTF_LIMIT": "525",
    "RISK_PCT": "1.5",
    "MAX_OPEN_TRADES": "6",
    # Owner decision 2026-07-12: 300% (was 200%) so the notional cap stops
    # binding at ~4-5 positions and all 6 slots can fill -> more coins open at
    # once. TRADE-OFF: higher total notional exposure = larger correlated
    # drawdown if every long moves together; ~6 positions all-stopping is
    # ~9% (near the 10% daily kill switch). Per-trade risk is unchanged.
    "MAX_PORTFOLIO_EXPOSURE_PCT": "300",
    "MAX_LEVERAGE": "10",
    "UNIVERSE_SIZE": "17",
    "UNIVERSE_INCLUDE": U17,
    "MIN_QUOTE_VOLUME_24H": "10000000",     # 10M — pinned coins clear it in quiet markets
    # Owner decision 2026-07-11: take profit and stop for the day at +4% on a
    # MARK-TO-MARKET basis — the moment intraday total (realized+unrealized)
    # gain hits +4% of the day-open equity, CLOSE all positions and lock new
    # entries (don't wait for trades to close). Daily window rolls at 00:00
    # Türkiye saati (UTC+3), when the lock releases and trading resumes.
    "DAILY_PROFIT_LOCK_PCT": "4",
    "DAILY_PROFIT_FLATTEN": "true",
    # Owner objective 2026-07-14: MAXIMISE the probability of a *realised* +4%
    # day. Adaptive is therefore OFF — a FIXED +4% mark-to-market lock banks
    # and flattens the instant intraday total touches +4%, every day, instead
    # of holding out (adaptive would raise the bar toward the 10% ceiling on a
    # trend day and risk touching +4% then giving it back). Trade-off: you cap
    # the rare >4% trend day at +4%. This also LOWERS variance (flat sooner),
    # so it is a pure objective-alignment change, not extra risk. Ceiling is
    # inert while adaptive is off but kept so re-enabling is a one-flag change.
    "DAILY_PROFIT_ADAPTIVE": "false",
    "DAILY_PROFIT_PCT_CEILING": "10",
    # Regime + edge weighted risk sizing (holdout-validated: H2 book Sharpe
    # 1.35 -> 1.83). Tilts per-entry risk UP in a strong BTC-4h trend and on
    # the higher-Sharpe legs (ichimoku, squeeze@4h), DOWN in chop and on the
    # weak leg (squeeze@1h), within the risk band. Sizing only, never a gate.
    "REGIME_EDGE_WEIGHT_ENABLED": "true",
    "DAY_BOUNDARY_OFFSET_HOURS": "3",
    "STALE_ENTRY_GUARD_BARS": "3",
    "KLINE_CACHE_ENABLED": "true",
    "UNIVERSE_REFRESH_SEC": "600",
    "AX_MODE": "paper",
    "LIVE_ENABLED": "false",
    "LIVE_SEND_ORDERS": "false",
}

# Hard safety: values this script is FORBIDDEN to produce, ever.
FORBIDDEN = {("AX_MODE", "live"), ("LIVE_ENABLED", "true"),
             ("LIVE_SEND_ORDERS", "true")}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Apply the SYSTEM_STATE §6 paper block to .env "
                    "(dry-run by default; never touches secrets or arms live).")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    p.add_argument("--baseline", action="store_true",
                   help="write the non-fast STRATEGIES (no :n=10 / :q=30)")
    args = p.parse_args(argv)

    changes = dict(BLOCK)
    if args.baseline:
        changes["STRATEGIES"] = STRATEGIES_BASE
    for k, v in changes.items():
        if k in SECRET_KEYS or (k, v.lower()) in FORBIDDEN:
            print(f"REFUSING: unsafe key/value {k}")
            return 2

    env_path = args.env_file
    if os.path.exists(env_path):
        base_lines = _read_lines(env_path)
    else:
        example = os.path.join(os.path.dirname(env_path) or ".", ".env.example")
        if os.path.exists(example):
            print(f"{env_path} not found — seeding from {example} "
                  "(secrets stay blank; fill Telegram/Binance keys separately).")
            base_lines = _read_lines(example)
        else:
            base_lines = []

    new_lines, change_log = apply_to_lines(base_lines, changes)
    print(f"Target file : {env_path}")
    print(f"Mode        : {'APPLY (writing)' if args.apply else 'DRY-RUN (no write)'}")
    print(f"Variant     : {'baseline' if args.baseline else 'FAST (n=10 / q=30)'}")
    print("Planned changes:")
    for c in change_log or ["  (none — file already matches; no-op)"]:
        print(c)
    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write "
              "(a .env.backup.<timestamp> is made first).")
        return 0
    if os.path.exists(env_path):
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
