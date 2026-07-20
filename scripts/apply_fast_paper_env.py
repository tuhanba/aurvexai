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

# Ichimoku's measured universe: the validated 12 minus TON (TON's futures
# history is too thin to have been measured — evidence-strict pin,
# docs/review/LEG_REVIEW_2026-07-17.md).
U11_ICHI = "BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TRX+DOT"

# Leg-review package 2026-07-17 (docs/review/LEG_REVIEW_2026-07-17.md):
#   * squeeze@1h REMOVED — deployed config re-measured +0.018R over 4031
#     trades (P(≤0)=0.25, MaxDD 50%); most trades, least R, cost-dominated.
#   * squeeze@4h back to the validated q=20 (drop :q=30) — q20 re-measured
#     +0.116R vs q30's +0.074/+0.078 on BOTH frames, better DSR/PF/MaxDD
#     and better 2025+.
#   * ichimoku pinned to its measured 11-coin universe — same-span evidence:
#     +0.222R (t 3.11, +131R) vs +0.103 (+69R) on the 17-coin frame; the 5
#     expansion coins alone measured +0.027R (t 0.20).
#   * donchian & band_walk unchanged (donchian recency is the paper window's
#     question; band_walk holds on majors).
# Prior deployment line kept for rollback reference:
#   donchian_trend@4h/1d:n=10 squeeze_breakout@1h/4h:ts=24:u=<U12>
#   squeeze_breakout@4h/1d:ts=24:q=30 ichimoku_trend@4h/1d
#   band_walk@4h/1d:ts=12:u=<MAJORS>
# TF-expansion follow-up 2026-07-18 (owner: "more trades AND more profit"):
#   * squeeze@2h ADDED as a 5th leg on its validated 11-coin universe.
#     Acceptance cell (DON_BBW_CACHE 1h→2h resample, DSR n_trials=217):
#     +0.065R over 2041 trades (2.25x squeeze@4h), HIGHER total R (+132 vs
#     +105), and ALIVE in 2025+ (+0.109, t 2.03) where squeeze@4h is dead
#     (+0.004, t 0.05). DSR +2.44, both halves positive. Paper-window
#     candidate (H2 t=1.16 below the strict 1.5 kill line — the 30-50 trade
#     window is the confirmation authority). ichimoku@2h was REJECTED same
#     day (edge collapsed, total R halved). docs/review/LEG_REVIEW_2026-07-17
#     §6.
STRATEGIES_FAST = (
    "donchian_trend@4h/1d:n=10 "
    "squeeze_breakout@4h/1d:ts=24 "
    f"squeeze_breakout@2h/8h:ts=24:u={U12} "
    f"ichimoku_trend@4h/1d:u={U11_ICHI} "
    f"band_walk@4h/1d:ts=12:u={MAJORS}")
STRATEGIES_BASE = (
    "donchian_trend@4h/1d "
    "squeeze_breakout@4h/1d:ts=24 "
    f"squeeze_breakout@2h/8h:ts=24:u={U12} "
    f"ichimoku_trend@4h/1d:u={U11_ICHI} "
    f"band_walk@4h/1d:ts=12:u={MAJORS}")

