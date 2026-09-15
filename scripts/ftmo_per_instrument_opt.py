#!/usr/bin/env python3
"""Per-instrument HONEST optimisation of OUR OWN ORB breakout edge.

Every parameter is causal (known at arm time). Params are chosen on the TRAIN
split (first 60% of days) and validated on the untouched TEST split (last 40%).
A change is only 'real' if it beats baseline on TEST too. No same-bar tricks.
"""
import sys, statistics
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
import ftmo_trail_probe as p
from statistics import mean

def prep(sym):
    bars = p.load(sym); bd = {}
    for b in bars: bd.setdefault(p.utc_day(b[0]), []).append(b)
    days = sorted(bd)
    return bd, days

def sim(bd, days, cost, range_h=0, range_len=1, buf=0.0, stop_mode="opp",
        stop_frac=1.0, exit_h=24, side="both", rangefilt=0.0, trail=0.0):
    """Return list of (day, R). rangefilt: require range>=k*trailing20d-median range%."""
    hist_rng = []   # trailing range% for causal filter
    out = []
    for di, day in enumerate(days):
        db = bd[day]
        rng = [b for b in db if range_h <= p.utc_hour(b[0]) < range_h+range_len]
        if not rng: continue
        hi = max(b[2] for b in rng); lo = min(b[3] for b in rng)
        if hi <= lo: continue
        rsz = (hi-lo)
        rpct = rsz / ((hi+lo)/2)
        # causal range filter using trailing median (known before today's break)
        ok = True
        if rangefilt > 0 and len(hist_rng) >= 20:
            med = statistics.median(hist_rng[-20:])
            if rpct < rangefilt * med: ok = False
        hist_rng.append(rpct)
        if not ok: continue
        seq = [b for b in db if p.utc_hour(b[0]) >= range_h+range_len
               and (exit_h>=24 or p.utc_hour(b[0]) < exit_h)]
        if not seq: continue
        b_ent = hi + buf*rsz
        s_ent = lo - buf*rsz
        ent = None
        for bi, b in enumerate(seq):
            _, o, h, l, c = b
            hb = h >= b_ent and side in ("both","long")
            hs = l <= s_ent and side in ("both","short")
            if hb and hs:
                pick = "long" if abs(o-b_ent)<=abs(o-s_ent) else "short"
            elif hb: pick="long"
            elif hs: pick="short"
            else: continue
            if pick=="long":
                e = max(b_ent, o)
                sl = lo if stop_mode=="opp" else e - stop_frac*rsz
            else:
                e = min(s_ent, o)
                sl = hi if stop_mode=="opp" else e + stop_frac*rsz
            rk = abs(e-sl)
            if rk<=0: continue
            rest = seq[bi:]; ex = rest[-1][4]; peak=e
            for mb in rest:
                _,mo,mh,ml,mc = mb
                if pick=="long":
                    if ml<=sl: ex=sl; break
                    peak=max(peak,mh)
                    if trail>0 and peak-e>=trail*rk: sl=max(sl,peak-trail*rk)
                else:
                    if mh>=sl: ex=sl; break
                    peak=min(peak,ml)
                    if trail>0 and e-peak>=trail*rk: sl=min(sl,peak+trail*rk)
            co = cost*e
            r = ((ex-e-co)/rk) if pick=="long" else ((e-ex-co)/rk)
            out.append((day, r)); break
    return out

def score(trades, days_train_max):
    tr = [r for d,r in trades if d<=days_train_max]
    te = [r for d,r in trades if d>days_train_max]
    return (mean(tr) if tr else -9, len(tr)), (mean(te) if te else -9, len(te))

def optimize(sym, cost):
    bd, days = prep(sym)
    split = days[int(len(days)*0.6)]
    base = dict(range_h=0, range_len=1, buf=0.0, stop_mode="opp", stop_frac=1.0,
                exit_h=24, side="both", rangefilt=0.0, trail=(0.3 if sym=="BTC" else 0.0))
    grids = {
        "range_h":[0,1,2,13],
        "range_len":[1,2,3],
        "buf":[0.0,0.03,0.06,0.10,0.15],
        "stop_mode":["opp"], "stop_frac":[0.5,0.75,1.0,1.25],
        "exit_h":[24,20,21,22,23],
        "side":["both","long","short"],
        "rangefilt":[0.0,0.5,0.8,1.0,1.2],
        "trail":[0.0,0.2,0.3,0.5],
    }
    cfg = dict(base)
    def ev(c):
        t = sim(bd,days,cost,**{k:c[k] for k in ["range_h","range_len","buf",
             "stop_mode","stop_frac","exit_h","side","rangefilt","trail"]})
        return score(t, split)
    (btr,_),(bte,_) = ev(cfg)
    order = ["range_h","range_len","buf","stop_frac","exit_h","side","rangefilt","trail"]
    for _pass in range(2):
        for dim in order:
            best=None
            for v in grids.get(dim,[cfg[dim]]):
                c=dict(cfg); c[dim]=v
                (tr,ntr),(te,nte)=ev(c)
                if ntr<40: continue           # need enough train trades
                if best is None or tr>best[0]:
                    best=(tr,v,te,nte)
            if best: cfg[dim]=best[1]
    (ftr,ntr),(fte,nte)=ev(cfg)
    return base, cfg, (btr,bte), (ftr,ntr,fte,nte)

