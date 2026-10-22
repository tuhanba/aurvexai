//+------------------------------------------------------------------+
//|                                           SessionVwapEma9EA.mq5  |
//|   Session VWAP (OHLC/4) vs EMA(9) crossover - M3 - XAUUSD/XAGUSD |
//|                                                                  |
//|   EXPERIMENTAL STRATEGY TEST. NOT A PRODUCTION TRADING SYSTEM.   |
//|   Stop-loss / take-profit are DISABLED by default: an open       |
//|   position stays fully exposed until the M3 close-vs-EMA9 exit   |
//|   fires, which can mean substantial losses.                      |
//+------------------------------------------------------------------+
#property copyright   "Experimental strategy test - use at your own risk"
#property version     "1.00"
#property description "Session VWAP (OHLC/4) vs EMA9 crossover on M3 for XAUUSD / XAGUSD."
#property description "Entries only inside configured session-opening windows."
#property description "Exits on a closed M3 candle vs EMA9 (always active)."
#property description "EXPERIMENTAL. SL/TP disabled by default - positions may carry large losses."

//+------------------------------------------------------------------+
//| Overview (see README.md for the full specification)              |
//|                                                                  |
//|  Module layout in this file:                                     |
//|   1. Enums / inputs                                              |
//|   2. Utilities (logging, formatting, symbol helpers)             |
//|   3. Time & session module   (broker time -> session local time) |
//|   4. Indicator module        (session VWAP calculator, EMA wrap) |
//|   5. Order execution module  (checks, OrderCheck/OrderSend,      |
//|                               retries, retcode handling)         |
//|   6. Position module         (count / close own positions)       |
//|   7. Symbol engine           (signal detection + orchestration)  |
//|   8. Event handlers          (OnInit/OnDeinit/OnTick/OnTimer/    |
//|                               OnTradeTransaction)                |
//+------------------------------------------------------------------+

#define EA_TAG      "[SVE9]"
#define SIG_TF      PERIOD_M3      // every calculation uses M3, whatever the chart timeframe
#define M3_SECONDS  180
#define MAX_SESSIONS 3

//==================================================================//
// 1. ENUMS / INPUTS                                                //
//==================================================================//
enum ENUM_SYMBOL_SET
  {
   SYMSET_GOLD_AND_SILVER = 0, // Gold and Silver
   SYMSET_GOLD_ONLY       = 1, // Gold only
   SYMSET_SILVER_ONLY     = 2  // Silver only
  };

enum ENUM_VWAP_VOLUME
  {
   VWAPVOL_AUTO = 0, // Auto: real volume if every checked bar has it, else tick volume
   VWAPVOL_REAL = 1, // Real volume only (VWAP invalid if broker has none)
   VWAPVOL_TICK = 2  // Tick volume only
  };

enum ENUM_SIGNAL_MODE
  {
   SIGNAL_INTRABAR  = 0, // Intrabar: live EMA vs live VWAP, enter immediately
   SIGNAL_BAR_CLOSE = 1  // Bar close: cross confirmed on a closed M3 bar
  };

enum ENUM_SESSION_TZ
  {
   TZ_NEW_YORK      = 0, // New York (UTC-5, US DST)
   TZ_LONDON        = 1, // London (UTC+0, EU DST)
   TZ_TOKYO         = 2, // Tokyo (UTC+9, no DST)
   TZ_UTC           = 3, // UTC
   TZ_BROKER_SERVER = 4  // Broker server time (no conversion)
  };

enum ENUM_BROKER_DST
  {
   BROKER_DST_NONE = 0, // No DST (fixed offset)
   BROKER_DST_US   = 1, // DST on US dates (most "GMT+2/+3" brokers)
   BROKER_DST_EU   = 2  // DST on EU dates
  };

input group "=== Instruments ==="
input ENUM_SYMBOL_SET  InpSymbolSet            = SYMSET_GOLD_AND_SILVER; // Symbols to trade
input string           InpGoldSymbol           = "XAUUSD";  // Gold base symbol name
input string           InpSilverSymbol         = "XAGUSD";  // Silver base symbol name
input string           InpSymbolPrefix         = "";        // Broker symbol prefix (e.g. "m.")
input string           InpSymbolSuffix         = "";        // Broker symbol suffix (e.g. ".r", "-ECN")

input group "=== Indicators (always calculated on M3) ==="
input int              InpEmaPeriod            = 9;            // EMA period (spec: 9, price: Close)
input ENUM_VWAP_VOLUME InpVwapVolume           = VWAPVOL_AUTO; // VWAP volume source
input int              InpAutoVolumeCheckBars  = 200;          // Auto mode: closed M3 bars checked for real volume

input group "=== Entry signal ==="
input ENUM_SIGNAL_MODE InpSignalMode           = SIGNAL_INTRABAR; // Cross detection mode
input double           InpCrossBufferPoints    = 0.0;   // Dead-band around VWAP in points (0 = none)
input int              InpBaselineResetGapSec  = 180;   // Tick gap (s) that resets the cross baseline (0 = off)
input bool             InpOneEntryPerBar       = true;  // Max one entry attempt per symbol per M3 bar
input int              InpMaxEntriesPerWindow  = 0;     // Max entries per symbol per opening window (0 = unlimited)
input bool             InpReverseOnOpposite    = false; // Opposite signal closes open position and reverses

input group "=== Exits ==="
input bool             InpManageExits          = true;  // Manage EMA candle-close exits
input bool             InpExitCheckOnStart     = true;  // Evaluate last closed M3 bar when the EA starts
input bool             InpExitOnVwapCross      = false; // OPTIONAL extra exit: closed-bar EMA crosses VWAP against position
input int              InpMaxCloseAttemptsPerBar = 10;  // Close retries per M3 bar before giving up until next bar

input group "=== Risk & execution ==="
input bool             InpEnableNewEntries     = true;  // Master switch for NEW entries (exits keep working)
input double           InpLotsGold             = 0.01;  // Fixed lot size - gold
input double           InpLotsSilver           = 0.01;  // Fixed lot size - silver
input int              InpMaxPositionsPerSymbol = 1;    // Max open positions per symbol (netting: forced 1)
input bool             InpUseStopLoss          = false; // Use stop-loss (DISABLED by default)
input int              InpStopLossPointsGold   = 1000;  // Stop-loss distance in points - gold
input int              InpStopLossPointsSilver = 500;   // Stop-loss distance in points - silver
input bool             InpUseTakeProfit        = false; // Use take-profit (DISABLED by default)
input int              InpTakeProfitPointsGold = 2000;  // Take-profit distance in points - gold
input int              InpTakeProfitPointsSilver = 1000;// Take-profit distance in points - silver
input int              InpMaxSpreadPointsGold  = 50;    // Max spread in points to open - gold
input int              InpMaxSpreadPointsSilver = 50;   // Max spread in points to open - silver
input int              InpMaxDeviationPoints   = 30;    // Max deviation / slippage in points
input ulong            InpMagic                = 930903; // Magic number
input int              InpOrderRetries         = 2;     // Retries on requote / price changed / price off
input string           InpOrderComment         = "SVE9"; // Order comment

input group "=== Broker server time ==="
input bool             InpAutoServerOffset     = true;  // Live only: detect offset from TimeTradeServer()-TimeGMT()
input int              InpServerUtcOffsetHours = 2;     // Broker STANDARD (winter) UTC offset, hours
input ENUM_BROKER_DST  InpServerDst            = BROKER_DST_US; // Broker DST rule (tester + fallback)

input group "=== Session 1 ==="
input bool             InpS1Enabled            = true;          // Enabled
input string           InpS1Name               = "NewYork";     // Name
input ENUM_SESSION_TZ  InpS1Zone               = TZ_NEW_YORK;   // Time zone of start time
input string           InpS1Start              = "09:30";       // Start (HH:MM, zone local time)
input int              InpS1WindowMinutes      = 30;            // Entry window length (minutes)
input int              InpS1LengthMinutes      = 390;           // Session length (minutes, for VWAP/log)

input group "=== Session 2 ==="
input bool             InpS2Enabled            = false;
input string           InpS2Name               = "London";
input ENUM_SESSION_TZ  InpS2Zone               = TZ_LONDON;
input string           InpS2Start              = "08:00";
input int              InpS2WindowMinutes      = 30;
input int              InpS2LengthMinutes      = 510;

