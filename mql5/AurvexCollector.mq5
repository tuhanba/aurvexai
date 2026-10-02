//+------------------------------------------------------------------+
//| AurvexCollector.mq5  — READ-ONLY live data collector              |
//| Runs on a SEPARATE (5th) chart alongside the trading EAs.          |
//| Collects ticks + deals/positions + account/symbol state for the    |
//| four symbols into daily CSVs (MQL5/Files). It has ZERO trade        |
//| authority: no CTrade, no OrderSend, no position/pending functions.  |
//| ⚠ UNCOMPILED SKELETON — F7 compile + verify in MT5 before relying.  |
//|   Does not touch or slow the trading EAs (own chart thread, bounded |
//|   batches, buffered append-close writes).                           |
//+------------------------------------------------------------------+
#property copyright "Aurvex / read-only collector"
#property version   "1.00"
#property strict
// NOTE: #include <Trade/Trade.mqh> is intentionally NOT included. This EA must
// never be able to send an order.

input string CollectSymbols      = "XAUUSD,XAGUSD,GER40.cash,JP225.cash"; // comma list
input int    TickTimerSeconds    = 1;      // how often to pull ticks (seconds)
input int    StateTimerSeconds   = 15;     // how often to snapshot account/positions/symbols
input int    TicksPerPollMax     = 5000;   // safety cap per symbol per poll
input int    HistoryBackfillDays = 60;     // on first start, backfill deals this many days
input long   OurMagic            = 770077; // tag deals/positions as "ours" (base Aurvex magic)
input string FilePrefix          = "AurvexCollector"; // CSV name prefix
input bool   VerboseHealth       = true;   // log flush/health details

//--- parsed symbols
string   g_syms[];
int      g_nSym=0;
//--- per-symbol tick cursor (restart-safe, persisted to checkpoint file)
long     g_lastMsc[];      // last tick time_msc written
int      g_lastMscCnt[];   // how many ticks at exactly g_lastMsc already written (dedup)
//--- deal cursor
ulong    g_lastDealTicket=0;
datetime g_lastStateSnap=0;
datetime g_curDay=0;
//--- write buffers (flushed append-close)
string   g_tickBuf[];      // one entry per line, prefixed "SYM\tLINE" so we route to the right file
int      g_tickBufN=0;
string   g_dealBuf[];
int      g_dealBufN=0;

//------------------------------- utils --------------------------------//
string DayStr(datetime t){ return TimeToString(t,TIME_DATE); } // yyyy.mm.dd
string DayTag(datetime t)
{
   MqlDateTime d; TimeToStruct(t,d);
   return StringFormat("%04d%02d%02d",d.year,d.mon,d.day);
}
string FileDir(){ return FilePrefix+"/"; }
string TickFile(string sym){ return FileDir()+"ticks_"+sym+"_"+DayTag(TimeGMT())+".csv"; }
string DealFile(){ return FileDir()+"deals_"+DayTag(TimeGMT())+".csv"; }
string PosFile(){ return FileDir()+"positions_"+DayTag(TimeGMT())+".csv"; }
string AcctFile(){ return FileDir()+"account_"+DayTag(TimeGMT())+".csv"; }
string SymFile(){ return FileDir()+"symbols_"+DayTag(TimeGMT())+".csv"; }
string HealthFile(){ return FileDir()+"health_"+DayTag(TimeGMT())+".csv"; }
string CheckpointFile(){ return FileDir()+"checkpoint.csv"; }

long NowMsc(){ return (long)TimeGMT()*1000; }   // collection timestamp (ms, UTC) best-effort

// append a single tab-separated line to a file, creating header if new.
// Robust (open-append-close); FILE_TXT so we write our own raw lines/separators.
void AppendLine(string file,string header,string line)
{
   int h=FileOpen(file,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI,'\t');
   if(h==INVALID_HANDLE){ Print("Collector: FileOpen failed ",file," err=",GetLastError()); return; }
   if(FileSize(h)==0) FileWriteString(h,header+"\r\n");
   FileSeek(h,0,SEEK_END);
   FileWriteString(h,line+"\r\n");
   FileClose(h);
}
void Health(string ev,string detail)
{
   AppendLine(HealthFile(),"collect_utc\tevent\tdetail",
              StringFormat("%s\t%s\t%s",TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),ev,detail));
   if(VerboseHealth) Print("Collector ",ev,": ",detail);
}

