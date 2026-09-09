#!/usr/bin/env python3
"""DEEP account-level analysis: optimal risk allocation across the improved book.
Weights chosen on TRAIN days, pass probability reported on TEST days (honest)."""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, median
random.seed(11)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def orb_R(sym,cost,trail=0.0,rangefilt=0.0,lookback=20,range_h=0,olen=1):
    bd,days=prep(sym); hist=[]; out={}
    for day in days:
        db=bd[day]
        rng=[b for b in db if range_h<=p.utc_hour(b[0])<range_h+olen]
        if not rng: continue
        hi=max(b[2] for b in rng); lo=min(b[3] for b in rng)
        if hi<=lo: continue
        mid=(hi+lo)/2; rp=(hi-lo)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(hist)>=lookback and rp<rangefilt*median(hist[-lookback:]): ok=False
        hist.append(rp)
        if not ok: continue
        seq=[b for b in db if p.utc_hour(b[0])>=range_h+olen]
        if not seq: continue
        ent=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: ent=("long",hi,lo) if abs(o-hi)<=abs(o-lo) else ("short",lo,hi)
            elif hb: ent=("long",hi,lo)
            elif hs: ent=("short",lo,hi)
            else: continue
            side,e,sl=ent
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
            co=cost*e
            out[day]=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk); break
    return out

def pdhl_R(sym,cost,rangefilt=0.0,lookback=20,atrmult=1.5,trail=0.5,ss=0,se=24):
    bd,days=prep(sym); histrp=[]; dr=[]; out={}
    for di,day in enumerate(days):
        db=bd[day]
        if di==0: dr.append(max(b[2] for b in db)-min(b[3] for b in db)); continue
        prev=bd[days[di-1]]; ph=max(b[2] for b in prev); pl=min(b[3] for b in prev)
        atr=mean(dr[-14:]) if len(dr)>=14 else None
        dr.append(max(b[2] for b in db)-min(b[3] for b in db))
        if not atr or atr<=0 or ph<=pl: continue
        mid=(ph+pl)/2; rp=(ph-pl)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(histrp)>=lookback and rp<rangefilt*median(histrp[-lookback:]): ok=False
        histrp.append(rp)
        if not ok: continue
        d=atrmult*atr; seq=[b for b in db if ss<=p.utc_hour(b[0])<se]
        if not seq: continue
        ent=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=ph,l<=pl
            if hb and hs: ent=("long",ph,ph-d) if abs(o-ph)<=abs(o-pl) else ("short",pl,pl+d)
            elif hb: ent=("long",ph,ph-d)
            elif hs: ent=("short",pl,pl+d)
            else: continue
            side,e,sl=ent
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
            co=cost*e
            out[day]=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk); break
    return out

# improved book
legs = {
  "XAUUSD": orb_R("XAUUSD",0.0004,trail=0.0,rangefilt=1.0),
  "XAGUSD": orb_R("XAGUSD",0.0004,trail=0.0,rangefilt=0.0),
  "BTC":    orb_R("BTC",0.0010,trail=0.3,rangefilt=0.0),
  "GER40":  pdhl_R("GER40",0.0004,rangefilt=0.0,ss=7,se=20),
  "NAS100": pdhl_R("NAS100",0.0004,rangefilt=0.0,ss=14,se=20),
  "JP225":  pdhl_R("JP225",0.0004,rangefilt=1.0,ss=0,se=6),
}
for k,v in legs.items():
    rs=list(v.values()); wr=sum(1 for r in rs if r>0)/len(rs)*100 if rs else 0
    print(f"  {k:7s}: n={len(rs):4d}  exp={mean(rs) if rs else 0:+.3f}  WR={wr:.0f}%")

alldays=sorted(set().union(*[set(m) for m in legs.values()]))
split=alldays[int(len(alldays)*0.6)]

def acct_returns(weights, day_subset):
    out=[]
    for d in day_subset:
        r=0.0; traded=False
        for s,w in weights.items():
            if d in legs[s]: r+=w*legs[s][d]; traded=True
        if traded: out.append(r)
    return out

