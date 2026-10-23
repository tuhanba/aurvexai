//+------------------------------------------------------------------+
//| OGP_Trade.mqh - risk engine (position sizing) + order execution  |
//+------------------------------------------------------------------+
#ifndef OGP_TRADE_MQH
#define OGP_TRADE_MQH

#define OGP_INF_RISK 1.0e12

//==================================================================//
// Risk accounting                                                  //
//==================================================================//
// Loss (positive number, account currency) of moving `vol` lots from `from` to `to`
double MoveLoss(const string sym, const int dir, const double vol, const double from, const double to)
  {
   double p = 0.0;
   if(!OrderCalcProfit(dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, sym, vol, from, to, p))
      return OGP_INF_RISK;
   return (p < 0.0) ? -p : 0.0;
  }

struct OgpRiskSummary
  {
   double            eaRiskFromEntry;   // EA positions: entry -> SL (+costs), "planned risk"
   double            allRiskFromNow;    // ALL positions: current price -> SL (+slippage), further equity at risk
   int               eaPositions;
   int               otherPositions;
   int               unprotected;       // positions without stop-loss (any magic)
   string            eaSyms[];
   int               eaDirs[];
  };

double SlippageFor(const string sym);       // defined in main file (per-symbol inputs)

void BuildRiskSummary(OgpRiskSummary &rs)
  {
   rs.eaRiskFromEntry = 0.0;
   rs.allRiskFromNow = 0.0;
   rs.eaPositions = 0;
   rs.otherPositions = 0;
   rs.unprotected = 0;
   ArrayResize(rs.eaSyms, 0);
   ArrayResize(rs.eaDirs, 0);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      double vol = PositionGetDouble(POSITION_VOLUME);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double cur = PositionGetDouble(POSITION_PRICE_CURRENT);
      bool mine = ((ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic);
      double slip = mine ? SlippageFor(sym) : 0.0;
      if(mine)
        {
         rs.eaPositions++;
         int n = ArraySize(rs.eaSyms);
         ArrayResize(rs.eaSyms, n + 1);
         ArrayResize(rs.eaDirs, n + 1);
         rs.eaSyms[n] = sym;
         rs.eaDirs[n] = dir;
        }
      else
         rs.otherPositions++;
      if(sl <= 0.0)
        {
         rs.unprotected++;
         rs.allRiskFromNow += OGP_INF_RISK;
         if(mine)
            rs.eaRiskFromEntry += OGP_INF_RISK;
         continue;
        }
      double slipLoss = (slip > 0.0) ? MoveLoss(sym, dir, vol, sl, sl - dir * slip) : 0.0;
      rs.allRiskFromNow += MoveLoss(sym, dir, vol, cur, sl) + slipLoss;
      if(mine)
         rs.eaRiskFromEntry += MoveLoss(sym, dir, vol, open, sl) + slipLoss + InpCommissionPerLot * vol;
     }
  }

