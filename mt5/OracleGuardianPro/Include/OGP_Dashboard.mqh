//+------------------------------------------------------------------+
//| OGP_Dashboard.mqh - on-chart status panel (labels)               |
//+------------------------------------------------------------------+
#ifndef OGP_DASHBOARD_MQH
#define OGP_DASHBOARD_MQH

#define OGP_DASH_PREFIX "OGP_DASH_"
#define OGP_DASH_LINES  40

class CDashboard
  {
private:
   int               m_used;
   bool              m_created;

   string            Name(const int i) const { return OGP_DASH_PREFIX + IntegerToString(i); }

public:
                     CDashboard(void) : m_used(0), m_created(false) {}

   void              Create(void)
     {
      if(!InpShowDashboard || m_created)
         return;
      string bg = OGP_DASH_PREFIX + "BG";
      ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, InpDashX - 4);
      ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, InpDashY - 4);
      ObjectSetInteger(0, bg, OBJPROP_XSIZE, 560);
      ObjectSetInteger(0, bg, OBJPROP_YSIZE, 40);
      ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, C'20,24,32');
      ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, bg, OBJPROP_COLOR, C'70,80,100');
      ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bg, OBJPROP_HIDDEN, true);
      for(int i = 0; i < OGP_DASH_LINES; i++)
        {
         string n = Name(i);
         ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
         ObjectSetInteger(0, n, OBJPROP_XDISTANCE, InpDashX);
         ObjectSetInteger(0, n, OBJPROP_YDISTANCE, InpDashY + i * (InpDashFontSize + 6));
         ObjectSetString(0, n, OBJPROP_FONT, "Consolas");
         ObjectSetInteger(0, n, OBJPROP_FONTSIZE, InpDashFontSize);
         ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, n, OBJPROP_HIDDEN, true);
         ObjectSetString(0, n, OBJPROP_TEXT, " ");
        }
      m_created = true;
     }

   void              Render(const string &lines[], const color &cols[])
     {
      if(!InpShowDashboard || !m_created)
         return;
      int n = ArraySize(lines);
      if(n > OGP_DASH_LINES)
         n = OGP_DASH_LINES;
      for(int i = 0; i < OGP_DASH_LINES; i++)
        {
         string nm = Name(i);
         ObjectSetString(0, nm, OBJPROP_TEXT, (i < n) ? lines[i] : " ");
         if(i < n)
            ObjectSetInteger(0, nm, OBJPROP_COLOR, cols[i]);
        }
      ObjectSetInteger(0, OGP_DASH_PREFIX + "BG", OBJPROP_YSIZE, n * (InpDashFontSize + 6) + 8);
      m_used = n;
      ChartRedraw(0);
     }

   void              Destroy(void)
     {
      ObjectsDeleteAll(0, OGP_DASH_PREFIX);
      m_created = false;
     }
  };

//--- small builder helpers
string g_dl[];
color  g_dc[];

void DashAdd(const string text, const color c = clrSilver)
  {
   int n = ArraySize(g_dl);
   ArrayResize(g_dl, n + 1);
   ArrayResize(g_dc, n + 1);
   g_dl[n] = text;
   g_dc[n] = c;
  }

void DashClear()
  {
   ArrayResize(g_dl, 0);
   ArrayResize(g_dc, 0);
  }

#endif
