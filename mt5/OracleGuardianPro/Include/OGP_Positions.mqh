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

         //--- EMA candle-close exit
         if(InpUseEmaExit)
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
         if(InpUseBreakEven)
           {
            double init = InitialDistance(k, t, open, sl);
            double gain = (dir > 0) ? cur - open : open - cur;
            double be = open + dir * spread;
            bool notYet = (dir > 0) ? (sl < be) : (sl > be);
            if(init > 0.0 && notYet && gain >= InpBreakEvenRR * init && MathAbs(cur - be) > minD)
              {
               newSl = be;
               why = StringFormat("break-even (gain %s >= %.2fR)", Px(s.sym, gain), InpBreakEvenRR);
              }
           }
         if(InpUseTrailing && a > 0.0)
           {
            double cand = cur - dir * InpTrailAtrMult * a;
            bool better = (dir > 0) ? (cand > newSl + 0.1 * a) : (cand < newSl - 0.1 * a);
            if(better && MathAbs(cur - cand) > minD)
              {
               newSl = cand;
               why = StringFormat("ATR trail %.2f x %s", InpTrailAtrMult, Px(s.sym, a));
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
