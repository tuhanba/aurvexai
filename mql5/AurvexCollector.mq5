//+------------------------------------------------------------------+
//| AurvexCollector.mq5  — READ-ONLY live data collector (v1.3)       |
//| v1.3 (resilience review): STRICT checkpoint load (validate main,  |
//|   else validated .tmp, else fresh cursors) + startup cursor LOG;   |
//|   lost/corrupt .commit sidecar NO LONGER trusts the whole file —   |
//|   committed length is rebuilt to the last well-formed record and   |
//|   the partial tail dropped; tick clock base VALIDATED before any    |
//|   UTC conversion or deal-history read; write failures logged with   |
//|   file+phase+errcode; disconnects reported as start/end+duration;   |
//|   resume/coverage tick gaps reported (span+duration+kind). CSV      |
//|   schema UNCHANGED (still "1.2"). NOT PASS until F7 compile + MT5.   |
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
#property version   "1.30"
#property strict
#define COLLECTOR_SCHEMA "1.2"   // CSV schema UNCHANGED since v1.2; only collector resilience changed
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
input int    GapWarnSec          = 300;    // report a tick-coverage gap longer than this (s)
input bool   VerboseHealth       = true;

string   g_syms[]; int g_nSym=0;
long     g_lastMsc[];      // per-symbol tick cursor: last written tick time_msc
int      g_lastMscCnt[];   // how many ticks at exactly g_lastMsc already written (dedup)
long     g_lastDealTimeMsc=0;   // reconcile anchor (max deal execution time processed)
ulong    g_seen[]; int g_seenN=0;  // in-session written deal tickets (sorted) for dedup
datetime g_lastStateSnap=0;
datetime g_curDay=0;
bool     g_clockOk=false;       // tick clock base validated (no UTC/history work until true)
long     g_clockOffsetSec=0;    // measured TimeTradeServer - TimeGMT (server <-> GMT)
datetime g_disconnectSince=0;   // >0 while disconnected: start of the current outage

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

// Validate the tick clock base BEFORE any UTC conversion or deal-history operation. We require
// a sane GMT and trade-server clock and a plausible GMT<->server offset. If it cannot be
// validated we do NOT convert tick times to UTC and do NOT touch historical data — the caller
// waits and re-checks on the next timer. (Records the measured offset for the analysis layer.)
bool ValidateClockBase()
{
   datetime g=TimeGMT(), s=TimeTradeServer();
   if(g<=0 || s<=0) return false;                       // clock not established yet
   long off=(long)s-(long)g;
   if(off>14*3600 || off<-14*3600) return false;        // implausible timezone offset
   g_clockOffsetSec=off;
   return true;
}

const string TICK_HDR="collect_msc\ttick_msc\tseq\tbroker_time\tutc_time\tbid\task\tlast\tvolume\tvolume_real\tflags";
const string DEAL_HDR="collect_utc\tdeal_time_msc\tdeal_ticket\torder_ticket\tposition_id\tmagic\tsymbol\tdeal_type\tentry_type\tvolume\tprice\tsl_planned\tcommission\tswap\tfee\tprofit\tea_version\towner";
const string POS_HDR="collect_utc\tticket\tposition_id\tmagic\tsymbol\tpos_type\tvolume\tprice_open\tsl\ttp\tprice_current\tswap\tprofit\towner";
const string ACCT_HDR="collect_utc\tbroker_time\tutc_time\tbalance\tequity\tmargin\tfree_margin\tmargin_level\topen_risk_est\topen_risk_known\tconnected\tserver";
const string SYM_HDR="collect_utc\tsymbol\tpoint\tdigits\ttick_size\ttick_value\tvolume_min\tvolume_step\tvolume_max\tcurrency_profit\tspread_points\tstops_level\tfreeze_level";

