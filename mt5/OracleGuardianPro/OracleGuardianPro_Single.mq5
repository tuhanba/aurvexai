//+------------------------------------------------------------------+
//|                                            OracleGuardianPro.mq5 |
//|  Oracle Guardian Pro - account-protection-first EA for           |
//|  Upcomers Oracle (XAUUSD / XAGUSD, M3 Session VWAP x EMA 9)      |
//|                                                                  |
//|  NO PROFIT IS GUARANTEED. Experimental, untested software.       |
//|  Priority: 1) Oracle rules 2) live equity tracking 3) dynamic    |
//|  risk 4) trade quality 5) daily target.                          |
//+------------------------------------------------------------------+
#property copyright   "Personal EA - use at your own risk"
#property version     "1.10"
#property description "Oracle Guardian Pro: Session VWAP (OHLC/4) x EMA9 on M3 for XAUUSD/XAGUSD"
#property description "with Upcomers Oracle rule guard, equity-based dynamic sizing and mandatory stop-loss."
#property description "No profit is guaranteed. Test on demo first."

//--- SINGLE-FILE BUILD: all Include/OGP_*.mqh modules are inlined below.
//--- Generated from the modular sources; edit those, then regenerate.
//==================================================================
// ===== MODULE: OGP_Inputs.mqh =====
//==================================================================
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
input ENUM_OGP_LOT_MODE InpLotMode     = OGP_LOT_FIXED; // Lot mode
input double   InpFixedLotGold          = 0.10;     // Fixed lots per position - gold
input double   InpFixedLotSilver        = 0.10;     // Fixed lots per position - silver (silver 0.10 lot ~ 10x gold risk per $!)
input double   InpRiskPct               = 0.25;     // Risk mode: risk per SIGNAL, % of CURRENT equity (split over positions)
input double   InpMaxTotalRiskPct       = 1.00;     // Max combined planned risk of open EA positions, % of initial balance
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

input group "=== 3b. Two positions per signal ==="
input ENUM_OGP_SECOND InpSecondEntry    = OGP_2ND_ON_RETEST; // Second position mode
input double   InpRetestZoneAtr         = 0.25;     // Retest zone beyond EMA/VWAP, ATR
input bool     InpRetestNeedsClose      = true;     // Retest must be confirmed by an M3 close back on the signal side
input int      InpRetestMaxBars         = 10;       // Retest must happen within N bars after entry #1
input double   InpTp1RR                 = 1.0;      // AT_SIGNAL mode: target of position #1 (R)
input bool     InpBeAfterTp1            = true;     // AT_SIGNAL mode: move #2 to break-even once price reaches TP1

input group "=== 4. Filters (each independent; untested -> OFF unless safety) ==="
input bool     InpUseTrendM15           = false;    // M15 EMA trend filter
input bool     InpUseTrendH1            = false;    // H1 EMA trend filter
input int      InpTrendEmaPeriod        = 50;       // Trend EMA period
input int      InpTrendSlopeBars        = 3;        // Trend EMA slope lookback (bars)
input bool     InpUseBreakoutFilter     = false;    // Require structure break or strong momentum
input int      InpBreakoutLookback      = 20;       // Swing lookback for breakout (M3 bars)
input double   InpMomentumBodyAtr       = 1.0;      // Momentum bar body >= x * ATR counts as confirmation
input bool     InpBreakoutRetest        = false;    // Require retest of the broken level
input int      InpBreakRetestMaxBars    = 6;        // Max bars between break and retest (breakout filter)
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
input ENUM_OGP_EMA_EXIT InpEmaExitMode = OGP_EMAX_AFTER_MFE; // EMA candle-close exit mode
input double   InpEmaExitMinR           = 0.5;      // AFTER_MFE mode: trade must have run this many R in favour first
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

//==================================================================
// ===== MODULE: OGP_Common.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Common.mqh - logging, CSV journal, formatting, symbol helpers |
//+------------------------------------------------------------------+
#ifndef OGP_COMMON_MQH
#define OGP_COMMON_MQH

#define OGP_TAG      "[OGP]"
#define OGP_SIG_TF   PERIOD_M3
#define OGP_M3_SEC   180

bool OgpIsTester() { return (bool)MQLInfoInteger(MQL_TESTER); }

//--- Source/quality of a risk reference value
enum ENUM_OGP_SOURCE
  {
   OGP_SRC_UNKNOWN  = 0, // cannot be determined -> entries blocked
   OGP_SRC_OBSERVED = 1, // observed live by the EA
   OGP_SRC_BOUND    = 2, // reconstructed conservative upper bound (history + M1 extremes)
   OGP_SRC_MANUAL   = 3  // entered by the user from the Upcomers dashboard
  };

string SourceText(const ENUM_OGP_SOURCE s)
  {
   switch(s)
     {
      case OGP_SRC_OBSERVED: return "OBSERVED";
      case OGP_SRC_BOUND:    return "RECONSTRUCTED(conservative)";
      case OGP_SRC_MANUAL:   return "MANUAL";
     }
   return "UNKNOWN";
  }

//==================================================================//
// Logging                                                          //
//==================================================================//
int    g_journal = INVALID_HANDLE;
string g_thrKeys[];
datetime g_thrTimes[];

string Ts(const datetime t) { return TimeToString(t, TIME_DATE | TIME_SECONDS); }

void OgpLog(const string msg) { Print(OGP_TAG, " ", msg); }

void JournalOpen()
  {
   if(!InpCsvJournal)
      return;
   string fn = StringFormat("OGP_journal_%I64d%s.csv", AccountInfoInteger(ACCOUNT_LOGIN), OgpIsTester() ? "_tester" : "");
   g_journal = FileOpen(fn, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ';');
   if(g_journal == INVALID_HANDLE)
     {
      OgpLog(StringFormat("WARNING: cannot open journal %s (err %d)", fn, GetLastError()));
      return;
     }
   if(FileSize(g_journal) == 0)
      FileWrite(g_journal, "server_time", "category", "symbol", "message", "balance", "equity");
   FileSeek(g_journal, 0, SEEK_END);
  }

void JournalClose()
  {
   if(g_journal != INVALID_HANDLE)
     {
      FileClose(g_journal);
      g_journal = INVALID_HANDLE;
     }
  }

// Category: SIGNAL, REJECT, ORDER, CLOSE, MODIFY, RISK, ORACLE, SESSION, NEWS, DATA, SYSTEM, DEAL
void Journal(const string cat, const string sym, const string msg)
  {
   OgpLog(StringFormat("%-7s %s %s", cat, sym, msg));
   if(g_journal != INVALID_HANDLE)
     {
      FileWrite(g_journal, Ts(TimeCurrent()), cat, sym, msg,
                DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2),
                DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
      FileFlush(g_journal);
     }
  }

// Same key logged at most once per `seconds`
void LogThrottled(const string key, const string cat, const string sym, const string msg, const int seconds = 60)
  {
   datetime now = TimeCurrent();
   int n = ArraySize(g_thrKeys);
   for(int i = 0; i < n; i++)
     {
      if(g_thrKeys[i] == key)
        {
         if(now - g_thrTimes[i] < seconds)
            return;
         g_thrTimes[i] = now;
         Journal(cat, sym, msg);
         return;
        }
     }
   ArrayResize(g_thrKeys, n + 1);
   ArrayResize(g_thrTimes, n + 1);
   g_thrKeys[n]  = key;
   g_thrTimes[n] = now;
   Journal(cat, sym, msg);
  }

//==================================================================//
// Symbol helpers                                                   //
//==================================================================//
double SymPoint(const string s)  { return SymbolInfoDouble(s, SYMBOL_POINT); }
int    SymDigits(const string s) { return (int)SymbolInfoInteger(s, SYMBOL_DIGITS); }
string Px(const string s, const double v) { return DoubleToString(v, SymDigits(s)); }
string Usd(const double v) { return DoubleToString(v, 2); }

double NormalizePrice(const string s, const double p)
  {
   double tick = SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE);
   if(tick <= 0.0)
      tick = SymPoint(s);
   return NormalizeDouble(MathRound(p / tick) * tick, SymDigits(s));
  }

int VolumeDigits(const double step)
  {
   int d = 0;
   double s = step;
   while(d < 8 && MathAbs(s - MathRound(s)) > 1e-9)
     {
      s *= 10.0;
      d++;
     }
   return d;
  }

double MaxD(const double a, const double b) { return (a > b) ? a : b; }
double MinD(const double a, const double b) { return (a < b) ? a : b; }

string RetcodeText(const uint rc)
  {
   switch(rc)
     {
      case TRADE_RETCODE_DONE:              return "DONE";
      case TRADE_RETCODE_DONE_PARTIAL:      return "DONE_PARTIAL";
      case TRADE_RETCODE_PLACED:            return "PLACED";
      case TRADE_RETCODE_REQUOTE:           return "REQUOTE";
      case TRADE_RETCODE_REJECT:            return "REJECT";
      case TRADE_RETCODE_CANCEL:            return "CANCEL";
      case TRADE_RETCODE_ERROR:             return "ERROR";
      case TRADE_RETCODE_TIMEOUT:           return "TIMEOUT";
      case TRADE_RETCODE_INVALID:           return "INVALID_REQUEST";
      case TRADE_RETCODE_INVALID_VOLUME:    return "INVALID_VOLUME";
      case TRADE_RETCODE_INVALID_PRICE:     return "INVALID_PRICE";
      case TRADE_RETCODE_INVALID_STOPS:     return "INVALID_STOPS";
      case TRADE_RETCODE_TRADE_DISABLED:    return "TRADE_DISABLED";
      case TRADE_RETCODE_MARKET_CLOSED:     return "MARKET_CLOSED";
      case TRADE_RETCODE_NO_MONEY:          return "NO_MONEY (insufficient margin)";
      case TRADE_RETCODE_PRICE_CHANGED:     return "PRICE_CHANGED";
      case TRADE_RETCODE_PRICE_OFF:         return "PRICE_OFF";
      case TRADE_RETCODE_TOO_MANY_REQUESTS: return "TOO_MANY_REQUESTS";
      case TRADE_RETCODE_CONNECTION:        return "NO_CONNECTION";
      case TRADE_RETCODE_INVALID_FILL:      return "INVALID_FILL";
      case TRADE_RETCODE_FROZEN:            return "FROZEN";
      case TRADE_RETCODE_LIMIT_VOLUME:      return "LIMIT_VOLUME";
      case TRADE_RETCODE_LIMIT_POSITIONS:   return "LIMIT_POSITIONS";
      case TRADE_RETCODE_POSITION_CLOSED:   return "POSITION_CLOSED";
      case 0:                               return "OK";
     }
   return "retcode " + IntegerToString((long)rc);
  }

bool ParseHHMM(const string text, int &minutes)
  {
   string parts[];
   if(StringSplit(text, StringGetCharacter(":", 0), parts) != 2)
      return false;
   int h = (int)StringToInteger(parts[0]);
   int m = (int)StringToInteger(parts[1]);
   if(h < 0 || h > 23 || m < 0 || m > 59)
      return false;
   minutes = h * 60 + m;
   return true;
  }

#endif

//==================================================================
// ===== MODULE: OGP_Time.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Time.mqh - broker server time <-> UTC <-> zone local time    |
//|                                                                  |
//| DST rules implemented:                                           |
//|  US: 2nd Sunday of March 02:00 local -> 1st Sunday Nov 02:00     |
//|  EU: last Sunday of March 01:00 UTC -> last Sunday Oct 01:00 UTC |
//| Live: broker offset = TimeTradeServer() - TimeGMT() (PC clock!)  |
//| Tester: manual InpServerUtcOffsetHours + InpServerDst rule.      |
//+------------------------------------------------------------------+
#ifndef OGP_TIME_MQH
#define OGP_TIME_MQH

int  g_autoOffsetSec   = 0;
bool g_autoOffsetValid = false;

datetime MakeDate(const int y, const int m, const int d)
  {
   MqlDateTime s;
   ZeroMemory(s);
   s.year = y;
   s.mon  = m;
   s.day  = d;
   return StructToTime(s);
  }

int DowOf(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.day_of_week;
  }

int YearOf(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.year;
  }

int MinuteOfDay(const datetime t)
  {
   long lt = (long)t;
   return (int)((lt % 86400) / 60);
  }

datetime DayStart(const datetime t)
  {
   long lt = (long)t;
   return (datetime)(lt - lt % 86400);
  }

datetime NthSunday(const int y, const int m, const int n)
  {
   datetime first = MakeDate(y, m, 1);
   int add = (7 - DowOf(first)) % 7;
   return first + (datetime)((add + 7 * (n - 1)) * 86400);
  }

datetime LastSunday(const int y, const int m)
  {
   int ny = (m == 12) ? y + 1 : y;
   int nm = (m == 12) ? 1 : m + 1;
   datetime last = MakeDate(ny, nm, 1) - 86400;
   return last - (datetime)(DowOf(last) * 86400);
  }

bool IsUsDst(const datetime utc)
  {
   int y = YearOf(utc);
   return (utc >= NthSunday(y, 3, 2) + 7 * 3600 && utc < NthSunday(y, 11, 1) + 6 * 3600);
  }

bool IsEuDst(const datetime utc)
  {
   int y = YearOf(utc);
   return (utc >= LastSunday(y, 3) + 3600 && utc < LastSunday(y, 10) + 3600);
  }

int ServerOffsetSeconds(const datetime serverTime)
  {
   if(InpAutoServerOffset && !OgpIsTester() && g_autoOffsetValid)
      return g_autoOffsetSec;
   int stdSec = InpServerUtcOffsetHours * 3600;
   datetime approxUtc = serverTime - stdSec;
   bool dst = false;
   if(InpServerDst == OGP_DST_US)
      dst = IsUsDst(approxUtc);
   else
      if(InpServerDst == OGP_DST_EU)
         dst = IsEuDst(approxUtc);
   return stdSec + (dst ? 3600 : 0);
  }

void RefreshAutoServerOffset()
  {
   if(!InpAutoServerOffset || OgpIsTester() || !TerminalInfoInteger(TERMINAL_CONNECTED))
      return;
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   long rounded = (long)MathRound(diff / 900.0) * 900;
   if(rounded < -12 * 3600 || rounded > 14 * 3600)
     {
      g_autoOffsetValid = false;
      LogThrottled("autooffset", "TIME", "", StringFormat("auto server offset %I64d s out of range - manual rule used", rounded), 3600);
      return;
     }
   if(!g_autoOffsetValid || g_autoOffsetSec != (int)rounded)
      Journal("TIME", "", StringFormat("broker server offset detected UTC%+.2f h (TimeTradeServer-TimeGMT, depends on PC clock)", rounded / 3600.0));
   g_autoOffsetSec   = (int)rounded;
   g_autoOffsetValid = true;
  }

datetime ServerNow() { return OgpIsTester() ? TimeCurrent() : TimeTradeServer(); }

datetime ServerToUtc(const datetime server) { return server - ServerOffsetSeconds(server); }

datetime UtcToServer(const datetime utc)
  {
   datetime guess = utc + InpServerUtcOffsetHours * 3600;
   return utc + ServerOffsetSeconds(guess);
  }

// UTC midnight (as UTC datetime) of the UTC day containing serverTime
datetime UtcDayKey(const datetime serverTime) { return DayStart(ServerToUtc(serverTime)); }

// Server time of the start of the UTC day containing serverTime
datetime UtcDayStartServer(const datetime serverTime) { return UtcToServer(UtcDayKey(serverTime)); }

int ZoneOffsetSeconds(const ENUM_OGP_ZONE zone, const datetime utc, const datetime serverTime)
  {
   switch(zone)
     {
      case OGP_ZONE_NEWYORK: return -5 * 3600 + (IsUsDst(utc) ? 3600 : 0);
      case OGP_ZONE_LONDON:  return (IsEuDst(utc) ? 3600 : 0);
      case OGP_ZONE_TOKYO:   return 9 * 3600;
      case OGP_ZONE_UTC:     return 0;
      case OGP_ZONE_SERVER:  return ServerOffsetSeconds(serverTime);
     }
   return 0;
  }

datetime ZoneLocal(const ENUM_OGP_ZONE zone, const datetime serverTime)
  {
   datetime utc = ServerToUtc(serverTime);
   return utc + ZoneOffsetSeconds(zone, utc, serverTime);
  }

datetime NyLocal(const datetime serverTime) { return ZoneLocal(OGP_ZONE_NEWYORK, serverTime); }

#endif

//==================================================================
// ===== MODULE: OGP_History.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_History.mqh - account deal history analysis                  |
//|                                                                  |
//| 1) EquityUpperBound(from,to): a CONSERVATIVE UPPER BOUND of the  |
//|    account equity at any moment in [from,to], built from:        |
//|      balance timeline (deal history, incl. deposits/withdrawals) |
//|    + for every position open in the interval, its best possible  |
//|      floating P/L from M1 high/low extremes (OrderCalcProfit).   |
//|    For a moment t: equity(t) = balance(t) + sum(floating of      |
//|    positions open at t) <= maxBalance(over a position's life) +  |
//|    sum(max floating of every position overlapping it).           |
//|    Used when the EA did not observe equity itself (first start,  |
//|    restarts, disconnections, missed UTC midnight). A bound that  |
//|    is too high only makes the shield/daily floor stricter.       |
//|                                                                  |
//| 2) ComputeCycleStats(): realized net P/L per UTC day since the   |
//|    payout-cycle start, valid days, best day, EA trades today.    |
//+------------------------------------------------------------------+
#ifndef OGP_HISTORY_MQH
#define OGP_HISTORY_MQH

struct OgpPosInfo
  {
   long              id;
   string            sym;
   int               dir;          // +1 buy, -1 sell
   double            volume;       // max volume seen
   double            priceOpen;    // volume weighted entry
   datetime          tOpen;
   datetime          tClose;       // 0 while still open
   bool              open;
  };

double DealNet(const ulong d)
  {
   return HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) +
          HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_FEE);
  }

bool IsTradeDeal(const long type) { return (type == DEAL_TYPE_BUY || type == DEAL_TYPE_SELL); }

