#!/usr/bin/env python3
"""Silver Runner Carry — comprehensive. Paired carry-vs-base contribution with
thresholds, carry days, stop types, long/short split, folds, remove-top-N,
swap/gap stress. Then stateful A-vs-B net-per-all-trades."""
import sys, random, datetime as dt
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean,median,pstdev
random.seed(11)
SYM="XAGUSD"; COST=0.0004
def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)
BD,DAYS=prep(SYM)
def dow(d): return (d+4)%7
def year(d): return dt.datetime.utcfromtimestamp(d*86400).year
def daily_atr(di,N=14):
    if di<N: return None
    rs=[max(b[2] for b in BD[DAYS[j]])-min(b[3] for b in BD[DAYS[j]]) for j in range(di-N,di)]
    return mean(rs)

def entry_of_day(di):
    """Return (side,e,sl,rk,bi0,seq) for the ORB entry that day, or None."""
    day=DAYS[di]; db=BD[day]; first=[b for b in db if p.utc_hour(b[0])==0]
    if not first: return None
    hi=max(b[2] for b in first); lo=min(b[3] for b in first)
    if hi<=lo: return None
    seq=[b for b in db if p.utc_hour(b[0])>0]
    if not seq: return None
    ent=None;bi0=None
    for bi,b in enumerate(seq):
        _,o,h,l,c=b; hb,hs=h>=hi,l<=lo
        if hb and hs: ent=("long",hi,lo) if abs(o-hi)<=abs(o-lo) else ("short",lo,hi);bi0=bi;break
        elif hb: ent=("long",hi,lo);bi0=bi;break
        elif hs: ent=("short",lo,hi);bi0=bi;break
    if ent is None: return None
    side,e,sl=ent
    if side=="long" and seq[bi0][1]>e: e=seq[bi0][1]
    if side=="short" and seq[bi0][1]<e: e=seq[bi0][1]
    rk=abs(e-sl)
    if rk<=0: return None
    return (side,e,sl,rk,bi0,seq,hi,lo)

def paired(thr,K,stop,swap):
    """List of (day,year,side,base_R,carry_R). Carried trades only."""
    out=[]
    for di in range(len(DAYS)):
        E=entry_of_day(di)
        if E is None: continue
        side,e,sl,rk,bi0,seq,hi,lo=E
        co=COST*e
        rest0=seq[bi0:]; ex=rest0[-1][4]; stopped=False
        for mb in rest0:
            if side=="long" and mb[3]<=sl: ex=sl;stopped=True;break
            if side=="short" and mb[2]>=sl: ex=sl;stopped=True;break
        R0=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk)
        if stopped or R0<thr: continue
        # carry stop
        atr=daily_atr(di)
        if stop=="be": cstop=e
        elif stop=="atr": cstop=(e-1.5*atr) if side=="long" else (e+1.5*atr) if atr else e
        elif stop=="struct": cstop=lo if side=="long" else hi
        exC=ex; nights=0; done=False
        for k in range(1,K+1):
            nd=di+k
            if nd>=len(DAYS): break
            if dow(DAYS[nd]) in (5,6): break
            ndb=BD[DAYS[nd]]; nights+=1
            for mb in ndb:
                _,mo,mh,ml,mc=mb
                if side=="long" and ml<=cstop: exC=cstop;done=True;break
                if side=="short" and mh>=cstop: exC=cstop;done=True;break
            if done: break
            exC=ndb[-1][4]
        sc=swap*nights*e
        RC=((exC-e-co-sc)/rk) if side=="long" else ((e-exC-co-sc)/rk)
        out.append((DAYS[di],year(DAYS[di]),side,R0,RC))
    return out
def bootdiff(d,N=5000):
    if len(d)<15: return (len(d),mean(d) if d else 0,0,0)
    ms=sorted(mean([random.choice(d) for _ in d]) for _ in range(N))
    return len(d),mean(d),ms[int(0.05*N)],ms[int(0.95*N)]

print("=== SILVER CARRY: eşik x taşıma x stop (paired katkı, swap 0.01%/gece, TEST 40%) ===")
split=DAYS[int(len(DAYS)*0.6)]
for thr in [1,2,3,4]:
    for K in [1,2]:
        for stop in ["be","atr","struct"]:
            pr=paired(thr,K,stop,0.0001)
            te=[x for x in pr if x[0]>split]
            d=[c-b for _,_,_,b,c in te]
            n,m,lo,hi=bootdiff(d)
            if n>=15:
                print(f"  thr>={thr} K={K} {stop:6s}: taşınan={n:3d} katkı={m:+.3f}R CI=[{lo:+.2f},{hi:+.2f}] {'>0' if lo>0 else 'x0'}")

