//+------------------------------------------------------------------+
//|  AurvexFTMO.mq5  —  ORB (gold) + PDHL (indices) auto-executor     |
//|                                                                    |
//|  v2.0 (2026-08-03): PER-CHART design.                             |
//|  Attach ONE instance to EACH chart you want to trade:             |
//|    * XAUUSD  -> Opening Range Breakout (first UTC hour)  [ORB]    |
//|    * GER40 / US100 (indices) -> Previous-Day High/Low   [PDHL]    |
//|  Each instance trades ONLY its own chart symbol and DRAWS its     |
//|  entry/stop levels on that chart, so nothing overlaps and you can |
//|  see the plan. Strategy is auto-detected from the symbol (metals  |
//|  = ORB, else PDHL); override with ForceStrategy if needed.        |
//|                                                                    |
//|  Carries the v1.1/v1.2 FTMO hardening: loss guard that CLOSES     |
//|  positions with a safety buffer, CET-aligned daily baseline,      |
//|  Friday weekend-flat + weekend block, two-sided stop retry,       |
//|  per-symbol filling, min-lot over-risk skip, high-impact news     |
//|  buffer, and a no-chase guard (skip an already-broken range).     |
//|                                                                    |
//|  v2.1: optional trailing stop (TrailStopR) — once a trade is      |
//|  +TrailStopR in profit, the SL trails that far behind the peak,    |
//|  locking profit while letting winners run. Per-instrument: gold/   |
//|  silver (ORB) run TrailStopR=0 (let the fat tail run); indices     |
//|  (PDHL) use 0.5.                                                    |
//|                                                                    |
//|  v2.2: gold/metals ORB timezone fix — ServerUtcOffset() maps the   |
//|  broker's server-time bars to UTC so the opening range is the true |
//|  00:00-01:00 UTC hour on any broker timezone.                      |
//|                                                                    |
//|  v2.3: index cash-session gate (PdhlSessionStartUTC/EndUTC). PDHL  |
//|  only arms while the index's exchange is open — the honest         |
//|  backtest (Yahoo, cash-session bars only) never validated the      |
//|  overnight-futures regime the live CFD was trading and losing in.  |
//|                                                                    |
//|  ⚠ Set AccountSize to your REAL account size (e.g. 10000 for a     |
//|  $10k account) so the overall-loss floor is stable across restarts.|
//+------------------------------------------------------------------+
#property copyright "Aurvex"
#property version   "2.30"
#property strict
#include <Trade/Trade.mqh>

//--- inputs -------------------------------------------------------------
input double RiskPct          = 0.5;      // risk per trade (% of balance)
input string ForceStrategy    = "AUTO";   // AUTO | ORB | PDHL  (AUTO: metals=ORB, else PDHL)
input int    OrbHours         = 1;        // opening-range length (hours), ORB only
input double PdhlStopATR      = 1.5;      // PDHL stop = ATR(14) * this
input double TrailStopR       = 0.5;      // trail stop this many R behind the peak once +TrailStopR in profit (0=off)
input int    MaxDailyLossPct  = 5;        // FTMO 2-step daily limit (guard)
input int    MaxOverallLossPct= 10;       // FTMO 2-step overall limit (guard)
input double DailyStopBufferPct = 1.0;    // stop this % BEFORE the FTMO floor (safety)
input int    FtmoResetHourUTC = 22;       // FTMO day reset in UTC (22=CEST summer, 23=CET winter)
input int    FridayFlattenHourUTC = 20;   // close everything before Friday's market close (UTC)
input int    PdhlSessionStartUTC = 0;     // PDHL only: enter at/after this UTC hour (index cash-session gate)
input int    PdhlSessionEndUTC   = 24;    // PDHL only: stop entering at/after this UTC hour (0/24 = no gate)
input double MaxSingleRiskMult = 2.0;     // skip a trade if forced min-lot risk exceeds this x target
input bool   AvoidNews        = true;     // block entries around high-impact news (FTMO news rule)
input int    NewsBufferMin    = 2;        // minutes each side of a high-impact event to stand down
input bool   DrawLevels       = true;     // draw entry/stop lines on the chart
input double AccountSize      = 0;        // 0 = balance at first start; set to REAL account size (e.g. 10000)
input long   Magic            = 770077;   // our order id
input string TelegramToken    = "";       // optional Telegram bot token
input string TelegramChatID   = "";       // optional Telegram chat id

