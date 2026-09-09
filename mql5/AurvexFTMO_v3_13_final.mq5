//+------------------------------------------------------------------+
//| AurvexFTMO_v3_12_merged.mq5                                       |
//| MERGE: hardened rewrite (v3.11, credit: friend's hardening) +     |
//|        Aurvex validated-strategy layer (v2.6-2.8).                |
//|                                                                    |
//| From the v3.11 base (kept):                                        |
//|   * restart-safe GlobalVariable persistence (state, plan, FTMO)   |
//|   * automatic CET/CEST + EST/EDT DST (FTMO reset + index sessions) |
//|   * OnTradeTransaction fill capture + planned-SL original-R        |
//|   * margin validation, retcode checks, broker freeze/stops guard   |
//|   * OrderCalcProfit-based lot sizing                               |
//| Added Aurvex validated layer (default-OFF where it changes fills): |
//|   * OrbRangeHourUTC + per-session effective magic (BTC multi-sess) |
//|   * MinRangeMedMult (GOLD low-vol-day filter, OOS +0.19->+0.36)    |
//|   * PdhlMinRangeMedMult (JP225 low-vol-day filter)                 |
//|   * PhaseTargetPct profit-lock                                     |
//|   * JournalTrades context CSV for KAPI-1 retro-testing             |
//|   * PDHL DEFAULTS to validated calendar-prior-day (skip Monday);   |
//|     PdhlUseBackScan=true restores v3.11's back-scan (which trades  |
//|     Mondays off Friday — net-NEGATIVE on GER40/NAS100 in tests,    |
//|     so it is OFF by default). See FTMO_PER_INSTRUMENT_RESEARCH.md. |
//|                                                                    |
//| ⚠ REVIEWED SKELETON — compile (F7) + demo-verify before any live   |
//|   use. Do not put on the funded/challenge account until the demo   |
//|   shows clean logs and fills.                                      |
//+------------------------------------------------------------------+
#property copyright "Aurvex / hardened rewrite + validated-strategy merge"
#property version   "3.13"
// v3.13 hardening (post-review): (1) reject risk multipliers >1 (never-raise
//   enforced, not just commented); (2) reject ORB windows that cross UTC midnight;
//   (3) size margin for BUY_STOP/SELL_STOP (the order types actually sent);
//   (4) retry the trade-journal write from the timer if the fill-event write missed.
//   Telegram URL-encoding intentionally not added — Telegram is unused (dormant).
#property strict

#include <Trade/Trade.mqh>

//--------------------------- strategy inputs -------------------------//
input double RiskPct             = 0.50;   // target risk per trade, % of AccountSize
input string ForceStrategy       = "AUTO"; // AUTO | ORB | PDHL
input int    OrbHours            = 1;      // opening-range length (hours)
input int    OrbRangeHourUTC     = 0;      // ORB range START hour UTC (0=00:00; BTC multi-session 0/3/13 on separate charts)
input double PdhlStopATR         = 1.50;   // PDHL stop distance = ATR(14) * multiplier
input double TrailStopR          = 0.50;   // trailing distance in initial R; 0 = disabled

//--------------------------- validated-strategy filters --------------//
input double MinRangeMedMult     = 0.0;    // ORB low-vol-day filter: require today's opening range >= x * trailing-20d median (0=off; GOLD: 1.0)
input double PdhlMinRangeMedMult  = 0.0;   // PDHL low-vol-day filter: require prior-day range >= x * trailing-20d median (0=off; JP225: 1.0 after KAPI-1)
input bool   PdhlUseBackScan     = false;  // false = validated calendar prior-day (skip Monday); true = v3.11 back-scan (trades Mon off Fri — negative on GER40/NAS100)

//--------------------------- profit-lock (v2.7) ----------------------//
input double PhaseTargetPct      = 0.0;    // profit-lock: phase target % (0=off; 10 Phase-1, 5 Phase-2)
input double NearTargetPct       = 1.5;    // within this % of the target, cut risk to NearTargetMult
input double NearTargetMult      = 0.5;    // risk multiplier once near the target

//--------------------------- account guard ---------------------------//
input double AccountSize         = 0;      // REQUIRED, e.g. 25000
input bool   RequireAccountSize  = true;   // refuse to start if AccountSize <= 0
const double FTMO_DAILY_LOSS_PCT   = 5.0;
const double FTMO_OVERALL_LOSS_PCT = 10.0;
input double LossBufferPct       = 1.0;    // 1.0 => guards at 4% daily / 9% overall
input double DeriskDD1Pct        = 3.0;
input double DeriskMult1         = 0.60;
input double DeriskDD2Pct        = 6.0;
input double DeriskMult2         = 0.35;
input double MaxSingleRiskMult   = 2.0;

//--------------------------- execution guard -------------------------//
input double MaxSpreadPoints      = 0;      // 0 = disabled; absolute spread cap in points
input double MaxSpreadToStopPct   = 12.5;   // spread may not exceed this % of planned SL distance; 0 = disabled
input bool   UseFreezeLevelGuard  = true;   // respect broker freeze level
input int    ExtraStopBufferPts   = 2;      // extra points beyond broker stop/freeze minimum
input double MarginSafetyFactor   = 1.10;   // require free margin >= calc margin * factor
input bool   AccountWideEmergencyFlatten = true; // guard breach: close/delete entire account

//--------------------------- session/time ----------------------------//
input bool   AutoPdhlSession     = true;   // GER/DAX and US/NAS symbols: cash-session gate
input int    PdhlStartUTCMin     = -1;     // manual override, minutes after UTC midnight
input int    PdhlEndUTCMin       = -1;     // -1/-1 = auto/no manual gate
input int    FridayFlattenUTCMin = 20*60;  // default 20:00 UTC
input int    TimerSeconds        = 2;
input int    ServerUtcOffsetOverrideHours = 999; // 999 = auto from live server
input int    TesterServerUtcOffsetHours   = 999;

//--------------------------- news ------------------------------------//
input bool   AvoidNews            = true;
input int    NewsBufferMin        = 2;
input bool   FreezeTrailInNews    = true;
input string NewsCurrencyOverride = "";
input bool   NewsFailClosed       = true;

//--------------------------- misc ------------------------------------//
input bool   DrawLevels          = true;
input bool   JournalTrades       = true;   // log each entry's context to MQL5/Files (passive)
input long   Magic               = 770077;
input string TelegramToken       = "";
input string TelegramChatID      = "";

CTrade trade;
string SYM, STRAT;
long   g_magic = 0;            // effective magic = Magic + OrbRangeHourUTC (multi-session safe)

bool     g_tradedToday = false;
bool     g_fridayFlat  = false;
bool     g_journaled   = false;
datetime g_utcTradeDay = 0;

datetime g_ftmoDay     = 0;
double   g_ftmoOpenBal = 0;
double   g_initBal     = 0;
bool     g_guardTripped = false;
bool     g_overallGuardTripped = false;

