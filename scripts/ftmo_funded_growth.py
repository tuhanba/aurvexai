#!/usr/bin/env python3
"""Funded Growth Mode — objective = geometric growth + payout reliability, NOT
challenge pass. Profit-funded risk scaling (use earned buffer, protect high-water)
vs fixed. Bootstrap the real account daily-return series; measure geometric growth,
breach, drawdown, payout over 90 trading days."""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from importlib import import_module
from statistics import mean, median, pstdev
random.seed(23)
dp=import_module("ftmo_deep_portfolio")
legs=dp.legs
w={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.25,"JP225":0.45}  # base 1.0x, NAS100 out
alldays=dp.alldays
day_ret=[]
for d in alldays:
    r=0.0;t=False
    for s,ww in w.items():
        if s in legs and d in legs[s]: r+=ww*legs[s][d]; t=True
    if t: day_ret.append(r/100.0)  # fraction
print(f"gerçek günlük getiri: n={len(day_ret)} ort={mean(day_ret)*100:+.3f}% std={pstdev(day_ret)*100:.3f}%")

def riskmult(model, eq, hw):
    """eq, hw normalized to start=1.0. Returns per-trade risk multiplier."""
    prof=(eq-1.0)*100  # profit % above initial
    dd_from_hw=(hw-eq)*100
    if model=="fixed1.0": return 1.0
    if model=="fixed1.3": return 1.3
    if model=="stepped":
        if eq<1.0: return 1.0   # de-risk handled in returns already; below start = base
        if dd_from_hw>=1.5: return 1.0
        if prof>=6: return 1.45
        if prof>=4: return 1.30
        if prof>=2: return 1.15
        return 1.0
    if model=="smooth":
        if eq<1.0: return 1.0
        if dd_from_hw>=1.5: return 1.0
        return min(1.5, 1.0+0.08*max(0,prof))   # +0.08x per +1% profit, cap 1.5
    if model=="hw_reset":
        if eq<1.0 or dd_from_hw>=1.5: return 1.0
        return min(1.5,1.0+0.10*max(0,prof))
    return 1.0

def run(model, N=90, paths=20000, dloss=0.05, oloss=0.10):
    finals=[]; breaches=0; maxdds=[]
    for _ in range(paths):
        eq=1.0; hw=1.0; mdd=0; busted=False
        for _ in range(N):
            m=riskmult(model,eq,hw)
            d=random.choice(day_ret)*m
            # funded de-risk when below start still applies (survival)
            if eq<1.0:
                ddp=(1.0-eq)*100
                if ddp>=6: d*=0.35
                elif ddp>=3: d*=0.60
            if d<=-dloss: breaches+=1; busted=True; break
            eq*=(1+d)
            if eq<=1-oloss: breaches+=1; busted=True; break
            hw=max(hw,eq); mdd=max(mdd,(hw-eq))
        if not busted:
            finals.append(eq); maxdds.append(mdd)
    fin=sorted(finals)
    n=len(fin)
    def pct(x): return fin[int(x*n)] if n else 0
    return dict(model=model, breach=breaches/paths*100,
                med=(median(finals)-1)*100 if finals else 0,
                mean=(mean(finals)-1)*100 if finals else 0,
                p5=(pct(0.05)-1)*100, p95=(pct(0.95)-1)*100,
                maxdd=mean(maxdds)*100 if maxdds else 0)
print("\n=== FUNDED 90-gün: geometrik büyüme + breach (gerçek getiri serisi) ===")
print(f"{'model':10s} {'breach%':>8s} {'medyan%':>8s} {'ort%':>7s} {'p5%':>7s} {'p95%':>8s} {'ort maxDD%':>11s}")
for model in ["fixed1.0","fixed1.3","stepped","smooth","hw_reset"]:
    r=run(model)
    print(f"{r['model']:10s} {r['breach']:>7.1f}% {r['med']:>7.1f}% {r['mean']:>6.1f}% {r['p5']:>6.1f}% {r['p95']:>7.1f}% {r['maxdd']:>10.1f}%")
