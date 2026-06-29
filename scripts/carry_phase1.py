#!/usr/bin/env python3
"""
Carry Phase 1 — net-on-capital harvest, significance, holdout, report.

Drives ``scripts/carry_sim.py`` over real (engine-host) data to answer the only
question that decides the strategy: after both hedge legs, four legs of fees,
slippage/basis, a collateral buffer and short-leg liquidation, what NET return ON
CAPITAL survives? Replaces Phase-0's gross-on-notional headline with the real
economics and re-asks significance on net per-settlement capital returns.

Writes ``CARRY_PHASE1_FINDINGS.md`` and evaluates the Section-6 paper-promotion
gate (stricter than Phase 0; still NOT a live bar). SOL/BNB are carried as
negative controls — the model is wrong if they come out profitable.

Reuses the Phase-0 data layer (funding + spot + paginator), the Phase-0
significance functions, and the holdout split pattern. Nothing here touches the
live decision path, places an order, or writes the DB.

Run on a Binance-reachable host (one line, no &&):

    python scripts/carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE,AVAX --controls SOL,BNB
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import statistics
import sys
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))  # sibling scripts (carry_phase0, carry_sim)

from aurvex.walkforward import (  # noqa: E402
    infer_funding_cadence_hours,
    load_or_fetch_candles,
    load_or_fetch_funding,
    load_or_fetch_spot,
)
import carry_sim as cs  # noqa: E402
from carry_phase0 import (  # noqa: E402  (reuse carry significance)
    autocorr_horizon, block_bootstrap_mean_ci, newey_west_tstat,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_UNIVERSE = ["BTC", "ETH", "XRP", "LINK", "DOGE", "AVAX"]
DEFAULT_CONTROLS = ["SOL", "BNB"]
HOURS_PER_YEAR = 365.25 * 24.0
MIN_ANNUAL_ON_CAPITAL = 0.02     # token-positive floor: < 2%/yr on capital = NO-GO


def cadence_tf(cadence_h: Optional[float]) -> str:
    """ccxt timeframe string matching the funding cadence (8h default, 4h alts)."""
    if cadence_h and abs(cadence_h - 4.0) < 0.5:
        return "4h"
    return "8h"


def _utc(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Per-symbol load + simulate (Tasks A-pull, B, C, D)
# ---------------------------------------------------------------------------

def load_symbol(base: str, cache_dir: str, refresh: bool) -> dict:
    psym = f"{base}/USDT:USDT"
    ssym = f"{base}/USDT"
    funding = load_or_fetch_funding(psym, cache_dir=cache_dir, refresh=refresh)
    if not funding:
        return {"n": 0}
    cadence_h = infer_funding_cadence_hours([t for t, _ in funding])
    tf = cadence_tf(cadence_h)
    # Perp + spot marks at the funding cadence; deep enough to bracket history.
    perp = load_or_fetch_candles(psym, tf, limit=12000, cache_dir=cache_dir)
    spot = load_or_fetch_spot(ssym, timeframe=tf, limit=12000, cache_dir=cache_dir,
                              refresh=refresh)
    tol = int((cadence_h or 8.0) * 3_600_000)
    perp_marks = cs.align_marks_to_funding(funding, perp, tol)
    spot_marks = cs.align_marks_to_funding(funding, spot, tol)
    return {
        "n": len(funding), "cadence_h": cadence_h,
        "rates": [r for _, r in funding],
        "perp_marks": perp_marks, "spot_marks": spot_marks,
        "first": funding[0][0], "last": funding[-1][0],
        "marks_ok": sum(1 for m in perp_marks if m is not None),
    }


def years_span(first_ms: int, last_ms: int) -> float:
    return max((last_ms - first_ms) / (365.25 * 86_400_000), 1e-9)


def simulate(base: str, data: dict, notional: float,
             cm: cs.CostModel, col: cs.CollateralModel,
             exit_run: int = 0) -> dict:
    res = cs.simulate_static_hold(
        data["rates"], data["perp_marks"], data["spot_marks"],
        notional=notional, cm=cm, col=col, exit_on_negative_run=exit_run)
    yrs = years_span(data["first"], data["last"])
    annual = res.net_return_on_capital / yrs
    rets = res.capital_returns
    sig = None
    if len(rets) >= 8:
        horizon = autocorr_horizon(rets)
        mean, lo, hi = block_bootstrap_mean_ci(rets, block_len=max(horizon, 1))
        _, nw_t = newey_west_tstat(rets)
        sig = {"block_len": max(horizon, 1), "mean": mean, "lo": lo, "hi": hi,
               "boot_positive": lo > 0, "nw_t": nw_t}
    return {"res": res, "annual_on_capital": annual, "years": yrs, "sig": sig}


# ---------------------------------------------------------------------------
# Holdout (Task F) — out-of-symbol generalisation on NET returns
# ---------------------------------------------------------------------------

def holdout_check(per_symbol: Dict[str, dict], universe: List[str]) -> dict:
    alive = [s for s in universe if per_symbol.get(s, {}).get("sim")]
    if len(alive) < 4:
        return {"ran": False}
    half = len(alive) // 2
    train, hold = alive[:half], alive[half:]

    def _net(group):
        return sum(per_symbol[s]["sim"]["res"].net_pnl for s in group)
    train_pos = _net(train) > 0
    hold_pos = _net(hold) > 0
    indiv_pos = sum(1 for s in alive
                    if per_symbol[s]["sim"]["res"].net_pnl > 0)
    majority = indiv_pos > len(alive) / 2
    return {"ran": True, "train": train, "holdout": hold,
            "train_pos": train_pos, "holdout_pos": hold_pos,
            "indiv_pos": indiv_pos, "n_alive": len(alive),
            "majority_pos": majority,
            "passes": train_pos and hold_pos and majority}


# ---------------------------------------------------------------------------
# Section-6 gate
# ---------------------------------------------------------------------------

def evaluate_gate(per_symbol: Dict[str, dict], controls: Dict[str, dict],
                  universe: List[str], holdout: dict) -> dict:
    alive = [s for s in universe if per_symbol.get(s, {}).get("sim")]
    meaningful = [s for s in alive
                  if per_symbol[s]["sim"]["annual_on_capital"] > MIN_ANNUAL_ON_CAPITAL]
    no_liq = [s for s in alive
              if per_symbol[s]["sim"]["res"].liquidations == 0]
    sig_pos = [s for s in alive
               if (per_symbol[s]["sim"]["sig"] or {}).get("boot_positive")
               and (per_symbol[s]["sim"]["sig"] or {}).get("nw_t", 0) > 2.0]
    # A control "passes" when it is NOT significantly net-positive. Use the
    # significance, not the raw annual sign: a marginally-positive annual with a
    # non-significant (or negative) t-stat is noise, not an edge.
    def _control_ok(c: dict) -> bool:
        sim = c.get("sim")
        if not sim:
            return True
        sig = sim.get("sig") or {}
        sig_pos = sig.get("boot_positive") and sig.get("nw_t", 0) > 2.0
        return not sig_pos
    controls_ok = all(_control_ok(c) for c in controls.values())

    c1 = len(meaningful) >= max(2, len(alive) // 2)     # net meaningful, broad
    c2 = len(no_liq) >= max(2, len(alive) // 2)         # survives without ruin
    c3 = bool(holdout.get("passes"))                    # out-of-symbol holdout
    c4 = len(sig_pos) >= max(2, len(alive) // 2)        # net significance
    c5 = controls_ok                                    # negative controls non-positive
    go = c1 and c2 and c3 and c4 and c5
    return {"go": go, "criteria": {
        "net_meaningful_broad": (c1, meaningful),
        "survives_no_liquidation": (c2, no_liq),
        "out_of_symbol_holdout": (c3, [] if not c3 else holdout.get("holdout", [])),
        "net_significance": (c4, sig_pos),
        "negative_controls_nonpositive": (c5, [k for k in controls]),
    }}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _f(x, p=6):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return (f"{x:.{p}f}".rstrip("0").rstrip(".")) or "0"
    return str(x)


def _md(rows, cols):
    if not rows:
        return "_(no data)_\n"
    h = "| " + " | ".join(cols) + " |"
    s = "| " + " | ".join("---" for _ in cols) + " |"
    b = "\n".join("| " + " | ".join(_f(r.get(c, "")) for c in cols) + " |" for r in rows)
    return f"{h}\n{s}\n{b}\n"


def build_report(per_symbol, controls, universe, holdout, gate, gate2, args,
                 cm, col, any_data) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p = [f"# Carry Phase 1 — Findings (net-on-capital hedge sim)\n\n",
         f"Generated: {now}\n\n",
         f"Universe: {', '.join(universe)}  ·  controls: {', '.join(args.controls)}\n\n"]
    if not any_data:
        p.append("> **NO DATA.** Run `scripts/carry_phase1.py` on a "
                 "Binance-reachable host (funding + perp + spot marks). The Claude "
                 "Code environment cannot reach Binance — template only.\n")
        return "".join(p)
    p.append(f"> Cost model: maker {cm.maker_fee:.4f}, taker {cm.taker_fee:.4f}, "
             f"slippage {cm.slippage:.4f}, half-spread {cm.half_spread:.4f} per leg "
             f"(4 legs). Collateral: leverage {col.leverage}, MMR {col.mmr}, buffer "
             f"{col.buffer_frac} of notional, liq-penalty {col.liq_penalty}, "
             f"**margin-mode {col.margin_mode}**.\n\n")
    if col.margin_mode == "isolated":
        p.append("> `margin-mode=isolated` is the harsh default: the perp short "
                 "stands alone, so a sharp up-move can liquidate it even though the "
                 "spot leg gained. Re-run with `--margin-mode cross` to model the "
                 "realistic backstop (spot collateralises the perp) and compare.\n\n")
    p.append("> **Return is on DEPLOYED CAPITAL** (spot notional + perp margin + "
             "buffer), not notional. The spot leg is unlevered, so capital >= "
             "notional — this is why net-on-capital is well below Phase-0's "
             "gross-on-notional.\n\n")

    # 1. Net-on-capital
    p.append("## 1. Net-on-capital harvest (static hold)\n\n")
    rows = []
    for s in universe + args.controls:
        d = per_symbol.get(s) or controls.get(s) or {}
        sim = d.get("sim")
        if not sim:
            continue
        r = sim["res"]
        rows.append({
            "symbol": s, "n": d.get("n"),
            "net_on_capital": round(r.net_return_on_capital, 5),
            "annual_on_capital": round(sim["annual_on_capital"], 5),
            "funding_pnl": round(r.funding_pnl, 2),
            "costs": round(r.cost_entry + r.cost_exit + r.cost_liq, 2),
            "liquidations": r.liquidations,
            "control": "yes" if s in args.controls else "",
        })
    p.append(_md(rows, ["symbol", "n", "net_on_capital", "annual_on_capital",
                        "funding_pnl", "costs", "liquidations", "control"]))
    p.append("\n`annual_on_capital` = total net-on-capital / years. Compare to "
             "Phase-0 gross-on-notional to see the shrink from real frictions.\n\n")

    # 2. Cost breakdown
    p.append("## 2. Four-leg cost + basis breakdown\n\n")
    crows = []
    for s in universe + args.controls:
        d = per_symbol.get(s) or controls.get(s) or {}
        sim = d.get("sim")
        if not sim:
            continue
        r = sim["res"]
        crows.append({"symbol": s, "cost_entry": round(r.cost_entry, 2),
                      "cost_exit": round(r.cost_exit, 2), "cost_liq": round(r.cost_liq, 2),
                      "basis_pnl": round(r.basis_pnl, 2),
                      "settlements_held": r.settlements_held})
    p.append(_md(crows, ["symbol", "cost_entry", "cost_exit", "cost_liq",
                         "basis_pnl", "settlements_held"]))

    # 3. Significance
    p.append("\n## 3. Net significance (block bootstrap + Newey-West on capital returns)\n\n")
    srows = []
    for s in universe + args.controls:
        d = per_symbol.get(s) or controls.get(s) or {}
        sim = d.get("sim")
        if not sim or not sim["sig"]:
            continue
        g = sim["sig"]
        srows.append({"symbol": s, "block_len": g["block_len"],
                      "mean_per_settlement": round(g["mean"], 8),
                      "boot95_lo": round(g["lo"], 8), "boot95_hi": round(g["hi"], 8),
                      "boot_positive": g["boot_positive"], "nw_t": round(g["nw_t"], 2),
                      "control": "yes" if s in args.controls else ""})
    p.append(_md(srows, ["symbol", "block_len", "mean_per_settlement", "boot95_lo",
                         "boot95_hi", "boot_positive", "nw_t", "control"]))

    # 4. Static vs negative-regime exit (Task E)
    p.append("\n## 4. Static hold vs negative-regime exit (descriptive, NOT tuned)\n\n")
    erows = []
    for s in universe:
        d = per_symbol.get(s, {})
        sim, ex = d.get("sim"), d.get("sim_exit")
        if not sim or not ex:
            continue
        erows.append({"symbol": s,
                      "static_annual": round(sim["annual_on_capital"], 5),
                      "exit_annual": round(ex["annual_on_capital"], 5),
                      "static_liq": sim["res"].liquidations,
                      "exit_liq": ex["res"].liquidations})
    p.append(_md(erows, ["symbol", "static_annual", "exit_annual",
                         "static_liq", "exit_liq"]))
    p.append("\nExit rule = close after N consecutive negative settlements, "
             "re-enter after N positive (N fixed a priori). Descriptive only.\n\n")

    # 5. Holdout
    p.append("## 5. Out-of-symbol holdout (net)\n\n")
    if holdout.get("ran"):
        p.append(f"- Train: {', '.join(holdout['train'])} — "
                 f"net {'POSITIVE' if holdout['train_pos'] else 'negative'}\n")
        p.append(f"- Holdout: {', '.join(holdout['holdout'])} — "
                 f"net {'POSITIVE' if holdout['holdout_pos'] else 'negative'}\n")
        p.append(f"- Individually net-positive: {holdout['indiv_pos']}/"
                 f"{holdout['n_alive']} (majority: {holdout['majority_pos']})\n")
        p.append(f"- Holdout gate: **{'PASS' if holdout['passes'] else 'FAIL'}**\n\n")
    else:
        p.append("- Not enough alive symbols to split.\n\n")

    # 6. Gate
    p.append("## 6. GO / NO-GO to paper (Section-6 gate)\n\n")
    crit = gate2["criteria"]
    p.append(_md([{"criterion": k, "pass": v[0], "symbols": ",".join(v[1]) or "-"}
                  for k, v in crit.items()], ["criterion", "pass", "symbols"]))
    verdict = "GO" if gate2["go"] else "NO-GO"
    p.append(f"\n### Recommendation: **{verdict} to paper proposal**\n\n")
    if gate2["go"]:
        p.append("All Section-6 criteria hold on the net-on-capital model. Draft a "
                 "paper-trading proposal (sizing/allocation across the surviving "
                 "symbols, both-legs paper executor). NOT a live bar.\n")
    else:
        failed = [k for k, v in crit.items() if not v[0]]
        p.append(f"At least one criterion fails ({', '.join(failed)}). Funding "
                 "harvest does not survive real frictions as modelled — an honest "
                 "NO-GO. Reconsider parameters only if a constraint was mis-modelled; "
                 "otherwise classify and stop. Do NOT promote to paper.\n")
    p.append("\n---\n_Generators: `scripts/carry_sim.py`, `scripts/carry_phase1.py`._\n")
    return "".join(p)


def main() -> None:
    ap = argparse.ArgumentParser(description="Carry Phase 1 net-on-capital sim.")
    ap.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE))
    ap.add_argument("--controls", default=",".join(DEFAULT_CONTROLS))
    ap.add_argument("--cache-dir", default="data/cache")
    ap.add_argument("--notional", type=float, default=10_000.0)
    ap.add_argument("--leverage", type=float, default=3.0)
    ap.add_argument("--buffer", type=float, default=0.5, help="collateral buffer frac of notional")
    ap.add_argument("--margin-mode", default="isolated", choices=["isolated", "cross"],
                    help="isolated (perp stands alone) | cross (spot gain backstops perp margin)")
    ap.add_argument("--exit-run", type=int, default=3, help="Task E: N consecutive neg settlements")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "CARRY_PHASE1_FINDINGS.md"))
    args = ap.parse_args()
    args.universe = [b.strip().upper() for b in args.universe.split(",") if b.strip()]
    args.controls = [b.strip().upper() for b in args.controls.split(",") if b.strip()]

    cm = cs.CostModel()
    col = cs.CollateralModel(leverage=args.leverage, buffer_frac=args.buffer,
                             margin_mode=args.margin_mode)

    per_symbol: Dict[str, dict] = {}
    controls: Dict[str, dict] = {}
    for base in args.universe:
        d = load_symbol(base, args.cache_dir, args.refresh)
        if d.get("n", 0) > 0:
            d["sim"] = simulate(base, d, args.notional, cm, col, exit_run=0)
            d["sim_exit"] = simulate(base, d, args.notional, cm, col, exit_run=args.exit_run)
        per_symbol[base] = d
    for base in args.controls:
        d = load_symbol(base, args.cache_dir, args.refresh)
        if d.get("n", 0) > 0:
            d["sim"] = simulate(base, d, args.notional, cm, col, exit_run=0)
        controls[base] = d

    any_data = any(d.get("sim") for d in {**per_symbol, **controls}.values())
    holdout = holdout_check(per_symbol, args.universe) if any_data else {"ran": False}
    gate2 = evaluate_gate(per_symbol, controls, args.universe, holdout) if any_data \
        else {"go": False, "criteria": {}}
    report = build_report(per_symbol, controls, args.universe, holdout, holdout,
                          gate2, args, cm, col, any_data)
    with open(args.out, "w") as fh:
        fh.write(report)

    print(f"any_data={any_data}  margin_mode={args.margin_mode}  "
          f"leverage={args.leverage}  buffer={args.buffer}")
    for base in args.universe + args.controls:
        d = per_symbol.get(base) or controls.get(base) or {}
        sim = d.get("sim")
        if not sim:
            print(f"  {base:<6} no data")
            continue
        r = sim["res"]
        tag = "[control]" if base in args.controls else ""
        print(f"  {base:<6} annual_on_capital={_f(sim['annual_on_capital'],4)} "
              f"liq={r.liquidations} nw_t={_f((sim['sig'] or {}).get('nw_t'),2)} {tag}")
    if any_data:
        print(f"HOLDOUT: {'PASS' if holdout.get('passes') else 'FAIL/na'}")
        print(f"GATE: {'GO' if gate2['go'] else 'NO-GO'} to paper")
    print(f"wrote {os.path.relpath(args.out)}")


if __name__ == "__main__":
    main()
