//+------------------------------------------------------------------+
//| AurvexScalpCandidate_c1.mq5 — C1 SCALP research candidate         |
//| SEPARATE candidate EA for the Strategy Tester ONLY. It does NOT   |
//| touch, include or replace the live EA (AurvexFTMO_v3_14/_v3_15).  |
//| Compile to its OWN .ex5 (e.g. Aurvex_scalp_c1) and run it only in |
//| the tester. ⚠ UNCOMPILED SKELETON — F7 (0 errors) + review before |
//| any use; status NOT PASS until compiled and tester-verified.      |
//|                                                                    |
//| Rules (see FTMO_CANDIDATES_PLAN.md C1): metals-style scalp —       |
//|  window [ScalpStartUTC..ScalpEndUTC); N-bar M1 high/low breakout;  |
//|  stop = AtrStopMult*ATR(M1,AtrPeriod); exit = TpR*stop OR          |
//|  TimeStopMin OR window/Friday flatten; MaxTradesPerDay cap; a COST |
//|  GATE skips a signal whose target < CostGateMult*(spread+comm+slip)|
//|  so wide-spread metals are not scalped into losses. FTMO daily/    |
//|  overall loss guards halt trading so limit behaviour is modelled.  |
//| UTC clock uses the SAME tester-offset pattern as the live EA so    |
//|  windows are correct in the Strategy Tester (set                   |
//|  TesterServerUtcOffsetHours to the broker's real offset, e.g. 3).  |
//+------------------------------------------------------------------+
#property copyright "Aurvex / scalp research candidate (tester-only)"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>

input double RiskPct                   = 0.46;   // risk % of AccountSize per trade (match baseline band)
input double AccountSize               = 25000;  // STARTING balance basis for risk (0 = use live balance)
input bool   RequireAccountSize        = true;   // refuse to init if AccountSize<=0 (avoid 0-lot)
input int    ScalpStartUTC             = 13;     // trade window start hour UTC (London-NY overlap)
input int    ScalpEndUTC               = 16;     // trade window end hour UTC (exclusive); flatten at end
input int    NbarLookback              = 5;      // breakout lookback: last N CLOSED M1 bars
input int    AtrPeriod                 = 14;     // ATR(M1) period for the stop
input double AtrStopMult               = 1.0;    // stop distance = AtrStopMult * ATR(M1)
input double TpR                       = 1.2;    // take-profit = TpR * stop distance (R multiple)
input int    TimeStopMin               = 10;     // time-stop: close a trade after this many minutes
input int    MaxTradesPerDay           = 6;      // hard cap on entries per UTC day
input double CostGateMult              = 3.0;    // require target >= CostGateMult*(spread+comm+slip)
input double CommissionPerLotUSD       = 0.0;    // round-turn commission per lot (0 = rely on broker spec)
input double SlippageBufferPts         = 0.0;    // extra slippage allowance (points) folded into the cost gate
input double DailyLossPct              = 5.0;    // FTMO daily-loss guard: halt the day past this DD
input double OverallLossPct            = 10.0;   // FTMO overall guard: halt entirely past this DD
input int    FridayFlattenUTCMin       = 1200;   // flatten + stop on Friday at/after this UTC minute (weekend-flat)
input int    DailyResetHourUTC          = -1;    // account daily-loss reset: -1 = broker/server midnight (FTMO rule)
input int    ServerUtcOffsetOverrideHours = 999; // 999 = auto from live server
input int    TesterServerUtcOffsetHours   = 999; // tester: set to the broker's real offset (e.g. 3)
input long   Magic                     = 880088; // candidate magic (distinct from live)

CTrade  trade;
int     g_atr=INVALID_HANDLE;
string  SYM;
double  g_initBal=0, g_dayStartBal=0;
long    g_acctDay=0;
datetime g_lastEntryBar=0, g_posOpenUtc=0;
int     g_tradesToday=0;
bool    g_haltAll=false, g_haltDay=false;

//--------------------------- UTC clock (tester-safe) ------------------//
long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999)
      return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999)
      return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}