input group "=== Session 3 ==="
input bool             InpS3Enabled            = false;
input string           InpS3Name               = "Tokyo";
input ENUM_SESSION_TZ  InpS3Zone               = TZ_TOKYO;
input string           InpS3Start              = "09:00";
input int              InpS3WindowMinutes      = 30;
input int              InpS3LengthMinutes      = 360;

input group "=== Logging / display ==="
input bool             InpLogEveryBar          = true;  // Log closed-bar EMA / VWAP on every new M3 bar
input bool             InpLogEveryTick         = false; // Log live EMA / VWAP on every tick (very verbose)
input bool             InpShowChartComment     = true;  // Status panel on the chart

//==================================================================//
// 2. UTILITIES                                                     //
//==================================================================//
bool IsTester() { return (bool)MQLInfoInteger(MQL_TESTER); }

void Log(const string msg) { Print(EA_TAG, " ", msg); }

string g_thrKeys[];
datetime g_thrTimes[];

// Logs at most once per `seconds` for the same key (data errors etc.).
void LogThrottled(const string key, const string msg, const int seconds = 60)
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
         Log(msg);
         return;
        }
     }
   ArrayResize(g_thrKeys, n + 1);
   ArrayResize(g_thrTimes, n + 1);
   g_thrKeys[n]  = key;
   g_thrTimes[n] = now;
   Log(msg);
  }

string Ts(const datetime t) { return TimeToString(t, TIME_DATE | TIME_SECONDS); }

double SymPoint(const string s)  { return SymbolInfoDouble(s, SYMBOL_POINT); }
int    SymDigits(const string s) { return (int)SymbolInfoInteger(s, SYMBOL_DIGITS); }
string Px(const string s, const double v) { return DoubleToString(v, SymDigits(s)); }

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

string RetcodeText(const uint rc)
  {
   switch(rc)
     {
      case TRADE_RETCODE_DONE:            return "DONE";
      case TRADE_RETCODE_DONE_PARTIAL:    return "DONE_PARTIAL";
      case TRADE_RETCODE_PLACED:          return "PLACED";
      case TRADE_RETCODE_REQUOTE:         return "REQUOTE";
      case TRADE_RETCODE_REJECT:          return "REJECT";
      case TRADE_RETCODE_CANCEL:          return "CANCEL";
      case TRADE_RETCODE_ERROR:           return "ERROR";
      case TRADE_RETCODE_TIMEOUT:         return "TIMEOUT";
      case TRADE_RETCODE_INVALID:         return "INVALID_REQUEST";
      case TRADE_RETCODE_INVALID_VOLUME:  return "INVALID_VOLUME";
      case TRADE_RETCODE_INVALID_PRICE:   return "INVALID_PRICE";
      case TRADE_RETCODE_INVALID_STOPS:   return "INVALID_STOPS";
      case TRADE_RETCODE_TRADE_DISABLED:  return "TRADE_DISABLED";
      case TRADE_RETCODE_MARKET_CLOSED:   return "MARKET_CLOSED";
      case TRADE_RETCODE_NO_MONEY:        return "NO_MONEY (insufficient margin)";
      case TRADE_RETCODE_PRICE_CHANGED:   return "PRICE_CHANGED";
      case TRADE_RETCODE_PRICE_OFF:       return "PRICE_OFF";
      case TRADE_RETCODE_TOO_MANY_REQUESTS: return "TOO_MANY_REQUESTS";
      case TRADE_RETCODE_CONNECTION:      return "NO_CONNECTION";
      case TRADE_RETCODE_INVALID_FILL:    return "INVALID_FILL";
      case TRADE_RETCODE_LIMIT_VOLUME:    return "LIMIT_VOLUME";
      case TRADE_RETCODE_LIMIT_POSITIONS: return "LIMIT_POSITIONS";
      case TRADE_RETCODE_POSITION_CLOSED: return "POSITION_CLOSED";
      case 0:                             return "OK";
     }
   return "retcode " + IntegerToString((long)rc);
  }

//==================================================================//
// 3. TIME & SESSION MODULE                                         //
//==================================================================//
// All session start times are given in the session's own local    //
// time zone. Conversion chain: broker server time -> UTC ->        //
// session local time. DST rules implemented:                       //
//   US: 2nd Sunday of March 02:00 local -> 1st Sunday Nov 02:00    //
//   EU: last Sunday of March 01:00 UTC -> last Sunday Oct 01:00 UTC//
//==================================================================//
struct SessionConfig
  {
   bool              enabled;
   string            name;
   ENUM_SESSION_TZ   zone;
   int               startMin;     // minutes after local midnight
   int               windowMin;    // entry window length
   int               lengthMin;    // full session length
  };

struct SessionState
  {
   bool              valid;
   datetime          startServer;  // most recent start, broker server time
   datetime          windowEndServer;
   datetime          sessionEndServer;
   bool              inWindow;
   bool              inSession;
  };

struct SessionSnapshot
  {
   bool              anyInWindow;
   int               windowSession;   // index of the session whose window is open
   datetime          windowStart;     // server time
   datetime          windowEnd;       // server time
   bool              anchorValid;
   datetime          anchor;          // VWAP anchor = latest session start (server time)
   int               anchorSession;
  };

SessionConfig g_sessions[MAX_SESSIONS];
bool          g_sessWasInWindow[MAX_SESSIONS];
bool          g_sessWasInSession[MAX_SESSIONS];
bool          g_sessLogInit = false;
int           g_autoOffsetSec = 0;
bool          g_autoOffsetValid = false;

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
   datetime start = NthSunday(y, 3, 2) + 7 * 3600;  // 02:00 EST = 07:00 UTC
   datetime end   = NthSunday(y, 11, 1) + 6 * 3600; // 02:00 EDT = 06:00 UTC
   return (utc >= start && utc < end);
  }

bool IsEuDst(const datetime utc)
  {
   int y = YearOf(utc);
   datetime start = LastSunday(y, 3) + 3600;  // 01:00 UTC
   datetime end   = LastSunday(y, 10) + 3600; // 01:00 UTC
   return (utc >= start && utc < end);
  }

// Broker server UTC offset (seconds) valid at the given server time.
int ServerOffsetSeconds(const datetime serverTime)
  {
   if(InpAutoServerOffset && !IsTester() && g_autoOffsetValid)
      return g_autoOffsetSec;
   int stdSec = InpServerUtcOffsetHours * 3600;
   datetime approxUtc = serverTime - stdSec;
   bool dst = false;
   if(InpServerDst == BROKER_DST_US)
      dst = IsUsDst(approxUtc);
   else
      if(InpServerDst == BROKER_DST_EU)
         dst = IsEuDst(approxUtc);
   return stdSec + (dst ? 3600 : 0);
  }

void RefreshAutoServerOffset()
  {
   if(!InpAutoServerOffset || IsTester())
      return;
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
      return;
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   long rounded = (long)MathRound(diff / 900.0) * 900; // 15-minute granularity
   if(rounded < -12 * 3600 || rounded > 14 * 3600)
     {
      LogThrottled("autooffset", StringFormat("Auto server offset %I64d s out of range - using manual rule", rounded), 3600);
      g_autoOffsetValid = false;
      return;
     }
   if(!g_autoOffsetValid || g_autoOffsetSec != (int)rounded)
      Log(StringFormat("Broker server UTC offset detected: %+.2f h (TimeTradeServer - TimeGMT; requires correct PC clock)",
                       rounded / 3600.0));
   g_autoOffsetSec   = (int)rounded;
   g_autoOffsetValid = true;
  }

int ZoneOffsetSeconds(const ENUM_SESSION_TZ zone, const datetime utc, const datetime serverTime)
  {
   switch(zone)
     {
      case TZ_NEW_YORK:      return -5 * 3600 + (IsUsDst(utc) ? 3600 : 0);
      case TZ_LONDON:        return (IsEuDst(utc) ? 3600 : 0);
      case TZ_TOKYO:         return 9 * 3600;
      case TZ_UTC:           return 0;
      case TZ_BROKER_SERVER: return ServerOffsetSeconds(serverTime);
     }
   return 0;
  }

