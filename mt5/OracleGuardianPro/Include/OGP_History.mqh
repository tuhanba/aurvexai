//+------------------------------------------------------------------+
//| OGP_History.mqh - account deal history analysis                  |
//|                                                                  |
//| 1) EquityUpperBound(from,to): a CONSERVATIVE UPPER BOUND of the  |
//|    account equity at any moment in [from,to], built from:        |
//|      balance timeline (deal history, incl. deposits/withdrawals) |
//|    + for every position open in the interval, its best possible  |
//|      floating P/L from M1 high/low extremes (OrderCalcProfit).   |
//|    For a moment t: equity(t) = balance(t) + sum(floating of      |
//|    positions open at t) <= maxBalance(over a position's life) +  |
//|    sum(max floating of every position overlapping it).           |
//|    Used when the EA did not observe equity itself (first start,  |
//|    restarts, disconnections, missed UTC midnight). A bound that  |
//|    is too high only makes the shield/daily floor stricter.       |
//|                                                                  |
//| 2) ComputeCycleStats(): realized net P/L per UTC day since the   |
//|    payout-cycle start, valid days, best day, EA trades today.    |
//+------------------------------------------------------------------+
#ifndef OGP_HISTORY_MQH
#define OGP_HISTORY_MQH

struct OgpPosInfo
  {
   long              id;
   string            sym;
   int               dir;          // +1 buy, -1 sell
   double            volume;       // max volume seen
   double            priceOpen;    // volume weighted entry
   datetime          tOpen;
   datetime          tClose;       // 0 while still open
   bool              open;
  };

double DealNet(const ulong d)
  {
   return HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_COMMISSION) +
          HistoryDealGetDouble(d, DEAL_SWAP) + HistoryDealGetDouble(d, DEAL_FEE);
  }

bool IsTradeDeal(const long type) { return (type == DEAL_TYPE_BUY || type == DEAL_TYPE_SELL); }