//------------------------------- checkpoint ---------------------------//
void SaveCheckpoint()
{
   int h=FileOpen(CheckpointFile(),FILE_WRITE|FILE_TXT|FILE_ANSI,'\t');
   if(h==INVALID_HANDLE) return;
   FileWriteString(h,"key\tvalue\r\n");
   for(int i=0;i<g_nSym;i++)
      FileWriteString(h,StringFormat("tick_%s\t%I64d:%d\r\n",g_syms[i],g_lastMsc[i],g_lastMscCnt[i]));
   FileWriteString(h,StringFormat("last_deal_ticket\t%I64u\r\n",g_lastDealTicket));
   FileClose(h);
}
void LoadCheckpoint()
{
   int h=FileOpen(CheckpointFile(),FILE_READ|FILE_TXT|FILE_ANSI,'\t');
   if(h==INVALID_HANDLE) return;   // first run: cursors stay 0
   bool first=true;
   while(!FileIsEnding(h))
   {
      string ln=FileReadString(h);          // FILE_TXT: one full line
      if(first){ first=false; continue; }   // skip header
      if(StringLen(ln)==0) continue;
      string f[]; if(StringSplit(ln,'\t',f)<2) continue;
      string k=f[0], v=f[1];
      if(StringFind(k,"tick_")==0)
      {
         string sym=StringSubstr(k,5);
         int idx=-1; for(int i=0;i<g_nSym;i++) if(g_syms[i]==sym){ idx=i; break; }
         if(idx>=0)
         {
            int colon=StringFind(v,":");
            if(colon>0){ g_lastMsc[idx]=(long)StringToInteger(StringSubstr(v,0,colon));
                         g_lastMscCnt[idx]=(int)StringToInteger(StringSubstr(v,colon+1)); }
         }
      }
      else if(k=="last_deal_ticket") g_lastDealTicket=(ulong)StringToInteger(v);
   }
   FileClose(h);
}

//------------------------------- ticks --------------------------------//
void PollTicks(int i)
{
   string sym=g_syms[i];
   MqlTick ticks[];
   ulong from=(g_lastMsc[i]>0)?(ulong)g_lastMsc[i]:(ulong)((long)(TimeGMT()-60)*1000);
   int n=CopyTicksRange(sym,ticks,COPY_TICKS_ALL,from,0);
   if(n<=0) return;
   int written=0, skipAtLast=g_lastMscCnt[i];
   for(int k=0;k<n && written<TicksPerPollMax;k++)
   {
      long msc=ticks[k].time_msc;
      if(msc<g_lastMsc[i]) continue;                          // older than cursor
      if(msc==g_lastMsc[i])                                   // same-ms: skip ones already written
      {
         if(skipAtLast>0){ skipAtLast--; continue; }
      }
      string line=StringFormat("%I64d\t%I64d\t%s\t%s\t%.8f\t%.8f\t%.8f\t%I64d\t%.4f\t%u",
         NowMsc(),msc,
         TimeToString(ticks[k].time,TIME_DATE|TIME_SECONDS),
         TimeToString((datetime)(msc/1000),TIME_DATE|TIME_SECONDS),
         ticks[k].bid,ticks[k].ask,ticks[k].last,
         (long)ticks[k].volume,ticks[k].volume_real,ticks[k].flags);
      AppendLine(TickFile(sym),
        "collect_msc\ttick_msc\tbroker_time\tutc_time\tbid\task\tlast\tvolume\tvolume_real\tflags",line);
      // advance cursor + same-ms counter
      if(msc>g_lastMsc[i]){ g_lastMsc[i]=msc; g_lastMscCnt[i]=1; }
      else g_lastMscCnt[i]++;
      written++;
   }
   if(written>0 && VerboseHealth && written>=TicksPerPollMax)
      Health("tick_cap",StringFormat("%s hit per-poll cap %d; will catch up next poll",sym,TicksPerPollMax));
}

