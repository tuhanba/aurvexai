//+------------------------------------------------------------------+
//| OGP_Account.mqh - live account monitor + Oracle rule engine      |
//|                                                                  |
//| WHAT MT5 GIVES US vs WHAT ONLY UPCOMERS KNOWS                    |
//|  Read directly from MT5 (exact): balance, equity, floating P/L,  |
//|   margin, free margin, margin level, currency, positions, deals. |
//|  NOT readable from MT5 (Upcomers server-side): the Dynamic Risk  |
//|   Shield floor, the highest-equity reference it trails, the      |
//|   equity Upcomers recorded at 00:00 UTC, payout-cycle resets.    |
//|  The EA therefore keeps its OWN references and labels each one:  |
//|   OBSERVED      - seen live by this EA                           |
//|   RECONSTRUCTED - conservative upper bound from history + M1     |
//|   MANUAL        - typed in by the user from the Upcomers panel   |
//|   UNKNOWN       - cannot be determined -> new entries BLOCKED    |
//|                                                                  |
//| RULE INTERPRETATIONS (owner-confirmed, conservative):            |
//|  Shield floor = max(initial*(1-5%), peakEquity - initial*5%,     |
//|                     manual floor)                                |
//|  Daily floor  = dayStartEquity - 4% * min(initial, dayStartEq)   |
//|                 (day = 00:00-23:59 UTC, reference = EQUITY)      |
//|  Single trade = 2% * min(initial, current equity)                |
//+------------------------------------------------------------------+
#ifndef OGP_ACCOUNT_MQH
#define OGP_ACCOUNT_MQH