//==================================================================//
class CHistoryAnalyzer
  {
private:
   datetime          m_dealTime[];
   double            m_balAfter[];
   double            m_balBeforeFirst;
   OgpPosInfo        m_pos[];

   int               FindPos(const long id)
     {
      for(int i = 0; i < ArraySize(m_pos); i++)
         if(m_pos[i].id == id)
            return i;
      return -1;
     }

   int               AddPos(const long id)
     {
      int n = ArraySize(m_pos);
      ArrayResize(m_pos, n + 1);
      m_pos[n].id = id;
      m_pos[n].sym = "";
      m_pos[n].dir = 0;
      m_pos[n].volume = 0.0;
      m_pos[n].priceOpen = 0.0;
      m_pos[n].tOpen = 0;
      m_pos[n].tClose = 0;
      m_pos[n].open = false;
      return n;
     }

   //--- loads deals + positions; history window starts `lookbackFrom`
   bool              Load(const datetime lookbackFrom, string &err)
     {
      ArrayResize(m_dealTime, 0);
      ArrayResize(m_balAfter, 0);
      ArrayResize(m_pos, 0);
      if(!HistorySelect(lookbackFrom, TimeCurrent() + 86400))
        {
         err = StringFormat("HistorySelect failed (err %d)", GetLastError());
         return false;
        }
      int n = HistoryDealsTotal();
      ArrayResize(m_dealTime, n);
      ArrayResize(m_balAfter, n);
      double nets[];
      ArrayResize(nets, n);
      for(int i = 0; i < n; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         m_dealTime[i] = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
         nets[i] = DealNet(d);
         long type = HistoryDealGetInteger(d, DEAL_TYPE);
         if(!IsTradeDeal(type))
            continue;
         long pid   = HistoryDealGetInteger(d, DEAL_POSITION_ID);
         long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
         double vol = HistoryDealGetDouble(d, DEAL_VOLUME);
         double prc = HistoryDealGetDouble(d, DEAL_PRICE);
         int k = FindPos(pid);
         if(k < 0)
            k = AddPos(pid);
         m_pos[k].sym = HistoryDealGetString(d, DEAL_SYMBOL);
         if(entry == DEAL_ENTRY_IN)
           {
            if(m_pos[k].tOpen == 0)
               m_pos[k].tOpen = m_dealTime[i];
            m_pos[k].dir = (type == DEAL_TYPE_BUY) ? 1 : -1;
            double tv = m_pos[k].volume + vol;
            if(tv > 0.0)
               m_pos[k].priceOpen = (m_pos[k].priceOpen * m_pos[k].volume + prc * vol) / tv;
            m_pos[k].volume = tv;
           }
         else
            if(entry == DEAL_ENTRY_INOUT)       // netting reversal: approximate as new direction
              {
               m_pos[k].dir = (type == DEAL_TYPE_BUY) ? 1 : -1;
               m_pos[k].priceOpen = prc;
               m_pos[k].volume = MaxD(m_pos[k].volume, vol);
               if(m_pos[k].tOpen == 0)
                  m_pos[k].tOpen = m_dealTime[i];
              }
            else                                // OUT / OUT_BY
               m_pos[k].tClose = m_dealTime[i];
        }
      //--- balance timeline walking backwards from the current balance
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      for(int i = n - 1; i >= 0; i--)
        {
         m_balAfter[i] = bal;
         bal -= nets[i];
        }
      m_balBeforeFirst = bal;

      //--- currently open positions
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0)
            continue;
         long pid = PositionGetInteger(POSITION_IDENTIFIER);
         int k = FindPos(pid);
         if(k < 0)
            k = AddPos(pid);
         m_pos[k].sym = PositionGetString(POSITION_SYMBOL);
         m_pos[k].dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
         m_pos[k].priceOpen = PositionGetDouble(POSITION_PRICE_OPEN);
         m_pos[k].volume = MaxD(m_pos[k].volume, PositionGetDouble(POSITION_VOLUME));
         datetime pt = (datetime)PositionGetInteger(POSITION_TIME);
         if(m_pos[k].tOpen == 0 || pt < m_pos[k].tOpen)
            m_pos[k].tOpen = pt;
         m_pos[k].open = true;
         m_pos[k].tClose = 0;
        }
      return true;
     }

   double            BalanceAt(const datetime t) const
     {
      double b = m_balBeforeFirst;
      for(int i = 0; i < ArraySize(m_dealTime); i++)
        {
         if(m_dealTime[i] > t)
            break;
         b = m_balAfter[i];
        }
      return b;
     }

   double            MaxBalance(const datetime a, const datetime b) const
     {
      double m = BalanceAt(a);
      for(int i = 0; i < ArraySize(m_dealTime); i++)
        {
         if(m_dealTime[i] <= a)
            continue;
         if(m_dealTime[i] > b)
            break;
         m = MaxD(m, m_balAfter[i]);
        }
      return m;
     }

   //--- best floating P/L of one position inside [a,b] from M1 extremes
   bool              MaxFloating(const OgpPosInfo &p, const datetime a, const datetime b, double &best, string &err)
     {
      if(p.priceOpen <= 0.0 || p.volume <= 0.0 || p.sym == "")
        {
         err = StringFormat("position %I64d: entry price/volume unknown (opened before history window)", p.id);
         return false;
        }
      MqlRates rr[];
      datetime a0 = (datetime)((long)a - (long)a % 60);
      int n = CopyRates(p.sym, PERIOD_M1, a0, b, rr);
      if(n <= 0)
         n = CopyRates(p.sym, PERIOD_M1, a0, 1, rr);
      if(n <= 0)
        {
         err = StringFormat("position %I64d %s: no M1 data for %s..%s (err %d)", p.id, p.sym, Ts(a), Ts(b), GetLastError());
         return false;
        }
      double ext = (p.dir > 0) ? rr[0].high : rr[0].low;
      for(int i = 1; i < n; i++)
        {
         if(p.dir > 0)
            ext = MaxD(ext, rr[i].high);
         else
            ext = MinD(ext, rr[i].low);
        }
      double pr = 0.0;
      if(!OrderCalcProfit(p.dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, p.sym, p.volume, p.priceOpen, ext, pr))
        {
         err = StringFormat("position %I64d %s: OrderCalcProfit failed (err %d)", p.id, p.sym, GetLastError());
         return false;
        }
      best = pr;
      return true;
     }

public:
   //--- conservative upper bound of equity over [from,to]
   bool              EquityUpperBound(const datetime from, const datetime to, double &bound, string &err)
     {
      bound = 0.0;
      err = "";
      if(!Load(from - 120 * 86400, err))
         return false;

      datetime a[], b[];
      double   fm[];
      int      idx[];
      int cnt = 0;
      for(int k = 0; k < ArraySize(m_pos); k++)
        {
         datetime end = m_pos[k].open ? to : (m_pos[k].tClose > 0 ? m_pos[k].tClose : to);
         datetime beg = m_pos[k].tOpen;
         if(beg == 0)
            beg = from;                     // opened before the history window
         if(beg > to || end < from)
            continue;
         ArrayResize(a, cnt + 1);
         ArrayResize(b, cnt + 1);
         ArrayResize(fm, cnt + 1);
         ArrayResize(idx, cnt + 1);
         a[cnt] = (beg > from) ? beg : from;
         b[cnt] = (end < to) ? end : to;
         idx[cnt] = k;
         if(!MaxFloating(m_pos[k], a[cnt], b[cnt], fm[cnt], err))
            return false;
         cnt++;
        }

      bound = MaxBalance(from, to);
      for(int i = 0; i < cnt; i++)
        {
         double s = MaxBalance(a[i], b[i]);
         for(int j = 0; j < cnt; j++)
            if(a[j] <= b[i] && b[j] >= a[i])
               s += fm[j];
         bound = MaxD(bound, s);
        }
      return true;
     }

   //--- equity of the account at a past moment is unknown; this returns
   //--- the conservative upper bound in a small window around it
   bool              EquityUpperBoundAround(const datetime t, const int halfWindowSec, double &bound, string &err)
     {
      return EquityUpperBound(t - halfWindowSec, t + halfWindowSec, bound, err);
     }
  };

//==================================================================//
// Cycle statistics (realized P/L per UTC day)                      //
//==================================================================//
struct OgpCycleStats
  {
   bool              ok;
   datetime          computedAt;
   double            cycleNet;        // realized net since cycle start
   double            todayNet;        // realized net today (UTC)
   double            bestDayNet;
   datetime          bestDayKey;
   int               validDays;
   int               tradingDays;
   int               eaEntriesToday;
   int               eaEntriesCycle;
  };

bool ComputeCycleStats(const datetime cycleStart, const datetime todayKeyUtc, const double validThreshold, OgpCycleStats &st)
  {
   st.ok = false;
   st.cycleNet = 0.0;
   st.todayNet = 0.0;
   st.bestDayNet = 0.0;
   st.bestDayKey = 0;
   st.validDays = 0;
   st.tradingDays = 0;
   st.eaEntriesToday = 0;
   st.eaEntriesCycle = 0;
   st.computedAt = TimeCurrent();

   if(!HistorySelect(cycleStart, TimeCurrent() + 86400))
      return false;
   datetime keys[];
   double   nets[];
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0)
         continue;
      long type = HistoryDealGetInteger(d, DEAL_TYPE);
      if(!IsTradeDeal(type))
         continue;
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      if(t < cycleStart)
         continue;
      datetime key = UtcDayKey(t);
      double net = DealNet(d);
      st.cycleNet += net;
      int k = -1;
      for(int j = 0; j < ArraySize(keys); j++)
         if(keys[j] == key)
           {
            k = j;
            break;
           }
      if(k < 0)
        {
         k = ArraySize(keys);
         ArrayResize(keys, k + 1);
         ArrayResize(nets, k + 1);
         keys[k] = key;
         nets[k] = 0.0;
        }
      nets[k] += net;
      //--- count SIGNALS: the second position of a signal ("#2") is not a new trade
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN && (ulong)HistoryDealGetInteger(d, DEAL_MAGIC) == InpMagic &&
         StringFind(HistoryDealGetString(d, DEAL_COMMENT), "#2") < 0)
        {
         st.eaEntriesCycle++;
         if(key == todayKeyUtc)
            st.eaEntriesToday++;
        }
     }
   st.tradingDays = ArraySize(keys);
   for(int j = 0; j < ArraySize(keys); j++)
     {
      if(keys[j] == todayKeyUtc)
         st.todayNet = nets[j];
      if(nets[j] >= validThreshold)
         st.validDays++;
      if(nets[j] > st.bestDayNet)
        {
         st.bestDayNet = nets[j];
         st.bestDayKey = keys[j];
        }
     }
   st.ok = true;
   return true;
  }

#endif

//==================================================================
// ===== MODULE: OGP_Account.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Account.mqh - live account monitor + Oracle rule engine      |
//|                                                                  |
//| WHAT MT5 GIVES US vs WHAT ONLY UPCOMERS KNOWS                    |
//|  Read directly from MT5 (exact): balance, equity, floating P/L,  |
//|   margin, free margin, margin level, currency, positions, deals. |
//|  NOT readable from MT5 (Upcomers server-side): the Dynamic Risk  |
//|   Shield floor, the highest-equity reference it trails, the      |
//|   equity Upcomers recorded at 00:00 UTC, payout-cycle resets.    |
//|  The EA therefore keeps its OWN references and labels each one:  |
//|   OBSERVED      - seen live by this EA                           |
//|   RECONSTRUCTED - conservative upper bound from history + M1     |
//|   MANUAL        - typed in by the user from the Upcomers panel   |
//|   UNKNOWN       - cannot be determined -> new entries BLOCKED    |
//|                                                                  |
//| RULE INTERPRETATIONS (owner-confirmed, conservative):            |
//|  Shield floor = max(initial*(1-5%), peakEquity - initial*5%,     |
//|                     manual floor)                                |
//|  Daily floor  = dayStartEquity - 4% * min(initial, dayStartEq)   |
//|                 (day = 00:00-23:59 UTC, reference = EQUITY)      |
//|  Single trade = 2% * min(initial, current equity)                |
//+------------------------------------------------------------------+
#ifndef OGP_ACCOUNT_MQH
#define OGP_ACCOUNT_MQH

