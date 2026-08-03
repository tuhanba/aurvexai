//+------------------------------------------------------------------+
//|  AurvexFTMO.mq5  —  ORB (gold) + PDHL (indices) auto-executor     |
//|  Places the exact stop-entry setups the Aurvex research validated:|
//|   * XAUUSD   Opening Range Breakout (first UTC hour)              |
//|   * GER40 / US100  Previous-Day High/Low breakout (ATR stop)      |
//|  First break wins; flat by 00:00 UTC; risk-based sizing from the  |
//|  broker's tick value (handles EUR-quoted GER40 automatically).    |
//|                                                                    |
//|  v1.1 hardening (2026-08-03):                                      |
//|   - loss guard now CLOSES positions (not just pendings) + buffer  |
//|   - both stop sides placed independently, missing side retried    |
//|   - per-symbol order filling mode (fixes index rejections)        |
//|   - FTMO-day (CET) baseline for the daily-loss guard, separate    |
//|     from the UTC trading session used by the strategy             |
//|   - Friday pre-close flatten (weekend-flat compliance) + weekend  |
//|     entry block                                                    |
//|   - min-lot over-risk guard (skips a trade that can't be sized)   |
//|  v1.2 (2026-08-03):                                                |
//|   - high-impact news buffer (FTMO news rule) via MT5 calendar     |
//|   - no-chase: skip a setup whose range already broke before arming|
//|                                                                    |
//|  ⚠ DEMO FIRST. Test on the FTMO Free Trial and watch it before    |
//|  any funded use. Start with gold only (indices default false).    |
//|  The news buffer needs the terminal's Economic Calendar (built in |
//|  to MT5); if the calendar is empty it fails safe (does not block). |
//+------------------------------------------------------------------+
#property copyright "Aurvex"
#property version   "1.20"
#property strict
#include <Trade/Trade.mqh>

//--- inputs -------------------------------------------------------------
input double RiskPct          = 0.5;      // risk per trade (% of balance)
input int    OrbHours         = 1;        // opening-range length (hours)
input double PdhlStopATR      = 1.5;      // PDHL stop = ATR(14) * this
input int    MaxDailyLossPct  = 5;        // FTMO 2-step daily limit (guard)
input int    MaxOverallLossPct= 10;       // FTMO 2-step overall limit (guard)
input double DailyStopBufferPct = 1.0;    // stop this % BEFORE the FTMO floor (safety)
input int    FtmoResetHourUTC = 22;       // FTMO day reset in UTC (22=CEST summer, 23=CET winter)
input int    FridayFlattenHourUTC = 20;   // close everything before Friday's market close (UTC)
input double MaxSingleRiskMult = 2.0;     // skip a trade if forced min-lot risk exceeds this x target
input bool   AvoidNews        = true;     // block entries around high-impact news (FTMO news rule)
input int    NewsBufferMin    = 2;        // minutes each side of a high-impact event to stand down
input double AccountSize      = 0;        // 0 = use balance at first start
input long   Magic            = 770077;   // our order id
//--- instruments (start GOLD ONLY; enable indices after gold is proven)
input bool   Trade_XAUUSD     = true;
input string Sym_XAUUSD       = "XAUUSD";
input bool   Trade_GER40      = false;
input string Sym_GER40        = "GER40.cash";
input bool   Trade_US100      = false;
input string Sym_US100        = "US100.cash";
//--- optional Telegram (whitelist api.telegram.org in Tools>Options>EA)
input string TelegramToken    = "";
input string TelegramChatID   = "";

CTrade  trade;
//--- per-symbol runtime state
string  g_sym[3];
string  g_strat[3];       // "ORB" | "PDHL"
bool    g_enabled[3];
bool    g_tradedToday[3];  // a position already opened today for this symbol (latch)
int     g_n = 0;

