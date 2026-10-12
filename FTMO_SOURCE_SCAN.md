# FTMO Source-Scan — publicly described day-trading methods (scan #1)

**Purpose.** Discover candidate edges from how day-trading methods are *actually
described* in public sources — trader blogs, indicator listings, strategy
write-ups — stated as **condition → entry → stop → exit**, not limited to the
names we picked for C1–C4. This is a *scan*, not a result: nothing here is
evidence of profit. It feeds the research pipeline as a queue of mechanizable
hypotheses to be measured on **our** data and costs.

## Discipline (enforced by `aurvex_research.py sources`)

- **Each rule is backed by a source that *directly describes that rule*.** Where
  a method's entry/stop/exit could **not** be tied to a directly-supporting
  source in this scan, the row is left **UNKNOWN** — the rules are blanked, not
  guessed. (6 of 11 are source-verified; 5 are UNKNOWN.)
- **`from_source` and `our_adaptation` are separate columns.** What the source
  says is kept apart from the FTMO/engine mechanics we add (risk sizing, cost
  gate, weekend-flat, daily/overall halt, tester clock, closed-bar+tick trigger).
  Our additions are never presented as if they came from the source.
- **Ads, profit claims and cherry-picked winners are NOT evidence.** The one
  "~70%" figure (London breakout) cites no data → treated as marketing.
- **Aliases of the same method are merged** into one row.
- **Vague rules are flagged; missing rules are parameterized + tested, never
  invented.** (E.g. Turtle Soup's exit target, RSI(2)'s absent stop.)

Sources are blogs, broker docs, forums and indicator listings — **not rigorous
or peer-reviewed**. Specific numbers are examples, not validated rules.

The machine-readable ledger is `research_out/source_scan_ledger.csv`.

---

## Status of this scan

| | |
|---|---|
| candidates catalogued | **11** |
| source-verified (rules directly sourced) | **6** — M01, M05, M07, M08, M09, M10 |
| UNKNOWN (no directly-supporting source yet) | **5** — M02, M03, M04, M06, M11 |
| shortlisted for first test | **3** — M05, M07, M09 |
| **LOCKED** (rules fixed, EA + sets exist) | **1** — **M05** |
| queued (shortlisted, no EA yet) | M07, M09 |
| parked — data we lack | M11 (order book), M04 (catalyst/news), M02 (VWAP volume) |

**No operator run-task is issued.** Only M05 has a runnable tester EA
(`mql5/AurvexInsideBarCandidate_m05.mq5`) + matching sets; M07 and M09 stay
**queued** until their rules are locked and their EAs are built.

---

## Source-verified methods

For each: **condition / entry / stop / exit** are the source rules; the
**[ADAPTATION]** line is what we add (not from the source).

### M05 — Inside-bar breakout · breakout · ✅ SELECTED + 🔒 LOCKED
*aliases: IB breakout, inside day break, NR break*
- **Condition (source):** an inside bar — its whole range inside the prior
  ("mother") bar's range.
- **Entry (source):** break of the **mother** bar high (long) / low (short);
  BOIB Pro waits up to N bars and optionally wants a **close** beyond.
- **Stop (source):** the **opposite end of the mother bar**.
- **Exit (source):** fixed R target — 1R default (2R offered).
- **[ADAPTATION]:** closed-bar setup + tick trigger; `BreakBufferPts` (source
  value unspecified → default 0); `SetupValidBars` expiry; `RiskPct` sizing;
  cost gate; FTMO weekend-flat + daily/overall halt + account-rule reset; tester
  UTC clock; `InsideTF` parameterized (not forced daily). *Not invented:* the
  source gives no "range too wide" skip and no time-stop, so there is none.
- data **yes** · code **high** · cost **med-high** · order-book **no**
- **Locked:** `mql5/AurvexInsideBarCandidate_m05.mq5` +
  `candidates/sets/M05_insidebar_*.set` + `candidates/M05_INSIDEBAR_CONFIG.md`.
