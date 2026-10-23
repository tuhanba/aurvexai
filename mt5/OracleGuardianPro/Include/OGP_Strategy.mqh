//+------------------------------------------------------------------+
//| OGP_Strategy.mqh - per-symbol data, signal detection, filters    |
//|                                                                  |
//| Signal: EMA(9, Close, M3) crossing the session VWAP (OHLC/4).    |
//|  Confirmed mode (default): sign(EMA-VWAP) differs between closed |
//|   bars [2] and [1]; evaluated once, on the first tick of bar[0]. |
//|  Live mode: sign(liveEMA-liveVWAP) changes tick-to-tick; the     |
//|   baseline is tracked on every tick, one attempt per bar.        |
//| Filters are independent modules; each returns a reason.          |
//+------------------------------------------------------------------+
#ifndef OGP_STRATEGY_MQH
#define OGP_STRATEGY_MQH

enum ENUM_OGP_EVAL
  {
   OGP_EVAL_OK     = 0,
   OGP_EVAL_REJECT = 1,
   OGP_EVAL_CHASED = 2
  };

struct OgpEntryIntent
  {
   int               dir;
   double            entry;
   double            slDist;
   double            tpDist;
   string            source;   // "confirmed" / "live" / "pullback" / "continuation"
   string            detail;
   int               score;    // quality score
   string            grade;    // A / B / C
   double            riskMult; // grade risk multiplier
  };

