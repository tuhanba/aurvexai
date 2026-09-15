#!/usr/bin/env python3
"""Per-instrument cost break-even: at what round-trip cost does each leg's OOS
expectancy cross zero? Arms the KAPI-1 read: the max tolerable spread per symbol."""
import sys
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, median

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def orb_R(sym,cost,trail=0.0,rangefilt=0.0,lookback=20,range_h=0,olen=1):
    bd,days=prep(sym); hist=[]; out=[]
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
            out.append(((ex-e-cost*e)/rk) if side=="long" else ((e-ex-cost*e)/rk)); break
    return out

def pdhl_R(sym,cost,rangefilt=0.0,ss=0,se=24):
    bd,days=prep(sym); dayset=set(days); histrp=[]; dr=[]; out=[]
    for day in days:
        db=bd[day]
        if (day-1) not in dayset: dr.append(max(b[2] for b in db)-min(b[3] for b in db)); continue
        prev=bd[day-1]; ph=max(b[2] for b in prev); pl=min(b[3] for b in prev)
        atr=mean(dr[-14:]) if len(dr)>=14 else None
        dr.append(max(b[2] for b in db)-min(b[3] for b in db))
        if not atr or atr<=0 or ph<=pl: continue
        mid=(ph+pl)/2; rp=(ph-pl)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(histrp)>=20 and rp<rangefilt*median(histrp[-20:]): ok=False
        histrp.append(rp)
        if not ok: continue
        d=1.5*atr; seq=[b for b in db if ss<=p.utc_hour(b[0])<se]
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
            rest=seq[bi:]; ex=rest[-1][4]
            for mb in rest:
                if side=="long" and mb[3]<=sl: ex=sl; break
                if side=="short" and mb[2]>=sl: ex=sl; break
            out.append(((ex-e-cost*e)/rk) if side=="long" else ((e-ex-cost*e)/rk)); break
    return out

# find break-even cost (where mean R crosses 0) per leg
def breakeven(fn, **kw):
    lo,hi=0.0,0.01
    for _ in range(40):
        mid=(lo+hi)/2
        m=mean(fn(cost=mid, **kw))
        if m>0: lo=mid
        else: hi=mid
    return lo

legs=[
  ("XAUUSD (gold, filter)", lambda cost: orb_R("XAUUSD",cost,trail=0.0,rangefilt=1.0)),
  ("XAUUSD (gold, no filt)", lambda cost: orb_R("XAUUSD",cost,trail=0.0,rangefilt=0.0)),
  ("XAGUSD (silver)",        lambda cost: orb_R("XAGUSD",cost,trail=0.0)),
  ("BTC (trail0.3)",         lambda cost: orb_R("BTC",cost,trail=0.3)),
  ("GER40",                  lambda cost: pdhl_R("GER40",cost,ss=7,se=20)),
  ("NAS100",                 lambda cost: pdhl_R("NAS100",cost,ss=14,se=20)),
  ("JP225 (filter)",         lambda cost: pdhl_R("JP225",cost,rangefilt=1.0,ss=0,se=6)),
]
print(f"{'leg':24s} {'exp@0.04%':>10s} {'exp@0.10%':>10s} {'break-even cost':>16s}")
for name,fn in legs:
    e04=mean(fn(0.0004)); e10=mean(fn(0.0010))
    lo,hi=0.0,0.02
    for _ in range(44):
        mid=(lo+hi)/2
        (lo,hi)=(mid,hi) if mean(fn(mid))>0 else (lo,mid)
    print(f"{name:24s} {e04:>+10.3f} {e10:>+10.3f} {lo*100:>14.3f}%")
