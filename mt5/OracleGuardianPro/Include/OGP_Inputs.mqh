//+------------------------------------------------------------------+
//| OGP_Inputs.mqh - enums and all user inputs                       |
//| Oracle Guardian Pro                                              |
//+------------------------------------------------------------------+
#ifndef OGP_INPUTS_MQH
#define OGP_INPUTS_MQH

enum ENUM_OGP_SYMBOLS
  {
   OGP_SYM_BOTH   = 0, // Gold + Silver
   OGP_SYM_GOLD   = 1, // Gold only
   OGP_SYM_SILVER = 2  // Silver only
  };

enum ENUM_OGP_ENTRY_MODE
  {
   OGP_ENTRY_CONFIRMED = 0, // Confirmed: cross validated on a closed M3 bar
   OGP_ENTRY_LIVE      = 1  // Live: cross detected on live EMA/VWAP
  };

enum ENUM_OGP_VWAP_VOL
  {
   OGP_VOL_AUTO = 0, // Auto (real volume if every checked bar has it)
   OGP_VOL_REAL = 1, // Real volume only
   OGP_VOL_TICK = 2  // Tick volume only
  };

enum ENUM_OGP_DST
  {
   OGP_DST_NONE = 0, // No DST
   OGP_DST_US   = 1, // US DST dates
   OGP_DST_EU   = 2  // EU DST dates
  };

enum ENUM_OGP_ZONE
  {
   OGP_ZONE_NEWYORK = 0, // New York (US DST)
   OGP_ZONE_LONDON  = 1, // London (EU DST)
   OGP_ZONE_TOKYO   = 2, // Tokyo
   OGP_ZONE_UTC     = 3, // UTC
   OGP_ZONE_SERVER  = 4  // Broker server time
  };

enum ENUM_OGP_LOT_MODE
  {
   OGP_LOT_FIXED = 0, // Fixed lots per position (still reduced by safety caps)
   OGP_LOT_RISK  = 1  // % of current equity per signal
  };

enum ENUM_OGP_SECOND
  {
   OGP_2ND_OFF       = 0, // One position per signal
   OGP_2ND_ON_RETEST = 1, // 2nd position on retest of EMA/VWAP zone, shared SL + target
   OGP_2ND_AT_SIGNAL = 2  // 2 positions at signal: #1 at TP1, #2 at final TP (BE after TP1)
  };

enum ENUM_OGP_EMA_EXIT
  {
   OGP_EMAX_OFF       = 0, // No EMA exit (only SL / TP / BE / trailing / safety)
   OGP_EMAX_ALWAYS    = 1, // Close on any M3 close beyond EMA (after min hold)
   OGP_EMAX_AFTER_MFE = 2  // Only once the trade has run >= InpEmaExitMinR in favour
  };

enum ENUM_OGP_VWAP_ANCHOR
  {
   OGP_VWAP_DAILY    = 0, // Once per trading day (TradingView "Session" anchor)
   OGP_VWAP_SESSIONS = 1, // At every enabled session start
   OGP_VWAP_BOTH     = 2  // Daily open + every session start
  };

enum ENUM_OGP_TP_MODE
  {
   OGP_TP_RR        = 0, // Fixed risk:reward (InpTpRR)
   OGP_TP_VWAP_BAND = 1  // VWAP +/- k standard deviations (TradingView band), skip if < min RR
  };

enum ENUM_OGP_SHIELD_MODEL
  {
   OGP_SHIELD_TRAILING = 0, // Trailing: floor = peak equity - 5% of initial (conservative, LIVE default)
   OGP_SHIELD_STATIC   = 1  // Static: floor = initial - 5% (ONLY for strategy research / if Upcomers confirms)
  };

enum ENUM_OGP_SL_STRUCT
  {
   OGP_SLS_SWING       = 0, // Beyond the recent swing high/low
   OGP_SLS_ORDER_BLOCK = 1  // Beyond the last opposite candle before the move (order block); swing fallback
  };

enum ENUM_OGP_PLAN
  {
   OGP_PLAN_TIME_HOLD = 0, // Time hold: cross with H1 trend, stop 2 ATR, NO target, exit after N bars (research winner)
   OGP_PLAN_TARGETS   = 1  // Targets: v1.4x plan (TP/RR, EMA exit, #2/runner, continuation, quality score)
  };

