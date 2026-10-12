//+------------------------------------------------------------------+
//| AurvexMeanRevCandidate_c4.mq5 — C4 MEAN-REVERSION candidate       |
//| SEPARATE tester-only candidate EA. Does NOT touch the live EA.    |
//| Compile to its OWN .ex5 (e.g. Aurvex_meanrev_c4) and run only in  |
//| the Strategy Tester. ⚠ UNCOMPILED SKELETON — NOT PASS until F7    |
//| (0 errors) + MT5 verification.                                    |
//|                                                                    |
//| Rules (FTMO_CANDIDATES_PLAN.md C4), indices, M5 signals in a RANGE |
//|  regime (ADX(H1) < AdxMax): fade an over-extension — short when    |
//|  Close>upper Bollinger(BbPeriod,BbDev) and RSI>RsiHi; long on the  |
//|  mirror. Stop beyond the band +/- AtrStopMult*ATR(M5); TP at the   |
//|  middle band (mean); time-stop TimeStopMin; session/Friday flat.   |
//|  Cost gate + FTMO daily/overall halt + tester-safe UTC clock.      |
//+------------------------------------------------------------------+
#property copyright "Aurvex / mean-reversion research candidate (tester-only)"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>

input double RiskPct                   = 0.46;
input double AccountSize               = 25000;
input bool   RequireAccountSize        = true;
input int    BbPeriod                  = 20;     // Bollinger period (M5)
input double BbDev                     = 2.0;    // Bollinger deviations
input int    RsiPeriod                 = 14;
input double RsiHi                     = 70.0;   // short above this; long below (100-RsiHi)
input int    AdxPeriod                 = 14;
input double AdxMax                    = 20.0;   // trade only when ADX(H1) < AdxMax (range regime)
input int    AtrPeriod                 = 14;
input double AtrStopMult               = 1.0;    // stop beyond band by AtrStopMult*ATR(M5)
input int    TimeStopMin               = 30;
input int    MaxTradesPerDay           = 4;
input double CostGateMult              = 2.0;
input double CommissionPerLotUSD       = 0.0;
input double SlippageBufferPts         = 0.0;
input double DailyLossPct              = 5.0;
input double OverallLossPct            = 10.0;
input int    FridayFlattenUTCMin       = 1200;
input int    ServerUtcOffsetOverrideHours = 999;
input int    TesterServerUtcOffsetHours   = 999;
input int    DailyResetHourUTC          = -1;    // account daily-loss reset: -1 = broker/server midnight
input long   Magic                     = 880044;

CTrade  trade;
int     g_bb=INVALID_HANDLE, g_rsi=INVALID_HANDLE, g_adx=INVALID_HANDLE, g_atr=INVALID_HANDLE;
string  SYM;
double  g_initBal=0, g_dayStartBal=0;
long    g_acctDay=0;
datetime g_lastBar=0, g_posOpenUtc=0;
int     g_tradesToday=0;
bool    g_haltAll=false, g_haltDay=false;

long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999) return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999) return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}
datetime NowUtc(){ return (bool)MQLInfoInteger(MQL_TESTER)?(datetime)((long)TimeTradeServer()-ServerUtcOffset()):TimeGMT(); }

double Buf(int h,int idx,int shift){ double b[]; if(h==INVALID_HANDLE||CopyBuffer(h,idx,shift,1,b)<1) return 0; return b[0]; }
double PointSize(){ return SymbolInfoDouble(SYM,SYMBOL_POINT); }
double MoneyPerPricePerLot(){ double ts=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_SIZE),tv=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_VALUE); return ts>0?tv/ts:0; }
double NormalizeLots(double lots){ double mn=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MIN),st=SymbolInfoDouble(SYM,SYMBOL_VOLUME_STEP),mx=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MAX); if(st>0)lots=MathFloor(lots/st)*st; if(lots<mn)return 0; if(lots>mx)lots=mx; return lots; }
double LotsForStop(double stopPx){ double bal=(AccountSize>0)?AccountSize:AccountInfoDouble(ACCOUNT_BALANCE),m=MoneyPerPricePerLot(); if(stopPx<=0||m<=0)return 0; return NormalizeLots((bal*RiskPct/100.0)/(stopPx*m)); }
bool WeekendOrFriClose(datetime u){ MqlDateTime d; TimeToStruct(u,d); if(d.day_of_week==0||d.day_of_week==6)return true; if(d.day_of_week==5 && d.hour*60+d.min>=FridayFlattenUTCMin)return true; return false; }

long AcctDayIndex(datetime u){ long sec=(DailyResetHourUTC>=0)?((long)u-(long)DailyResetHourUTC*3600):((long)u+ServerUtcOffset()); return sec/86400; }
void FlattenC(){ if(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic){ if(!trade.PositionClose(SYM)||trade.ResultRetcode()!=TRADE_RETCODE_DONE) return; } g_posOpenUtc=0; }
void RefreshDay(datetime u){ g_acctDay=AcctDayIndex(u); g_tradesToday=0; g_haltDay=false; g_dayStartBal=AccountInfoDouble(ACCOUNT_BALANCE); }
void CheckGuards(){ double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_initBal>0&&eq<=g_initBal*(1.0-OverallLossPct/100.0)&&!g_haltAll){g_haltAll=true;FlattenC();}
   if(g_dayStartBal>0&&eq<=g_dayStartBal*(1.0-DailyLossPct/100.0)&&!g_haltDay){g_haltDay=true;FlattenC();} }