class CAccountMonitor
  {
private:
   CHistoryAnalyzer  m_hist;
   string            m_file;
   datetime          m_lastSave;
   datetime          m_lastResolveTry;
   bool              m_needCycleRebuild;
   bool              m_gapPending;
   datetime          m_gapStart;
   bool              m_disconnected;
   double            m_lastEquity;
   datetime          m_initTime;

   //--- state persistence (key=value text file in MQL5/Files)
   bool              LoadState(datetime &stCycle, double &stInit)
     {
      int h = FileOpen(m_file, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return false;
      stCycle = 0;
      stInit = 0.0;
      while(!FileIsEnding(h))
        {
         string line = FileReadString(h);
         int p = StringFind(line, "=");
         if(p <= 0)
            continue;
         string k = StringSubstr(line, 0, p);
         string v = StringSubstr(line, p + 1);
         if(k == "peak_equity")
            peakEquity = StringToDouble(v);
         else if(k == "peak_src")
            peakSrc = (ENUM_OGP_SOURCE)StringToInteger(v);
         else if(k == "peak_time")
            peakTime = (datetime)StringToInteger(v);
         else if(k == "day_key")
            dayKey = (datetime)StringToInteger(v);
         else if(k == "day_start_equity")
            dayStartEquity = StringToDouble(v);
         else if(k == "day_src")
            daySrc = (ENUM_OGP_SOURCE)StringToInteger(v);
         else if(k == "last_seen")
            lastSeen = (datetime)StringToInteger(v);
         else if(k == "cycle_start")
            stCycle = (datetime)StringToInteger(v);
         else if(k == "initial_balance")
            stInit = StringToDouble(v);
        }
      FileClose(h);
      return true;
     }

   void              ResolvePeak(const datetime now)
     {
      string err = "";
      double bound = 0.0;
      if(m_needCycleRebuild)
        {
         datetime from = EffectiveCycleStart(now);
         if(m_hist.EquityUpperBound(from, now, bound, err))
           {
            peakEquity = MaxD(bound, equity);
            peakSrc = OGP_SRC_BOUND;
            peakTime = now;
            peakNote = "rebuilt from cycle start " + Ts(from);
            m_needCycleRebuild = false;
            Journal("ORACLE", "", StringFormat("peak equity reconstructed since cycle start %s: %s (conservative upper bound)", Ts(from), Usd(peakEquity)));
           }
         else
           {
            peakNote = "rebuild failed: " + err;
            LogThrottled("peakfail", "ORACLE", "", "cannot reconstruct peak equity: " + err + " -> entries blocked (enter InpManualShieldFloor or InpManualPeakEquity)", 300);
           }
        }
      if(m_gapPending && !m_needCycleRebuild)
        {
         if(m_hist.EquityUpperBound(m_gapStart, now, bound, err))
           {
            if(bound > peakEquity)
              {
               Journal("ORACLE", "", StringFormat("equity not observed %s..%s; conservative bound %s raises peak from %s",
                                                  Ts(m_gapStart), Ts(now), Usd(bound), Usd(peakEquity)));
               peakEquity = bound;
               peakSrc = OGP_SRC_BOUND;
               peakTime = now;
              }
            if(peakSrc == OGP_SRC_UNKNOWN)
               peakSrc = OGP_SRC_BOUND;
            peakNote = "";
            m_gapPending = false;
           }
         else
           {
            peakNote = "gap bound failed: " + err;
            LogThrottled("gapfail", "ORACLE", "", "cannot bound equity during unobserved gap: " + err, 300);
            peakSrc = OGP_SRC_UNKNOWN;
           }
        }
      if(InpManualPeakEquity > 0.0 && InpManualPeakEquity > peakEquity)
        {
         peakEquity = InpManualPeakEquity;
         if(peakSrc == OGP_SRC_UNKNOWN)
            peakSrc = OGP_SRC_MANUAL;
        }
      if(peakSrc == OGP_SRC_UNKNOWN && InpManualPeakEquity > 0.0 && !m_needCycleRebuild && !m_gapPending)
         peakSrc = OGP_SRC_MANUAL;
     }

   void              ResolveDayStart(const datetime now)
     {
      datetime key = UtcDayKey(now);
      if(InpManualDayStartEquity > 0.0 && DayStart(InpManualDayStartDate) == key)
        {
         dayStartEquity = InpManualDayStartEquity;
         daySrc = OGP_SRC_MANUAL;
         dayNote = "manual input";
         return;
        }
      datetime midServer = UtcToServer(key);
      double bound = 0.0;
      string err = "";
      if(m_hist.EquityUpperBoundAround(midServer, 60, bound, err))
        {
         dayStartEquity = bound;
         if(now - midServer <= 60)
            dayStartEquity = MaxD(dayStartEquity, MaxD(equity, m_lastEquity));
         daySrc = (lastSeen > 0 && lastSeen >= midServer - 60 && now - midServer <= 60) ? OGP_SRC_OBSERVED : OGP_SRC_BOUND;
         dayNote = StringFormat("UTC day start %s server", Ts(midServer));
         Journal("ORACLE", "", StringFormat("day start equity (00:00 UTC = %s server) = %s [%s]",
                                            Ts(midServer), Usd(dayStartEquity), SourceText(daySrc)));
        }
      else
        {
         daySrc = OGP_SRC_UNKNOWN;
         dayNote = "bound failed: " + err;
         LogThrottled("dayfail", "ORACLE", "", "cannot determine today's start equity: " + err +
                      " -> entries blocked (enter InpManualDayStartEquity + date)", 300);
        }
     }

public:
   //--- live snapshot (exact, from MT5)
   long              login;
   string            currency;
   long              leverage;
   double            balance;
   double            equity;
   double            floating;
   double            margin;
   double            freeMargin;
   double            marginLevel;
   bool              connected;
   //--- references kept by the EA
   double            peakEquity;
   ENUM_OGP_SOURCE   peakSrc;
   datetime          peakTime;
   string            peakNote;
   datetime          dayKey;
   double            dayStartEquity;
   ENUM_OGP_SOURCE   daySrc;
   string            dayNote;
   datetime          lastSeen;

                     CAccountMonitor(void) : m_file(""), m_lastSave(0), m_lastResolveTry(0), m_needCycleRebuild(false),
                     m_gapPending(false), m_gapStart(0), m_disconnected(false), m_lastEquity(0), m_initTime(0), login(0), currency(""),
                     leverage(0), balance(0), equity(0), floating(0), margin(0), freeMargin(0), marginLevel(0),
                     connected(true), peakEquity(0), peakSrc(OGP_SRC_UNKNOWN), peakTime(0), peakNote(""), dayKey(0),
                     dayStartEquity(0), daySrc(OGP_SRC_UNKNOWN), dayNote(""), lastSeen(0) {}

   //--- cycle start in the future (e.g. tester period before it): count from EA start instead
   datetime          EffectiveCycleStart(const datetime now) const { return (InpCycleStart <= now) ? InpCycleStart : ((m_initTime > 0) ? m_initTime : now); }

   void              ReadSnapshot(void)
     {
      login       = AccountInfoInteger(ACCOUNT_LOGIN);
      currency    = AccountInfoString(ACCOUNT_CURRENCY);
      leverage    = AccountInfoInteger(ACCOUNT_LEVERAGE);
      balance     = AccountInfoDouble(ACCOUNT_BALANCE);
      equity      = AccountInfoDouble(ACCOUNT_EQUITY);
      floating    = AccountInfoDouble(ACCOUNT_PROFIT);
      margin      = AccountInfoDouble(ACCOUNT_MARGIN);
      freeMargin  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      connected   = OgpIsTester() ? true : (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
     }

   void              Init(void)
     {
      ReadSnapshot();
      m_file = StringFormat("OGP_state_%I64d%s.txt", login, OgpIsTester() ? "_tester" : "");
      datetime now = ServerNow();
      m_initTime = now;
      datetime stCycle = 0;
      double stInit = 0.0;
      bool loaded = LoadState(stCycle, stInit);
      if(loaded && (stCycle != InpCycleStart || MathAbs(stInit - InpInitialBalance) > 0.009))
        {
         Journal("ORACLE", "", StringFormat("payout cycle / initial balance changed (state %s / %s -> inputs %s / %s): peak reference rebuilt",
                                            Ts(stCycle), Usd(stInit), Ts(InpCycleStart), Usd(InpInitialBalance)));
         loaded = false;
        }
      if(loaded && peakSrc != OGP_SRC_UNKNOWN && peakEquity > 0.0 && lastSeen > 0)
        {
         m_gapPending = true;
         m_gapStart = lastSeen;
         Journal("ORACLE", "", StringFormat("state loaded: peak %s [%s], last seen %s -> bounding the unobserved gap",
                                            Usd(peakEquity), SourceText(peakSrc), Ts(lastSeen)));
        }
      else
        {
         peakEquity = 0.0;
         peakSrc = OGP_SRC_UNKNOWN;
         m_needCycleRebuild = true;
        }
      if(InpCycleStart > now)
         Journal("ORACLE", "", "WARNING: InpCycleStart is in the future - cycle statistics count from EA start " + Ts(now));
      ResolvePeak(now);
      if(!loaded || dayKey != UtcDayKey(now) || daySrc == OGP_SRC_UNKNOWN)
        {
         dayKey = UtcDayKey(now);
         ResolveDayStart(now);
        }
      else
         if(InpManualDayStartEquity > 0.0 && DayStart(InpManualDayStartDate) == dayKey)
            ResolveDayStart(now);
      m_lastEquity = equity;
      lastSeen = now;
      Save();
     }

   void              Update(void)
     {
      ReadSnapshot();
      datetime now = ServerNow();

      //--- unobserved periods: disconnection or stalled EA (> 120 s)
      if(!connected)
        {
         if(!m_disconnected)
           {
            m_disconnected = true;
            if(!m_gapPending)
               m_gapStart = lastSeen;
            Journal("SYSTEM", "", "terminal DISCONNECTED - equity no longer observed");
           }
         return;
        }
      if(m_disconnected)
        {
         m_disconnected = false;
         m_gapPending = true;
         Journal("SYSTEM", "", "terminal RECONNECTED - bounding equity for the disconnected period");
        }
      if(lastSeen > 0 && now - lastSeen > 120 && !m_gapPending)
        {
         m_gapPending = true;
         m_gapStart = lastSeen;
        }

      //--- UTC day change
      datetime key = UtcDayKey(now);
      if(key != dayKey)
        {
         dayKey = key;
         daySrc = OGP_SRC_UNKNOWN;
         Journal("ORACLE", "", "new UTC trading day " + TimeToString(key, TIME_DATE));
        }

      //--- retries for unresolved references (max every 30 s)
      if((m_needCycleRebuild || m_gapPending || daySrc == OGP_SRC_UNKNOWN) && now - m_lastResolveTry >= 30)
        {
         m_lastResolveTry = now;
         if(m_needCycleRebuild || m_gapPending)
            ResolvePeak(now);
         if(daySrc == OGP_SRC_UNKNOWN)
            ResolveDayStart(now);
        }

      //--- live peak tracking
      if(!m_needCycleRebuild && equity > peakEquity)
        {
         peakEquity = equity;
         peakTime = now;
         if(peakSrc == OGP_SRC_UNKNOWN && !m_gapPending)
            peakSrc = OGP_SRC_OBSERVED;
        }
      m_lastEquity = equity;
      lastSeen = now;
      if(now - m_lastSave >= 30)
         Save();
     }

   void              Save(void)
     {
      int h = FileOpen(m_file, FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         LogThrottled("statesave", "SYSTEM", "", StringFormat("cannot write state file %s (err %d)", m_file, GetLastError()), 600);
         return;
        }
      FileWriteString(h, StringFormat("peak_equity=%.2f\n", peakEquity));
      FileWriteString(h, StringFormat("peak_src=%d\n", (int)peakSrc));
      FileWriteString(h, StringFormat("peak_time=%I64d\n", (long)peakTime));
      FileWriteString(h, StringFormat("day_key=%I64d\n", (long)dayKey));
      FileWriteString(h, StringFormat("day_start_equity=%.2f\n", dayStartEquity));
      FileWriteString(h, StringFormat("day_src=%d\n", (int)daySrc));
      FileWriteString(h, StringFormat("last_seen=%I64d\n", (long)lastSeen));
      FileWriteString(h, StringFormat("cycle_start=%I64d\n", (long)InpCycleStart));
      FileWriteString(h, StringFormat("initial_balance=%.2f\n", InpInitialBalance));
      FileClose(h);
      m_lastSave = ServerNow();
     }

   bool              PeakPending(void) const { return m_needCycleRebuild || m_gapPending; }
  };

//==================================================================//
// Oracle rule engine                                               //
//==================================================================//
class COracleRules
  {
private:
   datetime          m_lastStats;
   datetime          m_lockKey;
   bool              m_targetLogged;

public:
   double            shieldFloor;
   bool              shieldReliable;
   double            dailyLimit;
   double            dailyFloor;
   bool              dailyReliable;
   double            singleTradeLimit;
   double            validDayThreshold;
   double            payoutThreshold;
   OgpCycleStats     stats;
   bool              statsDirty;
   bool              dailyLock;
   string            dailyLockReason;
   bool              emergency;
   string            emergencyReason;

                     COracleRules(void) : m_lastStats(0), m_lockKey(0), m_targetLogged(false), shieldFloor(0), shieldReliable(false),
                     dailyLimit(0), dailyFloor(0), dailyReliable(false), singleTradeLimit(0), validDayThreshold(0),
                     payoutThreshold(0), statsDirty(true), dailyLock(false), dailyLockReason(""), emergency(false),
                     emergencyReason("") { stats.ok = false; }

   void              Update(CAccountMonitor &acc)
     {
      double init = InpInitialBalance;
      validDayThreshold = init * InpValidDayPct / 100.0;
      payoutThreshold   = init * InpPayoutPct / 100.0;

      //--- Dynamic Risk Shield (conservative interpretation)
      double shieldAmount = init * InpShieldPct / 100.0;
      double base = init - shieldAmount;
      shieldReliable = (acc.peakSrc != OGP_SRC_UNKNOWN && !acc.PeakPending()) || InpManualShieldFloor > 0.0;
      shieldFloor = base;
      if(acc.peakSrc != OGP_SRC_UNKNOWN)
         shieldFloor = MaxD(shieldFloor, acc.peakEquity - shieldAmount);
      if(InpManualShieldFloor > 0.0)
         shieldFloor = MaxD(shieldFloor, InpManualShieldFloor);

      //--- Daily drawdown (equity reference at 00:00 UTC)
      dailyReliable = (acc.daySrc != OGP_SRC_UNKNOWN);
      if(dailyReliable)
        {
         dailyLimit = MinD(init, acc.dayStartEquity) * InpDailyDDPct / 100.0;
         dailyFloor = acc.dayStartEquity - dailyLimit;
        }

      //--- Single trade loss
      singleTradeLimit = MinD(init, acc.equity) * InpSingleTradePct / 100.0;

      //--- realized statistics
      datetime now = ServerNow();
      if(statsDirty || now - m_lastStats >= 15)
        {
         OgpCycleStats tmp;
         if(ComputeCycleStats(acc.EffectiveCycleStart(now), acc.dayKey, validDayThreshold, tmp))
            stats = tmp;
         else
           {
            stats.ok = false;
            LogThrottled("statsfail", "ORACLE", "", "deal history unavailable - realized statistics unknown", 300);
           }
         m_lastStats = now;
         statsDirty = false;
        }

      //--- internal daily loss lock (sticky for the UTC day)
      if(m_lockKey != acc.dayKey)
        {
         m_lockKey = acc.dayKey;
         dailyLock = false;
         dailyLockReason = "";
         m_targetLogged = false;
        }
      if(dailyReliable && !dailyLock && acc.dayStartEquity - acc.equity >= InpDailyLossLockUSD)
        {
         dailyLock = true;
         dailyLockReason = StringFormat("internal daily loss lock: equity %s is %s below day start %s",
                                        Usd(acc.equity), Usd(acc.dayStartEquity - acc.equity), Usd(acc.dayStartEquity));
         Journal("RISK", "", dailyLockReason + " - no new entries until next UTC day");
        }
      if(InpStopAtDailyTarget && stats.ok && stats.todayNet >= InpDailyTargetUSD && !m_targetLogged)
        {
         m_targetLogged = true;
         Journal("RISK", "", StringFormat("daily target reached: realized net %s >= %s - no new entries today", Usd(stats.todayNet), Usd(InpDailyTargetUSD)));
        }

      //--- emergency (only with reliable floors)
      emergency = false;
      emergencyReason = "";
      if(shieldReliable && acc.equity <= shieldFloor + InpEmergencyBufferUSD)
        {
         emergency = true;
         emergencyReason = StringFormat("equity %s within %s of shield floor %s", Usd(acc.equity), Usd(InpEmergencyBufferUSD), Usd(shieldFloor));
        }
      if(dailyReliable && acc.equity <= dailyFloor + InpEmergencyBufferUSD)
        {
         emergency = true;
         emergencyReason = StringFormat("equity %s within %s of daily floor %s", Usd(acc.equity), Usd(InpEmergencyBufferUSD), Usd(dailyFloor));
        }
     }

   bool              EntryAllowed(CAccountMonitor &acc, string &why, const bool countTrades = true)
     {
      if(!acc.connected)
        {
         why = "terminal disconnected";
         return false;
        }
      if(!shieldReliable)
        {
         why = "Dynamic Risk Shield reference UNKNOWN (" + acc.peakNote + ")";
         return false;
        }
      if(!dailyReliable)
        {
         why = "today's start equity UNKNOWN (" + acc.dayNote + ")";
         return false;
        }
      if(!stats.ok)
        {
         why = "deal history statistics unavailable";
         return false;
        }
      if(emergency)
        {
         why = "EMERGENCY: " + emergencyReason;
         return false;
        }
      if(acc.equity - shieldFloor <= InpFloorSafetyUSD)
        {
         why = StringFormat("equity %s within safety %s of shield floor %s", Usd(acc.equity), Usd(InpFloorSafetyUSD), Usd(shieldFloor));
         return false;
        }
      if(acc.equity - dailyFloor <= InpFloorSafetyUSD)
        {
         why = StringFormat("equity %s within safety %s of daily floor %s", Usd(acc.equity), Usd(InpFloorSafetyUSD), Usd(dailyFloor));
         return false;
        }
      if(dailyLock)
        {
         why = dailyLockReason;
         return false;
        }
      if(InpStopAtDailyTarget && stats.todayNet >= InpDailyTargetUSD)
        {
         why = StringFormat("daily target reached (realized %s)", Usd(stats.todayNet));
         return false;
        }
      if(countTrades && stats.eaEntriesToday >= InpMaxTradesPerDay)
        {
         why = StringFormat("max new trades per day reached (%d)", InpMaxTradesPerDay);
         return false;
        }
      return true;
     }

   double            BestDayRatio(void) const
     {
      if(!stats.ok || stats.cycleNet <= 0.0)
         return 0.0;
      return 100.0 * stats.bestDayNet / stats.cycleNet;
     }

   string            PayoutStatus(const int openPositions) const
     {
      if(!stats.ok)
         return "unknown (history)";
      bool p1 = stats.cycleNet >= payoutThreshold;
      bool p2 = stats.validDays >= InpMinValidDays;
      bool p3 = stats.cycleNet > 0.0 && stats.bestDayNet <= stats.cycleNet * InpBestDayPct / 100.0;
      bool p4 = openPositions == 0;
      if(p1 && p2 && p3 && p4)
         return "ELIGIBLE (verify on Upcomers)";
      string s = "";
      if(!p1)
         s += StringFormat("net %s/%s ", Usd(stats.cycleNet), Usd(payoutThreshold));
      if(!p2)
         s += StringFormat("days %d/%d ", stats.validDays, InpMinValidDays);
      if(!p3)
         s += StringFormat("bestDay %.0f%%>%.0f%% ", BestDayRatio(), InpBestDayPct);
      if(!p4)
         s += "positions open";
      return "not yet: " + s;
     }
  };

#endif

//==================================================================
// ===== MODULE: OGP_Vwap.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Vwap.mqh - session-anchored VWAP on M3 bars (custom calc)    |
//|                                                                  |
//| MT5 has no built-in VWAP indicator, so it is calculated here:    |
//|   typical_i = (Open_i + High_i + Low_i + Close_i) / 4            |
//|   VWAP      = sum(typical_i * vol_i) / sum(vol_i)                |
//| over every M3 bar from the bar containing the anchor (session    |
//| start) to:                                                       |
//|   - the last CLOSED bar  -> closed VWAP (Bar1/Bar2 values), used |
//|     by confirmed mode, filters and exits;                        |
//|   - the forming bar with its current OHLC/volume -> live VWAP,   |
//|     used by live mode only.                                      |
//| Volume: Auto uses real volume only if every checked closed bar   |
//| has real_volume > 0, otherwise tick volume. The choice is shown  |
//| on the dashboard. Real-only with no real volume => VWAP invalid  |
//| (never silently substituted).                                    |
//+------------------------------------------------------------------+
#ifndef OGP_VWAP_MQH
#define OGP_VWAP_MQH

class CSessionVwap
  {
private:
   string            m_symbol;
   bool              m_volumeKnown;
   bool              m_useReal;
   datetime          m_anchorBar;
   datetime          m_lastClosed;
   bool              m_cacheValid;
   double            m_cumPV;
   double            m_cumV;
   int               m_closedCount;
   double            m_vwapBar1;
   double            m_vwapBar2;

   double            Typical(const MqlRates &r) const { return (r.open + r.high + r.low + r.close) / 4.0; }
   double            BarVolume(const MqlRates &r) const { return m_useReal ? (double)r.real_volume : (double)r.tick_volume; }

   bool              DetermineVolumeMode(void)
     {
      if(InpVwapVolume == OGP_VOL_TICK)
        {
         m_useReal = false;
         m_volumeKnown = true;
         return true;
        }
      if(InpVwapVolume == OGP_VOL_REAL)
        {
         m_useReal = true;
         m_volumeKnown = true;
         return true;
        }
      MqlRates rr[];
      int n = CopyRates(m_symbol, OGP_SIG_TF, 1, 200, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "volchk", "DATA", m_symbol, StringFormat("VWAP: cannot read M3 history to choose volume source (err %d)", GetLastError()), 60);
         return false;
        }
      int zeroReal = 0;
      for(int i = 0; i < n; i++)
         if(rr[i].real_volume <= 0)
            zeroReal++;
      bool useReal = (zeroReal == 0);
      if(!m_volumeKnown || useReal != m_useReal)
         Journal("DATA", m_symbol, StringFormat("VWAP volume source: %s (auto: %d bars checked, %d without real volume)",
                                                useReal ? "REAL" : "TICK", n, zeroReal));
      m_useReal = useReal;
      m_volumeKnown = true;
      return true;
     }

public:
                     CSessionVwap(void) : m_symbol(""), m_volumeKnown(false), m_useReal(false), m_anchorBar(0), m_lastClosed(0),
                     m_cacheValid(false), m_cumPV(0), m_cumV(0), m_closedCount(0), m_vwapBar1(0), m_vwapBar2(0) {}

   void              Init(const string sym) { m_symbol = sym; m_volumeKnown = false; Invalidate(); }
   void              Invalidate(void) { m_cacheValid = false; m_anchorBar = 0; m_lastClosed = 0; }
   string            VolumeType(void) const { return m_volumeKnown ? (m_useReal ? "REAL" : "TICK") : "?"; }
   int               ClosedCount(void) const { return m_closedCount; }
   datetime          AnchorBar(void) const { return m_anchorBar; }
   bool              Bar1Valid(void) const { return m_cacheValid && m_closedCount >= 1; }
   bool              Bar2Valid(void) const { return m_cacheValid && m_closedCount >= 2; }
   double            Bar1(void) const { return m_vwapBar1; }
   double            Bar2(void) const { return m_vwapBar2; }

   bool              UpdateClosed(const datetime anchor, const datetime lastClosed)
     {
      datetime anchorBar = (datetime)((long)anchor - ((long)anchor % OGP_M3_SEC));
      if(m_cacheValid && anchorBar == m_anchorBar && lastClosed == m_lastClosed)
         return true;
      if(anchorBar != m_anchorBar && InpVwapVolume == OGP_VOL_AUTO)
         m_volumeKnown = false;
      if(!m_volumeKnown && !DetermineVolumeMode())
        {
         m_cacheValid = false;
         return false;
        }
      m_anchorBar = anchorBar;
      m_lastClosed = lastClosed;
      m_cumPV = 0.0;
      m_cumV = 0.0;
      m_closedCount = 0;
      m_vwapBar1 = 0.0;
      m_vwapBar2 = 0.0;
      if(lastClosed < anchorBar)
        {
         m_cacheValid = true;
         return true;
        }
      MqlRates rr[];
      ResetLastError();
      int n = CopyRates(m_symbol, OGP_SIG_TF, anchorBar, lastClosed, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "vwapcopy", "DATA", m_symbol, StringFormat("VWAP: CopyRates M3 %s..%s failed (%d, err %d)",
                      Ts(anchorBar), Ts(lastClosed), n, GetLastError()), 60);
         m_cacheValid = false;
         return false;
        }
      for(int i = 0; i < n; i++)
        {
         if(rr[i].time < anchorBar || rr[i].time > lastClosed)
            continue;
         double v = BarVolume(rr[i]);
         m_cumPV += Typical(rr[i]) * v;
         m_cumV  += v;
         m_closedCount++;
         if(m_cumV > 0.0)
           {
            m_vwapBar2 = m_vwapBar1;
            m_vwapBar1 = m_cumPV / m_cumV;
           }
        }
      if(m_closedCount > 0 && m_cumV <= 0.0)
        {
         LogThrottled(m_symbol + "vwapzero", "DATA", m_symbol, StringFormat("VWAP invalid: %d bars since %s with zero %s volume",
                      m_closedCount, Ts(anchorBar), m_useReal ? "REAL" : "TICK"), 300);
         m_cacheValid = false;
         return false;
        }
      m_cacheValid = true;
      return true;
     }

   bool              Live(const MqlRates &bar0, double &vwap) const
     {
      if(!m_cacheValid || bar0.time < m_anchorBar)
         return false;
      double v = BarVolume(bar0);
      double vv = m_cumV + v;
      if(vv <= 0.0)
         return false;
      vwap = (m_cumPV + Typical(bar0) * v) / vv;
      return true;
     }
  };