for sym,cost in [("XAUUSD",0.0004),("XAGUSD",0.0004),("BTC",0.0010)]:
    base,cfg,(b_tr,b_te),(ftr,ntr,fte,nte)=optimize(sym,cost)
    print(f"\n===== {sym} =====")
    print(f"  baseline: TRAIN {b_tr:+.3f}  TEST {b_te:+.3f}")
    diff={k:cfg[k] for k in cfg if cfg[k]!=base[k]}
    print(f"  tuned   : TRAIN {ftr:+.3f} (n={ntr})  TEST {fte:+.3f} (n={nte})")
    print(f"  changed : {diff if diff else 'nothing'}")
    verdict = "REAL (TEST beats baseline)" if fte>b_te+0.02 else \
              "curve-fit (TEST no better)" if fte<=b_te+0.02 else "?"
    print(f"  verdict : {verdict}")

print("\n\n===== BTC tuned-config STABILITY: 5-fold, each param isolated =====")
bd,days = prep("BTC"); cost=0.0010
baseB = dict(range_h=0,range_len=1,buf=0.0,stop_mode="opp",stop_frac=1.0,
             exit_h=24,side="both",rangefilt=0.0,trail=0.3)
tuned = dict(baseB); tuned.update(range_h=1,buf=0.06,stop_frac=0.5,rangefilt=1.0,trail=0.2)
def folds5(cfg):
    t = sim(bd,days,cost,**cfg)
    rs=[r for _,r in t]
    if len(rs)<25: return None
    n=len(rs)//5
    fo=[mean(rs[i*n:(i+1)*n]) for i in range(5)]
    return mean(rs),len(rs),fo,sum(1 for x in fo if x>0)
for name,cfg in [("baseline",baseB),("tuned(all 5)",tuned)]:
    m,n,fo,pos=folds5(cfg)
    print(f"  {name:14s}: exp={m:+.3f} n={n}  folds={['%+.2f'%x for x in fo]}  {pos}/5 pos")
print("  -- isolate each tuned change on top of baseline --")
for k in ["range_h","buf","stop_frac","rangefilt","trail"]:
    c=dict(baseB); c[k]=tuned[k]
    m,n,fo,pos=folds5(c)
    print(f"  +{k}={tuned[k]:<5}: exp={m:+.3f} n={n}  {pos}/5 pos  folds={['%+.2f'%x for x in fo]}")

print("\n\n===== SINGLE LEVER: causal range-size filter, k-fold, all core =====")
for sym,cost,trail in [("XAUUSD",0.0004,0.0),("XAGUSD",0.0004,0.0),("BTC",0.0010,0.3)]:
    bd,days=prep(sym)
    print(f"  -- {sym} --")
    for rf in [0.0,0.5,0.8,1.0,1.2]:
        t=sim(bd,days,cost,rangefilt=rf,trail=trail)
        rs=[r for _,r in t]
        if len(rs)<25: print(f"    rf={rf}: too few"); continue
        n=len(rs)//5; fo=[mean(rs[i*n:(i+1)*n]) for i in range(5)]
        pos=sum(1 for x in fo if x>0)
        print(f"    rf={rf:<4}: exp={mean(rs):+.3f}  n={len(rs):4d}  {pos}/5 pos")

print("\n\n===== GOLD range-filter: strict TRAIN/TEST out-of-sample =====")
bd,days=prep("XAUUSD"); cost=0.0004
split=days[int(len(days)*0.6)]
def tt(rf):
    t=sim(bd,days,cost,rangefilt=rf)
    tr=[r for d,r in t if d<=split]; te=[r for d,r in t if d>split]
    return (mean(tr),len(tr)),(mean(te),len(te))
print("   rf     TRAIN(n)         TEST(n)")
for rf in [0.0,0.5,0.8,1.0,1.2]:
    (tr,ntr),(te,nte)=tt(rf)
    print(f"   {rf:<5} {tr:+.3f}({ntr:4d})     {te:+.3f}({nte:4d})")
# pick best rf on TRAIN, report its TEST
cands=[(tt(rf)[0][0],rf) for rf in [0.5,0.8,1.0,1.2]]
best_rf=max(cands)[1]
(tr,_),(te,nte)=tt(best_rf); (btr,_),(bte,_)=tt(0.0)
print(f"\n  best-on-TRAIN rf={best_rf}: TEST {te:+.3f} (n={nte})  vs baseline TEST {bte:+.3f}")
print(f"  --> {'REAL, adopt' if te>bte+0.02 else 'not robust, keep baseline'}")