// trailing state
bool   g_haveTrade = false;
bool   g_tLong     = false;
double g_tEntry    = 0;
double g_tRisk     = 0;
double g_tPeak     = 0;
double g_lastPeakPersist = 0;
datetime g_lastPeakPersistTime = 0;

// journal setup context (stashed at arm time)
double g_ctxHi=0, g_ctxLo=0, g_ctxRefPct=0, g_ctxMedPct=0, g_ctxSpreadPct=0;

//--------------------------- naming/persistence ----------------------//
string AccountPrefix()
{
   return StringFormat("AX3_%I64d_%I64d_", (long)AccountInfoInteger(ACCOUNT_LOGIN), g_magic);
}
string SymPrefix(){ return AccountPrefix() + SYM + "_"; }
string FtmoPrefix()
{
   // Risk state is account-wide and intentionally independent of Magic/Symbol.
   return StringFormat("AX312_FTMO_%I64d_", (long)AccountInfoInteger(ACCOUNT_LOGIN));
}
void GVSet(string name,double v)
{
   if(GlobalVariableSet(name,v)==0)
      PrintFormat("GV set failed %s err=%d",name,GetLastError());
}
bool GVGet(string name,double &v)
{
   if(!GlobalVariableCheck(name)) return false;
   return GlobalVariableGet(name,v);
}
void FlushState(){ GlobalVariablesFlush(); }

void SaveTradeDayState()
{
   GVSet(SymPrefix()+"UTC_DAY",(double)g_utcTradeDay);
   GVSet(SymPrefix()+"TRADED", g_tradedToday ? 1.0 : 0.0);
   GVSet(SymPrefix()+"FRIFLAT",g_fridayFlat  ? 1.0 : 0.0);
   GVSet(SymPrefix()+"JOURNALED",g_journaled ? 1.0 : 0.0);
   FlushState();
}
void SaveFtmoState()
{
   GVSet(FtmoPrefix()+"FTMO_DAY",(double)g_ftmoDay);
   GVSet(FtmoPrefix()+"FTMO_BAL",g_ftmoOpenBal);
   GVSet(FtmoPrefix()+"INIT_BAL",g_initBal);
   GVSet(FtmoPrefix()+"GUARD_DAY",g_guardTripped?1.0:0.0);
   GVSet(FtmoPrefix()+"GUARD_ALL",g_overallGuardTripped?1.0:0.0);
   FlushState();
}
void SaveTrailState()
{
   GVSet(SymPrefix()+"T_HAVE", g_haveTrade?1.0:0.0);
   GVSet(SymPrefix()+"T_LONG", g_tLong?1.0:0.0);
   GVSet(SymPrefix()+"T_ENTRY",g_tEntry);
   GVSet(SymPrefix()+"T_RISK", g_tRisk);
   GVSet(SymPrefix()+"T_PEAK", g_tPeak);
   FlushState();
}
void ClearTrailState()
{
   g_haveTrade=false; g_tLong=false; g_tEntry=0; g_tRisk=0; g_tPeak=0;
   g_lastPeakPersist=0; g_lastPeakPersistTime=0;
   SaveTrailState();
}
void PersistTrailPeakIfNeeded()
{
   if(!g_haveTrade || g_tRisk<=0 || g_tPeak<=0) return;
   datetime now=TimeTradeServer();
   double move=MathAbs(g_tPeak-g_lastPeakPersist);
   if(g_lastPeakPersist<=0 || move>=0.10*g_tRisk || now-g_lastPeakPersistTime>=5)
   {
      GVSet(SymPrefix()+"T_PEAK",g_tPeak);
      g_lastPeakPersist=g_tPeak;
      g_lastPeakPersistTime=now;
   }
}
void SavePlan(bool isBuy,double entry,double sl)
{
   string p=SymPrefix()+(isBuy?"BUY_":"SELL_");
   GVSet(p+"ENTRY",entry);
   GVSet(p+"SL",sl);
}
bool LoadPlan(bool isBuy,double &entry,double &sl)
{
   string p=SymPrefix()+(isBuy?"BUY_":"SELL_");
   return GVGet(p+"ENTRY",entry) && GVGet(p+"SL",sl);
}

//--------------------------- date/time helpers -----------------------//
datetime UtcDayStart(datetime t){ return (datetime)((long)t/86400*86400); }

datetime MakeUtc(int y,int mon,int day,int hour=0,int min=0)
{
   MqlDateTime d={};
   d.year=y; d.mon=mon; d.day=day; d.hour=hour; d.min=min; d.sec=0;
   return StructToTime(d);
}
int DaysInMonth(int y,int mon)
{
   int ny=y, nm=mon+1;
   if(nm==13){ nm=1; ny++; }
   datetime t=MakeUtc(ny,nm,1)-86400;
   MqlDateTime d; TimeToStruct(t,d);
   return d.day;
}
datetime NthSundayUtc(int y,int mon,int nth,int hourUtc)
{
   datetime first=MakeUtc(y,mon,1,hourUtc,0);
   MqlDateTime d; TimeToStruct(first,d);
   int firstSunday=1+((7-d.day_of_week)%7);
   return MakeUtc(y,mon,firstSunday+7*(nth-1),hourUtc,0);
}
datetime LastSundayUtc(int y,int mon,int hourUtc)
{
   int last=DaysInMonth(y,mon);
   datetime t=MakeUtc(y,mon,last,hourUtc,0);
   MqlDateTime d; TimeToStruct(t,d);
   int lastSunday=last-d.day_of_week;
   return MakeUtc(y,mon,lastSunday,hourUtc,0);
}
bool EuropeDst(datetime utc)
{
   MqlDateTime d; TimeToStruct(utc,d);
   datetime start=LastSundayUtc(d.year,3,1);
   datetime end  =LastSundayUtc(d.year,10,1);
   return (utc>=start && utc<end);
}
bool NewYorkDst(datetime utc)
{
   MqlDateTime d; TimeToStruct(utc,d);
   datetime start=NthSundayUtc(d.year,3,2,7);
   datetime end  =NthSundayUtc(d.year,11,1,6);
   return (utc>=start && utc<end);
}
int PragueUtcOffsetSec(datetime utc){ return EuropeDst(utc)?7200:3600; }
int NewYorkUtcOffsetSec(datetime utc){ return NewYorkDst(utc)?-14400:-18000; }

datetime FtmoDayStart(datetime utc)
{
   int off=PragueUtcOffsetSec(utc);
   datetime local=(datetime)((long)utc+off);
   datetime localMid=UtcDayStart(local);
   datetime guess=(datetime)((long)localMid-off);
   int off2=PragueUtcOffsetSec(guess);
   return (datetime)((long)localMid-off2);
}

long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999)
      return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999)
      return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}