// Most recent weekday start of a session at or before serverNow.
bool GetSessionState(const SessionConfig &cfg, const datetime serverNow, SessionState &st)
  {
   st.valid = false;
   st.inWindow = false;
   st.inSession = false;
   st.startServer = 0;
   st.windowEndServer = 0;
   st.sessionEndServer = 0;
   if(!cfg.enabled)
      return false;

   datetime utc   = serverNow - ServerOffsetSeconds(serverNow);
   datetime local = utc + ZoneOffsetSeconds(cfg.zone, utc, serverNow);
   long lt  = (long)local;
   long mid = lt - (lt % 86400);

   for(int k = 0; k <= 7; k++)
     {
      long ls = mid + (long)cfg.startMin * 60 - (long)k * 86400;
      if(ls > lt)
         continue;
      int dow = DowOf((datetime)ls);
      if(dow == 0 || dow == 6)          // no sessions on Saturday / Sunday (session-local)
         continue;
      long elapsed = lt - ls;
      st.valid            = true;
      st.startServer      = (datetime)((long)serverNow - elapsed);
      st.windowEndServer  = st.startServer + cfg.windowMin * 60;
      st.sessionEndServer = st.startServer + cfg.lengthMin * 60;
      st.inWindow         = (elapsed < (long)cfg.windowMin * 60);
      st.inSession        = (elapsed < (long)cfg.lengthMin * 60);
      return true;
     }
   return false;
  }

void GetSessionSnapshot(const datetime serverNow, SessionSnapshot &snap)
  {
   snap.anyInWindow   = false;
   snap.windowSession = -1;
   snap.windowStart   = 0;
   snap.windowEnd     = 0;
   snap.anchorValid   = false;
   snap.anchor        = 0;
   snap.anchorSession = -1;
   for(int i = 0; i < MAX_SESSIONS; i++)
     {
      SessionState st;
      if(!GetSessionState(g_sessions[i], serverNow, st))
         continue;
      if(!snap.anchorValid || st.startServer > snap.anchor)
        {
         snap.anchorValid   = true;
         snap.anchor        = st.startServer;
         snap.anchorSession = i;
        }
      if(st.inWindow && (!snap.anyInWindow || st.startServer > snap.windowStart))
        {
         snap.anyInWindow   = true;
         snap.windowSession = i;
         snap.windowStart   = st.startServer;
         snap.windowEnd     = st.windowEndServer;
        }
     }
  }

void UpdateSessionLogs(const datetime serverNow)
  {
   for(int i = 0; i < MAX_SESSIONS; i++)
     {
      if(!g_sessions[i].enabled)
         continue;
      SessionState st;
      GetSessionState(g_sessions[i], serverNow, st);
      string nm = g_sessions[i].name;
      if(!g_sessLogInit)
        {
         if(st.inWindow)
            Log(StringFormat("SESSION [%s] already in entry window at EA start (start %s, window ends %s, session ends %s server time)",
                             nm, Ts(st.startServer), Ts(st.windowEndServer), Ts(st.sessionEndServer)));
         else
            if(st.inSession)
               Log(StringFormat("SESSION [%s] in progress, entry window already closed (started %s, ends %s server time)",
                                nm, Ts(st.startServer), Ts(st.sessionEndServer)));
        }
      else
        {
         if(st.inWindow && !g_sessWasInWindow[i])
            Log(StringFormat("SESSION START [%s] at %s server time: entry window OPEN until %s, session ends %s, VWAP reset",
                             nm, Ts(st.startServer), Ts(st.windowEndServer), Ts(st.sessionEndServer)));
         if(!st.inWindow && g_sessWasInWindow[i])
            Log(StringFormat("SESSION [%s] entry window CLOSED at %s server time - no new entries until next session opening (exits stay active)",
                             nm, Ts(serverNow)));
         if(!st.inSession && g_sessWasInSession[i])
            Log(StringFormat("SESSION END [%s] at %s server time", nm, Ts(serverNow)));
        }
      g_sessWasInWindow[i]  = st.inWindow;
      g_sessWasInSession[i] = st.inSession;
     }
   g_sessLogInit = true;
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

bool LoadSession(const int idx, const bool en, const string name, const ENUM_SESSION_TZ zone,
                 const string start, const int windowMin, const int lengthMin)
  {
   g_sessions[idx].enabled   = en;
   g_sessions[idx].name      = name;
   g_sessions[idx].zone      = zone;
   g_sessions[idx].windowMin = windowMin;
   g_sessions[idx].lengthMin = lengthMin;
   g_sessions[idx].startMin  = 0;
   if(!en)
      return true;
   if(!ParseHHMM(start, g_sessions[idx].startMin))
     {
      Log(StringFormat("INIT ERROR: session %d start '%s' is not HH:MM", idx + 1, start));
      return false;
     }
   if(windowMin <= 0 || lengthMin < windowMin || lengthMin > 1440)
     {
      Log(StringFormat("INIT ERROR: session %d needs 0 < window (%d) <= length (%d) <= 1440", idx + 1, windowMin, lengthMin));
      return false;
     }
   Log(StringFormat("Session %d [%s]: start %s %s, entry window %d min, length %d min",
                    idx + 1, name, start, EnumToString(zone), windowMin, lengthMin));
   return true;
  }

//==================================================================//
// 4. INDICATOR MODULE                                              //
//==================================================================//
// Session VWAP on M3 bars:                                         //
//   typical_i = (Open_i + High_i + Low_i + Close_i) / 4            //
//   VWAP      = sum(typical_i * vol_i) / sum(vol_i)                //
// over every M3 bar from the bar containing the session start up   //
// to (a) the last closed bar ("closed VWAP") or (b) the forming    //
// bar with its current OHLC and volume ("live VWAP").              //
//==================================================================//
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

public:
                     CSessionVwap(void) : m_symbol(""), m_volumeKnown(false), m_useReal(false), m_anchorBar(0),
                     m_lastClosed(0), m_cacheValid(false), m_cumPV(0), m_cumV(0), m_closedCount(0),
                     m_vwapBar1(0), m_vwapBar2(0) {}

   void              Init(const string sym) { m_symbol = sym; Invalidate(); m_volumeKnown = false; }
   void              Invalidate(void) { m_cacheValid = false; m_anchorBar = 0; m_lastClosed = 0; }
   bool              UsesRealVolume(void) const { return m_useReal; }
   bool              VolumeKnown(void) const { return m_volumeKnown; }
   int               ClosedCount(void) const { return m_closedCount; }
   bool              Bar1Valid(void) const { return m_cacheValid && m_closedCount >= 1; }
   bool              Bar2Valid(void) const { return m_cacheValid && m_closedCount >= 2; }
   double            Bar1(void) const { return m_vwapBar1; }
   double            Bar2(void) const { return m_vwapBar2; }

   //--- decide which volume field to use
   bool              DetermineVolumeMode(void)
     {
      if(InpVwapVolume == VWAPVOL_TICK)
        {
         m_useReal = false;
         m_volumeKnown = true;
         return true;
        }
      if(InpVwapVolume == VWAPVOL_REAL)
        {
         m_useReal = true;
         m_volumeKnown = true;
         return true;
        }
      MqlRates rr[];
      int checkBars = (InpAutoVolumeCheckBars < 10) ? 10 : InpAutoVolumeCheckBars;
      int n = CopyRates(m_symbol, SIG_TF, 1, checkBars, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "volchk", StringFormat("%s VWAP: cannot read M3 history to choose volume source (err %d) - VWAP not available yet",
                                                         m_symbol, GetLastError()), 60);
         return false;
        }
      int zeroReal = 0;
      for(int i = 0; i < n; i++)
         if(rr[i].real_volume <= 0)
            zeroReal++;
      bool useReal = (zeroReal == 0);
      if(!m_volumeKnown || useReal != m_useReal)
         Log(StringFormat("%s VWAP volume source: %s (auto: %d M3 bars checked, %d without real volume)",
                          m_symbol, useReal ? "REAL volume" : "TICK volume", n, zeroReal));
      m_useReal = useReal;
      m_volumeKnown = true;
      return true;
     }

   //--- (re)build the closed-bar sums when the anchor or the last closed bar changes
   bool              UpdateClosed(const datetime anchor, const datetime lastClosed)
     {
      datetime anchorBar = (datetime)((long)anchor - ((long)anchor % M3_SECONDS));
      if(m_cacheValid && anchorBar == m_anchorBar && lastClosed == m_lastClosed)
         return true;

      if(anchorBar != m_anchorBar && InpVwapVolume == VWAPVOL_AUTO)
         m_volumeKnown = false;            // re-check volume source once per session
      if(!m_volumeKnown && !DetermineVolumeMode())
        {
         m_cacheValid = false;
         return false;
        }

      m_anchorBar   = anchorBar;
      m_lastClosed  = lastClosed;
      m_cumPV       = 0.0;
      m_cumV        = 0.0;
      m_closedCount = 0;
      m_vwapBar1    = 0.0;
      m_vwapBar2    = 0.0;

      if(lastClosed < anchorBar)          // no closed bar in this session yet
        {
         m_cacheValid = true;
         return true;
        }

      MqlRates rr[];
      ResetLastError();
      int n = CopyRates(m_symbol, SIG_TF, anchorBar, lastClosed, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "vwapcopy", StringFormat("%s VWAP DATA ERROR: CopyRates(M3, %s .. %s) returned %d, err %d",
                                                         m_symbol, Ts(anchorBar), Ts(lastClosed), n, GetLastError()), 60);
         m_cacheValid = false;
         return false;
        }
      for(int i = 0; i < n; i++)          // rr[0] = oldest
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
         LogThrottled(m_symbol + "vwapzero", StringFormat("%s VWAP DATA ERROR: %d closed bars since %s but total %s volume is 0 - VWAP invalid%s",
                                                         m_symbol, m_closedCount, Ts(anchorBar), m_useReal ? "REAL" : "TICK",
                                                         m_useReal ? " (broker provides no real volume; use AUTO or TICK)" : ""), 300);
         m_cacheValid = false;
         return false;
        }
      m_cacheValid = true;
      return true;
     }

   //--- live VWAP including the forming bar
   bool              Live(const MqlRates &bar0, double &vwap) const
     {
      if(!m_cacheValid || bar0.time < m_anchorBar)
         return false;
      double v  = BarVolume(bar0);
      double pv = m_cumPV + Typical(bar0) * v;
      double vv = m_cumV + v;
      if(vv <= 0.0)
         return false;
      vwap = pv / vv;
      return true;
     }
  };