enum ENUM_OGP_NEWS_FAIL
  {
   OGP_NEWS_FAIL_ALLOW = 0, // Calendar unavailable -> allow entries (dashboard warning)
   OGP_NEWS_FAIL_BLOCK = 1  // Calendar unavailable -> block entries
  };

//==================================================================//
input group "=== 1. Oracle account (firm rules - NOT trading risk) ==="
input double   InpInitialBalance        = 25000.0;  // Initial (funded) balance, account currency
input datetime InpCycleStart            = D'2026.10.01 00:00'; // Current payout-cycle start (SERVER time) - update after each payout
input double   InpShieldPct             = 5.0;      // Dynamic Risk Shield %
input double   InpDailyDDPct            = 4.0;      // Daily drawdown % (UTC day)
input double   InpSingleTradePct        = 2.0;      // Single trade loss %
input double   InpValidDayPct           = 0.5;      // Valid trading day realized profit %
input double   InpPayoutPct             = 1.0;      // Payout net profit threshold %
input double   InpBestDayPct            = 20.0;     // Best Day Rule %
input int      InpMinValidDays          = 5;        // Minimum valid trading days
input ENUM_OGP_SHIELD_MODEL InpShieldModel = OGP_SHIELD_TRAILING; // Shield model (keep TRAILING on the real account)
input double   InpManualShieldFloor     = 0.0;      // Shield floor read from Upcomers dashboard (0 = none)
input bool     InpTrustManualFloor      = false;    // Use the manual floor even if LOWER than the EA estimate (only if read from Upcomers today)
input double   InpManualPeakEquity      = 0.0;      // Highest equity read from Upcomers (0 = none)
input double   InpManualDayStartEquity  = 0.0;      // Today's start equity from Upcomers (0 = none)
input datetime InpManualDayStartDate    = D'1970.01.01'; // UTC date the manual day-start value belongs to

input group "=== 2. Internal risk (robot limits, far inside firm rules) ==="
input ENUM_OGP_LOT_MODE InpLotMode     = OGP_LOT_RISK; // Lot mode (RISK: equal $ per R; fixed lots act as MAX)
input double   InpFixedLotGold          = 0.10;     // Fixed lots per position - gold
input double   InpFixedLotSilver        = 0.10;     // Fixed lots per position - silver (silver 0.10 lot ~ 10x gold risk per $!)
input double   InpRiskPct               = 0.50;     // Risk mode: risk per SIGNAL, % of CURRENT equity (split over positions)
input double   InpMaxTotalRiskPct       = 1.00;     // Max combined planned risk of open EA positions, % of initial balance
input double   InpCorrelatedRiskFactor  = 0.50;     // Risk multiplier when other metal is open SAME direction
input bool     InpBlockOppositeMetals   = false;    // Block gold/silver in OPPOSITE directions at the same time
input double   InpDailyLossLockUSD      = 200.0;    // Daily max loss (equity vs UTC day start, incl. open risk)
input double   InpDailyTargetUSD        = 200.0;    // Daily net profit target
input bool     InpStopAtDailyTarget     = true;     // Stop new entries once today's realized net >= target
input int      InpMaxTradesPerDay       = 10;       // Max new EA signals per UTC day
input double   InpMaxSingleTradeLossUSD = 250.0;    // Internal max planned loss per trade (incl. costs)
input double   InpPositionEmergencyUSD  = 350.0;    // Close a position if its floating loss reaches this
input double   InpFloorSafetyUSD        = 300.0;    // Block entries when equity is this close to a firm floor
input double   InpEmergencyBufferUSD    = 120.0;    // Close all EA positions when this close to a firm floor
input double   InpCommissionPerLot      = 7.0;      // Round-turn commission per lot (account ccy) for sizing
input bool     InpBlockIfUnprotected    = true;     // Block entries if ANY account position has no stop-loss

