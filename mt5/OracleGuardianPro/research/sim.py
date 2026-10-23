"""Research simulator for the Oracle Guardian Pro gold tactics (approximation of the EA).

Data: Dukascopy XAUUSD BID M1 candles (UTC). Results are in R (risk units), so they do
not depend on lot sizing. Costs: fixed round-trip spread+commission in price units.
Intrabar: SL/TP resolved on M1 bars; if both inside one M1 bar, SL is assumed first.
"""
import glob, lzma, struct, os, sys, math, datetime as dt
import numpy as np

RAW = os.path.join(os.path.dirname(__file__), '..', 'duka', 'raw')
SCALE = 1000.0          # XAUUSD price scale in Dukascopy files
COST = 0.35             # round-trip cost in price units (spread ~0.28 + commission)


def load_m1():
    rows = []
    for f in sorted(glob.glob(os.path.join(RAW, '*.bi5'))):
        b = open(f, 'rb').read()
        if not b:
            continue
        try:
            d = lzma.decompress(b, format=lzma.FORMAT_ALONE)
        except Exception:
            continue
        day = dt.datetime.strptime(os.path.basename(f)[:10], '%Y-%m-%d').replace(tzinfo=dt.timezone.utc)
        t0 = int(day.timestamp())
        n = len(d) // 24
        for i in range(n):
            s, o, c, l, h, v = struct.unpack('>5if', d[i * 24:(i + 1) * 24])
            if v <= 0 and o == c == l == h:
                continue
            rows.append((t0 + s, o / SCALE, h / SCALE, l / SCALE, c / SCALE, v))
    a = np.array(rows, dtype=float)
    a = a[np.argsort(a[:, 0])]
    return a  # t,o,h,l,c,v


