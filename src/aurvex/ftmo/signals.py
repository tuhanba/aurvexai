"""Today's FTMO order tickets (ORB / PDHL) as structured, reusable data.

Shared by the CLI (`scripts/ftmo_signals_today.py`) and the Telegram sender
(`scripts/ftmo_send_signals.py`) so the level/lot logic lives in one place.

Pure w.r.t. data: callers pass a ``loader`` (instrument -> list[Candle]) so tests
inject synthetic bars and production uses the live fetch. All timing is UTC
sessions (day-boundary at 00:00 UTC); metals ORB uses the first hour of the
current session, index PDHL uses the prior session's range + ATR(14).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# instrument -> strategy
INSTRUMENTS = {"XAUUSD": "ORB", "GER40": "PDHL", "NAS100": "PDHL"}
# Value per 1.0 price point per 1.0 lot. Calibrated to FTMO's contract specs:
#   XAUUSD  contract 100 oz -> $100/point   (verify the gold spec once)
#   US100.cash / GER40.cash  contract size 1 -> 1 currency-unit/point
# (GER40.cash may be EUR-quoted; confirm its quote currency, else verify by trade.)
DEFAULT_PPV = {"XAUUSD": 100.0, "GER40": 1.0, "NAS100": 1.0}
VERIFY_PPV = {"XAUUSD": False, "GER40": True, "NAS100": False}


@dataclass
class Ticket:
    instrument: str
    strategy: str
    ref: str                 # human note about the range source
    buy_stop: float
    buy_sl: float
    sell_stop: float
    sell_sl: float
    stop_dist: float
    lots: float
    verify: bool


def _utc_day(ts: int) -> int:
    return ts // 86_400_000


def _atr14(bars) -> Optional[float]:
    if len(bars) < 15:
        return None
    trs = [max(bars[i].high - bars[i].low,
               abs(bars[i].high - bars[i - 1].close),
               abs(bars[i].low - bars[i - 1].close)) for i in range(1, len(bars))]
    return sum(trs[-14:]) / 14.0


def _lots(risk_amt: float, stop_dist: float, ppv: float) -> float:
    if stop_dist <= 0 or ppv <= 0:
        return 0.0
    return round(risk_amt / (stop_dist * ppv), 2)


def compute_ticket(instrument: str, bars, *, account: float, risk_pct: float,
                   ppv: float, stop_atr: float = 1.5) -> Optional[Ticket]:
    """Build the order ticket for one instrument, or None if not ready."""
    strat = INSTRUMENTS.get(instrument, "ORB")
    if not bars:
        return None
    risk_amt = account * risk_pct / 100.0
    verify = VERIFY_PPV.get(instrument, True)

    if strat == "ORB":
        cur = _utc_day(bars[-1].ts)
        session = [b for b in bars if _utc_day(b.ts) == cur]
        if len(session) < 2:
            return None                       # first hour not closed yet
        first = session[0]
        hi, lo = first.high, first.low
        if hi <= lo:
            return None
        dist = hi - lo
        return Ticket(instrument, strat, "first-hour range",
                      buy_stop=hi, buy_sl=lo, sell_stop=lo, sell_sl=hi,
                      stop_dist=dist, lots=_lots(risk_amt, dist, ppv), verify=verify)

    # PDHL
    cur = _utc_day(bars[-1].ts)
    prev = [b for b in bars if _utc_day(b.ts) == cur - 1]
    atr = _atr14(bars)
    if not prev or atr is None:
        return None
    ph, pl = max(b.high for b in prev), min(b.low for b in prev)
    dist = stop_atr * atr
    return Ticket(instrument, strat, f"prior-day {ph:.1f}/{pl:.1f} · ATR {atr:.1f}",
                  buy_stop=ph, buy_sl=ph - dist, sell_stop=pl, sell_sl=pl + dist,
                  stop_dist=dist, lots=_lots(risk_amt, dist, ppv), verify=verify)


def todays_tickets(loader: Callable[[str], list], *,
                   account: float = 100_000.0, risk_pct: float = 0.5,
                   ppv_map: Optional[Dict[str, float]] = None,
                   stop_atr: float = 1.5,
                   instruments: Optional[List[str]] = None) -> List[Ticket]:
    ppv_map = ppv_map or DEFAULT_PPV
    out: List[Ticket] = []
    for instr in (instruments or list(INSTRUMENTS)):
        try:
            bars = loader(instr)
        except Exception:
            continue
        t = compute_ticket(instr, bars, account=account, risk_pct=risk_pct,
                           ppv=ppv_map.get(instr, 1.0), stop_atr=stop_atr)
        if t is not None:
            out.append(t)
    return out


def format_tickets(tickets: List[Ticket], *, account: float, risk_pct: float,
                   header: str = "") -> str:
    risk_amt = account * risk_pct / 100.0
    lines = [header] if header else []
    lines.append(f"FTMO tickets · acct ${account:,.0f} · risk {risk_pct}% "
                 f"(${risk_amt:,.0f}/trade) · exit flat 00:00 UTC")
    if not tickets:
        lines.append("(no ready signals — for gold ORB re-run after 01:00 UTC)")
        return "\n".join(lines)
    for t in tickets:
        warn = " ⚠VERIFY lot" if t.verify else ""
        lines.append(
            f"\n{t.instrument} {t.strategy} ({t.ref}):"
            f"\n  BUY-STOP {t.buy_stop:.2f}  SL {t.buy_sl:.2f}"
            f"\n  SELL-STOP {t.sell_stop:.2f}  SL {t.sell_sl:.2f}"
            f"\n  stop {t.stop_dist:.2f} pts · ~{t.lots:.2f} lots{warn} · first break wins")
    return "\n".join(lines)
