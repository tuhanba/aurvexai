# AURVEX FTMO — HER ŞEY TEK DOSYADA (master)

> Tek dosyada: sistem özeti, tüm araştırma (kabul/reddet), KAPI-1 canlı analizi,
> güncel config (enstrüman-başına inputlar), v3.14 mimarisi + değişiklik raporu +
> demo listesi + geri-dönüş planı, **tam EA kodu**, governor referans modeli + testler,
> yolculuk/dürüst değerlendirme ve sonraki adımlar. Kaynak branch: `ftmo-final`.
> Son güncelleme: 2026-09-29.

---

# BÖLÜM 0 — Bir bakışta

- **Ne:** FTMO **$25k 2-Step Challenge** için MT5 Expert Advisor.
- **Strateji:** metaller (XAU/XAG) → **ORB** (ilk saat açılış-aralığı kırılımı);
  endeksler (GER40/JP225) → **PDHL** (önceki-gün yüksek/alçak kırılımı). No-TP,
  seans-kapanış çıkışı, drawdown'da de-risk, FTMO loss guard.
- **Edge:** gerçek ama **modest** (~+0.15R proxy, fat-tail — kâr nadir büyük
  koşuculardan gelir). Giriş **öngörülemez** (capstone kanıtı).
- **Canlı durum:** $25k gerçek FTMO Challenge (hesap 541438670). KAPI-1'de ilk 31
  işlem net **−%2.5** (kontrollü; zemine uzak). Canlıda hâlâ arkadaşın **v3.11**'i.
- **KAPI-1 kararı:** BTCUSD + US100 çıkarıldı; evren **4 enstrüman** (XAU/XAG/GER40/JP225);
  gold + JP225 vol-filtreleri açıldı.
- **Kod:** `v3.13_final` (canlı-hedef) + `v3.14_safety_candidate` (governor, default-OFF,
  demo bekliyor). Governor CANLIYA ALINMADI.

**Dürüst tek cümle:** Bu iyi bir motor ve edge gerçek ama modest; onu büyütmenin yolu
daha akıllı bir giriş DEĞİL (kanıtlandı) — düşük risk + gerçek veri + zaman + runway +
disiplin. Hiçbir kod, modest bir edge'i "işini bırakıp yaşayacağın gelire" çeviremez.

---

# BÖLÜM 1 — Strateji detayı

**ORB (XAU, XAG):**
- 00:00–01:00 UTC ilk saat yüksek/alçak = aralık.
- 01:00 UTC sonrası aralığın **ilk kırılımı**: yukarı → buy-stop, aşağı → sell-stop (OCO).
  Biri dolunca diğeri iptal. Armlamadan önce kırıldıysa → o gün pas (no-chase).
- Stop = aralığın karşı ucu. TP yok. Çıkış: 00:00 UTC seans kapanışı / stop / Cuma 20:00.

**PDHL (GER40, JP225):**
- Dünün (takvim önceki gün) yüksek/alçağı; ATR(14)×1.5 stop.
- Seans penceresinde ilk kırılım. GER40: yaz 07:00–15:30 / kış 08:00–16:30 UTC (oto-DST).
  JP225: 00:00–06:00 UTC (Tokyo, DST yok). Pazartesi işlem yok (calendar-PDHL).

