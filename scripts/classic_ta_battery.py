#!/usr/bin/env python3
"""Classic-TA battery — 14 textbook indicators, ALL through the same
cost-honest test (net of 0.13% RT, R vs 2xATR, 4h, 11 coins). Demonstrates that
oscillators/mean-reversion LOSE after cost and momentum/trend cluster near zero;
only the trend/breakout family (refined into the deployed legs) survives.
Run: python scripts/classic_ta_battery.py"""
# Broad classic-TA battery, ALL through the SAME cost-honest test:
# signal on CLOSED bar t -> enter next bar -> hold H bars -> net of 0.13% RT
# cost, expressed as R vs a 2xATR stop. Pooled across 11 coins, 4h bars.
import sys, os, csv, math
import numpy as np
sys.path.insert(0,"scripts"); sys.path.insert(0,"src")
from ml_edge_test import load, _rsi, _ema, _atr, _adx, RT_COST

COINS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","TRXUSDT","DOTUSDT"]
H=6  # ~1 day on 4h

def _stoch(h,l,c,n=14):
    out=np.zeros(len(c))
    for i in range(len(c)):
        lo=l[max(0,i-n+1):i+1].min(); hi=h[max(0,i-n+1):i+1].max()
        out[i]=100*(c[i]-lo)/max(hi-lo,1e-12)
    return out
def _cci(h,l,c,n=20):
    tp=(h+l+c)/3; out=np.zeros(len(c))
    for i in range(len(c)):
        w=tp[max(0,i-n+1):i+1]; md=np.mean(np.abs(w-w.mean()))
        out[i]=(tp[i]-w.mean())/max(0.015*md,1e-12)
    return out
def _roc(c,n=10):
    r=np.zeros(len(c)); r[n:]=c[n:]/c[:-n]-1; return r
def _macd(c):
    return _ema(c,12)-_ema(c,26)
def _willr(h,l,c,n=14):
    out=np.zeros(len(c))
    for i in range(len(c)):
        hi=h[max(0,i-n+1):i+1].max(); lo=l[max(0,i-n+1):i+1].min()
        out[i]=-100*(hi-c[i])/max(hi-lo,1e-12)
    return out
def _don(h,l,c,n=20):
    up=np.zeros(len(c)); dn=np.zeros(len(c))
    for i in range(len(c)):
        up[i]=h[max(0,i-n):i].max() if i>0 else h[i]
        dn[i]=l[max(0,i-n):i].min() if i>0 else l[i]
    return up,dn

# each signal fn returns array in {-1,0,+1} (dir to trade at bar t, no lookahead)
def signals(a):
    ts,o,h,l,c,v=a.T; n=len(c)
    rsi=_rsi(c); adx,pdi,ndi=_adx(h,l,c); e9,e21,e50=_ema(c,9),_ema(c,21),_ema(c,50)
    st=_stoch(h,l,c); cci=_cci(h,l,c); roc=_roc(c); macd=_macd(c); wr=_willr(h,l,c)
    up,dn=_don(h,l,c); atr=_atr(h,l,c)
    S={}
    # --- OSCILLATORS / MEAN-REVERSION (the "tons of TA") ---
    S["RSI mean-rev (os/ob 30/70)"]=np.where(rsi<30,1,np.where(rsi>70,-1,0))
    S["Stochastic mean-rev"]=np.where(st<20,1,np.where(st>80,-1,0))
    S["CCI mean-rev (+-100)"]=np.where(cci<-100,1,np.where(cci>100,-1,0))
    S["Williams%R mean-rev"]=np.where(wr<-80,1,np.where(wr>-20,-1,0))
    S["Bollinger mean-rev(z)"]=None  # set below
    # z-score mean reversion
    sma20=np.array([c[max(0,i-19):i+1].mean() for i in range(n)])
    sd20=np.array([c[max(0,i-19):i+1].std() for i in range(n)])
    z=(c-sma20)/np.maximum(sd20,1e-12)
    S["Bollinger mean-rev(z)"]=np.where(z<-2,1,np.where(z>2,-1,0))
    # --- MOMENTUM (same idea, different clothes) ---
    S["RSI momentum (>50)"]=np.where(rsi>55,1,np.where(rsi<45,-1,0))
    S["MACD sign"]=np.where(macd>0,1,-1)
    S["ROC momentum"]=np.where(roc>0,1,-1)
    S["Stochastic momentum"]=np.where(st>50,1,-1)
    # --- TREND / BREAKOUT (where the survivors live) ---
    S["EMA 9/21 cross"]=np.where(e9>e21,1,-1)
    S["EMA 21/50 cross"]=np.where(e21>e50,1,-1)
    S["ADX+DI trend (>25)"]=np.where((adx>25)&(pdi>ndi),1,np.where((adx>25)&(ndi>pdi),-1,0))
    S["Donchian breakout(20)"]=np.where(c>up,1,np.where(c<dn,-1,0))
    S["Price>EMA50 trend"]=np.where(c>e50,1,-1)
    return S, atr

def evaluate(sigfn):
    pooled=[]
    for sym in COINS:
        a=load(sym,"4h")
        if a is None: continue
        S,atr=signals(a); c=a[:,4]
        fwd=np.zeros(len(c)); fwd[:-H]=c[H:]/c[:-H]-1
        sig=sigfn(S)
        stop=np.maximum(2*atr/np.maximum(c,1e-12),1e-4)
        for i in range(60,len(c)-H):
            if sig[i]!=0:
                net=sig[i]*fwd[i]-RT_COST
                pooled.append(net/stop[i])
    if not pooled: return None
    arr=np.array(pooled); m=arr.mean(); sd=arr.std() or 1e-9
    t=m/(sd/math.sqrt(len(arr)))
    return len(arr),m,t

# get signal names from first coin
a0=load("BTCUSDT","4h"); names=list(signals(a0)[0].keys())
print(f"CLASSIC-TA BATTERY — 4h, {len(COINS)} coins, hold {H} bars, net of {RT_COST*100:.2f}% RT cost, R vs 2xATR")
print(f"{'signal':30s} {'n':>7} {'netExpR':>9} {'t':>7}  verdict")
rows=[]
for name in names:
    r=evaluate(lambda S,nm=name:S[nm])
    if r: rows.append((name,*r))
for name,n,m,t in sorted(rows,key=lambda x:-x[2]):
    v="GO?" if (m>0 and t>3) else "no-go"
    print(f"{name:30s} {n:>7} {m:>+9.4f} {t:>+7.1f}  {v}")