datetime g_lastDay      = 0;   // UTC trading day (strategy session)
datetime g_ftmoDay      = 0;   // FTMO day (CET-aligned) for the loss guard
double   g_ftmoDayOpenBal = 0; // balance at the start of the current FTMO day
double   g_initBal      = 0;
bool     g_fridayFlat   = false;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   g_n = 0;
   if(Trade_XAUUSD){ g_sym[g_n]=Sym_XAUUSD; g_strat[g_n]="ORB";  g_enabled[g_n]=true; g_n++; }
   if(Trade_GER40 ){ g_sym[g_n]=Sym_GER40;  g_strat[g_n]="PDHL"; g_enabled[g_n]=true; g_n++; }
   if(Trade_US100 ){ g_sym[g_n]=Sym_US100;  g_strat[g_n]="PDHL"; g_enabled[g_n]=true; g_n++; }
   for(int i=0;i<g_n;i++){ g_tradedToday[i]=false; SymbolSelect(g_sym[i], true); }
   g_initBal = (AccountSize>0 ? AccountSize : AccountInfoDouble(ACCOUNT_BALANCE));
   g_ftmoDayOpenBal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_lastDay = UtcDayStart(TimeGMT());
   g_ftmoDay = FtmoDayStart(TimeGMT());
   EventSetTimer(20);
   PrintFormat("AurvexFTMO v1.2 started. instruments=%d initBal=%.2f", g_n, g_initBal);
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason){ EventKillTimer(); }

//+------------------------------------------------------------------+
//| day boundaries                                                   |
//+------------------------------------------------------------------+
datetime UtcDayStart(datetime t){ return (datetime)((long)t/86400*86400); }

// FTMO's daily-loss window resets at 00:00 CE(S)T. FtmoResetHourUTC expresses
// that in UTC (22 in summer, 23 in winter). Returns the timestamp of the most
// recent reset, so a change in this value marks a new FTMO day.
datetime FtmoDayStart(datetime t)
{
   long shifted = (long)t - (long)FtmoResetHourUTC*3600;
   long dayFloor = (shifted/86400)*86400;
   return (datetime)(dayFloor + (long)FtmoResetHourUTC*3600);
}