//==================================================================//
// 5. ORDER EXECUTION MODULE                                        //
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

bool IsRetryable(const uint rc)
  {
   return (rc == TRADE_RETCODE_REQUOTE || rc == TRADE_RETCODE_PRICE_CHANGED || rc == TRADE_RETCODE_PRICE_OFF);
  }

// Sends a market DEAL request (open or close). Refreshes price, SL/TP and
// filling mode on every attempt. Never retries TIMEOUT/CONNECTION to avoid
// duplicate fills; the position scan on the next tick reveals the outcome.
bool SendMarketDeal(MqlTradeRequest &req, const int slPts, const int tpPts, const string ctx, MqlTradeResult &res)
  {
   string sym = req.symbol;
   int fillIdx = 0;
   double pt = SymPoint(sym);
   int maxRetries = (InpOrderRetries > 0) ? InpOrderRetries : 0;
   for(int attempt = 0; attempt <= maxRetries; attempt++)
     {
      MqlTick t;
      if(!SymbolInfoTick(sym, t) || t.bid <= 0.0 || t.ask <= 0.0)
        {
         Log(StringFormat("%s %s FAILED: no valid quote (err %d)", sym, ctx, GetLastError()));
         return false;
        }
      bool isBuy = (req.type == ORDER_TYPE_BUY);
      req.price = NormalizePrice(sym, isBuy ? t.ask : t.bid);
      if(req.position == 0)               // opening order: (re)compute stops from fill side
        {
         req.sl = (slPts > 0) ? NormalizePrice(sym, isBuy ? req.price - slPts * pt : req.price + slPts * pt) : 0.0;
         req.tp = (tpPts > 0) ? NormalizePrice(sym, isBuy ? req.price + tpPts * pt : req.price - tpPts * pt) : 0.0;
        }
      int fillCount = 0;
      req.type_filling = FillingCandidate(sym, fillIdx, fillCount);

      MqlTradeCheckResult chk;
      ZeroMemory(chk);
      ResetLastError();
      if(!OrderCheck(req, chk))
        {
         Log(StringFormat("%s %s REJECTED by OrderCheck: %s (%u) '%s' | vol=%.2f price=%s margin=%.2f free=%.2f err=%d",
                          sym, ctx, RetcodeText(chk.retcode), chk.retcode, chk.comment, req.volume,
                          Px(sym, req.price), chk.margin, chk.margin_free, GetLastError()));
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
         Log(StringFormat("%s %s OK: %s | order #%I64u deal #%I64u vol=%.2f price=%s (requested %s) sl=%s tp=%s bid=%s ask=%s",
                          sym, ctx, RetcodeText(res.retcode), res.order, res.deal, res.volume, Px(sym, res.price),
                          Px(sym, req.price), Px(sym, req.sl), Px(sym, req.tp), Px(sym, res.bid), Px(sym, res.ask)));
         if(res.retcode == TRADE_RETCODE_DONE_PARTIAL)
            Log(StringFormat("%s %s WARNING: partial fill %.2f of %.2f lots", sym, ctx, res.volume, req.volume));
         return true;
        }

      Log(StringFormat("%s %s FAILED (attempt %d/%d): %s (%u) '%s' ext=%d err=%d",
                       sym, ctx, attempt + 1, maxRetries + 1, RetcodeText(res.retcode), res.retcode,
                       res.comment, res.retcode_external, GetLastError()));
      if(res.retcode == TRADE_RETCODE_INVALID_FILL && fillIdx + 1 < fillCount)
        {
         fillIdx++;
         continue;
        }
      if(!IsRetryable(res.retcode))
         return false;
     }
   return false;
  }

bool TradingPermitted(string &why)
  {
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) && !IsTester())
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
      why = "algo trading not allowed for this EA (check EA properties)";
      return false;
     }
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
     {
      why = "trading not allowed on this account";
      return false;
     }
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
     {
      why = "expert trading disabled by broker for this account";
      return false;
     }
   return true;
  }

bool SymbolAllowsDirection(const string sym, const int dir, string &why)
  {
   long mode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED)
     {
      why = "symbol trading disabled";
      return false;
     }
   if(mode == SYMBOL_TRADE_MODE_CLOSEONLY)
     {
      why = "symbol is close-only";
      return false;
     }
   if(mode == SYMBOL_TRADE_MODE_LONGONLY && dir < 0)
     {
      why = "symbol is long-only";
      return false;
     }
   if(mode == SYMBOL_TRADE_MODE_SHORTONLY && dir > 0)
     {
      why = "symbol is short-only";
      return false;
     }
   return true;
  }

// Rounds DOWN to the volume step. Never rounds up to the minimum.
bool NormalizeLots(const string sym, const double requested, double &lots, string &why)
  {
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = vmin;
   if(step <= 0.0)
     {
      why = "symbol volume settings unavailable";
      return false;
     }
   double v = MathFloor(requested / step + 1e-7) * step;
   v = NormalizeDouble(v, VolumeDigits(step));
   if(v < vmin - 1e-10)
     {
      why = StringFormat("invalid volume: %.4f lots below broker minimum %.4f (step %.4f)", requested, vmin, step);
      return false;
     }
   if(vmax > 0.0 && v > vmax + 1e-10)
     {
      why = StringFormat("invalid volume: %.4f lots above broker maximum %.4f", requested, vmax);
      return false;
     }
   if(MathAbs(v - requested) > 1e-9)
      LogThrottled(sym + "lotadj", StringFormat("%s lot size %.4f rounded down to volume step -> %.4f", sym, requested, v), 3600);
   lots = v;
   return true;
  }

//==================================================================//
// 6. POSITION MODULE                                               //
//==================================================================//
struct PosCount
  {
   int               buys;
   int               sells;
   int               foreign;   // positions on this symbol with another magic
   double            buyVolume;
   double            sellVolume;
  };

