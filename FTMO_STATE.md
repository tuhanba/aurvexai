# FTMO_STATE.md — the FTMO pivot, single source of truth

Read this first for anything FTMO. Aurvex has been pivoted from a Binance
crypto-futures engine to an **FTMO trading operating system**: a parity-safe
governance layer, a real-data testing lab, and two validated, low-correlation
edges combined into a portfolio that stays inside FTMO's rules across every
out-of-sample period tested.

Everything is **flag-gated OFF by default** (`FTMO_MODE_ENABLED=false`) — the
standard build is byte-identical (parity test + full suite green, ~1010 tests).

## 1. What was built

**Governance OS** (`src/aurvex/ftmo/`, all parity-safe):
- `rules` / `ftmo_calendar` / `account_state` — FTMO rule math, DST-correct
  CE(S)T daily reset, equity-based daily & overall-loss budgets, high-water.
- `modes` / `health` / `compliance` / `correlation` — Challenge/Funded/Payout/
  Recovery/Survival modes, account Health Score, pre-trade worst-case compliance
  gate, per-correlation-cluster concurrency cap.
- Wired into the SHARED `decide()` + `PortfolioView` + engine + `backtest.py`
  (governance-in-the-loop) + a read-only `/api/ftmo` dashboard route.

**Testing lab**:
- `ftmo/data.py` — forex/metals/indices loader (Yahoo, CSV-cached).
- `ftmo/ftmo_sim.py` + `main.py ftmo-backtest` — Monte-Carlo pass/survival.
- Governance-in-the-loop backtest; `scripts/ftmo_*` for sweeps, deepen, basket,
  walk-forward, edge search, ORB tuning, portfolio.

**Validated strategies** (real engine profiles):
- `STRATEGY_PROFILE=orb` — Opening Range Breakout (metals). `detect_orb`.
- `STRATEGY_PROFILE=pdhl` — Previous-Day High/Low breakout (indices). `detect_pdhl`.
- Both use a stop-entry at the level + session-close exit (executor "SESSION").

## 2. The honest research arc (every step measured)

| direction | result | evidence |
|---|---|---|
| FX intraday mean-reversion | **overfit** — vanished on a bigger sample | `FTMO_FX_SWEEP.md`, `FTMO_DEEPEN.md` |
| Gold trend (daily) | **regime-fragile** — only 2/5 folds (gold rallies) | `FTMO_DEEPEN.md`, `FTMO_WALKFORWARD_GOLD.md` |
| Naive diversified basket | **breaches** — correlated drawdown blows 10% | `FTMO_BASKET.md` |
| Governance-in-the-loop | prevents the hard breach, but not open-DD alone | `FTMO_GOVERNED.md` |
| Bollinger fade (intraday) | **dead** on all instruments | `FTMO_EDGE_SEARCH.md` |
| **Gold ORB** | temporally stable (5/5 folds), passes at gold spread | `FTMO_ORB_SWEEP.md`, `FTMO_ORB_ENGINE.md`, `FTMO_COST_VERDICT.md` |
| **DAX / NAS100 PDHL** | cost-robust (survives 0.06% RT), low DD | `FTMO_EDGE_SEARCH2.md` |
| **Two/three-edge portfolio** | **5/5 OOS folds positive, 0 breaches, passes** | `FTMO_PORTFOLIO.md`, `FTMO_PORTFOLIO_WF.md` |

## 3. The validated result (strongest configuration)

Portfolio = **gold ORB + DAX PDHL + NAS100 PDHL**, one governed account,
correlation cap, risk 0.5%, 2-step challenge:

- Full sample (governed): **+352% / 2.5y at true 0.03% RT**, +216% at 0.06% RT,
  no breach.
- **Walk-forward: positive expectancy in 5/5 out-of-sample folds, 0 breaches,
  passes the +10% challenge in 4/5 folds, per-fold maxDD 5.7–7.9%** (safely
  inside FTMO's 10%).

DAX PDHL is the standout single edge (+113% / maxDD 7%, cost-robust). Silver is
out (its ~0.175% %-spread eats the edge). Gold ORB is execution-sensitive but
survives realistic spreads.

## 4. How to run it

```
# FTMO Monte-Carlo pass/survival on real FX/metals/indices:
python main.py ftmo-backtest --fx

# The validated portfolio + walk-forward:
python scripts/ftmo_portfolio_wf.py

# Paper engine with FTMO governance + the ORB edge (metals):
FTMO_MODE_ENABLED=true STRATEGY_PROFILE=orb ORB_HOURS=1 ORB_TARGET_R=0 python main.py engine
```

Key env: `FTMO_MODE_ENABLED`, `STRATEGY_PROFILE` (`orb`|`pdhl`), `ORB_HOURS`,
`ORB_TARGET_R` (0 = session-close), `PDHL_STOP_ATR`, `FTMO_MAX_CLUSTER`,
`FTMO_ACCOUNT_SIZE`, `FTMO_PATH`, `FTMO_PHASE`.

## 5. Honest caveats — what is NOT yet proven

- **In-sample construction** on ~2–3y of **Yahoo proxy** feeds (GC=F/^GDAXI/^IXIC
  ≠ FTMO's exact CFDs), a **flat cost model**, and **simplified stop-entry fills**.
- The one thing offline research cannot settle is **live breakout stop-entry
  slippage** on a real FTMO account.
- Sessions are UTC-anchored; index cash-session anchoring may improve results.

## 6. The remaining gate (live)

**Paper-forward on a real FTMO demo**, measuring actual per-instrument spreads and
breakout slippage against the edge's cost budget. If live execution holds, this is
a real path to a funded account; if it doesn't, it is an honest NO-GO and the OS +
lab are ready for the next edge. No funded capital before that demo verification.

## 7. Non-negotiables preserved

Paper/live parity (FTMO gate on the shared path, flag-gated), shadow advisory-only,
no secrets, the Binance five-gate live lock untouched, every FTMO veto a
rule-compliance veto (never alpha). See `PAPER_LIVE_PARITY.md`.
