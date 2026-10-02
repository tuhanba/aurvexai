//+------------------------------------------------------------------+
//| AurvexCollector.mq5  — READ-ONLY live data collector (v1.2)       |
//| v1.2 (review): per-ms tick SEQ for crash-replay dedup; FILE_SHARE  |
//|   flags for concurrent reads; AppendBatch verifies the FULL write  |
//|   and newline-terminates a partial tail; checkpoint written to a    |
//|   temp file then atomically moved (recovery from .tmp); ticks read  |
//|   in a FINITE window with a backlog cursor that advances even on    |
//|   empty windows; output under a versioned subfolder (v12).          |
//| Runs on a SEPARATE (5th) chart alongside the trading EAs.          |
//| Collects ticks + deals/positions + account/symbol state for the    |
//| four symbols into daily CSVs (MQL5/Files). ZERO trade authority:    |
//| no CTrade, no OrderSend, no position/pending functions.             |
//| ⚠ UNCOMPILED SKELETON — F7 compile + verify in MT5 before relying.  |
//|                                                                    |
//| v1.1 corrections (Sprint-1 review):                                 |
//|  - tick cursor: start (msc,count) held CONSTANT during the scan;    |
//|    the NEW cursor is computed separately; ALL same-ms ticks kept.   |
//|  - cursor/checkpoint advance ONLY after a verified batch write.     |
//|  - ticks read in bounded ranges, written in one batch per poll.     |
//|  - deals: overlap scan + ticket dedup; read via HistoryDealGet*     |
//|    (ticket form) WITHOUT HistoryDealSelect, so the history list is   |
//|    never reset mid-scan; a delayed small ticket is NOT skipped.      |
//|  - DEAL_TIME_MSC captured (report is by execution time).            |
//|  - open risk that can't be computed (no SL / calc fail) -> unknown. |
//+------------------------------------------------------------------+
#property copyright "Aurvex / read-only collector"
#property version   "1.20"
#property strict
#define COLLECTOR_SCHEMA "1.2"
// #include <Trade/Trade.mqh> intentionally OMITTED — this EA can never trade.

input string CollectSymbols      = "XAUUSD,XAGUSD,GER40.cash,JP225.cash";
input int    TickTimerSeconds    = 1;      // tick poll period (s)
input int    StateTimerSeconds   = 15;     // account/positions/symbols snapshot period (s)
input int    TicksPerPollMax     = 5000;   // bounded: max ticks written per symbol per window
input int    TickMaxLookbackSec  = 120;    // first/empty-cursor read starts this far back
input int    TickWindowSec       = 300;    // FINITE CopyTicksRange window (s) — never "all history" at once
input int    MaxWindowsPerPoll   = 6;      // catch backlog over several bounded windows per poll
input int    HistoryBackfillDays = 60;     // first start: backfill deals this many days
input int    ReconcileOverlapDays= 3;      // re-scan this overlap each reconcile (dedup handles repeats)
input long   OurMagic            = 770077; // tag deals/positions as "ours" (base Aurvex magic)
input string FilePrefix          = "AurvexCollector";
input bool   VerboseHealth       = true;

string   g_syms[]; int g_nSym=0;
long     g_lastMsc[];      // per-symbol tick cursor: last written tick time_msc
int      g_lastMscCnt[];   // how many ticks at exactly g_lastMsc already written (dedup)
long     g_lastDealTimeMsc=0;   // reconcile anchor (max deal execution time processed)
ulong    g_seen[]; int g_seenN=0;  // in-session written deal tickets (sorted) for dedup
datetime g_lastStateSnap=0;
datetime g_curDay=0;

