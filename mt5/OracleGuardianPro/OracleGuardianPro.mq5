//+------------------------------------------------------------------+
//|                                            OracleGuardianPro.mq5 |
//|  Oracle Guardian Pro - account-protection-first EA for           |
//|  Upcomers Oracle (XAUUSD / XAGUSD, M3 Session VWAP x EMA 9)      |
//|                                                                  |
//|  NO PROFIT IS GUARANTEED. Experimental, untested software.       |
//|  Priority: 1) Oracle rules 2) live equity tracking 3) dynamic    |
//|  risk 4) trade quality 5) daily target.                          |
//+------------------------------------------------------------------+
#property copyright   "Personal EA - use at your own risk"
#property version     "1.00"
#property description "Oracle Guardian Pro: Session VWAP (OHLC/4) x EMA9 on M3 for XAUUSD/XAGUSD"
#property description "with Upcomers Oracle rule guard, equity-based dynamic sizing and mandatory stop-loss."
#property description "No profit is guaranteed. Test on demo first."

//--- module order matters (each module uses the ones above it)
#include "Include/OGP_Inputs.mqh"
#include "Include/OGP_Common.mqh"
#include "Include/OGP_Time.mqh"
#include "Include/OGP_History.mqh"
#include "Include/OGP_Account.mqh"
#include "Include/OGP_Vwap.mqh"
#include "Include/OGP_Sessions.mqh"
#include "Include/OGP_Trade.mqh"
#include "Include/OGP_Strategy.mqh"
#include "Include/OGP_Positions.mqh"
#include "Include/OGP_Dashboard.mqh"

//==================================================================//
// Globals                                                          //
//==================================================================//
COgpSymbol       *g_syms[];
CAccountMonitor   g_acc;
COracleRules      g_rules;
CNewsFilter       g_news;
CPositionManager  g_pm;
CDashboard        g_dash;
datetime          g_lastOffsetRefresh = 0;
datetime          g_lastDash = 0;
string            g_entryBlock = "";
string            g_sessName = "";

double SlippageFor(const string sym)
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
      if(g_syms[i].sym == sym)
         return g_syms[i].slip;
   return 0.0;
  }

bool SymbolAllowsDirection(const string sym, const int dir, string &why)
  {
   long mode = SymbolInfoInteger(sym, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED || mode == SYMBOL_TRADE_MODE_CLOSEONLY)
     {
      why = "symbol trading disabled / close-only";
      return false;
     }
   if((mode == SYMBOL_TRADE_MODE_LONGONLY && dir < 0) || (mode == SYMBOL_TRADE_MODE_SHORTONLY && dir > 0))
     {
      why = "symbol does not allow this direction";
      return false;
     }
   return true;
  }

//==================================================================//
// Entry decision pipeline                                          //
//==================================================================//
void Reject(COgpSymbol *s, const string side, const string src, const string why)
  {
   s.lastDecision = "REJECTED: " + why;
   Journal("REJECT", s.sym, StringFormat("%s (%s): %s", side, src, why));
  }

