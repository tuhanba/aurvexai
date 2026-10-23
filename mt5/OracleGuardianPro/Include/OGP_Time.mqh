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
