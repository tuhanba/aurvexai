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
int        g_vwapResetMin = 18 * 60;
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
   ok = ok && ParseHHMM(InpVwapDailyResetNY, g_vwapResetMin) && ParseHHMM(InpRolloverStartNY, g_rollStartMin) && ParseHHMM(InpRolloverEndNY, g_rollEndMin) &&
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

// VWAP anchor: daily reset (TradingView "Session" anchor) and/or enabled session starts
datetime VwapAnchor(const datetime server)
  {
   datetime best = 0;
   for(int i = 0; i < OGP_MAX_SESSIONS && InpVwapAnchor != OGP_VWAP_DAILY; i++)
     {
      if(!g_sess[i].enabled)
         continue;
      datetime t = MostRecentStart(g_sess[i].zone, g_sess[i].startMin, 0x3E, server); // Mon..Fri
      if(t > best)
         best = t;
     }
   if(InpVwapAnchor != OGP_VWAP_SESSIONS || best == 0)
     {
      // trading day opens in the NY evening Sun..Thu (e.g. 18:00); a reset before noon runs Mon..Fri
      int mask = (g_vwapResetMin >= 12 * 60) ? 0x1F : 0x3E;
      datetime t = MostRecentStart(OGP_ZONE_NEWYORK, g_vwapResetMin, mask, server);
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