CTrade   trade;
string   SYM;                 // this chart's symbol
string   STRAT;               // "ORB" | "PDHL" for this chart
bool     g_tradedToday = false;

datetime g_lastDay        = 0;   // UTC trading day (strategy session)
datetime g_ftmoDay        = 0;   // FTMO day (CET-aligned) for the loss guard
double   g_ftmoDayOpenBal = 0;   // balance at the start of the current FTMO day
double   g_initBal        = 0;
bool     g_fridayFlat     = false;
// trailing-stop state for the open position on this chart
bool     g_haveTrade      = false;
double   g_tEntry = 0, g_tRisk = 0, g_tPeak = 0;
bool     g_tLong          = false;

//+------------------------------------------------------------------+
int OnInit()
{
   SYM   = _Symbol;
   STRAT = DetectStrategy();
   trade.SetExpertMagicNumber(Magic);
   trade.SetTypeFillingBySymbol(SYM);
   SymbolSelect(SYM, true);
   g_initBal        = (AccountSize>0 ? AccountSize : AccountInfoDouble(ACCOUNT_BALANCE));
   g_ftmoDayOpenBal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_lastDay        = UtcDayStart(TimeGMT());
   g_ftmoDay        = FtmoDayStart(TimeGMT());
   EventSetTimer(20);
   PrintFormat("AurvexFTMO v2.3 on %s  strat=%s  offsetH=%d  initBal=%.2f",
               SYM, STRAT, (int)(ServerUtcOffset()/3600), g_initBal);
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason){ EventKillTimer(); if(DrawLevels) DeleteLevels(); }

string DetectStrategy()
{
   string s = ForceStrategy; StringToUpper(s);
   if(s=="ORB" || s=="PDHL") return s;
   if(StringFind(SYM,"XAU")>=0 || StringFind(SYM,"GOLD")>=0 || StringFind(SYM,"XAG")>=0) return "ORB";
   return "PDHL";
}

//+------------------------------------------------------------------+
//| day boundaries                                                   |
//+------------------------------------------------------------------+
datetime UtcDayStart(datetime t){ return (datetime)((long)t/86400*86400); }

// FTMO's daily-loss window resets at 00:00 CE(S)T. FtmoResetHourUTC expresses
// that in UTC (22 in summer, 23 in winter). A change in the returned value marks
// a new FTMO day.
datetime FtmoDayStart(datetime t)
{
   long shifted  = (long)t - (long)FtmoResetHourUTC*3600;
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
      Notify(SYM+" FTMO day reset — daily baseline " + DoubleToString(g_ftmoDayOpenBal,2));
   }

   //--- new UTC trading day: flatten this symbol, reset latches, clear the drawing
   if(today != g_lastDay)
   {
      FlattenSymbol(SYM);
      g_tradedToday = false;
      g_fridayFlat  = false;
      g_lastDay = today;
      if(DrawLevels) DeleteLevels();
      Notify(SYM+" new UTC day — flat, ready");
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
         FlattenSymbol(SYM);
         g_fridayFlat = true;
         Notify(SYM+" Friday pre-close flatten — flat for the weekend");
      }
      return;
   }

   //--- FTMO loss guard: on a floor breach, CLOSE this symbol + cancel pendings
   if(!LossGuardOk())
   {
      FlattenSymbol(SYM);
      g_tradedToday = true;      // lock out re-entry until the next day
      return;
   }

   //--- one side filled -> cancel the opposite pending, latch "traded today"
   ManageFirstBreak(SYM);
   if(HasPosition(SYM)) { g_tradedToday=true; ManageTrailing(); return; }
   g_haveTrade = false;                 // no open position -> clear trail state
   if(g_tradedToday)    { DeletePendings(SYM); return; }

   //--- FTMO news rule: stand down within the buffer of a high-impact event
   if(IsNewsBlackout(SYM)) { DeletePendings(SYM); return; }

   double bid = SymbolInfoDouble(SYM, SYMBOL_BID);
   double ask = SymbolInfoDouble(SYM, SYMBOL_ASK);
   double px  = (bid>0 && ask>0) ? (bid+ask)/2.0 : bid;

   if(STRAT=="ORB")
   {
      if(nowGmt < today + (datetime)OrbHours*3600) return;     // first UTC hour not closed
      double hi,lo;
      if(!FirstHourRange(SYM, today, hi, lo)) return;
      if(DrawLevels) DrawSetup(hi, lo, lo, hi);                // buy=hi, sell=lo (draw always)
      if(px>0 && (px<lo || px>hi)) {                           // range already broke -> don't chase
         g_tradedToday=true;
         Notify(SYM+" ORB: range already broken before arming — skip today");
         return;
      }
      EnsureStops(SYM, hi, lo, lo, hi, "AurvexORB");
   }
   else // PDHL
   {
      // Cash-session gate: indices only trade well while their exchange is open.
      // Outside the window (e.g. overnight futures), rest no orders — the honest
      // backtest only ever entered in-session, so overnight fills are untested.
      int hourUtc = (int)(((long)nowGmt % 86400) / 3600);
      if(PdhlSessionStartUTC < PdhlSessionEndUTC &&
         (hourUtc < PdhlSessionStartUTC || hourUtc >= PdhlSessionEndUTC))
      {
         DeletePendings(SYM);
         return;
      }
      double ph,pl,atr;
      if(!PrevDayRange(SYM, today, ph, pl)) return;
      if(!Atr14(SYM, atr) || atr<=0) return;
      double d = PdhlStopATR*atr;
      if(DrawLevels) DrawSetup(ph, ph-d, pl, pl+d);            // buy=ph, sell=pl (draw always)
      if(px>0 && (px<pl || px>ph)) {                           // already outside prior-day range
         g_tradedToday=true;
         Notify(SYM+" PDHL: prior-day range already broken before arming — skip today");
         return;
      }
      EnsureStops(SYM, ph, ph-d, pl, pl+d, "AurvexPDHL");
   }
}

