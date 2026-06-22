"""
Regression: same-cycle exposure & margin caps.

Guards the bug where the engine opened several trades inside ONE cycle without
updating the running open_notional / open_margin, so the portfolio exposure cap
could be blown past in a single cycle (and every later cycle then rejected with
"portfolio exposure cap reached").

The fix keeps the running exposure/margin current between decisions in a cycle.
This test forces many ALLOW-able signals in a single cycle and asserts the cap
holds for the freshly opened book.
"""
import asyncio
import json

from aurvex.engine import Engine
from aurvex.models import LONG, Signal


def _force_allow_engine(cfg):
    """Engine whose detector emits a tradeable LONG for every symbol, scored
    above threshold, with same-cycle trade management disabled so the freshly
    opened book can be inspected directly."""
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_threshold = 60.0
    cfg.risk_pct = 0.5
    cfg.min_stop_dist_pct = 0.30
    eng = Engine(cfg)

    # CE-2: engine now calls detect_all() (not detect()); patch accordingly.
    def fake_detect_all(snap):
        price = snap.last_price
        return [Signal(symbol=snap.symbol, side=LONG, setup_type="momentum_breakout",
                       entry_hint=price, stop_hint=price * (1 - 0.0030),
                       base_confidence=0.9)]

    eng.detector.detect_all = fake_detect_all
    eng.engine.scorer.build = lambda sig, snap: setattr(sig, "score", 90.0)

    async def _noop(_snaps):
        return None

    eng._manage_open_trades = _noop  # keep trades open so we can measure the book
    return eng


def _run_one_cycle(eng):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(eng._cycle())
    finally:
        loop.close()


def test_same_cycle_respects_exposure_cap(cfg):
    cfg.max_portfolio_exposure_pct = 200.0   # cap = 2000 notional on 1000 balance
    cfg.max_open_trades = 8                   # do not let max_open mask the cap
    eng = _force_allow_engine(cfg)
    _run_one_cycle(eng)

    opens = eng.db.get_open_trades(mode=cfg.mode)
    total_notional = sum(t.position_size * t.remaining_fraction for t in opens)
    cap = cfg.initial_paper_balance * cfg.max_portfolio_exposure_pct / 100.0

    # Multiple trades opened in ONE cycle (the scenario that triggered the bug).
    assert len(opens) >= 2
    # And the cap is respected for the whole freshly opened book.
    assert total_notional <= cap + 1e-6, f"notional {total_notional} > cap {cap}"
    eng.db.close()


def test_same_cycle_respects_margin_cap(cfg):
    cfg.max_portfolio_exposure_pct = 300.0   # allow more notional than margin can back
    cfg.max_open_trades = 12
    eng = _force_allow_engine(cfg)
    _run_one_cycle(eng)

    opens = eng.db.get_open_trades(mode=cfg.mode)
    total_margin = sum(t.margin_used * t.remaining_fraction for t in opens)
    # Total committed margin can never exceed the account balance.
    assert total_margin <= cfg.initial_paper_balance + 1e-6, \
        f"margin {total_margin} > balance {cfg.initial_paper_balance}"
    eng.db.close()


def test_cap_actually_binds_midcycle(cfg):
    """At least one signal in the cycle must be rejected for the exposure cap,
    proving the running exposure is updated as trades open (not stale)."""
    cfg.max_portfolio_exposure_pct = 200.0
    cfg.max_open_trades = 8
    eng = _force_allow_engine(cfg)
    _run_one_cycle(eng)

    latest = eng.db.latest_funnel()
    raw = latest.get("top_reject_reasons") or "[]"
    reasons = dict((r[0], r[1]) for r in json.loads(raw))
    assert any("exposure cap" in k for k in reasons), \
        f"expected an exposure-cap reject in {reasons}"
    eng.db.close()


def test_second_trade_is_sized_to_remaining_room(cfg):
    """The second same-cycle trade must be sized down to the leftover room, not
    the full notional (the precise pre-fix symptom: two full-size trades)."""
    cfg.max_portfolio_exposure_pct = 200.0
    cfg.max_open_trades = 8
    eng = _force_allow_engine(cfg)
    _run_one_cycle(eng)

    opens = sorted(eng.db.get_open_trades(mode=cfg.mode),
                   key=lambda t: t.open_time)
    assert len(opens) >= 2
    notionals = [round(t.position_size, 2) for t in opens]
    # Not every opened trade is the same full size; the later one is clamped.
    assert len(set(notionals)) >= 2, f"all trades full size (cap not clamping): {notionals}"
    eng.db.close()
