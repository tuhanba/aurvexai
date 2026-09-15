#!/usr/bin/env python3
"""Failed Breakout Reversal (fade) — HONEST, look-ahead-free.

Rules (no future info):
  1. Build the opening-range (hi,lo) from the hour==RANGE_H UTC bars.
  2. Scan bars after the range. A 'failed upside break' = a bar whose HIGH pokes
     above hi but whose CLOSE is back below hi. Symmetric for downside.
     -> This is only KNOWN at that bar's close.
  3. Enter the FADE on the NEXT bar's OPEN (short after failed-up, long after
     failed-down). Strictly next bar => no same-bar look-ahead.
  4. Stop (for a short) ABOVE entry:
       - 'fakeout' mode: at the fakeout bar's HIGH (the poked extreme)
       - 'range'   mode: at hi (the range edge)
  5. No TP. Exit at session close, stop checked bar-by-bar (conservative: if a
     bar's high>=stop for a short -> exit at stop that bar).
  6. Round-trip cost applied. Walk-forward OOS folds reported.
"""
import os, sys
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
import ftmo_trail_probe as p
from statistics import mean

def run(sym, range_h=0, stop_mode="fakeout", cost=0.0004, sess_end=23):
    p.RT_COST = cost
    bars = p.load(sym)
    bd = {}
    for b in bars:
        bd.setdefault(p.utc_day(b[0]), []).append(b)
    trades = []
    for day in sorted(bd):
        db = bd[day]
        rng = [b for b in db if p.utc_hour(b[0]) == range_h]
        if not rng: continue
        hi = max(b[2] for b in rng); lo = min(b[3] for b in rng)
        if hi <= lo: continue
        seq = [b for b in db if p.utc_hour(b[0]) > range_h]
        entered = False
        for i in range(len(seq) - 1):
            _, o, h, l, c = seq[i]
            # failed upside break -> short fade
            if h >= hi and c < hi:
                nb = seq[i+1]
                entry = nb[1]                       # next bar OPEN
                stop = h if stop_mode == "fakeout" else hi
                if stop <= entry: continue          # must be above a short entry
                rk = stop - entry
                rest = seq[i+1:]
                ex = rest[-1][4]
                for mb in rest:
                    if mb[2] >= stop: ex = stop; break
                co = cost * entry
                r = (entry - ex - co) / rk
                trades.append((day, r)); entered = True; break
            # failed downside break -> long fade
            if l <= lo and c > lo:
                nb = seq[i+1]
                entry = nb[1]
                stop = l if stop_mode == "fakeout" else lo
                if stop >= entry: continue
                rk = entry - stop
                rest = seq[i+1:]
                ex = rest[-1][4]
                for mb in rest:
                    if mb[3] <= stop: ex = stop; break
                co = cost * entry
                r = (ex - entry - co) / rk
                trades.append((day, r)); entered = True; break
    return trades

def folds(trades, k=5):
    if len(trades) < k*3: return []
    n = len(trades)//k
    out = []
    for f in range(k):
        seg = [r for _, r in trades[f*n:(f+1)*n]]
        out.append(mean(seg) if seg else 0.0)
    return out

for sym, cost in [("XAUUSD",0.0004),("XAGUSD",0.0004),("BTC",0.0010)]:
    print(f"\n=== {sym}  (cost={cost}) ===")
    for mode in ["fakeout","range"]:
        t = run(sym, 0, mode, cost)
        if not t:
            print(f"  {mode:8s}: no trades"); continue
        rs = [r for _, r in t]
        wr = sum(1 for r in rs if r>0)/len(rs)*100
        fo = folds(t)
        pos = sum(1 for x in fo if x>0)
        print(f"  {mode:8s}: exp={mean(rs):+.3f}  n={len(rs):4d}  WR={wr:.0f}%  "
              f"OOS folds={['%+.2f'%x for x in fo]}  {pos}/{len(fo)} pos")
