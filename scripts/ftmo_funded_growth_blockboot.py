#!/usr/bin/env python3
"""Block-bootstrap robustness for the funded ordering. iid daily resampling
ignores clustering (a bad week is worse than one bad day); block bootstrap
(length-5 blocks) preserves short-run serial dependence. Re-rank the 3 finalists
under both samplers: fixed1.0, smooth (best profit-funded), smooth+guard."""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from importlib import import_module
from statistics import mean, median
random.seed(23)
dp=import_module("ftmo_deep_portfolio")
legs=dp.legs
w={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.25,"JP225":0.45}
day_ret=[]
for d in dp.alldays:
    r=0.0;t=False
    for s,ww in w.items():
        if s in legs and d in legs[s]: r+=ww*legs[s][d]; t=True
    if t: day_ret.append(r/100.0)
NR=len(day_ret)

def block_sampler(need, L=5):
    out=[]
    while len(out)<need:
        i=random.randrange(NR); out.extend(day_ret[i:i+L])
    return out[:need]

def smooth_mult(eq,hw):
    prof=(eq-1.0)*100; dd=(hw-eq)*100
    if eq<1.0 or dd>=1.5: return 1.0
    return min(1.5,1.0+0.08*max(0,prof))

def run(model, guard, block, N=180, paths=20000, PAYOUT_D=30, RETAIN=0.005):
    ruin=0; wds=[]; tps=[]
    for _ in range(paths):
        seq=block_sampler(N,5) if block else None
        eq=1.0;hw=1.0;busted=False;wd=0.0
        for day in range(1,N+1):
            m=1.0 if model=="fixed1.0" else smooth_mult(eq,hw)
            if guard and ((-day)%PAYOUT_D)<3: m*=0.5
            base=seq[day-1] if block else random.choice(day_ret)
            d=base*m
            if eq<1.0:
                ddp=(1.0-eq)*100
                if ddp>=6: d*=0.35
                elif ddp>=3: d*=0.60
            if d<=-0.05: ruin+=1;busted=True;break
            eq*=(1+d)
            if eq<=0.90: ruin+=1;busted=True;break
            hw=max(hw,eq)
            if day%PAYOUT_D==0 and eq>1.0+RETAIN:
                take=eq-(1.0+RETAIN); wd+=take; eq-=take; hw=eq
        if not busted: wds.append(wd); tps.append(wd+(eq-1.0))
    return dict(ruin=ruin/paths*100,
                mean_wd=mean(wds)*100 if wds else 0,
                med_tp=median(tps)*100 if tps else 0)

print(f"{'sampler':8s} {'model':14s} {'ruin%':>6s} {'ortÇek%':>8s} {'medTP%':>7s}")
for block,lbl in [(False,"iid"),(True,"block5")]:
    for model,guard,name in [("fixed1.0",False,"fixed1.0"),("smooth",False,"smooth"),("smooth",True,"smooth+guard")]:
        r=run(model,guard,block)
        print(f"{lbl:8s} {name:14s} {r['ruin']:>5.2f}% {r['mean_wd']:>7.1f}% {r['med_tp']:>6.1f}%")
