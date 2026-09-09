import sys
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, median

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def atr14(prev_ranges):
    if len(prev_ranges)<14: return None
    return mean(prev_ranges[-14:])

def sim_pdhl(sym,cost,rangefilt=0.0,lookback=20,atrmult=1.5,trail=0.5,
             sess_start=0,sess_end=24):
    # EA-matching: prior CALENDAR day (day-1). Missing (Sun/holiday) -> skip, as the
    # live EA's PrevDayRange does (this skips index PDHL on Mondays).
    bd,days=prep(sym); dayset=set(days); histrp=[]; dayrange=[]; out=[]
    for di,day in enumerate(days):
        db=bd[day]
        if (day-1) not in dayset:
            dayrange.append(max(b[2] for b in db)-min(b[3] for b in db)); continue
        prev=bd[day-1]
        ph=max(b[2] for b in prev); pl=min(b[3] for b in prev)
        # ATR proxy = mean of last 14 daily ranges
        atr=atr14(dayrange)
        curhi=max(b[2] for b in db); curlo=min(b[3] for b in db)
        dayrange.append(curhi-curlo)
        if not atr or atr<=0 or ph<=pl: continue
        mid=(ph+pl)/2; rp=(ph-pl)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(histrp)>=lookback:
            if rp < rangefilt*median(histrp[-lookback:]): ok=False
        histrp.append(rp)
        if not ok: continue
        d=atrmult*atr
        seq=[b for b in db if sess_start<=p.utc_hour(b[0])<sess_end]
        if not seq: continue
        ent=None
        for bi,b in enumerate(seq):
            _,o,h,l,c=b
            hb=h>=ph; hs=l<=pl
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
            out.append((day,((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk))); break
    return out

sess={"GER40":(7,20),"NAS100":(14,20),"JP225":(0,6)}
print("# INDEX PDHL volatility filter (prior-day range >= mult x trailing median), train/test")
for sym in ["GER40","NAS100","JP225"]:
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    ss,se=sess[sym]
    print(f"  -- {sym} (session {ss}-{se}) --")
    for rf in [0.0,0.8,1.0,1.2]:
        t=sim_pdhl(sym,0.0004,rf,sess_start=ss,sess_end=se)
        tr=[r for d,r in t if d<=split]; te=[r for d,r in t if d>split]
        print(f"     rf={rf}: TRAIN {mean(tr) if tr else 0:+.3f}({len(tr):3d})  "
              f"TEST {mean(te) if te else 0:+.3f}({len(te):3d})")

import random
random.seed(3)
def kfold(t,k=5):
    rs=[r for _,r in t]
    if len(rs)<25: return None
    n=len(rs)//k; fo=[mean(rs[i*n:(i+1)*n]) for i in range(k)]
    return mean(rs),len(rs),fo,sum(1 for x in fo if x>0)
def boot(vals,N=5000):
    ms=sorted(mean([random.choice(vals) for _ in vals]) for _ in range(N))
    return mean(vals),ms[int(0.05*N)],ms[int(0.95*N)]

print("\n# JP225 robustness (full-sample k-fold + OOS bootstrap)")
for rf in [0.0,1.0]:
    t=sim_pdhl("JP225",0.0004,rf,sess_start=0,sess_end=6)
    m,n,fo,pos=kfold(t)
    bd,days=prep("JP225"); split=days[int(len(days)*0.6)]
    te=[r for d,r in t if d>split]
    bm,blo,bhi=boot(te)
    print(f"  rf={rf}: kfold exp={m:+.3f} n={n} {pos}/5 pos folds={['%+.2f'%x for x in fo]}")
    print(f"         OOS n={len(te)} mean={bm:+.3f} 90%CI=[{blo:+.3f},{bhi:+.3f}] "
          f"{'>0' if blo>0 else 'crosses 0'}")
print("\n# JP225 cost sensitivity (OOS gain)")
bd,days=prep("JP225"); split=days[int(len(days)*0.6)]
for cost in [0.0004,0.0006,0.0008]:
    a=[r for d,r in sim_pdhl("JP225",cost,0.0,sess_start=0,sess_end=6) if d>split]
    b=[r for d,r in sim_pdhl("JP225",cost,1.0,sess_start=0,sess_end=6) if d>split]
    print(f"  cost={cost}: off={mean(a):+.3f} filter={mean(b):+.3f} gain={mean(b)-mean(a):+.3f}")
