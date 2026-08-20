#!/usr/bin/env python3
"""Trailing-stop probe: does the EA's 0.5R trail clip winners?

Replicates the LIVE EA logic exactly on cached 1h data — first-UTC-hour ORB for
gold, prior-day-high/low PDHL (ATR14*1.5 stop) for indices, stop-entry, first
break wins, session-close exit, NO take-profit — then sweeps the exit management
variant and reports the WINNER R-DISTRIBUTION. The live account showed every
winner clipped to ~+0.15R while losers ran full -1R; this tests whether that is
the trailing stop or just variance.

Run:  PYTHONPATH=src python scripts/ftmo_trail_probe.py
"""
import csv
import os
import sys
from statistics import mean

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "ftmo")
SYMS = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl", "JP225": "pdhl"}
PDHL_ATR = 1.5
RT_COST = 0.0006          # round-trip cost fraction of notional (~0.06%), applied in price terms


def load(sym):
    rows = []
    with open(os.path.join(DATA, f"{sym}_1h.csv")) as f:
        for r in csv.DictReader(f):
            rows.append((int(r["ts"]), float(r["open"]), float(r["high"]),
                         float(r["low"]), float(r["close"])))
    rows.sort()
    return rows


def utc_day(ts_ms):   return ts_ms // 86_400_000
def utc_hour(ts_ms):  return (ts_ms // 3_600_000) % 24


def atr14(day_bars_before):
    """ATR14 from the 14 hourly bars immediately before the day (list of OHLC)."""
    if len(day_bars_before) < 15:
        return None
    seg = day_bars_before[-15:]
    trs = []
    for k in range(1, 15):
        h, l = seg[k][2], seg[k][3]
        pc = seg[k - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return mean(trs) if trs else None


def simulate(sym, profile, variant):
    """Return list of trade R-multiples for one symbol under one exit variant.

    variant: 'none' (hard stop + session close), 'trail0.5', 'trail1.0',
             'trail1.5', 'be1.0' (breakeven at +1R).
    """
    bars = load(sym)
    # group by UTC day
    by_day = {}
    for b in bars:
        by_day.setdefault(utc_day(b[0]), []).append(b)
    days = sorted(by_day)
    results = []

    for di, day in enumerate(days):
        db = by_day[day]
        if profile == "orb":
            # first UTC hour (hour==0) range
            first = [b for b in db if utc_hour(b[0]) == 0]
            if not first:
                continue
            hi = max(b[2] for b in first); lo = min(b[3] for b in first)
            if hi <= lo:
                continue
            arm_from = 1          # bars after the first hour
            buy_entry, sell_entry = hi, lo
            buy_sl, sell_sl = lo, hi           # stop = opposite range edge
        else:  # pdhl
            if di == 0:
                continue
            prev = by_day.get(day - 1)
            if not prev or len(prev) < 3:
                continue
            ph = max(b[2] for b in prev); pl = min(b[3] for b in prev)
            # ATR14 from bars before this day
            hist = [b for d in days if d < day for b in by_day[d]]
            atr = atr14(hist)
            if not atr or atr <= 0 or ph <= pl:
                continue
            d = PDHL_ATR * atr
            arm_from = 0
            buy_entry, sell_entry = ph, pl
            buy_sl, sell_sl = ph - d, pl + d

        # walk the day's bars; first break wins
        seq = db[arm_from:]
        entered = None   # ('long'/'short', entry, sl, risk)
        for bi, b in enumerate(seq):
            _, o, h, l, c = b
            if entered is None:
                hit_buy = h >= buy_entry
                hit_sell = l <= sell_entry
                if hit_buy and hit_sell:
                    # both in one bar: take the side nearer the bar open (first touched)
                    if abs(o - buy_entry) <= abs(o - sell_entry):
                        entered = ("long", buy_entry, buy_sl, abs(buy_entry - buy_sl))
                    else:
                        entered = ("short", sell_entry, sell_sl, abs(sell_entry - sell_sl))
                elif hit_buy:
                    entered = ("long", buy_entry, buy_sl, abs(buy_entry - buy_sl))
                elif hit_sell:
                    entered = ("short", sell_entry, sell_sl, abs(sell_entry - sell_sl))
                if entered is None:
                    continue
                side, entry, sl, risk = entered
                if risk <= 0:
                    entered = None
                    continue
                peak = entry
                rest = seq[bi:]      # manage from the entry bar onward
                exit_px = None
                for mb in rest:
                    _, mo, mh, ml, mc = mb
                    # 1) adverse check against current SL (conservative order)
                    if side == "long":
                        if ml <= sl:
                            exit_px = sl; break
                        peak = max(peak, mh)
                    else:
                        if mh >= sl:
                            exit_px = sl; break
                        peak = min(peak, ml)
                    # 2) advance stop per the variant
                    if side == "long":
                        prof_r = (peak - entry) / risk
                        if variant.startswith("trail"):
                            tr = float(variant[5:])
                            if prof_r >= tr:
                                sl = max(sl, peak - tr * risk)
                        elif variant == "be1.0" and prof_r >= 1.0:
                            sl = max(sl, entry)
                    else:
                        prof_r = (entry - peak) / risk
                        if variant.startswith("trail"):
                            tr = float(variant[5:])
                            if prof_r >= tr:
                                sl = min(sl, peak + tr * risk)
                        elif variant == "be1.0" and prof_r >= 1.0:
                            sl = min(sl, entry)
                if exit_px is None:
                    exit_px = rest[-1][4]     # session close (day's last bar close)
                # R incl. round-trip cost
                cost = RT_COST * entry
                if side == "long":
                    r = (exit_px - entry - cost) / risk
                else:
                    r = (entry - exit_px - cost) / risk
                results.append(r)
                break   # one trade per symbol per day (first break wins)
    return results


def stats(rs):
    if not rs:
        return None
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    return {
        "n": len(rs),
        "exp": mean(rs),
        "wr": len(wins) / len(rs) * 100,
        "avg_win": mean(wins) if wins else 0.0,
        "avg_loss": mean(losses) if losses else 0.0,
        "gt1": sum(1 for r in wins if r >= 1.0),
        "gt2": sum(1 for r in wins if r >= 2.0),
        "gt3": sum(1 for r in wins if r >= 3.0),
        "best": max(rs),
    }


def main():
    variants = ["none", "trail0.5", "trail1.0", "trail1.5", "be1.0"]
    print("# Trailing-stop probe — EA logic on cached 1h data (cost ~0.06% RT)\n")
    print("Legend: exp=expectancy R/trade, WR=win%, aWin/aLoss=avg win/loss R,")
    print("        >=1R/2R/3R = winners of that size (the tail that pays the bills)\n")

    # per-variant pooled across the 4-symbol portfolio
    header = f"{'variant':9s} | {'n':>4s} {'exp':>6s} {'WR%':>5s} {'aWin':>5s} {'aLoss':>6s} | {'>=1R':>4s} {'>=2R':>4s} {'>=3R':>4s} {'best':>5s}"
    print(header); print("-" * len(header))
    pooled = {}
    for v in variants:
        allr = []
        for sym, prof in SYMS.items():
            allr += simulate(sym, prof, v)
        pooled[v] = allr
        s = stats(allr)
        print(f"{v:9s} | {s['n']:>4d} {s['exp']:>6.3f} {s['wr']:>5.1f} "
              f"{s['avg_win']:>5.2f} {s['avg_loss']:>6.2f} | "
              f"{s['gt1']:>4d} {s['gt2']:>4d} {s['gt3']:>4d} {s['best']:>5.2f}")

    # per-symbol expectancy under baseline vs current EA trail
    print("\n## per-symbol: baseline (no trail) vs EA trail0.5\n")
    print(f"{'symbol':8s} | {'none exp':>9s} {'n':>4s} | {'trail0.5 exp':>12s} {'n':>4s}")
    for sym, prof in SYMS.items():
        a = stats(simulate(sym, prof, "none"))
        b = stats(simulate(sym, prof, "trail0.5"))
        print(f"{sym:8s} | {a['exp']:>9.3f} {a['n']:>4d} | {b['exp']:>12.3f} {b['n']:>4d}")

    print("\n*Simplified stop-entry fills on 1h bars, conservative intrabar order "
          "(adverse-first). Relative comparison between variants is the signal.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