BLOCK = {
    "RISK_PROFILE": "aggressive_paper",
    "INITIAL_PAPER_BALANCE": "200",
    "STRATEGIES": STRATEGIES_FAST,          # or STRATEGIES_BASE (--baseline)
    "SHADOW_ONLY_SETUPS": "",               # ichimoku promoted to active
    "GLOBAL_RANKING": "true",
    "RANK_KEY": "edge",
    "LTF_LIMIT": "525",
    # Joint operating point (2026-07-20, docs/research/JOINT_OPERATING_POINT.md).
    # The concurrency-aware sweep (scripts/joint_operating_point.py) settles the
    # combined risk × slots × target question: aggregate risk = slots × per-trade
    # risk is the real budget, and the 5 legs are near-independent (corr +0.05),
    # so a SMALLER per-trade risk spread over the slots beats a big per-trade risk
    # in a few. Deployed 1.5% × 6 = 9% aggregate was the over-concentrated corner
    # (worst MAR/DD on the frontier). Per-trade risk 1.5 → 0.5 (band 0.25–0.75)
    # keeps the 6 slots but drops aggregate to 3% → positive MAR, ~halved
    # drawdown. Slots (the "trade count" lever) already at 6; 8 is the next step
    # once the account funds more concurrent min-notionals. Config-only, parity-safe.
    "RISK_PCT": "0.5",
    "MIN_RISK_PCT": "0.25",
    "MAX_RISK_PCT": "0.75",
    # AGGRESSIVE operating point (owner decision 2026-07-20): 8 slots, the
    # growth edge of the survivable frontier (JOINT_OPERATING_POINT.md). Slots
    # 6 → 8 recovers ~900 +EV trades that slot starvation was dropping; at the
    # low 0.5% per-trade risk this is the *diversification* lever, not more risk
    # (aggregate 8×0.5% = 4%, still well under the deployed-was 9%). Modelled
    # CAGR ~23% / MaxDD ~35% / ruin ~6% — the highest survivable-growth cell.
    # Going more aggressive means MORE SLOTS at low risk, never higher per-trade
    # risk: past ~1% the model shows a ruin cliff (that is gambling, not edge).
    "MAX_OPEN_TRADES": "8",
    # 400% so the notional cap does not bind before all 8 slots can fill (300%
    # was tuned for 6). TRADE-OFF: more concurrent notional = larger correlated
    # drawdown if every long moves together — bounded by the -10% daily kill and
    # the per-trade 0.5% risk (8 all-stopping ≈ 4%, under the kill).
    "MAX_PORTFOLIO_EXPOSURE_PCT": "400",
    "MAX_LEVERAGE": "10",
    "UNIVERSE_SIZE": "17",
    "UNIVERSE_INCLUDE": U17,
    "MIN_QUOTE_VOLUME_24H": "10000000",     # 10M — pinned coins clear it in quiet markets
    # Owner decision 2026-07-11: take profit and stop for the day on a MARK-TO-
    # MARKET basis — the moment intraday total (realized+unrealized) gain hits
    # the (adaptive) target of day-open equity, CLOSE all positions and lock new
    # entries (don't wait for trades to close). Daily window rolls at 00:00
    # Türkiye saati (UTC+3), when the lock releases and trading resumes.
    #
    # Floor raised 4% -> 8% (2026-07-20, data-backed). The deployed adaptive
    # flatten (BTC-4h-ADX floor->ceiling) was simulated on the real 5-leg OOS
    # stream (docs/research/ADAPTIVE_PROFIT_FLOOR.md): raising the floor is
    # MONOTONICALLY better (MAR -0.55 @4% -> -0.29 @8%) because a low floor caps
    # the skew edge's runner days. 8% roughly halves the modelled capping harm
    # while KEEPING the peak-lock flatten (fires later, not never) and staying
    # fully reversible. Dropping the flatten entirely scores best in the model
    # but the model is blind to the intraday peak-lock benefit, so that call is
    # left to the paper window's flatten-event logs — not made on model evidence.
    "DAILY_PROFIT_LOCK_PCT": "8",
    "DAILY_PROFIT_FLATTEN": "true",
    # Adaptive target by MEASURED trend regime (BTC 4h ADX): 8% floor in chop,
    # up to 10% ceiling in a strong trend — let winners run on hype days, bank
    # fast in chop. Never changes per-trade risk; only when we take the day.
    "DAILY_PROFIT_ADAPTIVE": "true",
    "DAILY_PROFIT_PCT_CEILING": "10",
    # Give-back guard (2026-07-20): the profit target only fires AT the target,
    # so a day that peaks BELOW it (e.g. +6% then fades to +1% / negative) is
    # unprotected. This intraday equity trailing lock arms once the day's peak
    # gain clears +4% of day-open equity and banks + locks the day if it gives
    # back >33% of that peak — banking a faded winner. It NEVER caps a running
    # day (which keeps making new peaks). Measured expectancy-positive + lower
    # drawdown even on the closed-R proxy that UNDERSTATES the benefit
    # (docs/research/DAILY_GIVEBACK_GUARD.md). Parity-safe; tunable via
    # scripts/update_env.py --giveback-arm-pct / --giveback-frac / --no-giveback-guard.
    "DAILY_GIVEBACK_GUARD_ENABLED": "true",
    "DAILY_GIVEBACK_ARM_PCT": "4",
    "DAILY_GIVEBACK_FRAC": "0.33",
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
                   help="write the non-fast STRATEGIES (no :n=10)")
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