input group "=== 3. Strategy core: Session VWAP (OHLC/4) x EMA (M3) ==="
input ENUM_OGP_PLAN InpTradePlan        = OGP_PLAN_TIME_HOLD; // Trade plan (see README section 18)
input int      InpHoldBars              = 40;       // Time-hold plan: close after N M3 bars (40 = 2 hours)
input double   InpHoldSlAtr             = 2.0;      // Time-hold plan: stop-loss distance in ATR (no take-profit)
input ENUM_OGP_ENTRY_MODE InpEntryMode  = OGP_ENTRY_CONFIRMED; // Entry mode
input int      InpEmaPeriod             = 9;        // EMA period (Close, M3)
input ENUM_OGP_VWAP_VOL InpVwapVolume   = OGP_VOL_AUTO; // VWAP volume source
input ENUM_OGP_VWAP_ANCHOR InpVwapAnchor = OGP_VWAP_DAILY; // VWAP reset (match your TradingView anchor)
input string   InpVwapDailyResetNY      = "18:00";  // Daily VWAP reset time, New York (check where TradingView VWAP restarts)
input bool     InpRequireNewSignal      = true;     // Same-direction re-entry only after an opposite cross
input bool     InpCloseOnOpposite       = true;     // Opposite signal closes open EA positions (after min hold), then may enter
input int      InpMinBarsAfterReset     = 2;        // Ignore crosses in the first N closed bars after a VWAP reset

input group "=== 3b. Two positions per signal ==="
input ENUM_OGP_SECOND InpSecondEntry    = OGP_2ND_ON_RETEST; // Second position mode
input double   InpRetestZoneAtr         = 0.25;     // Retest zone beyond EMA/VWAP, ATR
input bool     InpRetestNeedsClose      = true;     // Retest must be confirmed by an M3 close back on the signal side
input int      InpRetestMaxBars         = 10;       // Retest must happen within N bars after entry #1
input double   InpTp1RR                 = 1.0;      // AT_SIGNAL mode: target of position #1 (R)
input bool     InpBeAfterTp1            = true;     // AT_SIGNAL mode: move #2 to break-even once price reaches TP1

input group "=== 3c. Dynamic risk (only REDUCES risk, never increases it) ==="
input bool     InpUseQualityScore       = true;     // Grade each signal A/B/C and size by grade
input int      InpGradeAMin             = 4;        // Score >= this -> grade A (full risk)
input int      InpGradeBMin             = 2;        // Score >= this -> grade B
input double   InpRiskGradeB            = 0.6;      // Risk multiplier grade B
input double   InpRiskGradeC            = 0.0;      // Risk multiplier grade C (0 = skip C signals)
input int      InpLossStreakN           = 2;        // After N losing trades in a row today...
input double   InpLossStreakFactor      = 0.5;      // ...multiply risk by this
input double   InpProtectAfterUSD       = 100.0;    // Once today's realized net >= this...
input double   InpProtectFactor         = 0.5;      // ...multiply risk by this (protect the day)
input double   InpTaperRangeUSD         = 600.0;    // Risk tapers linearly over this distance above the safety buffer of the nearest floor
input double   InpTaperMinFactor        = 0.25;     // Minimum taper multiplier

input group "=== 3d. Extra entries & runner ==="
input bool     InpUseContinuation       = true;     // Trend-continuation entries: pullback to EMA within an existing EMA/VWAP leg
input double   InpContZoneAtr           = 0.30;     // Pullback must reach EMA +/- this ATR
input int      InpContMinBarsSide       = 5;        // EMA must have been on the same side of VWAP for N closed bars
input int      InpContCooldownBars      = 10;       // Bars since the last entry on the symbol
input int      InpContMaxPerLeg         = 2;        // Max continuation entries per EMA/VWAP leg
input int      InpLossCooldownBars      = 10;       // After a LOSING close: no new entry in the SAME direction on that symbol for N bars (0 = off)
input bool     InpSecondRunner          = true;     // Position #2 is a runner: far target + break-even + ATR trail
input double   InpRunnerRR              = 3.0;      // Runner target (R of position #1)
input double   InpRunnerTrailAtr        = 1.5;      // Runner ATR trailing distance (after +1R)

