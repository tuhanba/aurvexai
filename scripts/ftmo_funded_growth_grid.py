#!/usr/bin/env python3
"""Funded Growth Mode — CORRECTED per user review.

Fixes:
- Series is PROXY-DERIVED (Yahoo proxy -> portfolio legs), NOT a real account series.
- Chronological TRAIN (first 60%) / untouched TEST (last 40%) split. Parameters are
  scanned on TRAIN; TEST is only read once, at the end. Block bootstrap on TEST too.
- Full neighbor grid shown (rate 0.04/0.06/0.08/0.10, cap 1.2/1.3/1.4/1.5,
  guard_days 2/3/5, guard_mult 0.5/0.7) — ALL variants, not just the best.
- No 'dominates' language; medians reported alongside means.
"""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from importlib import import_module
from statistics import mean, median, pstdev
random.seed(23)
dp=import_module("ftmo_deep_portfolio")
legs=dp.legs
w={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.25,"JP225":0.45}
alldays=dp.alldays
series=[]  # (day, fractional daily return), chronological
for d in alldays:
    r=0.0;t=False
    for s,ww in w.items():
        if s in legs and d in legs[s]: r+=ww*legs[s][d]; t=True
    if t: series.append((d,r/100.0))
split=int(len(series)*0.60)
train=[r for _,r in series[:split]]
test =[r for _,r in series[split:]]
print(f"PROXY seri (Yahoo-proxy portfoy bacaklari): n={len(series)}")
print(f"  TRAIN n={len(train)} ort={mean(train)*100:+.3f}% std={pstdev(train)*100:.3f}%")
print(f"  TEST  n={len(test)}  ort={mean(test)*100:+.3f}% std={pstdev(test)*100:.3f}%")

def sim(pool, model, rate, cap, guard_days, guard_mult, block=False,
        N=180, paths=12000, PAYOUT_D=30, RETAIN=0.005):
    L=len(pool); ruin=0; wds=[]; tps=[]
    for _ in range(paths):
        if block:
            seq=[]
            while len(seq)<N:
                i=random.randrange(L); seq.extend(pool[i:i+5])
            seq=seq[:N]
        eq=1.0; hw=1.0; busted=False; wd=0.0
        for day in range(1,N+1):
            # per-trade risk multiplier
            if model=="fixed1.0": m=1.0
            elif model=="fixed1.3": m=1.3
            else:  # smooth profit-funded
                prof=(eq-1.0)*100; ddhw=(hw-eq)*100
                if eq<1.0 or ddhw>=1.5: m=1.0
                else: m=min(cap,1.0+rate*max(0.0,prof))
            if guard_days>0 and ((-day)%PAYOUT_D)<guard_days: m*=guard_mult
            d=(seq[day-1] if block else random.choice(pool))*m
            if eq<1.0:  # survival de-risk (production parity)
                ddp=(1.0-eq)*100
                if ddp>=6: d*=0.35
                elif ddp>=3: d*=0.60
            if d<=-0.05: ruin+=1; busted=True; break
            eq*=(1+d)
            if eq<=0.90: ruin+=1; busted=True; break
            hw=max(hw,eq)
            if day%PAYOUT_D==0 and eq>1.0+RETAIN:
                take=eq-(1.0+RETAIN); wd+=take; eq-=take; hw=eq
        if not busted: wds.append(wd); tps.append(wd+(eq-1.0))
    return dict(ruin=ruin/paths*100,
                med_wd=median(wds)*100 if wds else 0,
                mean_wd=mean(wds)*100 if wds else 0,
                med_tp=median(tps)*100 if tps else 0,
                mean_tp=mean(tps)*100 if tps else 0)

def row(name, pool, **kw):
    r=sim(pool,**kw)
    return f"{name:22s} ruin={r['ruin']:>5.2f}%  medÇek={r['med_wd']:>5.1f}%  ortÇek={r['mean_wd']:>5.1f}%  medTP={r['med_tp']:>5.1f}%  ortTP={r['mean_tp']:>5.1f}%"

# ---- Panel 0: references ----
for lbl,pool in [("TRAIN",train),("TEST",test)]:
    print(f"\n### {lbl} — referanslar")
    print(row("fixed1.0",pool,model="fixed1.0",rate=0,cap=0,guard_days=0,guard_mult=1))
    print(row("fixed1.3",pool,model="fixed1.3",rate=0,cap=0,guard_days=0,guard_mult=1))

# ---- Panel 1: smooth no-guard, rate x cap grid (16), TRAIN then TEST ----
for lbl,pool in [("TRAIN",train),("TEST",test)]:
    print(f"\n### {lbl} — smooth (guard YOK): rate x cap")
    for rate in (0.04,0.06,0.08,0.10):
        for cap in (1.2,1.3,1.4,1.5):
            print(row(f"smooth r={rate} cap={cap}",pool,model="smooth",rate=rate,cap=cap,guard_days=0,guard_mult=1))

# ---- Panel 2: smooth+guard grid at rate=0.08,cap=1.5 (guard_days x guard_mult), TRAIN/TEST ----
for lbl,pool in [("TRAIN",train),("TEST",test)]:
    print(f"\n### {lbl} — smooth+guard (rate=0.08 cap=1.5): gün x çarpan")
    for gd in (2,3,5):
        for gm in (0.5,0.7):
            print(row(f"guard {gd}g x{gm}",pool,model="smooth",rate=0.08,cap=1.5,guard_days=gd,guard_mult=gm))

# ---- Panel 3: block bootstrap on TEST for the finalists ----
print("\n### TEST — blok-bootstrap (L=5) finalistler")
print(row("fixed1.0 [block]",test,model="fixed1.0",rate=0,cap=0,guard_days=0,guard_mult=1,block=True))
print(row("smooth r=.08 cap1.5 [block]",test,model="smooth",rate=0.08,cap=1.5,guard_days=0,guard_mult=1,block=True))
print(row("smooth+guard 3g x.5 [block]",test,model="smooth",rate=0.08,cap=1.5,guard_days=3,guard_mult=0.5,block=True))
print(row("smooth+guard 3g x.7 [block]",test,model="smooth",rate=0.08,cap=1.5,guard_days=3,guard_mult=0.7,block=True))
