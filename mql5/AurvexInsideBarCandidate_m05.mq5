//+------------------------------------------------------------------+
//| AurvexInsideBarCandidate_m05.mq5 — M05 INSIDE-BAR BREAKOUT         |
//| SEPARATE tester-only candidate EA. Does NOT touch the live EA.    |
//| Compile to its OWN .ex5 (e.g. Aurvex_insidebar_m05) and run only  |
//| in the Strategy Tester. ⚠ UNCOMPILED SKELETON — NOT PASS until F7 |
//| (0 errors) + MT5 verification.                                    |
//|                                                                    |
//| This is the FIRST source-scan candidate whose rules are LOCKED     |
//| (FTMO_SOURCE_SCAN.md M05). The entry/stop/exit come from public    |
//| sources that DIRECTLY describe the inside-bar breakout; our added  |
//| FTMO/engine mechanics are marked [ADAPTATION] and are NOT claimed  |
//| to come from the source.                                           |
//|                                                                    |
//| FROM SOURCE — inside-bar breakout                                  |
//|   LuxAlgo, "Inside Bar Breakouts: Tight Risk, Big Reward"          |
//|     https://www.luxalgo.com/blog/inside-bar-breakouts-tight-risk-big-reward/
//|   TradingView "BOIB Pro" (XCcBBQ1t) inside-bar breakout script     |
//|     https://www.tradingview.com/script/XCcBBQ1t                    |
//|   - pattern: an inside bar whose whole range sits inside the prior |
//|     ("mother") bar's range.                                        |
//|   - entry : break of the MOTHER bar high (long) / low (short);     |
//|             BOIB Pro waits up to N bars and wants a close beyond.   |
//|   - stop  : the OPPOSITE end of the mother bar (LuxAlgo).          |
//|   - exit  : fixed R target — BOIB Pro defaults 1R (and 2R).        |
//|   - TF    : LuxAlgo prefers the daily for cleaner signals.         |
//|                                                                    |
//| [ADAPTATION] — ours, not from the source (declared)                |
//|   - closed-bar setup + tick trigger (same discipline as C3):       |
//|     detect the inside bar on CLOSED bars, watch the mother break   |
//|     on subsequent ticks, enter via retcode.                        |
//|   - BreakBufferPts beyond the mother extreme (source value         |
//|     unspecified → parameter, default 0).                           |
//|   - SetupValidBars: cancel an un-triggered setup after N bars.     |
//|   - RiskPct sizing to the stop distance; cost gate at setup.       |
//|   - FTMO daily/overall halt, weekend/Friday flat, account-rule     |
//|     daily reset hour, tester-safe UTC clock, tester-only guard.    |
//|   - InsideTF is parameterized (NOT forced daily) so it can be run  |
//|     on our instruments/periods; set the tester --tf to match.      |
//+------------------------------------------------------------------+
#property copyright "Aurvex / inside-bar breakout research candidate (tester-only)"
#property version   "0.10"
#property strict
#include <Trade/Trade.mqh>

input double        RiskPct                   = 0.46;  // match the baseline risk band per symbol [ADAPTATION]
input double        AccountSize               = 25000;
input bool          RequireAccountSize        = true;
input ENUM_TIMEFRAMES InsideTF                = PERIOD_H1; // detect inside bars on this TF (set tester --tf to match)
input double        TpR                       = 1.0;   // take-profit in R; BOIB Pro default is 1R (source)
input int           BreakBufferPts            = 0;     // break buffer beyond the mother extreme [ADAPTATION]
input int           SetupValidBars            = 3;     // cancel an un-triggered setup after N bars [ADAPTATION]
input bool          RequireCloseBeyond        = false; // BOIB-Pro-style close-beyond confirmation (source variant)
input int           MaxTradesPerDay           = 3;
input double        CostGateMult              = 2.0;   // require R-stop >= mult*(spread+comm+slip) [ADAPTATION]
input double        CommissionPerLotUSD       = 0.0;
input double        SlippageBufferPts         = 0.0;
input double        DailyLossPct              = 5.0;
input double        OverallLossPct            = 10.0;
input int           FridayFlattenUTCMin       = 1200;
input int           ServerUtcOffsetOverrideHours = 999;
input int           TesterServerUtcOffsetHours   = 999;
input int           DailyResetHourUTC          = -1;   // account daily-loss reset: -1 = broker/server midnight
input long          Magic                     = 880055;

