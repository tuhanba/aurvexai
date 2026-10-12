"""Tests for scripts/aurvex_edge.py — UTC bars, gap exclusion, bid/ask fills, explicit costs,
and NO LOOKAHEAD."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("aurvex_edge", ROOT / "scripts" / "aurvex_edge.py")
edge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(edge)

BAR = 60  # 60-second bars in these tests


def _bars(mids, start0=0, step=BAR, spread=0.2):
    """Build contiguous bars (bid/ask = mid -/+ spread/2, h/l = mid +/- 0.5)."""
    out = []
    for k, c in enumerate(mids):
        out.append({"start": start0 + k * step, "o": c, "h": c + 0.5, "l": c - 0.5, "c": c,
                    "bid_o": c - spread / 2, "ask_o": c + spread / 2,
                    "bid_c": c - spread / 2, "ask_c": c + spread / 2, "spread": spread, "n": 5})
    return out


def test_resample_utc_bucketing_and_drop_incomplete_last():
    # ticks over three 60s buckets; the last bucket is incomplete and must be dropped
    ticks = [(0, 99.9, 100.1), (30, 100.0, 100.2),
             (60, 100.9, 101.1), (90, 101.0, 101.2),
             (120, 102.0, 102.2)]
    bars = edge.resample_bars(ticks, 60, drop_last=True)
    assert len(bars) == 2                              # third (incomplete) bucket dropped
    assert bars[0]["start"] == 0 and bars[1]["start"] == 60
    assert abs(bars[0]["ask_o"] - 100.1) < 1e-9 and abs(bars[1]["bid_c"] - 101.0) < 1e-9


def test_contiguous_detects_gap():
    bars = _bars([100.0, 100.0, 100.0])
    bars[2]["start"] = bars[1]["start"] + 2 * BAR      # a missing bucket between 1 and 2
    assert edge.contiguous(bars, 0, 1, BAR) is True
    assert edge.contiguous(bars, 0, 2, BAR) is False


def test_entry_features_no_lookahead_and_gap_guard():
    hist = [100 + 0.1 * k for k in range(25)]
    i = 24
    a = _bars(hist + [200.0, 50.0]); b = _bars(hist + [100.0, 100.0])
    assert edge.entry_features(a, i, 20, BAR) == edge.entry_features(b, i, 20, BAR)  # future not leaked
    gap = _bars(hist); gap[10]["start"] += 5 * BAR     # gap inside the lookback window
    assert edge.entry_features(gap, 24, 20, BAR) is None


def test_forward_outcome_bidask_fill_and_costs():
    # entry fills at NEXT bar open ask; exit at horizon bar close bid; spread paid both sides
    bars = _bars([100.0] * 3 + [101.0, 102.0], spread=0.2)
    # i=2: fill at bar3 open ask=101.1; exit long at bar4 close bid=101.9 (H=2 -> j=4)
    o = edge.forward_outcome(bars, 2, 2, +1, BAR, slip_price=0.0, comm_price=None)
    assert abs(o["gross_after_spread_slip"] - (101.9 - 101.1)) < 1e-9
    assert o["full_after_cost"] is False               # commission unknown -> not full after-cost
    o2 = edge.forward_outcome(bars, 2, 2, +1, BAR, slip_price=0.05, comm_price=0.3)
    # slippage widens entry/exit; commission subtracted; now full after-cost
    assert o2["full_after_cost"] is True and o2["net"] < o["gross_after_spread_slip"]


def test_forward_outcome_excludes_gap_horizon():
    bars = _bars([100.0] * 6)
    bars[4]["start"] += 3 * BAR                         # gap within the forward horizon
    assert edge.forward_outcome(bars, 2, 3, +1, BAR) is None


def test_forward_outcome_short_mfe_mae_oriented():
    bars = _bars([100.0] * 2 + [100.0, 99.0, 98.0])     # price falls -> short profits
    sh = edge.forward_outcome(bars, 1, 3, -1, BAR, 0.0, 0.0)
    assert sh["gross_after_spread_slip"] > 0            # short gained
    assert sh["mfe"] > 0 and sh["mae"] <= 0             # favorable/adverse oriented to the short


def test_indep_count_non_overlapping():
    # entries at 0,1,2,10,11 with horizon 5 -> independent: 0, 10 => 2
    assert edge._indep_count([0, 1, 2, 10, 11], 5) == 2