input group "=== 4. Filters (each independent; untested -> OFF unless safety) ==="
input bool     InpUseTrend              = true;     // Higher-timeframe trend filter (trade only with the trend)
input ENUM_TIMEFRAMES InpTrendTF        = PERIOD_H1; // Trend timeframe
input bool     InpUseTrend2             = false;    // Second trend timeframe must agree too
input ENUM_TIMEFRAMES InpTrendTF2       = PERIOD_M15; // Second trend timeframe
input int      InpTrendEmaPeriod        = 50;       // Trend EMA period
input int      InpTrendSlopeBars        = 3;        // Trend EMA slope lookback (bars)
input bool     InpUseBreakoutFilter     = false;    // Require structure break or strong momentum
input int      InpBreakoutLookback      = 20;       // Swing lookback for breakout (M3 bars)
input double   InpMomentumBodyAtr       = 1.0;      // Momentum bar body >= x * ATR counts as confirmation
input bool     InpBreakoutRetest        = false;    // Require retest of the broken level
input int      InpBreakRetestMaxBars    = 6;        // Max bars between break and retest (breakout filter)
input bool     InpUseFvgFilter          = false;    // Require an unfilled Fair Value Gap in the signal direction
input int      InpFvgLookback           = 10;       // FVG search window (M3 bars)
input double   InpFvgMinAtr             = 0.20;     // Minimum FVG size, ATR
input bool     InpUseChaseFilter        = true;     // Skip if price is too far from VWAP (no chasing)
input double   InpMaxChaseAtr           = 1.0;      // Max distance entry->VWAP in ATR
input bool     InpUsePullbackMode       = false;    // After a skipped (chased) cross, wait for pullback + confirmation
input double   InpPullbackZoneAtr       = 0.30;     // Pullback zone around EMA/VWAP, ATR
input int      InpPullbackMaxBars       = 20;       // Pullback setup expires after N bars

input group "=== 5. ATR / volatility / stops ==="
input int      InpAtrPeriod             = 14;       // ATR period (M3)
input double   InpSlAtrMult             = 1.5;      // ATR stop multiple
input bool     InpUseStructureSL        = true;     // Stop beyond structure if wider than ATR stop
input ENUM_OGP_SL_STRUCT InpSlStructure = OGP_SLS_SWING; // Structure used for the stop
input int      InpSwingLookback         = 10;       // Swing lookback for structural stop (bars)
input double   InpMaxSlAtrMult          = 3.0;      // Skip trade if stop wider than x * ATR
input ENUM_OGP_TP_MODE InpTpMode       = OGP_TP_RR; // Take-profit mode
input double   InpTpRR                  = 1.5;      // RR mode: take-profit risk:reward (0 = no TP)
input double   InpTpBandMult            = 1.0;      // Band mode: target = VWAP +/- k * std dev
input double   InpMinTpRR               = 1.0;      // Band mode: skip trade if target gives less than this RR
input double   InpMaxBarRangeAtr        = 4.0;      // Block if last bar range > x * ATR (spike)
input double   InpMaxSpreadToAtr        = 0.25;     // Block if spread > x * ATR
input double   InpGoldMinAtr            = 0.80;     // Gold: min M3 ATR (price units, USD)
input double   InpGoldMaxAtr            = 12.0;     // Gold: max M3 ATR (price units)
input double   InpGoldMaxSpread         = 0.45;     // Gold: max spread (price units)
input double   InpGoldSlippage          = 0.25;     // Gold: slippage reserve in sizing (price units)
input double   InpGoldSlBuffer          = 0.20;     // Gold: extra buffer beyond swing (price units)
input double   InpSilverMinAtr          = 0.012;    // Silver: min M3 ATR (price units)
input double   InpSilverMaxAtr          = 0.30;     // Silver: max M3 ATR (price units)
input double   InpSilverMaxSpread       = 0.035;    // Silver: max spread (price units)
input double   InpSilverSlippage        = 0.015;    // Silver: slippage reserve in sizing (price units)
input double   InpSilverSlBuffer        = 0.010;    // Silver: extra buffer beyond swing (price units)