//==================================================================//
class CHistoryAnalyzer
  {
private:
   datetime          m_dealTime[];
   double            m_balAfter[];
   double            m_balBeforeFirst;
   OgpPosInfo        m_pos[];

   int               FindPos(const long id)
     {
      for(int i = 0; i < ArraySize(m_pos); i++)
         if(m_pos[i].id == id)
            return i;
      return -1;
     }

   int               AddPos(const long id)
     {
      int n = ArraySize(m_pos);
      ArrayResize(m_pos, n + 1);
      m_pos[n].id = id;
      m_pos[n].sym = "";
      m_pos[n].dir = 0;
      m_pos[n].volume = 0.0;
      m_pos[n].priceOpen = 0.0;
      m_pos[n].tOpen = 0;
      m_pos[n].tClose = 0;
      m_pos[n].open = false;
      return n;
     }

   //--- loads deals + positions; history window starts `lookbackFrom`
   bool              Load(const datetime lookbackFrom, string &err)
     {
      ArrayResize(m_dealTime, 0);
      ArrayResize(m_balAfter, 0);
      ArrayResize(m_pos, 0);
      if(!HistorySelect(lookbackFrom, TimeCurrent() + 86400))
        {
         err = StringFormat("HistorySelect failed (err %d)", GetLastError());
         return false;
        }
      int n = HistoryDealsTotal();
      ArrayResize(m_dealTime, n);
      ArrayResize(m_balAfter, n);
      double nets[];
      ArrayResize(nets, n);
      for(int i = 0; i < n; i++)
        {
         ulong d = HistoryDealGetTicket(i);
         m_dealTime[i] = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
         nets[i] = DealNet(d);
         long type = HistoryDealGetInteger(d, DEAL_TYPE);
         if(!IsTradeDeal(type))
            continue;
         long pid   = HistoryDealGetInteger(d, DEAL_POSITION_ID);
         long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
         double vol = HistoryDealGetDouble(d, DEAL_VOLUME);
         double prc = HistoryDealGetDouble(d, DEAL_PRICE);
         int k = FindPos(pid);
         if(k < 0)
            k = AddPos(pid);
         m_pos[k].sym = HistoryDealGetString(d, DEAL_SYMBOL);
         if(entry == DEAL_ENTRY_IN)
           {
            if(m_pos[k].tOpen == 0)
               m_pos[k].tOpen = m_dealTime[i];
            m_pos[k].dir = (type == DEAL_TYPE_BUY) ? 1 : -1;
            double tv = m_pos[k].volume + vol;
            if(tv > 0.0)
               m_pos[k].priceOpen = (m_pos[k].priceOpen * m_pos[k].volume + prc * vol) / tv;
            m_pos[k].volume = tv;
           }
         else
            if(entry == DEAL_ENTRY_INOUT)       // netting reversal: approximate as new direction
              {
               m_pos[k].dir = (type == DEAL_TYPE_BUY) ? 1 : -1;
               m_pos[k].priceOpen = prc;
               m_pos[k].volume = MaxD(m_pos[k].volume, vol);
               if(m_pos[k].tOpen == 0)
                  m_pos[k].tOpen = m_dealTime[i];
              }
            else                                // OUT / OUT_BY
               m_pos[k].tClose = m_dealTime[i];
        }
      //--- balance timeline walking backwards from the current balance
      double bal = AccountInfoDouble(ACCOUNT_BALANCE);
      for(int i = n - 1; i >= 0; i--)
        {
         m_balAfter[i] = bal;
         bal -= nets[i];
        }
      m_balBeforeFirst = bal;

      //--- currently open positions
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t == 0)
            continue;
         long pid = PositionGetInteger(POSITION_IDENTIFIER);
         int k = FindPos(pid);
         if(k < 0)
            k = AddPos(pid);
         m_pos[k].sym = PositionGetString(POSITION_SYMBOL);
         m_pos[k].dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
         m_pos[k].priceOpen = PositionGetDouble(POSITION_PRICE_OPEN);
         m_pos[k].volume = MaxD(m_pos[k].volume, PositionGetDouble(POSITION_VOLUME));
         datetime pt = (datetime)PositionGetInteger(POSITION_TIME);
         if(m_pos[k].tOpen == 0 || pt < m_pos[k].tOpen)
            m_pos[k].tOpen = pt;
         m_pos[k].open = true;
         m_pos[k].tClose = 0;
        }
      return true;
     }

   double            BalanceAt(const datetime t) const
     {
      double b = m_balBeforeFirst;
      for(int i = 0; i < ArraySize(m_dealTime); i++)
        {
         if(m_dealTime[i] > t)
            break;
         b = m_balAfter[i];
        }
      return b;
     }

   double            MaxBalance(const datetime a, const datetime b) const
     {
      double m = BalanceAt(a);
      for(int i = 0; i < ArraySize(m_dealTime); i++)
        {
         if(m_dealTime[i] <= a)
            continue;
         if(m_dealTime[i] > b)
            break;
         m = MaxD(m, m_balAfter[i]);
        }
      return m;
     }

   //--- best floating P/L of one position inside [a,b] from M1 extremes
   bool              MaxFloating(const OgpPosInfo &p, const datetime a, const datetime b, double &best, string &err)
     {
      if(p.priceOpen <= 0.0 || p.volume <= 0.0 || p.sym == "")
        {
         err = StringFormat("position %I64d: entry price/volume unknown (opened before history window)", p.id);
         return false;
        }
      MqlRates rr[];
      datetime a0 = (datetime)((long)a - (long)a % 60);
      int n = CopyRates(p.sym, PERIOD_M1, a0, b, rr);
      if(n <= 0)
         n = CopyRates(p.sym, PERIOD_M1, a0, 1, rr);
      if(n <= 0)
        {
         err = StringFormat("position %I64d %s: no M1 data for %s..%s (err %d)", p.id, p.sym, Ts(a), Ts(b), GetLastError());
         return false;
        }
      double ext = (p.dir > 0) ? rr[0].high : rr[0].low;
      for(int i = 1; i < n; i++)
        {
         if(p.dir > 0)
            ext = MaxD(ext, rr[i].high);
         else
            ext = MinD(ext, rr[i].low);
        }
      double pr = 0.0;
      if(!OrderCalcProfit(p.dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, p.sym, p.volume, p.priceOpen, ext, pr))
        {
         err = StringFormat("position %I64d %s: OrderCalcProfit failed (err %d)", p.id, p.sym, GetLastError());
         return false;
        }
      best = pr;
      return true;
     }