//+------------------------------------------------------------------+
//| data helpers                                                     |
//+------------------------------------------------------------------+
// Broker bars are timestamped in SERVER time, but our sessions are UTC. This is
// the server-minus-UTC offset (whole hours) used to convert a bar's time to UTC.
long ServerUtcOffset()
{
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}
// First UTC hour (00:00-01:00 UTC) high/low for `dayStart` (a UTC day start).
// Scans recent H1 bars and matches by UTC hour, so it is correct on ANY broker
// timezone (fixes the gold ORB grabbing the wrong hour on a UTC+n server).
bool FirstHourRange(string sym, datetime dayStart, double &hi, double &lo)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n = CopyRates(sym, PERIOD_H1, 0, 60, r);
   if(n < 2) return false;
   long off = ServerUtcOffset();
   for(int k=0;k<n;k++){
      long utc = (long)r[k].time - off;                       // bar open in UTC
      if(UtcDayStart((datetime)utc)==dayStart && ((utc%86400)/3600)==0){
         hi=r[k].high; lo=r[k].low;
         return (hi>lo);
      }
   }
   return false;
}
// Prior UTC day's high/low. Scans recent H1 bars and keeps those whose UTC day is
// the day before `dayStart` — correct on any broker timezone.
bool PrevDayRange(string sym, datetime dayStart, double &ph, double &pl)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n = CopyRates(sym, PERIOD_H1, 0, 96, r);
   if(n < 3) return false;
   long off = ServerUtcOffset();
   datetime prevDay = dayStart - 86400;
   ph=-DBL_MAX; pl=DBL_MAX; int cnt=0;
   for(int k=0;k<n;k++){
      long utc = (long)r[k].time - off;
      if(UtcDayStart((datetime)utc)==prevDay){
         ph=MathMax(ph,r[k].high); pl=MathMin(pl,r[k].low); cnt++;
      }
   }
   return (cnt>=3 && ph>pl);
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
//| chart level drawing                                              |
//+------------------------------------------------------------------+
void DrawHLine(string tag, double price, color col, int style)
{
   string name = tag + "_" + (string)Magic;
   if(ObjectFind(0,name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   else
      ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, col);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetString (0, name, OBJPROP_TEXT, tag);
}
void DrawSetup(double buyP, double buySL, double sellP, double sellSL)
{
   DrawHLine("AX_BUY",    buyP,   clrLime, STYLE_SOLID);
   DrawHLine("AX_BUYSL",  buySL,  clrGray, STYLE_DOT);
   DrawHLine("AX_SELL",   sellP,  clrRed,  STYLE_SOLID);
   DrawHLine("AX_SELLSL", sellSL, clrGray, STYLE_DOT);
   ChartRedraw(0);
}
void DeleteLevels()
{
   ObjectDelete(0, "AX_BUY_"    + (string)Magic);
   ObjectDelete(0, "AX_BUYSL_"  + (string)Magic);
   ObjectDelete(0, "AX_SELL_"   + (string)Magic);
   ObjectDelete(0, "AX_SELLSL_" + (string)Magic);
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| order/position management (this symbol only)                     |
//+------------------------------------------------------------------+
bool HasPosition(string sym)
{
   for(int i=PositionsTotal()-1;i>=0;i--){
      if(PositionGetTicket(i)==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==Magic) return true; }
   return false;
}
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
// Close all of OUR orders + positions for this symbol (hedge-safe: close by ticket).
void FlattenSymbol(string sym)
{
   for(int i=OrdersTotal()-1;i>=0;i--){
      ulong t=OrderGetTicket(i);
      if(OrderGetString(ORDER_SYMBOL)==sym && OrderGetInteger(ORDER_MAGIC)==Magic)
         trade.OrderDelete(t); }
   for(int i=PositionsTotal()-1;i>=0;i--){
      ulong t=PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL)==sym && PositionGetInteger(POSITION_MAGIC)==Magic)
         trade.PositionClose(t); }
}

