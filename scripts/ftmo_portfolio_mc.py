#!/usr/bin/env python3
"""Account-level pass probability with REAL cross-instrument correlation.
Bootstrap whole trading days (preserving same-day correlation) -> P(pass)."""
import sys, random
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
import ftmo_trail_probe as p
from statistics import mean, pstdev
random.seed(7)

def orb_daily_R(sym, cost, trail=0.0, range_h=0):
    p.RT_COST = cost
    bars = p.load(sym); bd = {}
    for b in bars: bd.setdefault(p.utc_day(b[0]), []).append(b)
    out = {}
    for day in sorted(bd):
        db = bd[day]
        first = [b for b in db if p.utc_hour(b[0]) == range_h]
        if not first: continue
        hi = max(b[2] for b in first); lo = min(b[3] for b in first)
        if hi <= lo: continue
        seq = [b for b in db if p.utc_hour(b[0]) > range_h]
        if not seq: continue
        ent = None
        for bi, b in enumerate(seq):
            _, o, h, l, c = b
            if ent is None:
                hb, hs = h >= hi, l <= lo
                if hb and hs:
                    ent = ("long",hi,lo) if abs(o-hi)<=abs(o-lo) else ("short",lo,hi)
                elif hb: ent = ("long",hi,lo)
                elif hs: ent = ("short",lo,hi)
                if ent is None: continue
                side, e, sl = ent
                if side=="long" and o>e: e=o
                if side=="short" and o<e: e=o
                rk = abs(e-sl)
                if rk<=0: ent=None; continue
                rest = seq[bi:]; ex = rest[-1][4]; peak=e
                for mb in rest:
                    _,mo,mh,ml,mc = mb
                    if side=="long":
                        if ml<=sl: ex=sl; break
                        peak=max(peak,mh)
                        if trail>0 and peak-e>=trail*rk: sl=max(sl, peak-trail*rk)
                    else:
                        if mh>=sl: ex=sl; break
                        peak=min(peak,ml)
                        if trail>0 and e-peak>=trail*rk: sl=min(sl, peak+trail*rk)
                co = cost*e
                out[day] = ((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk)
                break
    return out

# core book
book = [("XAUUSD",0.0004,0.0,0.35), ("XAGUSD",0.0004,0.0,0.35), ("BTC",0.0010,0.3,0.30)]
Rmaps = {sym: orb_daily_R(sym,cost,trail) for sym,cost,trail,_ in book}
riskw = {sym:w for sym,_,_,w in book}

# align on union of days -> daily account return %
alldays = sorted(set().union(*[set(m) for m in Rmaps.values()]))
day_ret = []   # list of account daily return % (only days with >=1 trade)
for d in alldays:
    r = 0.0; traded=False
    for sym in Rmaps:
        if d in Rmaps[sym]:
            r += riskw[sym] * Rmaps[sym][d]; traded=True
    if traded: day_ret.append(r)

print(f"# Real joint daily account returns  (n_days={len(day_ret)})")
print(f"  mean daily = {mean(day_ret):+.3f}%   std = {pstdev(day_ret):.3f}%")
# pairwise same-day correlation
syms=[s for s,_,_,_ in book]
common = [d for d in alldays if all(d in Rmaps[s] for s in syms)]
print(f"  days all-3 traded together: {len(common)}")
def corr(a,b):
    xs=[Rmaps[a][d] for d in common]; ys=[Rmaps[b][d] for d in common]
    mx,my=mean(xs),mean(ys); sx,sy=pstdev(xs),pstdev(ys)
    if sx==0 or sy==0: return 0
    return mean([(x-mx)*(y-my) for x,y in zip(xs,ys)])/(sx*sy)
for i in range(len(syms)):
    for j in range(i+1,len(syms)):
        print(f"  corr {syms[i]}/{syms[j]} = {corr(syms[i],syms[j]):+.3f}")

# bootstrap challenge paths (resample whole days -> preserves within-day corr)
def mc(target, dloss, oloss, ndays_max=60, N=20000):
    npass=nfail_daily=nfail_over=ntimeout=0
    for _ in range(N):
        eq=0.0
        for _day in range(ndays_max):
            d = random.choice(day_ret)
            # daily floor check (intraday approx: worst = the day's realised)
            if d <= -dloss: nfail_daily+=1; break
            eq += d
            if eq <= -oloss: nfail_over+=1; break
            if eq >= target: npass+=1; break
        else:
            ntimeout+=1
    tot=N
    return npass/tot*100, nfail_daily/tot*100, nfail_over/tot*100, ntimeout/tot*100

for tgt,label in [(10,"Phase1 +10%"),(5,"Phase2 +5%")]:
    pas,fd,fo,to = mc(tgt,5,10)
    print(f"\n# {label}: PASS={pas:.1f}%  fail(daily-5%)={fd:.1f}%  "
          f"fail(overall-10%)={fo:.1f}%  timeout60d={to:.1f}%")

print("\n\n===== FTMO-CORRECT: no time limit, with v2.4 de-risk =====")
def mc2(target, dloss=5, oloss=10, N=40000, derisk=True):
    npass=nbust=0
    for _ in range(N):
        eq=0.0; steps=0
        while steps < 400:
            steps+=1
            d = random.choice(day_ret)
            if derisk:  # shrink risk as equity draws down (v2.4)
                dd = -eq  # current drawdown %
                if dd >= 6: d *= 0.35
                elif dd >= 3: d *= 0.60
            if d <= -dloss: nbust+=1; break
            eq += d
            if eq <= -oloss: nbust+=1; break
            if eq >= target: npass+=1; break
        else:
            npass+=1  # positive drift, no time limit -> treat unresolved as eventual pass
    return npass/N*100, nbust/N*100

for tgt,label in [(10,"Phase1 +10%"),(5,"Phase2 +5%")]:
    for dr in (False, True):
        pas,bust = mc2(tgt, derisk=dr)
        tag = "with de-risk" if dr else "no de-risk  "
        print(f"  {label} [{tag}]: PASS={pas:.1f}%  BUST={bust:.1f}%")
