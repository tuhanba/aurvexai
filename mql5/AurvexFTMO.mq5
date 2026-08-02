//+------------------------------------------------------------------+
//|  AurvexFTMO.mq5  —  ORB (gold) + PDHL (indices) auto-executor     |
//|  Places the exact stop-entry setups the Aurvex research validated:|
//|   * XAUUSD   Opening Range Breakout (first UTC hour)              |
//|   * GER40 / US100  Previous-Day High/Low breakout (ATR stop)      |
//|  First break wins; flat by 00:00 UTC; risk-based sizing from the  |
//|  broker's tick value (handles EUR-quoted GER40 automatically).    |
//|                                                                    |
//|  ⚠ DEMO FIRST. This is a reviewed skeleton, not yet run on a live |
//|  terminal — test on the FTMO Free Trial and watch it before any   |
//|  funded use. Start with gold only (indices inputs default false). |
//+------------------------------------------------------------------+
#property copyright "Aurvex"
#property version   "1.00"
#property strict
#include <Trade/Trade.mqh>

//--- inputs -------------------------------------------------------------
input double RiskPct          = 0.5;      // risk per trade (% of balance)
input int    OrbHours         = 1;        // opening-range length (hours)
input double PdhlStopATR      = 1.5;      // PDHL stop = ATR(14) * this
input int    MaxDailyLossPct  = 5;        // FTMO 2-step daily limit (guard)
input int    MaxOverallLossPct= 10;       // FTMO 2-step overall limit (guard)
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
bool    g_placedToday[3];
int     g_n = 0;

datetime g_lastDay   = 0;
double   g_dayOpenBal = 0;
double   g_initBal    = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(Magic);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_n = 0;
   if(Trade_XAUUSD){ g_sym[g_n]=Sym_XAUUSD; g_strat[g_n]="ORB";  g_enabled[g_n]=true; g_n++; }
   if(Trade_GER40 ){ g_sym[g_n]=Sym_GER40;  g_strat[g_n]="PDHL"; g_enabled[g_n]=true; g_n++; }
   if(Trade_US100 ){ g_sym[g_n]=Sym_US100;  g_strat[g_n]="PDHL"; g_enabled[g_n]=true; g_n++; }
   for(int i=0;i<g_n;i++){ g_placedToday[i]=false; SymbolSelect(g_sym[i], true); }
   g_initBal = (AccountSize>0 ? AccountSize : AccountInfoDouble(ACCOUNT_BALANCE));
   g_dayOpenBal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_lastDay = UtcDayStart(TimeGMT());
   EventSetTimer(20);
   PrintFormat("AurvexFTMO started. instruments=%d initBal=%.2f", g_n, g_initBal);
   return(INIT_SUCCEEDED);
}
void OnDeinit(const int reason){ EventKillTimer(); }

//+------------------------------------------------------------------+
datetime UtcDayStart(datetime t){ return (datetime)((long)t/86400*86400); }

void OnTimer()
{
   datetime nowGmt = TimeGMT();
   datetime today  = UtcDayStart(nowGmt);

   //--- new UTC day: flatten yesterday, reset, set the daily baseline
   if(today != g_lastDay)
   {
      SessionFlattenAll();
      for(int i=0;i<g_n;i++) g_placedToday[i]=false;
      g_dayOpenBal = AccountInfoDouble(ACCOUNT_BALANCE);
      g_lastDay = today;
      Notify("New UTC day — flat, baseline " + DoubleToString(g_dayOpenBal,2));
   }

   //--- FTMO loss guard: if near a floor, cancel pendings and stop for the day
   if(!LossGuardOk())
   {
      for(int i=0;i<g_n;i++){ DeletePendings(g_sym[i]); g_placedToday[i]=true; }
      return;
   }

   //--- per instrument
   for(int i=0;i<g_n;i++)
   {
      if(!g_enabled[i]) continue;
      ManageFirstBreak(g_sym[i]);            // one side filled -> cancel other
      if(g_placedToday[i]) continue;
      if(HasPosition(g_sym[i]) || HasPending(g_sym[i])) continue;

      if(g_strat[i]=="ORB")
      {
         // need the first UTC-hour bar closed
         if(nowGmt < today + OrbHours*3600) continue;
         double hi,lo;
         if(!FirstHourRange(g_sym[i], today, hi, lo)) continue;
         PlaceStops(g_sym[i], hi, lo, lo, hi, "AurvexORB");
         g_placedToday[i]=true;
      }
      else // PDHL
      {
         double ph,pl,atr;
         if(!PrevDayRange(g_sym[i], today, ph, pl)) continue;
         if(!Atr14(g_sym[i], atr) || atr<=0) continue;
         double d = PdhlStopATR*atr;
         PlaceStops(g_sym[i], ph, ph-d, pl, pl+d, "AurvexPDHL");
         g_placedToday[i]=true;
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
   if(n < 15) return false;
   double s=0; for(int k=0;k<14;k++){
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
   return lots;
}
void PlaceStops(string sym, double buyPrice, double buySL,
                double sellPrice, double sellSL, string tag)
{
   int    d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   buyPrice=NormalizeDouble(buyPrice,d);  buySL =NormalizeDouble(buySL,d);
   sellPrice=NormalizeDouble(sellPrice,d);sellSL=NormalizeDouble(sellSL,d);
   double lotB = CalcLots(sym, buyPrice, buySL);
   double lotS = CalcLots(sym, sellPrice, sellSL);
   if(lotB<=0 || lotS<=0){ Notify(sym+": lot calc failed, skipped"); return; }
   bool okb = trade.BuyStop (lotB, buyPrice,  sym, buySL, 0, ORDER_TIME_DAY, 0, tag);
   bool oks = trade.SellStop(lotS, sellPrice, sym, sellSL,0, ORDER_TIME_DAY, 0, tag);
   Notify(StringFormat("%s %s  BUY-STOP %.*f (%.2f lot) / SELL-STOP %.*f (%.2f lot)  ok=%d/%d",
          sym, tag, d, buyPrice, lotB, d, sellPrice, lotS, okb, oks));
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
//| FTMO loss guard (equity vs daily/overall floors)                 |
//+------------------------------------------------------------------+
bool LossGuardOk()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyFloor   = g_dayOpenBal - g_initBal*MaxDailyLossPct/100.0;
   double overallFloor = g_initBal   - g_initBal*MaxOverallLossPct/100.0;
   if(eq <= dailyFloor)  { Notify("GUARD: daily floor — stop for the day");  return false; }
   if(eq <= overallFloor){ Notify("GUARD: overall floor — stop");            return false; }
   return true;
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
   char res[]; string hdr; string rhdr;
   int code = WebRequest("POST", url, "Content-Type: application/x-www-form-urlencoded\r\n",
                         5000, data, res, rhdr);
   if(code==-1) Print("Telegram WebRequest failed (whitelist api.telegram.org).");
}
//+------------------------------------------------------------------+