// Position sizing. Returns false (with reason) if the trade must be skipped.
// fixedLots > 0: fixed-lot mode (lots never increased, only reduced to fit the caps)
// riskShare: share of the per-signal risk given to this position (risk mode)
bool ComputeLots(const string sym, const int dir, const double entry, const double sl, const double slip,
                 const double fixedLots, const double riskShare,
                 const OgpRiskSummary &rs, CAccountMonitor &acc, COracleRules &rules,
                 double &lots, double &plannedLoss, string &capInfo, string &why)
  {
   double init = InpInitialBalance;
   bool fixedMode = (fixedLots > 0.0);
   double riskMoney = fixedMode ? OGP_INF_RISK : acc.equity * InpRiskPct / 100.0 * riskShare;
   capInfo = fixedMode ? StringFormat("fixed %.2f lots", fixedLots)
                       : StringFormat("base %.2f%% x %.2f of equity=%s", InpRiskPct, riskShare, Usd(riskMoney));

   //--- correlation: other metal already open in the same direction
   for(int i = 0; i < ArraySize(rs.eaSyms); i++)
     {
      if(rs.eaSyms[i] == sym)
         continue;
      if(rs.eaDirs[i] == dir)
        {
         riskMoney *= InpCorrelatedRiskFactor;
         capInfo += StringFormat(", correlated x%.2f", InpCorrelatedRiskFactor);
        }
      else
         if(InpBlockOppositeMetals)
           {
            why = "opposite-direction metal position open (InpBlockOppositeMetals)";
            return false;
           }
     }

   double capTotal  = init * InpMaxTotalRiskPct / 100.0 - rs.eaRiskFromEntry;
   double capSingle = MinD(InpMaxSingleTradeLossUSD, rules.singleTradeLimit * 0.5);
   double capLock   = InpDailyLossLockUSD - (acc.dayStartEquity - acc.equity) - rs.allRiskFromNow;
   double capDaily  = (acc.equity - rules.dailyFloor - InpFloorSafetyUSD) - rs.allRiskFromNow;
   double capShield = (acc.equity - rules.shieldFloor - InpFloorSafetyUSD) - rs.allRiskFromNow;

   double allowed = riskMoney;
   string binding = fixedMode ? "none" : "risk%";
   if(capTotal < allowed)
     {
      allowed = capTotal;
      binding = "combined-risk cap";
     }
   if(capSingle < allowed)
     {
      allowed = capSingle;
      binding = "single-trade cap";
     }
   if(capLock < allowed)
     {
      allowed = capLock;
      binding = "internal daily lock headroom";
     }
   if(capDaily < allowed)
     {
      allowed = capDaily;
      binding = "daily-drawdown headroom";
     }
   if(capShield < allowed)
     {
      allowed = capShield;
      binding = "shield headroom";
     }
   capInfo += StringFormat(" | caps total=%s single=%s lock=%s daily=%s shield=%s -> allowed %s (%s)",
                           Usd(capTotal), Usd(capSingle), Usd(capLock), Usd(capDaily), Usd(capShield), Usd(allowed), binding);
   if(allowed <= 0.0)
     {
      why = "no risk budget left (" + binding + ")";
      return false;
     }

   double lossPerLot = MoveLoss(sym, dir, 1.0, entry, sl) + MoveLoss(sym, dir, 1.0, sl, sl - dir * slip) + InpCommissionPerLot;
   if(lossPerLot <= 0.0 || lossPerLot >= OGP_INF_RISK)
     {
      why = StringFormat("cannot compute loss per lot (OrderCalcProfit err %d)", GetLastError());
      return false;
     }
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = vmin;
   double raw = allowed / lossPerLot;
   double v = NormalizeDouble(MathFloor(raw / step + 1e-9) * step, VolumeDigits(step));
   if(fixedMode)
     {
      double fx = NormalizeDouble(MathFloor(fixedLots / step + 1e-9) * step, VolumeDigits(step));
      if(v >= fx)
         v = fx;
      else
         capInfo += StringFormat(" | fixed %.2f REDUCED to %.2f by %s", fx, v, binding);
     }
   if(v < vmin - 1e-10)
     {
      why = StringFormat("minimum lot %.2f would risk %s > allowed %s", vmin, Usd(vmin * lossPerLot), Usd(allowed));
      return false;
     }
   if(vmax > 0.0 && v > vmax)
      v = NormalizeDouble(MathFloor(vmax / step + 1e-9) * step, VolumeDigits(step));
   double vlimit = SymbolInfoDouble(sym, SYMBOL_VOLUME_LIMIT);
   if(vlimit > 0.0 && v > vlimit)
     {
      why = StringFormat("symbol volume limit %.2f", vlimit);
      return false;
     }
   lots = v;
   plannedLoss = v * lossPerLot;
   capInfo += StringFormat(" | loss/lot %s -> %.2f lots, planned loss %s", Usd(lossPerLot), lots, Usd(plannedLoss));
   if(plannedLoss > rules.singleTradeLimit)
     {
      why = "planned loss exceeds Oracle single-trade limit";
      return false;
     }
   return true;
  }

