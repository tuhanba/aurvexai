#!/usr/bin/env python3
"""Breakeven-stop PROPER intrabar backtest (sequenced): arm BE once favorable
excursion reaches ARM x R, then exit at breakeven if price returns to entry.
Overturns an earlier non-sequenced reconstruction that looked +21%: properly
sequenced, the BE-stop is expectancy-NEGATIVE (-7 to -17%) and does not cut
drawdown — it truncates the same positive-skew runner tail as TP laddering.
NOT shipped. Run: python scripts/be_stop_backtest.py"""
# BE-stop PROPER intrabar backtest (sequenced). For each deployed-leg trade,
# walk the entry-TF bars in order: arm breakeven once favorable excursion
# reaches ARM x R; AFTER arming, if price returns to entry, exit at breakeven
# (0 minus a small cost) instead of the trade's actual mechanism exit. This
# captures BOTH the save (losers that had been up) AND the cost (winners cut at
# BE that would have run). Compares to HOLD (the trade's real r_net).
import pickle, os, csv, math
import numpy as np
KL="data/research_klines_4h"; _c={}
def kl(sym):
    s=sym.replace("/","").replace(":USDT","")
    if s in _c: return _c[s]
    p=os.path.join(KL,f"{s}_4h.csv")
    if not os.path.exists(p): _c[s]=None; return None
    rows=[[float(x) for x in r[:6]] for r in csv.reader(open(p))]
    _c[s]=np.array(sorted(rows)); return _c[s]

COST_R=0.05
def be_R(t, arm):
    a=kl(t.symbol)
    if a is None: return None
    seg=a[(a[:,0]>t.open_time)&(a[:,0]<=(t.close_time or t.open_time))]
    if len(seg)==0: return None
    dist=abs(t.entry-t.stop_loss)
    if dist<=0: return None
    long=str(t.side).upper().startswith("L")
    armed=False
    for _,o,h,l,c,v in seg:
        fav=(h-t.entry)/dist if long else (t.entry-l)/dist
        adv_hit_entry = (l<=t.entry) if long else (h>=t.entry)
        if not armed and fav>=arm:
            armed=True
            continue                     # arm this bar; BE can trigger next bars
        if armed and adv_hit_entry:
            return -COST_R               # exited at breakeven
    return t.r_net                       # BE never triggered → real outcome

LEGS={"donchian":"donchian_n10_11c6y","squeeze4h":"sqz4h_q20_11c6y",
      "ichimoku":"ichimoku_11c6y","band_walk":"bandwalk_ts12_5c6y"}
def summ(rs):
    a=np.array(rs); eq=1.0;peak=1.0;mdd=0.0
    for x in a:
        eq*=(1+0.005*x); peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
    return len(a),a.mean(),a.sum(),mdd

for arm in (1.0,1.5,2.0):
    print(f"\n=== ARM_BE_AFTER_R = {arm} ===")
    print(f"{'leg':>11} {'n':>5} | {'HOLD expR':>9} {'totR':>7} {'mDD%':>5} | {'BE expR':>8} {'totR':>7} {'mDD%':>5} {'dExpR%':>6}")
    AH=[];AB=[]
    for name,ck in LEGS.items():
        st=pickle.load(open(f"data/leg_review/{ck}.pkl","rb")); w=st["windows"]
        hold=[];be=[]
        for k in sorted(w):
            for t in w[k]:
                r=be_R(t,arm)
                if r is None: continue
                hold.append(t.r_net); be.append(r)
        AH+=hold;AB+=be
        nh,mh,th,dh=summ(hold); _,mb,tb,db=summ(be)
        print(f"{name:>11} {nh:>5} | {mh:>+9.4f} {th:>+7.1f} {dh*100:>4.0f}% | {mb:>+8.4f} {tb:>+7.1f} {db*100:>4.0f}% {(mb-mh)/abs(mh)*100:>+5.0f}%")
    nh,mh,th,dh=summ(AH); _,mb,tb,db=summ(AB)
    print("-"*82)
    print(f"{'POOLED':>11} {nh:>5} | {mh:>+9.4f} {th:>+7.1f} {dh*100:>4.0f}% | {mb:>+8.4f} {tb:>+7.1f} {db*100:>4.0f}% {(mb-mh)/abs(mh)*100:>+5.0f}%")