CTrade  trade;
string  SYM;
double  g_initBal=0, g_dayStartBal=0;
long    g_acctDay=0;
datetime g_lastBar=0;
int     g_tradesToday=0;
bool    g_haltAll=false, g_haltDay=false;
int     g_pendDir=0;                 // pending setup from the CLOSED inside bar: +1 up, -1 down, 0 none
double  g_pendTrigger=0, g_pendStop=0, g_pendTp=0;   // breakout trigger, stop distance, TP distance
int     g_pendAge=0;                 // bars since the setup was armed

long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999) return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999) return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}
datetime NowUtc(){ return (bool)MQLInfoInteger(MQL_TESTER)?(datetime)((long)TimeTradeServer()-ServerUtcOffset()):TimeGMT(); }

double PointSize(){ return SymbolInfoDouble(SYM,SYMBOL_POINT); }
double MoneyPerPricePerLot(){ double ts=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_SIZE),tv=SymbolInfoDouble(SYM,SYMBOL_TRADE_TICK_VALUE); return ts>0?tv/ts:0; }
double NormalizeLots(double lots){ double mn=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MIN),st=SymbolInfoDouble(SYM,SYMBOL_VOLUME_STEP),mx=SymbolInfoDouble(SYM,SYMBOL_VOLUME_MAX); if(st>0)lots=MathFloor(lots/st)*st; if(lots<mn)return 0; if(lots>mx)lots=mx; return lots; }
double LotsForStop(double stopPx){ double bal=(AccountSize>0)?AccountSize:AccountInfoDouble(ACCOUNT_BALANCE),m=MoneyPerPricePerLot(); if(stopPx<=0||m<=0)return 0; return NormalizeLots((bal*RiskPct/100.0)/(stopPx*m)); }
bool WeekendOrFriClose(datetime u){ MqlDateTime d; TimeToStruct(u,d); if(d.day_of_week==0||d.day_of_week==6)return true; if(d.day_of_week==5 && d.hour*60+d.min>=FridayFlattenUTCMin)return true; return false; }

long AcctDayIndex(datetime u){ long sec=(DailyResetHourUTC>=0)?((long)u-(long)DailyResetHourUTC*3600):((long)u+ServerUtcOffset()); return sec/86400; }
void FlattenC(){ if(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic){ if(!trade.PositionClose(SYM)||trade.ResultRetcode()!=TRADE_RETCODE_DONE) return; } }
void RefreshDay(datetime u){ g_acctDay=AcctDayIndex(u); g_tradesToday=0; g_haltDay=false; g_dayStartBal=AccountInfoDouble(ACCOUNT_BALANCE); }
void CheckGuards(){ double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_initBal>0&&eq<=g_initBal*(1.0-OverallLossPct/100.0)&&!g_haltAll){g_haltAll=true;FlattenC();}
   if(g_dayStartBal>0&&eq<=g_dayStartBal*(1.0-DailyLossPct/100.0)&&!g_haltDay){g_haltDay=true;FlattenC();} }

int OnInit()
{
   SYM=_Symbol;
   if(!(bool)MQLInfoInteger(MQL_TESTER)){Print("M05 is a TESTER-ONLY candidate — refusing to run live.");return INIT_FAILED;}
   if(RequireAccountSize&&AccountSize<=0){Print("M05: AccountSize<=0");return INIT_PARAMETERS_INCORRECT;}
   trade.SetExpertMagicNumber(Magic);
   g_initBal=AccountInfoDouble(ACCOUNT_BALANCE); RefreshDay(NowUtc());
   Print(StringFormat("Aurvex inside-bar M05 on %s tf=%d tpR=%.2f buf=%d validBars=%d closeBeyond=%s offsetH=%d",
         SYM,(int)InsideTF,TpR,BreakBufferPts,SetupValidBars,(RequireCloseBeyond?"true":"false"),(int)(ServerUtcOffset()/3600)));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ }

