#!/usr/bin/env python3
"""Fibonacci retracement continuation — cost-honest. Detect the swing (no
lookahead), enter in trend direction when price pulls back to a fib level, hold
H, R vs 2xATR net of cost. Result: NO-GO; the classic 0.5/0.618/0.786 levels are
systematically NEGATIVE (the deeper the retrace, the worse).
Run: python scripts/fib_test.py"""
# Fibonacci retracement — cost-honest. Detect the swing over a lookback (no
# lookahead), and when price pulls back to a fib level IN the swing's trend
# direction, enter (continuation) and hold H bars. R vs 2xATR, net of 0.13%.
import sys, math
import numpy as np
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from ml_edge_test import load, _atr, RT_COST

COINS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","TRXUSDT","DOTUSDT"]
FIBS=[0.382,0.5,0.618,0.786]

def test(level,L,H,band_atr=0.4):
    pooled=[]
    for s in COINS:
        a=load(s,"4h")
        if a is None: continue
        ts,o,h,l,c,v=a.T; n=len(c); atr=_atr(h,l,c)
        fwd=np.zeros(n); fwd[:-H]=c[H:]/c[:-H]-1
        for i in range(L,n-H):
            win_h=h[i-L:i+1]; win_l=l[i-L:i+1]
            hi=win_h.max(); lo=win_l.min()
            if hi-lo < atr[i]*3: continue           # need a real swing
            ihi=i-L+int(np.argmax(win_h)); ilo=i-L+int(np.argmax(-win_l))
            up = ihi>ilo                              # high made after low = uptrend
            rng=hi-lo
            if up:
                fibp=hi-level*rng; side=1
            else:
                fibp=lo+level*rng; side=-1
            if abs(c[i]-fibp) <= band_atr*atr[i]:     # price AT the fib level
                stop=max(2*atr[i]/max(c[i],1e-12),1e-4)
                pooled.append((side*fwd[i]-RT_COST)/stop)
    if not pooled: return None
    arr=np.array(pooled); m=arr.mean(); sd=arr.std() or 1e-9
    return len(arr), m, m/(sd/math.sqrt(len(arr)))

print(f"FIBONACCI retracement continuation — 4h, {len(COINS)} coins, net of {RT_COST*100:.2f}% RT, R vs 2xATR")
print(f"{'fib':>6} {'LB':>3} {'H':>3} {'n':>6} {'netExpR':>9} {'t':>7}  verdict")
for level in FIBS:
    for L in (24,48):
        for H in (6,12):
            r=test(level,L,H)
            if r:
                n,m,t=r
                v="GO?" if (m>0 and t>3) else "no-go"
                print(f"{level:>6} {L:>3} {H:>3} {n:>6} {m:>+9.4f} {t:>+7.1f}  {v}")