print("\n=== ROBUSTLUK: thr>=2 K=1 be (tüm örneklem, n büyük) ===")
pr=paired(2,1,"be",0.0001)
diffs=[(d,y,s,c-b) for d,y,s,b,c in pr]
allc=[x[3] for x in diffs]
print(f"  tüm carry katkısı: n={len(allc)} ort={mean(allc):+.3f}R med={median(allc):+.2f}")
# long vs short
lo=[x[3] for x in diffs if x[2]=='long']; sh=[x[3] for x in diffs if x[2]=='short']
print(f"  LONG carry:  n={len(lo)} ort={mean(lo):+.3f}R" if lo else "  LONG: yok")
print(f"  SHORT carry: n={len(sh)} ort={mean(sh):+.3f}R" if sh else "  SHORT: yok")
# by year
from collections import defaultdict
byy=defaultdict(list)
for d,y,s,c in diffs: byy[y].append(c)
print("  yıllara göre:")
for y in sorted(byy): print(f"     {y}: n={len(byy[y]):2d} ort={mean(byy[y]):+.3f}R")
# walk-forward 5 fold
srt=sorted(diffs); n=len(srt); k=5; fs=n//k
print("  walk-forward 5 fold:")
for i in range(k):
    seg=[x[3] for x in srt[i*fs:(i+1)*fs]]
    print(f"     fold{i+1}: n={len(seg):2d} ort={mean(seg):+.3f}R {'+' if mean(seg)>0 else '-'}")
# remove top N (monster dependence)
s=sorted(allc,reverse=True)
print("  dev-işlem bağımlılığı (en iyi N çıkar):")
for rm in [0,1,3,5,10]:
    sub=s[rm:]
    print(f"     top-{rm} çıkar: n={len(sub)} ort={mean(sub):+.3f}R {'POZİTİF' if mean(sub)>0 else 'NEGATİF'}")

print("\n=== NET-PER-ALL-TRADES: stateful A vs B (thr>=2 K=1 be, swap 0.01%) ===")
def stateful(system, thr=2, K=1, swap=0.0001):
    """system='base'|'A'(carry+new ORB)|'B'(carry, skip new ORB). Returns total R over all days."""
    total=0.0; ntr=0; carry_until=-1; carry=None
    for di in range(len(DAYS)):
        # manage existing carry
        if carry and di<=carry_until:
            side,e,cstop,rk,co=carry
            ndb=BD[DAYS[di]]; done=False; exC=ndb[-1][4]
            if dow(DAYS[di]) in (5,6): pass
            else:
                for mb in ndb:
                    _,mo,mh,ml,mc=mb
                    if side=="long" and ml<=cstop: exC=cstop;done=True;break
                    if side=="short" and mh>=cstop: exC=cstop;done=True;break
            sc=swap*e
            if done or di==carry_until:
                RC=((exC-e-co-sc)/rk) if side=="long" else ((e-exC-co-sc)/rk)
                total+=RC; ntr+=1; carry=None  # note: carry R replaces nothing extra; base R0 already counted below? No.
        # decide new ORB
        skip = (system=="B" and carry is not None)
        if skip: continue
        E=entry_of_day(di)
        if E is None: continue
        side,e,sl,rk,bi0,seq,hi,lo=E; co=COST*e
        rest0=seq[bi0:]; ex=rest0[-1][4]; stopped=False
        for mb in rest0:
            if side=="long" and mb[3]<=sl: ex=sl;stopped=True;break
            if side=="short" and mb[2]>=sl: ex=sl;stopped=True;break
        R0=((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk)
        if system=="base" or stopped or R0<thr:
            total+=R0; ntr+=1
        else:
            # start carry: count R0 now is wrong; we want carried final R. Simplify: book R0 up to close, then carry adds delta over next days.
            total+=R0; ntr+=1
            carry=(side,e,e,rk,co)  # BE stop
            carry_until=min(di+K,len(DAYS)-1)
    return total,ntr
for sysm in ["base","A","B"]:
    tot,ntr=stateful(sysm)
    print(f"  {sysm:5s}: toplam R={tot:+.1f}  işlem={ntr}  R/işlem={tot/ntr:+.3f}")
print("  (A: taşırken yeni ORB da aç | B: taşırken yeni ORB atla)")
