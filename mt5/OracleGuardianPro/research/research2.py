"""Hypothesis from the drift test: with the H1 trend, price dips in the first ~10 bars after a cross,
then continues (+0.86 ATR after 40 bars). Tactic: cross with trend -> wait for the dip -> hold ~2h."""
import sys, os, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
from sim import Data, run_trade, summarize
import research as R
D = R.D; b = D.b3; n = len(b)
SPLIT = R.SPLIT

def delayed_entry(delay_max=15, dip_atr=0.3, sl_atr=2.0):
    """after a trend-aligned cross at bar c, enter on the first bar (within delay_max) whose low/high
    retraced >= dip_atr*ATR against the signal from the cross-bar open; stop = sl_atr*ATR from entry"""
    pend = {}
    def f(i):
        d = R.cross_dir(i)
        if d and D.trend[i] == d:
            pend['c'] = (i, d, b[i, 1])
        if 'c' not in pend:
            return None
        c, side, ref = pend['c']
        if i - c > delay_max or D.trend[i] != side:
            pend.pop('c'); return None
        if i == c:
            return None
        a = D.atr[i - 1]
        dipped = (ref - b[i - 1, 3] >= dip_atr * a) if side > 0 else (b[i - 1, 2] - ref >= dip_atr * a)
        resumed = (b[i - 1, 4] > b[i - 1, 1]) if side > 0 else (b[i - 1, 4] < b[i - 1, 1])
        if dipped and resumed:
            pend.pop('c')
            return side, b[i, 1] - side * sl_atr * a, None
        return None
    return f

def cross_hold(sl_atr=2.0):
    def f(i):
        d = R.cross_dir(i)
        if not d or D.trend[i] != d:
            return None
        return d, b[i, 1] - d * sl_atr * D.atr[i - 1], None
    return f

for hold in (20, 40, 60):
    for sl in (1.5, 2.0, 3.0):
        R.simulate(cross_hold(sl), dict(max_bars=hold), f'S5 cross+trend, SL{sl}ATR, time exit {hold} bars')
for hold in (40, 60):
    for dip in (0.3, 0.6):
        for sl in (1.5, 2.0):
            R.simulate(delayed_entry(15, dip, sl), dict(max_bars=hold), f'S4 cross+trend, dip{dip}, SL{sl}, hold{hold}')
            R.simulate(delayed_entry(15, dip, sl), dict(max_bars=hold, be_r=1.0, trail_atr=2.0), f'S4 ... dip{dip}, SL{sl}, hold{hold}, BE+trail2')
