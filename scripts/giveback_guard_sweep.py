#!/usr/bin/env python3
"""Daily give-back guard sweep on the real 5-leg OOS trade stream (owner ask
2026-07-20: prevent a day that peaks then fades back to flat/negative).

Builds each day's intraday running gain from the closed-trade R sequence (ordered
by close time) under the DEPLOYED adaptive target + -10%% kill, then overlays a
give-back guard: arm once the intraday peak clears arm%% of day-open equity, bank
the day when the gain gives back `gb` of that peak. Sweeps arm x gb, day-block
bootstrap for MAR. The closed-R proxy UNDERSTATES the benefit — the scariest
give-back is UNREALIZED (an open winner marking back down), which closed R does
not see; the paper window measures the true effect. Run: python scripts/giveback_guard_sweep.py
"""
import sys, csv, random
import numpy as np
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from joint_optimize import load_portfolio, YEAR_MS
from daily_target_optimize import day_ordinal, KILL
from ml_edge_test import _adx

RISK=0.015; CEIL=0.10; FLOOR=0.08; LO,HI=20.0,40.0; N=300
rows=[[float(x) for x in r[:6]] for r in csv.reader(open("data/research_klines_4h/BTCUSDT_4h.csv"))]
bt=np.array(sorted(rows)); ADX,_,_=_adx(bt[:,2],bt[:,3],bt[:,4])
def regime(ts):
    i=np.searchsorted(bt[:,0],ts,side="right")-1
    return float(np.clip((ADX[max(i,0)]-LO)/(HI-LO),0,1))

trades,_=load_portfolio()
years=(trades[-1][0]-trades[0][0])/YEAR_MS
days={}
for ts,leg,r,g in trades: days.setdefault(day_ordinal(ts),[]).append((ts,r))
keys=sorted(days)
# each day: ordered (by close ts) list of trade R, plus day-open ts for regime
day_seq=[[r for _,r in sorted(days[k])] for k in keys]
day_ts0=[sorted(days[k])[0][0] for k in keys]

def day_ret(rs, ts0, arm=None, gb=None):
    """Intraday running gain with adaptive target flatten, -kill, and optional
    giveback guard (arm=min peak to arm, gb=fraction of peak given back to bank)."""
    tgt=FLOOR+regime(ts0)*(CEIL-FLOOR)
    g=0.0; peak=0.0; armed=False
    for r in rs:
        g+=RISK*r
        peak=max(peak,g)
        if g>=tgt: return tgt
        if g<=-KILL: return -KILL
        if arm is not None:
            if not armed and peak>=arm: armed=True
            if armed and g<=peak*(1-gb): return g   # bank the given-back peak
    return g

def boot(arm=None,gb=None):
    pre=[day_ret(rs,ts0,arm,gb) for rs,ts0 in zip(day_seq,day_ts0)]
    n=len(pre); rng=random.Random(11); cagrs=[];dds=[]
    for _ in range(N):
        eq=peak=1.0;mdd=0.0
        for _ in range(n):
            eq*=(1+pre[rng.randrange(n)])
            if eq<=0: eq=1e-9
            peak=max(peak,eq);mdd=max(mdd,(peak-eq)/peak)
        cagrs.append(eq**(1/years)-1 if eq>0 else -1); dds.append(mdd)
    cagrs.sort();dds.sort()
    mc=cagrs[len(cagrs)//2];md=dds[len(dds)//2]
    # also: avg realized day return + how many days the guard fired
    fired=sum(1 for rs,ts0 in zip(day_seq,day_ts0)
              if arm is not None and _fired(rs,ts0,arm,gb))
    return mc,md,(mc/md if md>0 else 0),np.mean(pre),fired,n

def _fired(rs,ts0,arm,gb):
    tgt=FLOOR+regime(ts0)*(CEIL-FLOOR); g=0.0;peak=0.0;armed=False
    for r in rs:
        g+=RISK*r; peak=max(peak,g)
        if g>=tgt or g<=-KILL: return False
        if not armed and peak>=arm: armed=True
        if armed and g<=peak*(1-gb): return True
    return False

print(f"Giveback-guard sweep — adaptive floor {FLOOR*100:.0f}%/ceil {CEIL*100:.0f}%, real OOS, {len(day_seq)} days, {years:.2f}y, x{N} boot")
print("NOTE: closed-R intraday proxy — UNDERSTATES benefit (misses UNREALIZED peaks, the scary give-back).\n")
print(f"{'config':>26} {'medCAGR%':>9} {'medMaxDD%':>10} {'MAR':>6} {'avgDayR%':>9} {'guard-fired days':>16}")
mc,md,mar,ad,_,n=boot(); print(f"{'baseline (no giveback)':>26} {mc*100:>9.1f} {md*100:>10.1f} {mar:>6.2f} {ad*100:>9.3f} {'--':>16}")
for arm in (0.03,0.04,0.05):
    for gb in (0.25,0.33,0.50):
        mc,md,mar,ad,fired,n=boot(arm,gb)
        tag=f"arm{arm*100:.0f}% giveback{gb*100:.0f}%"
        print(f"{tag:>26} {mc*100:>9.1f} {md*100:>10.1f} {mar:>6.2f} {ad*100:>9.3f} {fired:>7} ({fired/n*100:.0f}%)")