input group "=== 6. Position management ==="
input int      InpMinHoldSeconds        = 150;      // Min hold before discretionary exits (Oracle: <2 min = tick scalping)
input ENUM_OGP_EMA_EXIT InpEmaExitMode = OGP_EMAX_AFTER_MFE; // EMA candle-close exit mode
input double   InpEmaExitMinR           = 0.5;      // AFTER_MFE mode: trade must have run this many R in favour first
input bool     InpUseBreakEven          = false;    // Move stop to break-even
input double   InpBreakEvenRR           = 1.0;      // Break-even trigger in R
input bool     InpUseTrailing           = false;    // ATR trailing stop
input double   InpTrailAtrMult          = 1.5;      // Trailing distance in ATR
input int      InpMinModifySeconds      = 30;       // Min seconds between stop modifications per position

input group "=== 7. Trading hours ==="
input bool     InpUseSessionFilter      = true;     // Restrict entries to sessions below
input bool     InpTradeAllDay           = true;     // Trade all day (still rollover/weekend/news/Oracle gates)
input bool     InpS1Enabled             = true;     // Session 1 enabled
input string   InpS1Name                = "NewYork";
input ENUM_OGP_ZONE InpS1Zone           = OGP_ZONE_NEWYORK;
input string   InpS1Start               = "09:30";  // Session 1 start (zone local)
input string   InpS1End                 = "11:30";  // Session 1 end (zone local)
input bool     InpS2Enabled             = false;
input string   InpS2Name                = "London";
input ENUM_OGP_ZONE InpS2Zone           = OGP_ZONE_LONDON;
input string   InpS2Start               = "08:00";
input string   InpS2End                 = "10:30";
input bool     InpS3Enabled             = false;
input string   InpS3Name                = "Custom";
input ENUM_OGP_ZONE InpS3Zone           = OGP_ZONE_NEWYORK;
input string   InpS3Start               = "13:30";
input string   InpS3End                 = "15:00";
input bool     InpBlockRollover         = true;     // Block entries around metals daily rollover
input string   InpRolloverStartNY       = "16:30";  // Rollover block start (New York)
input string   InpRolloverEndNY         = "18:30";  // Rollover block end (New York)
input string   InpFridayNoEntryNY       = "14:00";  // Friday: no new entries after (New York)
input bool     InpCloseBeforeWeekend    = true;     // Friday: close EA positions
input string   InpFridayCloseNY         = "16:15";  // Friday close time (New York)

input group "=== 8. Broker server time ==="
input bool     InpAutoServerOffset      = true;     // Live: detect from TimeTradeServer()-TimeGMT()
input int      InpServerUtcOffsetHours  = 2;        // Broker standard (winter) UTC offset
input ENUM_OGP_DST InpServerDst         = OGP_DST_US; // Broker DST rule (tester + fallback)

input group "=== 9. News protection (MQL5 economic calendar) ==="
input bool     InpUseNewsFilter         = true;     // Block NEW entries around high-impact events
input string   InpNewsCurrencies        = "USD";    // Currencies (comma separated)
input bool     InpNewsHighOnly          = true;     // Only high-importance events (else also moderate)
input int      InpNewsMinutesBefore     = 15;       // Block minutes before event
input int      InpNewsMinutesAfter      = 15;       // Block minutes after event
input ENUM_OGP_NEWS_FAIL InpNewsFail    = OGP_NEWS_FAIL_ALLOW; // If calendar unavailable

input group "=== 10. Instruments & execution ==="
input ENUM_OGP_SYMBOLS InpSymbols       = OGP_SYM_BOTH; // Symbols
input string   InpGoldSymbol            = "XAUUSD";
input string   InpSilverSymbol          = "XAGUSD";
input string   InpSymbolPrefix          = "";
input string   InpSymbolSuffix          = "";
input bool     InpEnableNewEntries      = true;     // Master switch for new entries (management stays on)
input ulong    InpMagic                 = 2507311;  // Magic number (change it - do not share settings)
input int      InpMaxDeviationPoints    = 30;       // Max slippage, points
input int      InpOrderRetries          = 2;        // Retries on requote / price changed
input string   InpOrderComment          = "OGP";

input group "=== 11. Dashboard & logs ==="
input bool     InpShowDashboard         = true;
input int      InpDashX                 = 8;
input int      InpDashY                 = 20;
input int      InpDashFontSize          = 8;
input bool     InpCsvJournal            = true;     // Write MQL5/Files/OGP_journal_<login>.csv
input bool     InpLogEveryBar           = false;    // Log EMA/VWAP/ATR on every new M3 bar

#endif
