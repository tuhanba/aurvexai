#!/usr/bin/env python3
"""Funded Growth Mode with PAYOUT CYCLES.

Funded objective is NOT 'pass' — it is: maximise total *withdrawn* profit over a
horizon while minimising risk-of-ruin (a breach ends the funded account and the
earned buffer). Model:
  - initial balance 1.0; static max-loss floor 0.90 (10% of initial, FTMO style);
    daily-loss breach if a single day drops >=5% of start-of-day equity.
  - payout every PAYOUT_D trading days: withdraw a fraction of profit above 1.0,
    retaining a buffer; track cumulative withdrawn.
  - risk models: fixed1.0 / fixed1.3 / stepped / smooth / hw_reset, plus a
    'payout-approach risk reduction' overlay that de-risks in the last K days
    before a scheduled payout to protect the accrued (about-to-be-withdrawn) profit.
  - survival de-risk (below-start) always applies, same as production EA.

Silver-Carry on/off is MOOT: Silver Runner Carry was rejected in Step 1
(full-sample ~0R, monster-dependent). Not re-run here."""
import sys, random
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from importlib import import_module
from statistics import mean, median, pstdev
random.seed(23)
dp=import_module("ftmo_deep_portfolio")
legs=dp.legs
w={"XAUUSD":0.35,"XAGUSD":0.35,"BTC":0.30,"GER40":0.25,"JP225":0.45}
alldays=dp.alldays
day_ret=[]
for d in alldays:
    r=0.0;t=False
    for s,ww in w.items():
        if s in legs and d in legs[s]: r+=ww*legs[s][d]; t=True
    if t: day_ret.append(r/100.0)
print(f"gerçek günlük getiri: n={len(day_ret)} ort={mean(day_ret)*100:+.3f}% std={pstdev(day_ret)*100:.3f}%")

PAYOUT_D=30           # payout cadence (trading days ~ 6 calendar weeks)
RETAIN=0.005          # keep 0.5% profit buffer above 1.0 after each payout
PAYOUT_FRAC=1.0       # withdraw all profit above the retained buffer

def base_mult(model, eq, hw):
    prof=(eq-1.0)*100; dd_from_hw=(hw-eq)*100
    if model=="fixed1.0": return 1.0
    if model=="fixed1.3": return 1.3
    if model=="stepped":
        if eq<1.0 or dd_from_hw>=1.5: return 1.0
        if prof>=6: return 1.45
        if prof>=4: return 1.30
        if prof>=2: return 1.15
        return 1.0
    if model=="smooth":
        if eq<1.0 or dd_from_hw>=1.5: return 1.0
        return min(1.5,1.0+0.08*max(0,prof))
    if model=="hw_reset":
        if eq<1.0 or dd_from_hw>=1.5: return 1.0
        return min(1.5,1.0+0.10*max(0,prof))
    return 1.0

def run(model, payout_guard=False, N=180, paths=30000, dloss=0.05, ofloor=0.90,
        guard_days=3, guard_mult=0.5):
    withdrawn=[]; total_pnl=[]; breaches=0; maxdds=[]; ruin=0
    pay30=[];pay60=[];pay90=[]  # cumulative withdrawn by day 30/60/90 (as % of initial)
    for _ in range(paths):
        eq=1.0; hw=1.0; mdd=0.0; busted=False; wd=0.0
        w30=w60=w90=None
        for day in range(1,N+1):
            m=base_mult(model,eq,hw)
            # payout-approach risk reduction: de-risk in last guard_days before payout
            if payout_guard:
                to_pay=(-day)%PAYOUT_D  # days until next payout boundary
                if to_pay<guard_days: m*=guard_mult
            d=random.choice(day_ret)*m
            if eq<1.0:  # survival de-risk (production parity)
                ddp=(1.0-eq)*100
                if ddp>=6: d*=0.35
                elif ddp>=3: d*=0.60
            if d<=-dloss: breaches+=1; ruin+=1; busted=True; break
            eq*=(1+d)
            if eq<=ofloor: breaches+=1; ruin+=1; busted=True; break
            hw=max(hw,eq); mdd=max(mdd,hw-eq)
            if day%PAYOUT_D==0 and eq>1.0+RETAIN:
                take=(eq-(1.0+RETAIN))*PAYOUT_FRAC
                wd+=take; eq-=take; hw=eq
            if day==30: w30=wd
            if day==60: w60=wd
            if day==90: w90=wd
        if not busted:
            withdrawn.append(wd); total_pnl.append(wd+(eq-1.0)); maxdds.append(mdd)
            pay30.append(w30 or 0); pay60.append(w60 or 0); pay90.append(w90 or 0)
    tp=sorted(total_pnl); n=len(tp)
    def pct(x): return tp[int(x*n)] if n else 0
    # expected shortfall: mean total P&L over worst 5% of ALL paths (breach = -0.10)
    allpnl=sorted(total_pnl+[-0.10]*breaches)
    k=max(1,int(0.05*len(allpnl)))
    es=mean(allpnl[:k])
    return dict(model=model+("+guard" if payout_guard else ""),
        breach=breaches/paths*100, ruin=ruin/paths*100,
        med_wd=median(withdrawn)*100 if withdrawn else 0,
        mean_wd=mean(withdrawn)*100 if withdrawn else 0,
        med_tp=(pct(0.5))*100, p5=(pct(0.05))*100, p95=(pct(0.95))*100,
        maxdd=mean(maxdds)*100 if maxdds else 0, es=es*100,
        p_pay30=sum(1 for x in pay30 if x>0)/len(pay30)*100 if pay30 else 0,
        p_pay60=sum(1 for x in pay60 if x>0)/len(pay60)*100 if pay60 else 0,
        p_pay90=sum(1 for x in pay90 if x>0)/len(pay90)*100 if pay90 else 0)

print("\n=== FUNDED 180-gün, 30-günlük payout döngüsü (gerçek getiri serisi) ===")
print("withdrawn=çekilen kâr; total_pnl=çekilen+kalan; ruin=hesap patlama; ES=en kötü %5 ort P&L")
hdr=f"{'model':16s} {'breach%':>7s} {'ruin%':>6s} {'medÇek%':>8s} {'ortÇek%':>8s} {'p5tp%':>7s} {'medtp%':>7s} {'p95tp%':>8s} {'maxDD%':>7s} {'ES%':>6s} {'pay30':>6s} {'pay60':>6s} {'pay90':>6s}"
print(hdr)
rows=[]
for model in ["fixed1.0","fixed1.3","stepped","smooth","hw_reset"]:
    rows.append(run(model))
    if model in ("stepped","smooth"):
        rows.append(run(model, payout_guard=True))
for r in rows:
    print(f"{r['model']:16s} {r['breach']:>6.2f}% {r['ruin']:>5.2f}% {r['med_wd']:>7.1f}% {r['mean_wd']:>7.1f}% {r['p5']:>6.1f}% {r['med_tp']:>6.1f}% {r['p95']:>7.1f}% {r['maxdd']:>6.1f}% {r['es']:>5.1f}% {r['p_pay30']:>5.0f}% {r['p_pay60']:>5.0f}% {r['p_pay90']:>5.0f}%")
