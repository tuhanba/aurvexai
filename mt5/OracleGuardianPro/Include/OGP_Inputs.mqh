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
input double   InpManualShieldFloor     = 0.0;      // Shield floor read from Upcomers dashboard (0 = none)
input double   InpManualPeakEquity      = 0.0;      // Highest equity read from Upcomers (0 = none)
input double   InpManualDayStartEquity  = 0.0;      // Today's start equity from Upcomers (0 = none)
input datetime InpManualDayStartDate    = D'1970.01.01'; // UTC date the manual day-start value belongs to

input group "=== 2. Internal risk (robot limits, far inside firm rules) ==="
input double   InpRiskPct               = 0.25;     // Risk per trade, % of CURRENT equity
input double   InpMaxTotalRiskPct       = 0.50;     // Max combined planned risk, % of initial balance
input double   InpCorrelatedRiskFactor  = 0.50;     // Risk multiplier when other metal is open SAME direction
input bool     InpBlockOppositeMetals   = false;    // Block gold/silver in OPPOSITE directions at the same time
input double   InpDailyLossLockUSD      = 250.0;    // Internal daily loss lock (equity vs day start)
input double   InpDailyTargetUSD        = 200.0;    // Daily net profit target
input bool     InpStopAtDailyTarget     = true;     // Stop new entries once today's realized net >= target
input int      InpMaxTradesPerDay       = 4;        // Max new EA trades per UTC day
input double   InpMaxSingleTradeLossUSD = 250.0;    // Internal max planned loss per trade (incl. costs)
input double   InpPositionEmergencyUSD  = 350.0;    // Close a position if its floating loss reaches this
input double   InpFloorSafetyUSD        = 300.0;    // Block entries when equity is this close to a firm floor
input double   InpEmergencyBufferUSD    = 120.0;    // Close all EA positions when this close to a firm floor
input double   InpCommissionPerLot      = 7.0;      // Round-turn commission per lot (account ccy) for sizing
input bool     InpBlockIfUnprotected    = true;     // Block entries if ANY account position has no stop-loss

input group "=== 3. Strategy core: Session VWAP (OHLC/4) x EMA (M3) ==="
input ENUM_OGP_ENTRY_MODE InpEntryMode  = OGP_ENTRY_CONFIRMED; // Entry mode
input int      InpEmaPeriod             = 9;        // EMA period (Close, M3)
input ENUM_OGP_VWAP_VOL InpVwapVolume   = OGP_VOL_AUTO; // VWAP volume source
input bool     InpVwapDailyReset        = true;     // Also reset VWAP at metals daily open (18:00 New York)
input bool     InpRequireNewSignal      = true;     // Same-direction re-entry only after an opposite cross
input int      InpMinBarsAfterReset     = 2;        // Ignore crosses in the first N closed bars after a VWAP reset

input group "=== 4. Filters (each independent; untested -> OFF unless safety) ==="
input bool     InpUseTrendM15           = false;    // M15 EMA trend filter
input bool     InpUseTrendH1            = false;    // H1 EMA trend filter
input int      InpTrendEmaPeriod        = 50;       // Trend EMA period
input int      InpTrendSlopeBars        = 3;        // Trend EMA slope lookback (bars)
input bool     InpUseBreakoutFilter     = false;    // Require structure break or strong momentum
input int      InpBreakoutLookback      = 20;       // Swing lookback for breakout (M3 bars)
input double   InpMomentumBodyAtr       = 1.0;      // Momentum bar body >= x * ATR counts as confirmation
input bool     InpBreakoutRetest        = false;    // Require retest of the broken level
input int      InpRetestMaxBars         = 6;        // Max bars between break and retest
input bool     InpUseChaseFilter        = true;     // Skip if price is too far from VWAP (no chasing)
input double   InpMaxChaseAtr           = 1.0;      // Max distance entry->VWAP in ATR
input bool     InpUsePullbackMode       = false;    // After a skipped (chased) cross, wait for pullback + confirmation
input double   InpPullbackZoneAtr       = 0.30;     // Pullback zone around EMA/VWAP, ATR
input int      InpPullbackMaxBars       = 20;       // Pullback setup expires after N bars

input group "=== 5. ATR / volatility / stops ==="
input int      InpAtrPeriod             = 14;       // ATR period (M3)
input double   InpSlAtrMult             = 1.5;      // ATR stop multiple
input bool     InpUseStructureSL        = true;     // Stop beyond recent swing if wider than ATR stop
input int      InpSwingLookback         = 10;       // Swing lookback for structural stop (bars)
input double   InpMaxSlAtrMult          = 3.0;      // Skip trade if stop wider than x * ATR
input double   InpTpRR                  = 1.5;      // Take-profit risk:reward (0 = no TP)
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
input bool     InpUseEmaExit            = true;     // Close on M3 close beyond EMA (after min hold)
input bool     InpUseBreakEven          = false;    // Move stop to break-even
input double   InpBreakEvenRR           = 1.0;      // Break-even trigger in R
input bool     InpUseTrailing           = false;    // ATR trailing stop
input double   InpTrailAtrMult          = 1.5;      // Trailing distance in ATR
input int      InpMinModifySeconds      = 30;       // Min seconds between stop modifications per position

input group "=== 7. Trading hours ==="
input bool     InpUseSessionFilter      = true;     // Restrict entries to sessions below
input bool     InpTradeAllDay           = false;    // Ignore sessions, trade all day (still rollover/weekend/news)
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
