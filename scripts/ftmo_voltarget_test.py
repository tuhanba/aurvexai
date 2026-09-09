#!/usr/bin/env python3
"""Causal volatility-conditioned sizing test (account-level, honest train/test).
Sizes UP on high-trailing-vol days (vol known at entry). Conclusion: it LOWERS
out-of-sample pass probability -- a prop challenge is variance-constrained, so
levering into high-vol regimes adds bust risk faster than edge. Keep fixed sizing;
only the drawdown de-risk (v2.4) helps. Reproduce:
  PYTHONPATH=src:scripts python scripts/ftmo_voltarget_test.py
"""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from statistics import pstdev
import ftmo_trail_probe as p
from importlib import import_module
random.seed(21)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

dp=import_module("ftmo_deep_portfolio")
legs=dp.legs; base_w=dp.base_w; trainD=dp.trainD; testD=dp.testD

def vol_pct_map(sym,N=20):
    bd,days=prep(sym); closes={d:bd[d][-1][4] for d in days}
    out={}; allv=[]
    for i,d in enumerate(days):
        if i<N: continue
        rs=[closes[days[j]]/closes[days[j-1]]-1 for j in range(i-N+1,i+1)]
        v=pstdev(rs); out[d]=sum(1 for x in allv if x<v)/len(allv) if allv else 0.5; allv.append(v)
    return out
vp={s:vol_pct_map(s) for s in legs}

def acct_vt(weights, day_subset, lo_mult, hi_mult):
    out=[]
    for d in day_subset:
        r=0.0; traded=False
        for s,w in weights.items():
            if d in legs[s]:
                m=1.0
                if d in vp[s]:
                    pc=vp[s][d]; m=hi_mult if pc>=0.66 else (lo_mult if pc<=0.33 else 1.0)
                r+=w*m*legs[s][d]; traded=True
        if traded: out.append(r)
    return out

def mc(day_ret,target=10,dloss=5,oloss=10,N=15000):
    if not day_ret: return 0
    npass=0
    for _ in range(N):
        eq=0.0;steps=0
        while steps<400:
            steps+=1; d=random.choice(day_ret); dd=-eq
            if dd>=6: d*=0.35
            elif dd>=3: d*=0.60
            if d<=-dloss: break
            eq+=d
            if eq<=-oloss: break
            if eq>=target: npass+=1; break
        else: npass+=1
    return npass/N*100

print(f"  fixed sizing:           TEST pass={mc(dp.acct_returns(base_w,testD)):.1f}%")
for lo,hi in [(1.0,1.3),(0.8,1.3),(1.0,1.5),(0.7,1.4)]:
    print(f"  vol-size lo={lo} hi={hi}:   TRAIN={mc(acct_vt(base_w,trainD,lo,hi)):.1f}%  "
          f"TEST={mc(acct_vt(base_w,testD,lo,hi)):.1f}%")