//------------------------------- time/util ----------------------------//
datetime UtcDayStart0(datetime t){ return (datetime)((long)t/86400*86400); }
string DayTag(datetime t){ MqlDateTime d; TimeToStruct(t,d); return StringFormat("%04d%02d%02d",d.year,d.mon,d.day); }
// v1.2: output under a versioned subfolder so the changed schema NEVER mixes with
// v1.0/v1.1 files. Migration = start fresh here; do not append to old files.
string FileDir(){ return FilePrefix+"/v12/"; }
string TickFile(string sym){ return FileDir()+"ticks_"+sym+"_"+DayTag(TimeGMT())+".csv"; }
string DealFile(){ return FileDir()+"deals_"+DayTag(TimeGMT())+".csv"; }
string PosFile(){ return FileDir()+"positions_"+DayTag(TimeGMT())+".csv"; }
string AcctFile(){ return FileDir()+"account_"+DayTag(TimeGMT())+".csv"; }
string SymFile(){ return FileDir()+"symbols_"+DayTag(TimeGMT())+".csv"; }
string HealthFile(){ return FileDir()+"health_"+DayTag(TimeGMT())+".csv"; }
string CheckpointFile(){ return FileDir()+"checkpoint.csv"; }
long NowMsc(){ return (long)TimeGMT()*1000; }

const string TICK_HDR="collect_msc\ttick_msc\tseq\tbroker_time\tutc_time\tbid\task\tlast\tvolume\tvolume_real\tflags";
const string DEAL_HDR="collect_utc\tdeal_time_msc\tdeal_ticket\torder_ticket\tposition_id\tmagic\tsymbol\tdeal_type\tentry_type\tvolume\tprice\tsl_planned\tcommission\tswap\tfee\tprofit\tea_version\towner";
const string POS_HDR="collect_utc\tticket\tposition_id\tmagic\tsymbol\tpos_type\tvolume\tprice_open\tsl\ttp\tprice_current\tswap\tprofit\towner";
const string ACCT_HDR="collect_utc\tbroker_time\tutc_time\tbalance\tequity\tmargin\tfree_margin\tmargin_level\topen_risk_est\topen_risk_known\tconnected\tserver";
const string SYM_HDR="collect_utc\tsymbol\tpoint\tdigits\ttick_size\ttick_value\tvolume_min\tvolume_step\tvolume_max\tcurrency_profit\tspread_points\tstops_level\tfreeze_level";

// verified write: returns true only if the FULL payload was written+flushed.
// FILE_SHARE_READ|WRITE lets the Python importer read while we write. On a partial
// write (e.g. disk full) we terminate the broken tail with a newline so the importer
// treats it as one malformed line (skipped) rather than merging it into the next batch,
// and we return false so the cursor is NOT advanced (the batch is retried next poll;
// re-written ticks are deduped by (symbol,tick_msc,seq)).
bool AppendBatch(string file,string header,string payload)
{
   if(StringLen(payload)==0) return true;
   int h=FileOpen(file,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE){ Print("Collector FileOpen fail ",file," err=",GetLastError()); return false; }
   if(FileSize(h)==0) FileWriteString(h,header+"\r\n");
   FileSeek(h,0,SEEK_END);
   uint want=(uint)StringLen(payload);
   uint w=FileWriteString(h,payload);
   if(w<want) FileWriteString(h,"\r\n");   // close the corrupt partial line
   FileFlush(h);
   FileClose(h);
   return (w>=want);
}
void AppendLine(string file,string header,string line){ AppendBatch(file,header,line+"\r\n"); }
void Health(string ev,string detail)
{
   AppendLine(HealthFile(),"collect_utc\tevent\tdetail",
              StringFormat("%s\t%s\t%s",TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),ev,detail));
   if(VerboseHealth) Print("Collector ",ev,": ",detail);
}

