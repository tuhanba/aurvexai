#!/usr/bin/env python3
"""
edge_search_master.py — AurvexAI disciplined edge-search harness.

ONE place to prove or kill an edge. Takes strategy families x universes x
timeframes x cost/exec configs, runs the full battery, and emits a ranked
leaderboard with GO/NO-GO verdicts. Research-only: it never touches the live
route, never sizes real money, never enables anything.

Battery (per candidate cell):
  * gross vs NET Exp-R           (net = after taker fee + slippage + funding drag)
  * Profit Factor (PF)           sum(win R) / |sum(loss R)|
  * per-trade Sharpe
  * DSR                          Deflated Sharpe Ratio — Bailey & Lopez de Prado,
                                 deflated by the NUMBER OF TRIALS in this run
                                 (multiple-testing correction). Prob in [0,1].
  * MaxDD (R)                    on the portfolio R-equity curve, entry-ordered
  * trades, trades/day, R/day    the "serial / frequent" axis
  * split-half holdout           H1 (in-sample) vs H2 (out-of-sample) Exp-R + t
  * out-of-symbol holdout        train coins != test coins, both folds
  * concentration                best/worst coin, max single-coin share of R

Verdict per cell (honest acceptance bar):
  ACCEPTED_FOR_PAPER : netExpR>0 & PF>1.1 & DSR>0.90 & H2>0 & both OOS folds>0
                       & maxcoin share < 0.45 & n>=150
  RESEARCH_ONLY      : net positive but fails >=1 robustness cut
  NO_GO              : netExpR<=0 or PF<=1.1
  NEEDS_MORE_DATA    : n < 60

Usage:  python scripts/edge_search_master.py            # full run, text report
        python scripts/edge_search_master.py --json out.json
"""
import argparse, csv, glob, json, math, os, statistics, sys, itertools
from datetime import datetime, timezone

CACHE = "data/cache"

# ---- cost model (Binance USDT-M, VIP0 taker) -------------------------------
TAKER_FEE = 0.0005          # 5 bp per side
SLIP      = 0.0002          # 2 bp per side assumed
FUNDING_8H = 0.0001         # 1 bp / 8h holding drag (paid on the notional)
RT_COST = 2 * (TAKER_FEE + SLIP)     # round-trip taker cost, 14 bp

# ---------------------------------------------------------------------------
def bars(coin, tf):
    out = []
    p = f"{CACHE}/{coin}_USDT_USDT_{tf}.csv"
    try:
        f = open(p)
    except FileNotFoundError:
        return out
    for r in csv.reader(f):
        try:
            out.append((int(float(r[0])), float(r[1]), float(r[2]),
                        float(r[3]), float(r[4]), float(r[5])))
        except (ValueError, IndexError):
            pass
    return out