class COgpSymbol
  {
private:
   int               m_hEma;
   int               m_hAtr;
   int               m_hTr1;
   int               m_hTr2;
   long              m_lastTickMsc;
   datetime          m_lastTickTime;
   int               m_prevSign;
   datetime          m_signAnchor;
   bool              m_firstRun;
   int               m_need;

   int               SignOf(const double diff) const
     {
      if(diff > 0.0)
         return 1;
      if(diff < 0.0)
         return -1;
      return 0;
     }

   bool              TrendOk(const int handle, const ENUM_TIMEFRAMES tf, const int dir, string &txt)
     {
      double e[];
      ArraySetAsSeries(e, true);
      int need = InpTrendSlopeBars + 2;
      if(CopyBuffer(handle, 0, 1, need, e) != need)
        {
         txt = "no data";
         return false;
        }
      double c = iClose(sym, tf, 1);
      if(c <= 0.0)
        {
         txt = "no close";
         return false;
        }
      bool up = (c > e[0] && e[0] > e[InpTrendSlopeBars]);
      bool dn = (c < e[0] && e[0] < e[InpTrendSlopeBars]);
      txt = up ? "UP" : (dn ? "DOWN" : "FLAT");
      return (dir > 0) ? up : dn;
     }

   double            HighestHigh(const int from, const int count) const
     {
      double h = r[from].high;
      for(int i = from + 1; i < from + count && i < ArraySize(r); i++)
         h = MaxD(h, r[i].high);
      return h;
     }

   double            LowestLow(const int from, const int count) const
     {
      double l = r[from].low;
      for(int i = from + 1; i < from + count && i < ArraySize(r); i++)
         l = MinD(l, r[i].low);
      return l;
     }

   bool              BreakoutOk(const int dir, string &why)
     {
      int L = InpBreakoutLookback;
      double a = atr[1];
      double body = r[1].close - r[1].open;
      if(!InpBreakoutRetest)
        {
         double lvl = (dir > 0) ? HighestHigh(2, L) : LowestLow(2, L);
         bool brk = (dir > 0) ? (r[1].close > lvl) : (r[1].close < lvl);
         bool mom = (dir > 0) ? (body >= InpMomentumBodyAtr * a) : (-body >= InpMomentumBodyAtr * a);
         if(brk || mom)
            return true;
         why = StringFormat("breakout filter: no close beyond %s swing %s and no momentum bar", dir > 0 ? "high" : "low", Px(sym, lvl));
         return false;
        }
      for(int k = 2; k <= InpBreakRetestMaxBars + 1; k++)
        {
         double lvl = (dir > 0) ? HighestHigh(k + 1, L) : LowestLow(k + 1, L);
         bool broke = (dir > 0) ? (r[k].close > lvl) : (r[k].close < lvl);
         if(!broke)
            continue;
         double tol = 0.1 * a;
         bool retest = (dir > 0) ? (r[1].low <= lvl + tol && r[1].close > lvl) : (r[1].high >= lvl - tol && r[1].close < lvl);
         if(retest)
            return true;
        }
      why = "breakout filter: no break + retest within " + IntegerToString(InpBreakRetestMaxBars) + " bars";
      return false;
     }

   //--- unfilled FVG in the signal direction within the lookback
   //--- bullish FVG at bar k: low[k] > high[k+2]; still open if no later bar traded through its bottom
   bool              FvgOk(const int dir, const double a, string &why)
     {
      for(int k = 1; k <= InpFvgLookback && k + 2 < ArraySize(r); k++)
        {
         double gapLo = (dir > 0) ? r[k + 2].high : r[k].high;
         double gapHi = (dir > 0) ? r[k].low : r[k + 2].low;
         if(gapHi - gapLo < InpFvgMinAtr * a)
            continue;
         bool filled = false;
         for(int j = 1; j < k && !filled; j++)
            filled = (dir > 0) ? (r[j].low <= gapLo) : (r[j].high >= gapHi);
         if(!filled)
            return true;
        }
      why = StringFormat("FVG filter: no unfilled %s FVG >= %.2f ATR in last %d bars", dir > 0 ? "bullish" : "bearish", InpFvgMinAtr, InpFvgLookback);
      return false;
     }

   //--- order block: last opposite-colour candle before the move (buy: last bearish candle -> its low)
   bool              OrderBlockLevel(const int dir, double &level)
     {
      for(int k = 1; k <= InpSwingLookback && k < ArraySize(r); k++)
        {
         bool opposite = (dir > 0) ? (r[k].close < r[k].open) : (r[k].close > r[k].open);
         if(opposite)
           {
            level = (dir > 0) ? r[k].low : r[k].high;
            return true;
           }
        }
      return false;
     }

public:
   string            sym;
   bool              isGold;
   double            minAtr;
   double            maxAtr;
   double            maxSpread;
   double            slip;
   double            slBuffer;
   CSessionVwap      vwap;
   MqlRates          r[];
   double            ema[];
   double            atr[];
   MqlTick           tick;
   double            vwapLive;
   bool              vwapLiveOk;
   bool              newBar;
   bool              dataOk;
   datetime          curBar;
   //--- re-entry / pullback state
   int               lastEntryDir;
   bool              rearmed;
   datetime          lastEntryBar;
   bool              pbActive;
   int               pbDir;
   int               pbBarsLeft;
   //--- continuation state
   int               contSide;
   int               contSideBars;
   int               contLegCount;
   //--- loss cooldown (same direction)
   datetime          lossCoolUntil;
   int               lossDir;
   //--- second position (retest) state
   bool              s2Active;
   int               s2Dir;
   double            s2Sl;          // shared absolute stop-loss of the signal
   double            s2Tp;          // shared absolute target of the signal
   ulong             s2Ticket1;     // ticket of position #1
   double            s2Entry1;      // entry price of position #1 (#2 must be better)
   datetime          s2Bar1;        // bar of entry #1
   int               s2BarsLeft;
   //--- display
   string            lastSignal;
   string            lastDecision;
   string            trendText;

                     COgpSymbol(void) : m_hEma(INVALID_HANDLE), m_hAtr(INVALID_HANDLE), m_hTr1(INVALID_HANDLE), m_hTr2(INVALID_HANDLE),
                     m_lastTickMsc(0), m_lastTickTime(0), m_prevSign(0), m_signAnchor(0), m_firstRun(true), m_need(0), sym(""),
                     isGold(true), minAtr(0), maxAtr(0), maxSpread(0), slip(0), slBuffer(0), vwapLive(0), vwapLiveOk(false),
                     newBar(false), dataOk(false), curBar(0), lastEntryDir(0), rearmed(true), lastEntryBar(0), pbActive(false),
                     pbDir(0), pbBarsLeft(0), contSide(0), contSideBars(0), contLegCount(0), lossCoolUntil(0), lossDir(0), s2Active(false), s2Dir(0), s2Sl(0), s2Tp(0), s2Ticket1(0), s2Entry1(0), s2Bar1(0),
                     s2BarsLeft(0), lastSignal("-"), lastDecision("-"), trendText("-") {}

   bool              Init(const string s, const bool gold)
     {
      sym = s;
      isGold = gold;
      minAtr    = gold ? InpGoldMinAtr : InpSilverMinAtr;
      maxAtr    = gold ? InpGoldMaxAtr : InpSilverMaxAtr;
      maxSpread = gold ? InpGoldMaxSpread : InpSilverMaxSpread;
      slip      = gold ? InpGoldSlippage : InpSilverSlippage;
      slBuffer  = gold ? InpGoldSlBuffer : InpSilverSlBuffer;
      vwap.Init(s);
      ArraySetAsSeries(r, true);
      ArraySetAsSeries(ema, true);
      ArraySetAsSeries(atr, true);
      int a = InpBreakoutLookback + InpBreakRetestMaxBars + 4;
      int b = InpSwingLookback + 3;
      if(InpFvgLookback + 4 > b)
         b = InpFvgLookback + 4;
      m_need = (a > b) ? a : b;
      if(m_need < 30)
         m_need = 30;

      m_hEma = iMA(s, OGP_SIG_TF, InpEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      m_hAtr = iATR(s, OGP_SIG_TF, InpAtrPeriod);
      m_hTr1 = iMA(s, InpTrendTF, InpTrendEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      m_hTr2 = iMA(s, InpTrendTF2, InpTrendEmaPeriod, 0, MODE_EMA, PRICE_CLOSE);
      if(m_hEma == INVALID_HANDLE || m_hAtr == INVALID_HANDLE || m_hTr1 == INVALID_HANDLE || m_hTr2 == INVALID_HANDLE)
        {
         OgpLog(StringFormat("INIT ERROR %s: indicator handle creation failed (err %d)", s, GetLastError()));
         return false;
        }
      Journal("SYSTEM", s, StringFormat("ready: digits=%d point=%s tick=%s tickValue=%.4f contract=%.2f vol %.2f/%.2f/%.2f stops=%d freeze=%d spread=%d pts exec=%s",
                                        SymDigits(s), DoubleToString(SymPoint(s), SymDigits(s)),
                                        DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE), SymDigits(s)),
                                        SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE), SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE),
                                        SymbolInfoDouble(s, SYMBOL_VOLUME_MIN), SymbolInfoDouble(s, SYMBOL_VOLUME_STEP),
                                        SymbolInfoDouble(s, SYMBOL_VOLUME_MAX), (int)SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL),
                                        (int)SymbolInfoInteger(s, SYMBOL_TRADE_FREEZE_LEVEL), (int)SymbolInfoInteger(s, SYMBOL_SPREAD),
                                        EnumToString((ENUM_SYMBOL_TRADE_EXECUTION)SymbolInfoInteger(s, SYMBOL_TRADE_EXEMODE))));
      return true;
     }

   void              Deinit(void)
     {
      if(m_hEma != INVALID_HANDLE)
         IndicatorRelease(m_hEma);
      if(m_hAtr != INVALID_HANDLE)
         IndicatorRelease(m_hAtr);
      if(m_hTr1 != INVALID_HANDLE)
         IndicatorRelease(m_hTr1);
      if(m_hTr2 != INVALID_HANDLE)
         IndicatorRelease(m_hTr2);
      m_hEma = INVALID_HANDLE;
      m_hAtr = INVALID_HANDLE;
      m_hTr1 = INVALID_HANDLE;
      m_hTr2 = INVALID_HANDLE;
     }

   void              ResetBaseline(const string why)
     {
      if(m_prevSign != 0)
         Journal("SIGNAL", sym, "live cross baseline reset: " + why);
      m_prevSign = 0;
     }

   void              OnReconnect(void)
     {
      ResetBaseline("reconnect");
      vwap.Invalidate();
     }

   //--- load fresh data; returns true only when a NEW tick was processed
   bool              Refresh(const datetime anchor)
     {
      newBar = false;
      if(!SymbolInfoTick(sym, tick) || tick.bid <= 0.0)
        {
         LogThrottled(sym + "tick", "DATA", sym, StringFormat("no tick (err %d)", GetLastError()), 60);
         return false;
        }
      if(tick.time_msc == m_lastTickMsc)
         return false;
      dataOk = false;
      int bars = Bars(sym, OGP_SIG_TF);
      int need = (m_need > InpEmaPeriod * 5) ? m_need : InpEmaPeriod * 5;
      if(bars < need || BarsCalculated(m_hEma) < need || BarsCalculated(m_hAtr) < need)
        {
         LogThrottled(sym + "ready", "DATA", sym, StringFormat("waiting for M3 history / indicators (%d bars, need %d)", bars, need), 60);
         ResetBaseline("data not ready");
         return false;
        }
      ResetLastError();
      if(CopyRates(sym, OGP_SIG_TF, 0, m_need, r) != m_need || CopyBuffer(m_hEma, 0, 0, 3, ema) != 3 || CopyBuffer(m_hAtr, 0, 0, 3, atr) != 3)
        {
         LogThrottled(sym + "copy", "DATA", sym, StringFormat("CopyRates/CopyBuffer failed (err %d)", GetLastError()), 60);
         ResetBaseline("copy failed");
         return false;
        }
      if(ema[1] == EMPTY_VALUE || atr[1] == EMPTY_VALUE || atr[1] <= 0.0)
        {
         LogThrottled(sym + "empty", "DATA", sym, "indicator values empty", 60);
         return false;
        }
      if(m_lastTickTime > 0 && (long)(tick.time - m_lastTickTime) > 180)
         ResetBaseline(StringFormat("tick gap %I64d s", (long)(tick.time - m_lastTickTime)));
      m_lastTickMsc = tick.time_msc;
      m_lastTickTime = tick.time;

      vwapLiveOk = false;
      if(anchor > 0 && vwap.UpdateClosed(anchor, r[1].time))
         vwapLiveOk = vwap.Live(r[0], vwapLive);

      newBar = (r[0].time != curBar);
      if(newBar)
        {
         m_firstRun = (curBar == 0);
         curBar = r[0].time;
         if(InpLogEveryBar)
            Journal("DATA", sym, StringFormat("bar %s C=%s EMA=%s VWAP=%s(%s,%d bars) ATR=%s spread=%s",
                                              Ts(r[1].time), Px(sym, r[1].close), Px(sym, ema[1]),
                                              vwap.Bar1Valid() ? Px(sym, vwap.Bar1()) : "n/a", vwap.VolumeType(), vwap.ClosedCount(),
                                              Px(sym, atr[1]), Px(sym, tick.ask - tick.bid)));
        }
      dataOk = true;
      return true;
     }

   //--- crossover detection (confirmed or live). 0 = none
   int               DetectCross(const datetime anchor)
     {
      bool enoughBars = vwap.ClosedCount() > InpMinBarsAfterReset;
      if(InpEntryMode == OGP_ENTRY_CONFIRMED)
        {
         if(!newBar || m_firstRun || !vwap.Bar2Valid() || !enoughBars)
            return 0;
         int s2 = SignOf(ema[2] - vwap.Bar2());
         int s1 = SignOf(ema[1] - vwap.Bar1());
         return (s2 != 0 && s1 != 0 && s1 != s2) ? s1 : 0;
        }
      //--- live
      if(!vwapLiveOk)
        {
         ResetBaseline("live VWAP unavailable");
         return 0;
        }
      if(anchor != m_signAnchor)
        {
         m_signAnchor = anchor;
         m_prevSign = 0;            // VWAP reset is not a crossover
        }
      int s = SignOf(ema[0] - vwapLive);
      int dir = 0;
      if(s != 0)
        {
         if(m_prevSign != 0 && s != m_prevSign && enoughBars)
            dir = s;
         m_prevSign = s;
        }
      return dir;
     }

   //--- called for every detected cross, accepted or not
   void              OnCrossObserved(const int dir)
     {
      if(lastEntryDir != 0 && dir != lastEntryDir)
         rearmed = true;
      if(s2Active && dir != s2Dir)
         CancelSecond("opposite cross");
      if(pbActive && dir != pbDir)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup cancelled by opposite cross");
        }
     }

   void              OnEntry(const int dir)
     {
      s2Active = false;
      lastEntryDir = dir;
      rearmed = false;
      lastEntryBar = curBar;
      pbActive = false;
     }

   //--- second position: armed after entry #1 in ON_RETEST mode
   void              ArmSecond(const int dir, const double sl, const double tp, const ulong ticket1, const double entry1)
     {
      s2Entry1 = entry1;
      s2Active = true;
      s2Dir = dir;
      s2Sl = sl;
      s2Tp = tp;
      s2Ticket1 = ticket1;
      s2Bar1 = curBar;
      s2BarsLeft = InpRetestMaxBars;
      Journal("SIGNAL", sym, StringFormat("position #2 armed: waiting up to %d bars for a retest of EMA/VWAP (+-%.2f ATR), shared SL %s / target %s",
                                          InpRetestMaxBars, InpRetestZoneAtr, Px(sym, sl), tp > 0.0 ? Px(sym, tp) : "none"));
     }

   void              CancelSecond(const string why)
     {
      if(!s2Active)
         return;
      s2Active = false;
      Journal("SIGNAL", sym, "position #2 cancelled: " + why);
     }

   //--- returns true when the retest condition for position #2 is met now
   bool              CheckSecond(void)
     {
      if(!s2Active || !dataOk)
         return false;
      if(!PositionSelectByTicket(s2Ticket1))
        {
         CancelSecond("position #1 already closed");
         return false;
        }
      if(newBar && curBar != s2Bar1)
        {
         s2BarsLeft--;
         if(s2BarsLeft < 0)
           {
            CancelSecond("no retest within " + IntegerToString(InpRetestMaxBars) + " bars");
            return false;
           }
        }
      if(curBar == s2Bar1 || !vwap.Bar1Valid())
         return false;                       // never on the same bar as entry #1
      double e1 = ema[1], v1 = vwap.Bar1(), a = atr[1];
      if(SignOf(e1 - v1) != s2Dir)
        {
         CancelSecond("EMA crossed back through VWAP (setup invalid)");
         return false;
        }
      //--- position #2 only at a BETTER price than #1 (a real retest, not chasing)
      if((s2Dir > 0 && tick.ask >= s2Entry1) || (s2Dir < 0 && tick.bid <= s2Entry1))
         return false;
      double zoneTop = MaxD(e1, v1) + InpRetestZoneAtr * a;   // buy: pull back down into here
      double zoneBot = MinD(e1, v1) - InpRetestZoneAtr * a;   // sell: pull back up into here
      if(InpRetestNeedsClose)
        {
         if(!newBar)
            return false;
         if(s2Dir > 0)
            return (r[1].low <= zoneTop && r[1].close > v1 && r[1].close > r[1].open);
         return (r[1].high >= zoneBot && r[1].close < v1 && r[1].close < r[1].open);
        }
      if(s2Dir > 0)
         return (tick.ask <= zoneTop && tick.bid > s2Sl);
      return (tick.bid >= zoneBot && tick.ask < s2Sl);
     }

   //--- trend continuation: an existing EMA/VWAP leg pulls back to the EMA and resumes. 0 = none
   int               CheckContinuation(const datetime lastEntryBarAny)
     {
      if(!InpUseContinuation || !newBar || !vwap.Bar1Valid() || m_firstRun)
         return 0;
      double e1 = ema[1], v1 = vwap.Bar1(), a = atr[1];
      int side = SignOf(e1 - v1);
      if(side != contSide)
        {
         contSide = side;
         contSideBars = 1;
         contLegCount = 0;           // a cross starts a new leg
         return 0;
        }
      contSideBars++;
      if(side == 0 || contSideBars < InpContMinBarsSide || contLegCount >= InpContMaxPerLeg)
         return 0;
      if(lastEntryBarAny > 0 && (long)(curBar - lastEntryBarAny) < (long)InpContCooldownBars * OGP_M3_SEC)
         return 0;
      string t = "";
      if(!TrendOk(m_hTr1, InpTrendTF, side, t))
         return 0;                   // continuation only WITH the higher-timeframe trend
      bool touch = (side > 0) ? (r[1].low <= e1 + InpContZoneAtr * a) : (r[1].high >= e1 - InpContZoneAtr * a);
      bool resume = (side > 0) ? (r[1].close > e1 && r[1].close > v1 && r[1].close > r[1].open)
                    : (r[1].close < e1 && r[1].close < v1 && r[1].close < r[1].open);
      return (touch && resume) ? side : 0;
     }

   //--- quality score (0..6): HTF trend, 2nd HTF, VWAP slope, not extended, momentum bar, FVG
   int               QualityScore(const int dir, const double ext, string &txt)
     {
      int sc = 0;
      string t1 = "", t2 = "", fw = "";
      double a = atr[1];
      txt = "";
      if(TrendOk(m_hTr1, InpTrendTF, dir, t1))
        { sc++; txt += "trend "; }
      if(TrendOk(m_hTr2, InpTrendTF2, dir, t2))
        { sc++; txt += "trend2 "; }
      if(vwap.Bar2Valid() && dir * (vwap.Bar1() - vwap.Bar2()) > 0.0)
        { sc++; txt += "vwapSlope "; }
      if(ext <= 0.5 * a)
        { sc++; txt += "notExtended "; }
      if(dir * (r[1].close - r[1].open) >= 0.5 * a)
        { sc++; txt += "momentum "; }
      if(FvgOk(dir, a, fw))
        { sc++; txt += "fvg "; }
      return sc;
     }

   //--- pullback re-entry check on each new bar. 0 = none
   int               CheckPullback(void)
     {
      if(!pbActive || !newBar || !vwap.Bar1Valid())
         return 0;
      pbBarsLeft--;
      if(pbBarsLeft < 0)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup expired");
         return 0;
        }
      double e1 = ema[1], v1 = vwap.Bar1(), a = atr[1];
      if(SignOf(e1 - v1) != pbDir)
        {
         pbActive = false;
         Journal("SIGNAL", sym, "pullback setup invalid: EMA back on the other side of VWAP");
         return 0;
        }
      bool trig = (pbDir > 0) ? (r[1].low <= MaxD(e1, v1) + InpPullbackZoneAtr * a && r[1].close > e1 && r[1].close > v1)
                  : (r[1].high >= MinD(e1, v1) - InpPullbackZoneAtr * a && r[1].close < e1 && r[1].close < v1);
      return trig ? pbDir : 0;
     }

   void              ArmPullback(const int dir)
     {
      pbActive = true;
      pbDir = dir;
      pbBarsLeft = InpPullbackMaxBars;
      Journal("SIGNAL", sym, StringFormat("%s cross skipped (price extended) -> waiting up to %d bars for pullback to EMA/VWAP zone + confirmation",
                                          dir > 0 ? "BUY" : "SELL", InpPullbackMaxBars));
     }

   //--- strategy filters + stop/target. Order of checks = order of reasons.
   ENUM_OGP_EVAL     Evaluate(const int dir, const string source, OgpEntryIntent &it, string &why)
     {
      double a = atr[1];
      double spread = tick.ask - tick.bid;
      it.dir = dir;
      it.source = source;
      it.entry = (dir > 0) ? tick.ask : tick.bid;

      if(InpRequireNewSignal && source != "pullback" && source != "continuation" && lastEntryDir == dir && !rearmed)
        {
         why = "no new independent signal since last " + (dir > 0 ? string("BUY") : string("SELL")) + " entry (needs opposite cross first)";
         return OGP_EVAL_REJECT;
        }
      //--- volatility / spread (safety, always on)
      if(a < minAtr)
        {
         why = StringFormat("volatility too low: ATR %s < %s", Px(sym, a), Px(sym, minAtr));
         return OGP_EVAL_REJECT;
        }
      if(a > maxAtr)
        {
         why = StringFormat("abnormal volatility: ATR %s > %s", Px(sym, a), Px(sym, maxAtr));
         return OGP_EVAL_REJECT;
        }
      if(r[1].high - r[1].low > InpMaxBarRangeAtr * a)
        {
         why = StringFormat("spike bar: range %s > %.1f x ATR", Px(sym, r[1].high - r[1].low), InpMaxBarRangeAtr);
         return OGP_EVAL_REJECT;
        }
      if(spread > maxSpread)
        {
         why = StringFormat("spread %s > max %s", Px(sym, spread), Px(sym, maxSpread));
         return OGP_EVAL_REJECT;
        }
      if(spread > InpMaxSpreadToAtr * a)
        {
         why = StringFormat("spread %s > %.2f x ATR", Px(sym, spread), InpMaxSpreadToAtr);
         return OGP_EVAL_REJECT;
        }
      //--- higher-timeframe trend
      string t15 = "-", t60 = "-";
      if(InpUseTrend && !TrendOk(m_hTr1, InpTrendTF, dir, t15))
        {
         why = StringFormat("%s trend filter: trend %s, signal %s", EnumToString(InpTrendTF), t15, dir > 0 ? "BUY" : "SELL");
         return OGP_EVAL_REJECT;
        }
      if(InpUseTrend2 && !TrendOk(m_hTr2, InpTrendTF2, dir, t60))
        {
         why = StringFormat("%s trend filter: trend %s, signal %s", EnumToString(InpTrendTF2), t60, dir > 0 ? "BUY" : "SELL");
         return OGP_EVAL_REJECT;
        }
      //--- structure break / momentum
      if(InpUseBreakoutFilter && !BreakoutOk(dir, why))
         return OGP_EVAL_REJECT;
      //--- fair value gap confluence (optional)
      if(InpUseFvgFilter && !FvgOk(dir, a, why))
         return OGP_EVAL_REJECT;
      //--- anti-chase
      double vref = (InpEntryMode == OGP_ENTRY_LIVE && vwapLiveOk) ? vwapLive : vwap.Bar1();
      double ext = (dir > 0) ? it.entry - vref : vref - it.entry;
      if(InpUseChaseFilter && ext > InpMaxChaseAtr * a)
        {
         why = StringFormat("price extended %s from VWAP (> %.2f x ATR) - not chasing", Px(sym, ext), InpMaxChaseAtr);
         return OGP_EVAL_CHASED;
        }
      //--- stop-loss: ATR and structure
      double dist = InpSlAtrMult * a;
      string slInfo = StringFormat("ATR stop %s", Px(sym, dist));
      if(InpUseStructureSL)
        {
         double swing = (dir > 0) ? LowestLow(1, InpSwingLookback) - slBuffer : HighestHigh(1, InpSwingLookback) + slBuffer;
         string sname = "swing";
         if(InpSlStructure == OGP_SLS_ORDER_BLOCK)
           {
            double ob = 0.0;
            if(OrderBlockLevel(dir, ob))
              {
               swing = (dir > 0) ? ob - slBuffer : ob + slBuffer;
               sname = "order block";
              }
           }
         double sdist = (dir > 0) ? it.entry - swing : swing - it.entry;
         if(sdist > dist)
           {
            dist = sdist;
            slInfo = StringFormat("structure stop %s (%s %s)", Px(sym, sdist), sname, Px(sym, swing));
           }
        }
      double minDist = MinStopDistance(sym) + spread;
      if(dist < minDist)
         dist = minDist;
      if(dist > InpMaxSlAtrMult * a)
        {
         why = StringFormat("stop too wide: %s > %.1f x ATR (%s)", Px(sym, dist), InpMaxSlAtrMult, slInfo);
         return OGP_EVAL_REJECT;
        }
      it.slDist = dist;
      it.tpDist = (InpTpRR > 0.0) ? MaxD(dist * InpTpRR, minDist) : 0.0;
      string tpInfo = StringFormat("RR %.2f", InpTpRR);
      if(InpTpMode == OGP_TP_VWAP_BAND)
        {
         double sd = vwap.SdBar1();
         if(InpEntryMode == OGP_ENTRY_LIVE)
            vwap.LiveSd(r[0], sd);
         double target = vref + dir * InpTpBandMult * sd;
         double tdist = (dir > 0) ? target - it.entry : it.entry - target;
         double rr = (dist > 0.0) ? tdist / dist : 0.0;
         if(sd <= 0.0 || rr < InpMinTpRR)
           {
            why = StringFormat("VWAP band target %s gives RR %.2f < min %.2f (no room to target)", Px(sym, target), rr, InpMinTpRR);
            return OGP_EVAL_REJECT;
           }
         it.tpDist = MaxD(tdist, minDist);
         tpInfo = StringFormat("VWAP+%.1fsd band, RR %.2f", InpTpBandMult, rr);
        }
      //--- signal quality grade -> risk multiplier
      it.score = QualityScore(dir, ext, it.grade);
      string reasons = it.grade;
      it.grade = (it.score >= InpGradeAMin) ? "A" : ((it.score >= InpGradeBMin) ? "B" : "C");
      it.riskMult = 1.0;
      if(InpUseQualityScore)
        {
         if(it.grade == "B")
            it.riskMult = InpRiskGradeB;
         if(it.grade == "C")
            it.riskMult = InpRiskGradeC;
         if(it.riskMult <= 0.0)
           {
            why = StringFormat("quality grade C (score %d: %s) - skipped", it.score, reasons);
            return OGP_EVAL_REJECT;
           }
        }
      it.detail = StringFormat("grade %s (score %d: %s) %s, TP %s (%s), ATR %s, VWAP %s, EMA %s", it.grade, it.score, reasons, slInfo,
                               it.tpDist > 0.0 ? Px(sym, it.tpDist) : "none", tpInfo, Px(sym, a), Px(sym, vref),
                               Px(sym, (InpEntryMode == OGP_ENTRY_LIVE) ? ema[0] : ema[1]));
      return OGP_EVAL_OK;
     }

   string            TrendSummary(void)
     {
      string a = "-", b = "-";
      TrendOk(m_hTr1, InpTrendTF, 1, a);
      TrendOk(m_hTr2, InpTrendTF2, 1, b);
      trendText = StringSubstr(EnumToString(InpTrendTF), 7) + " " + a + " / " + StringSubstr(EnumToString(InpTrendTF2), 7) + " " + b;
      return trendText;
     }
  };

#endif
