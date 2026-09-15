# FTMO MODE — Phase 1 Architecture Roadmap

**Author:** Aurvex engineering (CTO / lead-quant architecture pass)
**Date:** 2026-07-27
**Branch:** `claude/ftmo-mode-architecture-qtob0m`
**Status:** DESIGN — no engine code changed by this document. This is the plan
that the implementation waves execute against.

> This document is the deliverable for the "FTMO Mode — Phase 1 Complete
> Architecture Refactor" task. It contains: (1) FTMO research from official
> sources, (2) a full review of the current Aurvex architecture, (3) the
> proposed FTMO-Mode architecture, and (4) a file-by-file, priority-ordered
> implementation plan with risk, testing, validation and migration strategy.
>
> It respects the non-negotiables in `CLAUDE.md`: paper/live parity stays
> sacred, the shadow learner never hard-vetoes, no secrets, keep it simple, and
> no real orders by default. FTMO Mode is added as a **config profile + a shared
> pre-trade compliance gate + an account-state service** — it does *not* fork
> the decision brain.

---

## 0. Executive summary (read this first)

1. **The biggest single fact: venue/instrument mismatch.** Aurvex is a
   **Binance USDT-M crypto-perpetual-futures** engine end to end — market data
   (`ccxt`/Binance), funding-rate model, isolated-margin liquidation math, and
   the live order path (`live_orders.py`, `order_payload.py`) are all
   Binance-perp specific. **FTMO is a simulated MetaTrader 4/5 (also cTrader /
   DXtrade) prop firm** trading FX, indices, commodities and *CFD* crypto — not
   Binance perps. You cannot literally place FTMO trades from this engine
   without a **new broker/market-data adapter** (an MT5 bridge or FTMO-platform
   connector). This roadmap treats that adapter as a distinct, later wave and
   makes **FTMO Mode Phase 1 a risk-governance + account-management operating
   layer** that (a) runs in paper/backtest against FTMO's *exact rule math*
   today, and (b) is execution-venue-agnostic so an MT5 bridge can be dropped in
   later without touching the brain.

2. **FTMO's binding constraints are rule-compliance limits, not alpha.** The
   objective flips from "max daily return" to "max probability of passing and
   staying funded for years". That is fundamentally a **risk-and-survival
   control problem**. Aurvex already has ~80% of the *primitives* (a shared
   risk manager, a daily-loss kill switch, an accounting reconciler, a funnel, a
   shadow learner). What it lacks is: **equity-based (floating) drawdown
   tracking**, a **static/trailing max-loss ledger vs a high-water mark**, a
   **CE(S)T day boundary**, a **pre-trade worst-case compliance projection**, an
   **operating-mode state machine**, and an **account Health Score**.

3. **The design adds one new package (`src/aurvex/ftmo/`) and one new shared
   gate**, wires FTMO state into the existing `PortfolioView` → `decide()` path
   so **parity is preserved automatically**, and extends (not replaces) the
   dashboard, telegram and backtester. No strategy code changes. No second path
   to the exchange. Every new veto is a *rule-compliance* veto (allowed by the
   non-negotiables), never an alpha/ML/regime veto (still forbidden).

---

# PART 1 — FTMO RESEARCH (official sources)

Primary source: **FTMO.com** (Trading Objectives, How-it-works). Corroborated
against multiple 2026 third-party summaries. Numbers below are the ones the
engine must encode as data (never hard-code a single account's numbers — they
vary by challenge type).

## 1.1 Products / evaluation paths

FTMO offers two evaluation formats in 2026:

| | **2-Step (Standard path)** | **1-Step** |
|---|---|---|
| Phases before funded | 2 (Challenge → Verification) | 1 (Challenge) |
| Phase-1 profit target | **10%** of initial capital | **10%** |
| Phase-2 profit target | **5%** | — (none) |
| Max **daily** loss | **5%** of initial capital | **3%** of initial capital |
| Max **overall** loss | **10%**, **static** (from initial balance) | **10%**, **trailing** (locks upward, never down) |
| Min trading days / phase | **≥ 4** calendar days (≥1 position opened) | not required |
| Time limit | **None** (the old 30-day cap was removed) | **None** |
| Consistency / best-day rule | — | single best day ≤ **50%** of total positive-day profit (soft; dilute by trading more) |
| Profit split (funded) | 80% → up to 90% via scaling | **90%** from first payout |
| Swing account variant | **Yes** | **No** |

## 1.2 The three rule engines that can kill an account

These are the only rules that *end* an evaluation or funded account. Everything
else is a target or an admin step.

**(A) Maximum Daily Loss.**
- Basis: **equity**, i.e. realized PnL **plus floating (open) PnL**. A big
  unrealized drawdown on open positions can breach it even with zero closes.
- Reference point: the **balance recorded at 00:00 CE(S)T** of the *current*
  day (Central European (Summer) Time — note DST). The limit for the day is
  `day_open_balance − dailyLossAmount`, where `dailyLossAmount` = 5% (2-Step) /
  3% (1-Step) of **initial** capital.
