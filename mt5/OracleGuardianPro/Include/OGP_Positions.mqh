//+------------------------------------------------------------------+
//| OGP_Positions.mqh - management of EA positions                   |
//|                                                                  |
//| Priority per tick (highest first):                               |
//|  1. account emergency (near a firm floor)      -> close          |
//|  2. position floating loss >= emergency limit  -> close          |
//|  3. Friday pre-weekend close                   -> close          |
//|  4. missing stop-loss                          -> set or close   |
//|  5. M3 close beyond EMA (after min hold)       -> close          |
//|  6. break-even / ATR trailing (after min hold, throttled)        |
//| 1-4 ignore the minimum hold time (account protection first).     |
//| 5-6 respect InpMinHoldSeconds (Oracle: < 2 min = tick scalping). |
//+------------------------------------------------------------------+
#ifndef OGP_POSITIONS_MQH
#define OGP_POSITIONS_MQH

class CPositionManager
  {
private:
   ulong             m_tk[];        // per-ticket memory
   double            m_initDist[];
   datetime          m_lastMod[];
   datetime          m_lastClose[];
   datetime          m_deferBar[];  // bar on which an EMA exit was deferred by min hold
   double            m_mfe[];       // best favourable price distance reached (price units)

   int               Slot(const ulong ticket)
     {
      for(int i = 0; i < ArraySize(m_tk); i++)
         if(m_tk[i] == ticket)
            return i;
      int n = ArraySize(m_tk);
      ArrayResize(m_tk, n + 1);
      ArrayResize(m_initDist, n + 1);
      ArrayResize(m_lastMod, n + 1);
      ArrayResize(m_lastClose, n + 1);
      ArrayResize(m_deferBar, n + 1);
      ArrayResize(m_mfe, n + 1);
      m_mfe[n] = 0.0;
      m_tk[n] = ticket;
      m_initDist[n] = 0.0;
      m_lastMod[n] = 0;
      m_lastClose[n] = 0;
      m_deferBar[n] = 0;
      return n;
     }

   double            InitialDistance(const int k, const ulong ticket, const double open, const double sl)
     {
      if(m_initDist[k] > 0.0)
         return m_initDist[k];
      double d = 0.0;
      if(HistoryOrderSelect(ticket))
        {
         double osl = HistoryOrderGetDouble(ticket, ORDER_SL);
         if(osl > 0.0)
            d = MathAbs(open - osl);
        }
      if(d <= 0.0 && sl > 0.0)
         d = MathAbs(open - sl);
      m_initDist[k] = d;
      return d;
     }

   void              TryClose(const int k, const ulong ticket, const string reason, const datetime now)
     {
      if(now - m_lastClose[k] < 3)
         return;                     // avoid hammering the server on repeated failures
      m_lastClose[k] = now;
      ClosePositionTicket(ticket, reason);   // logs its own result
     }

public:
   void              ManageSymbol(COgpSymbol *s, const bool emergency, const string emergencyWhy, const bool weekendClose, const datetime now)
     {
      ulong tickets[];
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0 || PositionGetString(POSITION_SYMBOL) != s.sym || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
            continue;
         int n = ArraySize(tickets);
         ArrayResize(tickets, n + 1);
         tickets[n] = t;
        }
      for(int j = 0; j < ArraySize(tickets); j++)
        {
         ulong t = tickets[j];
         if(!PositionSelectByTicket(t))
            continue;
         int k = Slot(t);
         int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
         double open = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl = PositionGetDouble(POSITION_SL);
         double tp = PositionGetDouble(POSITION_TP);
         double fl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
         long held = (long)(TimeCurrent() - (datetime)PositionGetInteger(POSITION_TIME));
         string side = (dir > 0) ? "BUY" : "SELL";

         if(emergency)
           {
            TryClose(k, t, "ACCOUNT EMERGENCY: " + emergencyWhy, now);
            continue;
           }
         if(fl <= -InpPositionEmergencyUSD)
           {
            TryClose(k, t, StringFormat("position emergency: floating %s <= -%s", Usd(fl), Usd(InpPositionEmergencyUSD)), now);
            continue;
           }
         if(weekendClose)
           {
            TryClose(k, t, "Friday pre-weekend close", now);
            continue;
           }
         if(sl <= 0.0)
           {
            double a = (s.dataOk && ArraySize(s.atr) > 1) ? s.atr[1] : 0.0;
            if(a > 0.0)
              {
               double cur = (dir > 0) ? s.tick.bid : s.tick.ask;
               double nsl = cur - dir * InpSlAtrMult * a;
               Journal("RISK", s.sym, StringFormat("#%I64u has no stop-loss - attaching %s", t, Px(s.sym, nsl)));
               if(!ModifyStops(t, nsl, tp, "attach missing SL"))
                  TryClose(k, t, "no stop-loss and SL could not be attached", now);
              }
            else
               TryClose(k, t, "no stop-loss and no ATR to build one", now);
            continue;
           }
         if(!s.dataOk)
            continue;

         //--- maximum favourable excursion (for AFTER_MFE exit mode)
         double curPx = (dir > 0) ? s.tick.bid : s.tick.ask;
         double fav = (dir > 0) ? curPx - open : open - curPx;
         if(fav > m_mfe[k])
            m_mfe[k] = fav;
         double initD = InitialDistance(k, t, open, sl);
         bool isSecond = (StringFind(PositionGetString(POSITION_COMMENT), "#2") >= 0);

         //--- time-hold plan: exit after InpHoldBars M3 bars, no EMA exit / BE / trailing
         if(InpTradePlan == OGP_PLAN_TIME_HOLD)
           {
            datetime pt = (datetime)PositionGetInteger(POSITION_TIME);
            datetime entryBar = (datetime)((long)pt - (long)pt % OGP_M3_SEC);
            long barsHeld = (long)(s.curBar - entryBar) / OGP_M3_SEC;
            if(s.newBar && barsHeld >= InpHoldBars && held >= InpMinHoldSeconds)
              {
               Journal("SIGNAL", s.sym, StringFormat("EXIT %s #%I64u: time exit after %I64d bars", side, t, barsHeld));
               TryClose(k, t, StringFormat("time exit (%I64d bars)", barsHeld), now);
              }
            continue;
           }

         //--- EMA candle-close exit
         bool emaArmed = (InpEmaExitMode == OGP_EMAX_ALWAYS) ||
                         (InpEmaExitMode == OGP_EMAX_AFTER_MFE && initD > 0.0 && m_mfe[k] >= InpEmaExitMinR * initD);
         if(InpEmaExitMode != OGP_EMAX_OFF && emaArmed)
           {
            if(s.newBar)
              {
               bool cond = (dir > 0) ? (s.r[1].close < s.ema[1]) : (s.r[1].close > s.ema[1]);
               m_deferBar[k] = 0;
               if(cond)
                 {
                  string why = StringFormat("M3 %s closed %s %s EMA %s", Ts(s.r[1].time), Px(s.sym, s.r[1].close),
                                            dir > 0 ? "<" : ">", Px(s.sym, s.ema[1]));
                  if(held >= InpMinHoldSeconds)
                    {
                     Journal("SIGNAL", s.sym, StringFormat("EXIT %s #%I64u: %s", side, t, why));
                     TryClose(k, t, "EMA exit: " + why, now);
                     continue;
                    }
                  m_deferBar[k] = s.curBar;
                  Journal("SIGNAL", s.sym, StringFormat("EXIT %s #%I64u deferred: %s, held %I64d s < min hold %d s", side, t, why, held, InpMinHoldSeconds));
                 }
              }
            else
               if(m_deferBar[k] == s.curBar && held >= InpMinHoldSeconds)
                 {
                  TryClose(k, t, "deferred EMA exit (min hold reached)", now);
                  continue;
                 }
           }

         //--- stop management (only after min hold, throttled)
         if(held < InpMinHoldSeconds || now - m_lastMod[k] < InpMinModifySeconds)
            continue;
         double a = s.atr[1];
         double cur = (dir > 0) ? s.tick.bid : s.tick.ask;
         double spread = s.tick.ask - s.tick.bid;
         double minD = MinStopDistance(s.sym);
         double newSl = sl;
         string why = "";
         //--- break-even: generic, or for #2 once TP1 has been reached (AT_SIGNAL mode)
         bool runner = (InpSecondRunner && isSecond);
         bool beTp1 = (InpSecondEntry == OGP_2ND_AT_SIGNAL && InpBeAfterTp1 && isSecond) || runner;
         if(InpUseBreakEven || beTp1)
           {
            double trigR = beTp1 ? (runner ? 1.0 : InpTp1RR) : InpBreakEvenRR;
            if(beTp1 && InpUseBreakEven)
               trigR = MinD(InpTp1RR, InpBreakEvenRR);
            double gain = (dir > 0) ? cur - open : open - cur;
            double be = open + dir * spread;
            bool notYet = (dir > 0) ? (sl < be) : (sl > be);
            if(initD > 0.0 && notYet && m_mfe[k] >= trigR * initD && gain > 0.0 && MathAbs(cur - be) > minD)
              {
               newSl = be;
               why = StringFormat("break-even (ran %s >= %.2fR)", Px(s.sym, m_mfe[k]), trigR);
              }
           }
         bool runnerTrail = runner && initD > 0.0 && m_mfe[k] >= initD;
         if((InpUseTrailing || runnerTrail) && a > 0.0)
           {
            double mult = runnerTrail ? InpRunnerTrailAtr : InpTrailAtrMult;
            double cand = cur - dir * mult * a;
            bool better = (dir > 0) ? (cand > newSl + 0.1 * a) : (cand < newSl - 0.1 * a);
            if(better && MathAbs(cur - cand) > minD)
              {
               newSl = cand;
               why = StringFormat("%sATR trail %.2f x %s", runnerTrail ? "runner " : "", mult, Px(s.sym, a));
              }
           }
         if(newSl != sl)
           {
            m_lastMod[k] = now;
            ModifyStops(t, newSl, tp, why);
           }
        }
     }
  };

#endif
