"""Tactic research on XAUUSD M3: baseline cross vs alternative entry/exit tactics.
In-sample: < 2026-07-01, out-of-sample: >= 2026-07-01. Results in R after costs."""
import sys, datetime as dt
import numpy as np
sys.path.insert(0, __import__('os').path.dirname(__file__))
from sim import Data, run_trade, summarize

D = Data()
b = D.b3
n = len(b)
SPLIT = dt.datetime(2026, 2, 15, tzinfo=dt.timezone.utc).timestamp()
print('M3 bars', n, 'from', dt.datetime.utcfromtimestamp(b[0, 0]), 'to', dt.datetime.utcfromtimestamp(b[-1, 0]))


def sign(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)


def cross_dir(i):
    """confirmed cross between closed bars i-2 and i-1 (entry at open of i), same VWAP day"""
    if D.nin[i - 1] < 4:
        return 0
    s2 = sign(D.ema9[i - 2] - D.vw[i - 2]); s1 = sign(D.ema9[i - 1] - D.vw[i - 1])
    return s1 if (s2 and s1 and s1 != s2) else 0


def swing_sl(i, side, look=10, buf=0.2):
    lo = b[i - look:i, 3].min(); hi = b[i - look:i, 2].max()
    return lo - buf if side > 0 else hi + buf


# ---------------------------------------------------------------- diagnostics
def drift_after_cross():
    print('\n== Forward drift after a confirmed cross (in ATR, positive = in signal direction) ==')
    for aligned in (None, True, False):
        out = {}
        for N in (5, 10, 20, 40):
            vals = []
            for i in range(60, n - N - 1):
                d = cross_dir(i)
                if not d or not D.ny_ok(i):
                    continue
                if aligned is not None and ((D.trend[i] == d) != aligned):
                    continue
                vals.append((b[i + N, 4] - b[i, 1]) * d / D.atr[i - 1])
            out[N] = (len(vals), np.mean(vals) if vals else 0.0)
        tag = 'all' if aligned is None else ('with H1 trend' if aligned else 'against/flat H1')
        print(f'  {tag:18s}', '  '.join(f'N={k}: {v[1]:+.3f} (n={v[0]})' for k, v in out.items()))


# ---------------------------------------------------------------- strategies
def simulate(entry_fn, exit_kw, name, one_at_a_time=True, cooldown_loss=10):
    trades = []
    i = 60
    busy_until = -1
    cool = {1: -1, -1: -1}
    while i < n - 2:
        if i <= busy_until or not D.ny_ok(i):
            i += 1
            continue
        sig = entry_fn(i)
        if sig is None:
            i += 1
            continue
        side, sl, tp_r = sig
        if i < cool[side]:
            i += 1
            continue
        entry = b[i, 1]
        risk = abs(entry - sl)
        a = D.atr[i - 1]
        if risk <= 0.2 * a or risk > 3.0 * a:
            i += 1
            continue
        tp = entry + side * tp_r * risk if tp_r else None
        R, j, why = run_trade(D, i, side, entry, sl, tp, **exit_kw)
        trades.append((b[i, 0], R, why))
        if R < 0 and cooldown_loss:
            cool[side] = j + cooldown_loss
        busy_until = j if one_at_a_time else i
        i += 1
    summarize(name, trades, SPLIT)
    return trades


def base_entry(tp_r=1.5, trend=True, chase=1.0, fade=False):
    def f(i):
        d = cross_dir(i)
        if not d:
            return None
        if fade:
            d = -d
        if trend and D.trend[i] != d:
            return None
        if chase and abs(b[i, 1] - D.vw[i - 1]) > chase * D.atr[i - 1]:
            return None
        a = D.atr[i - 1]
        sw = swing_sl(i, d)
        dist = max(1.5 * a, abs(b[i, 1] - sw))
        return d, b[i, 1] - d * dist, tp_r
    return f


def pullback_entry(level='ema', tp_r=2.0, min_side=5, zone=0.3, stop_look=5):
    """Trend leg = EMA on one side of VWAP for >= min_side bars AND H1 trend agrees.
    Entry when the last closed bar dipped into the EMA (or VWAP) zone and closed back in trend
    direction. Stop beyond the pullback extreme (tight), target tp_r R."""
    def f(i):
        a = D.atr[i - 1]
        side = sign(D.ema9[i - 1] - D.vw[i - 1])
        if side == 0 or D.trend[i] != side:
            return None
        for k in range(1, min_side + 1):
            if sign(D.ema9[i - k] - D.vw[i - k]) != side:
                return None
        ref = D.ema9[i - 1] if level == 'ema' else D.vw[i - 1]
        o, h, l, c = b[i - 1, 1:5]
        if side > 0:
            ok = l <= ref + zone * a and c > D.ema9[i - 1] and c > o
            sl = b[i - stop_look:i, 3].min() - 0.2
        else:
            ok = h >= ref - zone * a and c < D.ema9[i - 1] and c < o
            sl = b[i - stop_look:i, 2].max() + 0.2
        if not ok:
            return None
        return side, sl, tp_r
    return f


def band_reversion(k=2.0, tp_to_vwap=True):
    """Fade an extension beyond VWAP +/- k sigma once a bar closes back inside the band."""
    def f(i):
        sd = D.sd[i - 1]
        if sd <= 0 or D.nin[i - 1] < 20:
            return None
        up = D.vw[i - 2] + k * D.sd[i - 2]; dn = D.vw[i - 2] - k * D.sd[i - 2]
        c2 = b[i - 2, 4]; c1 = b[i - 1, 4]
        if c2 > up and c1 < D.vw[i - 1] + k * sd:
            side = -1; sl = max(b[i - 3:i, 2]) + 0.2
        elif c2 < dn and c1 > D.vw[i - 1] - k * sd:
            side = 1; sl = min(b[i - 3:i, 3]) - 0.2
        else:
            return None
        risk = abs(b[i, 1] - sl)
        dist_vw = abs(D.vw[i - 1] - b[i, 1])
        tp_r = dist_vw / risk if tp_to_vwap and risk > 0 else 1.5
        if tp_r < 0.8:
            return None
        return side, sl, tp_r
    return f


if __name__ == '__main__':
    drift_after_cross()
    print('\n== Strategies (R after costs; IS = Jan-Jun, OOS = Jul-Oct) ==')
    EMA_AFTER = dict(ema_exit=0.5)
    simulate(base_entry(), EMA_AFTER, 'S0 baseline cross+trend, TP1.5, EMA exit>0.5R')
    simulate(base_entry(), {}, 'S0b baseline, pure SL/TP 1.5R')
    simulate(base_entry(tp_r=None), dict(trail_atr=1.5, be_r=1.0), 'S0c baseline, no TP, BE1R + ATR trail')
    simulate(base_entry(trend=False), EMA_AFTER, 'S0d cross, NO trend filter')
    simulate(base_entry(fade=True, trend=False), {}, 'S1 FADE the cross, TP1.5')
    for lvl in ('ema', 'vwap'):
        for tp in (1.5, 2.0, 3.0):
            simulate(pullback_entry(level=lvl, tp_r=tp), {}, f'S2 trend pullback to {lvl}, TP{tp}')
        simulate(pullback_entry(level=lvl, tp_r=None), dict(trail_atr=1.5, be_r=1.0), f'S2 trend pullback to {lvl}, BE+trail')
    for k in (1.5, 2.0, 2.5):
        simulate(band_reversion(k), {}, f'S3 VWAP band reversion k={k}, TP=VWAP')
