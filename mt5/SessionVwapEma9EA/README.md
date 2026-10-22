# SessionVwapEma9EA — M3 Session VWAP / EMA 9 crossover EA (MT5)

> **Experimental strategy test, not a production trading system.**
> Stop-loss and take-profit are **disabled by default**. An open position then has
> no protective order. It stays exposed, with potentially substantial losses, until
> the M3 close-vs-EMA exit fires. If the EA is removed, the terminal stops, or the
> connection drops, the position has no exit at all.

**Compile status:** The source has **not** been compiled or backtested. I tried
MetaEditor 64 under Wine in my build sandbox, but it stopped at start-up with
"A debugger has been found running in your system" (its anti-debug check). I
checked the code by hand against the MQL5 API, but you must compile it yourself
(steps below) and send any compiler errors back.

---

## 1. Files

| File | Purpose |
|---|---|
| `SessionVwapEma9EA.mq5` | Complete EA, one self-contained file. |
| `README.md` | This document. |

**Dependencies:** none. VWAP is calculated inside the EA. EMA uses the built-in
`iMA` handle. No `#include` is needed, not even the standard library.

## 2. Compiling in MetaEditor

1. In MT5: **File → Open Data Folder**, then go to `MQL5\Experts\`.
2. Copy `SessionVwapEma9EA.mq5` there (a sub-folder is fine).
3. Open MetaEditor (F4), open the file, and press **Compile** (F7).
4. The *Errors* tab must show `0 errors`. Warnings do not block compiling. Please send them to me anyway.
5. In the terminal's Navigator, right-click **Expert Advisors → Refresh**.

## 3. Running in the Strategy Tester (M3)

1. **View → Strategy Tester** (Ctrl+R) → *Single* test.
2. Expert: `SessionVwapEma9EA`. Symbol: your gold symbol (e.g. `XAUUSD`).
   **Timeframe: M3.** The EA always calculates on M3 whatever you choose, but
   M3 keeps the visual mode and the chart consistent.
3. **Modelling: "Every tick based on real ticks"** (preferred) or "Every tick".
   *Do not* use "Open prices only" or "1 minute OHLC" with intrabar mode,
   because neither can show a crossover forming inside a bar.
4. Dates: a few weeks at first. Deposit and leverage should match your account.
5. Inputs tab:
   - set `InpSymbolSet` (Gold only is the easiest first test);
   - set the symbol prefix or suffix if your broker uses them;
   - **set `InpServerUtcOffsetHours` and `InpServerDst` to match your broker.**
     The tester cannot detect them automatically (see §6.1);
   - turn `InpShowChartComment` off if you like. The panel is disabled in the tester anyway.
6. Testing gold and silver together is a **multi-symbol test**. The tester
   downloads history for both symbols. Ticks for the second symbol are sampled
   through the EA's 500 ms timer, so its signals can be up to about 0.5 s late
   compared with live.
7. Read the **Journal** tab. Every signal, rejection reason, order, exit and
   deal is logged with the prefix `[SVE9]`.

## 4. Parameters and defaults

### Instruments
| Input | Default | Meaning |
|---|---|---|
| `InpSymbolSet` | Gold and Silver | Gold and Silver / Gold only / Silver only |
| `InpGoldSymbol` | `XAUUSD` | Base name for gold |
| `InpSilverSymbol` | `XAGUSD` | Base name for silver |
| `InpSymbolPrefix` | `""` | Added before the base name |
| `InpSymbolSuffix` | `""` | Added after the base name (e.g. `.r`, `-ECN`, `m`) |

### Indicators (always M3)
| Input | Default | Meaning |
|---|---|---|
| `InpEmaPeriod` | 9 | EMA period (Close price, standard EMA via `iMA`) |
| `InpVwapVolume` | Auto | Auto / Real only / Tick only (see §5.1) |
| `InpAutoVolumeCheckBars` | 200 | Closed M3 bars checked in Auto mode |

### Entry signal
| Input | Default | Meaning |
|---|---|---|
| `InpSignalMode` | Intrabar | Intrabar = live crossover, immediate entry. Bar close = crossover confirmed on a closed M3 bar |
| `InpCrossBufferPoints` | 0 | Dead-band around VWAP. A side only counts once \|EMA−VWAP\| > buffer |
| `InpBaselineResetGapSec` | 180 | If the gap between two ticks is longer than this, the crossover baseline resets, so a cross formed "while blind" is not traded (0 = off) |
| `InpOneEntryPerBar` | true | At most one entry attempt per symbol per M3 bar |
| `InpMaxEntriesPerWindow` | 0 | Maximum entries per symbol per opening window (0 = unlimited) |
| `InpReverseOnOpposite` | false | An opposite signal closes the open position and reverses it |

### Exits
| Input | Default | Meaning |
|---|---|---|
| `InpManageExits` | true | EMA candle-close exits |
| `InpExitCheckOnStart` | true | When the EA starts, check the last closed M3 bar against any open positions |
| `InpExitOnVwapCross` | **false** | Optional extra exit: on a closed bar, EMA is below VWAP (for longs) or above VWAP (for shorts) |
| `InpMaxCloseAttemptsPerBar` | 10 | Close retries before waiting for the next bar |

### Risk and execution
| Input | Default | Meaning |
|---|---|---|
| `InpEnableNewEntries` | true | Master switch for new entries. Exits keep working when it is off |
| `InpLotsGold` / `InpLotsSilver` | 0.01 / 0.01 | Fixed lots, rounded **down** to the volume step and never raised to the minimum |
| `InpMaxPositionsPerSymbol` | 1 | Hedging accounts only. Netting accounts always use 1 |
| `InpUseStopLoss` | **false** | Use a stop-loss |
| `InpStopLossPointsGold` / `Silver` | 1000 / 500 | SL distance in points (used only when enabled) |
| `InpUseTakeProfit` | **false** | Use a take-profit |
| `InpTakeProfitPointsGold` / `Silver` | 2000 / 1000 | TP distance in points (used only when enabled) |
| `InpMaxSpreadPointsGold` / `Silver` | 50 / 50 | No entry if the current spread is wider (points) |
| `InpMaxDeviationPoints` | 30 | Maximum slippage in points |
| `InpMagic` | 930903 | Magic number |
| `InpOrderRetries` | 2 | Retries on requote, price changed or price off |
| `InpOrderComment` | `SVE9` | Order comment |

The default point values are **placeholders**. A "point" depends on the broker:
XAUUSD can have 2 or 3 digits, and XAGUSD usually has 3. Check
`Market Watch → Specification` and the `ready:` line that the EA logs at start-up.

### Broker server time
| Input | Default | Meaning |
|---|---|---|
| `InpAutoServerOffset` | true | Live/demo only: offset = `TimeTradeServer() − TimeGMT()`, rounded to 15 min, refreshed hourly |
| `InpServerUtcOffsetHours` | 2 | Broker **standard (winter)** offset. Used by the tester and as the fallback |
| `InpServerDst` | US | DST rule of the broker server: none / US dates / EU dates |

### Sessions (3 slots)
| Slot | Enabled | Name | Zone | Start (local) | Entry window | Session length |
|---|---|---|---|---|---|---|
| 1 | **true** | NewYork | New York | 09:30 | 30 min | 390 min |
| 2 | false | London | London | 08:00 | 30 min | 510 min |
| 3 | false | Tokyo | Tokyo | 09:00 | 30 min | 360 min |

Zones: New York (UTC−5 with US DST), London (UTC+0 with EU DST), Tokyo (UTC+9),
UTC, and Broker server (no conversion).

### Logging
| Input | Default | Meaning |
|---|---|---|
| `InpLogEveryBar` | true | On each new M3 bar, log closed-bar O/H/L/C, EMA, VWAP and live values |
| `InpLogEveryTick` | false | Live EMA/VWAP on every tick (very verbose) |
| `InpShowChartComment` | true | Status panel (live charts only) |

## 5. How the EA calculates things

### 5.1 VWAP (session-anchored, OHLC/4)

```
typical_i = (Open_i + High_i + Low_i + Close_i) / 4      (M3 bar i)
VWAP      = Σ typical_i · volume_i  /  Σ volume_i
```

- The sum runs over every **M3 bar from the bar that contains the start of the
  most recent configured session** (the *anchor*) up to now.
- **Closed VWAP** uses closed bars only. Exits and bar-close mode use it.
  **Live VWAP** also includes the forming bar with its current O/H/L/C and
  current volume. Intrabar mode uses it, and it changes on every tick.
- **Reset:** when a new session starts, the anchor moves and the sums start
  from zero. If sessions overlap, the session that started most recently sets
  the anchor. Outside sessions, VWAP keeps accumulating from the last session
  start, which only matters for display and the optional VWAP exit.
- **Volume:** in *Auto* mode the EA checks the last 200 closed M3 bars. If
  every one has `real_volume > 0`, it uses real volume. Otherwise it uses
  **tick volume**. Gold and silver are usually OTC CFDs with no real exchange
  volume, so tick volume is the normal result. The choice is logged
  (`VWAP volume source: ...`) and checked again at each session start. If you
  choose *Real only* and the broker supplies none, VWAP is reported as
  **invalid** and the EA does not trade. It never switches source silently.
- MT5 builds bars from **Bid** prices, so EMA and VWAP are Bid-based.
- This is a *bar-based* VWAP: each M3 bar contributes once at its OHLC/4
  price. That follows the specification (OHLC/4). A tick-by-tick VWAP would
  give slightly different values.

### 5.2 EMA 9
`iMA(symbol, PERIOD_M3, 9, 0, MODE_EMA, PRICE_CLOSE)`. Buffer index 0 is the
forming bar (live close). Index 1 and 2 are closed bars. The handle is released
in `OnDeinit`.

### 5.3 Session timing
`server time → UTC → session local time`:

1. Server UTC offset. On live/demo accounts it is measured with
   `TimeTradeServer() − TimeGMT()`, which needs a correct PC clock. In the
   tester, or if detection fails, it comes from `InpServerUtcOffsetHours` plus
   the `InpServerDst` rule.
2. Session local time is UTC plus the zone offset, with DST applied by rule:
   US = 2nd Sunday of March 02:00 to 1st Sunday of November 02:00.
   EU = last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC.
3. The EA finds the most recent **weekday** local start of each session.
   *Entry window* = `start … start + window`. *Session* = `start … start + length`.
4. Example: with the common broker setting UTC+2 / US DST, New York 09:30 is
   16:30 server time all year.

The EA logs `SESSION START`, `entry window CLOSED` and `SESSION END`, all in
server time.

### 5.4 Entry signals

**Intrabar mode (default):**
- On every new tick of the symbol, `side = sign(EMA_live − VWAP_live)`, using
  the optional dead-band.
- The EA keeps the last non-zero side (the *baseline*). A **BUY** happens when
  the side changes from below to above, and a **SELL** when it changes from
  above to below.
- The baseline updates on every tick, including ticks outside entry windows.
  So a crossover that happened outside a window has already been absorbed
  when the window opens, and it is **not** traded later.
- The baseline is reset (the next tick only sets a new baseline and cannot
  signal) on: EA start, a new session anchor (a VWAP reset is not a crossover),
  a gap between ticks longer than `InpBaselineResetGapSec`, a terminal
  reconnect, and indicator data that is not ready.

**Bar-close mode:** on a new M3 bar, the EA compares bar[2] with bar[1] using
closed EMA and closed VWAP. Both bars must be in the current session.

**Acceptance checks.** These run in order, and each rejection is logged with
its reason:
1. New entries are enabled.
2. The tick time is inside an open entry window, and the bar the signal came
   from began inside that window.
3. One entry per bar.
4. Maximum entries per window.
5. Terminal, EA and account allow trading.
6. The symbol's trade mode allows this direction.
7. Spread is no more than the maximum.
8. Position rules: if an opposite position is open, the signal is rejected
   (unless reverse is on). Same-direction positions must be fewer than the
   maximum. On a netting account, a foreign position on the symbol blocks
   entry.
9. Lots are valid against min/step/max and the symbol volume limit.
10. SL/TP distances are greater than the broker's stops level.
11. Free margin is enough (`OrderCalcMargin`).

Execution: `OrderCheck`, then `OrderSend` as a market DEAL with the
configured deviation. The filling mode comes from the symbol (FOK, IOC or
Return). If the broker returns INVALID_FILL, the EA tries the next filling
mode. It retries only on REQUOTE, PRICE_CHANGED and PRICE_OFF. It **never**
retries on TIMEOUT or no-connection, because the order may already have filled
and a retry could duplicate it. Each signal gets one order. The bar is marked
"attempted" whatever the outcome.

### 5.5 Exits
- When a new M3 bar starts (so bar[1] has closed), the EA compares
  `close[1]` with `EMA[1]`:
  BUY closes if `close[1] < EMA[1]`. SELL closes if `close[1] > EMA[1]`.
- A live price crossing EMA inside an unfinished bar never closes a position.
- Only positions opened **before** the current bar are closed. A position
  opened on the first tick of the new bar is not closed by the previous bar's
  exit signal.
- Exits run whether or not an entry window is open, and even when new entries
  are disabled.
- A failed close is retried on later ticks or timer events, up to
  `InpMaxCloseAttemptsPerBar`. The rule is evaluated again on the next bar.
- The optional VWAP exit (`InpExitOnVwapCross`) is off by default.
- `OnTradeTransaction` logs every deal of the EA, with open/close, price,
  profit, commission, swap and reason (EA, SL, TP...).

## 6. Ambiguities in the specification and the choices made

These choices change how the EA actually trades. Please confirm or change them.

1. **"Session start" vs "opening window".** I read each configured session as
   a start time plus an entry window (default 30 min). VWAP resets at the
   session start. The session length (default 390 min for New York) is used
   only for logging. The spec gives no window length, so **30 min is my
   assumption.**
2. **Intrabar crossover against a moving VWAP.** Both lines move inside the
   bar. A live crossover can reverse before the bar closes, which is
   *repainting*, so some intrabar entries will not show up as crossovers on a
   closed-bar chart afterwards. With `InpOneEntryPerBar = true`, back-and-forth
   flips inside one bar give at most one entry. Bar-close mode is available if
   you want confirmed crossovers.
3. **First bars of a session.** Right after the reset, VWAP is the OHLC/4 of
   one or two bars and moves a lot, so EMA/VWAP crossovers are frequent and
   noisy just after the open. That follows from the spec, and I added no
   warm-up filter.
4. **Opposite signal while a position is open.** By default it is rejected and
   the position waits for its EMA exit. Reversal is an option.
5. **Exit on the first bar after entry.** If you enter in the middle of a bar
   and that bar closes on the wrong side of EMA, the position closes at the
   next bar's open. That can be a few minutes after entry, which the spec
   does not rule out.
6. **Exit check on start.** By default, after a restart, the EA checks the
   last closed bar right away. This is a conservative choice.
7. **Weekends.** Sessions whose local day is Saturday or Sunday are skipped.
8. **Spread and lots are set per symbol** because point sizes differ between
   gold and silver.

### 6.1 DST limitations
- DST rules are hard-coded (US and EU). Other rules (Australia and others) are
  not supported. If a broker changes its DST on a different date from the
  rule, sessions can be off by one hour around those dates.
- If the broker offset and the session-zone offset change on different dates
  (US vs EU, mid-March and late October), London and New York sessions can
  move by one hour against server time for 1–3 weeks. The conversion handles
  this when both rules are correct.
- In the **Strategy Tester** the offset cannot be detected, so the manual rule
  is used. **A wrong `InpServerUtcOffsetHours`/`InpServerDst` moves every
  session.** Before relying on a backtest, check the first `SESSION START` log
  lines against a known clock.
- Live auto detection uses `TimeGMT()`, which comes from the PC clock. A wrong
  PC clock gives a wrong offset (rounded to 15 min).

## 7. Basic test plan

**A. Smoke test (compile and start)**
1. It compiles with 0 errors.
2. Attach it to an XAUUSD chart (any timeframe) on a **demo** account. Check
   the log for: session config, broker offset, the `ready:` line for each
   symbol, the volume-source line, and the SL/TP warning.
3. Try a wrong suffix. Init must fail with a "symbol not found" message.

**B. Session timing (tester, XAUUSD, every tick real ticks, 2 weeks around a DST change, e.g. early to mid March)**
1. `SESSION START [NewYork]` must appear at 09:30 New York time converted to
   server time, on every weekday, including the weeks around the change.
2. No `OPEN` order outside the window. Search the log for `REJECTED: outside`
   and make sure those are signals from outside the window.
3. `entry window CLOSED` appears 30 min after the start. Positions opened in
   the window are still closed later by EMA exits.

**C. Signal and execution correctness (visual tester, XAUUSD)**
1. Add an EMA(9, Close) to the M3 chart. For VWAP, compare with the logged
   values (`M3 bar closed ... VWAP=`) or with a session-anchored OHLC/4 VWAP
   indicator, anchored at the same time and with the same volume type.
2. For each `SIGNAL BUY/SELL`, check that the logged EMA and VWAP values are
   on the correct sides and that only one `OPEN` follows.
3. For each `EXIT SIGNAL`, check the closed bar's close against EMA[1]. The
   close happens on the first tick of the next bar.
4. Spread: set the gold max spread to 1 point. Every signal must be rejected
   with a `spread` reason.
5. Lots: set lots to 0.001 when the broker minimum is 0.01. You must get an
   "invalid volume" rejection, not a silent 0.01.

**D. XAGUSD**
Repeat B and C with `InpSymbolSet = Silver only`. Then run gold and silver
together. Check that each symbol keeps its own position limit and that silver
uses its own spread and lot inputs.

**E. Robustness (demo, live feed)**
1. Turn the network off for more than 3 minutes during a window, then turn it
   back on. You should see `DISCONNECTED`, then `RECONNECTED` and a baseline
   reset, and no entry from a crossover that formed during the outage.
2. Restart the EA with a position open. `InpExitCheckOnStart` must evaluate
   the last closed bar.
3. Set `InpEnableNewEntries=false`. Signals must be logged as rejected, and
   exits must still work.

**F. Strategy evaluation (only after A–E pass)**
Use at least 6–12 months of real-tick data for each metal. Take commissions
and swaps into account. Compare intrabar mode with bar-close mode. Look at the
results with and without an SL. Expect high trade frequency and a large share
of noise trades, and judge the results with that in mind.

## 8. Known limitations and execution risks

- **No real compile or backtest has been done by me** (see the top of this file).
- **No SL/TP by default.** Gap risk (weekend, news, rollover) is unlimited
  until the next bar closes. If the EA or terminal stops, nothing manages the
  position.
- **The exit fires only after a candle closes.** On a fast move, the realised
  loss is whatever happened during up to 3 minutes, plus slippage.
- **Intrabar signals repaint** (see §6, item 2). Backtest results depend heavily on
  tick-data quality. Results from "Every tick" (generated ticks) can differ
  sharply from real ticks.
- **Tick volume is not traded volume.** On CFDs, tick-volume VWAP depends on
  the broker, so different brokers give different VWAPs and different signals.
- **Spread and rollover.** Around the daily rollover, metals spreads widen a
  lot. The spread filter blocks entries, but exits do **not** check spread and
  will close at a wide spread.
- **Slippage and requotes.** Market orders can fill worse than the signal
  price, within the deviation, or be rejected. Retries happen only on
  requote/price-changed/price-off.
- **TIMEOUT or no-connection on an entry.** The EA does not resend, so an
  entry can be missed. The next tick's position scan shows whether it filled.
- **Multi-symbol timing.** The non-chart symbol is processed by a 500 ms
  timer. Attaching one EA instance per symbol chart with `Gold only` /
  `Silver only` gives tick-level timing for each symbol. Use the **same magic
  number only if** each instance trades a different symbol.
- **Netting accounts.** At most one position per symbol, and any manual or
  foreign position on the symbol blocks entries. Reversal means a close and
  then a separate open.
- **Unusual session alignment.** If a session start is not on an M3 boundary
  (for example a 30-minute broker offset), the VWAP anchor is rounded down to
  the bar that contains the start.
- **Timezone and DST rules** are hard-coded (see §6.1).
- **No equity guard or daily-loss limit**, because the spec does not include
  one. There is no martingale, grid or lot escalation either.