datetime NowUtc()
{
   if((bool)MQLInfoInteger(MQL_TESTER))
      return (datetime)((long)TimeTradeServer()-ServerUtcOffset());
   return TimeGMT();
}

//--------------------------- helpers ----------------------------------//
double Atr()
{
   double b[]; if(g_atr==INVALID_HANDLE) return 0;
   if(CopyBuffer(g_atr,0,1,1,b)<1) return 0;   // last CLOSED bar's ATR
   return b[0];
}
double PointSize(){ return SymbolInfoDouble(SYM,SYMBOL_POINT); }
double MoneyPerPricePerLot()
{
   double ts=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_SIZE);
   double tv=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_VALUE);
   return (ts>0)?(tv/ts):0;                    // account money per 1.0 price move per 1 lot
}
double NormalizeLots(double lots)
{
   double mn=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MIN), st=SymbolInfoDouble(SYM,SYMBOL_VOLUME_STEP);
   double mx=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MAX);
   if(st>0) lots=MathFloor(lots/st)*st;
   if(lots<mn) lots=0;                         // below min -> no trade (never silently upsize)
   if(lots>mx) lots=mx;
   return lots;
}
double LotsForStop(double stopPx)
{
   double bal=(AccountSize>0)?AccountSize:AccountInfoDouble(ACCOUNT_BALANCE);
   double money=MoneyPerPricePerLot();
   if(stopPx<=0 || money<=0) return 0;
   double riskMoney=bal*RiskPct/100.0;
   return NormalizeLots(riskMoney/(stopPx*money));
}
bool InWindow(datetime u)
{
   MqlDateTime d; TimeToStruct(u,d);
   if(d.day_of_week==0 || d.day_of_week==6) return false;              // weekend flat
   if(d.day_of_week==5 && d.hour*60+d.min>=FridayFlattenUTCMin) return false;
   return (d.hour>=ScalpStartUTC && d.hour<ScalpEndUTC);
}
double HighestN(){ int s=iHighest(SYM,PERIOD_M1,MODE_HIGH,NbarLookback,1); return (s<0)?0:iHigh(SYM,PERIOD_M1,s); }
double LowestN(){  int s=iLowest (SYM,PERIOD_M1,MODE_LOW, NbarLookback,1); return (s<0)?0:iLow (SYM,PERIOD_M1,s); }

// account-day index per the FTMO reset rule: default (-1) rolls at the BROKER/server midnight
// (server = UTC + ServerUtcOffset); an explicit DailyResetHourUTC overrides it.
long AcctDayIndex(datetime u)
{
   long sec=(DailyResetHourUTC>=0)?((long)u-(long)DailyResetHourUTC*3600):((long)u+ServerUtcOffset());
   return sec/86400;
}
void FlattenCandidate(string why)
{
   if(PositionSelect(SYM) && PositionGetInteger(POSITION_MAGIC)==Magic)
   {
      if(!trade.PositionClose(SYM) || trade.ResultRetcode()!=TRADE_RETCODE_DONE)
         return;                                 // close FAILED -> preserve management state, retry
   }
   g_posOpenUtc=0;                                // cleared only on a confirmed close (or already flat)
}

//--------------------------- FTMO guards ------------------------------//
void RefreshDay(datetime u)
{
   g_acctDay=AcctDayIndex(u); g_tradesToday=0; g_haltDay=false;
   g_dayStartBal=AccountInfoDouble(ACCOUNT_BALANCE);
}
void CheckGuards()
{
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_initBal>0 && eq<=g_initBal*(1.0-OverallLossPct/100.0)){ if(!g_haltAll){ g_haltAll=true; FlattenCandidate("overall-loss"); } }
   if(g_dayStartBal>0 && eq<=g_dayStartBal*(1.0-DailyLossPct/100.0)){ if(!g_haltDay){ g_haltDay=true; FlattenCandidate("daily-loss"); } }
}

