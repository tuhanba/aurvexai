#!/usr/bin/env python3
"""
scripts/market_era_wave.py — per-ERA edge (the owner was right; I tested the
wrong horizon).

The owner asked: "bull market? this TA is best. chop? that one. high vol?
another. Find the edge PER MARKET CONDITION." I implemented that as a BAR-LEVEL
regime label — and measured it to flip every **1.3 days** (median; 42% of blocks
under a day, longest 15 days). That is indicator flicker, not a market era. No
wonder per-cell edge did not persist: the label had no time to mean anything.

This tests the owner's actual idea: ERAS that last MONTHS.

Era definition (slow and standard, deliberately not tuned):
  * BULL       : BTC above its 200-day SMA and within 15% of its running peak
  * CORRECTION : above the 200d SMA but 15-30% off the peak
  * BEAR       : below the 200-day SMA, or >30% off the peak
  * RECOVERY   : below-200d but price rising back through it (transition out)
All computed causally from BTC daily closes (resampled from 4h) — no lookahead.

Then, per (leg x era):
  1. how long do eras actually last (sanity: should be months, not days),
  2. net Exp-R per leg per era — the "which TA suits which market" table,
  3. the DECISIVE test: does a leg's edge in ONE instance of an era predict its
     edge in a LATER instance of the SAME era? That is what "pick the right tool
     per market" requires to work forward. If a leg is best in the 2021 bull and
     also best in the 2024 bull, the idea is tradeable. If not, it is hindsight.

Honest limitation stated up front: ~6 years contains only a handful of eras, so
the repeat-instance test is thin by construction. Thin evidence is reported as
thin, not promoted.

Research only — changes no engine behaviour.
"""
from __future__ import annotations

import dataclasses as _dc
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from regime_matrix import ALL12, ICH11, MAJORS5, _load_candles

DAY = 86_400_000
BULL, CORRECTION, BEAR, RECOVERY = "BULL", "CORRECTION", "BEAR", "RECOVERY"

LEGS = [
    ("donchian", "donchian_trend", ALL12, {"don_entry_bars": 10}),
    ("squeeze", "squeeze_breakout", ALL12, {"time_stop_bars": 24, "sqz_pctile": 20}),
    ("ichimoku", "ichimoku_trend", ICH11, {}),
    ("band_walk", "band_walk", MAJORS5, {"time_stop_bars": 12}),
]


def _daily_from_4h(bars):
    out, cur, key = [], None, None
    for b in bars:
        k = b.ts // DAY
        if cur is None or k != key:
            if cur is not None:
                out.append(cur)
            cur = [b.ts, b.close]
            key = k
        else:
            cur[1] = b.close
    if cur:
        out.append(cur)
    return out


def _era_timeline(btc_4h):
    """Causal daily era labels from BTC: 200d SMA + drawdown-from-peak."""
    d = _daily_from_4h(btc_4h)
    ts = [x[0] for x in d]
    cl = [x[1] for x in d]
    eras = []
    peak = 0.0
    for i in range(len(cl)):
        peak = max(peak, cl[i])
        if i < 200:
            eras.append(None)
            continue
        sma200 = sum(cl[i - 199:i + 1]) / 200
        dd = (peak - cl[i]) / peak if peak > 0 else 0.0
        above = cl[i] > sma200
        if above and dd <= 0.15:
            e = BULL
        elif above and dd <= 0.30:
            e = CORRECTION
        elif not above and dd > 0.30:
            e = BEAR
        elif not above:
            e = RECOVERY if cl[i] > cl[i - 20] else BEAR
        else:
            e = CORRECTION
        eras.append(e)
    return ts, eras


def _smooth(eras, min_days=21):
    """Hysteresis: a new era must hold ``min_days`` consecutively before it
    becomes effective; otherwise the previous era persists.

    Without this the raw label oscillates at the 200d-SMA / drawdown thresholds
    (1-day blocks) and we reproduce exactly the flicker this test exists to
    avoid. An era is supposed to be a market CHARACTER lasting months.
    """
    out = list(eras)
    eff = None
    pending, count = None, 0
    for i, e in enumerate(eras):
        if e is None:
            out[i] = None
            continue
        if eff is None:
            eff = e
        elif e == eff:
            pending, count = None, 0
        else:
            if e == pending:
                count += 1
            else:
                pending, count = e, 1
            if count >= min_days:
                eff = e
                pending, count = None, 0
        out[i] = eff
    return out