bool IsHedgingAccount()
  {
   return (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
  }

void CountPositions(const string sym, PosCount &pc)
  {
   pc.buys = 0;
   pc.sells = 0;
   pc.foreign = 0;
   pc.buyVolume = 0.0;
   pc.sellVolume = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != sym)
         continue;
      if((ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
        {
         pc.foreign++;
         continue;
        }
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
        {
         pc.buys++;
         pc.buyVolume += PositionGetDouble(POSITION_VOLUME);
        }
      else
        {
         pc.sells++;
         pc.sellVolume += PositionGetDouble(POSITION_VOLUME);
        }
     }
  }

// Closes own positions of `type` opened before `openedBefore`.
// Returns how many matching positions remain open afterwards.
int ClosePositions(const string sym, const ENUM_POSITION_TYPE type, const datetime openedBefore, const string reason)
  {
   ulong tickets[];
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != type)
         continue;
      if((datetime)PositionGetInteger(POSITION_TIME) >= openedBefore)
         continue;
      int n = ArraySize(tickets);
      ArrayResize(tickets, n + 1);
      tickets[n] = ticket;
     }

   int remaining = 0;
   for(int k = 0; k < ArraySize(tickets); k++)
     {
      if(!PositionSelectByTicket(tickets[k]))
         continue;                         // already gone
      double vol       = PositionGetDouble(POSITION_VOLUME);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double floating  = PositionGetDouble(POSITION_PROFIT);

      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      req.action    = TRADE_ACTION_DEAL;
      req.symbol    = sym;
      req.position  = tickets[k];
      req.volume    = vol;
      req.type      = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.deviation = (ulong)InpMaxDeviationPoints;
      req.magic     = InpMagic;
      req.comment   = InpOrderComment + " exit";
      req.type_time = ORDER_TIME_GTC;

      string ctx = StringFormat("CLOSE %s #%I64u (%s, open %s, vol %.2f, floating P/L %.2f)",
                                type == POSITION_TYPE_BUY ? "BUY" : "SELL", tickets[k], reason,
                                Px(sym, openPrice), vol, floating);
      if(!SendMarketDeal(req, 0, 0, ctx, res))
         remaining++;
      else
         if(PositionSelectByTicket(tickets[k]))
            remaining++;                   // partial close - still open
     }
   return remaining;
  }