#endif

//==================================================================
// ===== MODULE: OGP_Sessions.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Sessions.mqh - trading windows, VWAP anchors, rollover,      |
//|                    weekend handling, news filter                 |
//+------------------------------------------------------------------+
#ifndef OGP_SESSIONS_MQH
#define OGP_SESSIONS_MQH

#define OGP_MAX_SESSIONS 3

struct OgpSession
  {
   bool              enabled;
   string            name;
   ENUM_OGP_ZONE     zone;
   int               startMin;
   int               endMin;
  };

OgpSession g_sess[OGP_MAX_SESSIONS];
bool       g_sessWasIn[OGP_MAX_SESSIONS];
bool       g_sessLogInit = false;
int        g_rollStartMin = 0, g_rollEndMin = 0, g_friNoEntryMin = 0, g_friCloseMin = 0;

bool LoadSessionSlot(const int i, const bool en, const string name, const ENUM_OGP_ZONE zone, const string s, const string e)
  {
   g_sess[i].enabled = en;
   g_sess[i].name = name;
   g_sess[i].zone = zone;
   g_sess[i].startMin = 0;
   g_sess[i].endMin = 0;
   g_sessWasIn[i] = false;
   if(!en)
      return true;
   if(!ParseHHMM(s, g_sess[i].startMin) || !ParseHHMM(e, g_sess[i].endMin) || g_sess[i].startMin == g_sess[i].endMin)
     {
      OgpLog(StringFormat("INIT ERROR: session %d times '%s'-'%s' invalid (HH:MM, start != end)", i + 1, s, e));
      return false;
     }
   OgpLog(StringFormat("session %d [%s] %s-%s %s", i + 1, name, s, e, EnumToString(zone)));
   return true;
  }

bool SessionsInit()
  {
   bool ok = LoadSessionSlot(0, InpS1Enabled, InpS1Name, InpS1Zone, InpS1Start, InpS1End) &&
             LoadSessionSlot(1, InpS2Enabled, InpS2Name, InpS2Zone, InpS2Start, InpS2End) &&
             LoadSessionSlot(2, InpS3Enabled, InpS3Name, InpS3Zone, InpS3Start, InpS3End);
   ok = ok && ParseHHMM(InpRolloverStartNY, g_rollStartMin) && ParseHHMM(InpRolloverEndNY, g_rollEndMin) &&
        ParseHHMM(InpFridayNoEntryNY, g_friNoEntryMin) && ParseHHMM(InpFridayCloseNY, g_friCloseMin);
   if(!ok)
      OgpLog("INIT ERROR: invalid session / rollover / Friday time input");
   if(ok && InpUseSessionFilter && !InpTradeAllDay && !InpS1Enabled && !InpS2Enabled && !InpS3Enabled)
     {
      OgpLog("INIT ERROR: session filter on but no session enabled");
      ok = false;
     }
   g_sessLogInit = false;
   return ok;
  }

bool InMinuteRange(const int m, const int s, const int e)
  {
   if(s < e)
      return (m >= s && m < e);
   return (m >= s || m < e);    // crosses midnight
  }

bool SessionActive(const int i, const datetime server)
  {
   if(!g_sess[i].enabled)
      return false;
   datetime loc = ZoneLocal(g_sess[i].zone, server);
   int dow = DowOf(loc);
   if(dow == 0 || dow == 6)
      return false;
   return InMinuteRange(MinuteOfDay(loc), g_sess[i].startMin, g_sess[i].endMin);
  }

// Most recent occurrence (server time) of a zone-local start minute on allowed days
datetime MostRecentStart(const ENUM_OGP_ZONE zone, const int startMin, const int dowMask, const datetime server)
  {
   datetime loc = ZoneLocal(zone, server);
   long lt = (long)loc;
   long mid = lt - lt % 86400;
   for(int k = 0; k <= 8; k++)
     {
      long ls = mid + (long)startMin * 60 - (long)k * 86400;
      if(ls > lt)
         continue;
      if(((dowMask >> DowOf((datetime)ls)) & 1) == 0)
         continue;
      return (datetime)((long)server - (lt - ls));
     }
   return 0;
  }

// VWAP anchor: latest start of an enabled session (Mon-Fri) or metals daily open 18:00 NY (Sun-Thu)
datetime VwapAnchor(const datetime server)
  {
   datetime best = 0;
   for(int i = 0; i < OGP_MAX_SESSIONS; i++)
     {
      if(!g_sess[i].enabled)
         continue;
      datetime t = MostRecentStart(g_sess[i].zone, g_sess[i].startMin, 0x3E, server); // Mon..Fri
      if(t > best)
         best = t;
     }
   if(InpVwapDailyReset || best == 0)
     {
      datetime t = MostRecentStart(OGP_ZONE_NEWYORK, 18 * 60, 0x1F, server);           // Sun..Thu
      if(t > best)
         best = t;
     }
   return best;
  }

// Entry-time gate: sessions, rollover, Friday cut-off, weekend
bool TimeAllowsEntry(const datetime server, string &why, string &sessName)
  {
   sessName = "";
   datetime ny = NyLocal(server);
   int nyDow = DowOf(ny);
   int nyMin = MinuteOfDay(ny);
   if(nyDow == 6 || (nyDow == 0 && nyMin < 18 * 60))
     {
      why = "weekend";
      return false;
     }
   if(nyDow == 5 && nyMin >= g_friNoEntryMin)
     {
      why = "Friday cut-off (no new entries before weekend)";
      return false;
     }
   if(InpBlockRollover && InMinuteRange(nyMin, g_rollStartMin, g_rollEndMin))
     {
      why = "daily rollover block (wide spreads)";
      return false;
     }
   if(!InpUseSessionFilter || InpTradeAllDay)
     {
      sessName = "all-day";
      return true;
     }
   for(int i = 0; i < OGP_MAX_SESSIONS; i++)
      if(SessionActive(i, server))
        {
         sessName = g_sess[i].name;
         return true;
        }
   why = "outside configured trading sessions";
   return false;
  }

bool WeekendCloseDue(const datetime server)
  {
   if(!InpCloseBeforeWeekend)
      return false;
   datetime ny = NyLocal(server);
   return (DowOf(ny) == 5 && MinuteOfDay(ny) >= g_friCloseMin);
  }

void UpdateSessionLogs(const datetime server)
  {
   for(int i = 0; i < OGP_MAX_SESSIONS; i++)
     {
      if(!g_sess[i].enabled)
         continue;
      bool in = SessionActive(i, server);
      if(g_sessLogInit && in != g_sessWasIn[i])
         Journal("SESSION", "", StringFormat("session [%s] %s at %s server / %s New York", g_sess[i].name, in ? "START" : "END",
                                             Ts(server), TimeToString(NyLocal(server), TIME_MINUTES)));
      g_sessWasIn[i] = in;
     }
   g_sessLogInit = true;
  }

//==================================================================//
// News protection (MQL5 economic calendar)                         //
//  - Calendar data comes from MetaQuotes, is NOT available in the   //
//    Strategy Tester and can be incomplete or delayed live.         //
//  - Event times are trade-server time (MQL5 documentation).        //
//  - This filter only blocks NEW entries. The EA never places       //
//    pending orders, so it cannot straddle/bracket news (prohibited //
//    by Upcomers). Trading around news itself is allowed by Oracle; //
//    the block is a voluntary protection.                           //
//==================================================================//
class CNewsFilter
  {
private:
   datetime          m_times[];
   string            m_names[];
   datetime          m_lastRefresh;

public:
   bool              available;
   string            status;

                     CNewsFilter(void) : m_lastRefresh(0), available(false), status("not loaded") {}

   void              Refresh(const datetime server)
     {
      if(!InpUseNewsFilter)
        {
         available = false;
         status = "news filter OFF";
         return;
        }
      if(m_lastRefresh != 0 && server - m_lastRefresh < 900)
         return;
      m_lastRefresh = server;
      ArrayResize(m_times, 0);
      ArrayResize(m_names, 0);
      if(OgpIsTester())
        {
         available = false;
         status = "UNAVAILABLE in Strategy Tester (no calendar history)";
         return;
        }
      string cur[];
      int nc = StringSplit(InpNewsCurrencies, StringGetCharacter(",", 0), cur);
      bool anyOk = false;
      for(int c = 0; c < nc; c++)
        {
         string cc = cur[c];
         StringTrimLeft(cc);
         StringTrimRight(cc);
         if(cc == "")
            continue;
         MqlCalendarValue vals[];
         ResetLastError();
         int res = (int)CalendarValueHistory(vals, server - 3600, server + 86400, NULL, cc);
         int err = GetLastError();
         if(res <= 0 && err != 0)
           {
            status = StringFormat("calendar error %d for %s", err, cc);
            continue;
           }
         anyOk = true;
         for(int i = 0; i < ArraySize(vals); i++)
           {
            MqlCalendarEvent ev;
            if(!CalendarEventById(vals[i].event_id, ev))
               continue;
            bool important = (ev.importance == CALENDAR_IMPORTANCE_HIGH) ||
                             (!InpNewsHighOnly && ev.importance == CALENDAR_IMPORTANCE_MODERATE);
            if(!important)
               continue;
            int n = ArraySize(m_times);
            ArrayResize(m_times, n + 1);
            ArrayResize(m_names, n + 1);
            m_times[n] = vals[i].time;
            m_names[n] = cc + " " + ev.name;
           }
        }
      available = anyOk;
      if(anyOk)
         status = StringFormat("calendar OK, %d relevant events in next 24h", ArraySize(m_times));
      else
         LogThrottled("newsfail", "NEWS", "", "economic calendar UNAVAILABLE: " + status, 1800);
     }

   bool              Blocks(const datetime server, string &why)
     {
      if(!InpUseNewsFilter)
         return false;
      if(!available)
        {
         if(InpNewsFail == OGP_NEWS_FAIL_BLOCK)
           {
            why = "news data unavailable (configured to block)";
            return true;
           }
         return false;
        }
      for(int i = 0; i < ArraySize(m_times); i++)
        {
         if(server >= m_times[i] - InpNewsMinutesBefore * 60 && server <= m_times[i] + InpNewsMinutesAfter * 60)
           {
            why = StringFormat("news window: %s at %s", m_names[i], Ts(m_times[i]));
            return true;
           }
        }
      return false;
     }

   string            NextEvent(const datetime server) const
     {
      datetime best = 0;
      string nm = "";
      for(int i = 0; i < ArraySize(m_times); i++)
         if(m_times[i] >= server - InpNewsMinutesAfter * 60 && (best == 0 || m_times[i] < best))
           {
            best = m_times[i];
            nm = m_names[i];
           }
      if(best == 0)
         return "-";
      return TimeToString(best, TIME_MINUTES) + " " + nm;
     }
  };

#endif

//==================================================================
// ===== MODULE: OGP_Trade.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Trade.mqh - risk engine (position sizing) + order execution  |
//+------------------------------------------------------------------+
#ifndef OGP_TRADE_MQH
#define OGP_TRADE_MQH

#define OGP_INF_RISK 1.0e12

//==================================================================//
// Risk accounting                                                  //
//==================================================================//
// Loss (positive number, account currency) of moving `vol` lots from `from` to `to`
double MoveLoss(const string sym, const int dir, const double vol, const double from, const double to)
  {
   double p = 0.0;
   if(!OrderCalcProfit(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, vol, from, to, p))
      return OGP_INF_RISK;
   return (p < 0.0) ? -p : 0.0;
  }

struct OgpRiskSummary
  {
   double            eaRiskFromEntry;   // EA positions: entry -> SL (+costs), "planned risk"
   double            allRiskFromNow;    // ALL positions: current price -> SL (+slippage), further equity at risk
   int               eaPositions;
   int               otherPositions;
   int               unprotected;       // positions without stop-loss (any magic)
   string            eaSyms[];
   int               eaDirs[];
  };

double SlippageFor(const string sym);       // defined in main file (per-symbol inputs)

void BuildRiskSummary(OgpRiskSummary &rs)
  {
   rs.eaRiskFromEntry = 0.0;
   rs.allRiskFromNow = 0.0;
   rs.eaPositions = 0;
   rs.otherPositions = 0;
   rs.unprotected = 0;
   ArrayResize(rs.eaSyms, 0);
   ArrayResize(rs.eaDirs, 0);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      double vol = PositionGetDouble(POSITION_VOLUME);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double cur = PositionGetDouble(POSITION_PRICE_CURRENT);
      bool mine = ((ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic);
      double slip = mine ? SlippageFor(sym) : 0.0;
      if(mine)
        {
         rs.eaPositions++;
         int n = ArraySize(rs.eaSyms);
         ArrayResize(rs.eaSyms, n + 1);
         ArrayResize(rs.eaDirs, n + 1);
         rs.eaSyms[n] = sym;
         rs.eaDirs[n] = dir;
        }
      else
         rs.otherPositions++;
      if(sl <= 0.0)
        {
         rs.unprotected++;
         rs.allRiskFromNow += OGP_INF_RISK;
         if(mine)
            rs.eaRiskFromEntry += OGP_INF_RISK;
         continue;
        }
      double slipLoss = (slip > 0.0) ? MoveLoss(sym, dir, vol, sl, sl - dir * slip) : 0.0;
      rs.allRiskFromNow += MoveLoss(sym, dir, vol, cur, sl) + slipLoss;
      if(mine)
         rs.eaRiskFromEntry += MoveLoss(sym, dir, vol, open, sl) + slipLoss + InpCommissionPerLot * vol;
     }
  }

// Position sizing. Returns false (with reason) if the trade must be skipped.
// fixedLots > 0: fixed-lot mode (lots never increased, only reduced to fit the caps)
// riskShare: share of the per-signal risk given to this position (risk mode)
bool ComputeLots(const string sym, const int dir, const double entry, const double sl, const double slip,
                 const double fixedLots, const double riskShare,
                 const OgpRiskSummary &rs, CAccountMonitor &acc, COracleRules &rules,
                 double &lots, double &plannedLoss, string &capInfo, string &why)
  {
   double init = InpInitialBalance;
   bool fixedMode = (fixedLots > 0.0);
   double riskMoney = fixedMode ? OGP_INF_RISK : acc.equity * InpRiskPct / 100.0 * riskShare;
   capInfo = fixedMode ? StringFormat("fixed %.2f lots", fixedLots)
                       : StringFormat("base %.2f%% x %.2f of equity=%s", InpRiskPct, riskShare, Usd(riskMoney));

   //--- correlation: other metal already open in the same direction
   for(int i = 0; i < ArraySize(rs.eaSyms); i++)
     {
      if(rs.eaSyms[i] == sym)
         continue;
      if(rs.eaDirs[i] == dir)
        {
         riskMoney *= InpCorrelatedRiskFactor;
         capInfo += StringFormat(", correlated x%.2f", InpCorrelatedRiskFactor);
        }
      else
         if(InpBlockOppositeMetals)
           {
            why = "opposite-direction metal position open (InpBlockOppositeMetals)";
            return false;
           }
     }

   double capTotal  = init * InpMaxTotalRiskPct / 100.0 - rs.eaRiskFromEntry;
   double capSingle = MinD(InpMaxSingleTradeLossUSD, rules.singleTradeLimit * 0.5);
   double capLock   = InpDailyLossLockUSD - (acc.dayStartEquity - acc.equity) - rs.allRiskFromNow;
   double capDaily  = (acc.equity - rules.dailyFloor - InpFloorSafetyUSD) - rs.allRiskFromNow;
   double capShield = (acc.equity - rules.shieldFloor - InpFloorSafetyUSD) - rs.allRiskFromNow;

   double allowed = riskMoney;
   string binding = fixedMode ? "none" : "risk%";
   if(capTotal < allowed)
     {
      allowed = capTotal;
      binding = "combined-risk cap";
     }
   if(capSingle < allowed)
     {
      allowed = capSingle;
      binding = "single-trade cap";
     }
   if(capLock < allowed)
     {
      allowed = capLock;
      binding = "internal daily lock headroom";
     }
   if(capDaily < allowed)
     {
      allowed = capDaily;
      binding = "daily-drawdown headroom";
     }
   if(capShield < allowed)
     {
      allowed = capShield;
      binding = "shield headroom";
     }
   capInfo += StringFormat(" | caps total=%s single=%s lock=%s daily=%s shield=%s -> allowed %s (%s)",
                           Usd(capTotal), Usd(capSingle), Usd(capLock), Usd(capDaily), Usd(capShield), Usd(allowed), binding);
   if(allowed <= 0.0)
     {
      why = "no risk budget left (" + binding + ")";
      return false;
     }

   double lossPerLot = MoveLoss(sym, dir, 1.0, entry, sl) + MoveLoss(sym, dir, 1.0, sl, sl - dir * slip) + InpCommissionPerLot;
   if(lossPerLot <= 0.0 || lossPerLot >= OGP_INF_RISK)
     {
      why = StringFormat("cannot compute loss per lot (OrderCalcProfit err %d)", GetLastError());
      return false;
     }
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = vmin;
   double raw = allowed / lossPerLot;
   double v = NormalizeDouble(MathFloor(raw / step + 1e-9) * step, VolumeDigits(step));
   if(fixedMode)
     {
      double fx = NormalizeDouble(MathFloor(fixedLots / step + 1e-9) * step, VolumeDigits(step));
      if(v >= fx)
         v = fx;
      else
         capInfo += StringFormat(" | fixed %.2f REDUCED to %.2f by %s", fx, v, binding);
     }
   if(v < vmin - 1e-10)
     {
      why = StringFormat("minimum lot %.2f would risk %s > allowed %s", vmin, Usd(vmin * lossPerLot), Usd(allowed));
      return false;
     }
   if(vmax > 0.0 && v > vmax)
      v = NormalizeDouble(MathFloor(vmax / step + 1e-9) * step, VolumeDigits(step));
   double vlimit = SymbolInfoDouble(sym, SYMBOL_VOLUME_LIMIT);
   if(vlimit > 0.0 && v > vlimit)
     {
      why = StringFormat("symbol volume limit %.2f", vlimit);
      return false;
     }
   lots = v;
   plannedLoss = v * lossPerLot;
   capInfo += StringFormat(" | loss/lot %s -> %.2f lots, planned loss %s", Usd(lossPerLot), lots, Usd(plannedLoss));
   if(plannedLoss > rules.singleTradeLimit)
     {
      why = "planned loss exceeds Oracle single-trade limit";
      return false;
     }
   return true;
  }

