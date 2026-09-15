# Step 3 — Account-Level Risk Governor (dinamik) + BTC multi-session audit (DÜZELTİLMİŞ)

> **Kullanıcı incelemesine göre düzeltildi:** (a) governor artık sabit
> `MaxTotalOpenRiskPct` değil, **dinamik headroom-tabanlı**; (b) pending OCO
> çift-tetikleme ayrıca modellendi; (c) "FTMO tipik olarak netting" varsayımı
> **kaldırıldı** — hesap türü kanıtlanana kadar KARARSIZ. **Üretim kodu değişmedi.**

Audit hedefi: `mql5/AurvexFTMO_v3_13_final.mq5`.

---

## A) BTC multi-session audit — DÜZELTİLMİŞ

### ✅ Doğru olan (hedging semantiğinde)
- Per-session effective magic `g_magic = Magic + OrbRangeHourUTC` (987).
- Tüm ownership helper'ları `POSITION_MAGIC==g_magic` + sembol filtreli
  (HasPosition 368, HasPendingSide 379, DeletePendings 392, FlattenSymbol 403,
  journal 853, trailing 911).
- GV state izolasyonu `FtmoPrefix()` = `AX3_<login>_<g_magic>_` (129).

### ⚠️ Bulgu — hesap türü kontrol edilmiyor (varsayım KALDIRILDI)
**EA hiçbir yerde `ACCOUNT_MARGIN_MODE` okumuyor** (grep: eşleşme yok).
Magic-tabanlı izolasyon **hedging** semantiği varsayar.
- **NETTING** hesapta aynı sembolde aynı anda birden fazla pozisyon tutulamaz →
  pozisyonlar tek net pozisyona birleşir → magic izolasyonu pozisyon düzeyinde
  bozulur (çapraz-kapanma, orphan-SL). **HEDGING** hesapta izolasyon doğru çalışır.
- **Gerçek FTMO hesabının türü bu repoda kanıtlanmadı.** Önceki sürümdeki "FTMO
  tipik olarak netting" ifadesi **doğrulanmamış varsayımdı; kaldırıldı.** Hesap
  türü broker/hesap ayarına göre değişebilir.

### Karar: BTC multi-session = **KARARSIZ / KOŞULLU**
- Gerçek hesap `ACCOUNT_MARGIN_MODE` değeri **kanıtlanana kadar** multi-session
  lever'ı KARARSIZ. Tek-seans (OrbRangeHourUTC=0) her iki türde de güvenli.
- **v3.14 tasarım (minimal, güvenli):**
  1. OnInit'te `ACCOUNT_MARGIN_MODE` **oku ve açıkça logla** (Print + journal).
     Otomatik reddetme YOK — sadece görünürlük.
  2. Multi-session (birden fazla instance / OrbRangeHourUTC≠0) **yalnızca**
     `ConfirmHedgingVerified=true` (default false) **ve** demo üzerinde
     hedging/netting davranışı doğrulandıktan sonra açılır.
  3. Doğrulama yapılmadan multi-session açılmaz; tek-seans default kalır.

### ⚠️ İkincil (yalnızca netting'de sorun; hedging'de yok)
- Trailing sahipliği: birleşik net pozisyonun magic'i "ilk dolan"a ait olabilir.
- OnTradeTransaction fill capture (1059): birleşme deal'ında magic farklı gelebilir.
- Her ikisi de **yalnızca netting'de** geçerli; demo doğrulaması bunu ölçecek.

---

## B) Account-Level Risk Governor — DİNAMİK tasarım

### Sorun (audit)
`CalcLots` (603) her trade'i `g_initBal*RiskPct*RiskMultiplier()` ile
**instance-bağımsız** boyutlar. Hesap-düzeyi açık-risk toplaması YOK; tek
hesap-geneli kontrol *reaktif* `LossGuard` (786) — equity zemine düştükten sonra.

### Neden sabit `MaxTotalOpenRiskPct` yetmez
Sabit bir yüzde tavanı, o anki **gerçek headroom'u** bilmez: gün içinde zaten
zarar edilmişse, floating zarar varsa, ya da komisyon/swap/slippage tamponu
hesaba katılmamışsa, "izin verilen %4" günlük zemini yine de aşabilir. İzin
verilen yeni risk **o anki en dar headroom'a** bağlı olmalı.

### Dinamik headroom hesabı (pre-trade)
O anki hesap durumundan (hepsi canlı okunur):
```
eq            = ACCOUNT_EQUITY                         // realized+floating dahil
dailyFloor    = g_ftmoOpenBal - g_initBal*dailyEff/100 // mevcut EA (792)
overallFloor  = g_initBal    - g_initBal*overallEff/100// mevcut EA (793)
dayHeadroom     = eq - dailyFloor      // günlük zemine kalan
overallHeadroom = eq - overallFloor    // toplam zemine kalan
openStopRisk    = Σ pozisyon: |OrderCalcProfit(pozisyon SL'ine)|   // hepsi stop'a giderse
pendingWorst    = OCO çift-tetikleme dahil pending risk (aşağıda)
slipGapBuf      = SlippageGapBufferPct/100 * g_initBal  // gap/slippage tamponu
costBuf         = tahmini komisyon+swap (açık+yeni set)
```
Aynı anda **her şey ters giderse** kalan equity zeminlerin üstünde kalmalı:
```
committed   = openStopRisk + pendingWorst + slipGapBuf + costBuf
allowedNew  = min(dayHeadroom, overallHeadroom) - committed
```
- `allowedNew <= 0` → yeni trade **açma** (skip).
- Yeni trade'in worst-case stop-risk'i `R_new` ise: `R_new <= allowedNew` olmalı;
  değilse ya boyutu küçült ya skip (fail-closed).