//--------------------------- lifecycle --------------------------------//
int OnInit()
{
   SYM=_Symbol;
   if(!(bool)MQLInfoInteger(MQL_TESTER)){ Print("Scalp C1 is a TESTER-ONLY candidate — refusing to run live."); return INIT_FAILED; }
   if(RequireAccountSize && AccountSize<=0){ Print("Scalp C1: AccountSize<=0"); return INIT_PARAMETERS_INCORRECT; }
   if(ScalpStartUTC<0||ScalpStartUTC>23||ScalpEndUTC<=ScalpStartUTC||ScalpEndUTC>24||NbarLookback<1){
      Print("Scalp C1: bad window/lookback inputs"); return INIT_PARAMETERS_INCORRECT; }
   g_atr=iATR(SYM,PERIOD_M1,AtrPeriod);
   if(g_atr==INVALID_HANDLE){ Print("Scalp C1: iATR handle failed"); return INIT_FAILED; }
   trade.SetExpertMagicNumber(Magic);
   g_initBal=AccountInfoDouble(ACCOUNT_BALANCE);
   RefreshDay(NowUtc());
   Print(StringFormat("Aurvex scalp C1 on %s window=%d-%dUTC N=%d atrMult=%.2f TpR=%.2f offsetH=%d",
         SYM,ScalpStartUTC,ScalpEndUTC,NbarLookback,AtrStopMult,TpR,(int)(ServerUtcOffset()/3600)));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ if(g_atr!=INVALID_HANDLE) IndicatorRelease(g_atr); }

void OnTick()
{
   datetime u=NowUtc();
   if(AcctDayIndex(u)!=g_acctDay) RefreshDay(u);
   CheckGuards();

   bool haveOurPos=(PositionSelect(SYM) && PositionGetInteger(POSITION_MAGIC)==Magic);

   // while HALTED, keep retrying the close every tick until the position is actually gone
   if((g_haltAll||g_haltDay) && haveOurPos){ FlattenCandidate("halt-retry"); return; }

   // manage an open position: time-stop, window/weekend flatten (TP/SL are broker-side)
   if(haveOurPos)
   {
      if(TimeStopMin>0 && g_posOpenUtc>0 && (long)u-(long)g_posOpenUtc>=(long)TimeStopMin*60){ FlattenCandidate("time-stop"); return; }
      if(!InWindow(u)){ FlattenCandidate("window/weekend close"); return; }
      return;                                   // otherwise let SL/TP work
   }
   if(g_haltAll || g_haltDay) return;
   if(!InWindow(u)) return;
   if(g_tradesToday>=MaxTradesPerDay) return;

   datetime bar=iTime(SYM,PERIOD_M1,0);
   if(bar==g_lastEntryBar) return;              // at most one entry attempt per M1 bar

   double atr=Atr(); if(atr<=0) return;
   double stopPx=AtrStopMult*atr; if(stopPx<=0) return;

   // cost gate: target distance must dominate spread + commission + slippage
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double money=MoneyPerPricePerLot();
   double spreadPx=ask-bid;
   double commPx=(money>0)?(2.0*CommissionPerLotUSD)/money:0.0;      // round-turn commission in price
   double slipPx=SlippageBufferPts*PointSize();
   double targetPx=TpR*stopPx;
   if(targetPx < CostGateMult*(spreadPx+commPx+slipPx)) return;      // skip: costs too large vs target

   double hiN=HighestN(), loN=LowestN(); if(hiN<=0||loN<=0) return;
   double lots=LotsForStop(stopPx); if(lots<=0) return;

   // an entry attempt consumes this bar whether or not the fill confirms (no retry storm);
   // state advances ONLY on a confirmed fill (retcode DONE/PLACED).
   if(ask>hiN)                                   // upside breakout -> buy
   {
      g_lastEntryBar=bar; double sl=ask-stopPx, tp=ask+targetPx;
      trade.Buy(lots,SYM,0.0,sl,tp,"scalpC1");
      uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_posOpenUtc=u; g_tradesToday++; }
   }
   else if(bid<loN)                              // downside breakout -> sell
   {
      g_lastEntryBar=bar; double sl=bid+stopPx, tp=bid-targetPx;
      trade.Sell(lots,SYM,0.0,sl,tp,"scalpC1");
      uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_posOpenUtc=u; g_tradesToday++; }
   }
}
//+------------------------------------------------------------------+
