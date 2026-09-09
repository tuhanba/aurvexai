#!/usr/bin/env python3
"""Hybrid/structural tests (causal, train/test):
  A) HTF trend filter: take the breakout only if ALIGNED (or only if COUNTER) to
     the N-day price trend (price vs SMA-N of daily closes, known at arm time).
  B) Prior-day momentum bias: take only breakouts in the direction of the prior
     day's move (sign of prev close-open), causal.
"""
import sys
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def sim(sym,cost,trail,mode="none",N=20):
    """mode: none | align | counter | pdmom (prior-day momentum bias)."""
    bd,days=prep(sym); closes={d:bd[d][-1][4] for d in days}
    opens ={d:bd[d][0][1] for d in days}
    out=[]
    for di,day in enumerate(days):
        db=bd[day]
        first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        # trend context (causal: uses prior completed days only)
        trend=0
        if di>=N:
            sma=mean(closes[days[j]] for j in range(di-N,di))
            trend = 1 if closes[days[di-1]]>sma else -1
        pdmom=0
        if di>=1:
            pdmom = 1 if closes[days[di-1]]>opens[days[di-1]] else -1
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        ent=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: side="long" if abs(o-hi)<=abs(o-lo) else "short"
            elif hb: side="long"
            elif hs: side="short"
            else: continue
            sdir = 1 if side=="long" else -1
            if mode=="align" and trend!=0 and sdir!=trend: ent="skip"; break
            if mode=="counter" and trend!=0 and sdir==trend: ent="skip"; break
            if mode=="pdmom" and pdmom!=0 and sdir!=pdmom: ent="skip"; break
            e=hi if side=="long" else lo; sl=lo if side=="long" else hi
            if side=="long" and o>e: e=o
            if side=="short" and o<e: e=o
            rk=abs(e-sl)
            if rk<=0: ent=None; continue
            rest=seq[bi:]; ex=rest[-1][4]; peak=e
            for mb in rest:
                _,mo,mh,ml,mc=mb
                if side=="long":
                    if ml<=sl: ex=sl; break
                    peak=max(peak,mh)
                    if trail>0 and peak-e>=trail*rk: sl=max(sl,peak-trail*rk)
                else:
                    if mh>=sl: ex=sl; break
                    peak=min(peak,ml)
                    if trail>0 and e-peak>=trail*rk: sl=min(sl,peak+trail*rk)
            out.append((day,((ex-e-cost*e)/rk) if side=="long" else ((e-ex-cost*e)/rk))); break
    return out

for sym,cost,trail in [("XAUUSD",0.0004,0.0),("XAGUSD",0.0004,0.0),("BTC",0.0010,0.3)]:
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    print(f"# {sym}")
    for mode in ["none","align","counter","pdmom"]:
        t=sim(sym,cost,trail,mode)
        te=[r for d,r in t if d>split]
        print(f"  {mode:8s}: n={len(t):4d}  OOS={mean(te) if te else 0:+.3f} (n={len(te)})")

import random
random.seed(5)
def kfold(t,k=5):
    rs=[r for _,r in t]
    if len(rs)<25: return None
    n=len(rs)//k; fo=[mean(rs[i*n:(i+1)*n]) for i in range(k)]
    return mean(rs),len(rs),fo,sum(1 for x in fo if x>0)
def boot(vals,N=5000):
    if not vals: return (0,0,0)
    ms=sorted(mean([random.choice(vals) for _ in vals]) for _ in range(N))
    return mean(vals),ms[int(0.05*N)],ms[int(0.95*N)]

print("\n### ALIGN filter robustness ###")
# N-sensitivity (whole neighbourhood?) using align mode with different SMA windows
def sim_N(sym,cost,trail,N):
    return sim.__wrapped__ if False else sim(sym,cost,trail,"align",N)
for sym,cost,trail in [("XAUUSD",0.0004,0.0),("XAGUSD",0.0004,0.0),("BTC",0.0010,0.3)]:
    print(f"# {sym}")
    for N in [10,20,50]:
        t=sim(sym,cost,trail,"align",N)
        m,n,fo,pos=kfold(t)
        bd,days=prep(sym); split=days[int(len(days)*0.6)]
        te=[r for d,r in t if d>split]; bm,lo,hi=boot(te)
        print(f"  N={N:2d}: kfold={m:+.3f} {pos}/5  OOS={bm:+.3f} CI=[{lo:+.3f},{hi:+.3f}] {'>0' if lo>0 else 'x0'}")