//==================================================================//
// Execution                                                        //
//==================================================================//
ENUM_ORDER_TYPE_FILLING FillingCandidate(const string sym, const int idx, int &count)
  {
   ENUM_ORDER_TYPE_FILLING list[3];
   count = 0;
   long fm = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   if((fm & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      list[count++] = ORDER_FILLING_FOK;
   if((fm & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      list[count++] = ORDER_FILLING_IOC;
   list[count++] = ORDER_FILLING_RETURN;
   return list[(idx < count) ? idx : count - 1];
  }

bool TradingPermitted(string &why)
  {
   if(!OgpIsTester() && !TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      why = "terminal not connected";
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      why = "AutoTrading disabled in terminal";
      return false;
     }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      why = "algo trading not allowed for this EA";
      return false;
     }
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
     {
      why = "account does not allow (expert) trading";
      return false;
     }
   return true;
  }

double MinStopDistance(const string sym)
  {
   double pt = SymPoint(sym);
   long lvl = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   long frz = SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   return (double)((lvl > frz ? lvl : frz) + 2) * pt;
  }

// Send a market DEAL (open when req.position==0, close otherwise).
// slDist/tpDist (price distance) are re-applied to the fresh price on each attempt.
// Never retries TIMEOUT / CONNECTION (a retry could duplicate a filled order).
// slAbs/tpAbs > 0 override the distances with fixed price levels (shared SL/target).
bool SendDeal(MqlTradeRequest &req, const double slDist, const double tpDist, const string ctx, MqlTradeResult &res,
              const double slAbs = 0.0, const double tpAbs = 0.0)
  {
   string sym = req.symbol;
   int fillIdx = 0;
   int maxRetries = (InpOrderRetries > 0) ? InpOrderRetries : 0;
   for(int attempt = 0; attempt <= maxRetries; attempt++)
     {
      MqlTick t;
      if(!SymbolInfoTick(sym, t) || t.bid <= 0.0 || t.ask <= 0.0)
        {
         Journal("ORDER", sym, ctx + " FAILED: no valid quote");
         return false;
        }
      bool isBuy = (req.type == ORDER_TYPE_BUY);
      req.price = NormalizePrice(sym, isBuy ? t.ask : t.bid);
      if(req.position == 0)
        {
         req.sl = (slDist > 0.0) ? NormalizePrice(sym, isBuy ? req.price - slDist : req.price + slDist) : 0.0;
         req.tp = (tpDist > 0.0) ? NormalizePrice(sym, isBuy ? req.price + tpDist : req.price - tpDist) : 0.0;
         if(slAbs > 0.0)
            req.sl = NormalizePrice(sym, slAbs);
         if(tpAbs > 0.0)
            req.tp = NormalizePrice(sym, tpAbs);
         double minD = MinStopDistance(sym);
         if(req.sl > 0.0 && (isBuy ? req.price - req.sl : req.sl - req.price) < minD)
           {
            Journal("ORDER", sym, ctx + " REFUSED: price already too close to the stop-loss " + Px(sym, req.sl));
            return false;
           }
         if(req.tp > 0.0 && (isBuy ? req.tp - req.price : req.price - req.tp) < minD)
           {
            Journal("ORDER", sym, ctx + " REFUSED: price already at/through the target " + Px(sym, req.tp));
            return false;
           }
        }
      int fillCount = 0;
      req.type_filling = FillingCandidate(sym, fillIdx, fillCount);

      MqlTradeCheckResult chk;
      ZeroMemory(chk);
      ResetLastError();
      if(!OrderCheck(req, chk))
        {
         Journal("ORDER", sym, StringFormat("%s REJECTED by OrderCheck: %s (%u) '%s' vol=%.2f margin=%s free=%s",
                                            ctx, RetcodeText(chk.retcode), chk.retcode, chk.comment, req.volume,
                                            Usd(chk.margin), Usd(chk.margin_free)));
         if(chk.retcode == TRADE_RETCODE_INVALID_FILL && fillIdx + 1 < fillCount)
           {
            fillIdx++;
            continue;
           }
         return false;
        }
      ZeroMemory(res);
      ResetLastError();
      bool sent = OrderSend(req, res);
      if(sent && (res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_DONE_PARTIAL || res.retcode == TRADE_RETCODE_PLACED))
        {
         Journal("ORDER", sym, StringFormat("%s OK: %s order #%I64u deal #%I64u vol=%.2f price=%s (req %s) sl=%s tp=%s",
                                            ctx, RetcodeText(res.retcode), res.order, res.deal, res.volume, Px(sym, res.price),
                                            Px(sym, req.price), Px(sym, req.sl), Px(sym, req.tp)));
         return true;
        }
      Journal("ORDER", sym, StringFormat("%s FAILED (attempt %d/%d): %s (%u) '%s' err=%d",
                                         ctx, attempt + 1, maxRetries + 1, RetcodeText(res.retcode), res.retcode, res.comment, GetLastError()));
      if(res.retcode == TRADE_RETCODE_INVALID_FILL && fillIdx + 1 < fillCount)
        {
         fillIdx++;
         continue;
        }
      if(res.retcode != TRADE_RETCODE_REQUOTE && res.retcode != TRADE_RETCODE_PRICE_CHANGED && res.retcode != TRADE_RETCODE_PRICE_OFF)
         return false;
     }
   return false;
  }

bool ModifyStops(const ulong ticket, const double sl, const double tp, const string reason)
  {
   if(!PositionSelectByTicket(ticket))
      return false;
   string sym = PositionGetString(POSITION_SYMBOL);
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action = TRADE_ACTION_SLTP;
   req.position = ticket;
   req.symbol = sym;
   req.sl = (sl > 0.0) ? NormalizePrice(sym, sl) : 0.0;
   req.tp = (tp > 0.0) ? NormalizePrice(sym, tp) : 0.0;
   req.magic = InpMagic;
   ResetLastError();
   bool ok = OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE;
   Journal("MODIFY", sym, StringFormat("#%I64u %s sl=%s tp=%s -> %s (%u) %s", ticket, reason, Px(sym, req.sl), Px(sym, req.tp),
                                       ok ? "OK" : "FAILED", res.retcode, ok ? "" : RetcodeText(res.retcode)));
   return ok;
  }

bool ClosePositionTicket(const ulong ticket, const string reason)
  {
   if(!PositionSelectByTicket(ticket))
      return true;
   string sym = PositionGetString(POSITION_SYMBOL);
   int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
   double vol = PositionGetDouble(POSITION_VOLUME);
   double pl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = sym;
   req.position  = ticket;
   req.volume    = vol;
   req.type      = (dir > 0) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   req.deviation = (ulong)InpMaxDeviationPoints;
   req.magic     = InpMagic;
   req.comment   = InpOrderComment + " exit";
   req.type_time = ORDER_TIME_GTC;
   bool ok = SendDeal(req, 0.0, 0.0, StringFormat("CLOSE %s #%I64u %.2f lots (%s, floating %s)", dir > 0 ? "BUY" : "SELL",
                                                  ticket, vol, reason, Usd(pl)), res);
   if(ok && PositionSelectByTicket(ticket))
      return false;     // partial
   return ok;
  }

// Opens a position with a mandatory stop-loss. If the fill has no SL, the SL is
// set immediately; if that fails the position is closed (never left unprotected).
bool OpenWithStop(const string sym, const int dir, const double lots, const double slDist, const double tpDist, const string comment,
                  ulong &ticketOut, const double slAbs = 0.0, const double tpAbs = 0.0)
  {
   ticketOut = 0;
   if(slDist <= 0.0 && slAbs <= 0.0)
     {
      Journal("ORDER", sym, "refused: no stop-loss distance");
      return false;
     }
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = sym;
   req.volume    = lots;
   req.type      = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.deviation = (ulong)InpMaxDeviationPoints;
   req.magic     = InpMagic;
   req.comment   = comment;
   req.type_time = ORDER_TIME_GTC;
   if(!SendDeal(req, slDist, tpDist, StringFormat("OPEN %s %.2f lots [%s]", dir > 0 ? "BUY" : "SELL", lots, comment), res, slAbs, tpAbs))
      return false;
   ticketOut = res.order;     // hedging: position ticket == opening order ticket

   //--- verify the stop on the resulting position
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetDouble(POSITION_SL) > 0.0)
         continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = (slAbs > 0.0) ? slAbs : ((dir > 0) ? open - slDist : open + slDist);
      double tp = (tpAbs > 0.0) ? tpAbs : ((tpDist > 0.0) ? ((dir > 0) ? open + tpDist : open - tpDist) : 0.0);
      Journal("ORDER", sym, StringFormat("position #%I64u has NO stop-loss after fill - setting it now", t));
      if(!ModifyStops(t, sl, tp, "attach missing SL"))
        {
         Journal("ORDER", sym, StringFormat("could not attach SL to #%I64u - CLOSING it", t));
         ClosePositionTicket(t, "unprotected after fill");
        }
     }
   return true;
  }

#endif

//==================================================================
// ===== MODULE: OGP_Strategy.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Strategy.mqh - per-symbol data, signal detection, filters    |
//|                                                                  |
//| Signal: EMA(9, Close, M3) crossing the session VWAP (OHLC/4).    |
//|  Confirmed mode (default): sign(EMA-VWAP) differs between closed |
//|   bars [2] and [1]; evaluated once, on the first tick of bar[0]. |
//|  Live mode: sign(liveEMA-liveVWAP) changes tick-to-tick; the     |
//|   baseline is tracked on every tick, one attempt per bar.        |
//| Filters are independent modules; each returns a reason.          |
//+------------------------------------------------------------------+
#ifndef OGP_STRATEGY_MQH
#define OGP_STRATEGY_MQH

enum ENUM_OGP_EVAL
  {
   OGP_EVAL_OK     = 0,
   OGP_EVAL_REJECT = 1,
   OGP_EVAL_CHASED = 2
  };

struct OgpEntryIntent
  {
   int               dir;
   double            entry;
   double            slDist;
   double            tpDist;
   string            source;   // "confirmed" / "live" / "pullback"
   string            detail;
  };

class COgpSymbol
  {
private:
   int               m_hEma;
   int               m_hAtr;
   int               m_hT15;
   int               m_hT60;
   long              m_lastTickMsc;
   datetime          m_lastTickTime;
   int               m_prevSign;
   datetime          m_signAnchor;
   bool              m_firstRun;
   int               m_need;

   int               SignOf(const double diff) const
     {
      if(diff > 0.0)
         return 1;
      if(diff < 0.0)
         return -1;
      return 0;
     }

   bool              TrendOk(const int handle, const ENUM_TIMEFRAMES tf, const int dir, string &txt)
     {
      double e[];
      ArraySetAsSeries(e, true);
      int need = InpTrendSlopeBars + 2;
      if(CopyBuffer(handle, 0, 1, need, e) != need)
        {
         txt = "no data";
         return false;
        }
      double c = iClose(sym, tf, 1);
      if(c <= 0.0)
        {
         txt = "no close";
         return false;
        }
      bool up = (c > e[0] && e[0] > e[InpTrendSlopeBars]);
      bool dn = (c < e[0] && e[0] < e[InpTrendSlopeBars]);
      txt = up ? "UP" : (dn ? "DOWN" : "FLAT");
      return (dir > 0) ? up : dn;
     }

   double            HighestHigh(const int from, const int count) const
     {
      double h = r[from].high;
      for(int i = from + 1; i < from + count && i < ArraySize(r); i++)
         h = MaxD(h, r[i].high);
      return h;
     }

   double            LowestLow(const int from, const int count) const
     {
      double l = r[from].low;
      for(int i = from + 1; i < from + count && i < ArraySize(r); i++)
         l = MinD(l, r[i].low);
      return l;
     }

   bool              BreakoutOk(const int dir, string &why)
     {
      int L = InpBreakoutLookback;
      double a = atr[1];
      double body = r[1].close - r[1].open;
      if(!InpBreakoutRetest)
        {
         double lvl = (dir > 0) ? HighestHigh(2, L) : LowestLow(2, L);
         bool brk = (dir > 0) ? (r[1].close > lvl) : (r[1].close < lvl);
         bool mom = (dir > 0) ? (body >= InpMomentumBodyAtr * a) : (-body >= InpMomentumBodyAtr * a);
         if(brk || mom)
            return true;
         why = StringFormat("breakout filter: no close beyond %s swing %s and no momentum bar", dir > 0 ? "high" : "low", Px(sym, lvl));
         return false;
        }
      for(int k = 2; k <= InpBreakRetestMaxBars + 1; k++)
        {
         double lvl = (dir > 0) ? HighestHigh(k + 1, L) : LowestLow(k + 1, L);
         bool broke = (dir > 0) ? (r[k].close > lvl) : (r[k].close < lvl);
         if(!broke)
            continue;
         double tol = 0.1 * a;
         bool retest = (dir > 0) ? (r[1].low <= lvl + tol && r[1].close > lvl) : (r[1].high >= lvl - tol && r[1].close < lvl);
         if(retest)
            return true;
        }
      why = "breakout filter: no break + retest within " + IntegerToString(InpBreakRetestMaxBars) + " bars";
      return false;
     }

public:
   string            sym;
   bool              isGold;
   double            minAtr;
   double            maxAtr;
   double            maxSpread;
   double            slip;
   double            slBuffer;
   CSessionVwap      vwap;
   MqlRates          r[];
   double            ema[];
   double            atr[];
   MqlTick           tick;
   double            vwapLive;
   bool              vwapLiveOk;
   bool              newBar;
   bool              dataOk;
   datetime          curBar;
   //--- re-entry / pullback state
   int               lastEntryDir;
   bool              rearmed;
   datetime          lastEntryBar;
   bool              pbActive;
   int               pbDir;
   int               pbBarsLeft;
   //--- second position (retest) state
   bool              s2Active;
   int               s2Dir;
   double            s2Sl;          // shared absolute stop-loss of the signal
   double            s2Tp;          // shared absolute target of the signal
   ulong             s2Ticket1;     // ticket of position #1
   datetime          s2Bar1;        // bar of entry #1
   int               s2BarsLeft;
   //--- display
   string            lastSignal;
   string            lastDecision;
   string            trendText;

                     COgpSymbol(void) : m_hEma(INVALID_HANDLE), m_hAtr(INVALID_HANDLE), m_hT15(INVALID_HANDLE), m_hT60(INVALID_HANDLE),
                     m_lastTickMsc(0), m_lastTickTime(0), m_prevSign(0), m_signAnchor(0), m_firstRun(true), m_need(0), sym(""),
                     isGold(true), minAtr(0), maxAtr(0), maxSpread(0), slip(0), slBuffer(0), vwapLive(0), vwapLiveOk(false),
                     newBar(false), dataOk(false), curBar(0), lastEntryDir(0), rearmed(true), lastEntryBar(0), pbActive(false),
                     pbDir(0), pbBarsLeft(0), s2Active(false), s2Dir(0), s2Sl(0), s2Tp(0), s2Ticket1(0), s2Bar1(0),
                     s2BarsLeft(0), lastSignal("-"), lastDecision("-"), trendText("-") {}

   bool              Init(const string s, const bool gold)
     {
      sym = s;
      isGold = gold;
      minAtr    = gold ? InpGoldMinAtr : InpSilverMinAtr;
      maxAtr    = gold ? InpGoldMaxAtr : InpSilverMaxAtr;
      maxSpread = gold ? InpGoldMaxSpread : InpSilverMaxSpread;
      slip      = gold ? InpGoldSlippage : InpSilverSlippage;
      slBuffer  = gold ? InpGoldSlBuffer : InpSilverSlBuffer;
      vwap.Init(s);
      ArraySetAsSeries(r, true);
      ArraySetAsSeries(ema, true);
      ArraySetAsSeries(atr, true);
      int a = InpBreakoutLookback + InpBreakRetestMaxBars + 4;
      int b = InpSwingLookback + 3;
      m_need = (a > b) ? a : b;
      if(m_need < 30)
         m_need = 30;

      m_hEma = iMA(s, OGP_SIG_TF, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      m_hAtr = iATR(s, OGP_SIG_TF, InpAtrPeriod);
      m_hT15 = iMA(s, PERIOD_M15, InpTrendEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      m_hT60 = iMA(s, PERIOD_H1, InpTrendEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(m_hEma == INVALID_HANDLE || m_hAtr == INVALID_HANDLE || m_hT15 == INVALID_HANDLE || m_hT60 == INVALID_HANDLE)
        {
         OgpLog(StringFormat("INIT ERROR %s: indicator handle creation failed (err %d)", s, GetLastError()));
         return false;
        }
      Journal("SYSTEM", s, StringFormat("ready: digits=%d point=%s tick=%s tickValue=%.4f contract=%.2f vol %.2f/%.2f/%.2f stops=%d freeze=%d spread=%d pts exec=%s",
                                        SymDigits(s), DoubleToString(SymPoint(s), SymDigits(s)),
                                        DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE), SymDigits(s)),
                                        SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE), SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE),
                                        SymbolInfoDouble(s, SYMBOL_VOLUME_MIN), SymbolInfoDouble(s, SYMBOL_VOLUME_STEP),
                                        SymbolInfoDouble(s, SYMBOL_VOLUME_MAX), (int)SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL),
                                        (int)SymbolInfoInteger(s, SYMBOL_TRADE_FREEZE_LEVEL), (int)SymbolInfoInteger(s, SYMBOL_SPREAD),
                                        EnumToString((ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(s, SYMBOL_TRADE_EXEMODE))));
      return true;
     }

   void              Deinit(void)
     {
      if(m_hEma != INVALID_HANDLE)
         IndicatorRelease(m_hEma);
      if(m_hAtr != INVALID_HANDLE)
         IndicatorRelease(m_hAtr);
      if(m_hT15 != INVALID_HANDLE)
         IndicatorRelease(m_hT15);
      if(m_hT60 != INVALID_HANDLE)
         IndicatorRelease(m_hT60);
      m_hEma = INVALID_HANDLE;
      m_hAtr = INVALID_HANDLE;
      m_hT15 = INVALID_HANDLE;
      m_hT60 = INVALID_HANDLE;
     }

   void              ResetBaseline(const string why)
     {
      if(m_prevSign != 0)
         Journal("SIGNAL", sym, "live cross baseline reset: " + why);
      m_prevSign = 0;
     }

   void              OnReconnect(void)
     {
      ResetBaseline("reconnect");
      vwap.Invalidate();
     }

   //--- load fresh data; returns true only when a NEW tick was processed
   bool              Refresh(const datetime anchor)
     {
      newBar = false;
      if(!SymbolInfoTick(sym, tick) || tick.bid <= 0.0)
        {
         LogThrottled(sym + "tick", "DATA", sym, StringFormat("no tick (err %d)", GetLastError()), 60);
         return false;
        }
      if(tick.time_msc == m_lastTickMsc)
         return false;
      dataOk = false;
      int bars = Bars(sym, OGP_SIG_TF);
      int need = (m_need > InpEmaPeriod * 5) ? m_need : InpEmaPeriod * 5;
      if(bars < need || BarsCalculated(m_hEma) < need || BarsCalculated(m_hAtr) < need)
        {
         LogThrottled(sym + "ready", "DATA", sym, StringFormat("waiting for M3 history / indicators (%d bars, need %d)", bars, need), 60);
         ResetBaseline("data not ready");
         return false;
        }
      ResetLastError();
      if(CopyRates(sym, OGP_SIG_TF, 0, m_need, r) != m_need || CopyBuffer(m_hEma, 0, 0, 3, ema) != 3 || CopyBuffer(m_hAtr, 0, 0, 3, atr) != 3)
        {
         LogThrottled(sym + "copy", "DATA", sym, StringFormat("CopyRates/CopyBuffer failed (err %d)", GetLastError()), 60);
         ResetBaseline("copy failed");
         return false;
        }
      if(ema[1] == EMPTY_VALUE || atr[1] == EMPTY_VALUE || atr[1] <= 0.0)
        {
         LogThrottled(sym + "empty", "DATA", sym, "indicator values empty", 60);
         return false;
        }
      if(m_lastTickTime > 0 && (long)(tick.time - m_lastTickTime) > 180)
         ResetBaseline(StringFormat("tick gap %I64d s", (long)(tick.time - m_lastTickTime)));
      m_lastTickMsc = tick.time_msc;
      m_lastTickTime = tick.time;

      vwapLiveOk = false;
      if(anchor > 0 && vwap.UpdateClosed(anchor, r[1].time))
         vwapLiveOk = vwap.Live(r[0], vwapLive);

      newBar = (r[0].time != curBar);
      if(newBar)
        {
         m_firstRun = (curBar == 0);
         curBar = r[0].time;
         if(InpLogEveryBar)
            Journal("DATA", sym, StringFormat("bar %s C=%s EMA=%s VWAP=%s(%s,%d bars) ATR=%s spread=%s",
                                              Ts(r[1].time), Px(sym, r[1].close), Px(sym, ema[1]),
                                              vwap.Bar1Valid() ? Px(sym, vwap.Bar1()) : "n/a", vwap.VolumeType(), vwap.ClosedCount(),
                                              Px(sym, atr[1]), Px(sym, tick.ask - tick.bid)));
        }
      dataOk = true;
      return true;
     }

   //--- crossover detection (confirmed or live). 0 = none
   int               DetectCross(const datetime anchor)
     {
      bool enoughBars = vwap.ClosedCount() > InpMinBarsAfterReset;
      if(InpEntryMode == OGP_ENTRY_CONFIRMED)
        {
         if(!newBar || m_firstRun || !vwap.Bar2Valid() || !enoughBars)
            return 0;
         int s2 = SignOf(ema[2] - vwap.Bar2());
         int s1 = SignOf(ema[1] - vwap.Bar1());
         return (s2 != 0 && s1 != 0 && s1 != s2) ? s1 : 0;
        }
      //--- live
      if(!vwapLiveOk)
        {
         ResetBaseline("live VWAP unavailable");
         return 0;
        }
      if(anchor != m_signAnchor)
        {
         m_signAnchor = anchor;
         m_prevSign = 0;            // VWAP reset is not a crossover
        }
      int s = SignOf(ema[0] - vwapLive);
      int dir = 0;
      if(s != 0)
        {
         if(m_prevSign != 0 && s != m_prevSign && enoughBars)
            dir = s;
         m_prevSign = s;
        }
      return dir;
     }

   //--- called for every detected cross, accepted or not
   void              OnCrossObserved(const int dir)
     {
      if(lastEntryDir != 0 && dir != lastEntryDir)
         rearmed = true;
      if(s2Active && dir != s2Dir)
         CancelSecond("opposite cross");
      if(pbActive && dir != pbDir)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup cancelled by opposite cross");
        }
     }

   void              OnEntry(const int dir)
     {
      s2Active = false;
      lastEntryDir = dir;
      rearmed = false;
      lastEntryBar = curBar;
      pbActive = false;
     }

   //--- second position: armed after entry #1 in ON_RETEST mode
   void              ArmSecond(const int dir, const double sl, const double tp, const ulong ticket1)
     {
      s2Active = true;
      s2Dir = dir;
      s2Sl = sl;
      s2Tp = tp;
      s2Ticket1 = ticket1;
      s2Bar1 = curBar;
      s2BarsLeft = InpRetestMaxBars;
      Journal("SIGNAL", sym, StringFormat("position #2 armed: waiting up to %d bars for a retest of EMA/VWAP (+-%.2f ATR), shared SL %s / target %s",
                                          InpRetestMaxBars, InpRetestZoneAtr, Px(sym, sl), tp > 0.0 ? Px(sym, tp) : "none"));
     }

   void              CancelSecond(const string why)
     {
      if(!s2Active)
         return;
      s2Active = false;
      Journal("SIGNAL", sym, "position #2 cancelled: " + why);
     }

   //--- returns true when the retest condition for position #2 is met now
   bool              CheckSecond(void)
     {
      if(!s2Active || !dataOk)
         return false;
      if(!PositionSelectByTicket(s2Ticket1))
        {
         CancelSecond("position #1 already closed");
         return false;
        }
      if(newBar && curBar != s2Bar1)
        {
         s2BarsLeft--;
         if(s2BarsLeft < 0)
           {
            CancelSecond("no retest within " + IntegerToString(InpRetestMaxBars) + " bars");
            return false;
           }
        }
      if(curBar == s2Bar1 || !vwap.Bar1Valid())
         return false;                       // never on the same bar as entry #1
      double e1 = ema[1], v1 = vwap.Bar1(), a = atr[1];
      if(SignOf(e1 - v1) != s2Dir)
        {
         CancelSecond("EMA crossed back through VWAP (setup invalid)");
         return false;
        }
      double zoneTop = MaxD(e1, v1) + InpRetestZoneAtr * a;   // buy: pull back down into here
      double zoneBot = MinD(e1, v1) - InpRetestZoneAtr * a;   // sell: pull back up into here
      if(InpRetestNeedsClose)
        {
         if(!newBar)
            return false;
         if(s2Dir > 0)
            return (r[1].low <= zoneTop && r[1].close > v1 && r[1].close > r[1].open);
         return (r[1].high >= zoneBot && r[1].close < v1 && r[1].close < r[1].open);
        }
      if(s2Dir > 0)
         return (tick.ask <= zoneTop && tick.bid > s2Sl);
      return (tick.bid >= zoneBot && tick.ask < s2Sl);
     }

   //--- pullback re-entry check on each new bar. 0 = none
   int               CheckPullback(void)
     {
      if(!pbActive || !newBar || !vwap.Bar1Valid())
         return 0;
      pbBarsLeft--;
      if(pbBarsLeft < 0)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup expired");
         return 0;
        }
      double e1 = ema[1], v1 = vwap.Bar1(), a = atr[1];
      if(SignOf(e1 - v1) != pbDir)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup invalid: EMA back on the other side of VWAP");
         return 0;
        }
      bool trig = (pbDir > 0) ? (r[1].low <= MaxD(e1, v1) + InpPullbackZoneAtr * a && r[1].close > e1 && r[1].close > v1)
                  : (r[1].high >= MinD(e1, v1) - InpPullbackZoneAtr * a && r[1].close < e1 && r[1].close < v1);
      return trig ? pbDir : 0;
     }

   void              ArmPullback(const int dir)
     {
      pbActive = true;
      pbDir = dir;
      pbBarsLeft = InpPullbackMaxBars;
      Journal("SIGNAL", sym, StringFormat("%s cross skipped (price extended) -> waiting up to %d bars for pullback to EMA/VWAP zone + confirmation",
                                          dir > 0 ? "BUY" : "SELL", InpPullbackMaxBars));
     }

   //--- strategy filters + stop/target. Order of checks = order of reasons.
   ENUM_OGP_EVAL     Evaluate(const int dir, const string source, OgpEntryIntent &it, string &why)
     {
      double a = atr[1];
      double spread = tick.ask - tick.bid;
      it.dir = dir;
      it.source = source;
      it.entry = (dir > 0) ? tick.ask : tick.bid;

      if(InpRequireNewSignal && source != "pullback" && lastEntryDir == dir && !rearmed)
        {
         why = "no new independent signal since last " + (dir > 0 ? string("BUY") : string("SELL")) + " entry (needs opposite cross first)";
         return OGP_EVAL_REJECT;
        }
      //--- volatility / spread (safety, always on)
      if(a < minAtr)
        {
         why = StringFormat("volatility too low: ATR %s < %s", Px(sym, a), Px(sym, minAtr));
         return OGP_EVAL_REJECT;
        }
      if(a > maxAtr)
        {
         why = StringFormat("abnormal volatility: ATR %s > %s", Px(sym, a), Px(sym, maxAtr));
         return OGP_EVAL_REJECT;
        }
      if(r[1].high - r[1].low > InpMaxBarRangeAtr * a)
        {
         why = StringFormat("spike bar: range %s > %.1f x ATR", Px(sym, r[1].high - r[1].low), InpMaxBarRangeAtr);
         return OGP_EVAL_REJECT;
        }
      if(spread > maxSpread)
        {
         why = StringFormat("spread %s > max %s", Px(sym, spread), Px(sym, maxSpread));
         return OGP_EVAL_REJECT;
        }
      if(spread > InpMaxSpreadToAtr * a)
        {
         why = StringFormat("spread %s > %.2f x ATR", Px(sym, spread), InpMaxSpreadToAtr);
         return OGP_EVAL_REJECT;
        }
      //--- higher-timeframe trend
      string t15 = "-", t60 = "-";
      if(InpUseTrendM15 && !TrendOk(m_hT15, PERIOD_M15, dir, t15))
        {
         why = "M15 trend filter: trend " + t15;
         return OGP_EVAL_REJECT;
        }
      if(InpUseTrendH1 && !TrendOk(m_hT60, PERIOD_H1, dir, t60))
        {
         why = "H1 trend filter: trend " + t60;
         return OGP_EVAL_REJECT;
        }
      //--- structure break / momentum
      if(InpUseBreakoutFilter && !BreakoutOk(dir, why))
         return OGP_EVAL_REJECT;
      //--- anti-chase
      double vref = (InpEntryMode == OGP_ENTRY_LIVE && vwapLiveOk) ? vwapLive : vwap.Bar1();
      double ext = (dir > 0) ? it.entry - vref : vref - it.entry;
      if(InpUseChaseFilter && ext > InpMaxChaseAtr * a)
        {
         why = StringFormat("price extended %s from VWAP (> %.2f x ATR) - not chasing", Px(sym, ext), InpMaxChaseAtr);
         return OGP_EVAL_CHASED;
        }
      //--- stop-loss: ATR and structure
      double dist = InpSlAtrMult * a;
      string slInfo = StringFormat("ATR stop %s", Px(sym, dist));
      if(InpUseStructureSL)
        {
         double swing = (dir > 0) ? LowestLow(1, InpSwingLookback) - slBuffer : HighestHigh(1, InpSwingLookback) + slBuffer;
         double sdist = (dir > 0) ? it.entry - swing : swing - it.entry;
         if(sdist > dist)
           {
            dist = sdist;
            slInfo = StringFormat("structure stop %s (swing %s)", Px(sym, sdist), Px(sym, swing));
           }
        }
      double minDist = MinStopDistance(sym) + spread;
      if(dist < minDist)
         dist = minDist;
      if(dist > InpMaxSlAtrMult * a)
        {
         why = StringFormat("stop too wide: %s > %.1f x ATR (%s)", Px(sym, dist), InpMaxSlAtrMult, slInfo);
         return OGP_EVAL_REJECT;
        }
      it.slDist = dist;
      it.tpDist = (InpTpRR > 0.0) ? MaxD(dist * InpTpRR, minDist) : 0.0;
      it.detail = StringFormat("%s, TP %s (RR %.2f), ATR %s, VWAP %s, EMA %s", slInfo,
                               it.tpDist > 0.0 ? Px(sym, it.tpDist) : "none", InpTpRR, Px(sym, a), Px(sym, vref),
                               Px(sym, (InpEntryMode == OGP_ENTRY_LIVE) ? ema[0] : ema[1]));
      return OGP_EVAL_OK;
     }

   string            TrendSummary(void)
     {
      string a = "-", b = "-";
      TrendOk(m_hT15, PERIOD_M15, 1, a);
      TrendOk(m_hT60, PERIOD_H1, 1, b);
      trendText = "M15 " + a + " / H1 " + b;
      return trendText;
     }
  };