//+------------------------------------------------------------------+
void OnTimer()
{
   datetime nowGmt = TimeGMT();
   datetime today  = UtcDayStart(nowGmt);

   //--- FTMO day (CET) rollover: reset the daily-loss baseline to current balance
   datetime ftmoDay = FtmoDayStart(nowGmt);
   if(ftmoDay != g_ftmoDay)
   {
      g_ftmoDayOpenBal = AccountInfoDouble(ACCOUNT_BALANCE);
      g_ftmoDay = ftmoDay;
      Notify("FTMO day reset — daily baseline " + DoubleToString(g_ftmoDayOpenBal,2));
   }

   //--- new UTC trading day: flatten yesterday, reset per-symbol latches
   if(today != g_lastDay)
   {
      SessionFlattenAll();
      for(int i=0;i<g_n;i++) g_tradedToday[i]=false;
      g_fridayFlat = false;
      g_lastDay = today;
      Notify("New UTC day — flat, ready");
   }

   //--- weekend: no new entries (markets closed / gap risk)
   MqlDateTime st; TimeToStruct(nowGmt, st);
   int dow = st.day_of_week;                 // 0=Sun .. 6=Sat
   if(dow==0 || dow==6) return;

   //--- Friday: close everything before the market close (weekend-flat rule)
   if(dow==5 && nowGmt >= today + (datetime)FridayFlattenHourUTC*3600)
   {
      if(!g_fridayFlat)
      {
         SessionFlattenAll();
         g_fridayFlat = true;
         Notify("Friday pre-close flatten — flat for the weekend");
      }
      return;                                // no new entries after the Friday cutoff
   }

   //--- FTMO loss guard: on a floor breach, CLOSE positions + cancel pendings, stop for the day
   if(!LossGuardOk())
   {
      SessionFlattenAll();
      for(int i=0;i<g_n;i++) g_tradedToday[i]=true;   // lock out re-entry until next day
      return;
   }

   //--- per instrument
   for(int i=0;i<g_n;i++)
   {
      if(!g_enabled[i]) continue;

      // one side filled -> cancel the opposite pending, latch "traded today"
      ManageFirstBreak(g_sym[i]);
      if(HasPosition(g_sym[i])) { g_tradedToday[i]=true; continue; }
      if(g_tradedToday[i]) { DeletePendings(g_sym[i]); continue; }  // already traded -> no re-entry

      // FTMO news rule: within the buffer of a high-impact event for this symbol's
      // currency, cancel pendings (avoid a news-time fill) and don't arm new ones.
      if(IsNewsBlackout(g_sym[i])) { DeletePendings(g_sym[i]); continue; }

      double bid = SymbolInfoDouble(g_sym[i], SYMBOL_BID);
      double ask = SymbolInfoDouble(g_sym[i], SYMBOL_ASK);
      double px  = (bid>0 && ask>0) ? (bid+ask)/2.0 : bid;

      if(g_strat[i]=="ORB")
      {
         if(nowGmt < today + (datetime)OrbHours*3600) continue;     // first UTC hour not closed
         double hi,lo;
         if(!FirstHourRange(g_sym[i], today, hi, lo)) continue;
         if(px>0 && (px<lo || px>hi)) {                             // range already broke -> don't chase
            g_tradedToday[i]=true;
            Notify(g_sym[i]+" ORB: range already broken before arming — skip today");
            continue;
         }
         EnsureStops(g_sym[i], hi, lo, lo, hi, "AurvexORB");        // buy=hi, sell=lo
      }
      else // PDHL
      {
         double ph,pl,atr;
         if(!PrevDayRange(g_sym[i], today, ph, pl)) continue;
         if(!Atr14(g_sym[i], atr) || atr<=0) continue;
         if(px>0 && (px<pl || px>ph)) {                             // already outside prior-day range
            g_tradedToday[i]=true;
            Notify(g_sym[i]+" PDHL: prior-day range already broken before arming — skip today");
            continue;
         }
         double d = PdhlStopATR*atr;
         EnsureStops(g_sym[i], ph, ph-d, pl, pl+d, "AurvexPDHL");
      }
   }
}

//+------------------------------------------------------------------+
//| data helpers                                                     |
//+------------------------------------------------------------------+
bool FirstHourRange(string sym, datetime dayStart, double &hi, double &lo)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n = CopyRates(sym, PERIOD_H1, dayStart, OrbHours, r);
   if(n < OrbHours) return false;
   hi=-DBL_MAX; lo=DBL_MAX;
   for(int k=0;k<n;k++){ hi=MathMax(hi,r[k].high); lo=MathMin(lo,r[k].low); }
   return (hi>lo);
}
bool PrevDayRange(string sym, datetime dayStart, double &ph, double &pl)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n = CopyRates(sym, PERIOD_H1, dayStart-86400, dayStart-1, r);
   if(n < 3) return false;
   ph=-DBL_MAX; pl=DBL_MAX;
   for(int k=0;k<n;k++){ ph=MathMax(ph,r[k].high); pl=MathMin(pl,r[k].low); }
   return (ph>pl);
}
bool Atr14(string sym, double &atr)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n = CopyRates(sym, PERIOD_H1, 0, 16, r);
   if(n < 16) return false;
   double s=0; for(int k=1;k<15;k++){            // use closed bars (skip the forming r[0])
      double tr = MathMax(r[k].high-r[k].low,
                  MathMax(MathAbs(r[k].high-r[k+1].close),
                          MathAbs(r[k].low -r[k+1].close)));
      s += tr; }
   atr = s/14.0; return true;
}