//--------------------------- strategy/session ------------------------//
string DetectStrategy()
{
   string s=ForceStrategy; StringToUpper(s);
   if(s=="ORB" || s=="PDHL") return s;
   string z=SYM; StringToUpper(z);
   if(StringFind(z,"XAU")>=0 || StringFind(z,"GOLD")>=0 ||
      StringFind(z,"XAG")>=0 || StringFind(z,"SILVER")>=0)
      return "ORB";
   return "PDHL";
}
bool IsGermanIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"GER")>=0 || StringFind(s,"DAX")>=0 ||
          StringFind(s,"DE40")>=0 || StringFind(s,"DE30")>=0;
}
bool IsUSIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"US100")>=0 || StringFind(s,"NAS")>=0 ||
          StringFind(s,"USTEC")>=0 || StringFind(s,"NDX")>=0 ||
          StringFind(s,"US500")>=0 || StringFind(s,"SPX")>=0 ||
          StringFind(s,"US30")>=0 || StringFind(s,"DJ")>=0;
}
bool IsAsianIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"JP225")>=0 || StringFind(s,"JPN")>=0 ||
          StringFind(s,"N225")>=0 || StringFind(s,"NIK")>=0 ||
          StringFind(s,"HK")>=0   || StringFind(s,"JP")>=0;
}
bool PdhlSessionAllowed(datetime nowGmt)
{
   int minuteUtc=(int)(((long)nowGmt%86400)/60);
   if(PdhlStartUTCMin>=0 && PdhlEndUTCMin>=0 && PdhlStartUTCMin<PdhlEndUTCMin)
      return minuteUtc>=PdhlStartUTCMin && minuteUtc<PdhlEndUTCMin;
   if(!AutoPdhlSession) return true;
   if(IsGermanIndex(SYM))
   {
      int offMin=PragueUtcOffsetSec(nowGmt)/60;
      int start=9*60-offMin;
      int end=17*60+30-offMin;
      return minuteUtc>=start && minuteUtc<end;
   }
   if(IsUSIndex(SYM))
   {
      int offMin=NewYorkUtcOffsetSec(nowGmt)/60;
      int start=9*60+30-offMin;
      int end=16*60-offMin;
      return minuteUtc>=start && minuteUtc<end;
   }
   if(IsAsianIndex(SYM))
   {
      // Tokyo cash ~09:00-15:00 JST = 00:00-06:00 UTC (Japan has no DST).
      return minuteUtc>=0 && minuteUtc<6*60;
   }
   return true;
}

//--------------------------- notifications ---------------------------//
void Notify(string msg)
{
   Print(msg);
   if(StringLen(TelegramToken)==0 || StringLen(TelegramChatID)==0) return;
   string url="https://api.telegram.org/bot"+TelegramToken+"/sendMessage";
   string post="chat_id="+TelegramChatID+"&text="+msg;
   char data[]; StringToCharArray(post,data,0,StringLen(post));
   char res[]; string rhdr;
   ResetLastError();
   int code=WebRequest("POST",url,"Content-Type: application/x-www-form-urlencoded\r\n",
                       5000,data,res,rhdr);
   if(code==-1) PrintFormat("Telegram WebRequest failed err=%d",GetLastError());
}

//--------------------------- trade-result checks ---------------------//
bool RetcodeOk()
{
   uint r=trade.ResultRetcode();
   return (r==TRADE_RETCODE_DONE || r==TRADE_RETCODE_PLACED ||
           r==TRADE_RETCODE_DONE_PARTIAL || r==TRADE_RETCODE_NO_CHANGES);
}
bool CheckTradeCall(bool callOk,string action)
{
   bool ok=callOk && RetcodeOk();
   if(!ok)
      Notify(StringFormat("%s %s failed ret=%u %s",
             SYM,action,trade.ResultRetcode(),trade.ResultRetcodeDescription()));
   return ok;
}

//--------------------------- positions/orders ------------------------//
bool HasPosition(string sym)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==g_magic) return true;
   }
   return false;
}
bool HasPendingSide(string sym,bool isBuy)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym || OrderGetInteger(ORDER_MAGIC)!=g_magic) continue;
      ENUM_ORDER_TYPE tp=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(isBuy && tp==ORDER_TYPE_BUY_STOP) return true;
      if(!isBuy && tp==ORDER_TYPE_SELL_STOP) return true;
   }
   return false;
}
void DeletePendings(string sym)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetString(ORDER_SYMBOL)==sym && OrderGetInteger(ORDER_MAGIC)==g_magic)
         CheckTradeCall(trade.OrderDelete(tk),"OrderDelete");
   }
}
void FlattenSymbol(string sym)
{
   DeletePendings(sym);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==g_magic)
         CheckTradeCall(trade.PositionClose(tk),"PositionClose");
   }
}
void EmergencyFlatten()
{
   if(!AccountWideEmergencyFlatten){ FlattenSymbol(SYM); return; }
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      CheckTradeCall(trade.OrderDelete(tk),"EmergencyOrderDelete");
   }
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      CheckTradeCall(trade.PositionClose(tk),"EmergencyPositionClose");
   }
}

//--------------------------- historical data -------------------------//
// Opening range for `dayStart`, hours [OrbRangeHourUTC .. +OrbHours), matched by UTC
// hour so it is correct on any broker timezone (and supports BTC multi-session).
bool OpeningRange(string sym,datetime dayStart,double &hi,double &lo)
{
   if(OrbHours<1 || OrbHours>12) return false;
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,120,r);
   if(n<OrbHours+1) return false;
   long off=ServerUtcOffset();
   hi=-DBL_MAX; lo=DBL_MAX; int count=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      if(UtcDayStart((datetime)utc)!=dayStart) continue;
      int hour=(int)((utc%86400)/3600);
      if(hour>=OrbRangeHourUTC && hour<OrbRangeHourUTC+OrbHours)
      {
         hi=MathMax(hi,r[k].high);
         lo=MathMin(lo,r[k].low);
         count++;
      }
   }
   return count>=OrbHours && hi>lo;
}