//==================================================================//
// 7. SYMBOL ENGINE                                                 //
//==================================================================//
class CSymbolEngine
  {
private:
   string            m_sym;
   double            m_lotsInput;
   int               m_maxSpreadPts;
   int               m_slPts;
   int               m_tpPts;
   int               m_emaHandle;
   CSessionVwap      m_vwap;

   datetime          m_curBarTime;
   long              m_lastTickMsc;
   datetime          m_lastTickTime;
   int               m_prevSign;        // last non-zero EMA-VWAP side, 0 = no baseline
   datetime          m_signAnchor;
   bool              m_baselineResetNow;
   datetime          m_lastEntryBar;
   datetime          m_windowKey;
   int               m_windowEntries;

   bool              m_exitBuyPending;
   bool              m_exitSellPending;
   datetime          m_exitBar;
   int               m_closeAttempts;

   double            m_dispEma;
   double            m_dispVwap;
   bool              m_dispValid;

   //--------------------------------------------------------------
   bool              DataReady(void)
     {
      int need = (InpEmaPeriod * 5 > 50) ? InpEmaPeriod * 5 : 50;
      int bars = Bars(m_sym, SIG_TF);
      if(bars < need)
        {
         LogThrottled(m_sym + "bars", StringFormat("%s DATA: only %d M3 bars available (need %d) - waiting for history", m_sym, bars, need), 60);
         return false;
        }
      int calc = BarsCalculated(m_emaHandle);
      if(calc < need)
        {
         LogThrottled(m_sym + "calc", StringFormat("%s DATA: EMA(%d) M3 calculated %d bars (need %d) - waiting", m_sym, InpEmaPeriod, calc, need), 60);
         return false;
        }
      return true;
     }

   void              ResetBaseline(const string why)
     {
      if(m_prevSign != 0)
         Log(StringFormat("%s cross baseline reset: %s", m_sym, why));
      m_prevSign = 0;
      m_baselineResetNow = true;
     }

   int               SignOf(const double diff) const
     {
      double buf = MathMax(0.0, InpCrossBufferPoints) * SymPoint(m_sym);
      if(diff > buf)
         return 1;
      if(diff < -buf)
         return -1;
      return 0;
     }

   //--- SIGNAL DETECTION: intrabar (live EMA vs live VWAP, tick to tick)
   int               DetectIntrabarCross(const bool valid, const double ema0, const double vwap0, const datetime anchor)
     {
      if(!valid)
        {
         if(m_prevSign != 0)
            ResetBaseline("EMA/VWAP not available");
         return 0;
        }
      if(anchor != m_signAnchor)
        {
         m_signAnchor = anchor;
         if(m_prevSign != 0)
            ResetBaseline("new session VWAP anchor " + Ts(anchor));
         m_prevSign = 0;
        }
      int s = SignOf(ema0 - vwap0);
      int dir = 0;
      if(s != 0)
        {
         if(m_prevSign != 0 && s != m_prevSign)
            dir = s;
         m_prevSign = s;
        }
      return dir;
     }

   //--- SIGNAL DETECTION: bar close (bar[2] -> bar[1], both inside session)
   int               DetectBarCloseCross(const double &ema[])
     {
      if(!m_vwap.Bar2Valid())
         return 0;                         // need two closed bars in the session
      int s2 = SignOf(ema[2] - m_vwap.Bar2());
      int s1 = SignOf(ema[1] - m_vwap.Bar1());
      if(s2 != 0 && s1 != 0 && s1 != s2)
         return s1;
      return 0;
     }

   //--- ACCEPTANCE: every reason a signal can be refused
   bool              AcceptSignal(const int dir, const MqlTick &tick, const datetime signalBarTime,
                                  const datetime curBarTime, const SessionSnapshot &snap,
                                  double &lots, bool &needReverse, string &why)
     {
      needReverse = false;
      if(!InpEnableNewEntries)
        {
         why = "new entries disabled (InpEnableNewEntries=false)";
         return false;
        }
      if(!snap.anyInWindow)
        {
         why = "outside every configured session entry window";
         return false;
        }
      if(tick.time < snap.windowStart || tick.time >= snap.windowEnd || (long)signalBarTime < (long)snap.windowStart - ((long)snap.windowStart % M3_SECONDS))
        {
         why = StringFormat("crossover not inside the current entry window (tick %s, window %s - %s)",
                            Ts(tick.time), Ts(snap.windowStart), Ts(snap.windowEnd));
         return false;
        }
      if(InpOneEntryPerBar && m_lastEntryBar == curBarTime)
        {
         why = "entry already attempted on this M3 bar";
         return false;
        }
      if(m_windowKey != snap.windowStart)
        {
         m_windowKey = snap.windowStart;
         m_windowEntries = 0;
        }
      if(InpMaxEntriesPerWindow > 0 && m_windowEntries >= InpMaxEntriesPerWindow)
        {
         why = StringFormat("max entries per window reached (%d)", InpMaxEntriesPerWindow);
         return false;
        }
      if(!TradingPermitted(why))
         return false;
      if(!SymbolAllowsDirection(m_sym, dir, why))
         return false;

      double pt = SymPoint(m_sym);
      long spreadPts = (long)MathRound((tick.ask - tick.bid) / pt);
      if(spreadPts > m_maxSpreadPts)
        {
         why = StringFormat("spread %I64d pts > max %d pts", spreadPts, m_maxSpreadPts);
         return false;
        }

      PosCount pc;
      CountPositions(m_sym, pc);
      bool hedging = IsHedgingAccount();
      if(!hedging && pc.foreign > 0)
        {
         why = "netting account already holds a position on this symbol from another EA/manual trade";
         return false;
        }
      int same = (dir > 0) ? pc.buys : pc.sells;
      int opp  = (dir > 0) ? pc.sells : pc.buys;
      if(opp > 0)
        {
         if(!InpReverseOnOpposite)
           {
            why = StringFormat("opposite %s position open (reverse disabled)", dir > 0 ? "SELL" : "BUY");
            return false;
           }
         needReverse = true;
        }
      int maxPos = hedging ? InpMaxPositionsPerSymbol : 1;
      if(same >= maxPos)
        {
         why = StringFormat("max positions per symbol reached (%d)", maxPos);
         return false;
        }

      if(!NormalizeLots(m_sym, m_lotsInput, lots, why))
         return false;
      double vlimit = SymbolInfoDouble(m_sym, SYMBOL_VOLUME_LIMIT);
      double sameVol = (dir > 0) ? pc.buyVolume : pc.sellVolume;
      if(vlimit > 0.0 && sameVol + lots > vlimit + 1e-10)
        {
         why = StringFormat("symbol volume limit %.2f would be exceeded", vlimit);
         return false;
        }

      long stopsLevel = SymbolInfoInteger(m_sym, SYMBOL_TRADE_STOPS_LEVEL);
      if(m_slPts > 0 && m_slPts <= stopsLevel)
        {
         why = StringFormat("stop-loss %d pts within broker stops level %I64d pts", m_slPts, stopsLevel);
         return false;
        }
      if(m_tpPts > 0 && m_tpPts <= stopsLevel)
        {
         why = StringFormat("take-profit %d pts within broker stops level %I64d pts", m_tpPts, stopsLevel);
         return false;
        }

      double margin = 0.0;
      ENUM_ORDER_TYPE ot = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      double price = (dir > 0) ? tick.ask : tick.bid;
      if(!OrderCalcMargin(ot, m_sym, lots, price, margin))
        {
         why = StringFormat("OrderCalcMargin failed (err %d)", GetLastError());
         return false;
        }
      double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      if(margin > freeMargin)
        {
         why = StringFormat("insufficient margin: need %.2f, free %.2f", margin, freeMargin);
         return false;
        }
      return true;
     }

   //--- ORDER EXECUTION for an accepted signal
   void              ExecuteEntry(const int dir, const double lots, const bool needReverse, const datetime curBarTime)
     {
      m_lastEntryBar = curBarTime;          // one attempt per signal / bar, whatever the outcome
      if(needReverse)
        {
         ENUM_POSITION_TYPE oppType = (dir > 0) ? POSITION_TYPE_SELL : POSITION_TYPE_BUY;
         int left = ClosePositions(m_sym, oppType, D'3000.01.01', "reverse on opposite signal");
         if(left > 0)
           {
            Log(StringFormat("%s ENTRY ABORTED: could not close %d opposite position(s) for reversal", m_sym, left));
            return;
           }
        }
      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      req.action    = TRADE_ACTION_DEAL;
      req.symbol    = m_sym;
      req.volume    = lots;
      req.type      = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      req.deviation = (ulong)InpMaxDeviationPoints;
      req.magic     = InpMagic;
      req.comment   = InpOrderComment;
      req.type_time = ORDER_TIME_GTC;
      string ctx = StringFormat("OPEN %s %.2f lots", dir > 0 ? "BUY" : "SELL", lots);
      if(SendMarketDeal(req, m_slPts, m_tpPts, ctx, res))
         m_windowEntries++;
     }

   void              HandleSignal(const int dir, const string mode, const MqlTick &tick, const datetime signalBarTime,
                                  const datetime curBarTime, const double ema, const double vwap, const SessionSnapshot &snap)
     {
      string side = (dir > 0) ? "BUY" : "SELL";
      Log(StringFormat("%s SIGNAL %s (%s): EMA%d %s VWAP | EMA=%s VWAP=%s bid=%s ask=%s tick=%s bar=%s",
                       m_sym, side, mode, InpEmaPeriod, dir > 0 ? "crossed ABOVE" : "crossed BELOW",
                       Px(m_sym, ema), Px(m_sym, vwap), Px(m_sym, tick.bid), Px(m_sym, tick.ask),
                       Ts(tick.time), Ts(signalBarTime)));
      double lots = 0.0;
      bool needReverse = false;
      string why = "";
      if(!AcceptSignal(dir, tick, signalBarTime, curBarTime, snap, lots, needReverse, why))
        {
         Log(StringFormat("%s SIGNAL %s REJECTED: %s", m_sym, side, why));
         return;
        }
      Log(StringFormat("%s SIGNAL %s ACCEPTED: window [%s] %s - %s, lots %.2f%s",
                       m_sym, side, g_sessions[snap.windowSession].name, Ts(snap.windowStart), Ts(snap.windowEnd),
                       lots, needReverse ? ", reversing opposite position" : ""));
      ExecuteEntry(dir, lots, needReverse, curBarTime);
     }

   //--- EXIT SIGNALS: evaluated once per new M3 bar on the just-closed bar
   void              EvaluateExitSignals(const MqlRates &r[], const double &ema[], const datetime curBarTime)
     {
      m_exitBuyPending  = false;
      m_exitSellPending = false;
      m_closeAttempts   = 0;
      m_exitBar         = curBarTime;

      PosCount pc;
      CountPositions(m_sym, pc);
      if(pc.buys == 0 && pc.sells == 0)
         return;

      double c1 = r[1].close;
      double e1 = ema[1];
      bool buyExit  = (c1 < e1);
      bool sellExit = (c1 > e1);
      string buyWhy  = StringFormat("M3 bar %s closed %s < EMA %s", Ts(r[1].time), Px(m_sym, c1), Px(m_sym, e1));
      string sellWhy = StringFormat("M3 bar %s closed %s > EMA %s", Ts(r[1].time), Px(m_sym, c1), Px(m_sym, e1));

      if(InpExitOnVwapCross && m_vwap.Bar1Valid())
        {
         double v1 = m_vwap.Bar1();
         if(e1 < v1 && !buyExit)
           {
            buyExit = true;
            buyWhy = StringFormat("optional VWAP exit: closed-bar EMA %s < VWAP %s", Px(m_sym, e1), Px(m_sym, v1));
           }
         if(e1 > v1 && !sellExit)
           {
            sellExit = true;
            sellWhy = StringFormat("optional VWAP exit: closed-bar EMA %s > VWAP %s", Px(m_sym, e1), Px(m_sym, v1));
           }
        }

      if(pc.buys > 0)
        {
         if(buyExit)
           {
            Log(StringFormat("%s EXIT SIGNAL BUY: %s", m_sym, buyWhy));
            m_exitBuyPending = true;
           }
         else
            if(InpLogEveryBar)
               Log(StringFormat("%s hold BUY: M3 close %s >= EMA %s", m_sym, Px(m_sym, c1), Px(m_sym, e1)));
        }
      if(pc.sells > 0)
        {
         if(sellExit)
           {
            Log(StringFormat("%s EXIT SIGNAL SELL: %s", m_sym, sellWhy));
            m_exitSellPending = true;
           }
         else
            if(InpLogEveryBar)
               Log(StringFormat("%s hold SELL: M3 close %s <= EMA %s", m_sym, Px(m_sym, c1), Px(m_sym, e1)));
        }
     }

   //--- POSITION MANAGEMENT: execute pending exits (retries across ticks)
   void              ManageExits(void)
     {
      if(!m_exitBuyPending && !m_exitSellPending)
         return;
      if(m_closeAttempts >= InpMaxCloseAttemptsPerBar)
        {
         LogThrottled(m_sym + "closegiveup", StringFormat("%s EXIT: %d close attempts failed this bar - will re-evaluate on next M3 bar",
                                                         m_sym, m_closeAttempts), 180);
         return;
        }
      bool failed = false;
      if(m_exitBuyPending)
        {
         if(ClosePositions(m_sym, POSITION_TYPE_BUY, m_exitBar, "EMA candle-close exit") == 0)
            m_exitBuyPending = false;
         else
            failed = true;
        }
      if(m_exitSellPending)
        {
         if(ClosePositions(m_sym, POSITION_TYPE_SELL, m_exitBar, "EMA candle-close exit") == 0)
            m_exitSellPending = false;
         else
            failed = true;
        }
      if(failed)
         m_closeAttempts++;
     }

public:
                     CSymbolEngine(void) : m_sym(""), m_lotsInput(0), m_maxSpreadPts(0), m_slPts(0), m_tpPts(0),
                     m_emaHandle(INVALID_HANDLE), m_curBarTime(0), m_lastTickMsc(0), m_lastTickTime(0),
                     m_prevSign(0), m_signAnchor(0), m_baselineResetNow(false), m_lastEntryBar(0),
                     m_windowKey(0), m_windowEntries(0), m_exitBuyPending(false), m_exitSellPending(false),
                     m_exitBar(0), m_closeAttempts(0), m_dispEma(0), m_dispVwap(0), m_dispValid(false) {}

   string            Symbol_(void) const { return m_sym; }

   bool              Init(const string sym, const double lots, const int maxSpread, const int sl, const int tp)
     {
      m_sym          = sym;
      m_lotsInput    = lots;
      m_maxSpreadPts = maxSpread;
      m_slPts        = sl;
      m_tpPts        = tp;
      m_vwap.Init(sym);

      m_emaHandle = iMA(sym, SIG_TF, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(m_emaHandle == INVALID_HANDLE)
        {
         Log(StringFormat("INIT ERROR: iMA(%s, M3, %d, EMA, CLOSE) failed, err %d", sym, InpEmaPeriod, GetLastError()));
         return false;
        }
      double lotsN = 0.0;
      string why = "";
      if(!NormalizeLots(sym, lots, lotsN, why))
         Log(StringFormat("WARNING %s: %s - every entry will be rejected until fixed", sym, why));
      Log(StringFormat("%s ready: digits=%d point=%s tick size=%s vol min/step/max=%.2f/%.2f/%.2f stops level=%d spread now=%d pts, max %d pts, lots %.2f, SL %d pts, TP %d pts, filling=%d, exec mode=%s",
                       sym, SymDigits(sym), DoubleToString(SymPoint(sym), SymDigits(sym)),
                       DoubleToString(SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE), SymDigits(sym)),
                       SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP),
                       SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX), (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL),
                       (int)SymbolInfoInteger(sym, SYMBOL_SPREAD), maxSpread, lots, sl, tp,
                       (int)SymbolInfoInteger(sym, SYMBOL_FILLING_MODE),
                       EnumToString((ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(sym, SYMBOL_TRADE_EXEMODE))));
      return true;
     }

   void              Deinit(void)
     {
      if(m_emaHandle != INVALID_HANDLE)
        {
         IndicatorRelease(m_emaHandle);
         m_emaHandle = INVALID_HANDLE;
        }
     }

   void              OnReconnect(void)
     {
      ResetBaseline("terminal reconnected");
      m_vwap.Invalidate();
     }

   //--- main per-symbol pipeline
   void              Process(const SessionSnapshot &snap)
     {
      MqlTick tick;
      if(!SymbolInfoTick(m_sym, tick) || tick.bid <= 0.0)
        {
         LogThrottled(m_sym + "tick", StringFormat("%s DATA: no tick available (err %d)", m_sym, GetLastError()), 60);
         return;
        }
      if(tick.time_msc == m_lastTickMsc)
        {
         if(InpManageExits)
            ManageExits();                // retry pending exits on timer
         return;
        }

      if(!DataReady())
        {
         if(m_prevSign != 0)
            ResetBaseline("indicator data not ready");
         return;
        }

      MqlRates r[];
      double   ema[];
      ArraySetAsSeries(r, true);
      ArraySetAsSeries(ema, true);
      ResetLastError();
      if(CopyRates(m_sym, SIG_TF, 0, 3, r) != 3)
        {
         LogThrottled(m_sym + "rates", StringFormat("%s DATA ERROR: CopyRates M3 failed (err %d)", m_sym, GetLastError()), 60);
         return;
        }
      if(CopyBuffer(m_emaHandle, 0, 0, 3, ema) != 3 || ema[0] == EMPTY_VALUE || ema[1] == EMPTY_VALUE || ema[2] == EMPTY_VALUE)
        {
         LogThrottled(m_sym + "ema", StringFormat("%s DATA ERROR: EMA buffer copy failed (err %d)", m_sym, GetLastError()), 60);
         return;
        }

      //--- tick gap / reconnect protection: a cross that formed while we were blind is not traded
      m_baselineResetNow = false;
      if(InpBaselineResetGapSec > 0 && m_lastTickTime > 0 && (long)(tick.time - m_lastTickTime) > InpBaselineResetGapSec)
         ResetBaseline(StringFormat("tick gap %I64d s (%s -> %s)", (long)(tick.time - m_lastTickTime), Ts(m_lastTickTime), Ts(tick.time)));
      bool firstRun = (m_curBarTime == 0);
      if(firstRun)
         m_baselineResetNow = true;
      m_lastTickMsc  = tick.time_msc;
      m_lastTickTime = tick.time;

      //--- VWAP
      double vwap0 = 0.0;
      bool vwapOk = false;
      if(snap.anchorValid && m_vwap.UpdateClosed(snap.anchor, r[1].time))
         vwapOk = m_vwap.Live(r[0], vwap0);
      if(!snap.anchorValid)
         LogThrottled(m_sym + "anchor", m_sym + " VWAP: no enabled session start found - VWAP unavailable", 600);

      m_dispEma = ema[0];
      m_dispVwap = vwap0;
      m_dispValid = vwapOk;

      //--- new M3 bar: log, exits, bar-close signals
      bool isNewBar = (r[0].time != m_curBarTime);
      if(isNewBar)
        {
         m_curBarTime = r[0].time;
         if(InpLogEveryBar)
            Log(StringFormat("%s M3 bar closed %s: O=%s H=%s L=%s C=%s | EMA%d=%s | VWAP=%s (%s vol, %d bars since %s) | live EMA=%s VWAP=%s",
                             m_sym, Ts(r[1].time), Px(m_sym, r[1].open), Px(m_sym, r[1].high), Px(m_sym, r[1].low),
                             Px(m_sym, r[1].close), InpEmaPeriod, Px(m_sym, ema[1]),
                             m_vwap.Bar1Valid() ? Px(m_sym, m_vwap.Bar1()) : "n/a",
                             m_vwap.UsesRealVolume() ? "real" : "tick", m_vwap.ClosedCount(),
                             snap.anchorValid ? Ts(snap.anchor) : "-",
                             Px(m_sym, ema[0]), vwapOk ? Px(m_sym, vwap0) : "n/a"));
         if(InpManageExits && (!firstRun || InpExitCheckOnStart))
            EvaluateExitSignals(r, ema, r[0].time);

         if(InpSignalMode == SIGNAL_BAR_CLOSE && !firstRun && !m_baselineResetNow)
           {
            int dirBc = DetectBarCloseCross(ema);
            if(dirBc != 0)
               HandleSignal(dirBc, "bar-close", tick, r[1].time, r[0].time, ema[1], m_vwap.Bar1(), snap);
           }
        }

      if(InpManageExits)
         ManageExits();

      if(InpLogEveryTick)
         Log(StringFormat("%s tick %s bid=%s ask=%s live EMA=%s VWAP=%s", m_sym, Ts(tick.time), Px(m_sym, tick.bid),
                          Px(m_sym, tick.ask), Px(m_sym, ema[0]), vwapOk ? Px(m_sym, vwap0) : "n/a"));

      //--- intrabar signals (baseline tracked even outside windows)
      if(InpSignalMode == SIGNAL_INTRABAR)
        {
         if(m_baselineResetNow)
            m_prevSign = 0;
         int dir = DetectIntrabarCross(vwapOk, ema[0], vwap0, snap.anchor);
         if(dir != 0)
            HandleSignal(dir, "intrabar", tick, r[0].time, r[0].time, ema[0], vwap0, snap);
        }
     }

   string            StatusLine(void) const
     {
      PosCount pc;
      CountPositions(m_sym, pc);
      string side = (m_prevSign > 0) ? "EMA>VWAP" : (m_prevSign < 0 ? "EMA<VWAP" : "no baseline");
      return StringFormat("%s  EMA=%s  VWAP=%s  [%s]  pos B%d/S%d",
                          m_sym, Px(m_sym, m_dispEma), m_dispValid ? Px(m_sym, m_dispVwap) : "n/a", side, pc.buys, pc.sells);
     }
  };

