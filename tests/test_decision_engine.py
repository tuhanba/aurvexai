"""Decision engine: ALLOW / WATCH / REJECT paths and determinism."""
from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, REJECT, WATCH, LONG, now_ms
from conftest import make_signal, make_snapshot


def _pf(cfg, balance=1000.0, open_symbols=None, last_times=None, daily_pnl=0.0):
    open_symbols = open_symbols or []
    return PortfolioView(
        balance=balance, open_count=len(open_symbols), open_symbols=open_symbols,
        open_notional=0.0, last_trade_ms_by_symbol=last_times or {},
        daily_realized_pnl=daily_pnl, now_ms=now_ms())


def test_allow_when_score_high(cfg):
    eng = DecisionEngine(cfg)
    sig = make_signal(score=85.0)
    d = eng.decide(sig, make_snapshot(), _pf(cfg))
    assert d.decision == ALLOW
    assert d.position_size > 0
    assert d.stop_loss > 0 and d.entry > 0
    assert d.tp1 and d.tp2 and d.tp3
    assert d.tp1 > d.entry > d.stop_loss  # long ordering


def test_watch_between_thresholds(cfg):
    eng = DecisionEngine(cfg)
    sig = make_signal(score=55.0)  # between watch(50) and trade(60)
    d = eng.decide(sig, make_snapshot(), _pf(cfg))
    assert d.decision == WATCH
    assert d.failed_stage == "score_threshold"


def test_reject_low_score(cfg):
    eng = DecisionEngine(cfg)
    sig = make_signal(score=20.0)
    d = eng.decide(sig, make_snapshot(), _pf(cfg))
    assert d.decision == REJECT
    assert d.failed_stage == "score_threshold"


def test_reject_on_filter_cooldown(cfg):
    eng = DecisionEngine(cfg)
    sig = make_signal(score=90.0)
    # Same symbol traded 1 minute ago; cooldown is 20 min default.
    last = {"BTCUSDT": now_ms() - 60_000}
    d = eng.decide(sig, make_snapshot(), _pf(cfg, last_times=last))
    assert d.decision == REJECT
    assert d.failed_stage == "cooldown"


def test_reject_on_max_open(cfg):
    eng = DecisionEngine(cfg)
    cfg.max_open_trades = 2
    sig = make_signal(score=90.0)
    pf = _pf(cfg, open_symbols=["ETHUSDT", "SOLUSDT"])  # full
    d = eng.decide(sig, make_snapshot(), pf)
    assert d.decision == REJECT
    assert d.failed_stage == "max_open_trades"


def test_determinism(cfg):
    eng = DecisionEngine(cfg)
    s1 = make_signal(score=85.0)
    s2 = make_signal(score=85.0)
    d1 = eng.decide(s1, make_snapshot(), _pf(cfg))
    d2 = eng.decide(s2, make_snapshot(), _pf(cfg))
    for k in ("decision", "score", "threshold", "entry", "stop_loss",
              "tp1", "tp2", "tp3", "position_size", "leverage"):
        assert getattr(d1, k) == getattr(d2, k)


def test_decision_contract_fields(cfg):
    eng = DecisionEngine(cfg)
    d = eng.decide(make_signal(score=85.0), make_snapshot(), _pf(cfg))
    dd = d.to_dict()
    for key in ("symbol", "side", "decision", "score", "threshold", "setup_type",
                "risk_pct", "entry", "stop_loss", "tp1", "tp2", "tp3",
                "position_size", "max_loss", "reason", "failed_stage",
                "reject_reason", "metadata"):
        assert key in dd