void HandleCandidate(COgpSymbol *s, const int dir, const string src, const datetime now)
  {
   string side = (dir > 0) ? "BUY" : "SELL";
   double vref = (InpEntryMode == OGP_ENTRY_LIVE && s.vwapLiveOk) ? s.vwapLive : s.vwap.Bar1();
   double eref = (InpEntryMode == OGP_ENTRY_LIVE) ? s.ema[0] : s.ema[1];
   s.lastSignal = StringFormat("%s %s %s", side, src, TimeToString(now, TIME_MINUTES));
   Journal("SIGNAL", s.sym, StringFormat("%s %s: EMA%d %s VWAP | EMA=%s VWAP=%s (%s vol) bid=%s ask=%s ATR=%s",
                                         side, src, InpEmaPeriod, dir > 0 ? "crossed ABOVE" : "crossed BELOW",
                                         Px(s.sym, eref), Px(s.sym, vref), s.vwap.VolumeType(),
                                         Px(s.sym, s.tick.bid), Px(s.sym, s.tick.ask), Px(s.sym, s.atr[1])));
   string why = "";

   //--- 1. duplicate protection
   if(s.lastEntryBar == s.curBar)
     {
      Reject(s, side, src, "entry already attempted on this M3 bar");
      return;
     }
   //--- 2. strategy filters (signal quality, volatility, stops)
   OgpEntryIntent it;
   ENUM_OGP_EVAL ev = s.Evaluate(dir, src, it, why);
   if(ev == OGP_EVAL_CHASED && InpUsePullbackMode && src != "pullback")
      s.ArmPullback(dir);
   if(ev != OGP_EVAL_OK)
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 3. switches, time, news
   if(!InpEnableNewEntries)
     {
      Reject(s, side, src, "new entries disabled (InpEnableNewEntries=false)");
      return;
     }
   string sess = "";
   if(!TimeAllowsEntry(now, why, sess))
     {
      Reject(s, side, src, why);
      return;
     }
   if(g_news.Blocks(now, why))
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 4. Oracle / account gate
   if(!g_rules.EntryAllowed(g_acc, why))
     {
      Reject(s, side, src, why);
      return;
     }
   if(!TradingPermitted(why) || !SymbolAllowsDirection(s.sym, dir, why))
     {
      Reject(s, side, src, why);
      return;
     }
   //--- 5. position rules
   OgpRiskSummary rs;
   BuildRiskSummary(rs);
   for(int i = 0; i < ArraySize(rs.eaSyms); i++)
      if(rs.eaSyms[i] == s.sym)
        {
         Reject(s, side, src, "max 1 EA position per symbol");
         return;
        }
   if(InpBlockIfUnprotected && rs.unprotected > 0)
     {
      Reject(s, side, src, StringFormat("%d account position(s) without stop-loss", rs.unprotected));
      return;
     }
   if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING && PositionSelect(s.sym))
     {
      Reject(s, side, src, "netting account already has a position on this symbol");
      return;
     }
   //--- 6. sizing
   double lots = 0.0, planned = 0.0;
   string capInfo = "";
   it.entry = (dir > 0) ? s.tick.ask : s.tick.bid;
   double slPrice = it.entry - dir * it.slDist;
   if(!ComputeLots(s.sym, dir, it.entry, slPrice, s.slip, rs, g_acc, g_rules, lots, planned, capInfo, why))
     {
      Reject(s, side, src, why + " | " + capInfo);
      return;
     }
   //--- 7. margin (keep 10% of free margin in reserve)
   double margin = 0.0;
   if(!OrderCalcMargin(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, s.sym, lots, it.entry, margin) || margin > g_acc.freeMargin * 0.9)
     {
      Reject(s, side, src, StringFormat("insufficient margin: need %s, free %s", Usd(margin), Usd(g_acc.freeMargin)));
      return;
     }
   //--- 8. execute
   Journal("RISK", s.sym, StringFormat("%s ACCEPTED [%s] %s | %s | margin %s", side, sess, it.detail, capInfo, Usd(margin)));
   s.lastEntryBar = s.curBar;                // one attempt per bar whatever the outcome
   if(OpenWithStop(s.sym, dir, lots, it.slDist, it.tpDist, InpOrderComment))
     {
      s.OnEntry(dir);
      s.lastDecision = StringFormat("OPENED %s %.2f lots, risk %s", side, lots, Usd(planned));
      g_rules.stats.eaEntriesToday++;        // count immediately; history refresh follows
      g_rules.statsDirty = true;
     }
   else
      s.lastDecision = "ORDER FAILED (see journal)";
  }