//------------------------------- checkpoint ---------------------------//
// atomic checkpoint: write to a temp file, verify non-empty, then FileMove over the
// real file. On restart LoadCheckpoint recovers from the .tmp if a move was interrupted.
void SaveCheckpoint()
{
   string tmp=CheckpointFile()+".tmp";
   int h=FileOpen(tmp,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return;
   FileWriteString(h,"schema\t"+COLLECTOR_SCHEMA+"\r\n");
   for(int i=0;i<g_nSym;i++)
      FileWriteString(h,StringFormat("tick_%s\t%I64d:%d\r\n",g_syms[i],g_lastMsc[i],g_lastMscCnt[i]));
   FileWriteString(h,StringFormat("last_deal_time_msc\t%I64d\r\n",g_lastDealTimeMsc));
   FileFlush(h);
   ulong sz=FileSize(h);
   FileClose(h);
   if(sz==0){ FileDelete(tmp); return; }                 // never replace with an empty file
   if(!FileMove(tmp,0,CheckpointFile(),FILE_REWRITE))
      Print("Collector checkpoint move failed err=",GetLastError());
}
void LoadCheckpoint()
{
   int h=FileOpen(CheckpointFile(),FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE)
   {   // recovery: a crash between temp-write and move may leave only the .tmp
      h=FileOpen(CheckpointFile()+".tmp",FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
      if(h==INVALID_HANDLE) return;
   }
   while(!FileIsEnding(h))
   {
      string ln=FileReadString(h);
      if(StringLen(ln)==0) continue;
      string f[]; if(StringSplit(ln,'\t',f)<2) continue;
      string k=f[0], v=f[1];
      if(k=="schema"){ if(v!=COLLECTOR_SCHEMA) Health("checkpoint_schema",v); continue; }
      if(StringFind(k,"tick_")==0)
      {
         string sym=StringSubstr(k,5);
         for(int i=0;i<g_nSym;i++) if(g_syms[i]==sym)
         {
            int colon=StringFind(v,":");
            if(colon>0){ g_lastMsc[i]=(long)StringToInteger(StringSubstr(v,0,colon));
                         g_lastMscCnt[i]=(int)StringToInteger(StringSubstr(v,colon+1)); }
            break;
         }
      }
      else if(k=="last_deal_time_msc") g_lastDealTimeMsc=(long)StringToInteger(v);
   }
   FileClose(h);
}

//------------------------------- ticks --------------------------------//
// One bounded window. Returns: 1 = wrote ticks, 0 = empty window (cursor advanced past
// the gap), -1 = CopyTicks error or write failed (cursor unchanged), 2 = caught up.
int PollTicksWindow(int i)
{
   string sym=g_syms[i];
   long nowMs=NowMsc();
   long startMsc=g_lastMsc[i]; int startCnt=g_lastMscCnt[i];   // CONSTANT during this scan
   long fromMs=(startMsc>0)?startMsc:(nowMs-(long)TickMaxLookbackSec*1000);
   long toMs=MathMin(nowMs,fromMs+(long)TickWindowSec*1000);   // FINITE window
   if(toMs<=startMsc && startMsc>0) return 2;                  // nothing more to read now
   MqlTick ticks[];
   int n=CopyTicksRange(sym,ticks,COPY_TICKS_ALL,(ulong)fromMs,(ulong)toMs);
   if(n<0){ Health("tick_copy_err",StringFormat("%s err=%d",sym,GetLastError())); return -1; }
   long newMsc=startMsc; int newCnt=startCnt;                  // computed SEPARATELY
   int skip=startCnt, written=0;
   string batch="";
   for(int k=0;k<n && written<TicksPerPollMax;k++)
   {
      long msc=ticks[k].time_msc;
      if(msc<startMsc) continue;
      if(msc==startMsc && skip>0){ skip--; continue; }
      int seq;
      if(msc>newMsc){ newMsc=msc; newCnt=0; }                  // new ms -> seq restarts at 0
      seq=newCnt; newCnt++;                                    // 0-based index within this ms
      batch+=StringFormat("%I64d\t%I64d\t%d\t%s\t%s\t%.8f\t%.8f\t%.8f\t%I64d\t%.4f\t%u\r\n",
         NowMsc(),msc,seq,
         TimeToString(ticks[k].time,TIME_DATE|TIME_SECONDS),
         TimeToString((datetime)(msc/1000),TIME_DATE|TIME_SECONDS),
         ticks[k].bid,ticks[k].ask,ticks[k].last,
         (long)ticks[k].volume,ticks[k].volume_real,ticks[k].flags);
      written++;
   }
   if(written>0)
   {
      if(!AppendBatch(TickFile(sym),TICK_HDR,batch)){ Health("tick_write_fail",sym); return -1; }
      g_lastMsc[i]=newMsc; g_lastMscCnt[i]=newCnt;             // advance ONLY after verified write
      return (toMs>=nowMs)?2:1;
   }
   // empty window: advance the cursor past the gap so scanning still progresses
   if(toMs>startMsc){ g_lastMsc[i]=toMs; g_lastMscCnt[i]=0; }
   return (toMs>=nowMs)?2:0;
}
void PollTicks(int i)
{
   for(int w=0;w<MaxWindowsPerPoll;w++)
   {
      int r=PollTicksWindow(i);
      if(r==-1 || r==2) break;   // error (retry next poll) or caught up to present
      // r==1 (wrote, more to read) or r==0 (empty window, advanced): keep clearing backlog
   }
}

//------------------------------- deals (overlap + dedup) --------------//
bool SeenTicket(ulong tk)
{
   int lo=0,hi=g_seenN-1;
   while(lo<=hi){ int mid=(lo+hi)/2; if(g_seen[mid]==tk) return true; if(g_seen[mid]<tk) lo=mid+1; else hi=mid-1; }
   return false;
}
void AddSeenTicket(ulong tk)
{
   if(g_seenN>=ArraySize(g_seen)) ArrayResize(g_seen,g_seenN+256);
   int lo=0,hi=g_seenN-1;
   while(lo<=hi){ int mid=(lo+hi)/2; if(g_seen[mid]<tk) lo=mid+1; else hi=mid-1; }
   for(int i=g_seenN;i>lo;i--) g_seen[i]=g_seen[i-1];
   g_seen[lo]=tk; g_seenN++;
}
// reads via HistoryDealGet*(ticket,...) — requires the ticket to be inside the active
// HistorySelect() range; does NOT call HistoryDealSelect (no list reset). Returns true
// if the row was written (so the caller marks the ticket seen only on success).
bool WriteDealByTicket(ulong tk)
{
   long tmsc  =HistoryDealGetInteger(tk,DEAL_TIME_MSC);
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
   if(StringLen(sym)==0 && vol<=0) return false;   // not a tradable deal (balance op etc.) -> skip
   string dtypeS=(dtype==DEAL_TYPE_BUY)?"buy":(dtype==DEAL_TYPE_SELL)?"sell":"other";
   string entryS=(entry==DEAL_ENTRY_IN)?"in":(entry==DEAL_ENTRY_OUT)?"out":
                 (entry==DEAL_ENTRY_INOUT)?"inout":(entry==DEAL_ENTRY_OUT_BY)?"out_by":"na";
   // original planned SL and trading-EA version are NOT observable here -> unknown (not guessed)
   string line=StringFormat("%s\t%I64d\t%I64u\t%I64d\t%I64d\t%I64d\t%s\t%s\t%s\t%.2f\t%.8f\t%s\t%.2f\t%.2f\t%.2f\t%.2f\t%s\t%s",
      TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),tmsc,tk,order,posid,magic,sym,dtypeS,entryS,
      vol,price,"unknown",comm,swap,fee,profit,"unknown",
      (magic>=OurMagic && magic<=OurMagic+23)?"ours":"foreign");
   bool ok=AppendBatch(DealFile(),DEAL_HDR,line+"\r\n");
   if(ok && tmsc>g_lastDealTimeMsc) g_lastDealTimeMsc=tmsc;
   return ok;
}
void ReconcileDeals(datetime fromGmt)
{
   datetime from=fromGmt-(datetime)ReconcileOverlapDays*86400;
   if(!HistorySelect(from,TimeTradeServer()+86400)){ Health("deal_reconcile_fail","HistorySelect"); return; }
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)                        // index order; do NOT reset the list
   {
      ulong tk=HistoryDealGetTicket(i);
      if(tk==0 || SeenTicket(tk)) continue;        // dedup: a repeat in the overlap is skipped
      if(WriteDealByTicket(tk)) AddSeenTicket(tk);  // a delayed SMALL ticket is still captured
   }
   SaveCheckpoint();
}