#endif

//==================================================================
// ===== MODULE: OGP_Positions.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Positions.mqh - management of EA positions                   |
//|                                                                  |
//| Priority per tick (highest first):                               |
//|  1. account emergency (near a firm floor)      -> close          |
//|  2. position floating loss >= emergency limit  -> close          |
//|  3. Friday pre-weekend close                   -> close          |
//|  4. missing stop-loss                          -> set or close   |
//|  5. M3 close beyond EMA (after min hold)       -> close          |
//|  6. break-even / ATR trailing (after min hold, throttled)        |
//| 1-4 ignore the minimum hold time (account protection first).     |
//| 5-6 respect InpMinHoldSeconds (Oracle: < 2 min = tick scalping). |
//+------------------------------------------------------------------+
#ifndef OGP_POSITIONS_MQH
#define OGP_POSITIONS_MQH

class CPositionManager
  {
private:
   ulong             m_tk[];        // per-ticket memory
   double            m_initDist[];
   datetime          m_lastMod[];
   datetime          m_lastClose[];
   datetime          m_deferBar[];  // bar on which an EMA exit was deferred by min hold
   double            m_mfe[];       // best favourable price distance reached (price units)

   int               Slot(const ulong ticket)
     {
      for(int i = 0; i < ArraySize(m_tk); i++)
         if(m_tk[i] == ticket)
            return i;
      int n = ArraySize(m_tk);
      ArrayResize(m_tk, n + 1);
      ArrayResize(m_initDist, n + 1);
      ArrayResize(m_lastMod, n + 1);
      ArrayResize(m_lastClose, n + 1);
      ArrayResize(m_deferBar, n + 1);
      ArrayResize(m_mfe, n + 1);
      m_mfe[n] = 0.0;
      m_tk[n] = ticket;
      m_initDist[n] = 0.0;
      m_lastMod[n] = 0;
      m_lastClose[n] = 0;
      m_deferBar[n] = 0;
      return n;
     }

   double            InitialDistance(const int k, const ulong ticket, const double open, const double sl)
     {
      if(m_initDist[k] > 0.0)
         return m_initDist[k];
      double d = 0.0;
      if(HistoryOrderSelect(ticket))
        {
         double osl = HistoryOrderGetDouble(ticket, ORDER_SL);
         if(osl > 0.0)
            d = MathAbs(open - osl);
        }
      if(d <= 0.0 && sl > 0.0)
         d = MathAbs(open - sl);
      m_initDist[k] = d;
      return d;
     }

   void              TryClose(const int k, const ulong ticket, const string reason, const datetime now)
     {
      if(now - m_lastClose[k] < 3)
         return;                     // avoid hammering the server on repeated failures
      m_lastClose[k] = now;
      ClosePositionTicket(ticket, reason);   // logs its own result
     }

public:
   void              ManageSymbol(COgpSymbol *s, const bool emergency, const string emergencyWhy, const bool weekendClose, const datetime now)
     {
      ulong tickets[];
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0 || PositionGetString(POSITION_SYMBOL) != s.sym || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
            continue;
         int n = ArraySize(tickets);
         ArrayResize(tickets, n + 1);
         tickets[n] = t;
        }
      for(int j = 0; j < ArraySize(tickets); j++)
        {
         ulong t = tickets[j];
         if(!PositionSelectByTicket(t))
            continue;
         int k = Slot(t);
         int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
         double open = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl = PositionGetDouble(POSITION_SL);
         double tp = PositionGetDouble(POSITION_TP);
         double fl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
         long held = (long)(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME));
         string side = (dir > 0) ? "BUY" : "SELL";

         if(emergency)
           {
            TryClose(k, t, "ACCOUNT EMERGENCY: " + emergencyWhy, now);
            continue;
           }
         if(fl <= -InpPositionEmergencyUSD)
           {
            TryClose(k, t, StringFormat("position emergency: floating %s <= -%s", Usd(fl), Usd(InpPositionEmergencyUSD)), now);
            continue;
           }
         if(weekendClose)
           {
            TryClose(k, t, "Friday pre-weekend close", now);
            continue;
           }
         if(sl <= 0.0)
           {
            double a = (s.dataOk && ArraySize(s.atr) > 1) ? s.atr[1] : 0.0;
            if(a > 0.0)
              {
               double cur = (dir > 0) ? s.tick.bid : s.tick.ask;
               double nsl = cur - dir * InpSlAtrMult * a;
               Journal("RISK", s.sym, StringFormat("#%I64u has no stop-loss - attaching %s", t, Px(s.sym, nsl)));
               if(!ModifyStops(t, nsl, tp, "attach missing SL"))
                  TryClose(k, t, "no stop-loss and SL could not be attached", now);
              }
            else
               TryClose(k, t, "no stop-loss and no ATR to build one", now);
            continue;
           }
         if(!s.dataOk)
            continue;

         //--- maximum favourable excursion (for AFTER_MFE exit mode)
         double curPx = (dir > 0) ? s.tick.bid : s.tick.ask;
         double fav = (dir > 0) ? curPx - open : open - curPx;
         if(fav > m_mfe[k])
            m_mfe[k] = fav;
         double initD = InitialDistance(k, t, open, sl);
         bool isSecond = (StringFind(PositionGetString(POSITION_COMMENT), "#2") >= 0);

         //--- EMA candle-close exit
         bool emaArmed = (InpEmaExitMode == OGP_EMAX_ALWAYS) ||
                         (InpEmaExitMode == OGP_EMAX_AFTER_MFE && initD > 0.0 && m_mfe[k] >= InpEmaExitMinR * initD);
         if(InpEmaExitMode != OGP_EMAX_OFF && emaArmed)
           {
            if(s.newBar)
              {
               bool cond = (dir > 0) ? (s.r[1].close < s.ema[1]) : (s.r[1].close > s.ema[1]);
               m_deferBar[k] = 0;
               if(cond)
                 {
                  string why = StringFormat("M3 %s closed %s %s EMA %s", Ts(s.r[1].time), Px(s.sym, s.r[1].close),
                                            dir > 0 ? "<" : ">", Px(s.sym, s.ema[1]));
                  if(held >= InpMinHoldSeconds)
                    {
                     Journal("SIGNAL", s.sym, StringFormat("EXIT %s #%I64u: %s", side, t, why));
                     TryClose(k, t, "EMA exit: " + why, now);
                     continue;
                    }
                  m_deferBar[k] = s.curBar;
                  Journal("SIGNAL", s.sym, StringFormat("EXIT %s #%I64u deferred: %s, held %I64d s < min hold %d s", side, t, why, held, InpMinHoldSeconds));
                 }
              }
            else
               if(m_deferBar[k] == s.curBar && held >= InpMinHoldSeconds)
                 {
                  TryClose(k, t, "deferred EMA exit (min hold reached)", now);
                  continue;
                 }
           }

         //--- stop management (only after min hold, throttled)
         if(held < InpMinHoldSeconds || now - m_lastMod[k] < InpMinModifySeconds)
            continue;
         double a = s.atr[1];
         double cur = (dir > 0) ? s.tick.bid : s.tick.ask;
         double spread = s.tick.ask - s.tick.bid;
         double minD = MinStopDistance(s.sym);
         double newSl = sl;
         string why = "";
         //--- break-even: generic, or for #2 once TP1 has been reached (AT_SIGNAL mode)
         bool beTp1 = (InpSecondEntry == OGP_2ND_AT_SIGNAL && InpBeAfterTp1 && isSecond);
         if(InpUseBreakEven || beTp1)
           {
            double trigR = beTp1 ? InpTp1RR : InpBreakEvenRR;
            if(beTp1 && InpUseBreakEven)
               trigR = MinD(InpTp1RR, InpBreakEvenRR);
            double gain = (dir > 0) ? cur - open : open - cur;
            double be = open + dir * spread;
            bool notYet = (dir > 0) ? (sl < be) : (sl > be);
            if(initD > 0.0 && notYet && m_mfe[k] >= trigR * initD && gain > 0.0 && MathAbs(cur - be) > minD)
              {
               newSl = be;
               why = StringFormat("break-even (ran %s >= %.2fR)", Px(s.sym, m_mfe[k]), trigR);
              }
           }
         if(InpUseTrailing && a > 0.0)
           {
            double cand = cur - dir * InpTrailAtrMult * a;
            bool better = (dir > 0) ? (cand > newSl + 0.1 * a) : (cand < newSl - 0.1 * a);
            if(better && MathAbs(cur - cand) > minD)
              {
               newSl = cand;
               why = StringFormat("ATR trail %.2f x %s", InpTrailAtrMult, Px(s.sym, a));
              }
           }
         if(newSl != sl)
           {
            m_lastMod[k] = now;
            ModifyStops(t, newSl, tp, why);
           }
        }
     }
  };