//==================================================================//
// Main loop                                                        //
//==================================================================//
void ProcessAll()
  {
   datetime now = ServerNow();
   if(!OgpIsTester() && now - g_lastOffsetRefresh >= 3600)
     {
      RefreshAutoServerOffset();
      g_lastOffsetRefresh = now;
     }
   bool wasConnected = g_acc.connected;
   g_acc.Update();
   if(g_acc.connected && !wasConnected)
      for(int i = 0; i < ArraySize(g_syms); i++)
         g_syms[i].OnReconnect();
   g_rules.Update(g_acc);
   g_news.Refresh(now);
   UpdateSessionLogs(now);
   if(g_rules.emergency)
      LogThrottled("emerg", "RISK", "", "ACCOUNT EMERGENCY: " + g_rules.emergencyReason + " - closing EA positions", 30);

   datetime anchor = VwapAnchor(now);
   bool weekendClose = WeekendCloseDue(now);
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      COgpSymbol *s = g_syms[i];
      bool fresh = s.Refresh(anchor);
      g_pm.ManageSymbol(s, g_rules.emergency, g_rules.emergencyReason, weekendClose, now);
      if(!fresh || !s.dataOk)
         continue;
      int dir = s.DetectCross(anchor);
      if(dir != 0)
        {
         s.OnCrossObserved(dir);
         HandleCandidate(s, dir, InpEntryMode == OGP_ENTRY_LIVE ? "live" : "confirmed", now);
        }
      int pb = s.CheckPullback();
      if(pb != 0)
         HandleCandidate(s, pb, "pullback", now);
     }

   //--- global entry status for the dashboard
   string why = "";
   string sess = "";
   g_entryBlock = "";
   if(!InpEnableNewEntries)
      g_entryBlock = "entries disabled by user";
   else
      if(!g_rules.EntryAllowed(g_acc, why))
         g_entryBlock = why;
      else
         if(!TimeAllowsEntry(now, why, sess))
            g_entryBlock = why;
         else
            if(g_news.Blocks(now, why))
               g_entryBlock = why;
   g_sessName = sess;

   if(now != g_lastDash)
     {
      g_lastDash = now;
      DrawDashboard(now);
     }
  }