def resample(m1, sec):
    t = m1[:, 0]
    k = (t // sec).astype(np.int64)
    idx = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    ends = np.r_[idx[1:], len(t)]
    o = m1[idx, 1]
    c = m1[ends - 1, 4]
    h = np.maximum.reduceat(m1[:, 2], idx)
    l = np.minimum.reduceat(m1[:, 3], idx)
    v = np.add.reduceat(m1[:, 5], idx)
    return np.c_[k[idx] * sec, o, h, l, c, v], idx, ends


def ema(x, n):
    out = np.empty_like(x)
    a = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr_sma(b, n=14):
    h, l, c = b[:, 2], b[:, 3], b[:, 4]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.convolve(tr, np.ones(n) / n, 'full')[:len(tr)]
    out[:n] = tr[:n].mean()
    return out


def us_dst(ts):
    d = dt.datetime.utcfromtimestamp(ts)
    y = d.year
    def nth_sun(m, n):
        x = dt.datetime(y, m, 1)
        add = (6 - x.weekday()) % 7
        return x + dt.timedelta(days=add + 7 * (n - 1))
    s = nth_sun(3, 2) + dt.timedelta(hours=7)
    e = nth_sun(11, 1) + dt.timedelta(hours=6)
    return s <= d < e


def ny_offset(ts):
    return -4 * 3600 if us_dst(ts) else -5 * 3600


def vwap_anchor_ids(t3, reset_min=18 * 60):
    """id of the VWAP 'trading day' for each M3 bar: resets at 18:00 New York."""
    ids = np.empty(len(t3), dtype=np.int64)
    for i, ts in enumerate(t3):
        loc = ts + ny_offset(ts)
        ids[i] = (loc - reset_min * 60) // 86400
    return ids


def session_vwap(b, ids):
    tp = (b[:, 1] + b[:, 2] + b[:, 3] + b[:, 4]) / 4.0
    v = np.maximum(b[:, 5], 1e-9)
    pv = tp * v
    vw = np.empty(len(b))
    sd = np.empty(len(b))
    n_in = np.empty(len(b), dtype=np.int64)
    cpv = cv = cpv2 = 0.0
    cnt = 0
    for i in range(len(b)):
        if i == 0 or ids[i] != ids[i - 1]:
            cpv = cv = cpv2 = 0.0
            cnt = 0
        cpv += pv[i]; cv += v[i]; cpv2 += tp[i] * tp[i] * v[i]; cnt += 1
        vw[i] = cpv / cv
        var = cpv2 / cv - vw[i] ** 2
        sd[i] = math.sqrt(var) if var > 0 else 0.0
        n_in[i] = cnt
    return vw, sd, n_in


class Data:
    def __init__(self):
        m1 = load_m1()
        self.m1 = m1
        b3, idx3, ends3 = resample(m1, 180)
        self.b3, self.m1_start, self.m1_end = b3, idx3, ends3
        self.t3 = b3[:, 0]
        self.ema9 = ema(b3[:, 4], 9)
        self.atr = atr_sma(b3, 14)
        ids = vwap_anchor_ids(self.t3)
        self.vw, self.sd, self.nin = session_vwap(b3, ids)
        # H1 EMA50 trend, value of the last COMPLETED H1 bar for each M3 bar
        h1, _, _ = resample(m1, 3600)
        e50 = ema(h1[:, 4], 50)
        hk = h1[:, 0]
        pos = np.searchsorted(hk, self.t3, side='right') - 2   # last completed H1
        pos = np.clip(pos, 3, len(hk) - 1)
        up = (h1[pos, 4] > e50[pos]) & (e50[pos] > e50[pos - 3])
        dn = (h1[pos, 4] < e50[pos]) & (e50[pos] < e50[pos - 3])
        self.trend = np.where(up, 1, np.where(dn, -1, 0))
        loc = self.t3 + np.array([ny_offset(t) for t in self.t3])
        self.ny_min = ((loc % 86400) // 60).astype(int)
        self.ny_dow = ((loc // 86400 + 4) % 7).astype(int)  # 0=Sun

    def ny_ok(self, i, roll=(16 * 60 + 30, 18 * 60 + 30), fri_cut=14 * 60):
        m, d = self.ny_min[i], self.ny_dow[i]
        if d == 6 or (d == 0 and m < 18 * 60):
            return False
        if d == 5 and m >= fri_cut:
            return False
        if roll[0] <= m < roll[1]:
            return False
        return True


def run_trade(D, i_entry, side, entry, sl, tp, max_bars=None, ema_exit=None, be_r=None, trail_atr=None,
              fri_close=16 * 60 + 15):
    """Simulate from M3 bar i_entry (entry at its open) bar by bar using M1 inside.
    Returns (R, exit_bar, reason)."""
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0, i_entry, 'bad'
    cur_sl = sl
    mfe = 0.0
    b3 = D.b3
    m1 = D.m1
    n3 = len(b3)
    for j in range(i_entry, n3):
        # weekend / Friday close at bar open
        if D.ny_dow[j] == 5 and D.ny_min[j] >= fri_close and j > i_entry:
            x = b3[j, 1]
            return ((x - entry) * side - COST) / risk, j, 'friday'
        for k in range(D.m1_start[j], D.m1_end[j]):
            o, h, l = m1[k, 1], m1[k, 2], m1[k, 3]
            if side > 0:
                if l <= cur_sl:
                    return ((cur_sl - entry) - COST) / risk, j, 'sl' if cur_sl == sl else 'trail'
                if tp and h >= tp:
                    return ((tp - entry) - COST) / risk, j, 'tp'
                mfe = max(mfe, h - entry)
            else:
                if h + COST * 0.0 >= cur_sl:
                    return ((entry - cur_sl) - COST) / risk, j, 'sl' if cur_sl == sl else 'trail'
                if tp and l <= tp:
                    return ((entry - tp) - COST) / risk, j, 'tp'
                mfe = max(mfe, entry - l)
        c = b3[j, 4]
        # end of M3 bar j: management decisions take effect from bar j+1
        if be_r is not None and mfe >= be_r * risk:
            be = entry + side * 0.05
            if (side > 0 and be > cur_sl) or (side < 0 and be < cur_sl):
                cur_sl = be
        if trail_atr is not None and mfe >= risk:
            cand = c - side * trail_atr * D.atr[j]
            if (side > 0 and cand > cur_sl) or (side < 0 and cand < cur_sl):
                cur_sl = cand
        if ema_exit is not None and j > i_entry:
            armed = mfe >= ema_exit * risk
            if armed and ((side > 0 and c < D.ema9[j]) or (side < 0 and c > D.ema9[j])):
                if j + 1 < n3:
                    x = b3[j + 1, 1]
                    return ((x - entry) * side - COST) / risk, j + 1, 'ema'
        if max_bars is not None and j - i_entry + 1 >= max_bars and j + 1 < n3:
            x = b3[j + 1, 1]
            return ((x - entry) * side - COST) / risk, j + 1, 'time'
    return 0.0, n3 - 1, 'end'


def summarize(name, trades, split_ts):
    def stats(tt):
        if not tt:
            return '   n=0'
        r = np.array([x[1] for x in tt])
        wins = r[r > 0].sum(); loss = -r[r < 0].sum()
        pf = wins / loss if loss > 0 else float('inf')
        eq = np.cumsum(r); dd = (np.maximum.accumulate(eq) - eq).max()
        return f'n={len(r):4d} sumR={r.sum():7.1f} avgR={r.mean():6.3f} win%={100*(r>0).mean():5.1f} PF={pf:5.2f} maxDD_R={dd:5.1f}'
    ins = [x for x in trades if x[0] < split_ts]
    oos = [x for x in trades if x[0] >= split_ts]
    print(f'{name:44s} ALL {stats(trades)}')
    print(f'{"":44s} IS  {stats(ins)}')
    print(f'{"":44s} OOS {stats(oos)}')