void OnTick()
{
   datetime u=NowUtc();
   if(AcctDayIndex(u)!=g_acctDay) RefreshDay(u);
   CheckGuards();
   bool have=(PositionSelect(SYM)&&PositionGetInteger(POSITION_MAGIC)==Magic);

   // manage open position: SL/TP are broker-side (fixed-R, per source); only force weekend/Friday flat
   if(have)
   {
      if(WeekendOrFriClose(u)){ FlattenC(); }
      return;
   }
   if(g_haltAll||g_haltDay||WeekendOrFriClose(u)) return;

   // On each NEW CLOSED bar of InsideTF, (re)build the pending setup from closed-bar data only.
   // bar[2] = mother bar, bar[1] = inside bar (fully contained). Trigger = mother high/low. [ADAPTATION: closed-bar+tick]
   datetime bar=iTime(SYM,InsideTF,0);
   if(bar!=g_lastBar)
   {
      g_lastBar=bar;
      if(g_pendDir!=0 && ++g_pendAge>SetupValidBars) g_pendDir=0;   // expire an un-triggered setup
      double mh=iHigh(SYM,InsideTF,2), ml=iLow(SYM,InsideTF,2);     // mother bar
      double ih=iHigh(SYM,InsideTF,1), il=iLow(SYM,InsideTF,1);     // inside bar
      bool inside=(mh>ml) && (ih<=mh) && (il>=ml) && !(ih==mh && il==ml);
      if(inside)
      {
         double stopUp=(mh+BreakBufferPts*PointSize())-ml;         // long: stop at mother low (opposite end)
         double stopDn=mh-(ml-BreakBufferPts*PointSize());         // short: stop at mother high (opposite end)
         double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID), m=MoneyPerPricePerLot();
         double costPx=(ask-bid)+((m>0)?(2.0*CommissionPerLotUSD)/m:0.0)+SlippageBufferPts*PointSize();
         // arm a FRESH setup (overrides any stale one so a new inside bar re-arms the trigger)
         if(stopUp>0 && stopUp>=CostGateMult*costPx)
         { g_pendDir=+1; g_pendTrigger=mh+BreakBufferPts*PointSize(); g_pendStop=stopUp; g_pendTp=TpR*stopUp; g_pendAge=0; }
         else if(stopDn>0 && stopDn>=CostGateMult*costPx)
         { g_pendDir=-1; g_pendTrigger=ml-BreakBufferPts*PointSize(); g_pendStop=stopDn; g_pendTp=TpR*stopDn; g_pendAge=0; }
      }
   }

   // watch the pending breakout on EVERY tick of the current bar
   if(g_pendDir==0 || g_tradesToday>=MaxTradesPerDay) return;
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK), bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double lots=LotsForStop(g_pendStop); if(lots<=0){ g_pendDir=0; return; }
   // optional BOIB-Pro close-beyond confirmation: require the last CLOSED bar to close beyond the trigger
   double c1=iClose(SYM,InsideTF,1);
   if(g_pendDir>0 && ask>g_pendTrigger && (!RequireCloseBeyond || c1>g_pendTrigger))
   {
      trade.Buy(lots,SYM,0.0,ask-g_pendStop,ask+g_pendTp,"insidebarM05"); uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_tradesToday++; }
      g_pendDir=0;                                           // setup consumed either way
   }
   else if(g_pendDir<0 && bid<g_pendTrigger && (!RequireCloseBeyond || c1<g_pendTrigger))
   {
      trade.Sell(lots,SYM,0.0,bid+g_pendStop,bid-g_pendTp,"insidebarM05"); uint rc=trade.ResultRetcode();
      if(rc==TRADE_RETCODE_DONE||rc==TRADE_RETCODE_PLACED){ g_tradesToday++; }
      g_pendDir=0;
   }
}
//+------------------------------------------------------------------+