int OnInit()
{
   SYM=_Symbol;
   if(!(bool)MQLInfoInteger(MQL_TESTER)){Print("C4 is a TESTER-ONLY candidate — refusing to run live.");return INIT_FAILED;}
   if(RequireAccountSize&&AccountSize<=0){Print("C4: AccountSize<=0");return INIT_PARAMETERS_INCORRECT;}
   g_bb =iBands(SYM,PERIOD_M5,BbPeriod,0,BbDev,PRICE_CLOSE);
   g_rsi=iRSI(SYM,PERIOD_M5,RsiPeriod,PRICE_CLOSE);
   g_adx=iADX(SYM,PERIOD_H1,AdxPeriod);
   g_atr=iATR(SYM,PERIOD_M5,AtrPeriod);
   if(g_bb==INVALID_HANDLE||g_rsi==INVALID_HANDLE||g_adx==INVALID_HANDLE||g_atr==INVALID_HANDLE){Print("C4: handle fail");return INIT_FAILED;}
   trade.SetExpertMagicNumber(Magic);
   g_initBal=AccountInfoDouble(ACCOUNT_BALANCE); RefreshDay(NowUtc());
   Print(StringFormat("Aurvex meanrev C4 on %s bb=%d/%.1f rsiHi=%.0f adxMax=%.0f offsetH=%d",
         SYM,BbPeriod,BbDev,RsiHi,AdxMax,(int)(ServerUtcOffset()/3600)));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ if(g_bb!=INVALID_HANDLE)IndicatorRelease(g_bb); if(g_rsi!=INVALID_HANDLE)IndicatorRelease(g_rsi); if(g_adx!=INVALID_HANDLE)IndicatorRelease(g_adx); if(g_atr!=INVALID_HANDLE)IndicatorRelease(g_atr); }

void OnTick()
{
   datetime u=NowUtc();
   if(AcctDayIndex(u)!=g_acctDay) RefreshDay(u);
   CheckGuards();
   bool have=(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic);
   if(have)
   {
      if(TimeStopMin>0 && g_posOpenUtc>0 && (long)u-(long)g_posOpenUtc>=(long)TimeStopMin*60){ FlattenC(); return; }
      if(WeekendOrFriClose(u)){ FlattenC(); return; }
      return;                                       // TP (mean) / SL are broker-side
   }
   if(g_haltAll||g_haltDay||WeekendOrFriClose(u)) return;
   if(g_tradesToday>=MaxTradesPerDay) return;

   datetime bar=iTime(SYM,PERIOD_M5,0);
   if(bar==g_lastBar) return;                       // one evaluation per new M5 bar
   g_lastBar=bar;

   double adx=Buf(g_adx,0,1); if(adx<=0 || adx>=AdxMax) return;   // range regime only
   double mid=Buf(g_bb,0,1), up=Buf(g_bb,1,1), lo=Buf(g_bb,2,1);  // 0=base,1=upper,2=lower
   double rsi=Buf(g_rsi,0,1), atr=Buf(g_atr,0,1);
   if(mid<=0||up<=0||lo<=0||atr<=0) return;
   double c1=iClose(SYM,PERIOD_M5,1); if(c1<=0) return;
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID), m=MoneyPerPricePerLot();
   double costPx=(ask-bid)+((m>0)?(2.0*CommissionPerLotUSD)/m:0.0)+SlippageBufferPts*PointSize();
   double rsiLo=100.0-RsiHi;

   if(c1>up && rsi>RsiHi)                            // over-extended up -> fade short
   {
      double sl=up+AtrStopMult*atr, tp=mid, stopPx=sl-bid;
      if(stopPx>0 && (bid-tp) >= CostGateMult*costPx)
      { double lots=LotsForStop(stopPx); if(lots>0){ trade.Sell(lots,SYM,0.0,sl,tp,"meanrevC4"); uint rc=trade.ResultRetcode(); if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){g_posOpenUtc=u;g_tradesToday++;} } }
   }
   else if(c1<lo && rsi<rsiLo)                       // over-extended down -> fade long
   {
      double sl=lo-AtrStopMult*atr, tp=mid, stopPx=ask-sl;
      if(stopPx>0 && (tp-ask) >= CostGateMult*costPx)
      { double lots=LotsForStop(stopPx); if(lots>0){ trade.Buy(lots,SYM,0.0,sl,tp,"meanrevC4"); uint rc=trade.ResultRetcode(); if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){g_posOpenUtc=u;g_tradesToday++;} } }
   }
}
//+------------------------------------------------------------------+