// PDHL prior-day range. Default (PdhlUseBackScan=false): the prior CALENDAR day
// only (back==1); if it has no bars (Sunday/holiday, e.g. Monday) return false and
// skip — the validated behaviour. PdhlUseBackScan=true restores the v3.11 back-scan
// (finds the last day with bars, i.e. trades Monday off Friday).
bool PrevTradingDayRange(string sym,datetime dayStart,double &ph,double &pl)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,240,r);
   if(n<3) return false;
   long off=ServerUtcOffset();
   int maxBack = PdhlUseBackScan ? 10 : 1;
   for(int back=1;back<=maxBack;back++)
   {
      datetime target=dayStart-(datetime)back*86400;
      double h=-DBL_MAX,l=DBL_MAX; int cnt=0;
      for(int k=0;k<n;k++)
      {
         long utc=(long)r[k].time-off;
         if(UtcDayStart((datetime)utc)==target)
         {
            h=MathMax(h,r[k].high);
            l=MathMin(l,r[k].low);
            cnt++;
         }
      }
      if(cnt>=3 && h>l){ ph=h; pl=l; return true; }
   }
   return false;
}
bool Atr14(string sym,double &atr)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,16,r);
   if(n<16) return false;
   double sum=0;
   for(int k=1;k<15;k++)
   {
      double tr=MathMax(r[k].high-r[k].low,
                MathMax(MathAbs(r[k].high-r[k+1].close),
                        MathAbs(r[k].low-r[k+1].close)));
      sum+=tr;
   }
   atr=sum/14.0;
   return atr>0;
}
// Trailing-20d median of the opening-range SIZE (fraction of price), prior days only
// (causal). Returns -1 if not enough history. Used by the GOLD low-vol filter/journal.
double OrbMedianRangePct(string sym,int rangeHour,int orbHours,datetime today,int lookback)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,1200,r);
   if(n<orbHours*2) return -1;
   long off=ServerUtcOffset();
   datetime days[]; double dhi[]; double dlo[]; int cnt=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      int hr=(int)((utc%86400)/3600);
      if(hr<rangeHour || hr>=rangeHour+orbHours) continue;
      datetime dd=UtcDayStart((datetime)utc);
      if(dd>=today) continue;
      int idx=-1;
      for(int j=0;j<cnt;j++) if(days[j]==dd){ idx=j; break; }
      if(idx<0){ idx=cnt; cnt++; ArrayResize(days,cnt); ArrayResize(dhi,cnt); ArrayResize(dlo,cnt);
                 days[idx]=dd; dhi[idx]=r[k].high; dlo[idx]=r[k].low; }
      else { if(r[k].high>dhi[idx]) dhi[idx]=r[k].high; if(r[k].low<dlo[idx]) dlo[idx]=r[k].low; }
   }
   if(cnt<lookback) return -1;
   double rp[]; ArrayResize(rp,cnt);
   for(int j=0;j<cnt;j++){ double mid=(dhi[j]+dlo[j])/2.0; rp[j]=(mid>0)?(dhi[j]-dlo[j])/mid:0; }
   for(int a=0;a<cnt-1;a++) for(int b=a+1;b<cnt;b++) if(days[b]>days[a]){
      datetime td=days[a]; days[a]=days[b]; days[b]=td;
      double tr=rp[a]; rp[a]=rp[b]; rp[b]=tr; }
   double sub[]; ArrayResize(sub,lookback);
   for(int j=0;j<lookback;j++) sub[j]=rp[j];
   ArraySort(sub);
   return (sub[lookback/2]+sub[(lookback-1)/2])/2.0;
}
// PDHL vol-filter helper: refRp = prior day's full-day range %, medRp = median of the
// lookback days before it. Prior days only (causal). false if not enough history.
bool PrevDayRangePctMed(string sym,datetime today,int lookback,double &refRp,double &medRp)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,1200,r);
   if(n<2) return false;
   long off=ServerUtcOffset();
   datetime days[]; double dhi[]; double dlo[]; int cnt=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      datetime dd=UtcDayStart((datetime)utc);
      if(dd>=today) continue;
      int idx=-1;
      for(int j=0;j<cnt;j++) if(days[j]==dd){ idx=j; break; }
      if(idx<0){ idx=cnt; cnt++; ArrayResize(days,cnt); ArrayResize(dhi,cnt); ArrayResize(dlo,cnt);
                 days[idx]=dd; dhi[idx]=r[k].high; dlo[idx]=r[k].low; }
      else { if(r[k].high>dhi[idx]) dhi[idx]=r[k].high; if(r[k].low<dlo[idx]) dlo[idx]=r[k].low; }
   }
   if(cnt<lookback+1) return false;
   double rp[]; ArrayResize(rp,cnt);
   for(int j=0;j<cnt;j++){ double mid=(dhi[j]+dlo[j])/2.0; rp[j]=(mid>0)?(dhi[j]-dlo[j])/mid:0; }
   for(int a=0;a<cnt-1;a++) for(int b=a+1;b<cnt;b++) if(days[b]>days[a]){
      datetime td=days[a]; days[a]=days[b]; days[b]=td;
      double tr=rp[a]; rp[a]=rp[b]; rp[b]=tr; }
   refRp=rp[0];
   double sub[]; ArrayResize(sub,lookback);
   for(int j=0;j<lookback;j++) sub[j]=rp[j+1];
   ArraySort(sub);
   medRp=(sub[lookback/2]+sub[(lookback-1)/2])/2.0;
   return true;
}