void DrawDashboard(const datetime now)
  {
   if(!InpShowDashboard || (OgpIsTester() && !MQLInfoInteger(MQL_VISUAL_MODE)))
      return;
   DashClear();
   color hdr = clrGold, ok = clrLimeGreen, bad = clrTomato, warn = clrOrange, txt = clrSilver;
   DashAdd("ORACLE GUARDIAN PRO v1.00  (no profit guarantee)", hdr);
   DashAdd(StringFormat("Server %s | UTC %s | NY %s", TimeToString(now, TIME_MINUTES),
                        TimeToString(ServerToUtc(now), TIME_MINUTES), TimeToString(NyLocal(now), TIME_MINUTES)), txt);
   DashAdd(g_entryBlock == "" ? "ENTRIES: ALLOWED [" + g_sessName + "]" : "ENTRIES: BLOCKED - " + g_entryBlock,
           g_entryBlock == "" ? ok : bad);
   DashAdd("--- ACCOUNT (live MT5 data) ---", hdr);
   DashAdd(StringFormat("Balance %s  Equity %s  Floating %s %s", Usd(g_acc.balance), Usd(g_acc.equity), Usd(g_acc.floating), g_acc.currency),
           g_acc.floating >= 0 ? ok : warn);
   DashAdd(StringFormat("Margin %s  Free %s  Level %s%%  Lev 1:%I64d", Usd(g_acc.margin), Usd(g_acc.freeMargin),
                        g_acc.margin > 0 ? DoubleToString(g_acc.marginLevel, 0) : "-", g_acc.leverage), txt);
   DashAdd("--- ORACLE RULES (EA references; Upcomers server values not readable) ---", hdr);
   DashAdd(StringFormat("Shield floor %s [%s]  dist %s", Usd(g_rules.shieldFloor),
                        InpManualShieldFloor > 0 ? "MANUAL+" + SourceText(g_acc.peakSrc) : SourceText(g_acc.peakSrc),
                        Usd(g_acc.equity - g_rules.shieldFloor)), g_rules.shieldReliable ? txt : bad);
   DashAdd(StringFormat("Peak equity %s", Usd(g_acc.peakEquity)), txt);
   DashAdd(StringFormat("Day start eq %s [%s]  daily floor %s  dist %s", Usd(g_acc.dayStartEquity), SourceText(g_acc.daySrc),
                        Usd(g_rules.dailyFloor), Usd(g_acc.equity - g_rules.dailyFloor)), g_rules.dailyReliable ? txt : bad);
   DashAdd(StringFormat("Single trade limit %s | internal max %s", Usd(g_rules.singleTradeLimit), Usd(InpMaxSingleTradeLossUSD)), txt);
   if(g_rules.stats.ok)
     {
      DashAdd(StringFormat("Today realized %s / target %s | trades %d/%d | lock %s", Usd(g_rules.stats.todayNet), Usd(InpDailyTargetUSD),
                           g_rules.stats.eaEntriesToday, InpMaxTradesPerDay, g_rules.dailyLock ? "ON" : "off"),
              g_rules.dailyLock ? bad : txt);
      DashAdd(StringFormat("Cycle net %s | valid days %d/%d (>= %s) | best day %.0f%%", Usd(g_rules.stats.cycleNet),
                           g_rules.stats.validDays, InpMinValidDays, Usd(g_rules.validDayThreshold), g_rules.BestDayRatio()),
              g_rules.BestDayRatio() > InpBestDayPct ? warn : txt);
     }
   else
      DashAdd("Realized statistics: UNKNOWN (history)", bad);
   OgpRiskSummary rs;
   BuildRiskSummary(rs);
   DashAdd(StringFormat("Payout: %s", g_rules.PayoutStatus(rs.eaPositions + rs.otherPositions)), txt);
   DashAdd("--- RISK ---", hdr);
   DashAdd(StringFormat("EA planned risk %s / cap %s | positions EA %d other %d | no-SL %d",
                        rs.eaRiskFromEntry >= OGP_INF_RISK ? "INF" : Usd(rs.eaRiskFromEntry),
                        Usd(InpInitialBalance * InpMaxTotalRiskPct / 100.0), rs.eaPositions, rs.otherPositions, rs.unprotected),
           rs.unprotected > 0 ? bad : txt);
   DashAdd(StringFormat("Risk/trade %.2f%% of equity = %s", InpRiskPct, Usd(g_acc.equity * InpRiskPct / 100.0)), txt);
   if(g_rules.emergency)
      DashAdd("EMERGENCY: " + g_rules.emergencyReason, bad);
   DashAdd("--- MARKETS (M3) ---", hdr);
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      COgpSymbol *s = g_syms[i];
      if(!s.dataOk)
        {
         DashAdd(s.sym + ": waiting for data", warn);
         continue;
        }
      DashAdd(StringFormat("%s spread %s | ATR %s | EMA %s | VWAP %s (%s) | %s", s.sym, Px(s.sym, s.tick.ask - s.tick.bid),
                           Px(s.sym, s.atr[1]), Px(s.sym, s.ema[0]), s.vwap.Bar1Valid() ? Px(s.sym, s.vwap.Bar1()) : "n/a",
                           s.vwap.VolumeType(), s.TrendSummary()), txt);
      DashAdd(StringFormat("   last signal: %s | %s", s.lastSignal, s.lastDecision), txt);
     }
   DashAdd(StringFormat("News: %s | next: %s", g_news.status, g_news.NextEvent(now)),
           (InpUseNewsFilter && !g_news.available) ? warn : txt);
   g_dash.Render(g_dl, g_dc);
  }