//==================================================================//
// 8. EVENT HANDLERS                                                //
//==================================================================//
CSymbolEngine *g_engines[];
bool          g_wasConnected = true;
datetime      g_lastOffsetRefresh = 0;
datetime      g_lastComment = 0;

datetime ServerNow()
  {
   return IsTester() ? TimeCurrent() : TimeTradeServer();
  }

bool AddEngine(const string base, const double lots, const int maxSpread, const int sl, const int tp)
  {
   string sym = InpSymbolPrefix + base + InpSymbolSuffix;
   if(!SymbolSelect(sym, true))
     {
      Log(StringFormat("INIT ERROR: symbol '%s' not found / cannot be selected (err %d). Check prefix/suffix inputs.", sym, GetLastError()));
      return false;
     }
   CSymbolEngine *e = new CSymbolEngine();
   if(!e.Init(sym, lots, maxSpread, InpUseStopLoss ? sl : 0, InpUseTakeProfit ? tp : 0))
     {
      delete e;
      return false;
     }
   int n = ArraySize(g_engines);
   ArrayResize(g_engines, n + 1);
   g_engines[n] = e;
   return true;
  }

void FreeEngines()
  {
   for(int i = 0; i < ArraySize(g_engines); i++)
     {
      if(CheckPointer(g_engines[i]) == POINTER_DYNAMIC)
        {
         g_engines[i].Deinit();
         delete g_engines[i];
        }
     }
   ArrayResize(g_engines, 0);
  }

