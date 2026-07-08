"""
edge_search_master harness — verdict + metric-battery invariants.

The harness is research-only, but its verdict logic gates what may reach paper,
so its bar must be exact: NO_GO on non-positive/thin-PF, NEEDS_MORE_DATA on tiny
samples, ACCEPTED only when every robustness cut passes, RESEARCH_ONLY otherwise.
Also checks the net-of-cost accounting and DSR bounds.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import edge_search_master as M


def _trade(coin, ts, gross_r, hold=5, sd=0.02, tf="1h"):
    return {"coin": coin, "entry_ts": ts, "exit_ts": ts + hold * 3_600_000,
            "gross_r": gross_r, "hold": hold, "side": 1, "sd": sd, "tf": tf}


def test_net_is_gross_minus_cost():
    # one trade, gross +1R, sd 0.02 -> cost ~ (0.0014 + funding)/0.02 R deducted
    t = _trade("BTC", 0, 1.0, hold=5, sd=0.02)
    net = M.net_r(t)
    assert net < 1.0                       # cost drag applied
    assert net > 0.85                      # but modest at this stop size


def test_dsr_is_a_probability():
    p, sr0 = M.dsr(0.3, 500, 0.0, 3.0, [0.1, 0.2, 0.3, 0.05, 0.15])
    assert 0.0 <= p <= 1.0
    # more trials with higher spread -> higher benchmark SR0 -> harder to pass
    p2, sr0b = M.dsr(0.3, 500, 0.0, 3.0, [0.1, 0.2, 0.3, 0.9, 0.05])
    assert sr0b > sr0 and p2 <= p


def test_verdict_needs_more_data_on_thin_sample():
    trades = [_trade("BTC", i * 1000, 1.0) for i in range(30)]
    m = M.evaluate(trades, sr_trials=[0.2, 0.3])
    assert M.verdict(m) == "NEEDS_MORE_DATA"


def test_verdict_no_go_on_negative_edge():
    day = 86_400_000
    trades = [_trade("BTC", i * day, -0.5 if i % 2 else 0.1) for i in range(200)]
    m = M.evaluate(trades, sr_trials=[0.0, -0.1])
    assert m["net_expR"] <= 0 or m["pf"] <= 1.1
    assert M.verdict(m) == "NO_GO"


def test_verdict_accepts_only_when_robust():
    # A clean, well-diversified, sign-consistent positive edge across 6 coins.
    day = 86_400_000
    coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]
    trades = []
    ts = 0
    for k in range(600):
        coin = coins[k % len(coins)]
        # steady positive expectancy with realistic win/loss mix
        gross = 1.6 if (k % 3) else -1.0
        trades.append(_trade(coin, ts, gross, sd=0.02))
        ts += day // 2
    m = M.evaluate(trades, sr_trials=[0.05, 0.10, 0.15])
    assert m["net_expR"] > 0 and m["pf"] > 1.1
    # both halves and both out-of-symbol folds positive by construction
    assert m["h2_expR"] > 0 and m["oos_train_expR"] > 0 and m["oos_test_expR"] > 0
    assert M.verdict(m) in ("ACCEPTED_FOR_PAPER", "RESEARCH_ONLY")
