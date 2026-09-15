#!/usr/bin/env python3
"""Runner Carry Engine (Hipotez B) — honest, no pyramiding, exit-horizon only.
Base: ORB entry, exit at entry-day UTC close or stop (opposite range edge).
Carry: if open R at day-0 close >= threshold, HOLD into next days with a protective
stop, up to K more days (or Friday flatten), then force-close. Measures whether
carrying confirmed runners adds expectancy or gives it back."""
import sys
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean,median
def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)
def dow(utcday): return (utcday+4)%7  # 0=Mon..6=Sun (1970-01-01=Thu)

def sim(sym,cost,mode="base",thr=2.0,carryK=2,carrystop="be"):
    bd,days=prep(sym); dayidx={d:i for i,d in enumerate(days)}; out=[]
    for di,day in enumerate(days):
        db=bd[day]; first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        ent=None; bi0=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: ent=("long",hi,lo) if abs(o-hi)<=abs(o-lo) else ("short",lo,hi); bi0=bi; break
            elif hb: ent=("long",hi,lo); bi0=bi; break
            elif hs: ent=("short",lo,hi); bi0=bi; break
        if ent is None: continue
        side,e,sl=ent
        if side=="long" and seq[bi0][1]>e: e=seq[bi0][1]
        if side=="short" and seq[bi0][1]<e: e=seq[bi0][1]
        rk=abs(e-sl)
        if rk<=0: continue
        co=cost*e
        # --- day 0: to close or stop ---
        rest0=seq[bi0:]; ex=rest0[-1][4]; stopped=False
        for mb in rest0:
            if side=="long" and mb[3]<=sl: ex=sl; stopped=True; break
            if side=="short" and mb[2]>=sl: ex=sl; stopped=True; break
        R0=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk)
        if mode=="base" or stopped or R0<thr:
            out.append(R0); continue
        # --- CARRY: hold into day+1..day+K with protective stop ---
        cstop = e if carrystop=="be" else sl   # breakeven or original SL
        exC=ex; done=False
        for k in range(1,carryK+1):
            nd=di+k
            if nd>=len(days): break
            nday=days[nd]
            if dow(nday) in (5,6): break        # weekend: don't hold over
            ndb=bd[nday]
            for mb in ndb:
                _,mo,mh,ml,mc=mb
                if side=="long" and ml<=cstop: exC=cstop; done=True; break
                if side=="short" and mh>=cstop: exC=cstop; done=True; break
            if done: break
            exC=ndb[-1][4]                       # else carry to this day's close
        RC=((exC-e-co)/rk) if side=="long" else ((e-exC-co)/rk)
        out.append(RC)
    return out

def tail(rs):
    s=sorted(rs,reverse=True); n=len(s); tot=sum(rs)
    top10=sum(s[:max(1,n//10)]); 
    return (top10/tot*100) if tot>0 else 0
def rep(name,rs):
    if not rs: print(f"  {name}: yok"); return
    wr=sum(1 for r in rs if r>0)/len(rs)*100
    print(f"  {name:34s}: exp={mean(rs):+.3f} med={median(rs):+.2f} WR={wr:.0f}% n={len(rs)} top10%kâr-payı={tail(rs):.0f}% max={max(rs):+.1f}")

for sym,cost in [("XAUUSD",0.0004),("XAGUSD",0.0004)]:
    print(f"\n### {sym} — Runner Carry (breakeven stop) ###")
    rep("BASE (gün sonu kapat)", sim(sym,cost,"base"))
    for thr in [1.0,2.0,3.0]:
        for K in [1,2]:
            rep(f"carry thr>={thr}R  K={K}gün  BE-stop", sim(sym,cost,"carry",thr,K,"be"))

import random
random.seed(3)
def sim_paired(sym,cost,thr,K,carrystop,swap_per_night):
    """Return list of (day, base_R, carry_R) for CARRIED trades only, with swap cost."""
    bd,days=prep(sym); out=[]
    for di,day in enumerate(days):
        db=bd[day]; first=[b for b in db if p.utc_hour(b[0])==0]
        if not first: continue
        hi=max(b[2] for b in first); lo=min(b[3] for b in first)
        if hi<=lo: continue
        seq=[b for b in db if p.utc_hour(b[0])>0]
        if not seq: continue
        ent=None;bi0=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
            if hb and hs: ent=("long",hi,lo) if abs(o-hi)<=abs(o-lo) else ("short",lo,hi);bi0=bi;break
            elif hb: ent=("long",hi,lo);bi0=bi;break
            elif hs: ent=("short",lo,hi);bi0=bi;break
        if ent is None: continue
        side,e,sl=ent
        if side=="long" and seq[bi0][1]>e: e=seq[bi0][1]
        if side=="short" and seq[bi0][1]<e: e=seq[bi0][1]
        rk=abs(e-sl)
        if rk<=0: continue
        co=cost*e
        rest0=seq[bi0:]; ex=rest0[-1][4]; stopped=False
        for mb in rest0:
            if side=="long" and mb[3]<=sl: ex=sl;stopped=True;break
            if side=="short" and mb[2]>=sl: ex=sl;stopped=True;break
        R0=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk)
        if stopped or R0<thr: continue
        cstop=e if carrystop=="be" else sl; exC=ex; nights=0; done=False
        for k in range(1,K+1):
            nd=di+k
            if nd>=len(days): break
            nday=days[nd]
            if dow(nday) in (5,6): break
            ndb=bd[nday]; nights+=1
            for mb in ndb:
                _,mo,mh,ml,mc=mb
                if side=="long" and ml<=cstop: exC=cstop;done=True;break
                if side=="short" and mh>=cstop: exC=cstop;done=True;break
            if done: break
            exC=ndb[-1][4]
        swapcost=swap_per_night*nights*e
        RC=((exC-e-co-swapcost)/rk) if side=="long" else ((e-exC-co-swapcost)/rk)
        out.append((day,R0,RC))
    return out
def boot_diff(pairs,N=5000):
    d=[c-b for _,b,c in pairs]
    if len(d)<15: return (len(d),0,0,0)
    ms=sorted(mean([random.choice(d) for _ in d]) for _ in range(N))
    return len(d),mean(d),ms[int(0.05*N)],ms[int(0.95*N)]

print("\n\n### RIGOROUS: carry katkısı (carry - base) paired, swap'lı, OOS ###")
for sym,cost in [("XAUUSD",0.0004),("XAGUSD",0.0004)]:
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    print(f"# {sym}")
    for thr,K in [(2.0,1),(3.0,2)]:
        for swap in [0.0, 0.0001, 0.0002]:   # 0 / 0.01% / 0.02% per gece
            pairs=sim_paired(sym,cost,thr,K,"be",swap)
            te=[pr for pr in pairs if pr[0]>split]
            n,m,lo,hi=boot_diff(te)
            print(f"  thr>={thr} K={K} swap={swap*100:.2f}%/gece: taşınan={n:3d} katkı/işlem(TEST)={m:+.3f}R CI=[{lo:+.3f},{hi:+.3f}] {'>0' if lo>0 else 'x0'}")
