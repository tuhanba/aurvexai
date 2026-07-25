"""Phase 4 — correlation controller (cluster map, same-side down-weight, caps)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.correlation import CorrelationController
from aurvex.models import LONG, SHORT, Candle


def _series(n, step, ts0=0, tf=14_400_000):
    bars, p = [], 100.0
    for i in range(n):
        p *= (1 + step / 100.0)
        bars.append(Candle(ts=ts0 + i * tf, open=p, high=p * 1.001,
                           low=p * 0.999, close=p, volume=1.0))
    return bars


class _T:
    def __init__(self, symbol, side, notional, frac=1.0):
        self.symbol = symbol
        self.side = side
        self.position_size = notional
        self.remaining_fraction = frac


def _cc():
    return CorrelationController(Config())


def test_correlated_symbols_cluster_together():
    uni = {s: _series(60, 0.3) for s in ("BTC/USDT:USDT", "ETH/USDT:USDT",
                                         "SOL/USDT:USDT")}
    v = _cc().build(uni, window=30)
    assert v.data_ok
    clusters = {v.cluster(s) for s in uni}
    assert len(clusters) == 1     # all move identically → one cluster


def test_uncorrelated_symbols_separate_clusters():
    # Opposite-direction sawtooths → low/negative correlation.
    a = {"A/USDT:USDT": [], "B/USDT:USDT": []}
    pa = pb = 100.0
    for i in range(60):
        pa *= 1.01 if i % 2 == 0 else 0.99
        pb *= 0.99 if i % 2 == 0 else 1.01
        a["A/USDT:USDT"].append(Candle(i, pa, pa, pa, pa, 1))
        a["B/USDT:USDT"].append(Candle(i, pb, pb, pb, pb, 1))
    v = _cc().build(a, window=30)
    assert v.data_ok
    assert v.cluster("A/USDT:USDT") != v.cluster("B/USDT:USDT")


def test_thin_data_fail_safe():
    v = _cc().build({"A/USDT:USDT": _series(5, 0.1)}, window=30)
    assert not v.data_ok


def test_m_correlation_downweights_same_side_cluster():
    cc = _cc()
    uni = {s: _series(60, 0.3) for s in ("BTC/USDT:USDT", "ETH/USDT:USDT",
                                         "SOL/USDT:USDT")}
    v = cc.build(uni, window=30)
    opens = [_T("BTC/USDT:USDT", LONG, 100.0), _T("ETH/USDT:USDT", LONG, 100.0)]
    # A 3rd correlated long → heavy same-side load → down-weight < 1.
    m_long = cc.m_correlation(v, "SOL/USDT:USDT", LONG, opens)
    assert m_long < 1.0
    # A short in the same cluster is not same-side → no down-weight.
    m_short = cc.m_correlation(v, "SOL/USDT:USDT", SHORT, opens)
    assert m_short == 1.0


def test_m_correlation_fail_safe_cautious():
    from aurvex.correlation import CorrelationView
    m = _cc().m_correlation(CorrelationView(data_ok=False), "BTC/USDT:USDT",
                            LONG, [])
    assert m == 0.85          # cautious, never >1 when uncomputable


def test_net_directional_cap():
    cfg = Config()
    cfg.max_net_directional_pct = 100.0     # cap |long-short| at 100% of equity
    cc = CorrelationController(cfg)
    opens = [_T("BTC/USDT:USDT", LONG, 80.0)]
    # equity 100 → cap 100. Adding a 30 long → net 110 > 100 → reject.
    assert not cc.net_directional_ok(opens, LONG, 30.0, equity=100.0)
    # Adding a 30 short → net |80-30|=50 <= 100 → ok.
    assert cc.net_directional_ok(opens, SHORT, 30.0, equity=100.0)


def test_net_directional_disabled_by_default():
    cc = _cc()   # max_net_directional_pct default 0
    assert cc.net_directional_ok([_T("BTC/USDT:USDT", LONG, 1e9)], LONG, 1e9, 1.0)
