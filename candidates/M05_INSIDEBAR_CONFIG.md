# M05 Inside-bar breakout — LOCKED candidate (tester-only)

This is the **first** source-scan candidate whose rules are locked and that has a
runnable tester EA + matching sets. The other shortlisted methods (**M07** Turtle
Soup, **M09** RSI(2)) stay **queued** — no EA yet, rules not locked — so there is
no operator run-task for them.

- **EA:** `mql5/AurvexInsideBarCandidate_m05.mq5` (compile to its own
  `.ex5`, e.g. `Aurvex_insidebar_m05`). Tester-only: `OnInit` returns
  `INIT_FAILED` outside the Strategy Tester.
- **Sets:** `candidates/sets/M05_insidebar_{GER40_cash,JP225_cash,XAUUSD,XAGUSD}.set`
- **Timeframe:** `InsideTF=16385` (PERIOD_H1). **Set the tester `--tf` to match.**
- **Magic:** 880055 (distinct from live and from C1–C4).

## Rules — FROM SOURCE vs [ADAPTATION]

Every rule below is tagged by where it comes from. Source rules are backed by
links that **directly describe the inside-bar breakout**; adaptations are ours
and are **not** claimed to come from the source.

| rule | value | origin |
|---|---|---|
| pattern | inside bar: bar fully inside the prior ("mother") bar's range | **source** — [LuxAlgo](https://www.luxalgo.com/blog/inside-bar-breakouts-tight-risk-big-reward/) |
| entry | break of the **mother** bar high (long) / low (short) | **source** — LuxAlgo |
| entry (variant) | wait up to N bars; optional **close** beyond the level | **source** — [BOIB Pro](https://www.tradingview.com/script/XCcBBQ1t) (`SetupValidBars`, `RequireCloseBeyond`) |
| stop | the **opposite end of the mother bar** | **source** — LuxAlgo |
| take-profit | fixed **1R** (BOIB Pro default; 2R offered) | **source** — BOIB Pro (`TpR`, default 1.0) |
| preferred TF | daily, for cleaner signals | **source** — LuxAlgo (we parameterize `InsideTF`) |
| break buffer | points beyond the mother extreme | **[ADAPTATION]** — source value unspecified → `BreakBufferPts`, default 0 |
| setup→trigger | detect inside bar on the CLOSED bar, trigger on later ticks | **[ADAPTATION]** — same discipline as C3 |
| risk sizing | `RiskPct` of account to the stop distance | **[ADAPTATION]** — baseline risk, as C1–C4 |
| cost gate | skip if R-stop < `CostGateMult`·(spread+commission+slippage) | **[ADAPTATION]** |
| FTMO overlay | weekend/Friday flat, daily & overall loss halt, account-rule daily reset | **[ADAPTATION]** |
| tester clock | tester-safe UTC via `ServerUtcOffset()`; offset re-pinned per period | **[ADAPTATION]** |

**Not invented:** the source gives no "range too wide" skip and no time-stop, so
there is none here (default no filter). The buffer and setup-validity window are
declared adaptations, not source rules.

## How it is measured (same bar as C1–C4)

Same symbols/periods/risk as the current system; DST-correct tester offset per
period; metrics reported **together** — after-cost gain, time-to-target,
drawdown (balance/equity), and account-limit violation rate — with realized cost
(commission+swap) separated from the entry gate cost. Apparent success is
validated on reserved (OOS) periods before it is believed.

> Operator note: this file does **not** authorize a run. It defines the EA and
> sets. When F7 compiles clean (0 errors) and MT5 is verified, M05 can be added
> to a batch exactly like C1–C4; M07/M09 remain queued until their rules are
> locked and their EAs exist.