// --- committed-length (staging/commit) protocol -----------------------------
// A data file is only ever read by the importer UP TO its committed length, held in a
// "<file>.commit" sidecar. A batch is written at the committed offset (overwriting any
// uncommitted tail left by a prior failed write); only after the FULL payload is written
// is .commit advanced. So a partially-written batch — even one that happens to end with a
// full column count — stays BEYOND .commit and is never published to the importer. We
// never append a newline to a partial payload to make it "look valid".
long ReadCommit(string cf)
{
   int h=FileOpen(cf,FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return -1;
   string s=(FileIsEnding(h)?"":FileReadString(h));
   FileClose(h);
   return (StringLen(s)>0)?(long)StringToInteger(s):-1;
}
bool WriteCommitAtomic(string cf,long val)
{
   string tmp=cf+".tmp";
   int h=FileOpen(tmp,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return false;
   FileWriteString(h,IntegerToString(val));
   FileFlush(h); FileClose(h);
   return FileMove(tmp,0,cf,FILE_REWRITE);
}
// When the .commit sidecar is MISSING or CORRUPT we must NOT assume the whole existing file is
// valid (a crash/reset can leave a half-written tail). Rebuild the committed length as the end
// of the last run of well-formed, newline-terminated records (header column count) FROM THE
// START; scanning stops at the first malformed/short line, so a partial or corrupt tail is left
// uncommitted and is overwritten by the next batch. Returns 0 if not even one valid line exists.
long RebuildCommitLength(string file,string header)
{
   int cols=1; for(int i=0;i<StringLen(header);i++) if(StringGetCharacter(header,i)=='\t') cols++;
   int h=FileOpen(file,FILE_READ|FILE_BIN|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return 0;
   long sz=(long)FileSize(h);
   if(sz<=0){ FileClose(h); return 0; }
   uchar buf[]; int got=FileReadArray(h,buf,0,(int)sz); FileClose(h);
   long good=0; int fields=1;
   for(int p=0;p<got;p++)
   {
      uchar c=buf[p];
      if(c=='\t') fields++;
      else if(c=='\n')
      {
         if(fields==cols){ good=p+1; fields=1; }   // a complete, correctly-shaped line
         else break;                               // malformed/short line -> stop; tail is uncommitted
      }
   }
   return good;
}
bool AppendBatch(string file,string header,string payload)
{
   if(StringLen(payload)==0) return true;
   string cf=file+".commit";
   long committed=ReadCommit(cf);
   int h=FileOpen(file,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE){ Health("write_fail",StringFormat("file=%s phase=open err=%d",file,GetLastError())); return false; }
   if(committed<0)
   {   // new file, or lost/corrupt sidecar
      if(FileSize(h)==0){ FileWriteString(h,header+"\r\n"); committed=(long)FileSize(h); }
      else
      {   // sidecar gone but the file has content: rebuild to the last valid record (never trust the whole file)
         long rb=RebuildCommitLength(file,header);
         if(rb<=0){ FileSeek(h,0,SEEK_SET); string hh=header+"\r\n"; FileWriteString(h,hh); rb=(long)StringLen(hh); }
         committed=rb;
         Health("commit_rebuilt",StringFormat("file=%s size=%I64d committed=%I64d (sidecar lost/corrupt; partial tail dropped)",
                file,(long)FileSize(h),committed));
         WriteCommitAtomic(cf,committed);
      }
   }
   if(!FileSeek(h,committed,SEEK_SET)){ Health("write_fail",StringFormat("file=%s phase=seek off=%I64d err=%d",file,committed,GetLastError())); FileClose(h); return false; }
   uint want=(uint)StringLen(payload);
   uint w=FileWriteString(h,payload);
   int werr=GetLastError();
   FileFlush(h);
   FileClose(h);
   if(w<want){ Health("write_fail",StringFormat("file=%s phase=write wrote=%u want=%u err=%d",file,w,want,werr)); return false; }  // partial: .commit NOT advanced -> batch hidden, retried
   if(!WriteCommitAtomic(cf,committed+(long)want)){ Health("write_fail",StringFormat("file=%s phase=commit err=%d",file,GetLastError())); return false; }
   return true;
}
void AppendLine(string file,string header,string line){ AppendBatch(file,header,line+"\r\n"); }
void Health(string ev,string detail)
{
   AppendLine(HealthFile(),"collect_utc\tevent\tdetail",
              StringFormat("%s\t%s\t%s",TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),ev,detail));
   if(VerboseHealth) Print("Collector ",ev,": ",detail);
}

//------------------------------- checkpoint ---------------------------//
// validate a checkpoint file: correct schema line, a tick_ entry for EVERY configured
// symbol, and the last_deal_time_msc line. A temp that fails this must NOT replace the
// last good checkpoint. (Content/schema/symbol-completeness, not just non-empty.)
bool ValidateCheckpointFile(string path)
{
   int h=FileOpen(path,FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return false;
   bool schemaOk=false, dealOk=false; int tickCount=0;
   while(!FileIsEnding(h))
   {
      string ln=FileReadString(h); if(StringLen(ln)==0) continue;
      string f[]; if(StringSplit(ln,'\t',f)<2) continue;
      if(f[0]=="schema") schemaOk=(f[1]==COLLECTOR_SCHEMA);
      else if(StringFind(f[0],"tick_")==0)
      {
         string sym=StringSubstr(f[0],5);
         for(int i=0;i<g_nSym;i++) if(g_syms[i]==sym){ tickCount++; break; }
      }
      else if(f[0]=="last_deal_time_msc") dealOk=true;
   }
   FileClose(h);
   return (schemaOk && dealOk && tickCount==g_nSym);
}
// atomic checkpoint: write temp -> VALIDATE full content -> FileMove over the real file.
// An invalid/incomplete temp is deleted and the last good checkpoint is left intact.
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
   FileClose(h);
   if(!ValidateCheckpointFile(tmp))                       // reject an invalid temp
   { FileDelete(tmp); Health("checkpoint_invalid","temp failed validation; kept last good"); return; }
   if(!FileMove(tmp,0,CheckpointFile(),FILE_REWRITE))
      Print("Collector checkpoint move failed err=",GetLastError());
}
void LogCursors(string ctx)
{   // log the per-symbol cursors actually loaded at startup (and the deal anchor)
   for(int i=0;i<g_nSym;i++)
      Health("cursor",StringFormat("%s %s=%I64d:%d",ctx,g_syms[i],g_lastMsc[i],g_lastMscCnt[i]));
   Health("cursor",StringFormat("%s last_deal_time_msc=%I64d",ctx,g_lastDealTimeMsc));
}
void ParseCheckpoint(string path)
{
   int h=FileOpen(path,FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
   if(h==INVALID_HANDLE) return;
   while(!FileIsEnding(h))
   {
      string ln=FileReadString(h);
      if(StringLen(ln)==0) continue;
      string f[]; if(StringSplit(ln,'\t',f)<2) continue;
      string k=f[0], v=f[1];
      if(k=="schema") continue;                 // already validated by ValidateCheckpointFile
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
// STRICT load: a checkpoint is used only if it passes full validation (schema + a cursor for
// EVERY configured symbol + the deal anchor). The main file is tried first, then the .tmp
// (crash between temp-write and move). If NEITHER validates we start every cursor at 0 rather
// than loading a partial/stale cursor set. The loaded cursors are logged.
void LoadCheckpoint()
{
   string main=CheckpointFile(), tmp=CheckpointFile()+".tmp";
   if(ValidateCheckpointFile(main)){ ParseCheckpoint(main); LogCursors("loaded(checkpoint)"); return; }
   if(ValidateCheckpointFile(tmp))
   { Health("checkpoint_recovered","main missing/invalid; loaded validated .tmp");
     ParseCheckpoint(tmp); LogCursors("loaded(.tmp)"); return; }
   Health("checkpoint_fresh","no VALID checkpoint — all tick cursors start at 0 (full back-read)");
   LogCursors("fresh");
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
   int skip=startCnt, written=0; long firstMsc=-1;
   string batch="";
   for(int k=0;k<n && written<TicksPerPollMax;k++)
   {
      long msc=ticks[k].time_msc;
      if(msc<startMsc) continue;
      if(msc==startMsc && skip>0){ skip--; continue; }
      if(firstMsc<0) firstMsc=msc;                             // earliest tick the broker served
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
      // resume coverage gap: the earliest tick served is well AFTER our cursor -> the span in
      // between is not in the broker's tick store (e.g. after a reset). Report it with span/duration;
      // we advance past it, so it is a permanent (unrecoverable) hole in coverage.
      if(startMsc>0 && firstMsc>startMsc && (firstMsc-startMsc)>(long)GapWarnSec*1000)
         Health("tick_gap",StringFormat("%s from_msc=%I64d to_msc=%I64d dur_s=%I64d kind=unrecoverable(no-broker-ticks)",
                sym,startMsc,firstMsc,(firstMsc-startMsc)/1000));
      g_lastMsc[i]=newMsc; g_lastMscCnt[i]=newCnt;             // advance ONLY after verified write
      return (toMs>=nowMs)?2:1;
   }
   // empty window: advance the cursor past the gap so scanning still progresses. If this window
   // lies in the past (not the live edge) and is longer than GapWarnSec, report the skipped span
   // (cause — weekend/closed vs truly missing — is for the analysis layer, not asserted here).
   if(startMsc>0 && (toMs-startMsc)>(long)GapWarnSec*1000 && toMs<nowMs-(long)GapWarnSec*1000)
      Health("tick_gap",StringFormat("%s from_msc=%I64d to_msc=%I64d dur_s=%I64d kind=empty-window",
             sym,startMsc,toMs,(toMs-startMsc)/1000));
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
   // validate the clock base BEFORE any UTC conversion or deal-history read
   g_clockOk=ValidateClockBase();
   if(!g_clockOk)
      Health("clock_base_invalid","GMT/server clock not sane at init — deferring ticks/history to OnTimer");
   else
      Health("clock_base_ok",StringFormat("offset_server_minus_gmt_s=%I64d",g_clockOffsetSec));
   // on resume, flag the per-symbol gap between the loaded cursor and now (e.g. after a reset)
   if(g_clockOk)
   {
      long nowMs=NowMsc();
      for(int i=0;i<g_nSym;i++)
         if(g_lastMsc[i]>0 && nowMs-g_lastMsc[i]>(long)GapWarnSec*1000)
            Health("resume_gap",StringFormat("%s from_msc=%I64d to_msc=%I64d dur_s=%I64d (back-read on resume)",
                   g_syms[i],g_lastMsc[i],nowMs,(nowMs-g_lastMsc[i])/1000));
   }
   g_curDay=UtcDayStart0(TimeGMT());
   if(g_clockOk)
   {
      datetime dealFrom=(g_lastDealTimeMsc>0)?(datetime)(g_lastDealTimeMsc/1000):(TimeGMT()-(datetime)HistoryBackfillDays*86400);
      ReconcileDeals(dealFrom);
      SnapshotSymbols(); SnapshotAccount();
   }
   EventSetTimer(MathMax(1,TickTimerSeconds));
   Health("start",StringFormat("symbols=%d backfillDays=%d overlapDays=%d gapWarnSec=%d clockOk=%d",
          g_nSym,HistoryBackfillDays,ReconcileOverlapDays,GapWarnSec,(int)g_clockOk));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ SaveCheckpoint(); EventKillTimer(); Health("stop","reason="+(string)reason); }

void OnTimer()
{
   // connection: report an outage as a single start, then end + duration on reconnect
   if(!(bool)TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      if(g_disconnectSince==0)
      { g_disconnectSince=TimeGMT();
        Health("disconnect_start",TimeToString(g_disconnectSince,TIME_DATE|TIME_SECONDS)); }
      return;
   }
   if(g_disconnectSince>0)
   {
      datetime endT=TimeGMT(); long dur=(long)endT-(long)g_disconnectSince;
      Health("disconnect_end",StringFormat("start=%s end=%s dur_s=%I64d",
             TimeToString(g_disconnectSince,TIME_DATE|TIME_SECONDS),
             TimeToString(endT,TIME_DATE|TIME_SECONDS),dur));
      g_disconnectSince=0;
   }
   // clock-base gate: no UTC conversion or history work until the clock is validated
   if(!ValidateClockBase())
   { if(g_clockOk){ g_clockOk=false; Health("clock_base_invalid","deferring ticks/history until clock sane"); } return; }
   if(!g_clockOk){ g_clockOk=true; Health("clock_base_ok",StringFormat("offset_server_minus_gmt_s=%I64d",g_clockOffsetSec)); }

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
