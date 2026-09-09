#!/usr/bin/env python3
"""OUR OWN composite TA: an entry-quality score from causal features, weights
LEARNED on train, validated on test. Features (all known at arm time):
  f_trend  : breakout dir vs 20d SMA trend (+1 aligned / -1 counter)
  f_coil   : -percentile of yesterday's range in last 7 (compression=high score)
  f_orbsz  : +percentile of today's opening range vs trailing-20d (big=high)
  f_pdmom  : breakout dir vs prior-day momentum (+1/-1)
Score = sum(w_i * z(f_i)), w_i = train correlation(f_i, R). Then test whether the
TOP-scored trades robustly beat base (bootstrap CI), pooled across core instruments.
"""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, pstdev, median
random.seed(17)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def trades_with_features(sym,cost,trail):
    bd,days=prep(sym)
    closes={d:bd[d][-1][4] for d in days}; opens={d:bd[d][0][1] for d in days}
    dhi={d:max(b[2] for b in bd[d]) for d in days}; dlo={d:min(b[3] for b in bd[d]) for d in days}
    drng={d:dhi[d]-dlo[d] for d in days}
    orbhist=[]; rows=[]
    for di,day in enumerate(days):
        db=bd[day]
        first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        mid=(hi+lo)/2; orbsz=(hi-lo)/mid if mid>0 else 0
        # features (causal)
        if di<21: 
            orbhist.append(orbsz); continue
        sma=mean(closes[days[j]] for j in range(di-20,di)); trend=1 if closes[days[di-1]]>sma else -1
        last7=sorted(drng[days[j]] for j in range(di-7,di))
        coil_pct = sum(1 for x in last7 if x<drng[days[di-1]])/len(last7)  # 0=narrowest
        orb_pct = sum(1 for x in orbhist[-20:] if x<orbsz)/len(orbhist[-20:])
        pdmom = 1 if closes[days[di-1]]>opens[days[di-1]] else -1
        orbhist.append(orbsz)
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: side="long" if abs(o-hi)<=abs(o-lo) else "short"
            elif hb: side="long"
            elif hs: side="short"
            else: continue
            sdir=1 if side=="long" else -1
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
            R=((ex-e-cost*e)/rk) if side=="long" else ((e-ex-cost*e)/rk)
            f=dict(trend=sdir*trend, coil=(1-coil_pct), orbsz=orb_pct, pdmom=sdir*pdmom)
            rows.append((day,f,R)); break
    return rows

rows=[]
for sym,cost,trail in [("XAUUSD",0.0004,0.0),("XAGUSD",0.0004,0.0),("BTC",0.0010,0.3)]:
    rows+=trades_with_features(sym,cost,trail)
rows.sort(key=lambda r:r[0])
split=rows[int(len(rows)*0.6)][0]
train=[r for r in rows if r[0]<=split]; test=[r for r in rows if r[0]>split]
feats=["trend","coil","orbsz","pdmom"]

# standardize features on train, weight by train corr with R
def col(data,f): return [r[1][f] for r in data]
mu={f:mean(col(train,f)) for f in feats}; sd={f:pstdev(col(train,f)) or 1 for f in feats}
Rtr=[r[2] for r in train]; mR=mean(Rtr); sR=pstdev(Rtr) or 1
w={}
for f in feats:
    zf=[(r[1][f]-mu[f])/sd[f] for r in train]
    w[f]=mean(zf[i]*(Rtr[i]-mR)/sR for i in range(len(train)))  # corr
print("learned weights (train corr with R):", {k:round(v,3) for k,v in w.items()})

def score(r): return sum(w[f]*(r[1][f]-mu[f])/sd[f] for f in feats)
def boot(vals,N=5000):
    if not vals: return (0,0,0)
    ms=sorted(mean([random.choice(vals) for _ in vals]) for _ in range(N))
    return mean(vals),ms[int(0.05*N)],ms[int(0.95*N)]

teR=[r[2] for r in test]; bm,lo,hi=boot(teR)
print(f"\nbase (all test):      n={len(test)} OOS={bm:+.3f} CI=[{lo:+.3f},{hi:+.3f}]")
scored=sorted(test,key=score)
for name,sub in [("top 50% score",scored[len(scored)//2:]),
                 ("top 33% score",scored[2*len(scored)//3:]),
                 ("bottom 33% score",scored[:len(scored)//3])]:
    rs=[r[2] for r in sub]; m,l,h=boot(rs)
    print(f"{name:18s}: n={len(sub):4d} OOS={m:+.3f} CI=[{l:+.3f},{h:+.3f}] {'>0' if l>0 else 'x0'}")
