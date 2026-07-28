"""FTMO account Monte-Carlo simulator.

Answers the questions the FTMO pivot actually needs measured, which raw
profit/expectancy metrics cannot:

    * Challenge Pass Rate      — P(reach the profit target before any breach)
    * Daily-breach Rate        — P(hit the daily-loss limit)
    * Max-loss Breach Rate     — P(hit the overall/trailing limit)
    * Funded Survival Rate     — P(survive a horizon with no breach, no target)
    * average drawdown, days-to-target, min health along the path

Method (the standard prop-firm estimator): take a strategy's per-trade **R
distribution** (net R = PnL / risk, e.g. from a backtest's closed trades),
bootstrap-resample it into thousands of simulated account paths, apply FTMO's
exact rule math (``FtmoRuleSet`` + a per-day CE(S)T reset with high-water
ratchet) at each step, and count outcomes. It is instrument-agnostic: feed it R
samples from crypto today, from FX/indices once that data is wired — the rules
and the estimator are identical.

Modelling notes (kept explicit and conservative):
  * Trades within a simulated day accumulate realized PnL; the daily rule is
    checked on the running day equity. ``intratrade_worst_r`` (default -1.0)
    also charges each trade a transient dip to its stop *before* resolving, so a
    day of "wins" that each first dipped toward the stop can still breach the
    daily rule — the equity (floating) basis FTMO enforces, not realized-only.
  * Risk per trade is ``risk_pct`` of the CURRENT balance (compounding) by
    default, or of the initial size when ``compounding=False``.
  * One account path stops at the first of: pass, daily breach, max breach, or
    the trade budget (``max_days × trades_per_day``) — the latter is a "did not
    finish" timeout, reported separately from a breach.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from .rules import FUNDED, FtmoRuleSet

# outcomes
PASS = "pass"
BREACH_DAILY = "breach_daily"
BREACH_MAX = "breach_max"
TIMEOUT = "timeout"


@dataclass
class AccountRun:
    outcome: str
    trades: int
    days: int
    final_balance: float
    max_drawdown: float          # peak-to-trough on realized balance (currency)
    max_drawdown_pct: float


@dataclass
class FtmoSimReport:
    n_runs: int
    account_size: float
    path: str
    phase: str
    risk_pct: float
    trades_per_day: float
    max_days: int
    r_sample_n: int
    r_sample_mean: float
    r_sample_win_rate: float
    # rates (0..1)
    pass_rate: float
    daily_breach_rate: float
    max_breach_rate: float
    timeout_rate: float
    survival_rate: float          # 1 - (daily+max breach) ; "didn't blow up"
    # path stats
    avg_days_to_pass: Optional[float]
    avg_max_drawdown_pct: float
    p95_max_drawdown_pct: float

    def to_dict(self) -> Dict:
        return asdict(self)

    def summary_lines(self) -> List[str]:
        pct = lambda x: f"{100.0 * x:5.1f}%"
        out = [
            f"FTMO {self.path}/{self.phase}  size={self.account_size:,.0f}  "
            f"risk={self.risk_pct}%  ~{self.trades_per_day} trades/day  "
            f"horizon={self.max_days}d  runs={self.n_runs}",
            f"  R-sample: n={self.r_sample_n} mean={self.r_sample_mean:+.3f}R "
            f"win={pct(self.r_sample_win_rate)}",
            f"  PASS rate ............ {pct(self.pass_rate)}",
            f"  daily-breach rate .... {pct(self.daily_breach_rate)}",
            f"  max-loss breach rate . {pct(self.max_breach_rate)}",
            f"  timeout (unfinished) . {pct(self.timeout_rate)}",
            f"  SURVIVAL (no breach) . {pct(self.survival_rate)}",
            f"  avg max drawdown ..... {self.avg_max_drawdown_pct:.1f}%  "
            f"(p95 {self.p95_max_drawdown_pct:.1f}%)",
        ]
        if self.avg_days_to_pass is not None:
            out.append(f"  avg days to target ... {self.avg_days_to_pass:.1f}")
        return out


def simulate_account(r_samples: Sequence[float], ruleset: FtmoRuleSet,
                     rng: random.Random, *, risk_pct: float = 0.5,
                     trades_per_day: int = 3, max_days: int = 60,
                     compounding: bool = True,
                     intratrade_worst_r: float = -1.0) -> AccountRun:
    """Simulate one FTMO account path over resampled trade outcomes."""
    size = ruleset.account_size
    balance = size
    day_open = size
    high_water = size
    peak = size
    max_dd = 0.0
    day_pnl = 0.0
    day_trades = 0
    days_completed = 0
    max_trades = max(1, trades_per_day * max_days)
    has_target = ruleset.has_profit_target
    target_amt = ruleset.profit_target_amount()

    for i in range(1, max_trades + 1):
        r = r_samples[rng.randrange(len(r_samples))]
        risk_amount = (balance if compounding else size) * (risk_pct / 100.0)

        # Transient intraday dip toward the stop BEFORE the trade resolves. This
        # is the equity (floating) basis: a trade that ultimately wins may still
        # have dipped enough to breach the daily/overall floor.
        dip = min(0.0, intratrade_worst_r) * risk_amount
        worst_equity = balance + dip
        worst_day_pnl = day_pnl + dip
        if worst_day_pnl <= -ruleset.daily_loss_amount():
            return AccountRun(BREACH_DAILY, i, days_completed, balance,
                              max_dd, _pct(max_dd, size))
        if worst_equity <= ruleset.max_loss_floor(high_water):
            return AccountRun(BREACH_MAX, i, days_completed, balance,
                              max_dd, _pct(max_dd, size))

        # Resolve the trade.
        pnl = r * risk_amount
        balance += pnl
        day_pnl += pnl
        day_trades += 1

        # Realized daily / overall checks.
        if day_pnl <= -ruleset.daily_loss_amount():
            return AccountRun(BREACH_DAILY, i, days_completed, balance,
                              max_dd, _pct(max_dd, size))
        if balance <= ruleset.max_loss_floor(high_water):
            return AccountRun(BREACH_MAX, i, days_completed, balance,
                              max_dd, _pct(max_dd, size))

        peak = max(peak, balance)
        max_dd = max(max_dd, peak - balance)

        # Pass check (target reached AND minimum trading days met).
        if has_target and (balance - size) >= target_amt \
                and (days_completed + 1) >= ruleset.min_trading_days:
            return AccountRun(PASS, i, days_completed + 1, balance,
                              max_dd, _pct(max_dd, size))

        # Day close.
        if day_trades >= trades_per_day:
            days_completed += 1
            day_open = balance
            high_water = max(high_water, balance)   # trailing ratchet on balance
            day_pnl = 0.0
            day_trades = 0

    return AccountRun(TIMEOUT, max_trades, days_completed, balance,
                      max_dd, _pct(max_dd, size))


def monte_carlo(r_samples: Sequence[float], ruleset: FtmoRuleSet, *,
                n_runs: int = 3000, risk_pct: float = 0.5,
                trades_per_day: int = 3, max_days: int = 60,
                compounding: bool = True, intratrade_worst_r: float = -1.0,
                seed: int = 7) -> FtmoSimReport:
    """Run ``n_runs`` account paths and aggregate FTMO outcome statistics."""
    if not r_samples:
        raise ValueError("r_samples is empty — need a per-trade R distribution")
    rng = random.Random(seed)
    counts = {PASS: 0, BREACH_DAILY: 0, BREACH_MAX: 0, TIMEOUT: 0}
    dds: List[float] = []
    days_to_pass: List[int] = []
    for _ in range(n_runs):
        run = simulate_account(
            r_samples, ruleset, rng, risk_pct=risk_pct,
            trades_per_day=trades_per_day, max_days=max_days,
            compounding=compounding, intratrade_worst_r=intratrade_worst_r)
        counts[run.outcome] += 1
        dds.append(run.max_drawdown_pct)
        if run.outcome == PASS:
            days_to_pass.append(run.days)

    n = float(n_runs)
    wins = sum(1 for r in r_samples if r > 0)
    passed = counts[PASS] / n
    daily = counts[BREACH_DAILY] / n
    mx = counts[BREACH_MAX] / n
    return FtmoSimReport(
        n_runs=n_runs, account_size=ruleset.account_size, path=ruleset.path,
        phase=ruleset.phase, risk_pct=risk_pct, trades_per_day=trades_per_day,
        max_days=max_days, r_sample_n=len(r_samples),
        r_sample_mean=round(statistics.fmean(r_samples), 4),
        r_sample_win_rate=round(wins / len(r_samples), 4),
        pass_rate=round(passed, 4), daily_breach_rate=round(daily, 4),
        max_breach_rate=round(mx, 4), timeout_rate=round(counts[TIMEOUT] / n, 4),
        survival_rate=round(1.0 - daily - mx, 4),
        avg_days_to_pass=(round(statistics.fmean(days_to_pass), 2)
                          if days_to_pass else None),
        avg_max_drawdown_pct=round(statistics.fmean(dds), 2) if dds else 0.0,
        p95_max_drawdown_pct=round(_percentile(dds, 95), 2) if dds else 0.0,
    )


def funded_survival(r_samples: Sequence[float], ruleset: FtmoRuleSet, *,
                    months: int = 12, **kw) -> FtmoSimReport:
    """Survival estimate for a FUNDED account over ``months`` (no target).

    Runs the sim with the phase forced to funded (no profit target → the only
    exits are a breach or surviving the horizon). SURVIVAL rate is the headline.
    """
    funded_rs = ruleset.with_overrides(phase=FUNDED, profit_target_pct=0.0,
                                       min_trading_days=0)
    trades_per_day = kw.pop("trades_per_day", 3)
    return monte_carlo(r_samples, funded_rs, trades_per_day=trades_per_day,
                       max_days=int(months * 21), **kw)   # ~21 trading days/mo


# -- helpers -----------------------------------------------------------------
def r_samples_from_trades(closed_trades) -> List[float]:
    """Extract net-R samples from a list of closed Trade objects."""
    out: List[float] = []
    for t in closed_trades:
        try:
            out.append(float(t.r_net))
        except Exception:
            continue
    return out


def synthetic_r_samples(seed: int = 7, n: int = 400, win_rate: float = 0.45,
                        win_r: float = 1.6, loss_r: float = -1.0) -> List[float]:
    """A synthetic per-trade R distribution for OFFLINE demonstration only.

    Default is a modest positive edge (EV ≈ +0.17R) so the harness illustrates
    the FTMO mechanics when no real backtest trades are available. NOT evidence
    of any real edge — the driver flags loudly when this fallback is used.
    """
    rng = random.Random(seed)
    return [win_r if rng.random() < win_rate else loss_r for _ in range(n)]


def run_from_backtest(cfg, *, symbols: Optional[List[str]] = None,
                      bars: int = 1500, seed: int = 7, n_runs: int = 3000,
                      risk_pct: Optional[float] = None, trades_per_day: int = 3,
                      max_days: int = 60, account_size: Optional[float] = None,
                      min_r_samples: int = 30):
    """Drive the FTMO Monte-Carlo from an offline backtest's R distribution.

    Returns ``(report, used_synthetic)``. When the backtest yields too few
    trades (offline/thin), falls back to :func:`synthetic_r_samples` and sets
    ``used_synthetic=True`` so the caller can flag the output as non-evidence.
    """
    from ..backtest import Backtester, generate_candles
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    data = {s: generate_candles(s, bars, seed=seed + idx,
                                start_price=100.0 * (idx + 1), tf=cfg.ltf)
            for idx, s in enumerate(symbols)}
    bt = Backtester(cfg)
    bt.run(data)
    closed = getattr(bt, "_last_closed", []) or []
    r_samples = r_samples_from_trades(closed)
    used_synthetic = False
    if len(r_samples) < min_r_samples:
        r_samples = synthetic_r_samples(seed)
        used_synthetic = True
    rs = cfg.ftmo_ruleset()
    if account_size:
        rs = rs.with_overrides(account_size=float(account_size))
    risk_pct = cfg.risk_pct if risk_pct is None else risk_pct
    report = monte_carlo(r_samples, rs, n_runs=n_runs, risk_pct=risk_pct,
                         trades_per_day=trades_per_day, max_days=max_days,
                         seed=seed)
    return report, used_synthetic


def _pct(amount: float, base: float) -> float:
    return round(100.0 * amount / base, 4) if base else 0.0


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