- src: [LuxAlgo](https://www.luxalgo.com/blog/inside-bar-breakouts-tight-risk-big-reward/),
  [BOIB Pro](https://www.tradingview.com/script/XCcBBQ1t)

### M07 — Turtle Soup false-break · mean-reversion · ✅ SELECTED (queued)
*aliases: false breakout fade, failed N-bar break, stop-run reversal (Raschke, Street Smarts)*
- **Condition (source):** a fresh 20-day extreme with the prior 20-day extreme
  **≥4 sessions old**, then a reversal.
- **Entry (source):** buy-stop ~5–10 ticks back above the prior 20-day low
  (mirror at 20-day highs) — a fade of the failed breakdown.
- **Stop (source):** just beyond the sweep extreme (or ~1 tick beyond the day
  extreme).
- **Exit (source):** the opposite side of the range; abandon if price closes
  back beyond the reclaimed level.
- **[ADAPTATION]:** closed-bar+tick trigger; R-based target where the source
  gives a range-target; lookback/offset parameterized; FTMO overlay.
- **Missing rule (flagged):** exact R target not fixed in the source →
  parameterized + tested, not invented.
- data **yes** · code **med** · cost **med** · order-book **no**
- **Queued:** no EA yet.
- src: [LuxAlgo library](https://www.luxalgo.com/library/concept/turtle-soup.md),
  [TradingView script](https://www.tradingview.com/script/28gN99Tw-Turtle-Soup-Indicator),
  [turtletrader](https://www.turtletrader.com/trader-raschke/)

### M09 — RSI(2) mean reversion (Connors) · mean-reversion · ✅ SELECTED (queued)
*aliases: RSI-2, RSI2P, Connors pullback*
- **Condition (source):** long-only above the 200-SMA (mirror short below;
  short disabled by default).
- **Entry (source):** RSI(2) closes below ~10 (5 for stricter selection).
- **Stop (source):** **NONE** — the base rules carry no hard price stop; the
  trade is structural (held to the snapback).
- **Exit (source):** close above the 5-SMA (or RSI(2) > 65); optional time-exit.
- **[ADAPTATION]:** we **add a parameterized protective stop** — an explicit
  deviation from the no-stop base rule, to bound FTMO daily loss — plus the FTMO
  overlay and weekend-flat.
- **Missing rule / risk (flagged):** no hard stop in the base rule → losses
  structurally large; the added stop is what the limit-violation metric measures.
- data **yes** · code **high** · cost **low-med** · order-book **no**
- **Queued:** no EA yet.
- src: [LuxAlgo RSI-2](https://www.luxalgo.com/library/concept/rsi-2/),
  [backtrex](https://backtrex.com/en/backtests/connors-rsi-2-nasdaq-100)

### M01 — Opening Range Breakout · breakout
*aliases: opening range breakout, OR break, ORB, London/NY ORB*
- **Condition (source):** first N-min range after the open (optional skip if too
  wide / volume filter). **Entry:** break of range high/low (stop or
  close-outside). **Stop:** opposite side / midpoint. **Exit:** prior-day H/L,
  measured move, VWAP, R-multiple, or session close.
- **[ADAPTATION]:** FTMO overlay; closed-bar+tick; DST-pinned offset.
- *Not selected:* already covered by the current **C2** session-breakout family.
- src: [prorealcode](https://market.prorealcode.com/product/opening-range-breakout-london-session/),
  [nycservers](https://newyorkcityservers.com/blog/london-breakout-strategy)

### M08 — London session breakout · breakout
*aliases: London breakout, Asian-range break, Tokyo-range break*
- **Condition (source):** define the Asian/Tokyo range. **Entry:**
  buy-stop/sell-stop a few pips beyond (or close outside). **Stop:** opposite
  side / box midpoint / fixed 0.75–1.0%. **Exit:** R + trail, or time-exit at
  the London–NY overlap close; cancel unfilled by a cutoff; OCO.
- **[ADAPTATION]:** FTMO overlay; DST-pinned session hour.
- *uncited claim:* one source asserts ~70% win rate with no data → ignored.
- *Not selected (reserve):* a session-breakout cousin of **C2**.
- src: [StockSharp](https://doc.stocksharp.com/en/api-examples/0989_London_BreakOut_Classic),
  [LuxAlgo](https://www.luxalgo.com/library/indicator/1ak2SxuB-london-breakout-session-gbp-usd-forex-daytrade/)

### M10 — Pivot-point bounce · mean-reversion
*aliases: pivot bounce, floor-trader pivots, S/R pivot reversal*
- **Condition (source):** daily pivots from prior H/L/C. **Entry:** bounce off a
  pivot (buy near PP in an uptrend); Carter: penetrate + move ¼ to the next
  level on heavy volume. **Stop:** a few pips beyond the pivot, or below S1.
  **Exit:** the next pivot (S2/R2); no new entries after 15:30 ET; stop for the
  day after two losers.
- **[ADAPTATION]:** FTMO overlay.
- *Not selected:* "bounce" confirmation and "heavy volume" too fuzzy for a clean
  first test.
- src: [TradingView pivot-reversal](https://in.tradingview.com/support/solutions/43000594526-pivot-reversal-strategy/),
  [Carter pivots](https://kr.tradingview.com/script/9Ou1vo51-John-Carter-Pivot-Points)

---

## UNKNOWN — no directly-supporting source verified in scan #1

These rows are leads, not rules. Their condition/entry/stop/exit are left
**UNKNOWN** because this scan did not find a source that directly describes the
specific rules; they are **not** guessed. Each returns to the queue only once a
directly-supporting source is attached.

- **M02 — VWAP pullback / reversion** (trend-pullback). Also needs
  session-anchored VWAP volume we have not validated. → `needs-source` /
  `parked-unverified`.
- **M03 — Bull flag / ABCD continuation** (breakout). Pattern geometry
  inherently subjective. → `needs-source`.
- **M04 — Gap-and-go** (breakout). FX/indices trade ~24h (no classic gap); we
  lack catalyst/news tagging. → `needs-source` / `parked-needs-data`.
- **M06 — EMA pullback (20-EMA trend)** (trend-pullback). Overlaps current **C3**;
  left UNKNOWN until sourced. → `needs-source`.
- **M11 — Liquidity sweep / stop-run** (mean-reversion). **DATA WE LACK:** the
  true order-flow version needs **Level-2 order-book depth**, which our collector
  does not capture (ticks + deals only). A price-only proxy collapses into M07.
  → `needs-source` / `parked-needs-orderbook`.

---

## First test — what is and is NOT authorized

- **Locked (M05):** rules fixed, EA + sets delivered. It can be added to a batch
  exactly like C1–C4 **after** F7 compiles clean (0 errors) and MT5 is verified.
  That compile/verify is an operator step; this doc does not run it.
- **Queued (M07, M09):** shortlisted and source-verified, but **no EA yet** —
  rules to be locked next, one at a time, same as M05.
- **UNKNOWN / parked (M02–M04, M06, M11):** not testable until a direct source
  (or, for M11/M04/M02, the missing data) exists.

## How a locked method is measured (same bar as C1–C4)

Same symbols/periods/risk as the current system; DST-correct tester offset per
period; metrics reported **together** — after-cost gain, time-to-target,
drawdown (balance/equity), and account-limit violation rate — with realized cost
(commission+swap) separated from the entry gate cost. Apparent success is
validated on reserved (OOS) periods before it is believed. The ledger's
`status`/`decision` columns record what was tried, so re-tests are not repeated.

## Pipeline wiring

- **Ledger:** `research_out/source_scan_ledger.csv` (adds `source_verified`,
  `from_source`, `our_adaptation`, `locked`, `status`, `decision`).
- **CLI:** `python scripts/aurvex_research.py sources` validates the ledger
  (verified rows have a direct source and real rules; unverified rows keep rules
  UNKNOWN; a selected method must be verified and not depend on data we lack) and
  prints the catalog + locked/queued/UNKNOWN split; exits non-zero on a
  contradiction or a fabricated rule.
- No new candidate EA beyond M05; the **live EA and live sets are untouched**.
