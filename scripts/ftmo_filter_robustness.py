import sys, random, statistics
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
import ftmo_trail_probe as p
from statistics import mean, median
random.seed(1)

def prep(sym):
    bars=p.load(sym); bd={}
    for b in bars: bd.setdefault(p.utc_day(b[0]),[]).append(b)
    return bd, sorted(bd)

def sim_orb(sym,cost,rangefilt=0.0,lookback=20,range_h=0,olen=1,trail=0.0):
    bd,days=prep(sym); hist=[]; out=[]
    for day in days:
        db=bd[day]
        rng=[b for b in db if range_h<=p.utc_hour(b[0])<range_h+olen]
        if not rng: continue
        hi=max(b[2] for b in rng); lo=min(b[3] for b in rng)
        if hi<=lo: continue
        mid=(hi+lo)/2; rp=(hi-lo)/mid if mid>0 else 0
        ok=True
        if rangefilt>0 and len(hist)>=lookback:
            if rp < rangefilt*median(hist[-lookback:]): ok=False
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
            out.append((day,((ex-e-co)/rk) if side=="long" else ((e-ex-co)/rk))); break
    return out

def oos(sym,cost,rf,lookback=20):
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    t=sim_orb(sym,cost,rf,lookback)
    te=[r for d,r in t if d>split]
    return te

def boot_ci(vals,N=5000):
    if not vals: return (0,0,0)
    ms=[]
    for _ in range(N):
        s=[random.choice(vals) for _ in vals]; ms.append(mean(s))
    ms.sort(); return mean(vals), ms[int(0.05*N)], ms[int(0.95*N)]

print("# GOLD OOS bootstrap 90% CI (filter vs off)")
for rf in [0.0,1.0]:
    te=oos("XAUUSD",0.0004,rf)
    m,lo,hi=boot_ci(te)
    print(f"  rf={rf}: n={len(te)}  mean={m:+.3f}  90%CI=[{lo:+.3f},{hi:+.3f}]  "
          f"{'>0 excluded' if lo>0 else 'CI crosses 0'}")

print("\n# GOLD lookback sensitivity (OOS mean, rf=1.0)")
for lb in [10,15,20,25,30]:
    te=oos("XAUUSD",0.0004,1.0,lb); print(f"  lookback={lb}: n={len(te)} OOS={mean(te):+.3f}")

print("\n# GOLD cost sensitivity (OOS mean)")
for cost in [0.0004,0.0006,0.0008,0.0010]:
    a=oos("XAUUSD",cost,0.0); b=oos("XAUUSD",cost,1.0)
    print(f"  cost={cost}: off={mean(a):+.3f}  filter={mean(b):+.3f}  gain={mean(b)-mean(a):+.3f}")

print("\n# Extend vol-filter idea to INDICES via ORB proxy (do they benefit?)")
for sym in ["GER40","NAS100","JP225"]:
    bd,days=prep(sym); split=days[int(len(days)*0.6)]
    for rf in [0.0,1.0]:
        t=sim_orb(sym,0.0004,rf); te=[r for d,r in t if d>split]
        tag="off   " if rf==0 else "filter"
        print(f"  {sym:7s} {tag}: n={len(te):4d} OOS={mean(te) if te else 0:+.3f}")