#endif

//==================================================================
// ===== MODULE: OGP_Dashboard.mqh =====
//==================================================================
//+------------------------------------------------------------------+
//| OGP_Dashboard.mqh - on-chart status panel (labels)               |
//+------------------------------------------------------------------+
#ifndef OGP_DASHBOARD_MQH
#define OGP_DASHBOARD_MQH

#define OGP_DASH_PREFIX "OGP_DASH_"
#define OGP_DASH_LINES  40

class CDashboard
  {
private:
   int               m_used;
   bool              m_created;

   string            Name(const int i) const { return OGP_DASH_PREFIX + IntegerToString(i); }

public:
                     CDashboard(void) : m_used(0), m_created(false) {}

   void              Create(void)
     {
      if(!InpShowDashboard || m_created)
         return;
      string bg = OGP_DASH_PREFIX + "BG";
      ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, InpDashX - 4);
      ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, InpDashY - 4);
      ObjectSetInteger(0, bg, OBJPROP_XSIZE, 560);
      ObjectSetInteger(0, bg, OBJPROP_YSIZE, 40);
      ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, C'20,24,32');
      ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, bg, OBJPROP_COLOR, C'70,80,100');
      ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bg, OBJPROP_HIDDEN, true);
      for(int i = 0; i < OGP_DASH_LINES; i++)
        {
         string n = Name(i);
         ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
         ObjectSetInteger(0, n, OBJPROP_XDISTANCE, InpDashX);
         ObjectSetInteger(0, n, OBJPROP_YDISTANCE, InpDashY + i * (InpDashFontSize + 6));
         ObjectSetString(0, n, OBJPROP_FONT, "Consolas");
         ObjectSetInteger(0, n, OBJPROP_FONTSIZE, InpDashFontSize);
         ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
         ObjectSetString(0, n, OBJPROP_TEXT, " ");
        }
      m_created = true;
     }

   void              Render(const string &lines[], const color &cols[])
     {
      if(!InpShowDashboard || !m_created)
         return;
      int n = ArraySize(lines);
      if(n > OGP_DASH_LINES)
         n = OGP_DASH_LINES;
      for(int i = 0; i < OGP_DASH_LINES; i++)
        {
         string nm = Name(i);
         ObjectSetString(0, nm, OBJPROP_TEXT, (i < n) ? lines[i] : " ");
         if(i < n)
            ObjectSetInteger(0, nm, OBJPROP_COLOR, cols[i]);
        }
      ObjectSetInteger(0, OGP_DASH_PREFIX + "BG", OBJPROP_YSIZE, n * (InpDashFontSize + 6) + 8);
      m_used = n;
      ChartRedraw(0);
     }

   void              Destroy(void)
     {
      ObjectsDeleteAll(0, OGP_DASH_PREFIX);
      m_created = false;
     }
  };

//--- small builder helpers
string g_dl[];
color  g_dc[];

void DashAdd(const string text, const color c = clrSilver)
  {
   int n = ArraySize(g_dl);
   ArrayResize(g_dl, n + 1);
   ArrayResize(g_dc, n + 1);
   g_dl[n] = text;
   g_dc[n] = c;
  }

void DashClear()
  {
   ArrayResize(g_dl, 0);
   ArrayResize(g_dc, 0);
  }

#endif


//==================================================================//
// Globals                                                          //
//==================================================================//
COgpSymbol       *g_syms[];
CAccountMonitor   g_acc;
COracleRules      g_rules;
CNewsFilter       g_news;
CPositionManager  g_pm;
CDashboard        g_dash;
datetime          g_lastOffsetRefresh = 0;
datetime          g_lastDash = 0;
string            g_entryBlock = "";
string            g_sessName = "";

double SlippageFor(const string sym)
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
      if(g_syms[i].sym == sym)
         return g_syms[i].slip;
   return 0.0;
  }

bool SymbolAllowsDirection(const string sym, const int dir, string &why)
  {
   long mode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED || mode == SYMBOL_TRADE_MODE_CLOSEONLY)
     {
      why = "symbol trading disabled / close-only";
      return false;
     }
   if((mode == SYMBOL_TRADE_MODE_LONGONLY && dir < 0) || (mode == SYMBOL_TRADE_MODE_SHORTONLY && dir > 0))
     {
      why = "symbol does not allow this direction";
      return false;
     }
   return true;
  }

//==================================================================//
// Entry decision pipeline                                          //
//==================================================================//
void Reject(COgpSymbol *s, const string side, const string src, const string why)
  {
   s.lastDecision = "REJECTED: " + why;
   Journal("REJECT", s.sym, StringFormat("%s (%s): %s", side, src, why));
  }

void HandleCandidate(COgpSymbol *s, const int dir, const string src, const datetime now)
  {
   string side = (dir > 0) ? "BUY" : "SELL";
   double vref = (InpEntryMode == OGP_ENTRY_LIVE && s.vwapLiveOk) ? s.vwapLive : s.vwap.Bar1();
   double eref = (InpEntryMode == OGP_ENTRY_LIVE) ? s.ema[0] : s.ema[1];
   s.lastSignal = StringFormat("%s %s %s", side, src, TimeToString(now, TIME_MINUTES));
   Journal("SIGNAL", s.sym, StringFormat("%s %s: EMA%d %s VWAP | EMA=%s VWAP=%s (%s vol) bid=%s ask=%s ATR=%s",
                                         side, src, InpEmaPeriod, dir > 0 ? "crossed ABOVE" : "crossed BELOW",
                                         Px(s.sym, eref), Px(s.sym, vref), s.vwap.VolumeType(),
                                         Px(s.sym, s.tick.bid), Px(s.sym, s.tick.ask), Px(s.sym, s.atr[1])));
   string why = "";

   //--- 1. duplicate protection
   if(s.lastEntryBar == s.curBar)
     {
      Reject(s, side, src, "entry already attempted on this M3 bar");
      return;
     }
   //--- 2. strategy filters (signal quality, volatility, stops)
   OgpEntryIntent it;
   ENUM_OGP_EVAL ev = s.Evaluate(dir, src, it, why);
   if(ev == OGP_EVAL_CHASED && InpUsePullbackMode && src != "pullback")
      s.ArmPullback(dir);
   if(ev != OGP_EVAL_OK)
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 3. switches, time, news
   if(!InpEnableNewEntries)
     {
      Reject(s, side, src, "new entries disabled (InpEnableNewEntries=false)");
      return;
     }
   string sess = "";
   if(!TimeAllowsEntry(now, why, sess))
     {
      Reject(s, side, src, why);
      return;
     }
   if(g_news.Blocks(now, why))
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 4. Oracle / account gate
   if(!g_rules.EntryAllowed(g_acc, why))
     {
      Reject(s, side, src, why);
      return;
     }
   if(!TradingPermitted(why) || !SymbolAllowsDirection(s.sym, dir, why))
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 5. position rules
   OgpRiskSummary rs;
   BuildRiskSummary(rs);
   for(int i = 0; i < ArraySize(rs.eaSyms); i++)
      if(rs.eaSyms[i] == s.sym)
        {
         Reject(s, side, src, "max 1 EA position per symbol");
         return;
        }
   if(InpBlockIfUnprotected && rs.unprotected > 0)
     {
      Reject(s, side, src, StringFormat("%d account position(s) without stop-loss", rs.unprotected));
      return;
     }
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING && PositionSelect(s.sym))
     {
      Reject(s, side, src, "netting account already has a position on this symbol");
      return;
     }
   //--- 6. sizing (one or two positions per signal)
   bool hedging = (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
   ENUM_OGP_SECOND mode2 = hedging ? InpSecondEntry : OGP_2ND_OFF;
   bool twoNow = (mode2 == OGP_2ND_AT_SIGNAL);
   double share = (mode2 == OGP_2ND_OFF) ? 1.0 : 0.5;
   double fixedLots = FixedLotsFor(s);
   double spread = s.tick.ask - s.tick.bid;
   it.entry = (dir > 0) ? s.tick.ask : s.tick.bid;
   double slPrice = it.entry - dir * it.slDist;
   double tp1Dist = twoNow ? MaxD(it.slDist * InpTp1RR, MinStopDistance(s.sym) + spread) : it.tpDist;
   double lots1 = 0.0, planned1 = 0.0, lots2 = 0.0, planned2 = 0.0;
   string capInfo = "", capInfo2 = "";
   if(!ComputeLots(s.sym, dir, it.entry, slPrice, s.slip, fixedLots, share, rs, g_acc, g_rules, lots1, planned1, capInfo, why))
     {
      Reject(s, side, src, why + " | " + capInfo);
      return;
     }
   if(twoNow)
     {
      rs.eaRiskFromEntry += planned1;       // position #1 is part of the budget for #2
      rs.allRiskFromNow  += planned1;
      if(!ComputeLots(s.sym, dir, it.entry, slPrice, s.slip, fixedLots, share, rs, g_acc, g_rules, lots2, planned2, capInfo2, why))
        {
         Journal("RISK", s.sym, "position #2 not possible (" + why + ") - opening #1 only");
         twoNow = false;
         tp1Dist = it.tpDist;
        }
     }
   //--- 7. margin (keep 10% of free margin in reserve)
   double margin = 0.0;
   if(!OrderCalcMargin(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, s.sym, lots1 + lots2, it.entry, margin) || margin > g_acc.freeMargin * 0.9)
     {
      Reject(s, side, src, StringFormat("insufficient margin: need %s, free %s", Usd(margin), Usd(g_acc.freeMargin)));
      return;
     }
   //--- 8. execute
   Journal("RISK", s.sym, StringFormat("%s ACCEPTED [%s] %s | #1 %s%s | margin %s", side, sess, it.detail, capInfo,
                                       twoNow ? " | #2 " + capInfo2 : "", Usd(margin)));
   s.lastEntryBar = s.curBar;                // one attempt per bar whatever the outcome
   ulong tk1 = 0;
   if(!OpenWithStop(s.sym, dir, lots1, it.slDist, tp1Dist, InpOrderComment + "#1", tk1))
     {
      s.lastDecision = "ORDER FAILED (see journal)";
      return;
     }
   s.OnEntry(dir);
   s.lastDecision = StringFormat("OPENED %s #1 %.2f lots, risk %s", side, lots1, Usd(planned1));
   g_rules.stats.eaEntriesToday++;           // count immediately; history refresh follows
   g_rules.statsDirty = true;

   double pOpen = 0.0, pSl = 0.0, pTp = 0.0;
   if(tk1 > 0 && PositionSelectByTicket(tk1))
     {
      pOpen = PositionGetDouble(POSITION_PRICE_OPEN);
      pSl = PositionGetDouble(POSITION_SL);
      pTp = PositionGetDouble(POSITION_TP);
     }
   if(mode2 == OGP_2ND_OFF)
      return;
   if(pSl <= 0.0)
     {
      Journal("RISK", s.sym, "position #2 skipped: position #1 not found / has no SL");
      return;
     }
   if(twoNow)
     {
      double tpFinal = (it.tpDist > 0.0) ? pOpen + dir * it.tpDist : 0.0;
      ulong tk2 = 0;
      if(OpenWithStop(s.sym, dir, lots2, 0.0, 0.0, InpOrderComment + "#2", tk2, pSl, tpFinal))
         s.lastDecision += StringFormat(" + #2 %.2f lots", lots2);
     }
   else
      s.ArmSecond(dir, pSl, pTp, tk1);
  }

double FixedLotsFor(COgpSymbol *s)
  {
   if(InpLotMode != OGP_LOT_FIXED)
      return 0.0;
   return s.isGold ? InpFixedLotGold : InpFixedLotSilver;
  }

//--- position #2 after a retest of the EMA/VWAP zone (shared SL and target)
void HandleSecond(COgpSymbol *s, const datetime now)
  {
   int dir = s.s2Dir;
   string side = (dir > 0) ? "BUY" : "SELL";
   string why = "", sess = "";
   Journal("SIGNAL", s.sym, StringFormat("%s retest for position #2: bid=%s ask=%s EMA=%s VWAP=%s", side,
                                         Px(s.sym, s.tick.bid), Px(s.sym, s.tick.ask), Px(s.sym, s.ema[1]), Px(s.sym, s.vwap.Bar1())));
   bool ok = InpEnableNewEntries && TimeAllowsEntry(now, why, sess) && !g_news.Blocks(now, why) &&
             g_rules.EntryAllowed(g_acc, why, false) && TradingPermitted(why) && SymbolAllowsDirection(s.sym, dir, why);
   if(!InpEnableNewEntries)
      why = "new entries disabled";
   double spread = s.tick.ask - s.tick.bid;
   if(ok && spread > s.maxSpread)
     {
      ok = false;
      why = StringFormat("spread %s > max %s", Px(s.sym, spread), Px(s.sym, s.maxSpread));
     }
   if(!ok)
     {
      LogThrottled(s.sym + "s2rej", "REJECT", s.sym, side + " #2 (waiting): " + why, 60);
      return;                                // stays armed until it expires
     }
   OgpRiskSummary rs;
   BuildRiskSummary(rs);
   int mine = 0;
   for(int i = 0; i < ArraySize(rs.eaSyms); i++)
      if(rs.eaSyms[i] == s.sym)
         mine++;
   if(mine >= 2 || (InpBlockIfUnprotected && rs.unprotected > 0))
     {
      s.CancelSecond(mine >= 2 ? "already 2 positions on symbol" : "unprotected position on account");
      return;
     }
   double entry = (dir > 0) ? s.tick.ask : s.tick.bid;
   double lots = 0.0, planned = 0.0, margin = 0.0;
   string capInfo = "";
   if(!ComputeLots(s.sym, dir, entry, s.s2Sl, s.slip, FixedLotsFor(s), 0.5, rs, g_acc, g_rules, lots, planned, capInfo, why))
     {
      s.CancelSecond(why + " | " + capInfo);
      return;
     }
   if(!OrderCalcMargin(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, s.sym, lots, entry, margin) || margin > g_acc.freeMargin * 0.9)
     {
      s.CancelSecond("insufficient margin");
      return;
     }
   Journal("RISK", s.sym, StringFormat("%s #2 ACCEPTED on retest | SL %s TP %s | %s", side, Px(s.sym, s.s2Sl),
                                       s.s2Tp > 0.0 ? Px(s.sym, s.s2Tp) : "none", capInfo));
   s.s2Active = false;                       // one attempt only
   s.lastEntryBar = s.curBar;
   ulong tk2 = 0;
   if(OpenWithStop(s.sym, dir, lots, 0.0, 0.0, InpOrderComment + "#2", tk2, s.s2Sl, s.s2Tp))
      s.lastDecision = StringFormat("OPENED %s #2 %.2f lots on retest, risk %s", side, lots, Usd(planned));
  }