public:
   //--- conservative upper bound of equity over [from,to]
   bool              EquityUpperBound(const datetime from, const datetime to, double &bound, string &err)
     {
      bound = 0.0;
      err = "";
      if(!Load(from - 120 * 86400, err))
         return false;

      datetime a[], b[];
      double   fm[];
      int      idx[];
      int cnt = 0;
      for(int k = 0; k < ArraySize(m_pos); k++)
        {
         datetime end = m_pos[k].open ? to : (m_pos[k].tClose > 0 ? m_pos[k].tClose : to);
         datetime beg = m_pos[k].tOpen;
         if(beg == 0)
            beg = from;                     // opened before the history window
         if(beg > to || end < from)
            continue;
         ArrayResize(a, cnt + 1);
         ArrayResize(b, cnt + 1);
         ArrayResize(fm, cnt + 1);
         ArrayResize(idx, cnt + 1);
         a[cnt] = (beg > from) ? beg : from;
         b[cnt] = (end < to) ? end : to;
         idx[cnt] = k;
         if(!MaxFloating(m_pos[k], a[cnt], b[cnt], fm[cnt], err))
            return false;
         cnt++;
        }

      bound = MaxBalance(from, to);
      for(int i = 0; i < cnt; i++)
        {
         double s = MaxBalance(a[i], b[i]);
         for(int j = 0; j < cnt; j++)
            if(a[j] <= b[i] && b[j] >= a[i])
               s += fm[j];
         bound = MaxD(bound, s);
        }
      return true;
     }

   //--- equity of the account at a past moment is unknown; this returns
   //--- the conservative upper bound in a small window around it
   bool              EquityUpperBoundAround(const datetime t, const int halfWindowSec, double &bound, string &err)
     {
      return EquityUpperBound(t - halfWindowSec, t + halfWindowSec, bound, err);
     }
  };

//==================================================================//
// Cycle statistics (realized P/L per UTC day)                      //
//==================================================================//
struct OgpCycleStats
  {
   bool              ok;
   datetime          computedAt;
   double            cycleNet;        // realized net since cycle start
   double            todayNet;        // realized net today (UTC)
   double            bestDayNet;
   datetime          bestDayKey;
   int               validDays;
   int               tradingDays;
   int               eaEntriesToday;
   int               eaEntriesCycle;
  };

bool ComputeCycleStats(const datetime cycleStart, const datetime todayKeyUtc, const double validThreshold, OgpCycleStats &st)
  {
   st.ok = false;
   st.cycleNet = 0.0;
   st.todayNet = 0.0;
   st.bestDayNet = 0.0;
   st.bestDayKey = 0;
   st.validDays = 0;
   st.tradingDays = 0;
   st.eaEntriesToday = 0;
   st.eaEntriesCycle = 0;
   st.computedAt = TimeCurrent();

   if(!HistorySelect(cycleStart, TimeCurrent() + 86400))
      return false;
   datetime keys[];
   double   nets[];
   int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0)
         continue;
      long type = HistoryDealGetInteger(d, DEAL_TYPE);
      if(!IsTradeDeal(type))
         continue;
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      if(t < cycleStart)
         continue;
      datetime key = UtcDayKey(t);
      double net = DealNet(d);
      st.cycleNet += net;
      int k = -1;
      for(int j = 0; j < ArraySize(keys); j++)
         if(keys[j] == key)
           {
            k = j;
            break;
           }
      if(k < 0)
        {
         k = ArraySize(keys);
         ArrayResize(keys, k + 1);
         ArrayResize(nets, k + 1);
         keys[k] = key;
         nets[k] = 0.0;
        }
      nets[k] += net;
      //--- count SIGNALS: the second position of a signal ("#2") is not a new trade
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN && (ulong)HistoryDealGetInteger(d, DEAL_MAGIC) == InpMagic &&
         StringFind(HistoryDealGetString(d, DEAL_COMMENT), "#2") < 0)
        {
         st.eaEntriesCycle++;
         if(key == todayKeyUtc)
            st.eaEntriesToday++;
        }
     }
   st.tradingDays = ArraySize(keys);
   for(int j = 0; j < ArraySize(keys); j++)
     {
      if(keys[j] == todayKeyUtc)
         st.todayNet = nets[j];
      if(nets[j] >= validThreshold)
         st.validDays++;
      if(nets[j] > st.bestDayNet)
        {
         st.bestDayNet = nets[j];
         st.bestDayKey = keys[j];
        }
     }
   st.ok = true;
   return true;
  }

#endif
