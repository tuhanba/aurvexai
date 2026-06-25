"""Funnel logger: stage counting and top reject reasons."""
from aurvex.funnel import FunnelLogger
from aurvex.models import ALLOW, REJECT, WATCH, Decision


def _d(decision, stage="", reason=""):
    return Decision(symbol="X", side="LONG", decision=decision,
                    failed_stage=stage, reject_reason=reason)


def test_allow_counts():
    f = FunnelLogger()
    f.set_scanned(40, 12)
    f.record(_d(ALLOW))
    f.record(_d(ALLOW))
    f.mark_executed()
    assert f.stats.decision_allow_count == 2
    assert f.stats.score_pass_count == 2
    assert f.stats.risk_pass_count == 2
    assert f.stats.executed_count == 1
    assert f.stats.scanned_count == 40
    assert f.stats.candidate_count == 12


def test_watch_counts():
    f = FunnelLogger()
    f.record(_d(WATCH, stage="score_threshold"))
    assert f.stats.watch_count == 1
    assert f.stats.rejected_count == 0


def test_reject_attribution_and_top_reasons():
    f = FunnelLogger()
    f.record(_d(REJECT, stage="score_threshold", reason="low"))
    f.record(_d(REJECT, stage="risk", reason="exposure cap reached"))
    f.record(_d(REJECT, stage="cooldown", reason="cooldown 5m"))
    f.record(_d(REJECT, stage="cooldown", reason="cooldown 3m"))
    assert f.stats.rejected_count == 4
    # risk stage implies score passed
    assert f.stats.score_pass_count == 1
    top = f.stats.top_reject_reasons(5)
    # cooldown appears twice -> should be the top reason bucket prefix
    flat = dict(top)
    assert any(k.startswith("cooldown") for k in flat)


def test_finalize_sets_meta():
    f = FunnelLogger()
    stats = f.finalize(last_trade_minutes_ago=12.5, cycle_ms=42.0)
    assert stats.last_trade_minutes_ago == 12.5
    assert stats.cycle_ms == 42.0


def test_non_trading_bugra_signal_real_stage_not_score_threshold():
    """Buğra primary gate: under the default (score_as_gate=False) a non-trading
    Buğra signal is attributed to a real stage (filter/risk/slot), never the
    score_threshold gate."""
    from aurvex.config import Config
    from aurvex.decision import DecisionEngine
    from aurvex.filters import PortfolioView
    from aurvex.models import now_ms
    from conftest import make_signal, make_snapshot

    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_hours_utc = []
    assert cfg.score_as_gate is False

    de = DecisionEngine(cfg)
    # Cooldown reject (a real safety-filter stage), low score → must NOT be
    # attributed to score_threshold now that score is not a gate.
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, open_margin=0.0,
                       last_trade_ms_by_symbol={"BTCUSDT": now_ms() - 60_000},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    d = de.decide(make_signal(score=20.0), make_snapshot(), pf)

    f = FunnelLogger()
    f.record(d)
    assert d.failed_stage != "score_threshold"
    assert "score_threshold" not in dict(f.stats.top_reject_reasons(10))


def test_mark_ranked_out_is_capacity():
    f = FunnelLogger()
    f.mark_ranked_out("ranked_out:slots_full")
    assert f.stats.ranked_out_count == 1
    assert f.stats.capacity_reject_count == 1
    assert any(k.startswith("ranked_out") for k in dict(f.stats.top_reject_reasons(5)))