**Risk/güvenlik (ortak çekirdek):**
- Sizing: `g_initBal × RiskPct/100 × RiskMultiplier()`. RiskMultiplier YALNIZCA azaltır
  (drawdown'da de-risk 3%→0.6×, 6%→0.35×; hedefe yakınken profit-lock).
- FTMO loss guard: equity −%9'da (overall) / günlük −%4'te durur (LossBufferPct=1).
- Restart-safe (GlobalVariable), oto-DST, margin/retcode/freeze guard, journaling.

---

# BÖLÜM 2 — Tüm araştırma (kabul / reddet / kararsız)

## 2.1 Master tablo
| # | hipotez | karar | gerekçe |
|---|---|---|---|
| H1 | BTC multi-session (0/3/13 UTC) | **KARARSIZ** | proxy faydalı ama hedging varsayımına bağlı; gerçek `ACCOUNT_MARGIN_MODE` + demo doğrulanmadı |
| H2 | Runner Carry (gold+silver) | **REDDEDİLDİ** | tam-örneklem ~0R, monster-bağımlı, yıl-tutarsız |
| H3 | Profit-Funded Acceleration | **KOŞULLU ADAY** | küçük sağ-kuyruk kazancı, medyan düz/aşağı; parametreler keskin tanımlı değil; proxy seri |
| H4 | Account-Level Risk Governor | **KABUL (tasarım)** | hesap-düzeyi cap yoktu; dinamik headroom + OCO + korelasyon grubu |
| H5 | Alpha sleeves (yeni giriş-edge) | **REDDEDİLDİ** | giriş öngörülemez (capstone); 12+ fikir OOS çöktü |
| — | Challenge vs Funded ayrımı | **KABUL** | iki ayrı objective; `AccountPhase` ile ayrılır |
| — | Scalp motoru | **NO-GO** | 4 kampanya, net-negatif |

## 2.2 CAPSTONE — en önemli matematiksel kanıt
Kendi birleşik TA modelimizi kurduk (öğrenilen ağırlıklar):
- Özelliklerin işlem-R ile korelasyonu **~0** (0.005–0.05).
- Skor OOS'ta kazananı kaybedenden **ayıramıyor** (top %50 = baz).
- **Ama çıplak kırılım anlamlı** (CI [+0.022, +0.278], sıfırı dışlıyor).
- **Ters matematik:** en büyük %20 koşucu ile kaybedenler, girişten önce **AYNI**
  görünüyor (~0σ fark). Koşucunun ön-imzası yok.
- **Sonuç:** hangi kırılımın koşacağı önceden **öngörülemez.** Her giriş-filtresi OOS'ta
  çöküyor — bulamamamız değil, imzanın olmaması.

## 2.3 Doğrulanmış lever'lar (sisteme girdi)
| lever | sonuç |
|---|---|
| Gold düşük-vol filtresi (MinRangeMedMult=1.0) | OOS +0.19R → +0.36R; CI alt sınırı >0; cost-toleransı 2× |
| JP225 gerçek edge + filtresi | +0.086R OOS (EA-matching, CI sıfırı dışlıyor) |
| Dağılım: NAS100/US100 kes | negatif beklenti; break-even %0.013 (her spread öldürür) |
| Dağılım: JP225 ağırlık ↑ | 0.30 → 0.45 monoton faydalı |
| De-risk (drawdown'da kıs) | 3/0.6/6/0.35; blok-bootstrap +6.5pt; asla artırma |
| Maliyet break-even tablosu | enstrüman-başına tolere edilebilir maks spread |

## 2.4 Reddedilenler (kanıtla)
FBR (look-ahead artifact), çapraz-onay (artifact), vol-targeting (OOS geçişi düşürür),
HTF trend-hizası (CI sıfırı kesiyor), coil/inside-TA (CI sıfırı), align+range (örneklem
çöküyor), cross-instrument confluence (fayda yok/BTC'de zarar), pyramiding (+0.19→−0.40),
metal param-tuning (overfit), enerji/emtia range (kâra dönmüyor), rejim-adaptif (CI sıfırı),
scalp (net-negatif). **Look-ahead artifact çıkanlar yeniden ambalajlanmadı.**

## 2.5 Funded Growth Mode (H3) — düzeltilmiş
- **Veri:** Yahoo-proxy'den türetilmiş portföy serisi (GERÇEK hesap değil). n=930 gün.
- **Metod:** kronolojik TRAIN(%60)/untouched TEST(%40); parametreler yalnız TRAIN'de
  tarandı; TEST bir kez + blok-bootstrap. Tam komşu-ızgara gösterildi.
- **Sonuç:** ızgara **düz** (fark MC gürültüsü içinde); parametreler keskin tanımlı değil.
  Düz smooth: ort çekilen +~1pt ama **medyan daha düşük, ruin daha yüksek** → domine ETMİYOR.
  Guard: ruin↓ ama withdrawn↓ (risk-tercihi takası). **fixed1.3 funded'da reddedildi**
  (ruin ~%10). Karar: **KOŞULLU ADAY** — canlı funded verisi olmadan devreye alınmaz.

## 2.6 Risk vs Geçme (dürüst proxy tablosu)
| risk çarpanı | metal% | +%10 ulaşma | patlama |
|---|---|---|---|
| 1.0× | 0.35 | 98.2% | 1.8% |
| **1.3× (seçilen)** | **0.46** | **94.8%** | **5.2%** |
| 2.0× | 0.70 | 84.8% | 15.2% |
| 4.0× | 1.40 | 64.6% | 35.4% |

---

# BÖLÜM 3 — KAPI-1 canlı gerçek-fill analizi (2026-09-28)

**Kaynak:** MT5 rapor, hesap 541438670 ($25k FTMO Challenge 2-Step, gerçek). 31 işlem
(hepsi robot/EA), 09-09 → 09-23. **Canlıdaki EA v3.11** (bizim v3.13 config'i değil).

| metrik | değer |
|---|---|
| işlem | 31 (16 kazanç / 15 kayıp, %52 win) |
| net | **−$633.66 = −%2.53** |
| profit factor | **0.58** |
| komisyon / swap | −$100.01 / −$11.74 |
| max ardışık kayıp | 4 işlem, −$442.79 |
| max drawdown | ~%0.88 (zemine çok uzak) |

**Yön merceği:** long 23 işlem net −$7 (≈başabaş); **short 8 işlem net −$626** (2 kazanç).
**Enstrüman merceği:**
| sembol | net | PF | işlem | komisyon |
|---|---|---|---|---|
| JP225 | **+$165** | 2.29 | 6 | 0 |
| US100 | +$0.42 | — | 1 | 0 |
| XAGUSD | −$49 | 0.75 | 3 | −0.62 |
| XAUUSD | −$175 | 0.54 | 5 | −1.50 |
| GER40 | −$283 | 0.36 | 7 | 0 |
| BTCUSD | **−$291** | 0.16 | 9 | **−$97.89** |

**İki kritik bulgu:**
1. **BTC'yi komisyon öldürüyor:** toplam −$100 komisyonun −$97.89'u BTC (~$11/işlem,
   1R≈$122'nin ~%9'u). Komisyonsuz bile ~−$193. Deterministik (varyans değil).
2. **Zarar shortlarda/GER40'ta yoğun** — ikisi de araştırmanın işaret ettiği yerler
   (GER40 = v3.11 Monday back-scan; BTC = maliyet). Sistem geneli bozuk değil; JP225 pozitif.

**Yorum:** n=31 fat-tail edge için az — ne doğrular ne çürütür. Hayatta kalma sorunsuz;
ama challenge +%10 gidişatı şu an negatif. Config düzeltmeleri **risk artırmadan** olasılığı
iyileştirir. Sonraki: **KAPI-2** (yeni config'le 25-30 işlem → tekrar analiz).

---

# BÖLÜM 4 — Güncel config (KAPI-1 sonrası) — enstrüman-başına inputlar

**Evren: XAUUSD, XAGUSD, GER40.cash, JP225.cash (4 grafik, H1). BTCUSD + NAS100/US100 KAPALI.**
**Risk 1.3× (kullanıcı tercihi; 1.0× önerilir). AccountSize=25000 = BAŞLANGIÇ bakiyesi (her grafikte).**

### XAUUSD (Altın) — ORB
```
AccountSize=25000, RiskPct=0.46, TrailStopR=0, ForceStrategy=AUTO,
MinRangeMedMult=1.0, PdhlMinRangeMedMult=0, PhaseTargetPct=10
```
### XAGUSD (Gümüş) — ORB
```
AccountSize=25000, RiskPct=0.46, TrailStopR=0, ForceStrategy=AUTO,
MinRangeMedMult=0, PdhlMinRangeMedMult=0, PhaseTargetPct=10
```
### GER40.cash (DAX) — PDHL
```
AccountSize=25000, RiskPct=0.33, TrailStopR=0.5, ForceStrategy=AUTO,
MinRangeMedMult=0, PdhlMinRangeMedMult=0, PhaseTargetPct=10
```
### JP225.cash (Nikkei) — PDHL
```
AccountSize=25000, RiskPct=0.59, TrailStopR=0.5, ForceStrategy=AUTO,
MinRangeMedMult=0, PdhlMinRangeMedMult=1.0, PhaseTargetPct=10
```
**Gerisi default (dokunma):** OrbHours=1, OrbRangeHourUTC=0, PdhlStopATR=1.5,
PdhlUseBackScan=false, NearTargetPct=1.5, NearTargetMult=0.5, LossBufferPct=1.0,
Derisk 3/0.6/6/0.35, MaxSingleRiskMult=2.0, MaxSpread 0/12.5, MarginSafetyFactor=1.10,
AutoPdhlSession=true, FridayFlatten 20:00, AvoidNews=true, Magic=770077, GovernorEnabled=false.

**1.0× güvenli alternatif:** XAU 0.35 / XAG 0.35 / GER40 0.25 / JP225 0.45.

**Operasyonel (canlı v3.11, bugün):** BTCUSD + US100.cash grafiğini kaldır. GER40 Monday
v3.11'de togglelanamıyorsa duraklat veya v3.13'e geçişte otomatik düzelir.

---

# BÖLÜM 5 — v3.14 safety candidate (governor) — değişiklik/test/demo/geri-dönüş

**v3.14 = v3.13 + ADD-ONLY güvenlik katmanı. Hepsi default-OFF → v3.13 ile byte-identical.**
Strateji/giriş/çıkış/trailing/seans/RiskMultiplier/filtreler **değişmedi.** Profit-Funded YOK.
Otomatik BTC multi-session YOK.

**Eklenenler:**
1. OnInit'te `ACCOUNT_MARGIN_MODE` oku + logla (yalnız görünürlük).
2. Dinamik-headroom governor: `allowedNew = min(dayHeadroom, overallHeadroom) −
   openStopRisk − pendingWorst(OCO iki bacak) − slipGap − safety − cost`. Committed risk
   **canlı broker scan'inden** (restart/crash-safe).
3. Pending OCO çift-bacak rezervasyonu.
4. Instance'lar arası race: atomik INFLIGHT GV (`GlobalVariableSetOnCondition`, reserve-then-validate).
5. Fail-closed: GV/OrderCalc hatası → emri açma. Governor yalnız azaltır/reddeder.

**Testler:** `tests/test_ftmo_governor.py` 16 test; `pytest -k ftmo` **126 passed**.
Kapsanan: governor-off parity, never-raise, min-headroom, tamponlar, realized+floating,
OCO çift-say, iki-instance race, restart reconciliation, statik tavanlar.
⚠️ **MQL5 F7 derlemesi + demo doğrulaması demo öncesi ZORUNLU** (bu ortamda derlenemedi).

**Demo kontrol listesi (özet):** F7 temiz derleme → governor-off parity (v3.13 ile birebir
lot) → headroom (zemine yakın red) → OCO çift-bacak/gap-through → fill/partial/iptal →
restart/crash reconciliation → iki-instance race → **netting vs hedging AYRI raporla** → fail-closed.

**Geri-dönüş (tek adım):** grafikten v3.14 kaldır → v3.13 geri ekle (dosya değişmedi, birebir).
Alternatif: `GovernorEnabled=false`. GV temizliği: sadece `AXGOV_*` sil. Governor kalıcı state
tutmaz → temiz dönüş.

---

# BÖLÜM 6 — TAM KOD

## 6.1 Üretim EA — `mql5/AurvexFTMO_v3_14_safety_candidate.mq5`
(v3.13 = bu dosyadan governor katmanı çıkarılmış hâli; canlı-hedef v3.13.)

```mql5
//+------------------------------------------------------------------+
//| AurvexFTMO_v3_14_safety_candidate.mq5                             |
//| = v3.13 (unchanged challenge strategy) + an ADD-ONLY safety layer.|
//| SAFETY CANDIDATE — NOT for production until F7 compile + demo.     |
//|                                                                    |
//| v3.14 adds ONLY (all default-OFF => byte-identical to v3.13):      |
//|   1. ACCOUNT_MARGIN_MODE read + explicit log in OnInit (no gating).|
//|   2. Dynamic-headroom Account-Level Risk Governor (GovernorEnabled)|
//|      allowedNew = min(dayHeadroom, overallHeadroom)                |
//|                   - openStopRisk - pendingWorst(OCO both legs)     |
//|                   - slipGapBuffer - costBuffer - safetyPad.        |
//|      Committed risk is ALWAYS from a LIVE broker scan (positions + |
//|      pendings), so it self-reconciles after restart/crash.         |
//|   3. Pending OCO double-leg reservation (both legs counted until   |
//|      one fills and the opposite's cancel is confirmed).            |
//|   4. Cross-instance race safety via an atomic INFLIGHT GV          |
//|      (GlobalVariableSetOnCondition, reserve-then-validate).        |
//|   5. Fail-closed: any GV/OrderCalc failure => order is skipped.    |
//| v3.14 changes NOTHING about entry/exit/trailing/session/filters/   |
//| RiskMultiplier. No Profit-Funded scaling. No auto BTC multi-session|
//| Governor can ONLY reduce risk or reject an order — never raise it. |
//|                                                                    |
//| ---- original v3.13 header below ----                              |
//| MERGE: hardened rewrite (v3.11, credit: friend's hardening) +     |
//|        Aurvex validated-strategy layer (v2.6-2.8).                |
//|                                                                    |
//| From the v3.11 base (kept):                                        |
//|   * restart-safe GlobalVariable persistence (state, plan, FTMO)   |
//|   * automatic CET/CEST + EST/EDT DST (FTMO reset + index sessions) |
//|   * OnTradeTransaction fill capture + planned-SL original-R        |
//|   * margin validation, retcode checks, broker freeze/stops guard   |
//|   * OrderCalcProfit-based lot sizing                               |
//| Added Aurvex validated layer (default-OFF where it changes fills): |
//|   * OrbRangeHourUTC + per-session effective magic (BTC multi-sess) |
//|   * MinRangeMedMult (GOLD low-vol-day filter, OOS +0.19->+0.36)    |
//|   * PdhlMinRangeMedMult (JP225 low-vol-day filter)                 |
//|   * PhaseTargetPct profit-lock                                     |
//|   * JournalTrades context CSV for KAPI-1 retro-testing             |
//|   * PDHL DEFAULTS to validated calendar-prior-day (skip Monday);   |
//|     PdhlUseBackScan=true restores v3.11's back-scan (which trades  |
//|     Mondays off Friday — net-NEGATIVE on GER40/NAS100 in tests,    |
//|     so it is OFF by default). See FTMO_PER_INSTRUMENT_RESEARCH.md. |
//|                                                                    |
//| ⚠ REVIEWED SKELETON — compile (F7) + demo-verify before any live   |
//|   use. Do not put on the funded/challenge account until the demo   |
//|   shows clean logs and fills.                                      |
//+------------------------------------------------------------------+
#property copyright "Aurvex / hardened rewrite + validated-strategy merge"
#property version   "3.14"
// v3.13 hardening (post-review): (1) reject risk multipliers >1 (never-raise
//   enforced, not just commented); (2) reject ORB windows that cross UTC midnight;
//   (3) size margin for BUY_STOP/SELL_STOP (the order types actually sent);
//   (4) retry the trade-journal write from the timer if the fill-event write missed.
//   Telegram URL-encoding intentionally not added — Telegram is unused (dormant).
#property strict

#include <Trade/Trade.mqh>

//--------------------------- strategy inputs -------------------------//
input double RiskPct             = 0.50;   // target risk per trade, % of AccountSize
input string ForceStrategy       = "AUTO"; // AUTO | ORB | PDHL
input int    OrbHours            = 1;      // opening-range length (hours)
input int    OrbRangeHourUTC     = 0;      // ORB range START hour UTC (0=00:00; BTC multi-session 0/3/13 on separate charts)
input double PdhlStopATR         = 1.50;   // PDHL stop distance = ATR(14) * multiplier
input double TrailStopR          = 0.50;   // trailing distance in initial R; 0 = disabled

//--------------------------- validated-strategy filters --------------//
input double MinRangeMedMult     = 0.0;    // ORB low-vol-day filter: require today's opening range >= x * trailing-20d median (0=off; GOLD: 1.0)
input double PdhlMinRangeMedMult  = 0.0;   // PDHL low-vol-day filter: require prior-day range >= x * trailing-20d median (0=off; JP225: 1.0 after KAPI-1)
input bool   PdhlUseBackScan     = false;  // false = validated calendar prior-day (skip Monday); true = v3.11 back-scan (trades Mon off Fri — negative on GER40/NAS100)

//--------------------------- profit-lock (v2.7) ----------------------//
input double PhaseTargetPct      = 0.0;    // profit-lock: phase target % (0=off; 10 Phase-1, 5 Phase-2)
input double NearTargetPct       = 1.5;    // within this % of the target, cut risk to NearTargetMult
input double NearTargetMult      = 0.5;    // risk multiplier once near the target

//--------------------------- account guard ---------------------------//
input double AccountSize         = 0;      // REQUIRED, e.g. 25000
input bool   RequireAccountSize  = true;   // refuse to start if AccountSize <= 0
const double FTMO_DAILY_LOSS_PCT   = 5.0;
const double FTMO_OVERALL_LOSS_PCT = 10.0;
input double LossBufferPct       = 1.0;    // 1.0 => guards at 4% daily / 9% overall
input double DeriskDD1Pct        = 3.0;
input double DeriskMult1         = 0.60;
input double DeriskDD2Pct        = 6.0;
input double DeriskMult2         = 0.35;
input double MaxSingleRiskMult   = 2.0;

//--------------------------- execution guard -------------------------//
input double MaxSpreadPoints      = 0;      // 0 = disabled; absolute spread cap in points
input double MaxSpreadToStopPct   = 12.5;   // spread may not exceed this % of planned SL distance; 0 = disabled
input bool   UseFreezeLevelGuard  = true;   // respect broker freeze level
input int    ExtraStopBufferPts   = 2;      // extra points beyond broker stop/freeze minimum
input double MarginSafetyFactor   = 1.10;   // require free margin >= calc margin * factor
input bool   AccountWideEmergencyFlatten = true; // guard breach: close/delete entire account

//--------------------------- session/time ----------------------------//
input bool   AutoPdhlSession     = true;   // GER/DAX and US/NAS symbols: cash-session gate
input int    PdhlStartUTCMin     = -1;     // manual override, minutes after UTC midnight
input int    PdhlEndUTCMin       = -1;     // -1/-1 = auto/no manual gate
input int    FridayFlattenUTCMin = 20*60;  // default 20:00 UTC
input int    TimerSeconds        = 2;
input int    ServerUtcOffsetOverrideHours = 999; // 999 = auto from live server
input int    TesterServerUtcOffsetHours   = 999;

//--------------------------- news ------------------------------------//
input bool   AvoidNews            = true;
input int    NewsBufferMin        = 2;
input bool   FreezeTrailInNews    = true;
input string NewsCurrencyOverride = "";
input bool   NewsFailClosed       = true;

//--------------------------- misc ------------------------------------//
input bool   DrawLevels          = true;
input bool   JournalTrades       = true;   // log each entry's context to MQL5/Files (passive)
input long   Magic               = 770077;
input string TelegramToken       = "";
input string TelegramChatID      = "";

//--------------------------- v3.14 Account-Level Risk Governor --------//
// ALL default-OFF: with GovernorEnabled=false the EA behaves byte-identically
// to v3.13 (the governor gate short-circuits with no side effects). The governor
// can only REDUCE risk or REJECT an order; it never raises risk.
input bool   GovernorEnabled       = false;  // master switch for the account-level risk governor
input double SlippageGapBufferPct  = 0.5;    // gap/slippage reserve, % of AccountSize
input double DailyFloorSafetyPct   = 0.5;    // extra safety pad below the binding floor, % of AccountSize
input double GovCostBufferPct      = 0.1;    // commission+swap reserve for the open set, % of AccountSize
input double MaxTotalOpenRiskPct   = 0.0;    // extra static ceiling on total committed risk (0=off)
input double MaxCorrelatedRiskPct  = 0.0;    // ceiling on same-group concurrent risk (0=off)
input string SymbolGroup           = "";     // correlation group tag: metals|crypto|index (blank=ungrouped)
input int    GovInflightRetries    = 50;     // atomic reservation retries before fail-closed

CTrade trade;
string SYM, STRAT;
long   g_magic = 0;            // effective magic = Magic + OrbRangeHourUTC (multi-session safe)

bool     g_tradedToday = false;
bool     g_fridayFlat  = false;
bool     g_journaled   = false;
datetime g_utcTradeDay = 0;

datetime g_ftmoDay     = 0;
double   g_ftmoOpenBal = 0;
double   g_initBal     = 0;
bool     g_guardTripped = false;
bool     g_overallGuardTripped = false;

// trailing state
bool   g_haveTrade = false;
bool   g_tLong     = false;
double g_tEntry    = 0;
double g_tRisk     = 0;
double g_tPeak     = 0;
double g_lastPeakPersist = 0;
datetime g_lastPeakPersistTime = 0;

// journal setup context (stashed at arm time)
double g_ctxHi=0, g_ctxLo=0, g_ctxRefPct=0, g_ctxMedPct=0, g_ctxSpreadPct=0;

//--------------------------- naming/persistence ----------------------//
string AccountPrefix()
{
   return StringFormat("AX3_%I64d_%I64d_", (long)AccountInfoInteger(ACCOUNT_LOGIN), g_magic);
}
string SymPrefix(){ return AccountPrefix() + SYM + "_"; }
string FtmoPrefix()
{
   // Risk state is account-wide and intentionally independent of Magic/Symbol.
   return StringFormat("AX312_FTMO_%I64d_", (long)AccountInfoInteger(ACCOUNT_LOGIN));
}
void GVSet(string name,double v)
{
   if(GlobalVariableSet(name,v)==0)
      PrintFormat("GV set failed %s err=%d",name,GetLastError());
}
bool GVGet(string name,double &v)
{
   if(!GlobalVariableCheck(name)) return false;
   return GlobalVariableGet(name,v);
}
void FlushState(){ GlobalVariablesFlush(); }

void SaveTradeDayState()
{
   GVSet(SymPrefix()+"UTC_DAY",(double)g_utcTradeDay);
   GVSet(SymPrefix()+"TRADED", g_tradedToday ? 1.0 : 0.0);
   GVSet(SymPrefix()+"FRIFLAT",g_fridayFlat  ? 1.0 : 0.0);
   GVSet(SymPrefix()+"JOURNALED",g_journaled ? 1.0 : 0.0);
   FlushState();
}
void SaveFtmoState()
{
   GVSet(FtmoPrefix()+"FTMO_DAY",(double)g_ftmoDay);
   GVSet(FtmoPrefix()+"FTMO_BAL",g_ftmoOpenBal);
   GVSet(FtmoPrefix()+"INIT_BAL",g_initBal);
   GVSet(FtmoPrefix()+"GUARD_DAY",g_guardTripped?1.0:0.0);
   GVSet(FtmoPrefix()+"GUARD_ALL",g_overallGuardTripped?1.0:0.0);
   FlushState();
}
void SaveTrailState()
{
   GVSet(SymPrefix()+"T_HAVE", g_haveTrade?1.0:0.0);
   GVSet(SymPrefix()+"T_LONG", g_tLong?1.0:0.0);
   GVSet(SymPrefix()+"T_ENTRY",g_tEntry);
   GVSet(SymPrefix()+"T_RISK", g_tRisk);
   GVSet(SymPrefix()+"T_PEAK", g_tPeak);
   FlushState();
}
void ClearTrailState()
{
   g_haveTrade=false; g_tLong=false; g_tEntry=0; g_tRisk=0; g_tPeak=0;
   g_lastPeakPersist=0; g_lastPeakPersistTime=0;
   SaveTrailState();
}
void PersistTrailPeakIfNeeded()
{
   if(!g_haveTrade || g_tRisk<=0 || g_tPeak<=0) return;
   datetime now=TimeTradeServer();
   double move=MathAbs(g_tPeak-g_lastPeakPersist);
   if(g_lastPeakPersist<=0 || move>=0.10*g_tRisk || now-g_lastPeakPersistTime>=5)
   {
      GVSet(SymPrefix()+"T_PEAK",g_tPeak);
      g_lastPeakPersist=g_tPeak;
      g_lastPeakPersistTime=now;
   }
}
void SavePlan(bool isBuy,double entry,double sl)
{
   string p=SymPrefix()+(isBuy?"BUY_":"SELL_");
   GVSet(p+"ENTRY",entry);
   GVSet(p+"SL",sl);
}
bool LoadPlan(bool isBuy,double &entry,double &sl)
{
   string p=SymPrefix()+(isBuy?"BUY_":"SELL_");
   return GVGet(p+"ENTRY",entry) && GVGet(p+"SL",sl);
}

//--------------------------- date/time helpers -----------------------//
datetime UtcDayStart(datetime t){ return (datetime)((long)t/86400*86400); }

datetime MakeUtc(int y,int mon,int day,int hour=0,int min=0)
{
   MqlDateTime d={};
   d.year=y; d.mon=mon; d.day=day; d.hour=hour; d.min=min; d.sec=0;
   return StructToTime(d);
}
int DaysInMonth(int y,int mon)
{
   int ny=y, nm=mon+1;
   if(nm==13){ nm=1; ny++; }
   datetime t=MakeUtc(ny,nm,1)-86400;
   MqlDateTime d; TimeToStruct(t,d);
   return d.day;
}
datetime NthSundayUtc(int y,int mon,int nth,int hourUtc)
{
   datetime first=MakeUtc(y,mon,1,hourUtc,0);
   MqlDateTime d; TimeToStruct(first,d);
   int firstSunday=1+((7-d.day_of_week)%7);
   return MakeUtc(y,mon,firstSunday+7*(nth-1),hourUtc,0);
}
datetime LastSundayUtc(int y,int mon,int hourUtc)
{
   int last=DaysInMonth(y,mon);
   datetime t=MakeUtc(y,mon,last,hourUtc,0);
   MqlDateTime d; TimeToStruct(t,d);
   int lastSunday=last-d.day_of_week;
   return MakeUtc(y,mon,lastSunday,hourUtc,0);
}
bool EuropeDst(datetime utc)
{
   MqlDateTime d; TimeToStruct(utc,d);
   datetime start=LastSundayUtc(d.year,3,1);
   datetime end  =LastSundayUtc(d.year,10,1);
   return (utc>=start && utc<end);
}
bool NewYorkDst(datetime utc)
{
   MqlDateTime d; TimeToStruct(utc,d);
   datetime start=NthSundayUtc(d.year,3,2,7);
   datetime end  =NthSundayUtc(d.year,11,1,6);
   return (utc>=start && utc<end);
}
int PragueUtcOffsetSec(datetime utc){ return EuropeDst(utc)?7200:3600; }
int NewYorkUtcOffsetSec(datetime utc){ return NewYorkDst(utc)?-14400:-18000; }

datetime FtmoDayStart(datetime utc)
{
   int off=PragueUtcOffsetSec(utc);
   datetime local=(datetime)((long)utc+off);
   datetime localMid=UtcDayStart(local);
   datetime guess=(datetime)((long)localMid-off);
   int off2=PragueUtcOffsetSec(guess);
   return (datetime)((long)localMid-off2);
}

long ServerUtcOffset()
{
   if((bool)MQLInfoInteger(MQL_TESTER) && TesterServerUtcOffsetHours!=999)
      return (long)TesterServerUtcOffsetHours*3600;
   if(ServerUtcOffsetOverrideHours!=999)
      return (long)ServerUtcOffsetOverrideHours*3600;
   long diff=(long)TimeTradeServer()-(long)TimeGMT();
   return (long)(MathRound((double)diff/3600.0)*3600.0);
}

//--------------------------- strategy/session ------------------------//
string DetectStrategy()
{
   string s=ForceStrategy; StringToUpper(s);
   if(s=="ORB" || s=="PDHL") return s;
   string z=SYM; StringToUpper(z);
   if(StringFind(z,"XAU")>=0 || StringFind(z,"GOLD")>=0 ||
      StringFind(z,"XAG")>=0 || StringFind(z,"SILVER")>=0)
      return "ORB";
   return "PDHL";
}
bool IsGermanIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"GER")>=0 || StringFind(s,"DAX")>=0 ||
          StringFind(s,"DE40")>=0 || StringFind(s,"DE30")>=0;
}
bool IsUSIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"US100")>=0 || StringFind(s,"NAS")>=0 ||
          StringFind(s,"USTEC")>=0 || StringFind(s,"NDX")>=0 ||
          StringFind(s,"US500")>=0 || StringFind(s,"SPX")>=0 ||
          StringFind(s,"US30")>=0 || StringFind(s,"DJ")>=0;
}
bool IsAsianIndex(string s)
{
   StringToUpper(s);
   return StringFind(s,"JP225")>=0 || StringFind(s,"JPN")>=0 ||
          StringFind(s,"N225")>=0 || StringFind(s,"NIK")>=0 ||
          StringFind(s,"HK")>=0   || StringFind(s,"JP")>=0;
}
bool PdhlSessionAllowed(datetime nowGmt)
{
   int minuteUtc=(int)(((long)nowGmt%86400)/60);
   if(PdhlStartUTCMin>=0 && PdhlEndUTCMin>=0 && PdhlStartUTCMin<PdhlEndUTCMin)
      return minuteUtc>=PdhlStartUTCMin && minuteUtc<PdhlEndUTCMin;
   if(!AutoPdhlSession) return true;
   if(IsGermanIndex(SYM))
   {
      int offMin=PragueUtcOffsetSec(nowGmt)/60;
      int start=9*60-offMin;
      int end=17*60+30-offMin;
      return minuteUtc>=start && minuteUtc<end;
   }
   if(IsUSIndex(SYM))
   {
      int offMin=NewYorkUtcOffsetSec(nowGmt)/60;
      int start=9*60+30-offMin;
      int end=16*60-offMin;
      return minuteUtc>=start && minuteUtc<end;
   }
   if(IsAsianIndex(SYM))
   {
      // Tokyo cash ~09:00-15:00 JST = 00:00-06:00 UTC (Japan has no DST).
      return minuteUtc>=0 && minuteUtc<6*60;
   }
   return true;
}

//--------------------------- notifications ---------------------------//
void Notify(string msg)
{
   Print(msg);
   if(StringLen(TelegramToken)==0 || StringLen(TelegramChatID)==0) return;
   string url="https://api.telegram.org/bot"+TelegramToken+"/sendMessage";
   string post="chat_id="+TelegramChatID+"&text="+msg;
   char data[]; StringToCharArray(post,data,0,StringLen(post));
   char res[]; string rhdr;
   ResetLastError();
   int code=WebRequest("POST",url,"Content-Type: application/x-www-form-urlencoded\r\n",
                       5000,data,res,rhdr);
   if(code==-1) PrintFormat("Telegram WebRequest failed err=%d",GetLastError());
}

//--------------------------- trade-result checks ---------------------//
bool RetcodeOk()
{
   uint r=trade.ResultRetcode();
   return (r==TRADE_RETCODE_DONE || r==TRADE_RETCODE_PLACED ||
           r==TRADE_RETCODE_DONE_PARTIAL || r==TRADE_RETCODE_NO_CHANGES);
}
bool CheckTradeCall(bool callOk,string action)
{
   bool ok=callOk && RetcodeOk();
   if(!ok)
      Notify(StringFormat("%s %s failed ret=%u %s",
             SYM,action,trade.ResultRetcode(),trade.ResultRetcodeDescription()));
   return ok;
}

//--------------------------- positions/orders ------------------------//
bool HasPosition(string sym)
{
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==g_magic) return true;
   }
   return false;
}
bool HasPendingSide(string sym,bool isBuy)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetString(ORDER_SYMBOL)!=sym || OrderGetInteger(ORDER_MAGIC)!=g_magic) continue;
      ENUM_ORDER_TYPE tp=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(isBuy && tp==ORDER_TYPE_BUY_STOP) return true;
      if(!isBuy && tp==ORDER_TYPE_SELL_STOP) return true;
   }
   return false;
}
void DeletePendings(string sym)
{
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      if(OrderGetString(ORDER_SYMBOL)==sym && OrderGetInteger(ORDER_MAGIC)==g_magic)
         CheckTradeCall(trade.OrderDelete(tk),"OrderDelete");
   }
}
void FlattenSymbol(string sym)
{
   DeletePendings(sym);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==sym &&
         PositionGetInteger(POSITION_MAGIC)==g_magic)
         CheckTradeCall(trade.PositionClose(tk),"PositionClose");
   }
}
void EmergencyFlatten()
{
   if(!AccountWideEmergencyFlatten){ FlattenSymbol(SYM); return; }
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong tk=OrderGetTicket(i);
      if(tk==0) continue;
      CheckTradeCall(trade.OrderDelete(tk),"EmergencyOrderDelete");
   }
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong tk=PositionGetTicket(i);
      if(tk==0) continue;
      CheckTradeCall(trade.PositionClose(tk),"EmergencyPositionClose");
   }
}

//--------------------------- historical data -------------------------//
// Opening range for `dayStart`, hours [OrbRangeHourUTC .. +OrbHours), matched by UTC
// hour so it is correct on any broker timezone (and supports BTC multi-session).
bool OpeningRange(string sym,datetime dayStart,double &hi,double &lo)
{
   if(OrbHours<1 || OrbHours>12) return false;
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,120,r);
   if(n<OrbHours+1) return false;
   long off=ServerUtcOffset();
   hi=-DBL_MAX; lo=DBL_MAX; int count=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      if(UtcDayStart((datetime)utc)!=dayStart) continue;
      int hour=(int)((utc%86400)/3600);
      if(hour>=OrbRangeHourUTC && hour<OrbRangeHourUTC+OrbHours)
      {
         hi=MathMax(hi,r[k].high);
         lo=MathMin(lo,r[k].low);
         count++;
      }
   }
   return count>=OrbHours && hi>lo;
}

// PDHL prior-day range. Default (PdhlUseBackScan=false): the prior CALENDAR day
// only (back==1); if it has no bars (Sunday/holiday, e.g. Monday) return false and
// skip — the validated behaviour. PdhlUseBackScan=true restores the v3.11 back-scan
// (finds the last day with bars, i.e. trades Monday off Friday).
bool PrevTradingDayRange(string sym,datetime dayStart,double &ph,double &pl)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,240,r);
   if(n<3) return false;
   long off=ServerUtcOffset();
   int maxBack = PdhlUseBackScan ? 10 : 1;
   for(int back=1;back<=maxBack;back++)
   {
      datetime target=dayStart-(datetime)back*86400;
      double h=-DBL_MAX,l=DBL_MAX; int cnt=0;
      for(int k=0;k<n;k++)
      {
         long utc=(long)r[k].time-off;
         if(UtcDayStart((datetime)utc)==target)
         {
            h=MathMax(h,r[k].high);
            l=MathMin(l,r[k].low);
            cnt++;
         }
      }
      if(cnt>=3 && h>l){ ph=h; pl=l; return true; }
   }
   return false;
}
bool Atr14(string sym,double &atr)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,16,r);
   if(n<16) return false;
   double sum=0;
   for(int k=1;k<15;k++)
   {
      double tr=MathMax(r[k].high-r[k].low,
                MathMax(MathAbs(r[k].high-r[k+1].close),
                        MathAbs(r[k].low-r[k+1].close)));
      sum+=tr;
   }
   atr=sum/14.0;
   return atr>0;
}
// Trailing-20d median of the opening-range SIZE (fraction of price), prior days only
// (causal). Returns -1 if not enough history. Used by the GOLD low-vol filter/journal.
double OrbMedianRangePct(string sym,int rangeHour,int orbHours,datetime today,int lookback)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,1200,r);
   if(n<orbHours*2) return -1;
   long off=ServerUtcOffset();
   datetime days[]; double dhi[]; double dlo[]; int cnt=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      int hr=(int)((utc%86400)/3600);
      if(hr<rangeHour || hr>=rangeHour+orbHours) continue;
      datetime dd=UtcDayStart((datetime)utc);
      if(dd>=today) continue;
      int idx=-1;
      for(int j=0;j<cnt;j++) if(days[j]==dd){ idx=j; break; }
      if(idx<0){ idx=cnt; cnt++; ArrayResize(days,cnt); ArrayResize(dhi,cnt); ArrayResize(dlo,cnt);
                 days[idx]=dd; dhi[idx]=r[k].high; dlo[idx]=r[k].low; }
      else { if(r[k].high>dhi[idx]) dhi[idx]=r[k].high; if(r[k].low<dlo[idx]) dlo[idx]=r[k].low; }
   }
   if(cnt<lookback) return -1;
   double rp[]; ArrayResize(rp,cnt);
   for(int j=0;j<cnt;j++){ double mid=(dhi[j]+dlo[j])/2.0; rp[j]=(mid>0)?(dhi[j]-dlo[j])/mid:0; }
   for(int a=0;a<cnt-1;a++) for(int b=a+1;b<cnt;b++) if(days[b]>days[a]){
      datetime td=days[a]; days[a]=days[b]; days[b]=td;
      double tr=rp[a]; rp[a]=rp[b]; rp[b]=tr; }
   double sub[]; ArrayResize(sub,lookback);
   for(int j=0;j<lookback;j++) sub[j]=rp[j];
   ArraySort(sub);
   return (sub[lookback/2]+sub[(lookback-1)/2])/2.0;
}
// PDHL vol-filter helper: refRp = prior day's full-day range %, medRp = median of the
// lookback days before it. Prior days only (causal). false if not enough history.
bool PrevDayRangePctMed(string sym,datetime today,int lookback,double &refRp,double &medRp)
{
   MqlRates r[]; ArraySetAsSeries(r,true);
   int n=CopyRates(sym,PERIOD_H1,0,1200,r);
   if(n<2) return false;
   long off=ServerUtcOffset();
   datetime days[]; double dhi[]; double dlo[]; int cnt=0;
   for(int k=0;k<n;k++)
   {
      long utc=(long)r[k].time-off;
      datetime dd=UtcDayStart((datetime)utc);
      if(dd>=today) continue;
      int idx=-1;
      for(int j=0;j<cnt;j++) if(days[j]==dd){ idx=j; break; }
      if(idx<0){ idx=cnt; cnt++; ArrayResize(days,cnt); ArrayResize(dhi,cnt); ArrayResize(dlo,cnt);
                 days[idx]=dd; dhi[idx]=r[k].high; dlo[idx]=r[k].low; }
      else { if(r[k].high>dhi[idx]) dhi[idx]=r[k].high; if(r[k].low<dlo[idx]) dlo[idx]=r[k].low; }
   }
   if(cnt<lookback+1) return false;
   double rp[]; ArrayResize(rp,cnt);
   for(int j=0;j<cnt;j++){ double mid=(dhi[j]+dlo[j])/2.0; rp[j]=(mid>0)?(dhi[j]-dlo[j])/mid:0; }
   for(int a=0;a<cnt-1;a++) for(int b=a+1;b<cnt;b++) if(days[b]>days[a]){
      datetime td=days[a]; days[a]=days[b]; days[b]=td;
      double tr=rp[a]; rp[a]=rp[b]; rp[b]=tr; }
   refRp=rp[0];
   double sub[]; ArrayResize(sub,lookback);
   for(int j=0;j<lookback;j++) sub[j]=rp[j+1];
   ArraySort(sub);
   medRp=(sub[lookback/2]+sub[(lookback-1)/2])/2.0;
   return true;
}

//--------------------------- risk sizing / execution -----------------//
double RiskMultiplier()
{
   if(g_initBal<=0) return 1.0;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   // profit-lock: within NearTargetPct of the phase target -> cut risk (never raise)
   double gain=(eq-g_initBal)/g_initBal*100.0;
   if(PhaseTargetPct>0 && NearTargetPct>0 && gain>=PhaseTargetPct-NearTargetPct)
      return NearTargetMult;
   double dd=(g_initBal-eq)/g_initBal*100.0;
   if(DeriskDD2Pct>0 && dd>=DeriskDD2Pct) return DeriskMult2;
   if(DeriskDD1Pct>0 && dd>=DeriskDD1Pct) return DeriskMult1;
   return 1.0;
}
int VolumeDigits(double step)
{
   int d=0; double s=step;
   while(d<8 && MathAbs(s-MathRound(s))>1e-9){ s*=10.0; d++; }
   return d;
}
bool StopLossMoney(string sym,double entry,double sl,double volume,double &lossMoney)
{
   lossMoney=0.0;
   if(volume<=0 || entry<=0 || sl<=0 || entry==sl) return false;
   ENUM_ORDER_TYPE side=(sl<entry ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   double pnl=0.0;
   ResetLastError();
   if(!OrderCalcProfit(side,sym,volume,entry,sl,pnl))
   {
      PrintFormat("%s OrderCalcProfit failed err=%d entry=%.8f sl=%.8f vol=%.4f",
                  sym,GetLastError(),entry,sl,volume);
      return false;
   }
   lossMoney=MathAbs(pnl);
   return lossMoney>0;
}
double CalcLots(string sym,double entry,double sl,bool isBuy)
{
   double riskMoney=g_initBal*RiskPct/100.0*RiskMultiplier();
   if(riskMoney<=0 || entry<=0 || sl<=0 || entry==sl) return 0;
   double lossPerLot=0.0;
   if(!StopLossMoney(sym,entry,sl,1.0,lossPerLot) || lossPerLot<=0) return 0;
   double step=SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP);
   double vmin=SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(sym,SYMBOL_VOLUME_MAX);
   if(step<=0 || vmin<=0 || vmax<=0) return 0;
   double lots=riskMoney/lossPerLot;
   lots=MathFloor(lots/step+1e-9)*step;
   if(lots<vmin) lots=vmin;
   if(lots>vmax) lots=vmax;
   lots=NormalizeDouble(lots,VolumeDigits(step));
   double actualRisk=0.0;
   if(!StopLossMoney(sym,entry,sl,lots,actualRisk)) return 0;
   if(actualRisk>riskMoney*MaxSingleRiskMult)
   {
      Notify(StringFormat("%s volume risk %.2f > %.2fx target %.2f; SKIP",
                          sym,actualRisk,MaxSingleRiskMult,riskMoney));
      return 0;
   }
   double marginReq=0.0;
   // v3.13: we actually send BUY_STOP/SELL_STOP, so size the margin for those exact
   // order types (not the market BUY/SELL) for a correct fail-closed check.
   ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
   ResetLastError();
   if(!OrderCalcMargin(orderType,sym,lots,entry,marginReq) || marginReq<0)
   {
      Notify(StringFormat("%s margin calculation failed err=%d; TRADE SKIPPED",sym,GetLastError()));
      return 0;
   }
   double freeMargin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double required=MathMax(0.0,marginReq)*MathMax(1.0,MarginSafetyFactor);
   if(freeMargin<=0 || freeMargin<required)
   {
      Notify(StringFormat("%s insufficient free margin: need %.2f, free %.2f; SKIP",
                          sym,required,freeMargin));
      return 0;
   }
   return lots;
}
double BrokerProtectionDistance(string sym)
{
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   if(point<=0) return 0;
   long stopPts=SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL);
   long freezePts=(UseFreezeLevelGuard ? SymbolInfoInteger(sym,SYMBOL_TRADE_FREEZE_LEVEL) : 0);
   long minPts=(long)MathMax((double)stopPts,(double)freezePts)+(long)MathMax(0,ExtraStopBufferPts);
   return (double)minPts*point;
}
bool SpreadAllowed(string sym,double plannedStopDistance)
{
   double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
   double bid=SymbolInfoDouble(sym,SYMBOL_BID);
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   if(ask<=0 || bid<=0 || point<=0 || ask<bid) return false;
   double spread=ask-bid;
   double spreadPts=spread/point;
   if(MaxSpreadPoints>0 && spreadPts>MaxSpreadPoints)
   {
      PrintFormat("%s spread guard: %.1f pts > %.1f",sym,spreadPts,MaxSpreadPoints);
      return false;
   }
   if(MaxSpreadToStopPct>0 && plannedStopDistance>0 &&
      spread>plannedStopDistance*MaxSpreadToStopPct/100.0)
   {
      PrintFormat("%s spread guard: spread %.8f > %.2f%% of stop %.8f",
                  sym,spread,MaxSpreadToStopPct,plannedStopDistance);
      return false;
   }
   return true;
}
//--------------------------- v3.14 risk governor ---------------------//
// Committed risk is ALWAYS derived from a LIVE broker scan (positions +
// pendings), so it self-reconciles after any restart/crash — no dependence on
// persisted governor state. The INFLIGHT GV is only a sub-second race token,
// reset to 0 on init (which also clears any reservation leaked by a crash).
string GovPrefix()
{
   return StringFormat("AXGOV_%I64d_",(long)AccountInfoInteger(ACCOUNT_LOGIN));
}
double GovInflightGet(){ double v=0; if(GVGet(GovPrefix()+"INFLIGHT",v)) return v; return 0.0; }
void   GovInflightReset(){ GlobalVariableSet(GovPrefix()+"INFLIGHT",0.0); }
bool   GovInflightAdd(double delta)   // atomic; fail-closed if contention persists
{
   string k=GovPrefix()+"INFLIGHT";
   int tries=MathMax(1,GovInflightRetries);
   for(int i=0;i<tries;i++)
   {
      double cur=0; GVGet(k,cur);
      double nv=cur+delta; if(nv<0) nv=0;
      if(GlobalVariableSetOnCondition(k,nv,cur)) return true;
   }
   return false;
}
string SymbolGroupOf(string sym)
{
   string z=sym; StringToUpper(z);
   if(StringFind(z,"XAU")>=0||StringFind(z,"GOLD")>=0||
      StringFind(z,"XAG")>=0||StringFind(z,"SILVER")>=0) return "metals";
   if(StringFind(z,"BTC")>=0||StringFind(z,"ETH")>=0||StringFind(z,"CRYPTO")>=0) return "crypto";
   if(IsGermanIndex(z)||IsUSIndex(z)||IsAsianIndex(z)) return "index";
   return "";
}
// worst-case loss on an OPEN position from the CURRENT price to its CURRENT SL.
// A position with no SL is treated as full-account risk (blocks new risk), fail-closed.
double PositionRiskFromNow(ulong tk)
{
   if(!PositionSelectByTicket(tk)) return 0.0;
   double sl =PositionGetDouble(POSITION_SL);
   double vol=PositionGetDouble(POSITION_VOLUME);
   string sym=PositionGetString(POSITION_SYMBOL);
   long   pt =PositionGetInteger(POSITION_TYPE);
   if(vol<=0) return 0.0;
   if(sl<=0)  return g_initBal;   // stop-less position => block (fail-closed)
   double cur=(pt==POSITION_TYPE_BUY)?SymbolInfoDouble(sym,SYMBOL_BID)
                                     :SymbolInfoDouble(sym,SYMBOL_ASK);
   if(cur<=0) cur=PositionGetDouble(POSITION_PRICE_OPEN);
   ENUM_ORDER_TYPE side=(pt==POSITION_TYPE_BUY)?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double pnl=0.0;
   if(!OrderCalcProfit(side,sym,vol,cur,sl,pnl)) return g_initBal; // fail-closed
   return (pnl<0.0)?-pnl:0.0;
}
// worst-case loss on a PENDING order from its entry to its SL (both OCO legs
// are summed by the scan, which models the double-trigger / gap-through case).
double PendingRiskEntryToSL(ulong tk)
{
   if(!OrderSelect(tk)) return 0.0;
   string sym  =OrderGetString(ORDER_SYMBOL);
   double vol  =OrderGetDouble(ORDER_VOLUME_CURRENT);
   double entry=OrderGetDouble(ORDER_PRICE_OPEN);
   double sl   =OrderGetDouble(ORDER_SL);
   ENUM_ORDER_TYPE ot=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
   if(vol<=0||entry<=0) return 0.0;
   if(sl<=0) return g_initBal;   // stop-less pending => block (fail-closed)
   ENUM_ORDER_TYPE side=(ot==ORDER_TYPE_BUY_STOP||ot==ORDER_TYPE_BUY_LIMIT||ot==ORDER_TYPE_BUY)
                        ?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double pnl=0.0;
   if(!OrderCalcProfit(side,sym,vol,entry,sl,pnl)) return g_initBal; // fail-closed
   return (pnl<0.0)?-pnl:0.0;
}
// account-wide committed risk = all open positions (from-now) + all pendings
// (entry->SL, both OCO legs). Ground truth from the broker => restart/crash safe.
double ScanCommittedRisk()
{
   double tot=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong tk=PositionGetTicket(i); if(tk==0) continue; tot+=PositionRiskFromNow(tk); }
   for(int i=OrdersTotal()-1;i>=0;i--){ ulong tk=OrderGetTicket(i); if(tk==0) continue; tot+=PendingRiskEntryToSL(tk); }
   return tot;
}
double ScanGroupRisk(string group)
{
   if(StringLen(group)==0) return 0.0;
   double tot=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong tk=PositionGetTicket(i); if(tk==0) continue;
      if(SymbolGroupOf(PositionGetString(POSITION_SYMBOL))==group) tot+=PositionRiskFromNow(tk); }
   for(int i=OrdersTotal()-1;i>=0;i--){ ulong tk=OrderGetTicket(i); if(tk==0) continue;
      if(SymbolGroupOf(OrderGetString(ORDER_SYMBOL))==group) tot+=PendingRiskEntryToSL(tk); }
   return tot;
}
// binding headroom = tighter of (daily, overall) floor distance, minus reserves.
// Uses the SAME floor formulas as LossGuardOk() so the preventive layer agrees
// with the reactive guard.
double GovHeadroomAllowed()
{
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyEff  =MathMax(0.0,FTMO_DAILY_LOSS_PCT-LossBufferPct);
   double overallEff=MathMax(0.0,FTMO_OVERALL_LOSS_PCT-LossBufferPct);
   double dailyFloor  =g_ftmoOpenBal-g_initBal*dailyEff/100.0;
   double overallFloor=g_initBal    -g_initBal*overallEff/100.0;
   double dayHead =eq-dailyFloor;
   double overHead=eq-overallFloor;
   double slipGap=SlippageGapBufferPct/100.0*g_initBal;
   double safety =DailyFloorSafetyPct/100.0*g_initBal;
   double costBuf=GovCostBufferPct/100.0*g_initBal;
   return MathMin(dayHead,overHead)-slipGap-safety-costBuf;
}
// reserve-then-validate: reserve rNew into the atomic INFLIGHT budget FIRST, then
// validate against (live scan + inflight). This makes concurrent instances'
// reservations mutually visible (both include their R before validating), so under
// contention they fail safe (reject) rather than both over-committing. Caller must
// call GovernorRelease(rNew) after the OrderSend (whether it succeeds or fails).
bool GovernorTryReserve(string sym,double entry,double sl,double lots,double &rNew)
{
   rNew=0.0;
   double r=0.0;
   if(!StopLossMoney(sym,entry,sl,lots,r) || r<=0) return false; // fail-closed
   rNew=r;
   double allowed=GovHeadroomAllowed();
   if(allowed<=0){ rNew=0; return false; }                       // no headroom
   if(!GovInflightAdd(rNew)){ rNew=0; return false; }            // fail-closed on GV contention
   double committed=ScanCommittedRisk()+GovInflightGet();        // incl. my rNew + concurrent
   bool ok=(committed<=allowed);
   if(ok && MaxTotalOpenRiskPct>0 &&
      committed>MaxTotalOpenRiskPct/100.0*g_initBal) ok=false;   // extra static ceiling
   if(ok && MaxCorrelatedRiskPct>0)
   {
      double gr=ScanGroupRisk(SymbolGroup)+rNew;
      if(gr>MaxCorrelatedRiskPct/100.0*g_initBal) ok=false;      // correlated-group ceiling
   }
   if(!ok){ GovInflightAdd(-rNew); rNew=0; return false; }       // rollback + reject
   return true;
}
void GovernorRelease(double rNew){ if(rNew>0) GovInflightAdd(-rNew); }

void EnsureStops(string sym,double buyPrice,double buySL,
                 double sellPrice,double sellSL,string tag)
{
   int digits=(int)SymbolInfoInteger(sym,SYMBOL_DIGITS);
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   double protectDist=BrokerProtectionDistance(sym);
   if(point<=0) return;
   buyPrice=NormalizeDouble(buyPrice,digits);
   buySL=NormalizeDouble(buySL,digits);
   sellPrice=NormalizeDouble(sellPrice,digits);
   sellSL=NormalizeDouble(sellSL,digits);
   double buyRiskDist=MathAbs(buyPrice-buySL);
   double sellRiskDist=MathAbs(sellPrice-sellSL);
   double refRiskDist=MathMin(buyRiskDist,sellRiskDist);
   if(!SpreadAllowed(sym,refRiskDist)){ DeletePendings(sym); return; }
   trade.SetTypeFillingBySymbol(sym);
   if(!HasPendingSide(sym,true))
   {
      double ask=SymbolInfoDouble(sym,SYMBOL_ASK);
      if(ask>0 && buyPrice>ask+protectDist && buySL<buyPrice-protectDist)
      {
         double lot=CalcLots(sym,buyPrice,buySL,true);
         if(lot>0)
         {
            // v3.14 governor gate: when disabled this short-circuits (pass=true,
            // no reservation, no side effects) => identical to v3.13.
            double rNew=0; bool pass=true;
            if(GovernorEnabled) pass=GovernorTryReserve(sym,buyPrice,buySL,lot,rNew);
            if(pass)
            {
               SavePlan(true,buyPrice,buySL);
               bool ok=trade.BuyStop(lot,buyPrice,sym,buySL,0,ORDER_TIME_DAY,0,tag);
               if(GovernorEnabled) GovernorRelease(rNew);
               if(CheckTradeCall(ok,"BUY-STOP"))
                  Notify(StringFormat("%s %s BUY-STOP %.*f %.2f lot",sym,tag,digits,buyPrice,lot));
            }
            else Notify(StringFormat("%s %s BUY-STOP rejected by governor (insufficient headroom)",sym,tag));
         }
      }
   }
   if(!HasPendingSide(sym,false))
   {
      double bid=SymbolInfoDouble(sym,SYMBOL_BID);
      if(bid>0 && sellPrice<bid-protectDist && sellSL>sellPrice+protectDist)
      {
         double lot=CalcLots(sym,sellPrice,sellSL,false);
         if(lot>0)
         {
            // v3.14 governor gate (see BUY leg). The SELL leg reserves separately;
            // by now the just-placed BUY leg is in the scan, so the OCO pair's
            // combined (double-trigger) risk is what this leg is validated against.
            double rNew=0; bool pass=true;
            if(GovernorEnabled) pass=GovernorTryReserve(sym,sellPrice,sellSL,lot,rNew);
            if(pass)
            {
               SavePlan(false,sellPrice,sellSL);
               bool ok=trade.SellStop(lot,sellPrice,sym,sellSL,0,ORDER_TIME_DAY,0,tag);
               if(GovernorEnabled) GovernorRelease(rNew);
               if(CheckTradeCall(ok,"SELL-STOP"))
                  Notify(StringFormat("%s %s SELL-STOP %.*f %.2f lot",sym,tag,digits,sellPrice,lot));
            }
            else Notify(StringFormat("%s %s SELL-STOP rejected by governor (insufficient headroom)",sym,tag));
         }
      }
   }
}

//--------------------------- chart drawing ---------------------------//
void DrawHLine(string tag,double price,color col,int style)
{
   string name=tag+"_"+(string)g_magic;
   if(ObjectFind(0,name)<0) ObjectCreate(0,name,OBJ_HLINE,0,0,price);
   else ObjectSetDouble(0,name,OBJPROP_PRICE,price);
   ObjectSetInteger(0,name,OBJPROP_COLOR,col);
   ObjectSetInteger(0,name,OBJPROP_STYLE,style);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,1);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
   ObjectSetString(0,name,OBJPROP_TEXT,tag);
}
void DrawSetup(double buyP,double buySL,double sellP,double sellSL)
{
   DrawHLine("AX3_BUY",buyP,clrLime,STYLE_SOLID);
   DrawHLine("AX3_BUYSL",buySL,clrGray,STYLE_DOT);
   DrawHLine("AX3_SELL",sellP,clrRed,STYLE_SOLID);
   DrawHLine("AX3_SELLSL",sellSL,clrGray,STYLE_DOT);
   ChartRedraw(0);
}
void DeleteLevels()
{
   ObjectDelete(0,"AX3_BUY_"+(string)g_magic);
   ObjectDelete(0,"AX3_BUYSL_"+(string)g_magic);
   ObjectDelete(0,"AX3_SELL_"+(string)g_magic);
   ObjectDelete(0,"AX3_SELLSL_"+(string)g_magic);
   ChartRedraw(0);
}

//--------------------------- FTMO day reconstruction -----------------//
double ReconstructFtmoOpenBalance(datetime fromGmt)
{
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   long off=ServerUtcOffset();
   datetime fromServer=(datetime)((long)fromGmt+off);
   datetime toServer=TimeTradeServer();
   if(!HistorySelect(fromServer,toServer)) return bal;
   double realized=0;
   int total=HistoryDealsTotal();
   for(int i=0;i<total;i++)
   {
      ulong tk=HistoryDealGetTicket(i);
      if(tk==0) continue;
      realized += HistoryDealGetDouble(tk,DEAL_PROFIT);
      realized += HistoryDealGetDouble(tk,DEAL_COMMISSION);
      realized += HistoryDealGetDouble(tk,DEAL_SWAP);
      realized += HistoryDealGetDouble(tk,DEAL_FEE);
   }
   return bal-realized;
}
void RefreshFtmoDay(datetime nowGmt)
{
   datetime d=FtmoDayStart(nowGmt);
   if(d==g_ftmoDay) return;
   g_ftmoDay=d;
   g_ftmoOpenBal=ReconstructFtmoOpenBalance(d);
   g_guardTripped=false;
   SaveFtmoState();
   Notify(StringFormat("%s FTMO day reset/rebuilt; baseline %.2f",SYM,g_ftmoOpenBal));
}
bool LossGuardOk()
{
   if(g_overallGuardTripped || g_guardTripped) return false;
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   double dailyEff=MathMax(0.0,FTMO_DAILY_LOSS_PCT-LossBufferPct);
   double overallEff=MathMax(0.0,FTMO_OVERALL_LOSS_PCT-LossBufferPct);
   double dailyFloor=g_ftmoOpenBal-g_initBal*dailyEff/100.0;
   double overallFloor=g_initBal-g_initBal*overallEff/100.0;
   if(eq<=overallFloor)
   {
      g_overallGuardTripped=true; g_guardTripped=true; SaveFtmoState();
      Notify(StringFormat("%s GUARD OVERALL TRIPPED eq=%.2f floor=%.2f; trading locked",SYM,eq,overallFloor));
      return false;
   }
   if(eq<=dailyFloor)
   {
      g_guardTripped=true; SaveFtmoState();
      Notify(StringFormat("%s GUARD DAILY TRIPPED eq=%.2f floor=%.2f; locked until FTMO day reset",SYM,eq,dailyFloor));
      return false;
   }
   return true;
}

//--------------------------- news ------------------------------------//
string AutoNewsCurrency(string sym)
{
   if(StringLen(NewsCurrencyOverride)>0){ string x=NewsCurrencyOverride; StringToUpper(x); return x; }
   string z=sym; StringToUpper(z);
   if(StringFind(z,"XAU")>=0 || StringFind(z,"GOLD")>=0 ||
      StringFind(z,"XAG")>=0 || StringFind(z,"SILVER")>=0 || IsUSIndex(z))
      return "USD";
   if(IsGermanIndex(z)) return "EUR";
   string profit=SymbolInfoString(sym,SYMBOL_CURRENCY_PROFIT);
   StringToUpper(profit);
   return profit;
}
bool IsNewsBlackout(string sym)
{
   if(!AvoidNews || NewsBufferMin<=0) return false;
   string ccy=AutoNewsCurrency(sym);
   if(StringLen(ccy)==0) return false;
   datetime now=TimeTradeServer();
   datetime from=now-(datetime)NewsBufferMin*60;
   datetime to=now+(datetime)NewsBufferMin*60;
   MqlCalendarValue vals[];
   ResetLastError();
   int n=CalendarValueHistory(vals,from,to,NULL,ccy);
   if(n<0)
   {
      int err=GetLastError();
      PrintFormat("%s calendar unavailable ccy=%s err=%d",sym,ccy,err);
      return ((bool)MQLInfoInteger(MQL_TESTER) ? false : NewsFailClosed);
   }
   for(int i=0;i<n;i++)
   {
      MqlCalendarEvent ev;
      if(CalendarEventById(vals[i].event_id,ev))
         if(ev.importance==CALENDAR_IMPORTANCE_HIGH) return true;
   }
   return false;
}

//--------------------------- journal ---------------------------------//
void JournalOnFill()
{
   if(!JournalTrades || g_journaled) return;
   ulong tk=0;
   for(int i=PositionsTotal()-1;i>=0;i--){ ulong t=PositionGetTicket(i);
      if(PositionGetString(POSITION_SYMBOL)==SYM && PositionGetInteger(POSITION_MAGIC)==g_magic){ tk=t; break; } }
   if(tk==0) return;
   double entry=PositionGetDouble(POSITION_PRICE_OPEN);
   double sl=PositionGetDouble(POSITION_SL);
   double vol=PositionGetDouble(POSITION_VOLUME);
   bool isLong=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double eq=AccountInfoDouble(ACCOUNT_EQUITY);
   double gain=(g_initBal>0)?(eq-g_initBal)/g_initBal*100.0:0;
   double dd=(g_initBal>0)?(g_initBal-eq)/g_initBal*100.0:0;
   double bid=SymbolInfoDouble(SYM,SYMBOL_BID), ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   double px=(bid>0&&ask>0)?(bid+ask)/2.0:bid;
   double spr=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
   int dg=(int)SymbolInfoInteger(SYM,SYMBOL_DIGITS);
   string fn="AurvexFTMO_journal_"+SYM+"_"+(string)g_magic+".csv";
   int h=FileOpen(fn,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(h==INVALID_HANDLE){ Notify(SYM+" journal: FileOpen failed"); return; }
   if(FileSize(h)==0)
      FileWrite(h,"utc_time","symbol","strat","side","entry","sl","lots","hi","lo",
                "ref_range_pct","trail_med_pct","spread_arm_pct","spread_fill_pct",
                "gain_pct","dd_pct","riskmult");
   FileSeek(h,0,SEEK_END);
   FileWrite(h,TimeToString(TimeGMT(),TIME_DATE|TIME_MINUTES),SYM,STRAT,
             (isLong?"long":"short"),
             DoubleToString(entry,dg),DoubleToString(sl,dg),DoubleToString(vol,2),
             DoubleToString(g_ctxHi,dg),DoubleToString(g_ctxLo,dg),
             DoubleToString(g_ctxRefPct,4),DoubleToString(g_ctxMedPct,4),
             DoubleToString(g_ctxSpreadPct,4),DoubleToString(spr,4),
             DoubleToString(gain,3),DoubleToString(dd,3),DoubleToString(RiskMultiplier(),3));
   FileClose(h);
   g_journaled=true;
   SaveTradeDayState();
   Notify(SYM+" journaled entry -> MQL5/Files/"+fn);
}

//--------------------------- trailing --------------------------------//
void LoadTrailState()
{
   double v=0;
   if(GVGet(SymPrefix()+"T_HAVE",v)) g_haveTrade=(v>0.5);
   if(GVGet(SymPrefix()+"T_LONG",v)) g_tLong=(v>0.5);
   if(GVGet(SymPrefix()+"T_ENTRY",v))g_tEntry=v;
   if(GVGet(SymPrefix()+"T_RISK",v)) g_tRisk=v;
   if(GVGet(SymPrefix()+"T_PEAK",v)) g_tPeak=v;
   g_lastPeakPersist=g_tPeak;
   g_lastPeakPersistTime=TimeTradeServer();
   if(!HasPosition(SYM)) ClearTrailState();
   else if(!g_haveTrade || g_tRisk<=0)
   {
      g_haveTrade=false; g_tRisk=0;
      Notify(SYM+" existing position has no saved initial-R; trailing disabled for it.");
   }
}
void ManageTrailing()
{
   if(TrailStopR<=0 || !g_haveTrade || g_tRisk<=0) return;
   if(FreezeTrailInNews && IsNewsBlackout(SYM)) return;
   ulong tk=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0) continue;
      if(PositionGetString(POSITION_SYMBOL)==SYM &&
         PositionGetInteger(POSITION_MAGIC)==g_magic){ tk=t; break; }
   }
   if(tk==0){ ClearTrailState(); return; }
   double sl=PositionGetDouble(POSITION_SL);
   double tp=PositionGetDouble(POSITION_TP);
   bool isLong=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY);
   double bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   int digits=(int)SymbolInfoInteger(SYM,SYMBOL_DIGITS);
   double point=SymbolInfoDouble(SYM,SYMBOL_POINT);
   double stopLvl=BrokerProtectionDistance(SYM);
   if(isLong)
   {
      double oldPeak=g_tPeak;
      g_tPeak=MathMax(g_tPeak,bid);
      if(g_tPeak!=oldPeak) PersistTrailPeakIfNeeded();
      if((g_tPeak-g_tEntry)/g_tRisk>=TrailStopR)
      {
         double newSL=NormalizeDouble(g_tPeak-TrailStopR*g_tRisk,digits);
         if(newSL>sl+point && newSL<bid-stopLvl)
            if(CheckTradeCall(trade.PositionModify(tk,newSL,tp),"TrailModify")) SaveTrailState();
      }
   }
   else
   {
      double oldPeak=g_tPeak;
      g_tPeak=MathMin(g_tPeak,ask);
      if(g_tPeak!=oldPeak) PersistTrailPeakIfNeeded();
      if((g_tEntry-g_tPeak)/g_tRisk>=TrailStopR)
      {
         double newSL=NormalizeDouble(g_tPeak+TrailStopR*g_tRisk,digits);
         if((sl==0 || newSL<sl-point) && newSL>ask+stopLvl)
            if(CheckTradeCall(trade.PositionModify(tk,newSL,tp),"TrailModify")) SaveTrailState();
      }
   }
}

//--------------------------- lifecycle/state -------------------------//
void LoadState()
{
   datetime today=UtcDayStart(TimeGMT());
   double v=0;
   g_utcTradeDay=today;
   if(GVGet(SymPrefix()+"UTC_DAY",v) && (datetime)(long)v==today)
   {
      if(GVGet(SymPrefix()+"TRADED",v)) g_tradedToday=(v>0.5);
      if(GVGet(SymPrefix()+"FRIFLAT",v))g_fridayFlat =(v>0.5);
      if(GVGet(SymPrefix()+"JOURNALED",v))g_journaled=(v>0.5);
   }
   else
   {
      g_tradedToday=false; g_fridayFlat=false; g_journaled=false;
      SaveTradeDayState();
   }
   g_ftmoDay=FtmoDayStart(TimeGMT());
   g_ftmoOpenBal=ReconstructFtmoOpenBalance(g_ftmoDay);
   double savedFtmoDay=0, guardDay=0, guardAll=0;
   if(GVGet(FtmoPrefix()+"FTMO_DAY",savedFtmoDay) && (datetime)(long)savedFtmoDay==g_ftmoDay)
   {
      if(GVGet(FtmoPrefix()+"GUARD_DAY",guardDay)) g_guardTripped=(guardDay>0.5);
   }
   if(GVGet(FtmoPrefix()+"GUARD_ALL",guardAll)) g_overallGuardTripped=(guardAll>0.5);
   if(g_overallGuardTripped) g_guardTripped=true;
   SaveFtmoState();
   LoadTrailState();
}

int OnInit()
{
   SYM=_Symbol;
   STRAT=DetectStrategy();
   g_magic=Magic+OrbRangeHourUTC;      // per-session id; = Magic when OrbRangeHourUTC=0

   if(RequireAccountSize && AccountSize<=0)
   {
      Print("ERROR: Set AccountSize to the real starting account size (e.g. 25000). EA not started.");
      return INIT_PARAMETERS_INCORRECT;
   }
   g_initBal=(AccountSize>0 ? AccountSize : AccountInfoDouble(ACCOUNT_BALANCE));
   if(g_initBal<=0) return INIT_FAILED;

   double savedInit=0.0;
   if(GVGet(FtmoPrefix()+"INIT_BAL",savedInit) && savedInit>0 && MathAbs(savedInit-g_initBal)>0.01)
   {
      PrintFormat("ERROR: AccountSize %.2f conflicts with persisted FTMO initial balance %.2f.",
                  g_initBal,savedInit);
      return INIT_PARAMETERS_INCORRECT;
   }
   if(RiskPct<=0 || LossBufferPct<0 || LossBufferPct>=FTMO_DAILY_LOSS_PCT ||
      LossBufferPct>=FTMO_OVERALL_LOSS_PCT || MarginSafetyFactor<1.0 ||
      MaxSpreadPoints<0 || MaxSpreadToStopPct<0 || ExtraStopBufferPts<0 ||
      OrbHours<1 || OrbHours>12 || OrbRangeHourUTC<0 || OrbRangeHourUTC>23)
   {
      Print("ERROR: invalid risk/execution/strategy parameters.");
      return INIT_PARAMETERS_INCORRECT;
   }
   // v3.13: the risk modulators must only ever REDUCE risk. RiskMultiplier() returns
   // these directly, so a value > 1 would RAISE risk (e.g. a typo NearTargetMult=2.0
   // doubles risk near the target). Bound them to (0, 1].
   if(NearTargetMult<=0 || NearTargetMult>1.0 ||
      DeriskMult1<=0   || DeriskMult1>1.0   ||
      DeriskMult2<=0   || DeriskMult2>1.0)
   {
      Print("ERROR: risk multipliers (NearTargetMult, DeriskMult1/2) must be >0 and <=1.");
      return INIT_PARAMETERS_INCORRECT;
   }
   // v3.13: the ORB window must not cross UTC midnight (the hour test and the arming
   // time do not wrap). Reject rather than silently mis-arm.
   if(OrbRangeHourUTC+OrbHours>24)
   {
      Print("ERROR: OrbRangeHourUTC + OrbHours must be <= 24 (no midnight wrap).");
      return INIT_PARAMETERS_INCORRECT;
   }
   // v3.14: governor inputs are reserves/ceilings — never negative, and the
   // retry count must be >=1. Rejected rather than silently mis-behaving.
   if(SlippageGapBufferPct<0 || DailyFloorSafetyPct<0 || GovCostBufferPct<0 ||
      MaxTotalOpenRiskPct<0  || MaxCorrelatedRiskPct<0 || GovInflightRetries<1)
   {
      Print("ERROR: governor buffers/ceilings must be >=0 and GovInflightRetries >=1.");
      return INIT_PARAMETERS_INCORRECT;
   }
   trade.SetExpertMagicNumber(g_magic);
   trade.SetTypeFillingBySymbol(SYM);
   SymbolSelect(SYM,true);
   LoadState();
   // v3.14 (1): read and LOG the account margin mode (netting vs hedging). No
   // gating — this is visibility only. Multi-session isolation assumes hedging;
   // netting merges same-symbol positions. Verify on demo before multi-session.
   long marginMode=AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   string mmName=(marginMode==ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)?"RETAIL_HEDGING":
                 (marginMode==ACCOUNT_MARGIN_MODE_RETAIL_NETTING)?"RETAIL_NETTING":
                 (marginMode==ACCOUNT_MARGIN_MODE_EXCHANGE)?"EXCHANGE":"UNKNOWN";
   Notify(StringFormat("Aurvex v3.14 ACCOUNT_MARGIN_MODE=%s (%d) — magic isolation assumes HEDGING; verify on demo before BTC multi-session.",mmName,(int)marginMode));
   // v3.14 (4): reset the cross-instance in-flight reservation token to 0. This
   // also clears any reservation leaked by a prior crash mid-send (committed risk
   // is always recomputed from the live broker scan, so this is safe).
   GovInflightReset();
   int sec=MathMax(1,TimerSeconds);
   EventSetTimer(sec);
   Notify(StringFormat("Aurvex v3.14-safety on %s strat=%s magic=%d orbHourUTC=%d minRangeMult=%.2f pdhlMinRangeMult=%.2f pdhlBackScan=%s base=%.2f serverOffsetH=%d journal=%s governor=%s",
          SYM,STRAT,(int)g_magic,OrbRangeHourUTC,MinRangeMedMult,PdhlMinRangeMedMult,
          (PdhlUseBackScan?"on":"off"),g_initBal,(int)(ServerUtcOffset()/3600),
          (JournalTrades?"on":"off"),(GovernorEnabled?"ON":"off")));
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
   SaveTradeDayState();
   SaveFtmoState();
   SaveTrailState();
   EventKillTimer();
   if(DrawLevels) DeleteLevels();
}

//--------------------------- immediate trade event -------------------//
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   string ds=HistoryDealGetString(trans.deal,DEAL_SYMBOL);
   long magic=HistoryDealGetInteger(trans.deal,DEAL_MAGIC);
   if(ds!=SYM || magic!=g_magic) return;
   ENUM_DEAL_ENTRY entryType=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   if(entryType!=DEAL_ENTRY_IN && entryType!=DEAL_ENTRY_INOUT) return;
   ENUM_DEAL_TYPE dealType=(ENUM_DEAL_TYPE)HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   bool isBuy=(dealType==DEAL_TYPE_BUY);
   if(dealType!=DEAL_TYPE_BUY && dealType!=DEAL_TYPE_SELL) return;

   g_tradedToday=true;
   g_utcTradeDay=UtcDayStart(TimeGMT());
   SaveTradeDayState();
   DeletePendings(SYM);

   if(!g_haveTrade)
   {
      double plannedEntry=0,plannedSL=0;
      double fill=HistoryDealGetDouble(trans.deal,DEAL_PRICE);
      if(LoadPlan(isBuy,plannedEntry,plannedSL) && plannedSL>0)
      {
         g_haveTrade=true; g_tLong=isBuy; g_tEntry=fill;
         g_tRisk=MathAbs(fill-plannedSL); g_tPeak=fill;
         SaveTrailState();
      }
      else Notify(SYM+" fill detected but original SL plan missing; trailing disabled.");
   }
   JournalOnFill();
   Notify(StringFormat("%s fill detected; opposite pending cancelled; tradedToday=1",SYM));
}

void OnTick()
{
   if(FtmoDayStart(TimeGMT())!=g_ftmoDay) RefreshFtmoDay(TimeGMT());
   if(!LossGuardOk()){ EmergencyFlatten(); g_tradedToday=true; SaveTradeDayState(); return; }
   if(HasPosition(SYM))
   {
      g_tradedToday=true; SaveTradeDayState();
      DeletePendings(SYM); ManageTrailing();
   }
}

void OnTimer()
{
   datetime nowGmt=TimeGMT();
   RefreshFtmoDay(nowGmt);
   datetime today=UtcDayStart(nowGmt);
   if(today!=g_utcTradeDay)
   {
      FlattenSymbol(SYM);
      g_utcTradeDay=today;
      g_tradedToday=false; g_fridayFlat=false; g_journaled=false;
      ClearTrailState();
      SaveTradeDayState();
      if(DrawLevels) DeleteLevels();
      Notify(SYM+" new UTC strategy day; flat and ready.");
   }
   MqlDateTime st; TimeToStruct(nowGmt,st);
   int dow=st.day_of_week;
   if(dow==0 || dow==6) return;
   int minuteUtc=(int)(((long)nowGmt%86400)/60);
   if(dow==5 && minuteUtc>=FridayFlattenUTCMin)
   {
      if(!g_fridayFlat){ FlattenSymbol(SYM); g_fridayFlat=true; SaveTradeDayState(); Notify(SYM+" Friday flatten complete."); }
      return;
   }
   if(!LossGuardOk()){ EmergencyFlatten(); g_tradedToday=true; SaveTradeDayState(); return; }
   if(HasPosition(SYM))
   {
      g_tradedToday=true; SaveTradeDayState();
      DeletePendings(SYM); JournalOnFill(); ManageTrailing(); return;  // v3.13: retry journal if the fill-event write missed
   }
   if(g_tradedToday){ DeletePendings(SYM); return; }
   if(IsNewsBlackout(SYM)){ DeletePendings(SYM); return; }

   double bid=SymbolInfoDouble(SYM,SYMBOL_BID);
   double ask=SymbolInfoDouble(SYM,SYMBOL_ASK);
   double px=(bid>0 && ask>0)?(bid+ask)/2.0:bid;
   if(px<=0) return;

   if(STRAT=="ORB")
   {
      if(nowGmt<today+(datetime)(OrbRangeHourUTC+OrbHours)*3600) return;
      double hi,lo;
      if(!OpeningRange(SYM,today,hi,lo)) return;
      if(DrawLevels) DrawSetup(hi,lo,lo,hi);
      if(px<lo || px>hi)
      {
         g_tradedToday=true; SaveTradeDayState(); DeletePendings(SYM);
         Notify(SYM+" ORB already broken before arming; skip day."); return;
      }
      if(MinRangeMedMult>0)
      {
         double mid=(hi+lo)/2.0; double todayRp=(mid>0)?(hi-lo)/mid:0;
         double med=OrbMedianRangePct(SYM,OrbRangeHourUTC,OrbHours,today,20);
         if(med>0 && todayRp<MinRangeMedMult*med)
         {
            g_tradedToday=true; SaveTradeDayState();
            Notify(SYM+" ORB opening range "+DoubleToString(todayRp*100,3)+"% < "+
                   DoubleToString(MinRangeMedMult,2)+"x median "+DoubleToString(med*100,3)+"% — skip (low-vol day)");
            return;
         }
      }
      if(JournalTrades)
      {
         g_ctxHi=hi; g_ctxLo=lo;
         double m0=(hi+lo)/2.0; g_ctxRefPct=(m0>0)?(hi-lo)/m0*100.0:0;
         double med0=OrbMedianRangePct(SYM,OrbRangeHourUTC,OrbHours,today,20);
         g_ctxMedPct=(med0>0)?med0*100.0:-1;
         g_ctxSpreadPct=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
      }
      EnsureStops(SYM,hi,lo,lo,hi,"AurvexORB312");
   }
   else
   {
      if(!PdhlSessionAllowed(nowGmt)){ DeletePendings(SYM); return; }
      double ph,pl,atr;
      if(!PrevTradingDayRange(SYM,today,ph,pl)) return;
      if(!Atr14(SYM,atr)) return;
      double d=PdhlStopATR*atr;
      if(DrawLevels) DrawSetup(ph,ph-d,pl,pl+d);
      if(px<pl || px>ph)
      {
         g_tradedToday=true; SaveTradeDayState(); DeletePendings(SYM);
         Notify(SYM+" PDHL already broken before arming; skip day."); return;
      }
      if(PdhlMinRangeMedMult>0)
      {
         double refRp,medRp;
         if(PrevDayRangePctMed(SYM,today,20,refRp,medRp) && medRp>0 && refRp<PdhlMinRangeMedMult*medRp)
         {
            g_tradedToday=true; SaveTradeDayState();
            Notify(SYM+" PDHL prior-day range "+DoubleToString(refRp*100,3)+"% < "+
                   DoubleToString(PdhlMinRangeMedMult,2)+"x median "+DoubleToString(medRp*100,3)+"% — skip (low-vol day)");
            return;
         }
      }
      if(JournalTrades)
      {
         g_ctxHi=ph; g_ctxLo=pl;
         double mp=(ph+pl)/2.0; g_ctxRefPct=(mp>0)?(ph-pl)/mp*100.0:0;
         double refRp2,medRp2;
         g_ctxMedPct=PrevDayRangePctMed(SYM,today,20,refRp2,medRp2)?medRp2*100.0:-1;
         g_ctxSpreadPct=(px>0&&ask>0&&bid>0)?(ask-bid)/px*100.0:0;
      }
      EnsureStops(SYM,ph,ph-d,pl,pl+d,"AurvexPDHL312");
   }
}
//+------------------------------------------------------------------+
```

## 6.2 Governor referans modeli (Python) — `src/aurvex/ftmo/risk_governor.py`
MQL5 governor matematiğinin test edilebilir Python aynası (üretim EA ile senkron tutulur).

```python
"""Account-Level Risk Governor — Python reference model (v3.14).

This mirrors, in testable Python, the *math* of the MQL5 governor in
``mql5/AurvexFTMO_v3_14_safety_candidate.mq5``. The MT5 EA is the production
artifact; this module exists so the governor's decision logic (dynamic headroom,
buffers, OCO double-leg reservation, cross-instance race serialization,
reconciliation) can be unit-tested without a terminal. Keep the two in sync.

Design invariants (identical to the EA):
  * Committed risk is the tighter of the two FTMO floor headrooms MINUS reserved
    buffers; the binding constraint is ``min(daily_headroom, overall_headroom)``.
  * Committed risk is derived from a *scan* of open positions (worst-case loss
    from the current price to the current SL) plus pending orders (entry->SL,
    with BOTH OCO legs counted — the double-trigger / gap-through case).
  * The governor can only REJECT an order or leave it unchanged. It never raises
    risk and never resizes an order upward. When disabled it is a pass-through.
  * ``reserve-then-validate``: an order's risk is added to a shared in-flight
    budget FIRST, then validated against (scan + in-flight). Concurrent instances
    therefore see each other's reservation and fail safe (reject) rather than
    both over-committing.
  * The in-flight budget is a sub-second race token, reset to 0 on (re)start;
    committed risk itself always comes from the live scan, so it self-reconciles
    after a restart or crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

FTMO_DAILY_LOSS_PCT = 5.0
FTMO_OVERALL_LOSS_PCT = 10.0


@dataclass
class Exposure:
    """Live broker exposure as the governor scan sees it. Risks are positive
    money amounts (worst-case loss). Both OCO legs appear in ``pending_risks``."""
    open_risks: List[float] = field(default_factory=list)      # per open position, from-now->SL
    pending_risks: List[float] = field(default_factory=list)   # per pending order, entry->SL

    def committed(self) -> float:
        return sum(self.open_risks) + sum(self.pending_risks)


@dataclass
class Headroom:
    """Dynamic headroom from the same floor formulas as LossGuardOk()."""
    equity: float
    day_open_balance: float
    init_bal: float
    loss_buffer_pct: float = 1.0
    slip_gap_pct: float = 0.5
    safety_pct: float = 0.5
    cost_pct: float = 0.1

    @property
    def daily_floor(self) -> float:
        daily_eff = max(0.0, FTMO_DAILY_LOSS_PCT - self.loss_buffer_pct)
        return self.day_open_balance - self.init_bal * daily_eff / 100.0

    @property
    def overall_floor(self) -> float:
        overall_eff = max(0.0, FTMO_OVERALL_LOSS_PCT - self.loss_buffer_pct)
        return self.init_bal - self.init_bal * overall_eff / 100.0

    @property
    def day_headroom(self) -> float:
        return self.equity - self.daily_floor

    @property
    def overall_headroom(self) -> float:
        return self.equity - self.overall_floor

    def allowed(self) -> float:
        """Binding headroom minus reserves. The tighter floor wins."""
        slip = self.slip_gap_pct / 100.0 * self.init_bal
        safety = self.safety_pct / 100.0 * self.init_bal
        cost = self.cost_pct / 100.0 * self.init_bal
        return min(self.day_headroom, self.overall_headroom) - slip - safety - cost


class InflightBudget:
    """Shared, atomic in-flight reservation token (models the AXGOV INFLIGHT GV
    with GlobalVariableSetOnCondition). A single instance is shared across the
    'EA instances' in a race test."""

    def __init__(self) -> None:
        self._v = 0.0

    def add(self, delta: float) -> bool:
        self._v = max(0.0, self._v + delta)
        return True

    def get(self) -> float:
        return self._v

    def reset(self) -> None:
        self._v = 0.0


def try_reserve(
    exposure: Exposure,
    headroom: Headroom,
    inflight: InflightBudget,
    r_new: float,
    *,
    max_total_pct: float = 0.0,
    max_corr_pct: float = 0.0,
    group_committed: float = 0.0,
) -> bool:
    """Reserve-then-validate. Returns True iff the order may be placed; on True
    the caller must later call ``release`` with the same ``r_new``. Mirrors
    GovernorTryReserve() in the EA exactly.

    Fail-closed: a non-positive r_new, or no headroom, rejects.
    Never-raise: r_new is used as-is; the governor never increases it.
    """
    if r_new <= 0:
        return False
    allowed = headroom.allowed()
    if allowed <= 0:
        return False
    inflight.add(r_new)  # reserve FIRST so concurrent instances see it
    committed = exposure.committed() + inflight.get()
    ok = committed <= allowed
    if ok and max_total_pct > 0 and committed > max_total_pct / 100.0 * headroom.init_bal:
        ok = False
    if ok and max_corr_pct > 0 and (group_committed + r_new) > max_corr_pct / 100.0 * headroom.init_bal:
        ok = False
    if not ok:
        inflight.add(-r_new)  # rollback
        return False
    return True


def release(inflight: InflightBudget, r_new: float) -> None:
    """Release the in-flight reservation after the OrderSend (success or fail);
    once placed, the order is counted by the live scan instead."""
    if r_new > 0:
        inflight.add(-r_new)
```

## 6.3 Governor testleri — `tests/test_ftmo_governor.py` (16 test, hepsi geçiyor)

```python
"""Account-Level Risk Governor reference-model tests (v3.14).

These verify the governor MATH that the MQL5 EA implements
(mql5/AurvexFTMO_v3_14_safety_candidate.mq5). Terminal-runtime scenarios
(fill / partial fill / restart / crash / netting vs hedging) are verified on the
demo per FTMO_V314_DEMO_CHECKLIST.md — they need MT5, not Python.
"""
from aurvex.ftmo.risk_governor import (Exposure, Headroom, InflightBudget,
                                       release, try_reserve)


def _headroom(equity=25_000, day_open=25_000, init=25_000, **kw):
    return Headroom(equity=equity, day_open_balance=day_open, init_bal=init, **kw)


# -- headroom = min(daily, overall), buffers subtract exactly ----------------
def test_daily_floor_binds_at_day_start():
    # fresh day: day_open == init. daily_eff 4% => daily floor 24000 (headroom 1000);
    # overall_eff 9% => overall floor 22750 (headroom 2250). Daily is tighter.
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.day_headroom == 1000.0
    assert h.overall_headroom == 2250.0
    assert h.allowed() == 1000.0  # min of the two


def test_overall_floor_can_bind_after_prior_day_gains():
    # after gains the day resets high: day_open 27000 => daily floor 27000-1000=26000;
    # equity 26500 => day headroom 500; overall floor 22750 => overall headroom 3750.
    h = _headroom(equity=26_500, day_open=27_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.allowed() == 500.0  # daily still tighter here


def test_overall_binds_when_deep_below_start():
    # equity 23000, day_open 23000 (reset low): daily floor 22000 => day headroom 1000;
    # overall floor 22750 => overall headroom 250. Overall is now tighter.
    h = _headroom(equity=23_000, day_open=23_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.overall_headroom == 250.0
    assert h.allowed() == 250.0


def test_buffers_reduce_allowed_by_exact_amounts():
    base = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0).allowed()  # 1000
    h = _headroom(slip_gap_pct=0.5, safety_pct=0.5, cost_pct=0.1)         # 125+125+25=275
    assert base - h.allowed() == 275.0


# -- realized + floating loss both consume headroom (equity basis) -----------
def test_floating_loss_reduces_headroom():
    # a floating loss shows up as equity < balance; equity drives the floor test.
    h = _headroom(equity=24_500, day_open=25_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.day_headroom == 500.0  # 24500 - 24000
    assert h.allowed() == 500.0


def test_realized_loss_via_lower_equity_forces_reject():
    h = _headroom(equity=24_100, slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 100
    inflight = InflightBudget()
    assert try_reserve(Exposure(), h, inflight, r_new=150) is False   # 150 > 100
    assert inflight.get() == 0.0                                       # rolled back
    assert try_reserve(Exposure(), h, inflight, r_new=90) is True      # 90 <= 100


# -- never-raise / fail-closed ----------------------------------------------
def test_governor_never_raises_reservation():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    assert try_reserve(Exposure(), h, inflight, r_new=200) is True
    assert inflight.get() == 200.0  # exactly r_new, never more
    release(inflight, 200)
    assert inflight.get() == 0.0


def test_nonpositive_risk_is_rejected():
    h = _headroom()
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=0) is False
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=-50) is False


def test_no_headroom_rejects_everything():
    h = _headroom(equity=24_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 0
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=1) is False


# -- committed risk from scan (open + pending) ------------------------------
def test_open_and_pending_risk_consume_budget():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    exp = Exposure(open_risks=[400], pending_risks=[300])    # committed 700
    inflight = InflightBudget()
    assert try_reserve(exp, h, inflight, r_new=250) is True   # 700+250=950 <= 1000
    release(inflight, 250)
    assert try_reserve(exp, h, inflight, r_new=350) is False  # 700+350=1050 > 1000


# -- OCO double-leg: both legs counted; 2nd leg rejected if only one fits ----
def test_oco_second_leg_rejected_when_only_one_fits():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    exp = Exposure()
    # leg 1 (buy stop) risk 600 -> reserve, "place" (moves into scan as pending)
    assert try_reserve(exp, h, inflight, r_new=600) is True
    release(inflight, 600)
    exp.pending_risks.append(600)          # now visible to the scan
    # leg 2 (sell stop) risk 600 -> both legs would be 1200 > 1000 -> reject
    assert try_reserve(exp, h, inflight, r_new=600) is False
    # a smaller opposite leg that keeps the pair within budget is allowed
    assert try_reserve(exp, h, inflight, r_new=300) is True   # 600+300=900 <= 1000


# -- cross-instance race: reserve-then-validate serializes -------------------
def test_two_instances_cannot_double_commit():
    # shared budget, shared inflight token. Each instance wants 600; allowed 1000.
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    shared = InflightBudget()
    exp = Exposure()
    a = try_reserve(exp, h, shared, r_new=600)   # A reserves 600 (inflight 600)
    b = try_reserve(exp, h, shared, r_new=600)   # B sees 600 inflight -> 1200 > 1000 -> reject
    assert a is True and b is False
    assert shared.get() == 600.0                 # only A's reservation stands


def test_race_both_small_enough_both_pass():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    shared = InflightBudget()
    exp = Exposure()
    assert try_reserve(exp, h, shared, r_new=400) is True    # inflight 400
    assert try_reserve(exp, h, shared, r_new=400) is True    # 800 <= 1000
    assert shared.get() == 800.0


# -- reconciliation after restart: scan is the ground truth ------------------
def test_reconcile_after_restart_from_scan():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    inflight.add(500)          # leaked reservation from a crash mid-send
    inflight.reset()           # OnInit clears the token
    assert inflight.get() == 0.0
    # committed risk still reflects real broker state (a live pending of 800)
    exp = Exposure(pending_risks=[800])
    assert try_reserve(exp, h, inflight, r_new=150) is True   # 800+150 <= 1000
    release(inflight, 150)
    assert try_reserve(exp, h, inflight, r_new=250) is False  # 800+250 > 1000


# -- static ceilings (optional extra caps, never loosen) --------------------
def test_max_total_ceiling_can_bind_before_headroom():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    # 2% of 25000 = 500 ceiling; headroom would allow 1000 but ceiling binds
    assert try_reserve(Exposure(open_risks=[300]), h, InflightBudget(),
                       r_new=300, max_total_pct=2.0) is False  # 600 > 500
    assert try_reserve(Exposure(open_risks=[100]), h, InflightBudget(),
                       r_new=300, max_total_pct=2.0) is True   # 400 <= 500


def test_correlated_group_ceiling_binds():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    # metals group already holds 400; corr cap 2% = 500; new 300 -> 700 > 500 reject
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=300,
                       max_corr_pct=2.0, group_committed=400) is False
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=100,
                       max_corr_pct=2.0, group_committed=400) is True
```

## 6.4 Araştırma scriptleri (repoda, reproducible — burada listelenmiş)
`scripts/` altında (PYTHONPATH=src:scripts):
- `ftmo_deep_portfolio.py` — hesap-düzeyi dağılım/de-risk/leg getiri serileri.
- `ftmo_funded_growth.py`, `_payout.py`, `_blockboot.py`, `_grid.py` — Funded Mode.
- `ftmo_silver_carry_deep.py` — Runner Carry (reddedildi).
- `ftmo_pdhl_filter_test.py`, `ftmo_trail_probe.py` — filtre/PDHL/ORB probe.
- (scratchpad'de: carry, costbreak, hybrid, ownmodel, ownta, voltarget, fbr_honest...)

---

# BÖLÜM 7 — Yolculuk ve dürüst değerlendirme

## 7.1 Ne denedik, ne öğrendik
Üç ayrı yoldan ("kendi TA'mız", "farklı enstrümanlar", "ters matematik", "rejim-adaptif",
"risk artır") aynı cevaba vardık: **modest bir kırılım edge'i bu işin tavanı.** Giriş
öngörülemez (capstone). 12+ giriş-fikri OOS'ta çöktü. Hayatta kalan iki filtre (gold, JP225)
zaten içeride. Kod ~9/10 (sağlam, hardened, governor); **sonuç asla 10/10 değil** — çünkü
sınır kod değil, edge'in doğası.

## 7.2 Motor "yeterince iyi mi?" (dürüst)
- **Mühendislik: iyi.** Mekanik olarak çalışıyor; KAPI-1'de fill'ler temiz.
- **Edge: modest ve henüz canlıda kanıtlanmadı** (KAPI-1 net −%2.5).
- Asıl "yeterince iyi olmayan" şey büyük ihtimalle motor değil — **beklenti**: $25k'da,
  sıkı FTMO bariyerleriyle, modest bir edge'in **güvenilir gelir** üretmesini beklemek.
  Motor ne kadar iyi olsa da bu düşük-olasılık + yüksek-varyans bir yol.

## 7.3 Ayna (psikoloji = edge'in kaderi)
Tekrarlayan desen: küçük/negatif P&L → "yeterince iyi değil → daha fazla değiştir/risk artır/
başka yol". Bu istek her seferinde veri "modest, girişi zamanlayamayız" dedikten SONRA geldi.
Bu döngü, modest ama gerçek bir edge'i olan hesapları tam olarak batıran şeydir — sistem değil.
Gösterilen disiplin de gerçek: "maksimum risk" yerine 1.3× seçildi; dış göz (arkadaş kodu,
ChatGPT) arandı. **Asıl edge bir teknikte değil: o küçük/negatif P&L'lere ve "başka yol"
sesine rağmen sabredebilmende.**

## 7.4 Guardrail'ler (kanıtlanmış — tekrarlama)
- ❌ Yeni giriş-edge/filtre/"akıllı giriş" arama (öngörülemez — kanıtlandı).
- ❌ Riski artırma (bounded challenge varyans-kısıtlı; risk↑ = geçme↓ + bust↑).
- ❌ Pyramiding / kazanana ekleme (−0.40R).
- ❌ Reddedilenleri yeniden ambalajlama (FBR, cross-confirmation...).
- ✅ Gerçek lever'lar: gold/JP225 vol-filtre, de-risk (asla kapatma), düşük risk + çeşitlendirme.
- ✅ Sıradaki gerçek adım: veri (KAPI) → gerçek edge ölçümü.

---

# BÖLÜM 8 — Sonraki adımlar

1. **Canlı v3.11 (bugün):** BTCUSD + US100.cash grafiğini kaldır. Kalan 4'ü çalıştır.
2. **v3.13'e geçiş (test edilince):** F7 derle + demo doğrula → 4 enstrüman + gold/JP225
   filtreleri açık + GER40 calendar-PDHL. AccountSize=25000 her grafikte.
3. **KAPI-2:** yeni config'le 25-30 işlem biriktir → bu analizi tekrar koş. Hedef:
   config-farkı çıkınca kalan gerçek edge pozitif mi?
4. **v3.14 governor:** yalnız KAPI + demo doğrulamasından SONRA `GovernorEnabled=true`.
5. **Risk:** 1.3× standing; negatif gidişatta 1.0× öneriliyor (kullanıcı kararı).
6. **Duruş:** bunu tek gelir gibi değil, küçük bir edge gibi tut. Runway'i koru.

---

# EK — Dosya indeksi (repo, branch `ftmo-final`)
- `FTMO_MASTER.md` — bu dosya (her şey tek yerde).
- `FTMO_START_HERE.md` — yeni oturum için oryantasyon.
- `FTMO_KAPI1_FINDINGS.md` — KAPI-1 canlı analiz.
- `FTMO_V313_INPUTS.md`, `FTMO_V313_PER_INSTRUMENT_SETUP.md` — config.
- `FTMO_FUNDED_GROWTH_RESEARCH.md`, `FTMO_RUNNER_CARRY_RESEARCH.md`,
  `FTMO_RISK_GOVERNOR_AND_BTC_AUDIT.md`, `FTMO_V314_ARCHITECTURE.md`,
  `FTMO_V314_SAFETY_CANDIDATE.md` — araştırma/rapor.
- `FTMO_JOURNEY/` — sorular + bulgular + öz-analiz aynası.
- `mql5/AurvexFTMO_v3_14_safety_candidate.mq5`, `mql5/AurvexFTMO_v3_13_final.mq5` — EA.
- `src/aurvex/ftmo/`, `tests/test_ftmo_*.py`, `scripts/ftmo_*.py` — model/test/araştırma.