def _era_at(ts_list, eras, when):
    import bisect
    k = bisect.bisect_right(ts_list, when) - 1
    if k < 0:
        return None
    return eras[k]


def _blocks(eras):
    out, cur, n = [], None, 0
    for e in eras:
        if e is None:
            continue
        if e == cur:
            n += 1
        else:
            if cur:
                out.append((cur, n))
            cur, n = e, 1
    if cur:
        out.append((cur, n))
    return out


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    ts_list, eras = _era_timeline(coins["BTCUSDT"])
    eras = _smooth(eras, min_days=21)     # an era must last WEEKS, not days

    blocks = _blocks(eras)
    print("=== 1) Eras actually last MONTHS (vs my bar-label's 1.3 days) ===")
    for name, n in blocks:
        print(f"   {name:<11} {n:>4} days ({n/30.4:.1f} months)")
    lens = [n for _, n in blocks]
    print(f"   -> {len(blocks)} eras, mean {sum(lens)/len(lens):.0f} days, "
          f"longest {max(lens)} days\n")

    print("=== 2) WHICH TA SUITS WHICH MARKET (net Exp-R, cost incl.) ===")
    cells = defaultdict(lambda: defaultdict(list))
    seq = defaultdict(lambda: defaultdict(list))     # era instance -> R list
    inst_id = {}
    running = None
    idx = 0
    for i, e in enumerate(eras):
        if e is None:
            continue
        if e != running:
            idx += 1
            running = e
        inst_id[ts_list[i]] = (e, idx)

    import bisect
    keys = sorted(inst_id)
    for key, profile, universe, opts in LEGS:
        lcfg = _dc.replace(cfg, strategy_profile=profile, ltf="4h", htf="1d",
                           ltf_limit=max(600, cfg.ltf_limit), **opts)
        data = {s: coins[s] for s in universe if s in coins}
        bt = Backtester(lcfg)
        bt.run(data)
        for t in getattr(bt, "_last_closed", []) or []:
            e = _era_at(ts_list, eras, t.open_time)
            if not e:
                continue
            r = t.realized_pnl_pct or 0.0
            cells[key][e].append(r)
            k = bisect.bisect_right(keys, t.open_time) - 1
            if k >= 0:
                seq[key][inst_id[keys[k]]].append(r)

    era_names = [BULL, CORRECTION, BEAR, RECOVERY]
    print(f"{'leg':>10} " + " ".join(f"{e:>22}" for e in era_names))
    for key, _p, _u, _o in LEGS:
        row = []
        for e in era_names:
            rs = cells[key].get(e, [])
            row.append(f"{sum(rs)/len(rs):+.3f} (n={len(rs)})" if rs else "     —      ")
        print(f"{key:>10} " + " ".join(f"{c:>22}" for c in row))

    print("\n=== 3) DECISIVE: does the SAME leg win the SAME era again later? ===")
    for e in era_names:
        insts = sorted({i for k in seq for (ee, i) in seq[k] if ee == e})
        if len(insts) < 2:
            print(f"  {e}: only {len(insts)} instance in 6y — cannot test repeat")
            continue
        print(f"  {e}: {len(insts)} instances")
        rank_per_inst = []
        for i in insts:
            scores = {}
            for k in seq:
                rs = seq[k].get((e, i), [])
                if len(rs) >= 20:
                    scores[k] = sum(rs) / len(rs)
            if len(scores) >= 2:
                best = max(scores, key=scores.get)
                rank_per_inst.append((i, best, round(scores[best], 3), len(scores)))
        for i, best, sc, nlegs in rank_per_inst:
            print(f"     instance #{i}: best leg = {best} ({sc:+.3f})")
        if len(rank_per_inst) >= 2:
            winners = [b for _, b, _, _ in rank_per_inst]
            same = len(set(winners)) == 1
            print(f"     -> winner {'STABLE' if same else 'CHANGES'} across "
                  f"instances: {winners}")

    print("\n=== READ ===")
    print("  If the same leg wins the same era every time, 'pick the tool per")
    print("  market' is tradeable. If the winner changes, the per-era table is")
    print("  hindsight — true about the past, useless forward.")


if __name__ == "__main__":
    main()