//--------------------------- risk sizing / execution -----------------//
double RiskMultiplier()
{
   if(g_initBal<=0) return 1.0;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   // profit-lock: within NearTargetPct of the phase target -> cut risk (never raise)
   double gain=(eq-g_initBal)/g_initBal*100.0;
   if(PhaseTargetPct>0 && NearTargetPct>0 && gain>=PhaseTargetPct-NearTargetPct)
      return NearTargetMult;
   double dd=(g_initBal-eq)/g_initBal*100.0;
   if(DeriskDD2Pct>0 && dd>=DeriskDD2Pct) return DeriskMult2;
   if(DeriskDD1Pct>0 && dd>=DeriskDD1Pct) return DeriskMult1;
   return 1.0;
}
int VolumeDigits(double step)
{
   int d=0; double s=step;
   while(d<8 && MathAbs(s-MathRound(s))>1e-9){ s*=10.0; d++; }
   return d;
}
bool StopLossMoney(string sym,double entry,double sl,double volume,double &lossMoney)
{
   lossMoney=0.0;
   if(volume<=0 || entry<=0 || sl<=0 || entry==sl) return false;
   ENUM_ORDER_TYPE side=(sl<entry ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   double pnl=0.0;
   ResetLastError();
   if(!OrderCalcProfit(side,sym,volume,entry,sl,pnl))
   {
      PrintFormat("%s OrderCalcProfit failed err=%d entry=%.8f sl=%.8f vol=%.4f",
                  sym,GetLastError(),entry,sl,volume);
      return false;
   }
   lossMoney=MathAbs(pnl);
   return lossMoney>0;
}
double CalcLots(string sym,double entry,double sl,bool isBuy)
{
   double riskMoney=g_initBal*RiskPct/100.0*RiskMultiplier();
   if(riskMoney<=0 || entry<=0 || sl<=0 || entry==sl) return 0;
   double lossPerLot=0.0;
   if(!StopLossMoney(sym,entry,sl,1.0,lossPerLot) || lossPerLot<=0) return 0;
   double step=SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP);
   double vmin=SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX);
   if(step<=0 || vmin<=0 || vmax<=0) return 0;
   double lots=riskMoney/lossPerLot;
   lots=MathFloor(lots/step+1e-9)*step;
   if(lots<vmin) lots=vmin;
   if(lots>vmax) lots=vmax;
   lots=NormalizeDouble(lots,VolumeDigits(step));
   double actualRisk=0.0;
   if(!StopLossMoney(sym,entry,sl,lots,actualRisk)) return 0;
   if(actualRisk>riskMoney*MaxSingleRiskMult)
   {
      Notify(StringFormat("%s volume risk %.2f > %.2fx target %.2f; SKIP",
                          sym,actualRisk,MaxSingleRiskMult,riskMoney));
      return 0;
   }
   double marginReq=0.0;
   // v3.13: we actually send BUY_STOP/SELL_STOP, so size the margin for those exact
   // order types (not the market BUY/SELL) for a correct fail-closed check.
   ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
   ResetLastError();
   if(!OrderCalcMargin(orderType,sym,lots,entry,marginReq) || marginReq<0)
   {
      Notify(StringFormat("%s margin calculation failed err=%d; TRADE SKIPPED",sym,GetLastError()));
      return 0;
   }
   double freeMargin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double required=MathMax(0.0,marginReq)*MathMax(1.0,MarginSafetyFactor);
   if(freeMargin<=0 || freeMargin<required)
   {
      Notify(StringFormat("%s insufficient free margin: need %.2f, free %.2f; SKIP",
                          sym,required,freeMargin));
      return 0;
   }
   return lots;
}
double BrokerProtectionDistance(string sym)
{
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   if(point<=0) return 0;
   long stopPts=SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL);
   long freezePts=(UseFreezeLevelGuard ? SymbolInfoInteger(sym,SYMBOL_TRADE_FREEZE_LEVEL) : 0);
   long minPts=(long)MathMax((double)stopPts,(double)freezePts)+(long)MathMax(0,ExtraStopBufferPts);
   return (double)minPts*point;
}
bool SpreadAllowed(string sym,double plannedStopDistance)
{
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   if(ask<=0 || bid<=0 || point<=0 || ask<bid) return false;
   double spread=ask-bid;
   double spreadPts=spread/point;
   if(MaxSpreadPoints>0 && spreadPts>MaxSpreadPoints)
   {
      PrintFormat("%s spread guard: %.1f pts > %.1f",sym,spreadPts,MaxSpreadPoints);
      return false;
   }
   if(MaxSpreadToStopPct>0 && plannedStopDistance>0 &&
      spread>plannedStopDistance*MaxSpreadToStopPct/100.0)
   {
      PrintFormat("%s spread guard: spread %.8f > %.2f%% of stop %.8f",
                  sym,spread,MaxSpreadToStopPct,plannedStopDistance);
      return false;
   }
   return true;
}
void EnsureStops(string sym,double buyPrice,double buySL,
                 double sellPrice,double sellSL,string tag)
{
   int digits=(int)SymbolInfoInteger(sym,SYMBOL_DIGITS);
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   double protectDist=BrokerProtectionDistance(sym);
   if(point<=0) return;
   buyPrice=NormalizeDouble(buyPrice,digits);
   buySL=NormalizeDouble(buySL,digits);
   sellPrice=NormalizeDouble(sellPrice,digits);
   sellSL=NormalizeDouble(sellSL,digits);
   double buyRiskDist=MathAbs(buyPrice-buySL);
   double sellRiskDist=MathAbs(sellPrice-sellSL);
   double refRiskDist=MathMin(buyRiskDist,sellRiskDist);
   if(!SpreadAllowed(sym,refRiskDist)){ DeletePendings(sym); return; }
   trade.SetTypeFillingBySymbol(sym);
   if(!HasPendingSide(sym,true))
   {
      double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
      if(ask>0 && buyPrice>ask+protectDist && buySL<buyPrice-protectDist)
      {
         double lot=CalcLots(sym,buyPrice,buySL,true);
         if(lot>0)
         {
            SavePlan(true,buyPrice,buySL);
            bool ok=trade.BuyStop(lot,buyPrice,sym,buySL,0,ORDER_TIME_DAY,0,tag);
            if(CheckTradeCall(ok,"BUY-STOP"))
               Notify(StringFormat("%s %s BUY-STOP %.*f %.2f lot",sym,tag,digits,buyPrice,lot));
         }
      }
   }
   if(!HasPendingSide(sym,false))
   {
      double bid=SymbolInfoDouble(sym,SYMBOL_BID);
      if(bid>0 && sellPrice<bid-protectDist && sellSL>sellPrice+protectDist)
      {
         double lot=CalcLots(sym,sellPrice,sellSL,false);
         if(lot>0)
         {
            SavePlan(false,sellPrice,sellSL);
            bool ok=trade.SellStop(lot,sellPrice,sym,sellSL,0,ORDER_TIME_DAY,0,tag);
            if(CheckTradeCall(ok,"SELL-STOP"))
               Notify(StringFormat("%s %s SELL-STOP %.*f %.2f lot",sym,tag,digits,sellPrice,lot));
         }
      }
   }
}

//--------------------------- chart drawing ---------------------------//
void DrawHLine(string tag,double price,color col,int style)
{
   string name=tag+"_"+(string)g_magic;
   if(ObjectFind(0,name)<0) ObjectCreate(0,name,OBJ_HLINE,0,0,price);
   else ObjectSetDouble(0,name,OBJPROP_PRICE,price);
   ObjectSetInteger(0,name,OBJPROP_COLOR,col);
   ObjectSetInteger(0,name,OBJPROP_STYLE,style);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
   ObjectSetString(0,name,OBJPROP_TEXT,tag);
}
void DrawSetup(double buyP,double buySL,double sellP,double sellSL)
{
   DrawHLine("AX3_BUY",buyP,clrLime,STYLE_SOLID);
   DrawHLine("AX3_BUYSL",buySL,clrGray,STYLE_DOT);
   DrawHLine("AX3_SELL",sellP,clrRed,STYLE_SOLID);
   DrawHLine("AX3_SELLSL",sellSL,clrGray,STYLE_DOT);
   ChartRedraw(0);
}
void DeleteLevels()
{
   ObjectDelete(0,"AX3_BUY_"+(string)g_magic);
   ObjectDelete(0,"AX3_BUYSL_"+(string)g_magic);
   ObjectDelete(0,"AX3_SELL_"+(string)g_magic);
   ObjectDelete(0,"AX3_SELLSL_"+(string)g_magic);
   ChartRedraw(0);
}