class CAccountMonitor
  {
private:
   CHistoryAnalyzer  m_hist;
   string            m_file;
   datetime          m_lastSave;
   datetime          m_lastResolveTry;
   bool              m_needCycleRebuild;
   bool              m_gapPending;
   datetime          m_gapStart;
   bool              m_disconnected;
   double            m_lastEquity;
   datetime          m_initTime;

   //--- state persistence (key=value text file in MQL5/Files)
   bool              LoadState(datetime &stCycle, double &stInit)
     {
      int h = FileOpen(m_file, FILE_READ | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return false;
      stCycle = 0;
      stInit = 0.0;
      while(!FileIsEnding(h))
        {
         string line = FileReadString(h);
         int p = StringFind(line, "=");
         if(p <= 0)
            continue;
         string k = StringSubstr(line, 0, p);
         string v = StringSubstr(line, p + 1);
         if(k == "peak_equity")
            peakEquity = StringToDouble(v);
         else if(k == "peak_src")
            peakSrc = (ENUM_OGP_SOURCE)StringToInteger(v);
         else if(k == "peak_time")
            peakTime = (datetime)StringToInteger(v);
         else if(k == "day_key")
            dayKey = (datetime)StringToInteger(v);
         else if(k == "day_start_equity")
            dayStartEquity = StringToDouble(v);
         else if(k == "day_src")
            daySrc = (ENUM_OGP_SOURCE)StringToInteger(v);
         else if(k == "last_seen")
            lastSeen = (datetime)StringToInteger(v);
         else if(k == "cycle_start")
            stCycle = (datetime)StringToInteger(v);
         else if(k == "initial_balance")
            stInit = StringToDouble(v);
        }
      FileClose(h);
      return true;
     }

   void              ResolvePeak(const datetime now)
     {
      string err = "";
      double bound = 0.0;
      if(m_needCycleRebuild)
        {
         datetime from = EffectiveCycleStart(now);
         if(m_hist.EquityUpperBound(from, now, bound, err))
           {
            peakEquity = MaxD(bound, equity);
            peakSrc = OGP_SRC_BOUND;
            peakTime = now;
            peakNote = "rebuilt from cycle start " + Ts(from);
            m_needCycleRebuild = false;
            Journal("ORACLE", "", StringFormat("peak equity reconstructed since cycle start %s: %s (conservative upper bound)", Ts(from), Usd(peakEquity)));
           }
         else
           {
            peakNote = "rebuild failed: " + err;
            LogThrottled("peakfail", "ORACLE", "", "cannot reconstruct peak equity: " + err + " -> entries blocked (enter InpManualShieldFloor or InpManualPeakEquity)", 300);
           }
        }
      if(m_gapPending && !m_needCycleRebuild)
        {
         if(m_hist.EquityUpperBound(m_gapStart, now, bound, err))
           {
            if(bound > peakEquity)
              {
               Journal("ORACLE", "", StringFormat("equity not observed %s..%s; conservative bound %s raises peak from %s",
                                                  Ts(m_gapStart), Ts(now), Usd(bound), Usd(peakEquity)));
               peakEquity = bound;
               peakSrc = OGP_SRC_BOUND;
               peakTime = now;
              }
            if(peakSrc == OGP_SRC_UNKNOWN)
               peakSrc = OGP_SRC_BOUND;
            peakNote = "";
            m_gapPending = false;
           }
         else
           {
            peakNote = "gap bound failed: " + err;
            LogThrottled("gapfail", "ORACLE", "", "cannot bound equity during unobserved gap: " + err, 300);
            peakSrc = OGP_SRC_UNKNOWN;
           }
        }
      if(InpManualPeakEquity > 0.0 && InpManualPeakEquity > peakEquity)
        {
         peakEquity = InpManualPeakEquity;
         if(peakSrc == OGP_SRC_UNKNOWN)
            peakSrc = OGP_SRC_MANUAL;
        }
      if(peakSrc == OGP_SRC_UNKNOWN && InpManualPeakEquity > 0.0 && !m_needCycleRebuild && !m_gapPending)
         peakSrc = OGP_SRC_MANUAL;
     }

   void              ResolveDayStart(const datetime now)
     {
      datetime key = UtcDayKey(now);
      if(InpManualDayStartEquity > 0.0 && DayStart(InpManualDayStartDate) == key)
        {
         dayStartEquity = InpManualDayStartEquity;
         daySrc = OGP_SRC_MANUAL;
         dayNote = "manual input";
         return;
        }
      datetime midServer = UtcToServer(key);
      double bound = 0.0;
      string err = "";
      if(m_hist.EquityUpperBoundAround(midServer, 60, bound, err))
        {
         dayStartEquity = bound;
         if(now - midServer <= 60)
            dayStartEquity = MaxD(dayStartEquity, MaxD(equity, m_lastEquity));
         daySrc = (lastSeen > 0 && lastSeen >= midServer - 60 && now - midServer <= 60) ? OGP_SRC_OBSERVED : OGP_SRC_BOUND;
         dayNote = StringFormat("UTC day start %s server", Ts(midServer));
         Journal("ORACLE", "", StringFormat("day start equity (00:00 UTC = %s server) = %s [%s]",
                                            Ts(midServer), Usd(dayStartEquity), SourceText(daySrc)));
        }
      else
        {
         daySrc = OGP_SRC_UNKNOWN;
         dayNote = "bound failed: " + err;
         LogThrottled("dayfail", "ORACLE", "", "cannot determine today's start equity: " + err +
                      " -> entries blocked (enter InpManualDayStartEquity + date)", 300);
        }
     }

public:
   //--- live snapshot (exact, from MT5)
   long              login;
   string            currency;
   long              leverage;
   double            balance;
   double            equity;
   double            floating;
   double            margin;
   double            freeMargin;
   double            marginLevel;
   bool              connected;
   //--- references kept by the EA
   double            peakEquity;
   ENUM_OGP_SOURCE   peakSrc;
   datetime          peakTime;
   string            peakNote;
   datetime          dayKey;
   double            dayStartEquity;
   ENUM_OGP_SOURCE   daySrc;
   string            dayNote;
   datetime          lastSeen;

                     CAccountMonitor(void) : m_file(""), m_lastSave(0), m_lastResolveTry(0), m_needCycleRebuild(false),
                     m_gapPending(false), m_gapStart(0), m_disconnected(false), m_lastEquity(0), m_initTime(0), login(0), currency(""),
                     leverage(0), balance(0), equity(0), floating(0), margin(0), freeMargin(0), marginLevel(0),
                     connected(true), peakEquity(0), peakSrc(OGP_SRC_UNKNOWN), peakTime(0), peakNote(""), dayKey(0),
                     dayStartEquity(0), daySrc(OGP_SRC_UNKNOWN), dayNote(""), lastSeen(0) {}

   //--- cycle start in the future (e.g. tester period before it): count from EA start instead
   datetime          EffectiveCycleStart(const datetime now) const { return (InpCycleStart <= now) ? InpCycleStart : ((m_initTime > 0) ? m_initTime : now); }

   void              ReadSnapshot(void)
     {
      login       = AccountInfoInteger(ACCOUNT_LOGIN);
      currency    = AccountInfoString(ACCOUNT_CURRENCY);
      leverage    = AccountInfoInteger(ACCOUNT_LEVERAGE);
      balance     = AccountInfoDouble(ACCOUNT_BALANCE);
      equity      = AccountInfoDouble(ACCOUNT_EQUITY);
      floating    = AccountInfoDouble(ACCOUNT_PROFIT);
      margin      = AccountInfoDouble(ACCOUNT_MARGIN);
      freeMargin  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      marginLevel = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      connected   = OgpIsTester() ? true : (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
     }

   void              Init(void)
     {
      ReadSnapshot();
      m_file = StringFormat("OGP_state_%I64d%s.txt", login, OgpIsTester() ? "_tester" : "");
      datetime now = ServerNow();
      m_initTime = now;
      datetime stCycle = 0;
      double stInit = 0.0;
      bool loaded = LoadState(stCycle, stInit);
      if(loaded && (stCycle != InpCycleStart || MathAbs(stInit - InpInitialBalance) > 0.009))
        {
         Journal("ORACLE", "", StringFormat("payout cycle / initial balance changed (state %s / %s -> inputs %s / %s): peak reference rebuilt",
                                            Ts(stCycle), Usd(stInit), Ts(InpCycleStart), Usd(InpInitialBalance)));
         loaded = false;
        }
      if(loaded && peakSrc != OGP_SRC_UNKNOWN && peakEquity > 0.0 && lastSeen > 0)
        {
         m_gapPending = true;
         m_gapStart = lastSeen;
         Journal("ORACLE", "", StringFormat("state loaded: peak %s [%s], last seen %s -> bounding the unobserved gap",
                                            Usd(peakEquity), SourceText(peakSrc), Ts(lastSeen)));
        }
      else
        {
         peakEquity = 0.0;
         peakSrc = OGP_SRC_UNKNOWN;
         m_needCycleRebuild = true;
        }
      if(InpCycleStart > now)
         Journal("ORACLE", "", "WARNING: InpCycleStart is in the future - cycle statistics count from EA start " + Ts(now));
      ResolvePeak(now);
      if(!loaded || dayKey != UtcDayKey(now) || daySrc == OGP_SRC_UNKNOWN)
        {
         dayKey = UtcDayKey(now);
         ResolveDayStart(now);
        }
      else
         if(InpManualDayStartEquity > 0.0 && DayStart(InpManualDayStartDate) == dayKey)
            ResolveDayStart(now);
      m_lastEquity = equity;
      lastSeen = now;
      Save();
     }

   void              Update(void)
     {
      ReadSnapshot();
      datetime now = ServerNow();

      //--- unobserved periods: disconnection or stalled EA (> 120 s)
      if(!connected)
        {
         if(!m_disconnected)
           {
            m_disconnected = true;
            if(!m_gapPending)
               m_gapStart = lastSeen;
            Journal("SYSTEM", "", "terminal DISCONNECTED - equity no longer observed");
           }
         return;
        }
      if(m_disconnected)
        {
         m_disconnected = false;
         m_gapPending = true;
         Journal("SYSTEM", "", "terminal RECONNECTED - bounding equity for the disconnected period");
        }
      if(lastSeen > 0 && now - lastSeen > 120 && !m_gapPending)
        {
         m_gapPending = true;
         m_gapStart = lastSeen;
        }

      //--- UTC day change
      datetime key = UtcDayKey(now);
      if(key != dayKey)
        {
         dayKey = key;
         daySrc = OGP_SRC_UNKNOWN;
         Journal("ORACLE", "", "new UTC trading day " + TimeToString(key, TIME_DATE));
        }

      //--- retries for unresolved references (max every 30 s)
      if((m_needCycleRebuild || m_gapPending || daySrc == OGP_SRC_UNKNOWN) && now - m_lastResolveTry >= 30)
        {
         m_lastResolveTry = now;
         if(m_needCycleRebuild || m_gapPending)
            ResolvePeak(now);
         if(daySrc == OGP_SRC_UNKNOWN)
            ResolveDayStart(now);
        }

      //--- live peak tracking
      if(!m_needCycleRebuild && equity > peakEquity)
        {
         peakEquity = equity;
         peakTime = now;
         if(peakSrc == OGP_SRC_UNKNOWN && !m_gapPending)
            peakSrc = OGP_SRC_OBSERVED;
        }
      m_lastEquity = equity;
      lastSeen = now;
      if(now - m_lastSave >= 30)
         Save();
     }

   void              Save(void)
     {
      int h = FileOpen(m_file, FILE_WRITE | FILE_TXT | FILE_ANSI);
      if(h == INVALID_HANDLE)
        {
         LogThrottled("statesave", "SYSTEM", "", StringFormat("cannot write state file %s (err %d)", m_file, GetLastError()), 600);
         return;
        }
      FileWriteString(h, StringFormat("peak_equity=%.2f\n", peakEquity));
      FileWriteString(h, StringFormat("peak_src=%d\n", (int)peakSrc));
      FileWriteString(h, StringFormat("peak_time=%I64d\n", (long)peakTime));
      FileWriteString(h, StringFormat("day_key=%I64d\n", (long)dayKey));
      FileWriteString(h, StringFormat("day_start_equity=%.2f\n", dayStartEquity));
      FileWriteString(h, StringFormat("day_src=%d\n", (int)daySrc));
      FileWriteString(h, StringFormat("last_seen=%I64d\n", (long)lastSeen));
      FileWriteString(h, StringFormat("cycle_start=%I64d\n", (long)InpCycleStart));
      FileWriteString(h, StringFormat("initial_balance=%.2f\n", InpInitialBalance));
      FileClose(h);
      m_lastSave = ServerNow();
     }

   bool              PeakPending(void) const { return m_needCycleRebuild || m_gapPending; }
  };

//==================================================================//
// Oracle rule engine                                               //
//==================================================================//
class COracleRules
  {
private:
   datetime          m_lastStats;
   datetime          m_lockKey;
   bool              m_targetLogged;

public:
   double            shieldFloor;
   bool              shieldReliable;
   double            dailyLimit;
   double            dailyFloor;
   bool              dailyReliable;
   double            singleTradeLimit;
   double            validDayThreshold;
   double            payoutThreshold;
   OgpCycleStats     stats;
   bool              statsDirty;
   bool              dailyLock;
   string            dailyLockReason;
   bool              emergency;
   string            emergencyReason;

                     COracleRules(void) : m_lastStats(0), m_lockKey(0), m_targetLogged(false), shieldFloor(0), shieldReliable(false),
                     dailyLimit(0), dailyFloor(0), dailyReliable(false), singleTradeLimit(0), validDayThreshold(0),
                     payoutThreshold(0), statsDirty(true), dailyLock(false), dailyLockReason(""), emergency(false),
                     emergencyReason("") { stats.ok = false; }

   void              Update(CAccountMonitor &acc)
     {
      double init = InpInitialBalance;
      validDayThreshold = init * InpValidDayPct / 100.0;
      payoutThreshold   = init * InpPayoutPct / 100.0;

      //--- Dynamic Risk Shield (conservative interpretation)
      double shieldAmount = init * InpShieldPct / 100.0;
      double base = init - shieldAmount;
      shieldReliable = (acc.peakSrc != OGP_SRC_UNKNOWN && !acc.PeakPending()) || InpManualShieldFloor > 0.0;
      shieldFloor = base;
      if(acc.peakSrc != OGP_SRC_UNKNOWN)
         shieldFloor = MaxD(shieldFloor, acc.peakEquity - shieldAmount);
      if(InpManualShieldFloor > 0.0)
         shieldFloor = MaxD(shieldFloor, InpManualShieldFloor);

      //--- Daily drawdown (equity reference at 00:00 UTC)
      dailyReliable = (acc.daySrc != OGP_SRC_UNKNOWN);
      if(dailyReliable)
        {
         dailyLimit = MinD(init, acc.dayStartEquity) * InpDailyDDPct / 100.0;
         dailyFloor = acc.dayStartEquity - dailyLimit;
        }

      //--- Single trade loss
      singleTradeLimit = MinD(init, acc.equity) * InpSingleTradePct / 100.0;

      //--- realized statistics
      datetime now = ServerNow();
      if(statsDirty || now - m_lastStats >= 15)
        {
         OgpCycleStats tmp;
         if(ComputeCycleStats(acc.EffectiveCycleStart(now), acc.dayKey, validDayThreshold, tmp))
            stats = tmp;
         else
           {
            stats.ok = false;
            LogThrottled("statsfail", "ORACLE", "", "deal history unavailable - realized statistics unknown", 300);
           }
         m_lastStats = now;
         statsDirty = false;
        }

      //--- internal daily loss lock (sticky for the UTC day)
      if(m_lockKey != acc.dayKey)
        {
         m_lockKey = acc.dayKey;
         dailyLock = false;
         dailyLockReason = "";
         m_targetLogged = false;
        }
      if(dailyReliable && !dailyLock && acc.dayStartEquity - acc.equity >= InpDailyLossLockUSD)
        {
         dailyLock = true;
         dailyLockReason = StringFormat("internal daily loss lock: equity %s is %s below day start %s",
                                        Usd(acc.equity), Usd(acc.dayStartEquity - acc.equity), Usd(acc.dayStartEquity));
         Journal("RISK", "", dailyLockReason + " - no new entries until next UTC day");
        }
      if(InpStopAtDailyTarget && stats.ok && stats.todayNet >= InpDailyTargetUSD && !m_targetLogged)
        {
         m_targetLogged = true;
         Journal("RISK", "", StringFormat("daily target reached: realized net %s >= %s - no new entries today", Usd(stats.todayNet), Usd(InpDailyTargetUSD)));
        }

      //--- emergency (only with reliable floors)
      emergency = false;
      emergencyReason = "";
      if(shieldReliable && acc.equity <= shieldFloor + InpEmergencyBufferUSD)
        {
         emergency = true;
         emergencyReason = StringFormat("equity %s within %s of shield floor %s", Usd(acc.equity), Usd(InpEmergencyBufferUSD), Usd(shieldFloor));
        }
      if(dailyReliable && acc.equity <= dailyFloor + InpEmergencyBufferUSD)
        {
         emergency = true;
         emergencyReason = StringFormat("equity %s within %s of daily floor %s", Usd(acc.equity), Usd(InpEmergencyBufferUSD), Usd(dailyFloor));
        }
     }

   bool              EntryAllowed(CAccountMonitor &acc, string &why)
     {
      if(!acc.connected)
        {
         why = "terminal disconnected";
         return false;
        }
      if(!shieldReliable)
        {
         why = "Dynamic Risk Shield reference UNKNOWN (" + acc.peakNote + ")";
         return false;
        }
      if(!dailyReliable)
        {
         why = "today's start equity UNKNOWN (" + acc.dayNote + ")";
         return false;
        }
      if(!stats.ok)
        {
         why = "deal history statistics unavailable";
         return false;
        }
      if(emergency)
        {
         why = "EMERGENCY: " + emergencyReason;
         return false;
        }
      if(acc.equity - shieldFloor <= InpFloorSafetyUSD)
        {
         why = StringFormat("equity %s within safety %s of shield floor %s", Usd(acc.equity), Usd(InpFloorSafetyUSD), Usd(shieldFloor));
         return false;
        }
      if(acc.equity - dailyFloor <= InpFloorSafetyUSD)
        {
         why = StringFormat("equity %s within safety %s of daily floor %s", Usd(acc.equity), Usd(InpFloorSafetyUSD), Usd(dailyFloor));
         return false;
        }
      if(dailyLock)
        {
         why = dailyLockReason;
         return false;
        }
      if(InpStopAtDailyTarget && stats.todayNet >= InpDailyTargetUSD)
        {
         why = StringFormat("daily target reached (realized %s)", Usd(stats.todayNet));
         return false;
        }
      if(stats.eaEntriesToday >= InpMaxTradesPerDay)
        {
         why = StringFormat("max new trades per day reached (%d)", InpMaxTradesPerDay);
         return false;
        }
      return true;
     }

   double            BestDayRatio(void) const
     {
      if(!stats.ok || stats.cycleNet <= 0.0)
         return 0.0;
      return 100.0 * stats.bestDayNet / stats.cycleNet;
     }

   string            PayoutStatus(const int openPositions) const
     {
      if(!stats.ok)
         return "unknown (history)";
      bool p1 = stats.cycleNet >= payoutThreshold;
      bool p2 = stats.validDays >= InpMinValidDays;
      bool p3 = stats.cycleNet > 0.0 && stats.bestDayNet <= stats.cycleNet * InpBestDayPct / 100.0;
      bool p4 = openPositions == 0;
      if(p1 && p2 && p3 && p4)
         return "ELIGIBLE (verify on Upcomers)";
      string s = "";
      if(!p1)
         s += StringFormat("net %s/%s ", Usd(stats.cycleNet), Usd(payoutThreshold));
      if(!p2)
         s += StringFormat("days %d/%d ", stats.validDays, InpMinValidDays);
      if(!p3)
         s += StringFormat("bestDay %.0f%%>%.0f%% ", BestDayRatio(), InpBestDayPct);
      if(!p4)
         s += "positions open";
      return "not yet: " + s;
     }
  };

#endif