//==================================================================//
// Event handlers                                                   //
//==================================================================//
bool ValidateInputs()
  {
   string e = "";
   if(InpInitialBalance <= 0.0)
      e = "InpInitialBalance must be > 0";
   else if(InpRiskPct <= 0.0 || InpRiskPct > 1.0)
      e = "InpRiskPct must be in (0, 1.0] (firm single-trade limit is 2%)";
   else if(InpMaxTotalRiskPct < InpRiskPct)
      e = "InpMaxTotalRiskPct must be >= InpRiskPct";
   else if(InpDailyLossLockUSD <= 0.0 || InpDailyLossLockUSD >= InpInitialBalance * InpDailyDDPct / 100.0)
      e = "InpDailyLossLockUSD must be > 0 and below the firm daily drawdown";
   else if(InpMaxSingleTradeLossUSD <= 0.0 || InpMaxSingleTradeLossUSD >= InpInitialBalance * InpSingleTradePct / 100.0)
      e = "InpMaxSingleTradeLossUSD must be > 0 and below the firm single-trade limit";
   else if(InpPositionEmergencyUSD >= InpInitialBalance * InpSingleTradePct / 100.0)
      e = "InpPositionEmergencyUSD must be below the firm single-trade limit";
   else if(InpEmergencyBufferUSD <= 0.0 || InpFloorSafetyUSD <= InpEmergencyBufferUSD)
      e = "need 0 < InpEmergencyBufferUSD < InpFloorSafetyUSD";
   else if(InpMinHoldSeconds < 120)
      e = "InpMinHoldSeconds must be >= 120 (Oracle treats trades under 2 minutes as tick scalping)";
   else if(InpSlAtrMult <= 0.0 || InpMaxSlAtrMult < InpSlAtrMult)
      e = "need 0 < InpSlAtrMult <= InpMaxSlAtrMult";
   else if(InpCorrelatedRiskFactor <= 0.0 || InpCorrelatedRiskFactor > 1.0)
      e = "InpCorrelatedRiskFactor must be in (0, 1]";
   else if(InpMaxTradesPerDay < 1 || InpEmaPeriod < 1 || InpAtrPeriod < 1 || InpSwingLookback < 2 || InpBreakoutLookback < 2)
      e = "periods / lookbacks / max trades out of range";
   if(e != "")
     {
      OgpLog("INIT ERROR: " + e);
      return false;
     }
   return true;
  }

bool AddSymbol(const string base, const bool gold)
  {
   string sym = InpSymbolPrefix + base + InpSymbolSuffix;
   if(!SymbolSelect(sym, true))
     {
      OgpLog(StringFormat("INIT ERROR: symbol '%s' not found (check prefix/suffix), err %d", sym, GetLastError()));
      return false;
     }
   COgpSymbol *s = new COgpSymbol();
   if(!s.Init(sym, gold))
     {
      s.Deinit();
      delete s;
      return false;
     }
   int n = ArraySize(g_syms);
   ArrayResize(g_syms, n + 1);
   g_syms[n] = s;
   return true;
  }

void FreeSymbols()
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
      if(CheckPointer(g_syms[i]) == POINTER_DYNAMIC)
        {
         g_syms[i].Deinit();
         delete g_syms[i];
        }
   ArrayResize(g_syms, 0);
  }

