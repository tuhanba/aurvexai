//+------------------------------------------------------------------+
//| OGP_Vwap.mqh - session-anchored VWAP on M3 bars (custom calc)    |
//|                                                                  |
//| MT5 has no built-in VWAP indicator, so it is calculated here:    |
//|   typical_i = (Open_i + High_i + Low_i + Close_i) / 4            |
//|   VWAP      = sum(typical_i * vol_i) / sum(vol_i)                |
//| over every M3 bar from the bar containing the anchor (session    |
//| start) to:                                                       |
//|   - the last CLOSED bar  -> closed VWAP (Bar1/Bar2 values), used |
//|     by confirmed mode, filters and exits;                        |
//|   - the forming bar with its current OHLC/volume -> live VWAP,   |
//|     used by live mode only.                                      |
//| Volume: Auto uses real volume only if every checked closed bar   |
//| has real_volume > 0, otherwise tick volume. The choice is shown  |
//| on the dashboard. Real-only with no real volume => VWAP invalid  |
//| (never silently substituted).                                    |
//+------------------------------------------------------------------+
#ifndef OGP_VWAP_MQH
#define OGP_VWAP_MQH

class CSessionVwap
  {
private:
   string            m_symbol;
   bool              m_volumeKnown;
   bool              m_useReal;
   datetime          m_anchorBar;
   datetime          m_lastClosed;
   bool              m_cacheValid;
   double            m_cumPV;
   double            m_cumV;
   double            m_cumPV2;      // sum(vol * typical^2) for the standard deviation bands
   int               m_closedCount;
   double            m_sdBar1;
   double            m_vwapBar1;
   double            m_vwapBar2;

   double            Typical(const MqlRates &r) const { return (r.open + r.high + r.low + r.close) / 4.0; }
   double            BarVolume(const MqlRates &r) const { return m_useReal ? (double)r.real_volume : (double)r.tick_volume; }

   bool              DetermineVolumeMode(void)
     {
      if(InpVwapVolume == OGP_VOL_TICK)
        {
         m_useReal = false;
         m_volumeKnown = true;
         return true;
        }
      if(InpVwapVolume == OGP_VOL_REAL)
        {
         m_useReal = true;
         m_volumeKnown = true;
         return true;
        }
      MqlRates rr[];
      int n = CopyRates(m_symbol, OGP_SIG_TF, 1, 200, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "volchk", "DATA", m_symbol, StringFormat("VWAP: cannot read M3 history to choose volume source (err %d)", GetLastError()), 60);
         return false;
        }
      int zeroReal = 0;
      for(int i = 0; i < n; i++)
         if(rr[i].real_volume <= 0)
            zeroReal++;
      bool useReal = (zeroReal == 0);
      if(!m_volumeKnown || useReal != m_useReal)
         Journal("DATA", m_symbol, StringFormat("VWAP volume source: %s (auto: %d bars checked, %d without real volume)",
                                                useReal ? "REAL" : "TICK", n, zeroReal));
      m_useReal = useReal;
      m_volumeKnown = true;
      return true;
     }

