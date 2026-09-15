#!/usr/bin/env python3
"""Two more causal hybrids, rigorously (k-fold + bootstrap CI):
  1) Silver: trend-align AND range-filter combined.
  2) Cross-instrument confluence: filter silver/BTC breakout by GOLD's prior-day
     trend direction (causal: gold's prior completed day, known before today)."""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, median
random.seed(9)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def gold_trend_map(N=20):
    bd,days=prep("XAUUSD"); closes={d:bd[d][-1][4] for d in days}
    out={}
    for di,day in enumerate(days):
        if di>=N:
            sma=mean(closes[days[j]] for j in range(di-N,di))
            out[day]=1 if closes[days[di-1]]>sma else -1
    return out

def sim(sym,cost,trail,align=False,rangefilt=0.0,xtrend=None,N=20,lookback=20):
    bd,days=prep(sym); closes={d:bd[d][-1][4] for d in days}; hist=[]; out=[]
    for di,day in enumerate(days):
        db=bd[day]
        first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        mid=(hi+lo)/2; rp=(hi-lo)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(hist)>=lookback and rp<rangefilt*median(hist[-lookback:]): ok=False
        hist.append(rp)
        if not ok: continue
        trend=0
        if di>=N:
            sma=mean(closes[days[j]] for j in range(di-N,di))
            trend=1 if closes[days[di-1]]>sma else -1
        xt = xtrend.get(day,0) if xtrend else None
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: side="long" if abs(o-hi)<=abs(o-lo) else "short"
            elif hb: side="long"
            elif hs: side="short"
            else: continue
            sdir=1 if side=="long" else -1
            if align and trend!=0 and sdir!=trend: break
            if xtrend is not None and xt!=0 and sdir!=xt: break
            e=hi if side=="long" else lo; sl=lo if side=="long" else hi
            if side=="long" and o>e: e=o
            if side=="short" and o<e: e=o
            rk=abs(e-sl)
            if rk<=0: continue
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

def kfold(t,k=5):
    rs=[r for _,r in t]
    if len(rs)<20: return (0,0,[],0)
    n=len(rs)//k; fo=[mean(rs[i*n:(i+1)*n]) for i in range(k)]
    return mean(rs),len(rs),fo,sum(1 for x in fo if x>0)
def boot(vals,N=5000):
    if not vals: return (0,0,0)
    ms=sorted(mean([random.choice(vals) for _ in vals]) for _ in range(N))
    return mean(vals),ms[int(0.05*N)],ms[int(0.95*N)]
def report(name,sym,t):
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    m,n,fo,pos=kfold(t); te=[r for d,r in t if d>split]; bm,lo,hi=boot(te)
    print(f"  {name:34s}: n={n:4d} kfold={m:+.3f} {pos}/5  OOS={bm:+.3f} CI=[{lo:+.3f},{hi:+.3f}] {'>0' if lo>0 else 'x0'}")

gt=gold_trend_map()
print("### 1) Silver: align + range combined ###")
report("silver base",           "XAGUSD", sim("XAGUSD",0.0004,0.0))
report("silver align",          "XAGUSD", sim("XAGUSD",0.0004,0.0,align=True))
report("silver range1.0",       "XAGUSD", sim("XAGUSD",0.0004,0.0,rangefilt=1.0))
report("silver align+range1.0", "XAGUSD", sim("XAGUSD",0.0004,0.0,align=True,rangefilt=1.0))
print("### 2) Cross-instrument: GOLD prior-day trend filters ... ###")
report("silver base",           "XAGUSD", sim("XAGUSD",0.0004,0.0))
report("silver x-gold-trend",   "XAGUSD", sim("XAGUSD",0.0004,0.0,xtrend=gt))
report("BTC base",              "BTC",    sim("BTC",0.0010,0.3))
report("BTC x-gold-trend",      "BTC",    sim("BTC",0.0010,0.3,xtrend=gt))