- **Bağlayıcı kısıt = en dar headroom** (kullanıcı talebi: min alınıyor). Sabit
  `MaxTotalOpenRiskPct` yalnızca **ek üst-tavan** olarak kalır (dinamik hesabı
  gevşetmez, sadece daha da kısabilir).

### Pending OCO çift-tetikleme modeli
ORB her iki yöne stop koyar (BUY_STOP + SELL_STOP); "first-break-wins" ile biri
dolunca diğeri iptal. **Risk:** hızlı/gap piyasada **her iki bacak da** iptalden
önce dolabilir → çift pozisyon, çift zarar.
- Governor, bir OCO çifti için `pendingWorst`'e **iki bacağın toplam stop-zararını**
  rezerve eder (tek bacak değil), ta ki biri dolup diğeri **iptali doğrulanana**
  kadar.
- Bir bacak dolunca: diğerini hemen iptal et; iptal **onaylanana** kadar ikisini
  de rezerve tut. Onaylanınca rezervi tek pozisyona indir.
- Gap-through senaryosu için ek `slipGapBuf` (stop seviyesinin ötesine kayma).

### Instance'lar arası race-safety
Tek terminalde instance'lar arası tek kanal = GlobalVariables.
- Paylaşımlı GV: `AXGOV_<login>_COMMITTED` (açık+pending rezerve toplam risk).
  `eq`/floor'lar zaten hesap-global (her instance kendi okur).
- Rezervasyon atomik: `GlobalVariableSetOnCondition(COMMITTED, cur+R_new, cur)` —
  başarısızsa retry; K denemede olmazsa skip (fail-closed). İki instance aynı
  tick'te aynı headroom'u çift-rezerve edemez.
- **Release:** pozisyon kapanış / pending iptal-expire `OnTradeTransaction`'da
  aynı atomikle `COMMITTED -= R`.
- **Reconciliation:** OnInit + timer, `COMMITTED`'i canlı pozisyon+pending
  taramasından yeniden hesapla (drift/restart/çöküş güvenliği). GV = cache;
  gerçek = broker durumu.

### Korelasyon-grubu ek katmanı
`MaxCorrelatedRiskPct` + `SymbolGroup` (metals={XAU,XAG}, crypto={BTC×seans},
index={GER40,JP225}): grup-içi eşzamanlı openStopRisk tavanı. Dinamik headroom
zaten ana koruma; bu, korelasyonlu-gün yoğunlaşmasına ek sınır.

### Yeni input'lar (hepsi yalnızca kısıtlar; default'lar no-op)
| input | anlam | default |
|---|---|---|
| `GovernorEnabled` | dinamik governor aç/kapa | false (no-op) |
| `SlippageGapBufferPct` | gap/slippage tamponu (% initial) | 0.5 |
| `DailyFloorSafetyPct` | dayHeadroom'dan ek emniyet payı | 0.5 |
| `MaxTotalOpenRiskPct` | ek statik üst-tavan (0=off) | 0 |
| `MaxCorrelatedRiskPct` | grup-içi eşzamanlı risk tavanı | 0 |
| `MaxNewRiskPerFtmoDayPct` | gün-içi kümülatif yeni risk tavanı | 0 |
| `SymbolGroup` | korelasyon grubu | "" |

### Sınır
Yalnızca **aynı terminal** içinde çalışır (GV IPC). Çoklu terminal/VPS'te GV
paylaşılmaz → tek terminal zorunlu ya da harici koordinasyon gerekir.

---

## Audit özet
| konu | durum | v3.14 aksiyonu |
|---|---|---|
| per-session magic izolasyonu | ✅ (hedging) | — |
| GV state izolasyonu | ✅ | — |
| hesap türü kontrolü | ❌ eksik | `ACCOUNT_MARGIN_MODE` **oku+logla** (reddetme yok) |
| BTC multi-session | ⚠️ **KARARSIZ** | hesap türü kanıtlanana + demo doğrulanana kadar tek-seans |
| account-level açık-risk cap | ❌ eksik | **dinamik headroom** governor (min-of-headrooms) |
| OCO çift-tetikleme | ❌ modellenmemiş | pending çift-bacak rezervi + iptal onayı |
| korelasyon-grubu cap | ❌ eksik | `MaxCorrelatedRiskPct` + gruplar |
| reaktif loss guard | ✅ var | önleyici dinamik governor ile tamamla |