void CheckConnection()
  {
   if(IsTester())
      return;
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   if(connected && !g_wasConnected)
     {
      Log("Terminal RECONNECTED - resetting cross baselines and VWAP caches");
      for(int i = 0; i < ArraySize(g_engines); i++)
         g_engines[i].OnReconnect();
      RefreshAutoServerOffset();
     }
   if(!connected && g_wasConnected)
      Log("Terminal DISCONNECTED from trade server - no signals can be acted on until reconnection");
   g_wasConnected = connected;
  }

void ProcessAll()
  {
   CheckConnection();
   datetime now = ServerNow();
   if(!IsTester() && now - g_lastOffsetRefresh >= 3600)
     {
      RefreshAutoServerOffset();
      g_lastOffsetRefresh = now;
     }
   SessionSnapshot snap;
   GetSessionSnapshot(now, snap);
   UpdateSessionLogs(now);

   for(int i = 0; i < ArraySize(g_engines); i++)
      g_engines[i].Process(snap);

   if(InpShowChartComment && !IsTester() && now != g_lastComment)
     {
      g_lastComment = now;
      string txt = StringFormat("SessionVwapEma9EA (EXPERIMENTAL)  server %s  |  %s\n", Ts(now),
                                snap.anyInWindow ? StringFormat("ENTRY WINDOW [%s] until %s", g_sessions[snap.windowSession].name, Ts(snap.windowEnd))
                                : "outside entry windows (exits active)");
      if(!InpUseStopLoss && !InpUseTakeProfit)
         txt += "WARNING: no SL/TP - exposure until EMA exit\n";
      for(int i = 0; i < ArraySize(g_engines); i++)
         txt += g_engines[i].StatusLine() + "\n";
      Comment(txt);
     }
  }

int OnInit()
  {
   Log("==================================================================");
   Log("SessionVwapEma9EA v1.00 - EXPERIMENTAL strategy test, not production software");
   Log(StringFormat("Account margin mode: %s | tester=%s | chart %s %s (calculations always use M3)",
                    IsHedgingAccount() ? "HEDGING" : "NETTING/EXCHANGE", IsTester() ? "yes" : "no",
                    _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period)));

   //--- input validation
   if(InpEmaPeriod < 1)
     {
      Log("INIT ERROR: InpEmaPeriod must be >= 1");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpLotsGold <= 0.0 || InpLotsSilver <= 0.0)
     {
      Log("INIT ERROR: lot sizes must be > 0");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpMaxPositionsPerSymbol < 1 || InpMaxDeviationPoints < 0 || InpMaxSpreadPointsGold < 0 || InpMaxSpreadPointsSilver < 0)
     {
      Log("INIT ERROR: max positions must be >= 1, deviation and spreads >= 0");
      return INIT_PARAMETERS_INCORRECT;
     }
   if((InpUseStopLoss && (InpStopLossPointsGold <= 0 || InpStopLossPointsSilver <= 0)) ||
      (InpUseTakeProfit && (InpTakeProfitPointsGold <= 0 || InpTakeProfitPointsSilver <= 0)))
     {
      Log("INIT ERROR: enabled SL/TP distances must be > 0 points");
      return INIT_PARAMETERS_INCORRECT;
     }

   if(!LoadSession(0, InpS1Enabled, InpS1Name, InpS1Zone, InpS1Start, InpS1WindowMinutes, InpS1LengthMinutes) ||
      !LoadSession(1, InpS2Enabled, InpS2Name, InpS2Zone, InpS2Start, InpS2WindowMinutes, InpS2LengthMinutes) ||
      !LoadSession(2, InpS3Enabled, InpS3Name, InpS3Zone, InpS3Start, InpS3WindowMinutes, InpS3LengthMinutes))
      return INIT_PARAMETERS_INCORRECT;
   if(!InpS1Enabled && !InpS2Enabled && !InpS3Enabled)
     {
      Log("INIT ERROR: no session enabled - the EA could never enter");
      return INIT_PARAMETERS_INCORRECT;
     }
   for(int i = 0; i < MAX_SESSIONS; i++)
     {
      g_sessWasInWindow[i]  = false;
      g_sessWasInSession[i] = false;
     }
   g_sessLogInit = false;

   //--- broker time
   g_autoOffsetValid = false;
   RefreshAutoServerOffset();
   if(!g_autoOffsetValid)
      Log(StringFormat("Broker server time: manual rule UTC%+d (standard) with %s DST%s",
                       InpServerUtcOffsetHours, EnumToString(InpServerDst),
                       IsTester() ? " (Strategy Tester: auto detection is not possible)" : ""));
   Log(StringFormat("Server now %s -> UTC offset %+.2f h", Ts(ServerNow()), ServerOffsetSeconds(ServerNow()) / 3600.0));

   //--- risk warning
   if(!InpUseStopLoss && !InpUseTakeProfit)
      Log("WARNING: STOP-LOSS AND TAKE-PROFIT ARE DISABLED. Open positions are exposed to potentially substantial losses "
          "until the M3 close-vs-EMA exit fires (or indefinitely if the EA is stopped / disconnected).");
   else
      if(!InpUseStopLoss)
         Log("WARNING: STOP-LOSS IS DISABLED - downside is unbounded until the EMA exit fires.");

   //--- symbols
   ArrayResize(g_engines, 0);
   bool ok = true;
   if(InpSymbolSet == SYMSET_GOLD_AND_SILVER || InpSymbolSet == SYMSET_GOLD_ONLY)
      ok = ok && AddEngine(InpGoldSymbol, InpLotsGold, InpMaxSpreadPointsGold, InpStopLossPointsGold, InpTakeProfitPointsGold);
   if(InpSymbolSet == SYMSET_GOLD_AND_SILVER || InpSymbolSet == SYMSET_SILVER_ONLY)
      ok = ok && AddEngine(InpSilverSymbol, InpLotsSilver, InpMaxSpreadPointsSilver, InpStopLossPointsSilver, InpTakeProfitPointsSilver);
   if(!ok || ArraySize(g_engines) == 0)
     {
      FreeEngines();
      return INIT_FAILED;
     }
   Log(StringFormat("Signal mode %s, cross buffer %.1f pts, baseline gap reset %d s, one entry/bar=%s, max entries/window=%d, reverse=%s, new entries=%s, VWAP exit=%s",
                    EnumToString(InpSignalMode), InpCrossBufferPoints, InpBaselineResetGapSec,
                    InpOneEntryPerBar ? "yes" : "no", InpMaxEntriesPerWindow, InpReverseOnOpposite ? "yes" : "no",
                    InpEnableNewEntries ? "ON" : "OFF", InpExitOnVwapCross ? "ON" : "OFF"));

   g_wasConnected = IsTester() ? true : (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   if(!EventSetMillisecondTimer(500))
      Log(StringFormat("WARNING: timer could not be created (err %d) - only chart-symbol ticks will drive the EA", GetLastError()));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   FreeEngines();
   Comment("");
   Log(StringFormat("Deinitialized (reason %d). Open positions are NOT closed and are no longer managed.", reason));
  }

void OnTick()  { ProcessAll(); }
void OnTimer() { ProcessAll(); }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if((ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   string sym   = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   long   entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   long   type  = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
   long   rsn   = HistoryDealGetInteger(trans.deal, DEAL_REASON);
   string e = (entry == DEAL_ENTRY_IN) ? "OPENED" : (entry == DEAL_ENTRY_OUT ? "CLOSED" : (entry == DEAL_ENTRY_INOUT ? "REVERSED" : "CLOSED_BY"));
   Log(StringFormat("DEAL %s %s #%I64u %s %.2f lots @ %s | position #%I64d | profit %.2f commission %.2f swap %.2f | reason %s",
                    sym, e, trans.deal, type == DEAL_TYPE_BUY ? "BUY" : (type == DEAL_TYPE_SELL ? "SELL" : "OTHER"),
                    HistoryDealGetDouble(trans.deal, DEAL_VOLUME), Px(sym, HistoryDealGetDouble(trans.deal, DEAL_PRICE)),
                    HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID), HistoryDealGetDouble(trans.deal, DEAL_PROFIT),
                    HistoryDealGetDouble(trans.deal, DEAL_COMMISSION), HistoryDealGetDouble(trans.deal, DEAL_SWAP),
                    EnumToString((ENUM_DEAL_REASON)rsn)));
  }
//+------------------------------------------------------------------+
