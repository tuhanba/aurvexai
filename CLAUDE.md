# CLAUDE.md — context for Claude Code

This file orients an AI coding assistant working in this repository. Read it
before making changes.

## What this is

AurvexAI is a **clean-core crypto-futures scalp engine** (Binance USDT-M perps).
It is deliberately simple: one decision brain, explicit risk, paper/live parity,
observe-first shadow learning, funnel observability, a basic Flask dashboard and
Telegram alerts. It is the from-scratch replacement for an older, over-complex
engine; do **not** reintroduce that complexity (see "Non-negotiables").

## Non-negotiables (safety)

1. **No real orders by default.** Since the owner-authorized Stage-3 wave
   (2026-07-03) a real order path exists in `live_orders.py`, but it is
   disarmed unless the FULL five-gate lock is open: `LIVE_ENABLED=true` +
   `LIVE_HUMAN_CONFIRM` token + engine mode `live` (Telegram confirm +
   restart) + `LIVE_SEND_ORDERS=true` + API keys. Every default keeps it
   disarmed; `LiveExecutor._send_order()` without an armed adapter is still
   the SIMULATED stub. Never weaken a gate, never default any of them on,
   and never add a second code path that can reach an exchange.
2. **No secrets in code or git.** Binance keys and the Telegram token live only
   in `.env` (gitignored). `.env.example` holds placeholders. Never commit `.env`
   or a real key.
3. **Paper/live parity is sacred.** `DecisionEngine.decide()` must stay
   mode-agnostic. Paper, live and backtest share the same decision, threshold and
   risk model. Only the executor differs. See `PAPER_LIVE_PARITY.md`.
4. **Shadow learner never hard-vetoes.** It is advisory/observe-first only.
5. **Keep it simple.** No Friday/CEO layer, no multi-AI consensus, no
   macro/news/sentiment/regime/ML/Ghost/reputation hard vetoes, no Optuna
   auto-apply. These were intentionally removed.

## Architecture (one line)

`market data → scanner → Buğra setups [PRIMARY GATE] → safety filters → risk gate
→ DecisionEngine → PaperExecutor → journal/shadow/funnel → SQLite → dashboard/telegram`

The **Buğra 5-condition signal is the primary entry gate**; the safety filters
and risk gate decide if a candidate is executable. **Score/Shadow are a SUPPORT
layer, never a veto** — they (a) rank executable candidates for the limited slots
and (b) modulate risk/leverage/margin within the hard caps, both in the *measured*
edge direction only. The old "score < threshold → reject" veto is OFF by default
(`SCORE_AS_GATE=false`); risk modulation is OFF by default (`RISK_MODULATION_ENABLED=false`).

Full detail: `ARCHITECTURE.md`. Strategy detail: `SCALP_STRATEGY_SPEC.md`.
Risk detail: `RISK_MODEL.md`.

## Layout

- `src/aurvex/` — all engine code (config, models, indicators, market_data,
  scanner, setups, scoring, filters, risk, decision, executors, storage,
  metrics, journal, funnel, shadow, telegram, backtest, engine, dashboard/).
- `main.py` — CLI: `engine | dashboard | demo | backtest`.
- `tests/` — pytest suite (must stay green).

## Run

- Tests: `pytest`
- Offline demo (no network/keys): `python main.py demo`
- Offline backtest: `python main.py backtest`
- Paper engine (Binance public data, no key): `python main.py engine`
- Dashboard (port 5000): `python main.py dashboard`
- Docker: `docker compose up -d --build`

## Config

Everything is env-driven via `.env` (see `.env.example`). The active paper
defaults come from `RISK_PROFILE` (default `aggressive_paper`): balance 200 USDT,
risk 2%/trade (band 1–3%), max 4 open, daily-loss kill switch 10%, trade
threshold 60, LTF 1m / HTF 15m, `DATA_PROVIDER=ccxt`, `AX_MODE=paper`,
`LIVE_ENABLED=false`. The legacy 1000 / 0.5% / 3% values are preserved as
`RISK_PROFILE=conservative_paper`. An explicit env var always overrides its
profile default. Profiles are config-only — they change sizing inputs, never
`decide()`'s allow/reject logic.

## Definition of done for any change

1. `pytest` is green (48+ tests).
2. Parity tests still pass (decision unchanged across executors).
3. No secrets added; `.env` not committed.
4. If you touched the decision path, update `PAPER_LIVE_PARITY.md` reasoning.
5. Offline `python main.py demo` still completes end-to-end.

## Operational note (Termius / mobile)

When giving shell commands for the server, list them **one per line**. Do not
chain with `&&` (Termius mobile paste breaks on chained commands).

## Current status

Paper-ready, running the `aggressive_paper` profile (200 USDT / 2% / 10%) on a
fresh epoch with label-only quality grading and read-only governor reporting.
Live OFF by design. See `INITIAL_BUILD_REPORT.md` for the readiness report and
the exact conditions required before any live consideration, and
`GOVERNOR_QUALITY_OBSERVABILITY_REPORT.md` for the aggressive-paper rollout.
