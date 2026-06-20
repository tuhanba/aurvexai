"""
Paper/live parity.

The core invariant: the SAME mock signal produces the SAME Decision regardless
of executor, and the live executor consumes that identical decision. The only
differences live introduces are downstream execution concerns (canary risk
scaling + simulated flag), never the decision itself.
"""
import copy

from aurvex.decision import DecisionEngine
from aurvex.executors import LiveExecutor, PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, now_ms
from conftest import make_signal, make_snapshot


def _pf(balance=1000.0):
    return PortfolioView(balance=balance, open_count=0, open_symbols=[],
                         open_notional=0.0, last_trade_ms_by_symbol={},
                         daily_realized_pnl=0.0, now_ms=now_ms())


def test_same_decision_for_both_executors(cfg):
    eng = DecisionEngine(cfg)
    sig = make_signal(score=85.0)
    snap = make_snapshot()
    decision = eng.decide(sig, snap, _pf())
    assert decision.decision == ALLOW

    # Live gate must be explicitly opened.
    cfg.live_enabled = True
    cfg.live_human_confirm = "I_CONFIRM"

    paper = PaperExecutor(cfg)
    live = LiveExecutor(cfg, connection_ok=True)

    paper_trade = paper.open(copy.deepcopy(decision))
    live_trade, safety = live.open(copy.deepcopy(decision),
                                   snap_spread_pct=snap.orderbook.spread_pct,
                                   est_slippage_pct=0.0)
    assert safety.ok
    assert live_trade is not None

    # Decision-level fields identical (the shared brain output).
    for field in ("entry", "stop_loss", "tp1", "tp2", "tp3", "score",
                  "threshold", "risk_pct", "leverage"):
        pv = getattr(paper_trade, field, None)
        lv = getattr(live_trade, field, None)
        if field in ("tp1", "tp2", "tp3"):
            # trades store tps in tp_targets; compare those instead
            continue
        assert pv == lv, f"{field} differs: paper={pv} live={lv}"

    # TP target prices identical between paper and live.
    assert [t.price for t in paper_trade.tp_targets] == \
           [t.price for t in live_trade.tp_targets]

    # Differences are execution-only.
    assert paper_trade.mode == "paper"
    assert live_trade.mode == "live"
    assert live_trade.metadata.get("simulated") is True
    # Canary shrinks live size; paper is full size.
    assert live_trade.position_size <= paper_trade.position_size


def test_live_decision_uses_no_separate_threshold(cfg):
    # There is exactly one threshold/risk path; decision does not branch on mode.
    eng = DecisionEngine(cfg)
    d1 = eng.decide(make_signal(score=62.0), make_snapshot(), _pf())
    d2 = eng.decide(make_signal(score=62.0), make_snapshot(), _pf())
    assert d1.threshold == d2.threshold == cfg.trade_threshold
    assert d1.decision == d2.decision