//------------------------------- state snapshots ----------------------//
double OpenRiskEst(bool &known)
{
   known=true; double tot=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i); if(tk==0) continue;
      double sl=PositionGetDouble(POSITION_SL);
      if(sl<=0){ known=false; continue; }          // uncomputable -> mark unknown (not guessed)
      string sym=PositionGetString(POSITION_SYMBOL);
      double vol=PositionGetDouble(POSITION_VOLUME);
      long pt=PositionGetInteger(POSITION_TYPE);
      double cur=(pt==POSITION_TYPE_BUY)?SymbolInfoDouble(sym,SYMBOL_BID):SymbolInfoDouble(sym,SYMBOL_ASK);
      double pnl=0; ENUM_ORDER_TYPE side=(pt==POSITION_TYPE_BUY)?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
      if(OrderCalcProfit(side,sym,vol,cur,sl,pnl)) tot+=(pnl<0?-pnl:0); else known=false;
   }
   return tot;
}
void SnapshotAccount()
{
   bool known; double risk=OpenRiskEst(known);
   string line=StringFormat("%s\t%s\t%s\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%.2f\t%d\t%d\t%s",
     TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),
     TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),
     TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),
     AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY),
     AccountInfoDouble(ACCOUNT_MARGIN),AccountInfoDouble(ACCOUNT_MARGIN_FREE),
     AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),risk,(known?1:0),
     (int)TerminalInfoInteger(TERMINAL_CONNECTED),AccountInfoString(ACCOUNT_SERVER));
   AppendLine(AcctFile(),ACCT_HDR,line);
}
void SnapshotPositions()
{
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
      AppendLine(PosFile(),POS_HDR,line);
   }
}
void SnapshotSymbols()
{
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
      AppendLine(SymFile(),SYM_HDR,line);
   }
}