- Reset: recalculated daily at **00:00 CE(S)T**.
- **Implication for Aurvex:** the current kill switch is *realized-PnL only* and
  *UTC-day* based. Both are wrong for FTMO. This is the #1 correctness gap.

**(B) Maximum Loss (overall drawdown).**
- 10% of initial capital.
- **2-Step: static** — floor is fixed at `initial − 10%` forever.
- **1-Step: trailing** — the floor is `high_water − 10%` where `high_water`
  ratchets up (end-of-day balance based) and **never decreases**.
- Basis: equity for intraday monitoring (a floating loss can breach it).

**(C) Consistency / best-day (1-Step & funded scaling).**
- No single day's profit may exceed ~50% of total profit at payout time. Not an
  instant violation — it *blocks payout* until diluted by more trading days.

## 1.3 Trading-condition rules (Standard vs Swing)

- **Standard account:** no holding positions **over the weekend** (must be flat
  before weekend close); **2-minute news buffer** on funded — no opening/closing
  affected instruments within ±2 min of high-impact news.
- **Swing account (2-Step only):** **exempt** from both the news restriction and
  the weekend-close rule. 1-Step has no Swing option.
- **Implication:** Aurvex needs a **calendar/session module** (CE(S)T aware) and,
  for a real FTMO connection, an **economic-calendar feed** for the news buffer.
  In crypto-paper simulation these are configurable/optional.

## 1.4 Funded phase, scaling, payouts

- **Funded account:** no profit target; the two loss rules (A, B) still bind.
  Objective becomes *protect the account and reach payout*.
- **Scaling plan:** +25% balance every 4 months if ≥10% net profit over the
  period, profit in ≥2 of the 4 months, and zero rule violations. Split rises
  toward 90%.
- **Payout:** first payout available on the on-demand / 14-day cycle; must be in
  profit with **no open or pending orders**; requested in Account MetriX.

## 1.5 What the engine must model as *data* (not constants)

`FtmoRuleSet` fields: `account_size`, `path` (one_step|two_step), `phase`
(challenge|verification|funded), `profit_target_pct`, `daily_loss_pct`,
`max_loss_pct`, `max_loss_mode` (static|trailing), `min_trading_days`,
`account_variant` (standard|swing), `weekend_flat_required`,
`news_buffer_minutes`, `consistency_max_day_pct`, `profit_split_pct`,
`tz` = "Europe/Prague" (CE(S)T). One `FtmoRuleSet` instance per configured
account; the code reads fields, never literals.