//--------------------------- FTMO day reconstruction -----------------//
double ReconstructFtmoOpenBalance(datetime fromGmt)
{
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   long off=ServerUtcOffset();
   datetime fromServer=(datetime)((long)fromGmt+off);
   datetime toServer=TimeTradeServer();
   if(!HistorySelect(fromServer,toServer)) return bal;
   double realized=0;
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(tk==0) continue;
      realized += HistoryDealGetDouble(tk,DEAL_PROFIT);
      realized += HistoryDealGetDouble(tk,DEAL_COMMISSION);
      realized += HistoryDealGetDouble(tk,DEAL_SWAP);
      realized += HistoryDealGetDouble(tk,DEAL_FEE);
   }
   return bal-realized;
}
void RefreshFtmoDay(datetime nowGmt)
{
   datetime d=FtmoDayStart(nowGmt);
   if(d==g_ftmoDay) return;
   g_ftmoDay=d;
   g_ftmoOpenBal=ReconstructFtmoOpenBalance(d);
   g_guardTripped=false;
   SaveFtmoState();
   Notify(StringFormat("%s FTMO day reset/rebuilt; baseline %.2f",SYM,g_ftmoOpenBal));
}
bool LossGuardOk()
{
   if(g_overallGuardTripped || g_guardTripped) return false;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyEff=MathMax(0.0,FTMO_DAILY_LOSS_PCT-LossBufferPct);
   double overallEff=MathMax(0.0,FTMO_OVERALL_LOSS_PCT-LossBufferPct);
   double dailyFloor=g_ftmoOpenBal-g_initBal*dailyEff/100.0;
   double overallFloor=g_initBal-g_initBal*overallEff/100.0;
   if(eq<=overallFloor)
   {
      g_overallGuardTripped=true; g_guardTripped=true; SaveFtmoState();
      Notify(StringFormat("%s GUARD OVERALL TRIPPED eq=%.2f floor=%.2f; trading locked",SYM,eq,overallFloor));
      return false;
   }
   if(eq<=dailyFloor)
   {
      g_guardTripped=true; SaveFtmoState();
      Notify(StringFormat("%s GUARD DAILY TRIPPED eq=%.2f floor=%.2f; locked until FTMO day reset",SYM,eq,dailyFloor));
      return false;
   }
   return true;
}

//--------------------------- news ------------------------------------//
string AutoNewsCurrency(string sym)
{
   if(StringLen(NewsCurrencyOverride)>0){ string x=NewsCurrencyOverride; StringToUpper(x); return x; }
   string z=sym; StringToUpper(z);
   if(StringFind(z,"XAU")>=0 || StringFind(z,"GOLD")>=0 ||
      StringFind(z,"XAG")>=0 || StringFind(z,"SILVER")>=0 || IsUSIndex(z))
      return "USD";
   if(IsGermanIndex(z)) return "EUR";
   string profit=SymbolInfoString(sym,SYMBOL_CURRENCY_PROFIT);
   StringToUpper(profit);
   return profit;
}
bool IsNewsBlackout(string sym)
{
   if(!AvoidNews || NewsBufferMin<=0) return false;
   string ccy=AutoNewsCurrency(sym);
   if(StringLen(ccy)==0) return false;
   datetime now=TimeTradeServer();
   datetime from=now-(datetime)NewsBufferMin*60;
   datetime to=now+(datetime)NewsBufferMin*60;
   MqlCalendarValue vals[];
   ResetLastError();
   int n=CalendarValueHistory(vals,from,to,NULL,ccy);
   if(n<0)
   {
      int err=GetLastError();
      PrintFormat("%s calendar unavailable ccy=%s err=%d",sym,ccy,err);
      return ((bool)MQLInfoInteger(MQL_TESTER) ? false : NewsFailClosed);
   }
   for(int i=0;i<n;i++)
   {
      MqlCalendarEvent ev;
      if(CalendarEventById(vals[i].event_id,ev))
         if(ev.importance==CALENDAR_IMPORTANCE_HIGH) return true;
   }
   return false;
}

//--------------------------- journal ---------------------------------//
void JournalOnFill()
{
   if(!JournalTrades || g_journaled) return;
   ulong tk=0;
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL)==SYM && PositionGetInteger(POSITION_MAGIC)==g_magic){ tk=t; break; } }
   if(tk==0) return;
   double entry=PositionGetDouble(POSITION_PRICE_OPEN);
   double sl=PositionGetDouble(POSITION_SL);
   double vol=PositionGetDouble(POSITION_VOLUME);
   bool isLong=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   double gain=(g_initBal>0)?(eq-g_initBal)/g_initBal*100.0:0;
   double dd=(g_initBal>0)?(g_initBal-eq)/g_initBal*100.0:0;
   double bid=SymbolInfoDouble(SYM,SYMBOL_BID), ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   double px=(bid>0&&ask>0)?(bid+ask)/2.0:bid;
   double spr=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
   int dg=(int)SymbolInfoInteger(SYM,SYMBOL_DIGITS);
   string fn="AurvexFTMO_journal_"+SYM+"_"+(string)g_magic+".csv";
   int h=FileOpen(fn,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(h==INVALID_HANDLE){ Notify(SYM+" journal: FileOpen failed"); return; }
   if(FileSize(h)==0)
      FileWrite(h,"utc_time","symbol","strat","side","entry","sl","lots","hi","lo",
                "ref_range_pct","trail_med_pct","spread_arm_pct","spread_fill_pct",
                "gain_pct","dd_pct","riskmult");
   FileSeek(h,0,SEEK_END);
   FileWrite(h,TimeToString(TimeGMT(),TIME_DATE|TIME_MINUTES),SYM,STRAT,
             (isLong?"long":"short"),
             DoubleToString(entry,dg),DoubleToString(sl,dg),DoubleToString(vol,2),
             DoubleToString(g_ctxHi,dg),DoubleToString(g_ctxLo,dg),
             DoubleToString(g_ctxRefPct,4),DoubleToString(g_ctxMedPct,4),
             DoubleToString(g_ctxSpreadPct,4),DoubleToString(spr,4),
             DoubleToString(gain,3),DoubleToString(dd,3),DoubleToString(RiskMultiplier(),3));
   FileClose(h);
   g_journaled=true;
   SaveTradeDayState();
   Notify(SYM+" journaled entry -> MQL5/Files/"+fn);
}