def tf_minutes(tf):
    return {"5m":5,"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"1d":1440}[tf]

def atr(b, i, n=14):
    if i < n + 1:
        return None
    s = 0.0
    for k in range(i - n, i):
        s += max(b[k][2]-b[k][3], abs(b[k][2]-b[k-1][4]), abs(b[k][3]-b[k-1][4]))
    return s / n

# ---- normal CDF / inverse (for DSR) ----------------------------------------
def _Phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _Phi_inv(p):
    # Acklam's rational approximation
    if p <= 0.0: return -1e9
    if p >= 1.0: return 1e9
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2*math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1-pl:
        q = p-0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2*math.log(1-p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)

def _moments(x):
    n = len(x)
    m = sum(x)/n
    var = sum((v-m)**2 for v in x)/n
    sd = math.sqrt(var) or 1e-12
    skew = sum(((v-m)/sd)**3 for v in x)/n
    kurt = sum(((v-m)/sd)**4 for v in x)/n
    return m, sd, skew, kurt

def psr(sr, n, skew, kurt, sr_star):
    """Probabilistic Sharpe Ratio vs benchmark sr_star (per-trade units)."""
    denom = math.sqrt(max(1e-9, 1 - skew*sr + (kurt-1)/4.0*sr*sr))
    return _Phi((sr - sr_star) * math.sqrt(max(1, n-1)) / denom)

def dsr(sr, n, skew, kurt, sr_trials):
    """Deflated Sharpe: benchmark = expected max SR across the K trials run."""
    K = max(2, len(sr_trials))
    var_sr = statistics.pvariance(sr_trials) if len(sr_trials) > 1 else 0.0
    gamma = 0.5772156649
    e = math.e
    sr0 = math.sqrt(var_sr) * ((1-gamma)*_Phi_inv(1 - 1.0/K) +
                               gamma*_Phi_inv(1 - 1.0/(K*e)))
    return psr(sr, n, skew, kurt, sr0), sr0

# ---------------------------------------------------------------------------
# Strategy families. Each returns a list of trade dicts:
#   {coin, entry_ts, exit_ts, gross_r, hold_bars, side}
# gross_r is R-normalised (per-trade stop budget), BEFORE cost. Net applied later.
# ---------------------------------------------------------------------------
def strat_donchian(b, coin, tf, N=48, X=20, atr_mult=2.0):
    trades = []; n = len(b); cl = [x[4] for x in b]
    i = max(N, 100) + 2
    while i < n - 2:
        a = atr(b, i)
        if a is None or a <= 0: i += 1; continue
        hh = max(x[2] for x in b[i-N:i]); ll = min(x[3] for x in b[i-N:i])
        sma = sum(cl[i-100:i]) / 100
        side = 0
        if cl[i] > hh and cl[i] > sma: side = +1
        elif cl[i] < ll and cl[i] < sma: side = -1
        if not side: i += 1; continue
        entry = b[i+1][1]; stop = entry - side*atr_mult*a; sd = atr_mult*a/entry
        if sd <= 0: i += 1; continue
        ret = None; j = i+1
        while j < n-1 and j < i+1+400:
            if side > 0 and b[j][3] <= stop: ret = stop/entry-1; break
            if side < 0 and b[j][2] >= stop: ret = -(stop/entry-1); break
            rhh = max(x[2] for x in b[j-X:j]); rll = min(x[3] for x in b[j-X:j])
            if side > 0 and b[j][4] < rll: ret = side*(b[j][4]/entry-1); break
            if side < 0 and b[j][4] > rhh: ret = side*(b[j][4]/entry-1); break
            j += 1
        if ret is None: ret = side*(b[min(j,n-1)][4]/entry-1)
        trades.append({"coin": coin, "entry_ts": b[i+1][0], "exit_ts": b[min(j,n-1)][0],
                       "gross_r": ret/sd, "hold": j-i, "side": side, "sd": sd})
        i = j + 1
    return trades

def strat_squeeze(b, coin, tf, W=24, pctile=20.0, stop_mult=1.0, time_stop=48):
    """W-bar range-percentile squeeze -> breakout, 1x range stop, time-stop exit."""
    trades = []; n = len(b); cl = [x[4] for x in b]
    i = W + 2
    while i < n - 2:
        window = b[i-W:i]
        rng = [x[2]-x[3] for x in window]
        cur = b[i][2]-b[i][3]
        srt = sorted(rng)
        thresh = srt[int(len(srt)*pctile/100.0)]
        if cur > thresh:  # not compressed
            i += 1; continue
        hh = max(x[2] for x in window); ll = min(x[3] for x in window)
        side = 0
        if cl[i] > hh: side = +1
        elif cl[i] < ll: side = -1
        if not side: i += 1; continue
        entry = b[i+1][1]; band = hh-ll; stop = entry - side*stop_mult*band
        sd = stop_mult*band/entry
        if sd <= 0: i += 1; continue
        ret = None; j = i+1
        while j < n-1 and j < i+1+time_stop:
            if side > 0 and b[j][3] <= stop: ret = stop/entry-1; break
            if side < 0 and b[j][2] >= stop: ret = -(stop/entry-1); break
            j += 1
        if ret is None: ret = side*(b[min(j,n-1)][4]/entry-1)
        trades.append({"coin": coin, "entry_ts": b[i+1][0], "exit_ts": b[min(j,n-1)][0],
                       "gross_r": ret/sd, "hold": j-i, "side": side, "sd": sd})
        i = j + 1
    return trades

def strat_volexp_donchian(b, coin, tf, N=48, X=20, atr_mult=2.0, volk=2.0):
    """Frequency probe: donchian breakout gated by a volume-expansion filter."""
    base = strat_donchian(b, coin, tf, N, X, atr_mult)
    # approximate: only keep breakouts whose entry bar had >volk x median vol
    keep = []
    vols = [x[5] for x in b]
    ts_to_idx = {b[i][0]: i for i in range(len(b))}
    for t in base:
        idx = ts_to_idx.get(t["entry_ts"])
        if idx is None or idx < 51: keep.append(t); continue
        med = sorted(vols[idx-50:idx])[25]
        if b[idx][5] >= volk*med:
            keep.append(t)
    return keep

# ---- net application + funding drag ---------------------------------------
def net_r(t):
    """Apply round-trip taker cost + funding drag (per hold), in R units.
    Uses the trade's own timeframe (t['tf']) so mixed-TF portfolios cost right."""
    sd = t["sd"] if t["sd"] > 0 else 1e-9
    hold_hours = t["hold"] * tf_minutes(t["tf"]) / 60.0
    funding = FUNDING_8H * (hold_hours / 8.0)          # notional drag
    cost = RT_COST + funding
    return t["gross_r"] - cost / sd

# ---- metric battery --------------------------------------------------------
def _half(ts_list, mid):
    return

def evaluate(trades, sr_trials=None, min_n=60):
    """Full battery over a flat list of trades (each carrying its own 'tf').
    sr_trials = SRs across all cells in the run (for DSR deflation)."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    net = [net_r(t) for t in trades]
    gross = [t["gross_r"] for t in trades]
    n = len(net)
    m, sd, skew, kurt = _moments(net)
    sr = m / sd
    wins = [r for r in net if r > 0]; losses = [r for r in net if r < 0]
    pf = (sum(wins) / abs(sum(losses))) if losses else float('inf')
    # span / frequency
    t0, t1 = trades[0]["entry_ts"], trades[-1]["entry_ts"]
    days = max(1e-9, (t1 - t0) / 1000 / 86400)
    tpd = n / days
    rpd = sum(net) / days
    # MaxDD on entry-ordered R equity
    eq = 0.0; peak = 0.0; maxdd = 0.0
    for r in net:
        eq += r; peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
    # split-half
    mid = t0 + (t1 - t0) // 2
    h1 = [net[k] for k in range(n) if trades[k]["entry_ts"] < mid]
    h2 = [net[k] for k in range(n) if trades[k]["entry_ts"] >= mid]
    def _stat(x):
        if len(x) < 10: return (0.0, 0.0, len(x))
        mm = statistics.mean(x); ss = statistics.pstdev(x) or 1e-9
        return (mm, mm/ss*math.sqrt(len(x)), len(x))
    h1s, h2s = _stat(h1), _stat(h2)
    # out-of-symbol
    by_coin = {}
    for k, t in enumerate(trades):
        by_coin.setdefault(t["coin"], []).append(net[k])
    coins = sorted(by_coin)
    train = [c for idx, c in enumerate(coins) if idx % 2 == 0]
    test = [c for idx, c in enumerate(coins) if idx % 2 == 1]
    oos_tr = _stat([r for c in train for r in by_coin[c]])
    oos_te = _stat([r for c in test for r in by_coin[c]])
    # concentration
    coin_R = {c: sum(v) for c, v in by_coin.items()}
    total_R = sum(net)
    best = max(coin_R.items(), key=lambda kv: kv[1])
    worst = min(coin_R.items(), key=lambda kv: kv[1])
    pos_R = sum(v for v in coin_R.values() if v > 0) or 1e-9
    maxshare = max((v/pos_R for v in coin_R.values() if v > 0), default=0.0)
    # DSR
    trials = sr_trials if sr_trials else [sr]
    dsr_p, sr0 = dsr(sr, n, skew, kurt, trials)
    return {
        "n": n, "gross_expR": statistics.mean(gross), "net_expR": m,
        "pf": pf, "win_pct": 100.0*len(wins)/n, "sharpe": sr, "dsr": dsr_p,
        "maxdd_R": maxdd, "trades_per_day": tpd, "R_per_day": rpd,
        "cost_drag_R": statistics.mean(gross) - m,
        "h1_expR": h1s[0], "h1_t": h1s[1], "h2_expR": h2s[0], "h2_t": h2s[1],
        "oos_train_expR": oos_tr[0], "oos_test_expR": oos_te[0],
        "n_coins": len(coins), "best_coin": best, "worst_coin": worst,
        "max_coin_share": maxshare,
    }

def verdict(m, min_n=150):
    if m is None or m["n"] < 60:
        return "NEEDS_MORE_DATA"
    if m["net_expR"] <= 0 or m["pf"] <= 1.1:
        return "NO_GO"
    robust = (m["dsr"] > 0.90 and m["h2_expR"] > 0 and
              m["oos_train_expR"] > 0 and m["oos_test_expR"] > 0 and
              m["max_coin_share"] < 0.45 and m["n"] >= min_n)
    return "ACCEPTED_FOR_PAPER" if robust else "RESEARCH_ONLY"

# ---------------------------------------------------------------------------
# Universe presets (strategy-specific; validated in prior waves).
MOM28 = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","TON","TRX",
         "DOT","NEAR","ARB","SUI","ICP","ATOM","ENA","FET","GALA","GRT","JUP",
         "SEI","STX","UNI","WIF","WLD","XLM"]
CORE12 = ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","AVAX","LINK","TON","TRX","DOT"]

# candidate cells: (name, family_fn, tf, universe, kwargs)
def build_cells():
    cells = []
    # donchian family — the known strongest edge, several speeds
    cells.append(("donchian 4h N20/X20", strat_donchian, "4h", CORE12, dict(N=20,X=20,atr_mult=2.0)))
    cells.append(("donchian 1h N48/X20", strat_donchian, "1h", MOM28, dict(N=48,X=20,atr_mult=2.0)))
    cells.append(("donchian 1h N30/X20", strat_donchian, "1h", MOM28, dict(N=30,X=20,atr_mult=2.0)))
    cells.append(("donchian 30m N48/X20", strat_donchian, "30m", CORE12, dict(N=48,X=20,atr_mult=2.0)))
    cells.append(("donchian 2h N20/X10", strat_donchian, "2h", CORE12, dict(N=20,X=10,atr_mult=2.0)))
    # squeeze family
    cells.append(("squeeze 1h W24 p20", strat_squeeze, "1h", MOM28, dict(W=24,pctile=20.0,stop_mult=1.0,time_stop=48)))
    cells.append(("squeeze 30m W24 p20", strat_squeeze, "30m", CORE12, dict(W=24,pctile=20.0,stop_mult=1.0,time_stop=48)))
    cells.append(("squeeze 15m W24 p20", strat_squeeze, "15m", CORE12, dict(W=24,pctile=20.0,stop_mult=1.0,time_stop=48)))
    # volume-expansion donchian — the harness-discovered quality filter, swept
    cells.append(("volexp1.5-donch 1h", strat_volexp_donchian, "1h", MOM28, dict(N=48,X=20,atr_mult=2.0,volk=1.5)))
    cells.append(("volexp2.0-donch 1h", strat_volexp_donchian, "1h", MOM28, dict(N=48,X=20,atr_mult=2.0,volk=2.0)))
    cells.append(("volexp2.5-donch 1h", strat_volexp_donchian, "1h", MOM28, dict(N=48,X=20,atr_mult=2.0,volk=2.5)))
    cells.append(("volexp3.0-donch 1h", strat_volexp_donchian, "1h", MOM28, dict(N=48,X=20,atr_mult=2.0,volk=3.0)))
    cells.append(("volexp2.0-donch 4h", strat_volexp_donchian, "4h", CORE12, dict(N=20,X=20,atr_mult=2.0,volk=2.0)))
    return cells

# named portfolios: merge the trade streams of >=2 cells onto one timeline.
PORTFOLIOS = {
    "PF: donchian1h + squeeze1h": ["donchian 1h N48/X20", "squeeze 1h W24 p20"],
    "PF: volexp1h + squeeze1h":   ["volexp2.0-donch 1h", "squeeze 1h W24 p20"],
}

def run(cells):
    # pass 1: gather per-cell trades (each tagged with its tf) + SR for DSR
    per_cell = []
    trades_by_name = {}
    for (name, fn, tf, uni, kw) in cells:
        trades = []
        for c in uni:
            b = bars(c, tf)
            if len(b) < 400: continue
            for t in fn(b, c, tf, **kw):
                t["tf"] = tf
                trades.append(t)
        trades_by_name[name] = trades
        sr = (lambda net: (_moments(net)[0]/_moments(net)[1]) if net else 0.0)(
            [net_r(t) for t in trades])
        per_cell.append((name, tf, trades, sr))
    # portfolios: merge trade streams
    portfolios = []
    for pname, members in PORTFOLIOS.items():
        merged = []
        for mnm in members:
            merged += trades_by_name.get(mnm, [])
        if merged:
            sr = (lambda net: _moments(net)[0]/_moments(net)[1])([net_r(t) for t in merged])
            portfolios.append((pname, "mix", merged, sr))
    all_cells = per_cell + portfolios
    sr_trials = [sr for (_, _, tr, sr) in all_cells if tr]
    # pass 2: full battery with DSR deflation across all trials
    results = []
    for (name, tf, trades, _sr) in all_cells:
        m = evaluate(trades, sr_trials=sr_trials)
        results.append((name, tf, m, verdict(m)))
    return results

def fmt(results):
    order = {"ACCEPTED_FOR_PAPER":0, "RESEARCH_ONLY":1, "NEEDS_MORE_DATA":2, "NO_GO":3}
    def score(r):
        _, _, m, v = r
        rpd = m["R_per_day"] if m else -9
        return (order.get(v,9), -(rpd))
    results = sorted(results, key=score)
    print("="*118)
    print("AURVEXAI EDGE-SEARCH MASTER — ranked leaderboard (net of fee+slip+funding)")
    print("="*118)
    hdr = (f"{'candidate':<22}{'tf':>4} {'verdict':<18} {'netExpR':>8} {'PF':>5} "
           f"{'DSR':>5} {'t/day':>6} {'R/day':>6} {'maxDD':>6} {'H2R':>7} {'OOSte':>7} {'maxcoin':>7} {'n':>6}")
    print(hdr); print("-"*118)
    for (name, tf, m, v) in results:
        if m is None:
            print(f"{name:<22}{tf:>4} {v:<18}  (no trades)"); continue
        print(f"{name:<22}{tf:>4} {v:<18} {m['net_expR']:>+8.4f} {m['pf']:>5.2f} "
              f"{m['dsr']:>5.2f} {m['trades_per_day']:>6.2f} {m['R_per_day']:>+6.3f} "
              f"{m['maxdd_R']:>6.1f} {m['h2_expR']:>+7.4f} {m['oos_test_expR']:>+7.4f} "
              f"{m['max_coin_share']:>6.2f} {m['n']:>6}")
    print("-"*118)
    acc = [r for r in results if r[3] == "ACCEPTED_FOR_PAPER"]
    print(f"ACCEPTED_FOR_PAPER: {[r[0] for r in acc] or 'none'}")
    print("verdict bar: netExpR>0 & PF>1.1 & DSR>0.90 & H2>0 & both OOS folds>0 "
          "& maxcoin<0.45 & n>=150")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    if not os.path.isdir(CACHE):
        print(f"no {CACHE}/ — run from repo root with data cache present"); sys.exit(1)
    results = run(build_cells())
    fmt(results)
    if args.json:
        payload = {"generated": datetime.now(timezone.utc).isoformat(),
                   "cost_model": {"taker_fee": TAKER_FEE, "slip": SLIP,
                                  "funding_8h": FUNDING_8H, "rt_cost": RT_COST},
                   "results": [{"name": n, "tf": tf, "verdict": v, "metrics": m}
                               for (n, tf, m, v) in results]}
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"\nwrote {args.json}")

if __name__ == "__main__":
    main()
