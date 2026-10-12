//+------------------------------------------------------------------+
//| AurvexTrendContCandidate_c3.mq5 — C3 TREND-CONTINUATION candidate |
//| SEPARATE tester-only candidate EA. Does NOT touch the live EA.    |
//| Compile to its OWN .ex5 (e.g. Aurvex_trend_c3) and run only in    |
//| the Strategy Tester. ⚠ UNCOMPILED SKELETON — NOT PASS until F7    |
//| (0 errors) + MT5 verification.                                    |
//|                                                                    |
//| Rules (FTMO_CANDIDATES_PLAN.md C3), indices (GER40/JP225), H1:     |
//|  regime up = Close > EMA(EmaSlow) AND Close > prior-day close;     |
//|  entry = after a pullback that tagged EMA(EmaFast), on the break   |
//|  of the prior bar's high (mirror for down); stop = max(swing,      |
//|  AtrStopMult*ATR); exit = ATR chandelier trail (TrailAtrMult*ATR)  |
//|  + session/Friday flatten. Cost gate + FTMO daily/overall halt +   |
//|  tester-safe UTC clock, as C1.                                     |
//+------------------------------------------------------------------+
#property copyright "Aurvex / trend-continuation research candidate (tester-only)"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>

input double RiskPct                   = 0.46;   // match the index baseline risk band per symbol
input double AccountSize               = 25000;
input bool   RequireAccountSize        = true;
input int    EmaFast                   = 20;     // pullback EMA (H1)
input int    EmaSlow                   = 200;    // trend EMA (H1)
input int    AtrPeriod                 = 14;
input double AtrStopMult               = 1.5;    // initial stop = AtrStopMult*ATR(H1)
input double TrailAtrMult              = 3.0;    // chandelier trail = highest-since-entry - mult*ATR
input int    MaxTradesPerDay           = 3;
input double CostGateMult              = 2.0;    // require target-ish (AtrStopMult*ATR) >= mult*(spread+comm+slip)
input double CommissionPerLotUSD       = 0.0;
input double SlippageBufferPts         = 0.0;
input double DailyLossPct              = 5.0;
input double OverallLossPct            = 10.0;
input int    FridayFlattenUTCMin       = 1200;
input int    ServerUtcOffsetOverrideHours = 999;
input int    TesterServerUtcOffsetHours   = 999;
input int    DailyResetHourUTC          = -1;    // account daily-loss reset: -1 = broker/server midnight
input long   Magic                     = 880033;

CTrade  trade;
int     g_emaF=INVALID_HANDLE, g_emaS=INVALID_HANDLE, g_atr=INVALID_HANDLE;
string  SYM;
double  g_initBal=0, g_dayStartBal=0, g_entryExtreme=0;
long    g_acctDay=0;
datetime g_lastBar=0;
int     g_tradesToday=0;
bool    g_haltAll=false, g_haltDay=false;
int     g_pendDir=0;                 // pending setup from the last CLOSED bar: +1 up, -1 down, 0 none
double  g_pendTrigger=0, g_pendStop=0;   // breakout trigger level + stop distance for the setup

long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999) return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999) return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}
datetime NowUtc(){ return (bool)MQLInfoInteger(MQL_TESTER)?(datetime)((long)TimeTradeServer()-ServerUtcOffset()):TimeGMT(); }

double Buf(int h,int shift){ double b[]; if(h==INVALID_HANDLE||CopyBuffer(h,0,shift,1,b)<1) return 0; return b[0]; }
double PointSize(){ return SymbolInfoDouble(SYM,SYMBOL_POINT); }
double MoneyPerPricePerLot(){ double ts=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_SIZE),tv=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_VALUE); return ts>0?tv/ts:0; }
double NormalizeLots(double lots){ double mn=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MIN),st=SymbolInfoDouble(SYM,SYMBOL_VOLUME_STEP),mx=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MAX); if(st>0)lots=MathFloor(lots/st)*st; if(lots<mn)return 0; if(lots>mx)lots=mx; return lots; }
double LotsForStop(double stopPx){ double bal=(AccountSize>0)?AccountSize:AccountInfoDouble(ACCOUNT_BALANCE),m=MoneyPerPricePerLot(); if(stopPx<=0||m<=0)return 0; return NormalizeLots((bal*RiskPct/100.0)/(stopPx*m)); }
double PriorDayClose(){ return iClose(SYM,PERIOD_D1,1); }
bool WeekendOrFriClose(datetime u){ MqlDateTime d; TimeToStruct(u,d); if(d.day_of_week==0||d.day_of_week==6)return true; if(d.day_of_week==5 && d.hour*60+d.min>=FridayFlattenUTCMin)return true; return false; }

long AcctDayIndex(datetime u){ long sec=(DailyResetHourUTC>=0)?((long)u-(long)DailyResetHourUTC*3600):((long)u+ServerUtcOffset()); return sec/86400; }
void FlattenC(){ if(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic){ if(!trade.PositionClose(SYM)||trade.ResultRetcode()!=TRADE_RETCODE_DONE) return; } g_entryExtreme=0; }
void RefreshDay(datetime u){ g_acctDay=AcctDayIndex(u); g_tradesToday=0; g_haltDay=false; g_dayStartBal=AccountInfoDouble(ACCOUNT_BALANCE); }
void CheckGuards(){ double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_initBal>0&&eq<=g_initBal*(1.0-OverallLossPct/100.0)&&!g_haltAll){g_haltAll=true;FlattenC();}
   if(g_dayStartBal>0&&eq<=g_dayStartBal*(1.0-DailyLossPct/100.0)&&!g_haltDay){g_haltDay=true;FlattenC();} }