//------------------------------- deals --------------------------------//
void WriteDeal(ulong tk)
{
   if(!HistoryDealSelect(tk)) return;
   long order =HistoryDealGetInteger(tk,DEAL_ORDER);
   long posid =HistoryDealGetInteger(tk,DEAL_POSITION_ID);
   long magic =HistoryDealGetInteger(tk,DEAL_MAGIC);
   string sym =HistoryDealGetString(tk,DEAL_SYMBOL);
   long dtype =HistoryDealGetInteger(tk,DEAL_TYPE);
   long entry =HistoryDealGetInteger(tk,DEAL_ENTRY);
   double vol =HistoryDealGetDouble(tk,DEAL_VOLUME);
   double price=HistoryDealGetDouble(tk,DEAL_PRICE);
   double comm =HistoryDealGetDouble(tk,DEAL_COMMISSION);
   double swap =HistoryDealGetDouble(tk,DEAL_SWAP);
   double fee  =HistoryDealGetDouble(tk,DEAL_FEE);
   double profit=HistoryDealGetDouble(tk,DEAL_PROFIT);
   string dtypeS=(dtype==DEAL_TYPE_BUY)?"buy":(dtype==DEAL_TYPE_SELL)?"sell":"other";
   string entryS=(entry==DEAL_ENTRY_IN)?"in":(entry==DEAL_ENTRY_OUT)?"out":
                 (entry==DEAL_ENTRY_INOUT)?"inout":(entry==DEAL_ENTRY_OUT_BY)?"out_by":"na";
   // collector CANNOT know the original planned SL or the trading EA version -> unknown
   string line=StringFormat("%s\t%I64u\t%I64d\t%I64d\t%I64d\t%s\t%s\t%s\t%.2f\t%.8f\t%s\t%.2f\t%.2f\t%.2f\t%.2f\t%s\t%s",
      TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),tk,order,posid,magic,sym,dtypeS,entryS,
      vol,price,"unknown",comm,swap,fee,profit,"unknown",
      (magic>=OurMagic && magic<=OurMagic+23)?"ours":"foreign");
   AppendLine(DealFile(),
     "collect_utc\tdeal_ticket\torder_ticket\tposition_id\tmagic\tsymbol\tdeal_type\tentry_type\tvolume\tprice\tsl_planned\tcommission\tswap\tfee\tprofit\tea_version\towner",line);
}
// reconcile: scan history since the last processed ticket's time window and write new deals
void ReconcileDeals(datetime fromGmt)
{
   long off=0; // deals are selected by SERVER time; use a wide window to be safe
   datetime fromSrv=(datetime)((long)fromGmt);
   if(!HistorySelect(fromSrv-86400,TimeTradeServer()+86400))
   { Health("deal_reconcile_fail","HistorySelect failed"); return; }
   int total=HistoryDealsTotal();
   ulong maxTk=g_lastDealTicket;
   for(int i=0;i<total;i++)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(tk==0 || tk<=g_lastDealTicket) continue;
      WriteDeal(tk);
      if(tk>maxTk) maxTk=tk;
   }
   if(maxTk>g_lastDealTicket){ g_lastDealTicket=maxTk; SaveCheckpoint(); }
}

//------------------------------- state snapshots ----------------------//
double OpenRiskEst()
{
   double tot=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      double sl=PositionGetDouble(POSITION_SL);
      if(sl<=0) continue;                           // unknown risk -> skip (not guessed)
      string sym=PositionGetString(POSITION_SYMBOL);
      double vol=PositionGetDouble(POSITION_VOLUME);
      long pt=PositionGetInteger(POSITION_TYPE);
      double cur=(pt==POSITION_TYPE_BUY)?SymbolInfoDouble(sym,SYMBOL_BID):SymbolInfoDouble(sym,SYMBOL_ASK);
      double pnl=0;
      ENUM_ORDER_TYPE side=(pt==POSITION_TYPE_BUY)?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      if(OrderCalcProfit(side,sym,vol,cur,sl,pnl)) tot+=(pnl<0?-pnl:0);
   }
   return tot;
}
void SnapshotAccount()
{
   string line=StringFormat("%s\t%s\t%s\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%d\t%s",
     TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),
     TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),
     TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),
     AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY),
     AccountInfoDouble(ACCOUNT_MARGIN),AccountInfoDouble(ACCOUNT_MARGIN_FREE),
     AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),OpenRiskEst(),
     (int)TerminalInfoInteger(TERMINAL_CONNECTED),AccountInfoString(ACCOUNT_SERVER));
   AppendLine(AcctFile(),
     "collect_utc\tbroker_time\tutc_time\tbalance\tequity\tmargin\tfree_margin\tmargin_level\topen_risk_est\tconnected\tserver",line);
}
void SnapshotPositions()
{
   string hdr="collect_utc\tticket\tposition_id\tmagic\tsymbol\tpos_type\tvolume\tprice_open\tsl\ttp\tprice_current\tswap\tprofit\towner";
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      long magic=PositionGetInteger(POSITION_MAGIC);
      long pt=PositionGetInteger(POSITION_TYPE);
      string line=StringFormat("%s\t%I64u\t%I64d\t%I64d\t%s\t%s\t%.2f\t%.8f\t%.8f\t%.8f\t%.8f\t%.2f\t%.2f\t%s",
        TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),tk,PositionGetInteger(POSITION_IDENTIFIER),magic,
        PositionGetString(POSITION_SYMBOL),(pt==POSITION_TYPE_BUY)?"buy":"sell",
        PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),
        PositionGetDouble(POSITION_SL),PositionGetDouble(POSITION_TP),
        PositionGetDouble(POSITION_PRICE_CURRENT),PositionGetDouble(POSITION_SWAP),
        PositionGetDouble(POSITION_PROFIT),
        (magic>=OurMagic && magic<=OurMagic+23)?"ours":"foreign");
      AppendLine(PosFile(),hdr,line);
   }
}
void SnapshotSymbols()
{
   string hdr="collect_utc\tsymbol\tpoint\tdigits\ttick_size\ttick_value\tvolume_min\tvolume_step\tvolume_max\tcurrency_profit\tspread_points\tstops_level\tfreeze_level";
   for(int i=0;i<g_nSym;i++)
   {
      string s=g_syms[i];
      string line=StringFormat("%s\t%s\t%.10f\t%d\t%.10f\t%.6f\t%.2f\t%.2f\t%.2f\t%s\t%d\t%d\t%d",
        TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),s,
        SymbolInfoDouble(s,SYMBOL_POINT),(int)SymbolInfoInteger(s,SYMBOL_DIGITS),
        SymbolInfoDouble(s,SYMBOL_TRADE_TICK_SIZE),SymbolInfoDouble(s,SYMBOL_TRADE_TICK_VALUE),
        SymbolInfoDouble(s,SYMBOL_VOLUME_MIN),SymbolInfoDouble(s,SYMBOL_VOLUME_STEP),
        SymbolInfoDouble(s,SYMBOL_VOLUME_MAX),SymbolInfoString(s,SYMBOL_CURRENCY_PROFIT),
        (int)SymbolInfoInteger(s,SYMBOL_SPREAD),
        (int)SymbolInfoInteger(s,SYMBOL_TRADE_STOPS_LEVEL),(int)SymbolInfoInteger(s,SYMBOL_TRADE_FREEZE_LEVEL));
      AppendLine(SymFile(),hdr,line);
   }
}