//==================================================================//
// Execution                                                        //
//==================================================================//
ENUM_ORDER_TYPE_FILLING FillingCandidate(const string sym, const int idx, int &count)
  {
   ENUM_ORDER_TYPE_FILLING list[3];
   count = 0;
   long fm = SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   if((fm & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      list[count++] = ORDER_FILLING_FOK;
   if((fm & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      list[count++] = ORDER_FILLING_IOC;
   list[count++] = ORDER_FILLING_RETURN;
   return list[(idx < count) ? idx : count - 1];
  }

bool TradingPermitted(string &why)
  {
   if(!OgpIsTester() && !TerminalInfoInteger(TERMINAL_CONNECTED))
     {
      why = "terminal not connected";
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      why = "AutoTrading disabled in terminal";
      return false;
     }
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      why = "algo trading not allowed for this EA";
      return false;
     }
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
     {
      why = "account does not allow (expert) trading";
      return false;
     }
   return true;
  }

double MinStopDistance(const string sym)
  {
   double pt = SymPoint(sym);
   long lvl = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   long frz = SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   return (double)((lvl > frz ? lvl : frz) + 2) * pt;
  }

// Send a market DEAL (open when req.position==0, close otherwise).
// slDist/tpDist (price distance) are re-applied to the fresh price on each attempt.
// Never retries TIMEOUT / CONNECTION (a retry could duplicate a filled order).
// slAbs/tpAbs > 0 override the distances with fixed price levels (shared SL/target).
bool SendDeal(MqlTradeRequest &req, const double slDist, const double tpDist, const string ctx, MqlTradeResult &res,
              const double slAbs = 0.0, const double tpAbs = 0.0)
  {
   string sym = req.symbol;
   int fillIdx = 0;
   int maxRetries = (InpOrderRetries > 0) ? InpOrderRetries : 0;
   for(int attempt = 0; attempt <= maxRetries; attempt++)
     {
      MqlTick t;
      if(!SymbolInfoTick(sym, t) || t.bid <= 0.0 || t.ask <= 0.0)
        {
         Journal("ORDER", sym, ctx + " FAILED: no valid quote");
         return false;
        }
      bool isBuy = (req.type == ORDER_TYPE_BUY);
      req.price = NormalizePrice(sym, isBuy ? t.ask : t.bid);
      if(req.position == 0)
        {
         req.sl = (slDist > 0.0) ? NormalizePrice(sym, isBuy ? req.price - slDist : req.price + slDist) : 0.0;
         req.tp = (tpDist > 0.0) ? NormalizePrice(sym, isBuy ? req.price + tpDist : req.price - tpDist) : 0.0;
         if(slAbs > 0.0)
            req.sl = NormalizePrice(sym, slAbs);
         if(tpAbs > 0.0)
            req.tp = NormalizePrice(sym, tpAbs);
         double minD = MinStopDistance(sym);
         if(req.sl > 0.0 && (isBuy ? req.price - req.sl : req.sl - req.price) < minD)
           {
            Journal("ORDER", sym, ctx + " REFUSED: price already too close to the stop-loss " + Px(sym, req.sl));
            return false;
           }
         if(req.tp > 0.0 && (isBuy ? req.tp - req.price : req.price - req.tp) < minD)
           {
            Journal("ORDER", sym, ctx + " REFUSED: price already at/through the target " + Px(sym, req.tp));
            return false;
           }
        }
      int fillCount = 0;
      req.type_filling = FillingCandidate(sym, fillIdx, fillCount);

      MqlTradeCheckResult chk;
      ZeroMemory(chk);
      ResetLastError();
      if(!OrderCheck(req, chk))
        {
         Journal("ORDER", sym, StringFormat("%s REJECTED by OrderCheck: %s (%u) '%s' vol=%.2f margin=%s free=%s",
                                            ctx, RetcodeText(chk.retcode), chk.retcode, chk.comment, req.volume,
                                            Usd(chk.margin), Usd(chk.margin_free)));
         if(chk.retcode == TRADE_RETCODE_INVALID_FILL && fillIdx + 1 < fillCount)
           {
            fillIdx++;
            continue;
           }
         return false;
        }
      ZeroMemory(res);
      ResetLastError();
      bool sent = OrderSend(req, res);
      if(sent && (res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_DONE_PARTIAL || res.retcode == TRADE_RETCODE_PLACED))
        {
         Journal("ORDER", sym, StringFormat("%s OK: %s order #%I64u deal #%I64u vol=%.2f price=%s (req %s) sl=%s tp=%s",
                                            ctx, RetcodeText(res.retcode), res.order, res.deal, res.volume, Px(sym, res.price),
                                            Px(sym, req.price), Px(sym, req.sl), Px(sym, req.tp)));
         return true;
        }
      Journal("ORDER", sym, StringFormat("%s FAILED (attempt %d/%d): %s (%u) '%s' err=%d",
                                         ctx, attempt + 1, maxRetries + 1, RetcodeText(res.retcode), res.retcode, res.comment, GetLastError()));
      if(res.retcode == TRADE_RETCODE_INVALID_FILL && fillIdx + 1 < fillCount)
        {
         fillIdx++;
         continue;
        }
      if(res.retcode != TRADE_RETCODE_REQUOTE && res.retcode != TRADE_RETCODE_PRICE_CHANGED && res.retcode != TRADE_RETCODE_PRICE_OFF)
         return false;
     }
   return false;
  }

bool ModifyStops(const ulong ticket, const double sl, const double tp, const string reason)
  {
   if(!PositionSelectByTicket(ticket))
      return false;
   string sym = PositionGetString(POSITION_SYMBOL);
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action = TRADE_ACTION_SLTP;
   req.position = ticket;
   req.symbol = sym;
   req.sl = (sl > 0.0) ? NormalizePrice(sym, sl) : 0.0;
   req.tp = (tp > 0.0) ? NormalizePrice(sym, tp) : 0.0;
   req.magic = InpMagic;
   ResetLastError();
   bool ok = OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE;
   Journal("MODIFY", sym, StringFormat("#%I64u %s sl=%s tp=%s -> %s (%u) %s", ticket, reason, Px(sym, req.sl), Px(sym, req.tp),
                                       ok ? "OK" : "FAILED", res.retcode, ok ? "" : RetcodeText(res.retcode)));
   return ok;
  }

bool ClosePositionTicket(const ulong ticket, const string reason)
  {
   if(!PositionSelectByTicket(ticket))
      return true;
   string sym = PositionGetString(POSITION_SYMBOL);
   int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
   double vol = PositionGetDouble(POSITION_VOLUME);
   double pl = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = sym;
   req.position  = ticket;
   req.volume    = vol;
   req.type      = (dir > 0) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   req.deviation = (ulong)InpMaxDeviationPoints;
   req.magic     = InpMagic;
   req.comment   = InpOrderComment + " exit";
   req.type_time = ORDER_TIME_GTC;
   bool ok = SendDeal(req, 0.0, 0.0, StringFormat("CLOSE %s #%I64u %.2f lots (%s, floating %s)", dir > 0 ? "BUY" : "SELL",
                                                  ticket, vol, reason, Usd(pl)), res);
   if(ok && PositionSelectByTicket(ticket))
      return false;     // partial
   return ok;
  }

// Opens a position with a mandatory stop-loss. If the fill has no SL, the SL is
// set immediately; if that fails the position is closed (never left unprotected).
bool OpenWithStop(const string sym, const int dir, const double lots, const double slDist, const double tpDist, const string comment,
                  ulong &ticketOut, const double slAbs = 0.0, const double tpAbs = 0.0)
  {
   ticketOut = 0;
   if(slDist <= 0.0 && slAbs <= 0.0)
     {
      Journal("ORDER", sym, "refused: no stop-loss distance");
      return false;
     }
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = sym;
   req.volume    = lots;
   req.type      = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.deviation = (ulong)InpMaxDeviationPoints;
   req.magic     = InpMagic;
   req.comment   = comment;
   req.type_time = ORDER_TIME_GTC;
   if(!SendDeal(req, slDist, tpDist, StringFormat("OPEN %s %.2f lots [%s]", dir > 0 ? "BUY" : "SELL", lots, comment), res, slAbs, tpAbs))
      return false;
   ticketOut = res.order;     // hedging: position ticket == opening order ticket

   //--- verify the stop on the resulting position
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || PositionGetString(POSITION_SYMBOL) != sym || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      if(PositionGetDouble(POSITION_SL) > 0.0)
         continue;
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = (slAbs > 0.0) ? slAbs : ((dir > 0) ? open - slDist : open + slDist);
      double tp = (tpAbs > 0.0) ? tpAbs : ((tpDist > 0.0) ? ((dir > 0) ? open + tpDist : open - tpDist) : 0.0);
      Journal("ORDER", sym, StringFormat("position #%I64u has NO stop-loss after fill - setting it now", t));
      if(!ModifyStops(t, sl, tp, "attach missing SL"))
        {
         Journal("ORDER", sym, StringFormat("could not attach SL to #%I64u - CLOSING it", t));
         ClosePositionTicket(t, "unprotected after fill");
        }
     }
   return true;
  }

#endif
