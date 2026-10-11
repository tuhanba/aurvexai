"""Tests for scripts/aurvex_edge.py — entry features / forward outcomes, enforcing NO LOOKAHEAD."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("aurvex_edge", ROOT / "scripts" / "aurvex_edge.py")
edge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edge)


def _bars(closes):
    # simple bars with h/l = c +/- 0.5, spread 0.1, 1-min buckets
    return [{"start_msc": i * 60000, "o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "spread": 0.1}
            for i, c in enumerate(closes)]


def test_resample_buckets_by_barsec():
    ticks = [(0, 100.0, 0.2), (1000, 101.0, 0.2), (60000, 102.0, 0.4), (61000, 103.0, 0.4)]
    bars = edge.resample_bars(ticks, 60)           # 60s bars
    assert len(bars) == 2
    assert bars[0]["o"] == 100.0 and bars[0]["c"] == 101.0 and bars[0]["h"] == 101.0
    assert abs(bars[0]["spread"] - 0.2) < 1e-9 and abs(bars[1]["spread"] - 0.4) < 1e-9


def test_entry_features_no_lookahead():
    # identical history up to i, DIFFERENT futures -> features at i MUST be identical
    hist = [100 + (0.1 * k) for k in range(25)]
    i = 24
    a = _bars(hist + [200.0, 50.0])                # wild future
    b = _bars(hist + [100.0, 100.0])               # calm future
    fa = edge.entry_features(a, i, 20)
    fb = edge.entry_features(b, i, 20)
    assert fa == fb and fa is not None             # future never leaked into entry features


def test_forward_outcome_depends_only_on_future_and_entry():
    base = _bars([100.0] * 10 + [100.0, 101.0, 102.0, 103.0])  # i=9, future rises
    i = 9
    o1 = edge.forward_outcome(base, i, 3, +1, cost=0.0)
    # change a PAST bar (before i) — outcome must not change (uses entry close + future only)
    changed = [dict(x) for x in base]; changed[2]["c"] = 999.0; changed[2]["h"] = 999.0
    o2 = edge.forward_outcome(changed, i, 3, +1, cost=0.0)
    assert o1 == o2 and o1 is not None


def test_forward_outcome_long_short_cost_and_excursions():
    bars = _bars([100.0] * 6 + [100.0, 101.0, 102.0])  # i=5 entry at 100; future bars 100,101,102
    i = 5
    lo = edge.forward_outcome(bars, i, 3, +1, cost=0.5)
    # gross long = 102-100 = 2; after cost 0.5 -> 1.5; MFE uses highs (102.5-100=2.5)
    assert abs(lo["gross"] - 2.0) < 1e-9 and abs(lo["ret_after_cost"] - 1.5) < 1e-9
    assert abs(lo["mfe"] - 2.5) < 1e-9
    sh = edge.forward_outcome(bars, i, 3, -1, cost=0.5)
    assert abs(sh["gross"] + 2.0) < 1e-9           # short loses as price rose
    assert sh["mae"] < 0                            # adverse excursion against the short


def test_breakout_flag():
    bars = _bars([100.0] * 20 + [100.4] * 1)        # last 20 before i are flat ~100(+/-0.5)
    # force i's close above the prior-20 high
    bars[20]["c"] = 102.0
    f = edge.entry_features(bars, 20, 20)
    assert f["breakout_up"] == 1 and f["breakout_dn"] == 0


def test_entry_features_insufficient_history_returns_none():
    assert edge.entry_features(_bars([100.0] * 5), 3, 20) is None