//------------------------------- lifecycle ----------------------------//
int OnInit()
{
   string parts[]; int n=StringSplit(CollectSymbols,',',parts);
   if(n<=0){ Print("Collector: no symbols"); return INIT_PARAMETERS_INCORRECT; }
   ArrayResize(g_syms,n); ArrayResize(g_lastMsc,n); ArrayResize(g_lastMscCnt,n);
   g_nSym=0;
   for(int i=0;i<n;i++)
   {
      string s=parts[i]; StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s)==0) continue;
      g_syms[g_nSym]=s; g_lastMsc[g_nSym]=0; g_lastMscCnt[g_nSym]=0;
      SymbolSelect(s,true); g_nSym++;
   }
   ArrayResize(g_syms,g_nSym);
   LoadCheckpoint();
   g_curDay=UtcDayStart0(TimeGMT());
   datetime dealFrom=(g_lastDealTimeMsc>0)?(datetime)(g_lastDealTimeMsc/1000):(TimeGMT()-(datetime)HistoryBackfillDays*86400);
   ReconcileDeals(dealFrom);
   SnapshotSymbols(); SnapshotAccount();
   EventSetTimer(MathMax(1,TickTimerSeconds));
   Health("start",StringFormat("symbols=%d backfillDays=%d overlapDays=%d",g_nSym,HistoryBackfillDays,ReconcileOverlapDays));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ SaveCheckpoint(); EventKillTimer(); Health("stop","reason="+(string)reason); }

void OnTimer()
{
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED)){ Health("disconnected","not connected; will resume"); return; }
   datetime day=UtcDayStart0(TimeGMT());
   if(day!=g_curDay){ g_curDay=day; SnapshotSymbols(); Health("day_rollover",DayTag(TimeGMT())); }
   for(int i=0;i<g_nSym;i++) PollTicks(i);
   SaveCheckpoint();
   if(TimeGMT()-g_lastStateSnap>=StateTimerSeconds)
   {
      SnapshotAccount(); SnapshotPositions();
      datetime anchor=(g_lastDealTimeMsc>0)?(datetime)(g_lastDealTimeMsc/1000):(TimeGMT()-(datetime)ReconcileOverlapDays*86400);
      ReconcileDeals(anchor);
      g_lastStateSnap=TimeGMT();
   }
}
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(SeenTicket(trans.deal)) return;
   // make the deal readable by ticket via a bounded HistorySelect (not HistoryDealSelect)
   if(!HistorySelect(TimeTradeServer()-86400,TimeTradeServer()+86400)) return;
   if(WriteDealByTicket(trans.deal)){ AddSeenTicket(trans.deal); SaveCheckpoint(); }
}
//+------------------------------------------------------------------+
