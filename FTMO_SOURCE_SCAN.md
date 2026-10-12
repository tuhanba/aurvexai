# FTMO Source-Scan — publicly described day-trading methods (scan #1)

**Purpose.** Discover candidate edges from how day-trading methods are *actually
described* in public sources — social posts, trader blogs, indicator listings,
strategy write-ups — stated as **condition → entry → stop → exit**, not limited
to the technical names we happened to pick for C1–C4. This is a *scan*, not a
result: nothing here is evidence of profit. It feeds the research pipeline as a
queue of mechanizable hypotheses to be measured on **our** data and costs.

**Discipline (applied to every row).**

- Each method records its **source links**. The machine-readable row is
  `research_out/source_scan_ledger.csv`; `scripts/aurvex_research.py sources`
  validates and reports it.
- **Ads, profit claims and cherry-picked winners are NOT evidence.** Where a
  source gives a win-rate or return, it is recorded as an *uncited claim* and
  carries no weight in selection. (The one "~70% win rate" figure found —
  London breakout — cites no data and is treated as marketing.)
- **Aliases of the same method are merged** into one row (e.g. "false breakout
  fade" / "failed N-bar break" / "stop-run reversal" → one Turtle-Soup row).
- **Vague rules are flagged, not invented.** Where a source leaves a threshold
  undefined (e.g. "range too wide", "shallow pullback", "heavy volume") the row
  says so in `vague_flags`; where a rule is simply absent (e.g. Turtle Soup's
  exit target) it is listed in `missing_rules` and marked as something we must
  **parameterize and test**, never silently fill in.
- Sources are trader blogs, broker docs, forums and TradingView/indicator
  listings — **not rigorous or peer-reviewed**. Specific numbers are examples,
  not validated rules.

---

## Catalog (11 candidates)

Legend — **data**: do we already have it? · **code**: codability ·
**cost**: cost-sensitivity (lower is friendlier to FTMO after-cost).

### M01 — Opening Range Breakout (ORB) · breakout
*aliases: opening range breakout, OR break, ORB, London/NY ORB*
- **Condition:** first N-minute range after the session open; optional skips
  (range too wide) / filters (volume).
- **Entry:** break of range high (long) / low (short) — buy-stop/sell-stop
  beyond the range, or a close outside it.
- **Stop:** opposite side of the range, or the range midpoint.
- **Exit:** prior-day H/L, measured move, VWAP, R-multiple, or session close.
- data **yes** · code **high** · cost **med** · order-book **no**
- *vague:* "range too wide" threshold undefined; volume filter undefined.
- *Not selected:* already covered by our current **C2** session-breakout family.
- src: [prorealcode](https://market.prorealcode.com/product/opening-range-breakout-london-session/),
  [nycservers](https://newyorkcityservers.com/blog/london-breakout-strategy)

### M02 — VWAP pullback / reversion · trend-pullback
*aliases: VWAP bounce, VWAP reclaim, 9EMA+VWAP*
- **Condition:** price trending above/below the session VWAP.
- **Entry:** pull back to VWAP, then resume in the trend direction.
- **Stop:** beyond VWAP or the last swing.
- **Exit:** fixed R-multiple or a VWAP band.
- data **partial** · code **med** · cost **med-high** · order-book **no**
- *vague:* "pullback" depth undefined; which EMA unspecified.
- *missing:* exact entry-trigger candle not defined.
- *Not selected:* needs reliable **session-anchored volume/VWAP** we have not
  validated in the collector.
- src: [luxalgo](https://www.luxalgo.com/library/concept/rsi-2/)

### M03 — Bull flag / ABCD continuation · breakout
*aliases: flag breakout, consolidation break, ABCD*
- **Condition:** a sharp impulse (flagpole), then a shallow consolidation.
- **Entry:** break of the flag high on rising volume.
- **Stop:** below the flag low.
- **Exit:** measured move (flagpole length) or trail.
- data **yes** · code **low-med** · cost **med** · order-book **no**
- *vague:* flag geometry (slope, depth, duration) entirely undefined.
- *missing:* objective consolidation definition.
- *Not selected:* pattern geometry too subjective to code objectively for a
  clean first test.
- src: [luxalgo](https://www.luxalgo.com/library/concept/rsi-2/)

### M04 — Gap-and-go · breakout
*aliases: gap continuation, premarket breakout*
- **Condition:** a catalyst gap + premarket volume.
- **Entry:** break of the premarket / opening-range high after a shallow
  pullback or inside bar.
- **Stop:** under the consolidation.
- **Exit:** R-multiple or trail; invalid if the gap fills.
- data **no** · code **med** · cost **med** · order-book **no**
- *vague:* "shallow pullback" undefined. *missing:* catalyst definition.
- *Not selected:* FX/indices trade ~24h (no classic gap), and we lack reliable
  **catalyst/news tagging**.
- src: [nycservers](https://newyorkcityservers.com/blog/london-breakout-strategy)

### M05 — Inside-bar breakout · breakout  ✅ SELECTED
*aliases: IB breakout, inside day break, NR break*
- **Condition:** an inside bar — its range contained within the prior bar's.
- **Entry:** a stop order just beyond the inside bar's high/low.
- **Stop:** opposite side of the inside bar (or the mother bar).
- **Exit:** fixed R-multiple or trail; a gap straight through invalidates (fall
  back to ORB).
- data **yes** · code **high** · cost **med-high** · order-book **no**
- *vague:* buffer distance beyond the bar is source-specific (parameterize).
- **Why selected:** OHLC-only, fully mechanical, needs **no new data**, and is
  structurally distinct from our ORB/trend families.
- src: [prorealcode](https://market.prorealcode.com/product/opening-range-breakout-london-session/)

### M06 — EMA pullback (20-EMA trend) · trend-pullback
*aliases: moving-average pullback, 20EMA bounce, trend pullback*
- **Condition:** trend — price above a rising 20-EMA (mirror for shorts).
- **Entry:** pull back to the EMA, then break-and-hold / rejection candle.
- **Stop:** beyond the EMA or the last swing.
- **Exit:** 1.5–2R or trail.
- data **yes** · code **high** · cost **med** · order-book **no**
- *vague:* "break-and-hold" confirmation loosely defined.
- *Not selected:* overlaps our current **C3** trend-continuation family.
- src: [tradingview pivot-reversal](https://in.tradingview.com/support/solutions/43000594526-pivot-reversal-strategy/)

### M07 — Turtle Soup false-break · mean-reversion  ✅ SELECTED
*aliases: false breakout fade, failed N-bar break, stop-run reversal (Raschke)*
- **Condition:** price prints a new N-bar extreme, then closes back inside the
  range.
- **Entry:** on the reversal back inside the prior extreme.
- **Stop:** just beyond the false-break extreme.
- **Exit:** external target (R-multiple or prior swing) — **the original rules
  give no fixed number** (flagged below).
- data **yes** · code **med** · cost **med** · order-book **no**
- *vague:* N-bar lookback is source-specific.
- *missing:* **exit target not specified in sources** — must be parameterized
  and tested, not invented.
- **Why selected:** OHLC-only mechanical mean-reversion, distinct from C4's
  Bollinger-band fade, and the missing exit is cleanly parameterizable.
- src: [luxalgo](https://www.luxalgo.com/library/concept/rsi-2/)

### M08 — London session breakout · breakout
*aliases: London breakout, Asian-range break, Tokyo-range break*
- **Condition:** define the Asian/Tokyo session range.
- **Entry:** buy-stop/sell-stop a few pips beyond the range, or a close outside.
- **Stop:** opposite side of the range, the box midpoint, or a fixed 0.75–1.0%.
- **Exit:** R-multiple + trail, or a time-exit at the London–NY overlap close;
  cancel unfilled orders by a cutoff; OCO on the two sides.
- data **yes** · code **high** · cost **med** · order-book **no**
- *uncited claim:* one source asserts ~70% win rate with **no data** → ignored.
- *vague:* buffer pips (3–5) and "wide range skip" (>60 pips EURUSD) are
  source-specific.
- *Not selected (reserve):* a session-breakout cousin of **C2**; kept in reserve
  to avoid duplicating ORB in the first test batch.
- src: [stocksharp](https://doc.stocksharp.com/en/api-examples/0989_London_BreakOut_Classic),
  [luxalgo](https://www.luxalgo.com/library/indicator/1ak2SxuB-london-breakout-session-gbp-usd-forex-daytrade/)

### M09 — RSI(2) mean reversion (Connors) · mean-reversion  ✅ SELECTED
*aliases: RSI-2, RSI2P, Connors pullback*
- **Condition:** long-only when price is above its 200-period SMA (mirror short
  below; short disabled by default in most write-ups).
- **Entry:** RSI(2) closes below ~10 (or 5 for stricter selection).
- **Stop:** base rules carry **no hard price stop** — the trade is structural
  (held to the snapback). Flagged below as an FTMO risk.
- **Exit:** close above the 5-period SMA (or RSI(2) > 65); optional time-exit
  after N bars.
- data **yes** · code **high** · cost **low-med** · order-book **no**
- *vague:* exact thresholds vary by source.
- *missing / risk:* **no hard stop → losses are structurally large**, which is a
  direct FTMO daily-loss hazard — exactly what the limit-violation metric must
  capture. We will test **with** an added protective stop and record it as a
  deviation from the published rule.
- **Why selected:** fully mechanical, low trade count (cost-friendly), and its
  daily-loss exposure is precisely what our metrics are built to measure.
- src: [luxalgo](https://www.luxalgo.com/library/concept/rsi-2/),
  [stocksharp](https://doc.stocksharp.com/en/designer-gallery/Larry_Connors_Rsi2),
  [backtrex](https://backtrex.com/en/backtests/connors-rsi-2-nasdaq-100)

### M10 — Pivot-point bounce · mean-reversion
*aliases: pivot bounce, floor-trader pivots, S/R pivot reversal*
- **Condition:** daily pivots from the prior H/L/C; price interacts with a level.
- **Entry:** bounce off the pivot (buy near PP in an uptrend); Carter's variant:
  penetrate a pivot and move ¼ of the way to the next level on heavy volume.
- **Stop:** a few pips beyond the pivot, or below S1 for room.
- **Exit:** the next pivot (S2/R2); no new entries after 15:30 ET; stop for the
  day after two losers in a row.
- data **yes** · code **med** · cost **med** · order-book **no**
- *vague:* "bounce" confirmation and "heavy volume" undefined.
- *Not selected:* bounce confirmation too fuzzy for a clean first test.
- src: [tradingview](https://in.tradingview.com/support/solutions/43000594526-pivot-reversal-strategy/),
  [carter pivots](https://kr.tradingview.com/script/9Ou1vo51-John-Carter-Pivot-Points)

### M11 — Liquidity sweep / stop-run · mean-reversion  ⚠ DATA WE LACK
*aliases: stop hunt, liquidity grab, order-block sweep, ICT liquidity*
- **Condition:** price sweeps a prior high/low (runs resting stops), then reverses.
- **Entry:** after the sweep + a displacement back inside.
- **Stop:** beyond the sweep extreme.
- **Exit:** the opposing liquidity pool, or an R-multiple.
- data **no** · code **low** · cost **high** · **order-book: YES (required)**
- *vague:* "displacement" and "liquidity pool" are qualitative.
- *missing / data gap:* the true order-flow version needs **Level-2 order-book
  depth**, which our collector does **not** capture (ticks + deals only). A
  price-only proxy (false break of a swing extreme) collapses into **M07**, so
  the distinct order-flow edge is **not testable with our data**.
- src: [forum](https://forums.bearbulltraders.com/tags/pivot%20points/)

---

## First test selection (3) — rationale

Selection criteria, in order: **data we already have** → **objective
codability** → **cost-sensitivity** (favouring methods that survive FTMO
after-cost), with a spread across edge types so we don't just re-test C1–C4's
breakout/trend bias.

| pick | method | type | why |
|---|---|---|---|
| **M05** | Inside-bar breakout | breakout | OHLC-only, fully mechanical, zero new data; distinct from ORB. |
| **M07** | Turtle Soup false-break | mean-reversion | OHLC-only mechanical fade; distinct from C4; missing exit is parameterizable. |
| **M09** | RSI(2) (Connors) | mean-reversion (HTF) | Fully mechanical, cost-friendly; its structural-loss / daily-limit risk is exactly what our metrics measure. |

All three are **OHLC-only** (data in hand), **fully mechanical** (no subjective
pattern reading), and together span breakout + two flavours of mean-reversion.

**Flagged as needing data we lack:** **M11** (order-book depth), plus **M04**
(reliable catalyst/news + premarket gaps) and **M02** (validated
session-anchored VWAP volume). These are parked until the data exists; they are
not coded on proxies that quietly change the method.

## How the selected methods are compared (same bar as C1–C4)

Identical to the candidate plan — **no special treatment**:
- **Same risk** (baseline `RiskPct`), **same symbols/periods** as the current
  system, DST-correct tester offset per period, weekend-flat, FTMO daily/overall
  halts, cost gate on entry.
- **Metrics reported together:** after-cost gain, **time-to-target**, drawdown
  (balance/equity), and **account-limit violation rate** (how often a
  daily/overall limit would be breached) — never after-cost gain alone.
- **Realized cost (commission+swap) is reported separately from the entry gate
  cost**, same as the C1–C4 analyzer.
- Any apparently-successful method is **validated on reserved (OOS) periods**
  before it is believed; the ledger's `status`/`decision` track this, and the
  edge-hypothesis ledger (`research_out/hypotheses_ledger.csv`) records what was
  tried.

## Pipeline wiring

The scan is part of the research pipeline, not a one-off doc:
- **Ledger:** `research_out/source_scan_ledger.csv` (one row per method, with
  source links, data/code/cost ratings, vague/missing-rule flags, selection).
- **CLI:** `python scripts/aurvex_research.py sources --ledger
  research_out/source_scan_ledger.csv` validates the ledger (every row has a
  source; no "selected" method relies on data we lack or on unflagged missing
  rules) and prints the catalog + selection summary. It exits non-zero on a
  contradiction (e.g. a selected method flagged order-book-dependent).
- **Tried-methods record:** the `status`/`decision` columns are updated as each
  method is tested/validated, so re-tests are never silently repeated.

> Scope note: this scan only **queues** mechanizable hypotheses. It creates no
> new candidate EA and does not touch the live EA or live sets. Measurement of
> M05/M07/M09 on real data is an operator-run step (separate tester terminal),
> reported afterwards with the metrics above.