public:
                     CSessionVwap(void) : m_symbol(""), m_volumeKnown(false), m_useReal(false), m_anchorBar(0), m_lastClosed(0),
                     m_cacheValid(false), m_cumPV(0), m_cumV(0), m_cumPV2(0), m_closedCount(0), m_sdBar1(0), m_vwapBar1(0), m_vwapBar2(0) {}

   void              Init(const string sym) { m_symbol = sym; m_volumeKnown = false; Invalidate(); }
   void              Invalidate(void) { m_cacheValid = false; m_anchorBar = 0; m_lastClosed = 0; }
   string            VolumeType(void) const { return m_volumeKnown ? (m_useReal ? "REAL" : "TICK") : "?"; }
   int               ClosedCount(void) const { return m_closedCount; }
   datetime          AnchorBar(void) const { return m_anchorBar; }
   bool              Bar1Valid(void) const { return m_cacheValid && m_closedCount >= 1; }
   bool              Bar2Valid(void) const { return m_cacheValid && m_closedCount >= 2; }
   double            Bar1(void) const { return m_vwapBar1; }
   double            Bar2(void) const { return m_vwapBar2; }
   //--- volume-weighted standard deviation: sqrt(sum(v*tp^2)/sum(v) - vwap^2) (TradingView band basis)
   double            SdBar1(void) const { return m_sdBar1; }
   bool              LiveSd(const MqlRates &bar0, double &sd) const
     {
      if(!m_cacheValid || bar0.time < m_anchorBar)
         return false;
      double v = BarVolume(bar0), tp = Typical(bar0);
      double vv = m_cumV + v;
      if(vv <= 0.0)
         return false;
      double mean = (m_cumPV + tp * v) / vv;
      double var = (m_cumPV2 + tp * tp * v) / vv - mean * mean;
      sd = (var > 0.0) ? MathSqrt(var) : 0.0;
      return true;
     }

   bool              UpdateClosed(const datetime anchor, const datetime lastClosed)
     {
      datetime anchorBar = (datetime)((long)anchor - ((long)anchor % OGP_M3_SEC));
      if(m_cacheValid && anchorBar == m_anchorBar && lastClosed == m_lastClosed)
         return true;
      if(anchorBar != m_anchorBar && InpVwapVolume == OGP_VOL_AUTO)
         m_volumeKnown = false;
      if(!m_volumeKnown && !DetermineVolumeMode())
        {
         m_cacheValid = false;
         return false;
        }
      m_anchorBar = anchorBar;
      m_lastClosed = lastClosed;
      m_cumPV = 0.0;
      m_cumV = 0.0;
      m_cumPV2 = 0.0;
      m_sdBar1 = 0.0;
      m_closedCount = 0;
      m_vwapBar1 = 0.0;
      m_vwapBar2 = 0.0;
      if(lastClosed < anchorBar)
        {
         m_cacheValid = true;
         return true;
        }
      MqlRates rr[];
      ResetLastError();
      int n = CopyRates(m_symbol, OGP_SIG_TF, anchorBar, lastClosed, rr);
      if(n <= 0)
        {
         LogThrottled(m_symbol + "vwapcopy", "DATA", m_symbol, StringFormat("VWAP: CopyRates M3 %s..%s failed (%d, err %d)",
                      Ts(anchorBar), Ts(lastClosed), n, GetLastError()), 60);
         m_cacheValid = false;
         return false;
        }
      for(int i = 0; i < n; i++)
        {
         if(rr[i].time < anchorBar || rr[i].time > lastClosed)
            continue;
         double v = BarVolume(rr[i]);
         double tp = Typical(rr[i]);
         m_cumPV += tp * v;
         m_cumPV2 += tp * tp * v;
         m_cumV  += v;
         m_closedCount++;
         if(m_cumV > 0.0)
           {
            m_vwapBar2 = m_vwapBar1;
            m_vwapBar1 = m_cumPV / m_cumV;
           }
        }
      if(m_closedCount > 0 && m_cumV <= 0.0)
        {
         LogThrottled(m_symbol + "vwapzero", "DATA", m_symbol, StringFormat("VWAP invalid: %d bars since %s with zero %s volume",
                      m_closedCount, Ts(anchorBar), m_useReal ? "REAL" : "TICK"), 300);
         m_cacheValid = false;
         return false;
        }
      if(m_cumV > 0.0)
        {
         double var = m_cumPV2 / m_cumV - m_vwapBar1 * m_vwapBar1;
         m_sdBar1 = (var > 0.0) ? MathSqrt(var) : 0.0;
        }
      m_cacheValid = true;
      return true;
     }

   bool              Live(const MqlRates &bar0, double &vwap) const
     {
      if(!m_cacheValid || bar0.time < m_anchorBar)
         return false;
      double v = BarVolume(bar0);
      double vv = m_cumV + v;
      if(vv <= 0.0)
         return false;
      vwap = (m_cumPV + Typical(bar0) * v) / vv;
      return true;
     }
  };

#endif