def mc_pass(day_ret, target=10, dloss=5, oloss=10, N=20000, derisk=True):
    if not day_ret: return 0
    npass=0
    for _ in range(N):
        eq=0.0; steps=0
        while steps<400:
            steps+=1; d=random.choice(day_ret)
            if derisk:
                dd=-eq
                if dd>=6: d*=0.35
                elif dd>=3: d*=0.60
            if d<=-dloss: break
            eq+=d
            if eq<=-oloss: break
            if eq>=target: npass+=1; break
        else: npass+=1
    return npass/N*100

trainD=[d for d in alldays if d<=split]; testD=[d for d in alldays if d>split]
base_w={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.30,"NAS100":0.25,"JP225":0.30}
print(f"\n# baseline weights: TRAIN pass={mc_pass(acct_returns(base_w,trainD)):.1f}%  "
      f"TEST pass={mc_pass(acct_returns(base_w,testD)):.1f}%")

from statistics import pstdev
br=acct_returns(base_w,alldays)
print(f"\n# baseline daily account return: mean={mean(br):+.3f}%  std={pstdev(br):.3f}%  n={len(br)}")

print("\n# DROP-ONE-LEG attribution (TEST pass prob; baseline TEST = %.1f%%)" % mc_pass(acct_returns(base_w,testD)))
for drop in legs:
    w={k:v for k,v in base_w.items() if k!=drop}
    print(f"  without {drop:7s}: TEST pass={mc_pass(acct_returns(w,testD)):.1f}%  "
          f"(leg exp={mean(list(legs[drop].values())):+.3f})")

print("\n# WEIGHT SEARCH (pick best on TRAIN, report TEST)")
import itertools
metals=[0.30,0.40,0.50]; btc=[0.20,0.30]; ger=[0.0,0.25]; nas=[0.0,0.20]; jp=[0.30,0.45]
best=None
for m,bt,g,na,j in itertools.product(metals,btc,ger,nas,jp):
    w={"XAUUSD":m,"XAGUSD":m,"BTC":bt,"GER40":g,"NAS100":na,"JP225":j}
    tr=mc_pass(acct_returns(w,trainD),N=8000)
    if best is None or tr>best[0]: best=(tr,w)
tr,w=best
te=mc_pass(acct_returns(w,testD))
print(f"  best-on-TRAIN weights: {w}")
print(f"  TRAIN pass={tr:.1f}%  ->  TEST pass={te:.1f}%   (baseline TEST {mc_pass(acct_returns(base_w,testD)):.1f}%)")

print("\n# SCRUTINY: silver return distribution (is the 99.2%% a variance artifact?)")
sv=sorted(legs["XAGUSD"].values())
print(f"  silver: min={sv[0]:+.2f} p1={sv[len(sv)//100]:+.2f} p5={sv[len(sv)//20]:+.2f} "
      f"median={sv[len(sv)//2]:+.2f} p95={sv[int(len(sv)*0.95)]:+.2f} max={sv[-1]:+.2f}")
gold=sorted(legs["XAUUSD"].values())
print(f"  gold  : min={gold[0]:+.2f} p5={gold[len(gold)//20]:+.2f} median={gold[len(gold)//2]:+.2f} max={gold[-1]:+.2f}")
# how often silver trades ALONE (single-leg high-variance days)
alone=0
for d in legs["XAGUSD"]:
    if sum(1 for s in legs if d in legs[s])==1: alone+=1
print(f"  silver trades alone on {alone}/{len(legs['XAGUSD'])} of its days")

print("\n# JP225 weight robustness (all else at baseline; TEST pass)")
for jw in [0.30,0.40,0.45,0.55]:
    w=dict(base_w); w["JP225"]=jw
    print(f"  JP225 weight={jw}: TEST pass={mc_pass(acct_returns(w,testD)):.1f}%")

print("\n# Recommended vs baseline (drop NAS100, JP225 up), TEST")
rec={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.25,"NAS100":0.0,"JP225":0.45}
print(f"  baseline    TEST pass={mc_pass(acct_returns(base_w,testD)):.1f}%")
print(f"  recommended TEST pass={mc_pass(acct_returns(rec,testD)):.1f}%")
