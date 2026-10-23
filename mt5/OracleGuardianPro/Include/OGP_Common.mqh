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