// Trailing stop: once the open position is +TrailStopR in profit, trail the SL to
// stay TrailStopR behind the best price (locks profit, keeps upside). OOS-neutral
// on expectancy but smooths the equity curve and cuts "gave it all back" losses.
void ManageTrailing()
{
   if(TrailStopR <= 0) return;
   ulong tk = 0;
   for(int i=PositionsTotal()-1;i>=0;i--){
      ulong t=PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL)==SYM && PositionGetInteger(POSITION_MAGIC)==Magic){ tk=t; break; }
   }
   if(tk==0){ g_haveTrade=false; return; }

   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl    = PositionGetDouble(POSITION_SL);
   double tp    = PositionGetDouble(POSITION_TP);
   bool   isLong = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double bid = SymbolInfoDouble(SYM, SYMBOL_BID);
   double ask = SymbolInfoDouble(SYM, SYMBOL_ASK);

   if(!g_haveTrade){                       // first sight of this position: record its risk
      g_haveTrade=true; g_tEntry=entry; g_tLong=isLong;
      g_tRisk=MathAbs(entry-sl);
      g_tPeak=(isLong ? bid : ask);
   }
   if(g_tRisk<=0) return;

   int    d = (int)SymbolInfoInteger(SYM, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(SYM, SYMBOL_POINT);
   double stopLvl = (double)SymbolInfoInteger(SYM, SYMBOL_TRADE_STOPS_LEVEL) * point;

   if(isLong){
      g_tPeak = MathMax(g_tPeak, bid);
      if((g_tPeak-g_tEntry)/g_tRisk >= TrailStopR){
         double newSL = NormalizeDouble(g_tPeak - TrailStopR*g_tRisk, d);
         if(newSL > sl + point && newSL < bid - stopLvl)
            trade.PositionModify(tk, newSL, tp);
      }
   } else {
      g_tPeak = MathMin(g_tPeak, ask);
      if((g_tEntry-g_tPeak)/g_tRisk >= TrailStopR){
         double newSL = NormalizeDouble(g_tPeak + TrailStopR*g_tRisk, d);
         if((sl==0 || newSL < sl - point) && newSL > ask + stopLvl)
            trade.PositionModify(tk, newSL, tp);
      }
   }
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
   if(eq <= dailyFloor)  { Notify(SYM+" GUARD: daily floor — flatten + stop for the day");  return false; }
   if(eq <= overallFloor){ Notify(SYM+" GUARD: overall floor — flatten + stop");            return false; }
   return true;
}

//+------------------------------------------------------------------+
//| High-impact news buffer (FTMO news rule)                         |
//+------------------------------------------------------------------+
// True if a HIGH-importance event for this symbol's quote currency falls within
// NewsBufferMin minutes either side of now. Uses the terminal's built-in
// Economic Calendar; if the calendar has no data it returns false (fail-safe).
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
