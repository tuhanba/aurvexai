"""FTMO correlation clusters + concurrent-position cap."""
from aurvex.ftmo import correlation as corr


def test_cluster_of_known():
    assert corr.cluster_of("XAUUSD") == "metal"
    assert corr.cluster_of("XAGUSD") == "metal"
    assert corr.cluster_of("US500") == "equity"
    assert corr.cluster_of("NAS100") == "equity"
    assert corr.cluster_of("USDJPY") == "jpy"
    assert corr.cluster_of("EURUSD") == "usd_major"


def test_cluster_of_yahoo_symbol():
    # GC=F is the Yahoo symbol for XAUUSD -> resolves to the metal cluster.
    assert corr.cluster_of("GC=F") == "metal"


def test_cluster_of_unmapped_is_solo():
    assert corr.cluster_of("BTCUSDT").startswith("_solo:")
    assert corr.cluster_of("BTCUSDT") != corr.cluster_of("ETHUSDT")


def test_cluster_counts():
    counts = corr.cluster_counts(["XAUUSD", "XAGUSD", "US500", "USDJPY"])
    assert counts["metal"] == 2
    assert counts["equity"] == 1
    assert counts["jpy"] == 1


def test_cluster_full_caps_per_cluster():
    opens = ["XAUUSD", "XAGUSD"]          # 2 metals open
    assert corr.cluster_full("US500", opens, max_per_cluster=2) is False  # equity empty
    # A third metal would exceed a cap of 2.
    assert corr.cluster_full("GC=F", opens, max_per_cluster=2) is True
    assert corr.cluster_full("XAUUSD", opens, max_per_cluster=3) is False


def test_cluster_cap_disabled():
    opens = ["XAUUSD", "XAGUSD", "US500", "NAS100"]
    assert corr.cluster_full("US30", opens, max_per_cluster=0) is False