//+------------------------------------------------------------------+
//| sizing + placement                                               |
//+------------------------------------------------------------------+
double CalcLots(string sym, double entry, double sl)
{
   double riskUSD = (AccountSize>0?AccountSize:AccountInfoDouble(ACCOUNT_BALANCE))*RiskPct/100.0;
   double tickVal = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSz  = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double dist    = MathAbs(entry-sl);
   if(tickSz<=0 || dist<=0 || tickVal<=0) return 0;
   double valPerPrice = tickVal / tickSz;            // account-ccy per 1.0 price per lot
   double lots = riskUSD / (dist * valPerPrice);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step>0) lots = MathFloor(lots/step)*step;
   lots = MathMax(vmin, MathMin(vmax, lots));
   // over-risk guard: if the min tradable lot forces risk well above target, skip
   double actualRisk = lots * dist * valPerPrice;
   if(actualRisk > riskUSD * MaxSingleRiskMult){
      Notify(StringFormat("%s: min-lot risk %.2f > %.2f x target — skipped",
                          sym, actualRisk, MaxSingleRiskMult));
      return 0;
   }
   return lots;
}
// Place whichever stop side is still missing and currently valid. Called every
// tick until both sides are live (or a position opens), so a side rejected at
// setup (price already past the level) is retried when the price allows it.
void EnsureStops(string sym, double buyPrice, double buySL,
                 double sellPrice, double sellSL, string tag)
{
   int    d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   double stopLvl = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * point;
   buyPrice =NormalizeDouble(buyPrice, d);  buySL =NormalizeDouble(buySL, d);
   sellPrice=NormalizeDouble(sellPrice,d);  sellSL=NormalizeDouble(sellSL,d);
   trade.SetTypeFillingBySymbol(sym);                 // correct filling per symbol

   if(!HasPendingSide(sym, true))                     // no buy-stop yet
   {
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(ask>0 && buyPrice > ask + stopLvl)           // valid buy-stop (above market)
      {
         double lot = CalcLots(sym, buyPrice, buySL);
         if(lot>0){
            bool ok = trade.BuyStop(lot, buyPrice, sym, buySL, 0, ORDER_TIME_DAY, 0, tag);
            Notify(StringFormat("%s %s BUY-STOP %.*f (%.2f lot) ok=%d", sym, tag, d, buyPrice, lot, ok));
         }
      }
   }
   if(!HasPendingSide(sym, false))                    // no sell-stop yet
   {
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      if(bid>0 && sellPrice < bid - stopLvl)          // valid sell-stop (below market)
      {
         double lot = CalcLots(sym, sellPrice, sellSL);
         if(lot>0){
            bool ok = trade.SellStop(lot, sellPrice, sym, sellSL, 0, ORDER_TIME_DAY, 0, tag);
            Notify(StringFormat("%s %s SELL-STOP %.*f (%.2f lot) ok=%d", sym, tag, d, sellPrice, lot, ok));
         }
      }
   }
}