//------------------------------- lifecycle ----------------------------//
int OnInit()
{
   // parse symbols
   string parts[]; int n=StringSplit(CollectSymbols,',',parts);
   if(n<=0){ Print("Collector: no symbols"); return INIT_PARAMETERS_INCORRECT; }
   ArrayResize(g_syms,n); ArrayResize(g_lastMsc,n); ArrayResize(g_lastMscCnt,n);
   g_nSym=0;
   for(int i=0;i<n;i++)
   {
      string s=parts[i]; StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s)==0) continue;
      g_syms[g_nSym]=s; g_lastMsc[g_nSym]=0; g_lastMscCnt[g_nSym]=0;
      SymbolSelect(s,true);
      g_nSym++;
   }
   ArrayResize(g_syms,g_nSym);
   LoadCheckpoint();
   g_curDay=UtcDayStart0(TimeGMT());
   // backfill deals on first start
   ReconcileDeals(TimeGMT()-(datetime)HistoryBackfillDays*86400);
   SnapshotSymbols();
   SnapshotAccount();
   int sec=MathMax(1,TickTimerSeconds);
   EventSetTimer(sec);
   Health("start",StringFormat("symbols=%d backfillDays=%d tickTimer=%ds",g_nSym,HistoryBackfillDays,sec));
   return INIT_SUCCEEDED;
}
datetime UtcDayStart0(datetime t){ return (datetime)((long)t/86400*86400); }

void OnDeinit(const int reason){ SaveCheckpoint(); EventKillTimer(); Health("stop","reason="+(string)reason); }

void OnTimer()
{
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
   { Health("disconnected","terminal not connected; will resume"); return; }
   // daily rollover marker
   datetime day=UtcDayStart0(TimeGMT());
   if(day!=g_curDay){ g_curDay=day; SnapshotSymbols(); Health("day_rollover",DayTag(TimeGMT())); }
   // ticks for all symbols
   for(int i=0;i<g_nSym;i++) PollTicks(i);
   SaveCheckpoint();
   // periodic state snapshot
   if(TimeGMT()-g_lastStateSnap>=StateTimerSeconds)
   {
      SnapshotAccount(); SnapshotPositions();
      ReconcileDeals(TimeGMT()-2*86400);   // rolling reconcile window for missed events
      g_lastStateSnap=TimeGMT();
   }
}
// capture fills immediately (collector sees ALL account deals, not just this chart)
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(trans.deal<=g_lastDealTicket) return;
   WriteDeal(trans.deal);
   g_lastDealTicket=trans.deal;
   SaveCheckpoint();
}
//+------------------------------------------------------------------+