//--------------------------- trailing --------------------------------//
void LoadTrailState()
{
   double v=0;
   if(GVGet(SymPrefix()+"T_HAVE",v)) g_haveTrade=(v>0.5);
   if(GVGet(SymPrefix()+"T_LONG",v)) g_tLong=(v>0.5);
   if(GVGet(SymPrefix()+"T_ENTRY",v))g_tEntry=v;
   if(GVGet(SymPrefix()+"T_RISK",v)) g_tRisk=v;
   if(GVGet(SymPrefix()+"T_PEAK",v)) g_tPeak=v;
   g_lastPeakPersist=g_tPeak;
   g_lastPeakPersistTime=TimeTradeServer();
   if(!HasPosition(SYM)) ClearTrailState();
   else if(!g_haveTrade || g_tRisk<=0)
   {
      g_haveTrade=false; g_tRisk=0;
      Notify(SYM+" existing position has no saved initial-R; trailing disabled for it.");
   }
}
void ManageTrailing()
{
   if(TrailStopR<=0 || !g_haveTrade || g_tRisk<=0) return;
   if(FreezeTrailInNews && IsNewsBlackout(SYM)) return;
   ulong tk=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==SYM &&
         PositionGetInteger(POSITION_MAGIC)==g_magic){ tk=t; break; }
   }
   if(tk==0){ ClearTrailState(); return; }
   double sl=PositionGetDouble(POSITION_SL);
   double tp=PositionGetDouble(POSITION_TP);
   bool isLong=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   int digits=(int)SymbolInfoInteger(SYM,SYMBOL_DIGITS);
   double point=SymbolInfoDouble(SYM,SYMBOL_POINT);
   double stopLvl=BrokerProtectionDistance(SYM);
   if(isLong)
   {
      double oldPeak=g_tPeak;
      g_tPeak=MathMax(g_tPeak,bid);
      if(g_tPeak!=oldPeak) PersistTrailPeakIfNeeded();
      if((g_tPeak-g_tEntry)/g_tRisk>=TrailStopR)
      {
         double newSL=NormalizeDouble(g_tPeak-TrailStopR*g_tRisk,digits);
         if(newSL>sl+point && newSL<bid-stopLvl)
            if(CheckTradeCall(trade.PositionModify(tk,newSL,tp),"TrailModify")) SaveTrailState();
      }
   }
   else
   {
      double oldPeak=g_tPeak;
      g_tPeak=MathMin(g_tPeak,ask);
      if(g_tPeak!=oldPeak) PersistTrailPeakIfNeeded();
      if((g_tEntry-g_tPeak)/g_tRisk>=TrailStopR)
      {
         double newSL=NormalizeDouble(g_tPeak+TrailStopR*g_tRisk,digits);
         if((sl==0 || newSL<sl-point) && newSL>ask+stopLvl)
            if(CheckTradeCall(trade.PositionModify(tk,newSL,tp),"TrailModify")) SaveTrailState();
      }
   }
}

//--------------------------- lifecycle/state -------------------------//
void LoadState()
{
   datetime today=UtcDayStart(TimeGMT());
   double v=0;
   g_utcTradeDay=today;
   if(GVGet(SymPrefix()+"UTC_DAY",v) && (datetime)(long)v==today)
   {
      if(GVGet(SymPrefix()+"TRADED",v)) g_tradedToday=(v>0.5);
      if(GVGet(SymPrefix()+"FRIFLAT",v))g_fridayFlat =(v>0.5);
      if(GVGet(SymPrefix()+"JOURNALED",v))g_journaled=(v>0.5);
   }
   else
   {
      g_tradedToday=false; g_fridayFlat=false; g_journaled=false;
      SaveTradeDayState();
   }
   g_ftmoDay=FtmoDayStart(TimeGMT());
   g_ftmoOpenBal=ReconstructFtmoOpenBalance(g_ftmoDay);
   double savedFtmoDay=0, guardDay=0, guardAll=0;
   if(GVGet(FtmoPrefix()+"FTMO_DAY",savedFtmoDay) && (datetime)(long)savedFtmoDay==g_ftmoDay)
   {
      if(GVGet(FtmoPrefix()+"GUARD_DAY",guardDay)) g_guardTripped=(guardDay>0.5);
   }
   if(GVGet(FtmoPrefix()+"GUARD_ALL",guardAll)) g_overallGuardTripped=(guardAll>0.5);
   if(g_overallGuardTripped) g_guardTripped=true;
   SaveFtmoState();
   LoadTrailState();
}

int OnInit()
{
   SYM=_Symbol;
   STRAT=DetectStrategy();
   g_magic=Magic+OrbRangeHourUTC;      // per-session id; = Magic when OrbRangeHourUTC=0

   if(RequireAccountSize && AccountSize<=0)
   {
      Print("ERROR: Set AccountSize to the real starting account size (e.g. 25000). EA not started.");
      return INIT_PARAMETERS_INCORRECT;
   }
   g_initBal=(AccountSize>0 ? AccountSize : AccountInfoDouble(ACCOUNT_BALANCE));
   if(g_initBal<=0) return INIT_FAILED;

   double savedInit=0.0;
   if(GVGet(FtmoPrefix()+"INIT_BAL",savedInit) && savedInit>0 && MathAbs(savedInit-g_initBal)>0.01)
   {
      PrintFormat("ERROR: AccountSize %.2f conflicts with persisted FTMO initial balance %.2f.",
                  g_initBal,savedInit);
      return INIT_PARAMETERS_INCORRECT;
   }
   if(RiskPct<=0 || LossBufferPct<0 || LossBufferPct>=FTMO_DAILY_LOSS_PCT ||
      LossBufferPct>=FTMO_OVERALL_LOSS_PCT || MarginSafetyFactor<1.0 ||
      MaxSpreadPoints<0 || MaxSpreadToStopPct<0 || ExtraStopBufferPts<0 ||
      OrbHours<1 || OrbHours>12 || OrbRangeHourUTC<0 || OrbRangeHourUTC>23)
   {
      Print("ERROR: invalid risk/execution/strategy parameters.");
      return INIT_PARAMETERS_INCORRECT;
   }
   // v3.13: the risk modulators must only ever REDUCE risk. RiskMultiplier() returns
   // these directly, so a value > 1 would RAISE risk (e.g. a typo NearTargetMult=2.0
   // doubles risk near the target). Bound them to (0, 1].
   if(NearTargetMult<=0 || NearTargetMult>1.0 ||
      DeriskMult1<=0   || DeriskMult1>1.0   ||
      DeriskMult2<=0   || DeriskMult2>1.0)
   {
      Print("ERROR: risk multipliers (NearTargetMult, DeriskMult1/2) must be >0 and <=1.");
      return INIT_PARAMETERS_INCORRECT;
   }
   // v3.13: the ORB window must not cross UTC midnight (the hour test and the arming
   // time do not wrap). Reject rather than silently mis-arm.
   if(OrbRangeHourUTC+OrbHours>24)
   {
      Print("ERROR: OrbRangeHourUTC + OrbHours must be <= 24 (no midnight wrap).");
      return INIT_PARAMETERS_INCORRECT;
   }
   trade.SetExpertMagicNumber(g_magic);
   trade.SetTypeFillingBySymbol(SYM);
   SymbolSelect(SYM,true);
   LoadState();
   int sec=MathMax(1,TimerSeconds);
   EventSetTimer(sec);
   Notify(StringFormat("Aurvex v3.13-merged on %s strat=%s magic=%d orbHourUTC=%d minRangeMult=%.2f pdhlMinRangeMult=%.2f pdhlBackScan=%s base=%.2f serverOffsetH=%d journal=%s",
          SYM,STRAT,(int)g_magic,OrbRangeHourUTC,MinRangeMedMult,PdhlMinRangeMedMult,
          (PdhlUseBackScan?"on":"off"),g_initBal,(int)(ServerUtcOffset()/3600),
          (JournalTrades?"on":"off")));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
   SaveTradeDayState();
   SaveFtmoState();
   SaveTrailState();
   EventKillTimer();
   if(DrawLevels) DeleteLevels();
}

