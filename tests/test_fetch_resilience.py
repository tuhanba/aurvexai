"""Data-fetch resilience: a transient failure is retried instead of discarding
the snapshot (the trade-blocker fix). Safety-neutral — only re-attempts to GET
fresh data; the cache/skip fallback is unchanged on total failure."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.market_data import CCXTProvider


def _provider(retries=2, backoff=0):
    cfg = Config()
    cfg.fetch_retries = retries
    cfg.fetch_retry_backoff_ms = backoff
    return CCXTProvider(cfg)


def test_succeeds_first_try():
    p = _provider()
    val, exc = p._with_retries(lambda: 42, "x")
    assert val == 42 and exc is None
    assert p.stats.retries == 0


def test_recovers_after_transient_failures():
    p = _provider(retries=2)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:          # fail twice, succeed on the 3rd
            raise ConnectionError("timeout")
        return "ok"

    val, exc = p._with_retries(flaky, "order_book")
    assert val == "ok" and exc is None
    assert calls["n"] == 3
    assert p.stats.retries == 2     # two retries were counted


def test_gives_up_after_exhausting_retries():
    p = _provider(retries=2)

    def always_fail():
        raise ConnectionError("dead link")

    val, exc = p._with_retries(always_fail, "order_book")
    assert val is None
    assert isinstance(exc, ConnectionError)     # last exc returned for the caller
    assert p.stats.retries == 2                 # attempts = retries + 1 = 3


def test_zero_retries_is_single_attempt():
    p = _provider(retries=0)
    calls = {"n": 0}

    def fail_once():
        calls["n"] += 1
        raise ValueError("x")

    val, exc = p._with_retries(fail_once, "x")
    assert val is None and isinstance(exc, ValueError)
    assert calls["n"] == 1          # no retry when fetch_retries=0 (old behaviour)
    assert p.stats.retries == 0