//==================================================================//
// Main loop                                                        //
//==================================================================//
void ProcessAll()
  {
   datetime now = ServerNow();
   if(!OgpIsTester() && now - g_lastOffsetRefresh >= 3600)
     {
      RefreshAutoServerOffset();
      g_lastOffsetRefresh = now;
     }
   bool wasConnected = g_acc.connected;
   g_acc.Update();
   if(g_acc.connected && !wasConnected)
      for(int i = 0; i < ArraySize(g_syms); i++)
         g_syms[i].OnReconnect();
   g_rules.Update(g_acc);
   g_news.Refresh(now);
   UpdateSessionLogs(now);
   if(g_rules.emergency)
      LogThrottled("emerg", "RISK", "", "ACCOUNT EMERGENCY: " + g_rules.emergencyReason + " - closing EA positions", 30);

   datetime anchor = VwapAnchor(now);
   bool weekendClose = WeekendCloseDue(now);
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      COgpSymbol *s = g_syms[i];
      bool fresh = s.Refresh(anchor);
      g_pm.ManageSymbol(s, g_rules.emergency, g_rules.emergencyReason, weekendClose, now);
      if(!fresh || !s.dataOk)
         continue;
      int dir = s.DetectCross(anchor);
      if(dir != 0)
        {
         s.OnCrossObserved(dir);
         HandleCandidate(s, dir, InpEntryMode == OGP_ENTRY_LIVE ? "live" : "confirmed", now);
        }
      int pb = s.CheckPullback();
      if(pb != 0)
         HandleCandidate(s, pb, "pullback", now);
      if(s.CheckSecond())
         HandleSecond(s, now);
     }

   //--- global entry status for the dashboard
   string why = "";
   string sess = "";
   g_entryBlock = "";
   if(!InpEnableNewEntries)
      g_entryBlock = "entries disabled by user";
   else
      if(!g_rules.EntryAllowed(g_acc, why))
         g_entryBlock = why;
      else
         if(!TimeAllowsEntry(now, why, sess))
            g_entryBlock = why;
         else
            if(g_news.Blocks(now, why))
               g_entryBlock = why;
   g_sessName = sess;

   if(now != g_lastDash)
     {
      g_lastDash = now;
      DrawDashboard(now);
     }
  }

void DrawDashboard(const datetime now)
  {
   if(!InpShowDashboard || (OgpIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE)))
      return;
   DashClear();
   color hdr = clrGold, ok = clrLimeGreen, bad = clrTomato, warn = clrOrange, txt = clrSilver;
   DashAdd("ORACLE GUARDIAN PRO v1.10  (no profit guarantee)", hdr);
   DashAdd(StringFormat("Server %s | UTC %s | NY %s", TimeToString(now, TIME_MINUTES),
                        TimeToString(ServerToUtc(now), TIME_MINUTES), TimeToString(NyLocal(now), TIME_MINUTES)), txt);
   DashAdd(g_entryBlock == "" ? "ENTRIES: ALLOWED [" + g_sessName + "]" : "ENTRIES: BLOCKED - " + g_entryBlock,
           g_entryBlock == "" ? ok : bad);
   DashAdd("--- ACCOUNT (live MT5 data) ---", hdr);
   DashAdd(StringFormat("Balance %s  Equity %s  Floating %s %s", Usd(g_acc.balance), Usd(g_acc.equity), Usd(g_acc.floating), g_acc.currency),
           g_acc.floating >= 0 ? ok : warn);
   DashAdd(StringFormat("Margin %s  Free %s  Level %s%%  Lev 1:%I64d", Usd(g_acc.margin), Usd(g_acc.freeMargin),
                        g_acc.margin > 0 ? DoubleToString(g_acc.marginLevel, 0) : "-", g_acc.leverage), txt);
   DashAdd("--- ORACLE RULES (EA references; Upcomers server values not readable) ---", hdr);
   DashAdd(StringFormat("Shield floor %s [%s]  dist %s", Usd(g_rules.shieldFloor),
                        InpManualShieldFloor > 0 ? "MANUAL+" + SourceText(g_acc.peakSrc) : SourceText(g_acc.peakSrc),
                        Usd(g_acc.equity - g_rules.shieldFloor)), g_rules.shieldReliable ? txt : bad);
   DashAdd(StringFormat("Peak equity %s", Usd(g_acc.peakEquity)), txt);
   DashAdd(StringFormat("Day start eq %s [%s]  daily floor %s  dist %s", Usd(g_acc.dayStartEquity), SourceText(g_acc.daySrc),
                        Usd(g_rules.dailyFloor), Usd(g_acc.equity - g_rules.dailyFloor)), g_rules.dailyReliable ? txt : bad);
   DashAdd(StringFormat("Single trade limit %s | internal max %s", Usd(g_rules.singleTradeLimit), Usd(InpMaxSingleTradeLossUSD)), txt);
   if(g_rules.stats.ok)
     {
      DashAdd(StringFormat("Today realized %s / target %s | trades %d/%d | lock %s", Usd(g_rules.stats.todayNet), Usd(InpDailyTargetUSD),
                           g_rules.stats.eaEntriesToday, InpMaxTradesPerDay, g_rules.dailyLock ? "ON" : "off"),
              g_rules.dailyLock ? bad : txt);
      DashAdd(StringFormat("Cycle net %s | valid days %d/%d (>= %s) | best day %.0f%%", Usd(g_rules.stats.cycleNet),
                           g_rules.stats.validDays, InpMinValidDays, Usd(g_rules.validDayThreshold), g_rules.BestDayRatio()),
              g_rules.BestDayRatio() > InpBestDayPct ? warn : txt);
     }
   else
      DashAdd("Realized statistics: UNKNOWN (history)", bad);
   OgpRiskSummary rs;
   BuildRiskSummary(rs);
   DashAdd(StringFormat("Payout: %s", g_rules.PayoutStatus(rs.eaPositions + rs.otherPositions)), txt);
   DashAdd("--- RISK ---", hdr);
   DashAdd(StringFormat("EA planned risk %s / cap %s | positions EA %d other %d | no-SL %d",
                        rs.eaRiskFromEntry >= OGP_INF_RISK ? "INF" : Usd(rs.eaRiskFromEntry),
                        Usd(InpInitialBalance * InpMaxTotalRiskPct / 100.0), rs.eaPositions, rs.otherPositions, rs.unprotected),
           rs.unprotected > 0 ? bad : txt);
   if(InpLotMode == OGP_LOT_FIXED)
      DashAdd(StringFormat("Lots FIXED gold %.2f / silver %.2f per position (reduced if caps bind) | #2: %s",
                           InpFixedLotGold, InpFixedLotSilver, EnumToString(InpSecondEntry)), warn);
   else
      DashAdd(StringFormat("Risk/signal %.2f%% of equity = %s | #2: %s", InpRiskPct, Usd(g_acc.equity * InpRiskPct / 100.0),
                           EnumToString(InpSecondEntry)), txt);
   if(g_rules.emergency)
      DashAdd("EMERGENCY: " + g_rules.emergencyReason, bad);
   DashAdd("--- MARKETS (M3) ---", hdr);
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      COgpSymbol *s = g_syms[i];
      if(!s.dataOk)
        {
         DashAdd(s.sym + ": waiting for data", warn);
         continue;
        }
      DashAdd(StringFormat("%s spread %s | ATR %s | EMA %s | VWAP %s (%s) | %s", s.sym, Px(s.sym, s.tick.ask - s.tick.bid),
                           Px(s.sym, s.atr[1]), Px(s.sym, s.ema[0]), s.vwap.Bar1Valid() ? Px(s.sym, s.vwap.Bar1()) : "n/a",
                           s.vwap.VolumeType(), s.TrendSummary()), txt);
      DashAdd(StringFormat("   last signal: %s | %s%s", s.lastSignal, s.lastDecision,
                           s.s2Active ? StringFormat(" | #2 armed (%d bars left)", s.s2BarsLeft) : ""), txt);
     }
   DashAdd(StringFormat("News: %s | next: %s", g_news.status, g_news.NextEvent(now)),
           (InpUseNewsFilter && !g_news.available) ? warn : txt);
   g_dash.Render(g_dl, g_dc);
  }

//==================================================================//
// Event handlers                                                   //
//==================================================================//
bool ValidateInputs()
  {
   string e = "";
   if(InpInitialBalance <= 0.0)
      e = "InpInitialBalance must be > 0";
   else if(InpRiskPct <= 0.0 || InpRiskPct > 1.0)
      e = "InpRiskPct must be in (0, 1.0] (firm single-trade limit is 2%)";
   else if(InpMaxTotalRiskPct < InpRiskPct)
      e = "InpMaxTotalRiskPct must be >= InpRiskPct";
   else if(InpDailyLossLockUSD <= 0.0 || InpDailyLossLockUSD >= InpInitialBalance * InpDailyDDPct / 100.0)
      e = "InpDailyLossLockUSD must be > 0 and below the firm daily drawdown";
   else if(InpMaxSingleTradeLossUSD <= 0.0 || InpMaxSingleTradeLossUSD >= InpInitialBalance * InpSingleTradePct / 100.0)
      e = "InpMaxSingleTradeLossUSD must be > 0 and below the firm single-trade limit";
   else if(InpPositionEmergencyUSD >= InpInitialBalance * InpSingleTradePct / 100.0)
      e = "InpPositionEmergencyUSD must be below the firm single-trade limit";
   else if(InpEmergencyBufferUSD <= 0.0 || InpFloorSafetyUSD <= InpEmergencyBufferUSD)
      e = "need 0 < InpEmergencyBufferUSD < InpFloorSafetyUSD";
   else if(InpMinHoldSeconds < 120)
      e = "InpMinHoldSeconds must be >= 120 (Oracle treats trades under 2 minutes as tick scalping)";
   else if(InpSlAtrMult <= 0.0 || InpMaxSlAtrMult < InpSlAtrMult)
      e = "need 0 < InpSlAtrMult <= InpMaxSlAtrMult";
   else if(InpCorrelatedRiskFactor <= 0.0 || InpCorrelatedRiskFactor > 1.0)
      e = "InpCorrelatedRiskFactor must be in (0, 1]";
   else if(InpLotMode == OGP_LOT_FIXED && (InpFixedLotGold <= 0.0 || InpFixedLotSilver <= 0.0))
      e = "fixed lots must be > 0";
   else if(InpMaxTotalRiskPct <= 0.0 || InpMaxTotalRiskPct > 3.0)
      e = "InpMaxTotalRiskPct must be in (0, 3]";
   else if(InpSecondEntry == OGP_2ND_AT_SIGNAL && (InpTp1RR <= 0.0 || (InpTpRR > 0.0 && InpTp1RR >= InpTpRR)))
      e = "AT_SIGNAL mode needs 0 < InpTp1RR < InpTpRR";
   else if(InpRetestMaxBars < 1 || InpEmaExitMinR < 0.0)
      e = "InpRetestMaxBars >= 1 and InpEmaExitMinR >= 0 required";
   else if(InpMaxTradesPerDay < 1 || InpEmaPeriod < 1 || InpAtrPeriod < 1 || InpSwingLookback < 2 || InpBreakoutLookback < 2)
      e = "periods / lookbacks / max trades out of range";
   if(e != "")
     {
      OgpLog("INIT ERROR: " + e);
      return false;
     }
   return true;
  }

bool AddSymbol(const string base, const bool gold)
  {
   string sym = InpSymbolPrefix + base + InpSymbolSuffix;
   if(!SymbolSelect(sym, true))
     {
      OgpLog(StringFormat("INIT ERROR: symbol '%s' not found (check prefix/suffix), err %d", sym, GetLastError()));
      return false;
     }
   COgpSymbol *s = new COgpSymbol();
   if(!s.Init(sym, gold))
     {
      s.Deinit();
      delete s;
      return false;
     }
   int n = ArraySize(g_syms);
   ArrayResize(g_syms, n + 1);
   g_syms[n] = s;
   return true;
  }

void FreeSymbols()
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
      if(CheckPointer(g_syms[i]) == POINTER_DYNAMIC)
        {
         g_syms[i].Deinit();
         delete g_syms[i];
        }
   ArrayResize(g_syms, 0);
  }

int OnInit()
  {
   OgpLog("==================================================================");
   OgpLog("Oracle Guardian Pro v1.10 - NO PROFIT GUARANTEE - verify every rule on Upcomers");
   if(!ValidateInputs() || !SessionsInit())
      return INIT_PARAMETERS_INCORRECT;
   JournalOpen();
   RefreshAutoServerOffset();
   if(!g_autoOffsetValid)
      Journal("TIME", "", StringFormat("server time rule: UTC%+d standard, %s DST%s", InpServerUtcOffsetHours,
                                       EnumToString(InpServerDst), OgpIsTester() ? " (tester: no auto detection)" : ""));
   datetime now = ServerNow();
   Journal("TIME", "", StringFormat("server %s = UTC %s = New York %s", Ts(now), Ts(ServerToUtc(now)), Ts(NyLocal(now))));

   ArrayResize(g_syms, 0);
   bool ok = true;
   if(InpSymbols == OGP_SYM_BOTH || InpSymbols == OGP_SYM_GOLD)
      ok = ok && AddSymbol(InpGoldSymbol, true);
   if(InpSymbols == OGP_SYM_BOTH || InpSymbols == OGP_SYM_SILVER)
      ok = ok && AddSymbol(InpSilverSymbol, false);
   if(!ok || ArraySize(g_syms) == 0)
     {
      FreeSymbols();
      JournalClose();
      return INIT_FAILED;
     }

   g_acc.Init();
   g_rules.Update(g_acc);
   Journal("SYSTEM", "", StringFormat("account %I64d %s, leverage 1:%I64d, margin mode %s, balance %s, equity %s",
                                      g_acc.login, g_acc.currency, g_acc.leverage,
                                      AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? "HEDGING" : "NETTING",
                                      Usd(g_acc.balance), Usd(g_acc.equity)));
   if(MathAbs(g_acc.balance - InpInitialBalance) > InpInitialBalance * 0.10)
      Journal("SYSTEM", "", StringFormat("WARNING: balance %s differs >10%% from InpInitialBalance %s - check the input",
                                         Usd(g_acc.balance), Usd(InpInitialBalance)));
   Journal("ORACLE", "", StringFormat("firm limits (reference, NOT targets): shield %s (%.1f%%), daily %.1f%%, single trade %.1f%% = %s, valid day %s, payout %s",
                                      Usd(InpInitialBalance * InpShieldPct / 100.0), InpShieldPct, InpDailyDDPct, InpSingleTradePct,
                                      Usd(g_rules.singleTradeLimit), Usd(g_rules.validDayThreshold), Usd(g_rules.payoutThreshold)));
   Journal("ORACLE", "", StringFormat("shield floor %s [%s], day start %s [%s]", Usd(g_rules.shieldFloor), SourceText(g_acc.peakSrc),
                                      Usd(g_acc.dayStartEquity), SourceText(g_acc.daySrc)));
   Journal("SYSTEM", "", StringFormat("lots %s (gold %.2f / silver %.2f) | position #2: %s | max combined risk %.2f%%",
                                      EnumToString(InpLotMode), InpFixedLotGold, InpFixedLotSilver, EnumToString(InpSecondEntry), InpMaxTotalRiskPct));
   if(InpSecondEntry != OGP_2ND_OFF && AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      Journal("SYSTEM", "", "WARNING: netting account - second position disabled");
   Journal("SYSTEM", "", StringFormat("mode %s | trend M15 %s H1 %s | breakout %s | chase %s | pullback %s | EMA exit %s | BE %s | trail %s | news %s",
                                      EnumToString(InpEntryMode), InpUseTrendM15 ? "ON" : "off", InpUseTrendH1 ? "ON" : "off",
                                      InpUseBreakoutFilter ? "ON" : "off", InpUseChaseFilter ? "ON" : "off",
                                      InpUsePullbackMode ? "ON" : "off", EnumToString(InpEmaExitMode),
                                      InpUseBreakEven ? "ON" : "off", InpUseTrailing ? "ON" : "off", InpUseNewsFilter ? "ON" : "off"));
   g_dash.Create();
   if(!EventSetTimer(1))
      Journal("SYSTEM", "", StringFormat("WARNING: timer failed (err %d)", GetLastError()));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_acc.Save();
   FreeSymbols();
   g_dash.Destroy();
   Journal("SYSTEM", "", StringFormat("deinit (reason %d). Open positions keep their broker-side SL/TP but are NOT managed now.", reason));
   JournalClose();
  }

void OnTick()  { ProcessAll(); }
void OnTimer() { ProcessAll(); }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   g_rules.statsDirty = true;
   if(!HistoryDealSelect(trans.deal))
      return;
   if((ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   string sym = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   string e = (entry == DEAL_ENTRY_IN) ? "OPENED" : (entry == DEAL_ENTRY_OUT ? "CLOSED" : (entry == DEAL_ENTRY_INOUT ? "REVERSED" : "CLOSED_BY"));
   Journal("DEAL", sym, StringFormat("%s #%I64u %.2f lots @ %s | pos #%I64d | profit %s comm %s swap %s | reason %s",
                                     e, trans.deal, HistoryDealGetDouble(trans.deal, DEAL_VOLUME),
                                     Px(sym, HistoryDealGetDouble(trans.deal, DEAL_PRICE)),
                                     HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_PROFIT)),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_COMMISSION)),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_SWAP)),
                                     EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON))));
  }
//+------------------------------------------------------------------+