int OnInit()
  {
   OgpLog("==================================================================");
   OgpLog("Oracle Guardian Pro v1.00 - NO PROFIT GUARANTEE - verify every rule on Upcomers");
   if(!ValidateInputs() || !SessionsInit())
      return INIT_PARAMETERS_INCORRECT;
   JournalOpen();
   RefreshAutoServerOffset();
   if(!g_autoOffsetValid)
      Journal("TIME", "", StringFormat("server time rule: UTC%+d standard, %s DST%s", InpServerUtcOffsetHours,
                                       EnumToString(InpServerDst), OgpIsTester() ? " (tester: no auto detection)" : ""));
   datetime now = ServerNow();
   Journal("TIME", "", StringFormat("server %s = UTC %s = New York %s", Ts(now), Ts(ServerToUtc(now)), Ts(NyLocal(now))));

   ArrayResize(g_syms, 0);
   bool ok = true;
   if(InpSymbols == OGP_SYM_BOTH || InpSymbols == OGP_SYM_GOLD)
      ok = ok && AddSymbol(InpGoldSymbol, true);
   if(InpSymbols == OGP_SYM_BOTH || InpSymbols == OGP_SYM_SILVER)
      ok = ok && AddSymbol(InpSilverSymbol, false);
   if(!ok || ArraySize(g_syms) == 0)
     {
      FreeSymbols();
      JournalClose();
      return INIT_FAILED;
     }

   g_acc.Init();
   g_rules.Update(g_acc);
   Journal("SYSTEM", "", StringFormat("account %I64d %s, leverage 1:%I64d, margin mode %s, balance %s, equity %s",
                                      g_acc.login, g_acc.currency, g_acc.leverage,
                                      AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? "HEDGING" : "NETTING",
                                      Usd(g_acc.balance), Usd(g_acc.equity)));
   if(MathAbs(g_acc.balance - InpInitialBalance) > InpInitialBalance * 0.10)
      Journal("SYSTEM", "", StringFormat("WARNING: balance %s differs >10%% from InpInitialBalance %s - check the input",
                                         Usd(g_acc.balance), Usd(InpInitialBalance)));
   Journal("ORACLE", "", StringFormat("firm limits (reference, NOT targets): shield %s (%.1f%%), daily %.1f%%, single trade %.1f%% = %s, valid day %s, payout %s",
                                      Usd(InpInitialBalance * InpShieldPct / 100.0), InpShieldPct, InpDailyDDPct, InpSingleTradePct,
                                      Usd(g_rules.singleTradeLimit), Usd(g_rules.validDayThreshold), Usd(g_rules.payoutThreshold)));
   Journal("ORACLE", "", StringFormat("shield floor %s [%s], day start %s [%s]", Usd(g_rules.shieldFloor), SourceText(g_acc.peakSrc),
                                      Usd(g_acc.dayStartEquity), SourceText(g_acc.daySrc)));
   Journal("SYSTEM", "", StringFormat("mode %s | trend M15 %s H1 %s | breakout %s | chase %s | pullback %s | EMA exit %s | BE %s | trail %s | news %s",
                                      EnumToString(InpEntryMode), InpUseTrendM15 ? "ON" : "off", InpUseTrendH1 ? "ON" : "off",
                                      InpUseBreakoutFilter ? "ON" : "off", InpUseChaseFilter ? "ON" : "off",
                                      InpUsePullbackMode ? "ON" : "off", InpUseEmaExit ? "ON" : "off",
                                      InpUseBreakEven ? "ON" : "off", InpUseTrailing ? "ON" : "off", InpUseNewsFilter ? "ON" : "off"));
   g_dash.Create();
   if(!EventSetTimer(1))
      Journal("SYSTEM", "", StringFormat("WARNING: timer failed (err %d)", GetLastError()));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   g_acc.Save();
   FreeSymbols();
   g_dash.Destroy();
   Journal("SYSTEM", "", StringFormat("deinit (reason %d). Open positions keep their broker-side SL/TP but are NOT managed now.", reason));
   JournalClose();
  }

void OnTick()  { ProcessAll(); }
void OnTimer() { ProcessAll(); }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   g_rules.statsDirty = true;
   if(!HistoryDealSelect(trans.deal))
      return;
   if((ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   string sym = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   string e = (entry == DEAL_ENTRY_IN) ? "OPENED" : (entry == DEAL_ENTRY_OUT ? "CLOSED" : (entry == DEAL_ENTRY_INOUT ? "REVERSED" : "CLOSED_BY"));
   Journal("DEAL", sym, StringFormat("%s #%I64u %.2f lots @ %s | pos #%I64d | profit %s comm %s swap %s | reason %s",
                                     e, trans.deal, HistoryDealGetDouble(trans.deal, DEAL_VOLUME),
                                     Px(sym, HistoryDealGetDouble(trans.deal, DEAL_PRICE)),
                                     HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_PROFIT)),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_COMMISSION)),
                                     Usd(HistoryDealGetDouble(trans.deal, DEAL_SWAP)),
                                     EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON))));
  }
//+------------------------------------------------------------------+