int OnInit()
{
   SYM=_Symbol;
   if(!(bool)MQLInfoInteger(MQL_TESTER)){Print("C3 is a TESTER-ONLY candidate — refusing to run live.");return INIT_FAILED;}
   if(RequireAccountSize&&AccountSize<=0){Print("C3: AccountSize<=0");return INIT_PARAMETERS_INCORRECT;}
   g_emaF=iMA(SYM,PERIOD_H1,EmaFast,0,MODE_EMA,PRICE_CLOSE);
   g_emaS=iMA(SYM,PERIOD_H1,EmaSlow,0,MODE_EMA,PRICE_CLOSE);
   g_atr =iATR(SYM,PERIOD_H1,AtrPeriod);
   if(g_emaF==INVALID_HANDLE||g_emaS==INVALID_HANDLE||g_atr==INVALID_HANDLE){Print("C3: handle fail");return INIT_FAILED;}
   trade.SetExpertMagicNumber(Magic);
   g_initBal=AccountInfoDouble(ACCOUNT_BALANCE); RefreshDay(NowUtc());
   Print(StringFormat("Aurvex trend C3 on %s emaF=%d emaS=%d atrMult=%.2f trail=%.2f offsetH=%d",
         SYM,EmaFast,EmaSlow,AtrStopMult,TrailAtrMult,(int)(ServerUtcOffset()/3600)));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ if(g_emaF!=INVALID_HANDLE)IndicatorRelease(g_emaF); if(g_emaS!=INVALID_HANDLE)IndicatorRelease(g_emaS); if(g_atr!=INVALID_HANDLE)IndicatorRelease(g_atr); }

void OnTick()
{
   datetime u=NowUtc();
   if(AcctDayIndex(u)!=g_acctDay) RefreshDay(u);
   CheckGuards();
   bool have=(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic);

   // while HALTED, keep retrying the close every tick until the position is actually gone
   if((g_haltAll||g_haltDay) && have){ FlattenC(); return; }

   // manage open position: chandelier trail + session/weekend flatten
   if(have)
   {
      if(WeekendOrFriClose(u)){ FlattenC(); return; }
      double atr=Buf(g_atr,1); long ptype=PositionGetInteger(POSITION_TYPE);
      double cur=(ptype==POSITION_TYPE_BUY)?SymbolInfoDouble(SYM,SYMBOL_BID):SymbolInfoDouble(SYM,SYMBOL_ASK);
      if(ptype==POSITION_TYPE_BUY){ if(cur>g_entryExtreme||g_entryExtreme==0)g_entryExtreme=cur;
         double newSl=g_entryExtreme-TrailAtrMult*atr; double sl=PositionGetDouble(POSITION_SL);
         if(atr>0 && newSl>sl) trade.PositionModify(SYM,newSl,PositionGetDouble(POSITION_TP)); }
      else { if(cur<g_entryExtreme||g_entryExtreme==0)g_entryExtreme=cur;
         double newSl=g_entryExtreme+TrailAtrMult*atr; double sl=PositionGetDouble(POSITION_SL);
         if(atr>0 && (sl==0||newSl<sl)) trade.PositionModify(SYM,newSl,PositionGetDouble(POSITION_TP)); }
      return;
   }
   if(g_haltAll||g_haltDay||WeekendOrFriClose(u)) return;

   // On each NEW CLOSED H1 bar, (re)build the pending setup from closed-bar data only. The
   // breakout TRIGGER is the prior bar's high/low; it is then watched on subsequent ticks.
   datetime bar=iTime(SYM,PERIOD_H1,0);
   if(bar!=g_lastBar)
   {
      g_lastBar=bar; g_pendDir=0;
      double emaF=Buf(g_emaF,1), emaS=Buf(g_emaS,1), atr=Buf(g_atr,1);
      double c1=iClose(SYM,PERIOD_H1,1), h1=iHigh(SYM,PERIOD_H1,1), l1=iLow(SYM,PERIOD_H1,1);
      double pdc=PriorDayClose();
      if(emaF>0&&emaS>0&&atr>0&&pdc>0)
      {
         double stopPx=AtrStopMult*atr;
         double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID), m=MoneyPerPricePerLot();
         double costPx=(ask-bid)+((m>0)?(2.0*CommissionPerLotUSD)/m:0.0)+SlippageBufferPts*PointSize();
         if(stopPx>=CostGateMult*costPx)                     // cost gate at setup time
         {
            if(c1>emaS && c1>pdc && l1<=emaF){ g_pendDir=+1; g_pendTrigger=h1; g_pendStop=stopPx; }   // up pullback
            else if(c1<emaS && c1<pdc && h1>=emaF){ g_pendDir=-1; g_pendTrigger=l1; g_pendStop=stopPx; } // down pullback
         }
      }
   }
   // watch the pending breakout on EVERY tick of the current bar (not only at the bar edge)
   if(g_pendDir==0 || g_tradesToday>=MaxTradesPerDay) return;
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double lots=LotsForStop(g_pendStop); if(lots<=0){ g_pendDir=0; return; }
   if(g_pendDir>0 && ask>g_pendTrigger)
   {
      trade.Buy(lots,SYM,0.0,ask-g_pendStop,0.0,"trendC3"); uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_entryExtreme=ask; g_tradesToday++; }
      g_pendDir=0;                                           // setup consumed this bar either way
   }
   else if(g_pendDir<0 && bid<g_pendTrigger)
   {
      trade.Sell(lots,SYM,0.0,bid+g_pendStop,0.0,"trendC3"); uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_entryExtreme=bid; g_tradesToday++; }
      g_pendDir=0;
   }
}
//+------------------------------------------------------------------+
