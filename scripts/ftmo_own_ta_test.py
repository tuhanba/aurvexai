#!/usr/bin/env python3
"""Our own TA: causal price-STRUCTURE pre-filters for the ORB breakout.
Each is mechanically motivated and knowable at arm time (uses only prior days):
  coil    : yesterday's full range in the BOTTOM third of the last 7 day-ranges
            (volatility compression -> expansion). Trade only post-coil.
  expand  : yesterday in the TOP third (post-expansion continuation).
  inside  : yesterday's range INSIDE the day before (coil variant).
Validated with k-fold + bootstrap CI; only ship if CI>0 and neighbourhood-robust.
"""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean
random.seed(13)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def sim(sym,cost,trail,mode="none"):
    bd,days=prep(sym)
    dhi={d:max(b[2] for b in bd[d]) for d in days}
    dlo={d:min(b[3] for b in bd[d]) for d in days}
    drange={d:dhi[d]-dlo[d] for d in days}
    out=[]
    for di,day in enumerate(days):
        db=bd[day]
        first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        # causal structural context from prior days
        ok=True
        if mode!="none":
            if di<8: ok=False
            else:
                prev=days[di-1]
                last7=[drange[days[j]] for j in range(di-7,di)]   # 7 days ending yesterday
                s=sorted(last7); t1=s[len(s)//3]; t2=s[2*len(s)//3]
                if mode=="coil":   ok = drange[prev] <= t1
                if mode=="expand": ok = drange[prev] >= t2
                if mode=="inside":
                    d2=days[di-2]
                    ok = (dhi[prev]<=dhi[d2] and dlo[prev]>=dlo[d2])
        if not ok: continue
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: side="long" if abs(o-hi)<=abs(o-lo) else "short"
            elif hb: side="long"
            elif hs: side="short"
            else: continue
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
    if len(rs)<20: return (0,0,0)
    n=len(rs)//k; fo=[mean(rs[i*n:(i+1)*n]) for i in range(k)]
    return mean(rs),len(rs),sum(1 for x in fo if x>0)
def boot(vals,N=5000):
    if not vals: return (0,0,0)
    ms=sorted(mean([random.choice(vals) for _ in vals]) for _ in range(N))
    return mean(vals),ms[int(0.05*N)],ms[int(0.95*N)]
def rep(sym,cost,trail,mode):
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    t=sim(sym,cost,trail,mode); m,n,pos=kfold(t)
    te=[r for d,r in t if d>split]; bm,lo,hi=boot(te)
    print(f"  {mode:8s}: n={n:4d} kfold={m:+.3f} {pos}/5  OOS={bm:+.3f} CI=[{lo:+.3f},{hi:+.3f}] {'>0' if lo>0 else 'x0'}")

for sym,cost,trail in [("XAUUSD",0.0004,0.0),("XAGUSD",0.0004,0.0),("BTC",0.0010,0.3)]:
    print(f"# {sym}")
    for mode in ["none","coil","expand","inside"]:
        rep(sym,cost,trail,mode)
