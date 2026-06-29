#!/usr/bin/env python3
"""
Carry Phase 0 — Tasks B & C: descriptive funding stats + gross frictionless
harvest curve + carry-appropriate significance, written to
``CARRY_PHASE0_FINDINGS.md``.

This is the HARD GATE for the Funding-Carry research wave. It answers one
question with data, *before* any hedge simulation is written: does a gross,
frictionless funding-harvest edge even exist, persist across regimes, and
generalise across symbols?

The gross harvest modelled here is the simplest possible: a continuously-held
delta-neutral short-perp position with a **frictionless** hedge and **zero**
fees, accruing realized funding each settlement on a fixed notional. The
per-settlement gross carry return of that position equals the funding rate (a
short receives funding when the rate is positive and pays when it is negative).

IMPORTANT framing baked into the report:
  * The headline yield is return on **NOTIONAL**, not on capital. Once hedge
    capital + 4-leg costs + a collateral buffer are modelled in the sim phase
    it shrinks materially — do not read it as a capital yield.
  * Significance is NOT the i.i.d. trade-count + DSR gate. Funding settlements
    are autocorrelated (one position spans many settlements), so significance
    uses a block bootstrap (block length >= the funding autocorrelation horizon)
    and a Newey-West-adjusted t-stat on per-settlement gross carry returns.

Nothing here touches the live decision path, places an order, or writes to the
engine DB. It reads the read-only research cache populated by
``scripts/carry_data.py``.

Run on a Binance-reachable host (one line, no &&):

    python scripts/carry_phase0.py --universe BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.walkforward import (  # noqa: E402
    infer_funding_cadence_hours,
    load_or_fetch_funding,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK"]

# Liquidity note per symbol (flag thin books — a Phase-0 descriptive caveat, not
# a hard filter). Phase 0 casts slightly wider than the prior wave's liquid core
# to test the "edge lives in alts" hypothesis.
LIQUIDITY_NOTE = {
    "BTC": "deep", "ETH": "deep", "SOL": "deep", "BNB": "deep", "XRP": "deep",
    "DOGE": "liquid mid-cap", "AVAX": "liquid mid-cap", "LINK": "liquid mid-cap",
}

HOURS_PER_YEAR = 365.25 * 24.0
DEFAULT_MAKER_FEE = 0.0002      # 2 bps maker (Binance USDT-M maker, rough)


# ---------------------------------------------------------------------------
# Pure statistics (no numpy — small, testable, deterministic)
# ---------------------------------------------------------------------------

def autocorr(series: Sequence[float], lag: int) -> float:
    """Lag-``lag`` sample autocorrelation. Returns 0.0 for degenerate input."""
    n = len(series)
    if lag <= 0 or lag >= n:
        return 1.0 if lag == 0 else 0.0
    mean = sum(series) / n
    denom = sum((x - mean) ** 2 for x in series)
    if denom <= 0:
        return 0.0
    num = sum((series[i] - mean) * (series[i - lag] - mean)
              for i in range(lag, n))
    return num / denom


def autocorr_horizon(series: Sequence[float], max_lag: int = 200,
                     threshold: float = 0.2) -> int:
    """Smallest lag at which |acf| first falls below ``threshold``.

    Used as the block-bootstrap block length: blocks must be at least as long as
    the horizon over which settlements stay correlated, otherwise the bootstrap
    understates the variance of the mean. Floored at 1, capped at ``max_lag``.

    The cap is 200 (not 50): on the engine-host run the majors (BTC/ETH/XRP/LINK)
    saturated a 50-lag cap, i.e. funding stayed correlated past ~16 days, so a
    50-block bootstrap would still understate the variance of the mean. 200
    (~66 days at 8h) gives the crossing room to actually appear.
    """
    n = len(series)
    hi = min(max_lag, n - 1)
    for lag in range(1, hi + 1):
        if abs(autocorr(series, lag)) < threshold:
            return max(1, lag)
    return max(1, hi)


def run_lengths(signs: Sequence[int]) -> List[Tuple[int, int]]:
    """Compress a sign sequence into ``[(sign, run_length), ...]``."""
    out: List[Tuple[int, int]] = []
    for s in signs:
        if out and out[-1][0] == s:
            out[-1] = (s, out[-1][1] + 1)
        else:
            out.append((s, 1))
    return out


def block_bootstrap_mean_ci(series: Sequence[float], block_len: int,
                            n_boot: int = 2000, seed: int = 7,
                            alpha: float = 0.05) -> Tuple[float, float, float]:
    """Circular-block-bootstrap CI for the mean of an autocorrelated series.

    Resamples overlapping blocks of length ``block_len`` (circularly, so every
    start index is valid) until a series of the original length is rebuilt, takes
    its mean, and repeats ``n_boot`` times. Returns ``(mean, lo, hi)`` for the
    central ``1-alpha`` interval. The block length preserves within-block
    autocorrelation, which the i.i.d. bootstrap (and the trade DSR) would ignore.
    """
    n = len(series)
    point = sum(series) / n if n else 0.0
    if n < 2 or block_len < 1:
        return point, point, point
    block_len = min(block_len, n)
    rng = random.Random(seed)
    n_blocks = math.ceil(n / block_len)
    means: List[float] = []
    for _ in range(n_boot):
        acc = 0.0
        count = 0
        for _b in range(n_blocks):
            start = rng.randrange(n)
            for k in range(block_len):
                if count >= n:
                    break
                acc += series[(start + k) % n]
                count += 1
        means.append(acc / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return point, lo, hi


def newey_west_tstat(series: Sequence[float], lag: Optional[int] = None
                     ) -> Tuple[float, float]:
    """Newey-West (HAC) t-stat for ``mean(series) == 0``.

    Returns ``(mean, t_stat)``. The long-run variance of the mean is
    ``gamma0 + 2 * sum_{k=1..L}(1 - k/(L+1)) * gamma_k`` (Bartlett kernel),
    correcting the naive t-stat for the positive autocorrelation of funding
    settlements — the carry analog of deflating for serial dependence.
    """
    n = len(series)
    if n < 2:
        return (series[0] if series else 0.0), 0.0
    mean = sum(series) / n
    dev = [x - mean for x in series]
    gamma0 = sum(d * d for d in dev) / n
    if gamma0 <= 0:
        return mean, 0.0
    L = lag if lag is not None else min(n - 1, int(round(4 * (n / 100.0) ** (2 / 9))))
    L = max(1, L)
    lrv = gamma0
    for k in range(1, L + 1):
        gk = sum(dev[i] * dev[i - k] for i in range(k, n)) / n
        lrv += 2.0 * (1.0 - k / (L + 1.0)) * gk
    if lrv <= 0:
        return mean, 0.0
    se = math.sqrt(lrv / n)
    if se <= 0:
        return mean, 0.0
    return mean, mean / se


# ---------------------------------------------------------------------------
# Funding descriptives (Task B)
# ---------------------------------------------------------------------------

def _utc(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc)


def settlements_per_year(cadence_h: Optional[float]) -> Optional[float]:
    if not cadence_h or cadence_h <= 0:
        return None
    return HOURS_PER_YEAR / cadence_h


def describe_funding(rows: List[Tuple[int, float]],
                     cadence_h: Optional[float]) -> Dict[str, object]:
    rates = [r for _, r in rows]
    n = len(rates)
    if n == 0:
        return {"n": 0}
    mean = statistics.mean(rates)
    spy = settlements_per_year(cadence_h)
    return {
        "n": n,
        "mean": mean,
        "median": statistics.median(rates),
        "std": statistics.pstdev(rates) if n > 1 else 0.0,
        "pct_positive": sum(1 for r in rates if r > 0) / n * 100.0,
        "annualized_mean": (mean * spy) if spy else None,
        "settlements_per_year": spy,
        "acf1": autocorr(rates, 1),
        "first": rows[0][0],
        "last": rows[-1][0],
    }


def regime_segmented(rows: List[Tuple[int, float]]) -> List[Dict[str, object]]:
    """Mean funding per calendar quarter (the carry analog of 'edge per run')."""
    by_q: Dict[str, List[float]] = defaultdict(list)
    for ts, rate in rows:
        d = _utc(ts)
        q = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        by_q[q].append(rate)
    out = []
    for q in sorted(by_q):
        vals = by_q[q]
        out.append({
            "regime": q, "n": len(vals),
            "mean": statistics.mean(vals),
            "pct_positive": sum(1 for r in vals if r > 0) / len(vals) * 100.0,
        })
    return out


def negative_tail(rows: List[Tuple[int, float]], top_k: int = 5
                  ) -> List[Dict[str, object]]:
    """Worst negative-funding episodes (depth = cumulative paid, duration).

    A static short harvester *pays* during negative-funding regimes; these runs
    are its drawdown source. Depth is the summed (negative) funding over the run.
    """
    episodes = []
    cur_start = None
    cur_sum = 0.0
    cur_len = 0
    for ts, rate in rows:
        if rate < 0:
            if cur_start is None:
                cur_start = ts
                cur_sum = 0.0
                cur_len = 0
            cur_sum += rate
            cur_len += 1
        else:
            if cur_start is not None:
                episodes.append((cur_start, cur_len, cur_sum))
                cur_start = None
    if cur_start is not None:
        episodes.append((cur_start, cur_len, cur_sum))
    episodes.sort(key=lambda e: e[2])  # most negative cumulative first
    return [{"start": _utc(s).strftime("%Y-%m-%d"), "duration": l,
             "depth": d} for s, l, d in episodes[:top_k]]


# ---------------------------------------------------------------------------
# Gross frictionless harvest + cost sanity (Task C)
# ---------------------------------------------------------------------------

def harvest_curve(rows: List[Tuple[int, float]]) -> List[float]:
    """Cumulative gross harvest on notional (sum of per-settlement funding)."""
    cum = 0.0
    out = []
    for _, rate in rows:
        cum += rate
        out.append(cum)
    return out


def cost_sanity(rows: List[Tuple[int, float]], cadence_h: Optional[float],
                maker_fee: float = DEFAULT_MAKER_FEE) -> Dict[str, object]:
    """First-order cost check: per-settlement positive funding vs amortized cost.

    Cost proxy = one round-trip maker cost (entry+exit = ``2*maker_fee``) on
    notional, amortized over the average positive-run length (you enter at the
    start of a positive-funding run and exit at the end). If positive funding
    does not even clear this token cost, a 2-3%/yr gross is an illusion.
    """
    rates = [r for _, r in rows]
    pos = [r for r in rates if r > 0]
    if not pos:
        return {"clears": False, "reason": "no positive funding"}
    signs = [1 if r > 0 else 0 for r in rates]
    pos_runs = [length for s, length in run_lengths(signs) if s == 1]
    avg_pos_run = statistics.mean(pos_runs) if pos_runs else 1.0
    rt_cost = 2.0 * maker_fee
    amortized_cost_per_settlement = rt_cost / max(avg_pos_run, 1e-9)
    mean_pos_funding = statistics.mean(pos)
    spy = settlements_per_year(cadence_h)
    return {
        "mean_pos_funding": mean_pos_funding,
        "avg_pos_run": avg_pos_run,
        "rt_maker_cost": rt_cost,
        "amortized_cost_per_settlement": amortized_cost_per_settlement,
        "clears": mean_pos_funding > amortized_cost_per_settlement,
        "gross_annual_on_notional": (statistics.mean(rates) * spy) if spy else None,
    }


def significance(rows: List[Tuple[int, float]]) -> Dict[str, object]:
    """Block-bootstrap CI + Newey-West t-stat on per-settlement gross carry.

    The gross carry return series IS the funding series (continuously-held short
    collects funding each settlement). This is the carry-appropriate replacement
    for the trade-count + i.i.d. DSR gate.
    """
    rates = [r for _, r in rows]
    n = len(rates)
    if n < 8:
        return {"n": n, "insufficient": True}
    horizon = autocorr_horizon(rates)
    block = max(horizon, 1)
    mean, lo, hi = block_bootstrap_mean_ci(rates, block_len=block)
    nw_mean, nw_t = newey_west_tstat(rates)
    return {
        "n": n,
        "acf_horizon": horizon,
        "block_len": block,
        "mean_per_settlement": mean,
        "boot_lo": lo,
        "boot_hi": hi,
        "boot_positive": lo > 0,
        "nw_tstat": nw_t,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _f(x: object, p: int = 8) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        s = f"{x:.{p}f}".rstrip("0").rstrip(".")
        return s or "0"
    return str(x)


def _md_table(rows: List[dict], cols: List[str]) -> str:
    if not rows:
        return "_(no data)_\n"
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(_f(r.get(c, "")) for c in cols) + " |"
                     for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def evaluate_gate(per_symbol: Dict[str, dict]) -> Dict[str, object]:
    """Section-4 gate: GO to simulation only if ALL criteria hold."""
    have = [s for s, d in per_symbol.items() if d.get("desc", {}).get("n", 0) > 0]
    cost_clears = [s for s in have if per_symbol[s]["cost"].get("clears")]
    gross_pos = [s for s in have
                 if (per_symbol[s]["desc"].get("annualized_mean") or 0) > 0]
    sig_pos = [s for s in have
               if per_symbol[s]["sig"].get("boot_positive")
               and (per_symbol[s]["sig"].get("nw_tstat") or 0) > 2.0]

    # Regime: positive mean funding in a majority of quarters, for the symbols
    # that otherwise look alive (gross-positive).
    regime_ok = []
    for s in gross_pos:
        regs = per_symbol[s]["regimes"]
        if not regs:
            continue
        pos_q = sum(1 for r in regs if r["mean"] > 0)
        if pos_q >= math.ceil(len(regs) * 0.6):
            regime_ok.append(s)

    c1 = len(cost_clears) > 1                       # clears cost on >1 symbol
    c2 = len(regime_ok) >= 1                        # survives multiple regimes
    c3 = len(gross_pos) >= max(2, math.ceil(len(have) * 0.5))  # broad, not 1-2
    c4 = len(sig_pos) >= 1                          # significance comfortably +ve
    go = c1 and c2 and c3 and c4
    return {
        "go": go,
        "criteria": {
            "cost_clears_>1_symbol": (c1, cost_clears),
            "positive_across_regimes": (c2, regime_ok),
            "broad_across_universe": (c3, gross_pos),
            "significance_positive": (c4, sig_pos),
        },
        "n_have": len(have),
    }


def build_report(per_symbol: Dict[str, dict], gate: Dict[str, object],
                 universe: List[str], any_data: bool) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p = [
        "# Carry Phase 0 — Findings (funding-harvest gross-edge gate)\n\n",
        f"Generated: {now}\n\n",
        f"Universe: {', '.join(universe)}\n\n",
    ]
    if not any_data:
        p.append("> **NO DATA.** No funding history was found in the cache. Run "
                 "`scripts/carry_data.py --refresh` on a Binance-reachable host "
                 "first, then re-run this script. (The Claude Code environment "
                 "cannot reach Binance — this report is a template until run on "
                 "the engine host.)\n\n")
        return "".join(p)

    p.append("> **Yield is on NOTIONAL, not capital.** The gross frictionless "
             "harvest below zeroes out fees, hedge capital and collateral. Once "
             "the 4-leg costs + collateral buffer are modelled in the sim phase, "
             "the headline shrinks materially. Do not read a notional yield as a "
             "capital yield.\n\n")
    p.append("> **Significance is carry-adapted, not the trade DSR.** Funding "
             "settlements are autocorrelated (one position spans many "
             "settlements), so the i.i.d. trade-count + DSR gate does not "
             "transfer. We use a block bootstrap (block >= funding autocorrelation "
             "horizon) and a Newey-West t-stat on per-settlement gross carry "
             "returns.\n\n")

    # --- Per-symbol funding stats ---
    p.append("## 1. Per-symbol funding statistics\n\n")
    desc_rows = []
    for s in universe:
        d = per_symbol.get(s, {})
        desc = d.get("desc", {})
        if desc.get("n", 0) == 0:
            continue
        desc_rows.append({
            "symbol": s, "liquidity": LIQUIDITY_NOTE.get(s, "?"),
            "n": desc["n"], "cadence_h": d.get("cadence_h"),
            "mean": round(desc["mean"], 8),
            "median": round(desc["median"], 8),
            "std": round(desc["std"], 8),
            "pct_pos": round(desc["pct_positive"], 1),
            "annual_on_notional": (round(desc["annualized_mean"], 5)
                                   if desc["annualized_mean"] is not None else None),
            "acf1": round(desc["acf1"], 3),
        })
    p.append(_md_table(desc_rows, ["symbol", "liquidity", "n", "cadence_h", "mean",
                                   "median", "std", "pct_pos",
                                   "annual_on_notional", "acf1"]))
    p.append("\n`annual_on_notional` uses per-symbol cadence: "
             "settlements/yr = (365.25*24)/cadence_h. It is a gross-funding "
             "yield on notional, **not** on capital.\n\n")

    # --- Regime-segmented ---
    p.append("## 2. Regime-segmented mean funding (by quarter)\n\n")
    p.append("Carry's failure mode is funding flipping sign between regimes — "
             "aggregate-positive is not enough.\n\n")
    for s in universe:
        d = per_symbol.get(s, {})
        regs = d.get("regimes", [])
        if not regs:
            continue
        p.append(f"### {s}\n\n")
        p.append(_md_table([{**r, "mean": round(r["mean"], 8),
                             "pct_positive": round(r["pct_positive"], 1)}
                            for r in regs],
                           ["regime", "n", "mean", "pct_positive"]))
        p.append("\n")

    # --- Negative tail ---
    p.append("## 3. Negative-funding tail (drawdown source for a static short)\n\n")
    tail_rows = []
    for s in universe:
        d = per_symbol.get(s, {})
        for ep in d.get("neg_tail", []):
            tail_rows.append({"symbol": s, **ep, "depth": round(ep["depth"], 6)})
    p.append(_md_table(tail_rows, ["symbol", "start", "duration", "depth"]))
    p.append("\n`depth` = summed (negative) funding paid over the run; "
             "`duration` = settlements.\n\n")

    # --- Gross harvest + cost sanity ---
    p.append("## 4. Gross frictionless harvest + first-order cost sanity\n\n")
    harv_rows = []
    for s in universe:
        d = per_symbol.get(s, {})
        c = d.get("cost", {})
        desc = d.get("desc", {})
        if desc.get("n", 0) == 0:
            continue
        cum = d.get("harvest_final")
        harv_rows.append({
            "symbol": s,
            "cum_harvest_on_notional": (round(cum, 5) if cum is not None else None),
            "annual_on_notional": (round(desc["annualized_mean"], 5)
                                   if desc.get("annualized_mean") is not None else None),
            "mean_pos_funding": round(c.get("mean_pos_funding", 0.0), 8),
            "amortized_cost": round(c.get("amortized_cost_per_settlement", 0.0), 8),
            "clears_cost": c.get("clears"),
        })
    p.append(_md_table(harv_rows, ["symbol", "cum_harvest_on_notional",
                                   "annual_on_notional", "mean_pos_funding",
                                   "amortized_cost", "clears_cost"]))
    p.append("\nCost proxy = one round-trip maker cost (2*maker_fee) amortized "
             "over the average positive-run length. `clears_cost=False` means "
             "funding does not even beat a token cost — ignore any gross yield "
             "there.\n\n")

    # --- Significance ---
    p.append("## 5. Carry significance (block bootstrap + Newey-West)\n\n")
    sig_rows = []
    for s in universe:
        d = per_symbol.get(s, {})
        sig = d.get("sig", {})
        if sig.get("insufficient") or not sig:
            continue
        sig_rows.append({
            "symbol": s, "n": sig["n"], "acf_horizon": sig["acf_horizon"],
            "block_len": sig["block_len"],
            "mean_per_settlement": round(sig["mean_per_settlement"], 8),
            "boot95_lo": round(sig["boot_lo"], 8),
            "boot95_hi": round(sig["boot_hi"], 8),
            "boot_positive": sig["boot_positive"],
            "nw_tstat": round(sig["nw_tstat"], 2),
        })
    p.append(_md_table(sig_rows, ["symbol", "n", "acf_horizon", "block_len",
                                  "mean_per_settlement", "boot95_lo", "boot95_hi",
                                  "boot_positive", "nw_tstat"]))
    p.append("\nThis replaces the trade-count + DSR gate. `boot_positive` = the "
             "95% block-bootstrap CI lower bound is above zero; `nw_tstat` is the "
             "Newey-West (HAC) t-stat on per-settlement gross carry.\n\n")

    # --- Cross-symbol concentration ---
    p.append("## 6. Cross-symbol concentration (gross stage)\n\n")
    annuals = {s: per_symbol[s]["desc"].get("annualized_mean")
               for s in universe
               if per_symbol.get(s, {}).get("desc", {}).get("n", 0) > 0
               and per_symbol[s]["desc"].get("annualized_mean") is not None}
    pos_annuals = {s: v for s, v in annuals.items() if v > 0}
    total_pos = sum(pos_annuals.values()) or 0.0
    if pos_annuals and total_pos > 0:
        top_sym = max(pos_annuals, key=pos_annuals.get)
        top_share = pos_annuals[top_sym] / total_pos * 100.0
        p.append(f"- Symbols with positive gross annual-on-notional: "
                 f"{len(pos_annuals)}/{len(annuals)}\n")
        p.append(f"- Top contributor: **{top_sym}** "
                 f"({top_share:.0f}% of summed positive gross annual)\n")
        p.append(f"- Concentration verdict: "
                 f"{'CONCENTRATED in 1-2 symbols (BNB-style risk)' if top_share > 60 else 'broadly distributed'}\n\n")
    else:
        p.append("- No symbol shows positive gross annual-on-notional.\n\n")

    # --- GO / NO-GO ---
    p.append("## 7. GO / NO-GO to simulation (Section-4 gate)\n\n")
    crit = gate["criteria"]
    p.append(_md_table([
        {"criterion": k, "pass": v[0], "symbols": ",".join(v[1]) or "-"}
        for k, v in crit.items()
    ], ["criterion", "pass", "symbols"]))
    verdict = "GO" if gate["go"] else "NO-GO"
    p.append(f"\n### Recommendation: **{verdict} to hedge-simulation phase**\n\n")
    if gate["go"]:
        p.append("All four gross-stage criteria hold. Proceed to the "
                 "hedge-simulation phase (cost/collateral model, hedge-instrument "
                 "decision). This is NOT a promote-to-paper bar.\n")
    else:
        failed = [k for k, v in crit.items() if not v[0]]
        p.append(f"At least one gross-stage criterion fails ({', '.join(failed)}). "
                 "Per the Phase-0 gate, funding harvest is likely dead too: an "
                 "honest NO-GO here is an acceptable outcome. Reconsider "
                 "basis-spread as a separate hypothesis, or classify as research. "
                 "Do NOT begin hedge simulation.\n")
    p.append("\n---\n_Generator: `scripts/carry_phase0.py`. Data: "
             "`scripts/carry_data.py` (read-only research cache)._\n")
    return "".join(p)


def analyze_symbol(base: str, cache_dir: str, maker_fee: float) -> dict:
    from aurvex.walkforward import _funding_cache_path  # local: data-layer detail
    psym = f"{base}/USDT:USDT"
    rows = load_or_fetch_funding(psym, cache_dir=cache_dir, refresh=False)
    if not rows:
        return {"desc": {"n": 0}}
    cadence_h = infer_funding_cadence_hours([t for t, _ in rows])
    desc = describe_funding(rows, cadence_h)
    curve = harvest_curve(rows)
    return {
        "cadence_h": cadence_h,
        "desc": desc,
        "regimes": regime_segmented(rows),
        "neg_tail": negative_tail(rows),
        "cost": cost_sanity(rows, cadence_h, maker_fee),
        "sig": significance(rows),
        "harvest_final": curve[-1] if curve else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Carry Phase 0 descriptive + harvest.")
    ap.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE))
    ap.add_argument("--cache-dir", default="data/cache")
    ap.add_argument("--maker-fee", type=float, default=DEFAULT_MAKER_FEE)
    ap.add_argument("--out", default=os.path.join(ROOT, "CARRY_PHASE0_FINDINGS.md"))
    args = ap.parse_args()
    bases = [b.strip().upper() for b in args.universe.split(",") if b.strip()]

    per_symbol: Dict[str, dict] = {}
    for base in bases:
        per_symbol[base] = analyze_symbol(base, args.cache_dir, args.maker_fee)

    any_data = any(d.get("desc", {}).get("n", 0) > 0 for d in per_symbol.values())
    gate = evaluate_gate(per_symbol) if any_data else {"go": False, "criteria": {}}
    report = build_report(per_symbol, gate, bases, any_data)
    with open(args.out, "w") as fh:
        fh.write(report)

    print(f"any_data={any_data}")
    for base in bases:
        d = per_symbol[base]
        desc = d.get("desc", {})
        if desc.get("n", 0) == 0:
            print(f"  {base:<6} no funding data")
            continue
        sig = d.get("sig", {})
        print(f"  {base:<6} n={desc['n']:<6} "
              f"annual_on_notional={_f(desc.get('annualized_mean'), 4)} "
              f"clears_cost={d['cost'].get('clears')} "
              f"nw_t={_f(sig.get('nw_tstat'), 2)}")
    if any_data:
        print(f"GATE: {'GO' if gate['go'] else 'NO-GO'} to simulation")
    print(f"wrote {os.path.relpath(args.out)}")


if __name__ == "__main__":
    main()