//+------------------------------------------------------------------+
//| order/position management                                        |
//+------------------------------------------------------------------+
bool HasPosition(string sym)
{
   for(int i=PositionsTotal()-1;i>=0;i--){
      ulong t=PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==Magic) return true; }
   return false;
}
bool HasPending(string sym)
{
   for(int i=OrdersTotal()-1;i>=0;i--){
      ulong t=OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL)==sym &&
         OrderGetInteger(ORDER_MAGIC)==Magic) return true; }
   return false;
}
// true if a pending order of the given side (buy-stop / sell-stop) already exists.
bool HasPendingSide(string sym, bool isBuy)
{
   for(int i=OrdersTotal()-1;i>=0;i--){
      if(OrderGetTicket(i)==0) continue;               // selects the order
      if(OrderGetString(ORDER_SYMBOL)==sym && OrderGetInteger(ORDER_MAGIC)==Magic){
         long type = OrderGetInteger(ORDER_TYPE);
         if(isBuy  && type==ORDER_TYPE_BUY_STOP)  return true;
         if(!isBuy && type==ORDER_TYPE_SELL_STOP) return true;
      }
   }
   return false;
}
void DeletePendings(string sym)
{
   for(int i=OrdersTotal()-1;i>=0;i--){
      ulong t=OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL)==sym && OrderGetInteger(ORDER_MAGIC)==Magic)
         trade.OrderDelete(t); }
}
void ManageFirstBreak(string sym)
{
   if(HasPosition(sym)) DeletePendings(sym);   // one side filled -> cancel the other
}
void SessionFlattenAll()
{
   for(int i=OrdersTotal()-1;i>=0;i--){
      ulong t=OrderGetTicket(i);
      if(OrderGetInteger(ORDER_MAGIC)==Magic) trade.OrderDelete(t); }
   for(int i=PositionsTotal()-1;i>=0;i--){
      ulong t=PositionGetTicket(i);
      if(PositionGetInteger(POSITION_MAGIC)==Magic)
         trade.PositionClose(PositionGetString(POSITION_SYMBOL)); }
}

//+------------------------------------------------------------------+
//| FTMO loss guard (equity vs daily/overall floors, with buffer)    |
//+------------------------------------------------------------------+
bool LossGuardOk()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   // Stop DailyStopBufferPct% before the true FTMO floors so we never touch them.
   double dailyEff   = MathMax(0.0, MaxDailyLossPct   - DailyStopBufferPct);
   double overallEff = MathMax(0.0, MaxOverallLossPct - DailyStopBufferPct);
   double dailyFloor   = g_ftmoDayOpenBal - g_initBal*dailyEff/100.0;
   double overallFloor = g_initBal        - g_initBal*overallEff/100.0;
   if(eq <= dailyFloor)  { Notify("GUARD: daily floor — flatten + stop for the day");  return false; }
   if(eq <= overallFloor){ Notify("GUARD: overall floor — flatten + stop");            return false; }
   return true;
}

//+------------------------------------------------------------------+
//| High-impact news buffer (FTMO news rule)                         |
//+------------------------------------------------------------------+
// True if a HIGH-importance event for this symbol's quote currency falls within
// NewsBufferMin minutes either side of now. Uses the terminal's built-in
// Economic Calendar; if the calendar has no data it returns false (fail-safe:
// trading is not blocked when we can't see the calendar).
bool IsNewsBlackout(string sym)
{
   if(!AvoidNews || NewsBufferMin<=0) return false;
   string ccy = SymbolInfoString(sym, SYMBOL_CURRENCY_PROFIT);   // XAUUSD/US100->USD, GER40->EUR
   if(StringLen(ccy)==0) return false;
   datetime now  = TimeGMT();
   datetime from = now - (datetime)(NewsBufferMin*60);
   datetime to   = now + (datetime)(NewsBufferMin*60);
   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals, from, to, NULL, ccy);
   for(int i=0;i<n;i++){
      MqlCalendarEvent ev;
      if(CalendarEventById(vals[i].event_id, ev)){
         if(ev.importance==CALENDAR_IMPORTANCE_HIGH) return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| Telegram (optional; whitelist api.telegram.org in EA options)    |
//+------------------------------------------------------------------+
void Notify(string msg)
{
   Print(msg);
   if(StringLen(TelegramToken)==0 || StringLen(TelegramChatID)==0) return;
   string url = "https://api.telegram.org/bot"+TelegramToken+"/sendMessage";
   string post= "chat_id="+TelegramChatID+"&text="+msg;
   char data[]; StringToCharArray(post, data, 0, StringLen(post));
   char res[]; string rhdr;
   int code = WebRequest("POST", url, "Content-Type: application/x-www-form-urlencoded\r\n",
                         5000, data, res, rhdr);
   if(code==-1) Print("Telegram WebRequest failed (whitelist api.telegram.org).");
}
//+------------------------------------------------------------------+