**Sources:**
- [FTMO — Trading Objectives](https://ftmo.com/en/trading-objectives/)
- [FTMO — How it works](https://ftmo.com/en/how-it-works/)
- [FTMO Rules 2026: 1-Step & 2-Step (tradetanto)](https://tradetanto.com/learn/ftmo-rules-evaluation-process)
- [FTMO Payouts Guide 2026 (Lune)](https://lunefi.com/blog/ftmo-payouts)
- [FTMO Rules — Drawdown & Reset Policy (brokeranalysis)](https://brokeranalysis.com/prop-trading-firms/ftmo/rules/)

> ⚠️ FTMO tweaks numbers periodically (the 1-Step launched Feb 2026, the 30-day
> limit was removed). Encode every number in `FtmoRuleSet`/`.env`, add a
> `rules_source_date`, and re-verify against ftmo.com before any live use.

---

# PART 2 — CURRENT ARCHITECTURE REVIEW

Method: read the source directly. Line/behaviour references are to files as they
exist on this branch.

## 2.1 Data flow (as built)

```
market data (ccxt/Binance) → scanner → setups [PRIMARY GATE]
  → filters (hard vetoes) → risk gate (sizing) → DecisionEngine.decide()
  → PaperExecutor / LiveExecutor → journal/shadow/funnel → SQLite
  → dashboard (Flask) / telegram
```

Single decision brain: `decision.py::DecisionEngine.decide()` is called
identically by paper, live and backtest. This is the parity guarantee and it is
genuinely respected today.

## 2.2 Module-by-module review

| Module | LOC | What it does | FTMO relevance |
|---|---|---|---|
| `decision.py` | 167 | The single brain. filters → (advisory score) → risk → ALLOW. Mode-agnostic. | **Core reuse.** FTMO gate slots in here as one more hard filter — parity preserved for free. |
| `risk.py` | 456 | Shared `RiskManager`. Sizes notional from `risk_pct`/stop (cost-inclusive), controlled leverage, exposure cap, liq-safety invariant, TP ladder. `risk_multiplier ∈ [0.5,1.5]`. | **Core reuse.** FTMO changes the *inputs* (risk_pct, caps) per mode/health, not the math. Add a *max-loss-aware* notional ceiling. |
| `filters.py` | 212 | Minimal hard vetoes incl. `f_daily_loss` (realized-only, UTC), `f_daily_profit_lock`, `f_max_open`, cooldown, spread, slippage, trade-hours. `PortfolioView` carries account state into `decide()`. | **Primary extension point.** Add `f_ftmo_compliance`. `PortfolioView` is exactly the channel to inject FTMO state without breaking parity. |
| `accounting.py` | 84 | Pure reconciler: initial/realized_closed/realized_open_partial/unrealized/**equity**. Proves cash invariant. | **Key primitive.** `equity` here is the number FTMO's daily/overall loss rules read. Reuse directly. |
| `engine.py` | 2096 | Orchestrator: cycle loop, snapshotting, portfolio build, kill-switch firing, profit-lock/flatten, regime advisory, mode switch, panic flatten, live preflight/gates, multi-strategy fan-out. Builds `PortfolioView` in `_portfolio()`. | **Main wiring site.** FTMO account-state update + mode transitions hook into the cycle loop; `_portfolio()` populates FTMO fields. |
| `executors.py` | 583 | `PaperExecutor` / base. Exit management, partial scale-outs, funding, journal writes. | Reuse. FTMO needs an "equity mark each cycle" hook (already have marks) and a weekend-flatten call. |
| `live_orders.py` / `order_payload.py` | 443/437 | Binance-perp real order path (five-gate locked, disarmed by default). | **Not usable for FTMO.** FTMO needs a separate MT5/FTMO adapter behind the same executor interface (later wave). Do NOT bend the Binance path toward FTMO. |
| `shadow.py` | 819 | Observe-first learner over paper + rejected populations; single-target R outcome; stages 0/50/100 → advisory `score_delta`/`risk_multiplier`. **Never hard-vetoes.** | **Extend labels.** Add FTMO-survival labels (did-this-trade-help/hurt-survival, should-have-skipped, drawdown-added). Stays advisory. |
| `metrics.py` | 141 | Win rate, expectancy, R, PF, `max_drawdown`, breakdowns. | Extend with FTMO metrics (see backtest section). |
| `backtest.py` | ~390 | Offline/real-candle backtester reusing the brain; funding, trailing, `compute_metrics`. | **Extend** to FTMO-simulation harness: pass-rate, breach-rate, funded-survival across many seeds. |
| `dashboard/app.py` | 1133 | Flask, ~25 JSON routes + index. Status/accounting/portfolio/regime/live-readiness. | Add FTMO card + `/api/ftmo` route. |
| `telegram.py` | 625 | Notifier interface + Telegram impl; typed events (kill switch, profit target, regime, receipts…). | Add FTMO decision-explanation events. |
| `config.py` | 977 | Env-driven config, `RISK_PROFILE` presets, validation asserts. | Add FTMO config block + `FtmoRuleSet` loader + an `ftmo_*` profile. |
| `governor.py` | 562 | Read-only advisory aggregator (`REGIME_ADVISORY` etc.). | Good home for a read-only "FTMO advisory" surface before it becomes a hard gate. |
| `storage.py` | 1008 | SQLite: trades, signal_events, funnel, shadow, balance, metrics. | Add `ftmo_account_state` + `ftmo_day` tables; `daily_realized_pnl` already exists. |
| `models.py` | 332 | Dataclasses; `Decision` is the contract. | Add FTMO fields to `Decision.metadata` (no schema break). |

## 2.3 Strengths (keep these)

- **True single-brain parity.** `decide()` is genuinely mode-agnostic; parity is
  tested (`test_paper_live_parity.py`). This is the platform FTMO Mode stands on.
- **Explicit, auditable risk math** with a liq-safety invariant and cost-inclusive
  sizing — already "1R = the configured net budget".
- **A real accounting reconciler** that already computes **equity** (the exact
  quantity FTMO's rules read) and proves a cash invariant.
- **Observe-first funnel + shadow** — the perfect substrate for "should I trade?"
  because it already tracks *rejected* signals and what would have happened.
- **Flag-gated, parity-proven change discipline** (regime layer shipped OFF by
  default with a parity test). FTMO Mode should follow the same discipline.
- **A hard daily-loss kill switch and profit-lock/flatten already exist** — the
  scaffolding for FTMO's daily rule is present, just measured on the wrong basis.

## 2.4 Weaknesses / gaps vs FTMO (problems found)

**P1 — Daily-loss basis is wrong for FTMO (correctness).**
`filters.f_daily_loss` and `engine.py` fire on `daily_realized_pnl` only
(`filters.py:148`, `engine.py:1453`). FTMO's daily loss is **equity-based**
(floating counts) and resets at **00:00 CE(S)T**, not UTC (`engine.py:67`
`_utc_day_start_ms`). A floating drawdown that never closes can breach FTMO while
the current kill switch stays silent. **This alone can fail an account.**

**P2 — No overall max-loss ledger / high-water mark.** Nothing tracks the
static-vs-trailing 10% floor or a ratcheting high-water balance. The engine has
no concept of "distance to account death".

**P3 — No worst-case pre-trade projection.** `risk.py` sizes to lose ~`risk_pct`
at *this trade's* stop, but never asks "if this new position AND all open
positions hit their stops together, do we breach the remaining daily or overall
budget?" FTMO requires *portfolio-worst-case* thinking, not per-trade.

**P4 — No operating-mode state machine.** There is a paper/live *execution* mode
and a `strategy_profile`, but no Challenge/Funded/Payout/Recovery/Survival
behavioural mode that reshapes risk/frequency/thresholds by account situation.

**P5 — No account Health Score.** No single scalar that summarises account danger
and throttles the system continuously.

**P6 — Objective is return, not survival.** Risk sizing, profit-lock and the
whole funnel optimise realized edge. There is no "no-trade is a valid, *good*
decision" logic, no survival/pass-probability estimate.

**P7 — Backtest measures money, not FTMO outcomes.** `metrics.py`/`backtest.py`
report expectancy/PF/`max_drawdown`, not pass-rate, breach-rate, funded-survival,
time-to-target, or rule-violation counts.

**P8 — Calendar blind spots.** No CE(S)T day boundary, no weekend-flat logic, no
news buffer, no min-trading-day tracking.

**P9 — Venue mismatch (strategic).** As in §0.1 — Binance perps ≠ FTMO CFD/MT5.
The reusable asset is the *brain and risk framework*; execution/data need a new
adapter. Pretending otherwise is the main way this project could go wrong.

**P10 — Crypto edge is a documented NO-GO.** `SYSTEM_STATE.md` records scalp as a
final NO-GO and only multi-strategy trend/squeeze as validated. FTMO Mode must
not resurrect scalp, and must treat the *strategy* question (does any edge exist
on FTMO instruments?) as **unproven and out of Phase-1 scope** — Phase 1 delivers
the *governance OS*, not a new alpha claim.

---

# PART 3 — PROPOSED FTMO-MODE ARCHITECTURE

## 3.1 Design principles

1. **FTMO Mode is a governance layer around the existing brain, not a fork.**
   Everything new is either (a) config, (b) account-state computed each cycle, or
   (c) a *shared* pre-trade compliance gate inside `decide()`. Paper/live/backtest
   all pass through it identically → **parity holds by construction**.
2. **Every new veto is a rule-compliance veto**, never an alpha veto. This is
   consistent with `CLAUDE.md` (which forbids macro/news/ML/regime *alpha* vetoes,
   not risk-limit gates).
3. **Fail-closed on rules.** If FTMO state is unknown/stale, the compliance gate
   blocks new risk. The opposite of the alpha layers (which fail-open/observe).
4. **Execution-venue-agnostic.** FTMO state is fed money numbers (equity,
   day-open balance, high-water). It does not care whether those came from
   Binance-paper, a backtest, or a future MT5 bridge.
5. **Flag-gated, OFF by default, parity-tested** — same discipline as the regime
   wave.

## 3.2 New package `src/aurvex/ftmo/`

```
src/aurvex/ftmo/
  __init__.py
  rules.py          # FtmoRuleSet dataclass + loader from config/.env
  account_state.py  # FtmoAccountState: day-open baseline, high-water, budgets
  compliance.py     # pre-trade worst-case projection → allow/deny + reasons
  health.py         # HealthScore (0..100) from account danger signals
  modes.py          # FtmoMode state machine + per-mode behaviour profile
  objectives.py     # challenge progress, pass/survival probability estimates
  calendar.py       # CE(S)T day boundary, weekend, (optional) news windows
```

### 3.2.1 `rules.py` — `FtmoRuleSet`
Immutable per-account rule data (from §1.5). Pure data + helpers:
`daily_loss_amount(initial)`, `max_loss_floor(high_water, initial)` (branches
static/trailing), `profit_target_amount(phase)`.

### 3.2.2 `account_state.py` — `FtmoAccountState`
The heart of the system. Updated **every cycle** from
`accounting.compute_accounting(...)` output + the CE(S)T calendar:

- `day_open_balance` — balance snapshot at the last CE(S)T 00:00 boundary.
- `equity`, `balance`, `floating_pnl` — from the reconciler.
- `high_water_balance` — ratchets up on day-close (for 1-Step trailing).
- Derived budgets (the numbers the gate and dashboard use):
  - `remaining_daily_loss = equity − (day_open_balance − daily_loss_amount)`
  - `remaining_max_loss = equity − max_loss_floor`
  - `current_drawdown = high_water − equity`
  - `daily_risk_budget` = min(remaining_daily_loss, remaining_max_loss) × a
    **mode-scaled fraction** (never risk the whole budget in one day).
  - `trading_days_done`, `days_to_min`, `phase_progress_pct`.
- Persisted to a new `ftmo_account_state` table so a restart mid-day keeps the
  CE(S)T baseline and high-water (critical — losing day-open resets the budget).

### 3.2.3 `compliance.py` — the pre-trade gate (the important new logic)
`evaluate(candidate_decision, open_trades, state, ruleset) -> ComplianceResult`.
It answers **"Should this trade exist given FTMO rules?"** using *portfolio
worst-case*, not per-trade risk:

```
projected_daily_worst = floating_pnl_if_all_open_hit_stops
                        + candidate.max_loss           # this trade's stop loss
if equity_after_daily_worst < day_open_balance − daily_loss_amount:  DENY(daily)
if equity_after_total_worst  < max_loss_floor:                        DENY(max_loss)
if candidate.max_loss > state.daily_risk_budget_remaining:            DENY(budget)
if weekend_flat_required and near_weekend_close:                      DENY(weekend)
if news_buffer active on instrument:                                  DENY(news)
if correlation/exposure would concentrate worst-case:                 DENY(concentration)
```

Returns an explicit reason string (fed to telegram + funnel). This gate is the
concrete implementation of the task's rule: *"If the trade increases the
probability of violating any FTMO rule, the trade must never be executed."*

### 3.2.4 `health.py` — Account Health Score
`HealthScore` ∈ [0,100], a weighted blend (all normalised, all *lower = more
danger*):

```
health = w1·daily_budget_headroom_frac
       + w2·max_loss_headroom_frac
       + w3·(1 − current_drawdown/max_loss_amount)
       + w4·distance_to_target_progress        (challenge only)
       + w5·recent_volatility_of_equity_inverse
```

Health **modulates, never vetoes** (vetoes are the compliance gate's job). It
maps to a **mode-consistent** risk multiplier and threshold nudge:
- lower health → smaller `risk_multiplier` (into the existing `[0.5,1.5]` clamp
  in `risk.py:202`), fewer `max_open_trades`, higher effective confidence
  threshold, fewer trades/day. This satisfies "the lower the health, the more
  conservative the AI becomes" **without** introducing a new alpha veto.

### 3.2.5 `modes.py` — operating-mode state machine
`FtmoMode ∈ {CHALLENGE, FUNDED, PAYOUT, RECOVERY, SURVIVAL}` with a pure
transition function `next_mode(state, ruleset, calendar) -> FtmoMode` and a
`ModeProfile` (risk fraction, max trades, target confidence, daily-budget
fraction, allow-new-risk flag):

| Mode | Trigger | Behaviour profile |
|---|---|---|
| **Challenge** | phase ∈ challenge/verification, healthy | Balanced: reach target with margin; cap daily budget fraction; stop for the day once a sensible daily gain banked (reuse profit-lock). |
| **Funded** | phase = funded, healthy | Protect first: smaller daily budget fraction, tighter concentration, "no-trade" bias. |
| **Payout** | funded & payout window near | Minimal risk: only high-conviction, shrink size, prioritise not breaching before payout date; flatten before payout (no open orders rule). |
| **Recovery** | current_drawdown > X% of max-loss | Halve risk, raise confidence threshold, reduce max_open, require worst-case headroom ≫ budget. Climb out slowly. |
| **Survival** | remaining_daily or remaining_max_loss below a hard floor | Near-freeze: block essentially all new risk (compliance gate denies), manage/flatten open, wait for day reset. |

Mode is computed each cycle in the engine (like `_market_regime()`), surfaced to
dashboard/telegram, and its `ModeProfile` feeds Health + the risk inputs. Modes
change *inputs* to the shared brain — never `decide()`'s allow/reject logic —
so parity is intact.

### 3.2.6 `objectives.py` — survival / pass probability
Cheap, explicit estimators (not ML): challenge progress %, expected days to
target at current expectancy, an empirical **pass-probability** and
**survival-probability** from the Monte-Carlo FTMO backtest (§Part 6). Displayed,
not used as a gate in Phase 1.

## 3.3 How it wires into the existing brain (parity-safe)

```
engine cycle:
  reconcile → accounting.equity/balance/floating          (existing)
  → ftmo.calendar: CE(S)T day boundary? update day_open_balance, roll high-water
  → ftmo.account_state.update(...)                          (NEW, each cycle)
  → ftmo.modes.next_mode(...) ; ftmo.health.score(...)      (NEW)
  → _portfolio(): PortfolioView gains ftmo_state + health   (extend existing)
  → per candidate: DecisionEngine.decide(signal, snap, pf, risk_multiplier)
        filters.evaluate(...)  ← includes NEW f_ftmo_compliance (shared gate)
        risk.evaluate(...)     ← risk_pct/caps come from ModeProfile×Health
  → telegram.ftmo_decision(...) explains allow/deny         (NEW event)
```

Because the gate lives in the shared `FilterChain` and the mode/health only
change *config inputs*, **paper, live and backtest get identical FTMO behaviour**
and `test_paper_live_parity.py` still passes.

## 3.4 Execution/venue (explicitly deferred, but designed for)

Phase 1 runs FTMO Mode over the existing Binance-paper/backtest money stream —
i.e. it *simulates* an FTMO account's rule math against real price action. A
**later** wave adds `src/aurvex/adapters/ftmo_mt5.py` implementing the same
executor interface as `PaperExecutor`, plus an MT5 market-data provider. The
brain, risk, compliance gate, modes and health are all reused unchanged. The
Binance `live_orders.py` five-gate lock is **not** touched and is **not** a path
to FTMO.

---

# PART 4 — MODULE CHANGES (summary)

| File | Change | Type |
|---|---|---|
| `src/aurvex/ftmo/*` | New package (7 modules above) | **NEW** |
| `config.py` | FTMO config block, `FtmoRuleSet` loader, `ftmo_*` profile, `FTMO_MODE_ENABLED` flag (default OFF), validation asserts | Extend |
| `.env.example` | Documented FTMO vars (account size, path, phase, variant, tz, enable flag) | Extend |
| `filters.py` | New `f_ftmo_compliance`; `PortfolioView` gains `ftmo_state`, `health`; gate no-ops when `FTMO_MODE_ENABLED=false` | Extend |
| `engine.py` | Build/update `FtmoAccountState`, compute mode+health each cycle, populate `PortfolioView`, CE(S)T boundary in `_utc_day_start_ms` sibling, weekend-flatten hook, mode/health telegram | Extend |
| `risk.py` | Optional max-loss-aware notional ceiling; consume mode/health-derived `risk_pct`/caps (via existing override params — no signature break where avoidable) | Extend |
| `accounting.py` | (reuse) optionally expose `floating_pnl` explicitly | Minor |
| `shadow.py` | New FTMO-survival labels (survival-helpful / payout-hurting / should-skip / drawdown-added); stays advisory | Extend |
| `metrics.py` / `backtest.py` | FTMO metrics + Monte-Carlo FTMO simulation harness | Extend |
| `dashboard/app.py` (+ template) | `/api/ftmo` route + FTMO card | Extend |
| `telegram.py` | `ftmo_decision`, `ftmo_mode_change`, `ftmo_rule_warning`, `ftmo_health` events | Extend |
| `storage.py` | `ftmo_account_state`, `ftmo_day` tables; persistence of baseline/high-water | Extend |
| `models.py` | FTMO fields into `Decision.metadata` (no schema break) | Minor |
| `governor.py` | Optional `FTMO_ADVISORY` read-only surface (pre-gate rollout) | Optional |
| `main.py` | `ftmo-backtest` subcommand for the simulation harness | Extend |
| `tests/` | New test modules (see Part 7) | **NEW** |

---

# PART 5 — FILE-BY-FILE IMPLEMENTATION PLAN (waves)

Each wave is independently shippable, flag-gated OFF, and ends with `pytest`
green + parity intact + `python main.py demo` completing.

### Wave 0 — Rules & account-state (no behaviour change)
1. `src/aurvex/ftmo/rules.py` — `FtmoRuleSet` + loader.
2. `src/aurvex/ftmo/calendar.py` — CE(S)T (`Europe/Prague`) day boundary, weekend
   windows; unit-test DST transitions.
3. `src/aurvex/ftmo/account_state.py` — `FtmoAccountState.update()` from
   accounting output; budgets; high-water ratchet; static/trailing floor.
4. `storage.py` — `ftmo_account_state` table + load/save.
5. `config.py` + `.env.example` — FTMO block, `FTMO_MODE_ENABLED=false`.
6. Tests: `test_ftmo_rules.py`, `test_ftmo_calendar.py`, `test_ftmo_state.py`
   (incl. equity-vs-realized daily breach, CE(S)T reset, trailing vs static).
   *No engine wiring yet → zero behaviour change, trivially parity-safe.*

### Wave 1 — Health & modes (still no gate)
7. `src/aurvex/ftmo/health.py` — `HealthScore`.
8. `src/aurvex/ftmo/modes.py` — mode state machine + `ModeProfile`.
9. `engine.py` — compute state/health/mode each cycle; stash in `PortfolioView`
   (carried, **not yet gating**); telegram `ftmo_mode_change`/`ftmo_health`.
10. `dashboard/app.py` + template — read-only FTMO card + `/api/ftmo`.
11. Tests: `test_ftmo_health.py`, `test_ftmo_modes.py`, `test_ftmo_dashboard.py`,
    a **parity test** proving `decide()` output unchanged while FTMO fields ride
    along.

### Wave 2 — The compliance gate (behaviour change, flag-gated)
12. `src/aurvex/ftmo/compliance.py` — worst-case projection.
13. `filters.py` — `f_ftmo_compliance` (no-op unless `FTMO_MODE_ENABLED`).
14. `risk.py` — max-loss-aware ceiling; consume mode/health risk inputs.
15. `telegram.py` — `ftmo_decision` (approve/deny + reason), `ftmo_rule_warning`.
16. `shadow.py` — FTMO-survival labels.
17. Tests: `test_ftmo_compliance.py` (daily/max/weekend/news/concentration denies),
    `test_ftmo_gate_parity.py` (**gate OFF ⇒ byte-identical to today**),
    `test_ftmo_no_trade_is_valid.py`.

### Wave 3 — FTMO backtest / validation harness
18. `metrics.py` — FTMO metrics.
19. `backtest.py` — Monte-Carlo FTMO simulation (many seeds → pass/breach/survival).
20. `main.py` — `ftmo-backtest` subcommand.
21. `objectives.py` — pass/survival probability from the harness.
22. Tests: `test_ftmo_backtest.py`, `test_ftmo_metrics.py`.

### Wave 4 (later, separate approval) — MT5/FTMO execution adapter
23. `src/aurvex/adapters/ftmo_mt5.py` (executor iface) + MT5 data provider,
    behind its own multi-gate lock analogous to Binance's five-gate. **Not part
    of Phase 1.** Requires an explicit owner decision like `FINAL_OWNER_DECISION.md`.

---

# PART 6 — PRIORITY ORDER

1. **P1 (correctness, must-fix first):** equity-based, CE(S)T daily-loss +
   overall max-loss ledger (Wave 0) — this is the rule that fails accounts.
2. **P2:** worst-case pre-trade compliance gate (Wave 2 core).
3. **P3:** operating modes + Health throttling (Wave 1).
4. **P4:** FTMO simulation/backtest so claims are measured, not asserted (Wave 3).
5. **P5:** dashboard/telegram FTMO surfaces (Waves 1–2, incremental).
6. **P6:** shadow FTMO-survival labels (Wave 2).
7. **P7 (deferred):** MT5/FTMO execution adapter (Wave 4, separate approval).

Rationale: rule *math* correctness before any behaviour change; the gate before
the cosmetics; measurement before the real-money adapter.

---

# PART 7 — RISK ASSESSMENT

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Breaking paper/live parity** | Med | High | Gate lives in shared `FilterChain`; mode/health change only *inputs*; a dedicated `test_ftmo_gate_parity.py` proves `decide()` is byte-identical with the flag OFF. Ship OFF by default. |
| **Wrong FTMO numbers** (rules drift) | Med | High | All numbers in `FtmoRuleSet`/`.env` + `rules_source_date`; re-verify vs ftmo.com before live; never hard-code. |
| **Equity-basis regression** in the daily rule | Med | High | New gate is additive and flag-gated; keep the legacy realized-only kill switch untouched for Binance-paper; FTMO daily rule is a *separate* gate reading `equity`. |
| **Venue mismatch mis-sold as "trades FTMO now"** | High if unmanaged | High | This doc states plainly: Phase 1 is governance/simulation; real FTMO execution is Wave 4 behind its own lock. |
| **Reintroducing forbidden complexity** (CEO/multi-AI/alpha vetoes) | Low | Med | Every new veto is a *rule-compliance* veto; Health/modes only modulate; shadow stays advisory. Reviewed against `CLAUDE.md` non-negotiables. |
| **Restart loses CE(S)T baseline / high-water** → wrong budget | Med | High | Persist `ftmo_account_state`; on boot, restore day-open + high-water; reconcile on start. |
| **No proven edge on FTMO instruments** | High | High (strategic) | Phase 1 makes **no** alpha claim; it delivers the OS. Edge on FX/indices is an explicit, separate research question gated by the Monte-Carlo harness before any funded attempt. |
| **DST / timezone bugs** | Med | Med | Use a tz library (`zoneinfo`), unit-test spring/autumn transitions, store the tz name not a fixed offset. |

---

# PART 8 — TESTING STRATEGY

- **Unit (per new module):** rules math, calendar/DST, state budgets (equity vs
  realized daily breach; static vs trailing floor; high-water ratchet), health
  monotonicity, mode transitions, compliance denies for each rule, worst-case
  projection with multiple open trades.
- **Parity (non-negotiable):** `test_ftmo_gate_parity.py` — with
  `FTMO_MODE_ENABLED=false`, `decide()` and executor outputs are identical to
  `main` for a fixed seed. Existing `test_paper_live_parity.py` stays green.
- **Behavioural:** with the flag ON, construct account states just inside/outside
  each limit and assert allow/deny + exact reason string; assert "no-trade" is
  emitted as a first-class decision, not a silent skip.
- **Integration:** `python main.py demo` and `python main.py backtest` complete
  end-to-end with the flag both OFF and ON.
- **Regression:** full `pytest` (48+ existing tests) stays green at every wave.
- **Property tests (nice-to-have):** invariant "the gate never allows a trade
  whose portfolio worst-case breaches a limit" over randomised states.

---

# PART 9 — VALIDATION STRATEGY

Following the repo's evidence culture (`SYSTEM_STATE.md`, `TEST_EVIDENCE.md`):

1. **FTMO Monte-Carlo harness** (Wave 3): run the shared brain over historical +
   bootstrapped price paths for a chosen instrument set, N seeds, and report:
   **Challenge Pass Rate, Verification Pass Rate, Daily-breach Rate, Max-loss
   Breach Rate, Funded-Survival Rate (e.g. survives 12 months), Monthly Payout
   Probability, Rule-violation count, Recovery Time, Average Health, Avg time-to-
   target, Expected Lifetime Value**.
2. **Ablations:** gate OFF vs ON; per-mode; Health on/off — show breach-rate ↓
   and survival ↑ from the governance layer, independent of any alpha claim.
3. **Paper-forward:** run FTMO Mode in Binance-paper for a fixed window; confirm
   the account-state numbers reconcile exactly with `accounting.py` and that no
   simulated FTMO breach ever occurs undetected.
4. **Gate before go:** no funded/live FTMO attempt until the harness shows an
   acceptable pass/survival distribution AND an explicit owner decision doc
   (mirror `FINAL_OWNER_DECISION.md` / `LIVE_READY_CHECKLIST.md`).

**Honesty guardrail:** if the harness shows the strategies have **no edge** on
FTMO instruments (the crypto scalp precedent — a documented NO-GO), the roadmap's
correct output is "the governance OS is built and correct, but do not fund until
an edge is validated." Building the OS is valuable regardless; funding without
edge is not.

---

# PART 10 — MIGRATION STRATEGY

1. **Additive & flag-gated.** `FTMO_MODE_ENABLED=false` by default. With it off,
   the system is byte-identical to today (parity test enforces this). Existing
   Binance-paper multi-strategy deployment is unaffected.
2. **New profile, not a mutation.** Add an `ftmo_challenge` / `ftmo_funded`
   `RISK_PROFILE`-style preset rather than editing `aggressive_paper`. Profiles
   remain config-only (they change sizing inputs, never `decide()` logic).
3. **Schema migrations forward-only.** New tables (`ftmo_account_state`,
   `ftmo_day`) created if absent; no existing table altered destructively;
   `storage.py` guards with `CREATE TABLE IF NOT EXISTS`.
4. **Docs updated in lockstep.** Update `PAPER_LIVE_PARITY.md` (why the gate is
   parity-safe), `ARCHITECTURE.md` (the new layer), `RISK_MODEL.md` (worst-case
   projection), and add a `SYSTEM_STATE.md` entry per wave — the repo's rule is
   "if any doc contradicts SYSTEM_STATE, that file wins", so keep it current.
5. **Staged rollout:** Wave 0–1 observe-only (state + health + modes surfaced,
   no gate) → verify numbers reconcile in paper → Wave 2 enable the gate in
   paper → Wave 3 validate via harness → only then consider Wave 4 (MT5 adapter)
   under a fresh owner sign-off.
6. **Rollback:** set `FTMO_MODE_ENABLED=false` — instant, complete revert to
   current behaviour with no data loss (new tables simply go unused).

---

## Appendix A — Direct answers to the task's explicit requirements

| Task requirement | Where addressed |
|---|---|
| Research FTMO from official sources | Part 1 (ftmo.com Trading Objectives / How-it-works + 2026 corroboration) |
| Analyse every module, document behaviour, strengths, weaknesses | Part 2 (§2.2–2.4) |
| FTMO-aware risk engine (remaining daily/max loss, drawdown, floating DD, budget, correlation, exposure, margin, vol, spread, news, session) | `compliance.py` worst-case gate (§3.2.3) + `account_state.py` budgets (§3.2.2) + risk-input modulation (§3.2.4) |
| "If a trade increases violation probability, never execute" | `f_ftmo_compliance` fail-closed gate (§3.2.3, Wave 2) |
| Account Health Score influencing size/leverage/frequency/threshold/quality/max-open | `health.py` (§3.2.4) modulating existing `risk_multiplier` clamp + `max_open_trades` |
| Operating modes: Challenge / Funded / Payout / Recovery / Survival | `modes.py` (§3.2.5) |
| Trade-Necessity AI ("should I trade?", no-trade as valid) | Compliance gate + mode "allow-new-risk" flag + `test_ftmo_no_trade_is_valid.py` (§3.2.3, Part 7) |
| Shadow learner: survival / payout / should-skip / drawdown labels | `shadow.py` extension (Wave 2), stays advisory |
| FTMO dashboard (mode, health, budgets, progress, payout, compliance, confidence, quality, survival, risk state) | `/api/ftmo` + FTMO card (Wave 1–2) |
| Telegram decision explanations | `ftmo_decision` / `ftmo_rule_warning` / `ftmo_mode_change` / `ftmo_health` (Wave 2) |
| Backtest: pass rate, avg DD, survival, payout prob, violations, recovery time, avg health, ELV | FTMO Monte-Carlo harness (Part 6, Wave 3) |
| Roadmap: current review, problems, proposed arch, module changes, file plan, priority, risk, testing, validation, migration | Parts 2–10 |

## Appendix B — Non-negotiables compliance check (`CLAUDE.md`)

- **No real orders by default / never weaken the five-gate lock** — respected;
  Binance `live_orders.py` untouched; FTMO execution is a separate later adapter
  behind its own lock. ✅
- **No secrets in code/git** — FTMO config via `.env` only; `.env.example`
  placeholders. ✅
- **Paper/live parity sacred** — FTMO gate is shared and flag-gated; parity test
  added. ✅
- **Shadow never hard-vetoes** — new labels are advisory only. ✅
- **Keep it simple / no CEO/multi-AI/alpha vetoes** — new vetoes are
  *rule-compliance* only; modes/health only modulate inputs. ✅
- **Don't resurrect scalp** — Phase 1 makes no alpha claim; edge on FTMO
  instruments is an explicit, separately-gated research question. ✅

---

*End of FTMO Mode Phase-1 roadmap. Next action: implement Wave 0 (rules +
calendar + account-state + storage + config), flag-gated OFF, with tests — no
behaviour change.*
