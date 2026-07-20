#!/usr/bin/env python3
"""Cross-sectional relative-strength (market-neutral long-short) — a structurally
DIFFERENT axis from single-asset TA. Rank the universe by trailing return, long
top-K / short bottom-K, hold H, net of cost. Both momentum and short-term
reversal. Result: NO-GO after cost (gross signal real but sub-cost).
Run: python scripts/cross_sectional_test.py"""
# "My own" candidate: CROSS-SECTIONAL relative-strength (market-neutral).
# Rank the universe by trailing return each bar; long top-K, short bottom-K;
# hold H bars; net of cost. Tests BOTH signs: momentum (long winners) and
# short-term reversal (long losers). Structurally different from single-asset TA.
import sys, csv, math
import numpy as np
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from ml_edge_test import load, RT_COST

COINS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","TRXUSDT","DOTUSDT"]

# align all coins on common timestamps
series={}
for s in COINS:
    a=load(s,"4h")
    if a is not None: series[s]={int(t):c for t,_,_,_,c,_ in a}
common=sorted(set.intersection(*[set(d) for d in series.values()]))
C=np.array([[series[s][t] for s in COINS] for t in common])  # [T, N]
T,N=C.shape
years=(common[-1]-common[0])/(365.25*24*3600*1000)

def run(lookback,H,K,sign):
    # ret over lookback ending at t (no lookahead), forward ret t->t+H
    nets=[]
    t=lookback
    while t+H<T:
        past=C[t]/C[t-lookback]-1
        fwd=C[t+H]/C[t]-1
        order=np.argsort(past)              # ascending
        longs=order[-K:] if sign>0 else order[:K]   # mom: top; rev: bottom
        shorts=order[:K] if sign>0 else order[-K:]
        r=fwd[longs].mean()-fwd[shorts].mean()      # market-neutral
        r-=4*RT_COST/ (1)                           # 2 sides * round-trip cost
        nets.append(r)
        t+=H
    if not nets: return None
    arr=np.array(nets); m=arr.mean(); sd=arr.std() or 1e-9
    tstat=m/(sd/math.sqrt(len(arr)))
    per_yr=len(arr)/years
    sharpe=(m/sd)*math.sqrt(per_yr)
    return len(arr),m,tstat,sharpe

print(f"CROSS-SECTIONAL long-short — 4h, {N} coins, {T} bars, {years:.1f}y, net of {RT_COST*100:.2f}% RT/side")
print(f"{'strategy':>26} {'LB':>3} {'H':>3} {'K':>2} {'n':>5} {'netPerHold%':>11} {'t':>6} {'annSharpe':>9}  verdict")
for sign,label in ((1,"momentum"),(-1,"reversal")):
    for lb in (6,12,24,48):
        for H in (6,12):
            for K in (2,3):
                r=run(lb,H,K,sign)
                if r:
                    n,m,tt,sh=r
                    v="GO?" if (m>0 and tt>3 and sh>1) else "no-go"
                    print(f"{label:>26} {lb:>3} {H:>3} {K:>2} {n:>5} {m*100:>+11.3f} {tt:>+6.1f} {sh:>+9.2f}  {v}")