//--------------------------- immediate trade event -------------------//
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   string ds=HistoryDealGetString(trans.deal,DEAL_SYMBOL);
   long magic=HistoryDealGetInteger(trans.deal,DEAL_MAGIC);
   if(ds!=SYM || magic!=g_magic) return;
   ENUM_DEAL_ENTRY entryType=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   if(entryType!=DEAL_ENTRY_IN && entryType!=DEAL_ENTRY_INOUT) return;
   ENUM_DEAL_TYPE dealType=(ENUM_DEAL_TYPE)HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   bool isBuy=(dealType==DEAL_TYPE_BUY);
   if(dealType!=DEAL_TYPE_BUY && dealType!=DEAL_TYPE_SELL) return;

   g_tradedToday=true;
   g_utcTradeDay=UtcDayStart(TimeGMT());
   SaveTradeDayState();
   DeletePendings(SYM);

   if(!g_haveTrade)
   {
      double plannedEntry=0,plannedSL=0;
      double fill=HistoryDealGetDouble(trans.deal,DEAL_PRICE);
      if(LoadPlan(isBuy,plannedEntry,plannedSL) && plannedSL>0)
      {
         g_haveTrade=true; g_tLong=isBuy; g_tEntry=fill;
         g_tRisk=MathAbs(fill-plannedSL); g_tPeak=fill;
         SaveTrailState();
      }
      else Notify(SYM+" fill detected but original SL plan missing; trailing disabled.");
   }
   JournalOnFill();
   Notify(StringFormat("%s fill detected; opposite pending cancelled; tradedToday=1",SYM));
}

void OnTick()
{
   if(FtmoDayStart(TimeGMT())!=g_ftmoDay) RefreshFtmoDay(TimeGMT());
   if(!LossGuardOk()){ EmergencyFlatten(); g_tradedToday=true; SaveTradeDayState(); return; }
   if(HasPosition(SYM))
   {
      g_tradedToday=true; SaveTradeDayState();
      DeletePendings(SYM); ManageTrailing();
   }
}

void OnTimer()
{
   datetime nowGmt=TimeGMT();
   RefreshFtmoDay(nowGmt);
   datetime today=UtcDayStart(nowGmt);
   if(today!=g_utcTradeDay)
   {
      FlattenSymbol(SYM);
      g_utcTradeDay=today;
      g_tradedToday=false; g_fridayFlat=false; g_journaled=false;
      ClearTrailState();
      SaveTradeDayState();
      if(DrawLevels) DeleteLevels();
      Notify(SYM+" new UTC strategy day; flat and ready.");
   }
   MqlDateTime st; TimeToStruct(nowGmt,st);
   int dow=st.day_of_week;
   if(dow==0 || dow==6) return;
   int minuteUtc=(int)(((long)nowGmt%86400)/60);
   if(dow==5 && minuteUtc>=FridayFlattenUTCMin)
   {
      if(!g_fridayFlat){ FlattenSymbol(SYM); g_fridayFlat=true; SaveTradeDayState(); Notify(SYM+" Friday flatten complete."); }
      return;
   }
   if(!LossGuardOk()){ EmergencyFlatten(); g_tradedToday=true; SaveTradeDayState(); return; }
   if(HasPosition(SYM))
   {
      g_tradedToday=true; SaveTradeDayState();
      DeletePendings(SYM); JournalOnFill(); ManageTrailing(); return;  // v3.13: retry journal if the fill-event write missed
   }
   if(g_tradedToday){ DeletePendings(SYM); return; }
   if(IsNewsBlackout(SYM)){ DeletePendings(SYM); return; }

   double bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   double px=(bid>0 && ask>0)?(bid+ask)/2.0:bid;
   if(px<=0) return;

   if(STRAT=="ORB")
   {
      if(nowGmt<today+(datetime)(OrbRangeHourUTC+OrbHours)*3600) return;
      double hi,lo;
      if(!OpeningRange(SYM,today,hi,lo)) return;
      if(DrawLevels) DrawSetup(hi,lo,lo,hi);
      if(px<lo || px>hi)
      {
         g_tradedToday=true; SaveTradeDayState(); DeletePendings(SYM);
         Notify(SYM+" ORB already broken before arming; skip day."); return;
      }
      if(MinRangeMedMult>0)
      {
         double mid=(hi+lo)/2.0; double todayRp=(mid>0)?(hi-lo)/mid:0;
         double med=OrbMedianRangePct(SYM,OrbRangeHourUTC,OrbHours,today,20);
         if(med>0 && todayRp<MinRangeMedMult*med)
         {
            g_tradedToday=true; SaveTradeDayState();
            Notify(SYM+" ORB opening range "+DoubleToString(todayRp*100,3)+"% < "+
                   DoubleToString(MinRangeMedMult,2)+"x median "+DoubleToString(med*100,3)+"% — skip (low-vol day)");
            return;
         }
      }
      if(JournalTrades)
      {
         g_ctxHi=hi; g_ctxLo=lo;
         double m0=(hi+lo)/2.0; g_ctxRefPct=(m0>0)?(hi-lo)/m0*100.0:0;
         double med0=OrbMedianRangePct(SYM,OrbRangeHourUTC,OrbHours,today,20);
         g_ctxMedPct=(med0>0)?med0*100.0:-1;
         g_ctxSpreadPct=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
      }
      EnsureStops(SYM,hi,lo,lo,hi,"AurvexORB312");
   }
   else
   {
      if(!PdhlSessionAllowed(nowGmt)){ DeletePendings(SYM); return; }
      double ph,pl,atr;
      if(!PrevTradingDayRange(SYM,today,ph,pl)) return;
      if(!Atr14(SYM,atr)) return;
      double d=PdhlStopATR*atr;
      if(DrawLevels) DrawSetup(ph,ph-d,pl,pl+d);
      if(px<pl || px>ph)
      {
         g_tradedToday=true; SaveTradeDayState(); DeletePendings(SYM);
         Notify(SYM+" PDHL already broken before arming; skip day."); return;
      }
      if(PdhlMinRangeMedMult>0)
      {
         double refRp,medRp;
         if(PrevDayRangePctMed(SYM,today,20,refRp,medRp) && medRp>0 && refRp<PdhlMinRangeMedMult*medRp)
         {
            g_tradedToday=true; SaveTradeDayState();
            Notify(SYM+" PDHL prior-day range "+DoubleToString(refRp*100,3)+"% < "+
                   DoubleToString(PdhlMinRangeMedMult,2)+"x median "+DoubleToString(medRp*100,3)+"% — skip (low-vol day)");
            return;
         }
      }
      if(JournalTrades)
      {
         g_ctxHi=ph; g_ctxLo=pl;
         double mp=(ph+pl)/2.0; g_ctxRefPct=(mp>0)?(ph-pl)/mp*100.0:0;
         double refRp2,medRp2;
         g_ctxMedPct=PrevDayRangePctMed(SYM,today,20,refRp2,medRp2)?medRp2*100.0:-1;
         g_ctxSpreadPct=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
      }
      EnsureStops(SYM,ph,ph-d,pl,pl+d,"AurvexPDHL312");
   }
}
//+------------------------------------------------------------------+
