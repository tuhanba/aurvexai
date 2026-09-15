# Step 3 — Account-Level Risk Governor tasarımı + BTC multi-session kod auditi

Bu doküman iki şeyi kapsar: (A) BTC multi-session kodunun güvenlik auditi,
(B) Account-Level Risk Governor tasarımı. **Üretim kodu bu adımda DEĞİŞTİRİLMEDİ**
— tasarım + audit; uygulama v3.14 önerisinde (`FTMO_V314_ARCHITECTURE.md`).

Audit hedefi: `mql5/AurvexFTMO_v3_13_final.mq5`.

---

## A) BTC multi-session kod auditi

Kurulum: aynı BTC sembolünde 3 ayrı grafik/EA-instance, `OrbRangeHourUTC = 0/3/13`
ile üç korelasyonsuz seans.

### ✅ Doğru olan
- **Per-session effective magic:** `g_magic = Magic + OrbRangeHourUTC` (satır 987).
  Üç instance → üç ayrı magic (Magic+0/+3/+13).
- **Ownership izolasyonu:** `HasPosition` (368), `HasPendingSide` (379),
  `DeletePendings` (392), `FlattenSymbol` (403), journal (853), trailing (911)
  hepsi `POSITION_MAGIC==g_magic` **ve** sembol ile filtreliyor. Pending ve
  (hedging'de) pozisyon düzeyinde birbirini iptal/kapatmaz.
- **GV state izolasyonu:** `FtmoPrefix()` = `AX3_<login>_<g_magic>_` (129) → plan/
  trail/trade-day GV'leri seanslar arası çakışmaz.
- **Emergency flatten:** `AccountWideEmergencyFlatten` açıkken tüm hesabı düzler
  (magic bağımsız) — kasıtlı hesap-geneli kill switch (412).

### ❌/⚠️ Kritik bulgu — NETTING vs HEDGING (en önemli)
**EA hiçbir yerde `ACCOUNT_MARGIN_MODE` kontrol etmiyor** (grep: eşleşme yok).
Magic-tabanlı izolasyon **hedging** semantiği varsayar. Ama:
- **FTMO MT5 hesapları tipik olarak NETTING'dir.** Netting'de aynı sembolde
  **aynı anda 3 ayrı pozisyon tutulamaz** — broker onları tek bir net pozisyona
  birleştirir. Sonuçlar:
  1. İki BTC seansı dolunca pozisyonlar **tek net pozisyona** birleşir; ayrı
     magic'ler korunmaz (birleşmiş pozisyon tek magic taşır).
  2. Bir seansın trailing'i (`PositionClose`/SL değişimi) diğer seansın
     "sahip olduğu" birleşik pozisyonu yönetir/kapatır.
  3. Seans-kapanış flatten'ı ortak net pozisyonu düzler.
  4. Magic'i eşleşmeyen seans birleşik pozisyonu göremez → **orphan SL** riski
     (trailing sahibi bulamaz, stop yönetilmez).
- **Yani BTC multi-session lever'ı netting hesapta yapısal olarak çalışmaz.**
  Doğrulanmış "3 korelasyonsuz seans" faydası hedging varsayımına dayanıyordu.

**Öneri (v3.14):**
- OnInit'te `ACCOUNT_MARGIN_MODE` oku. `ACCOUNT_MARGIN_MODE_RETAIL_NETTING` ise:
  - multi-session BTC (birden fazla instance aynı sembolde) **reddet/uyar**
    (INIT_FAILED veya tek-seans'a düş), **veya**
  - BTC seanslarını ayrı sembollere/alt-hesaplara koy (broker destekliyorsa),
    **veya**
  - netting'de yalnızca **tek** BTC seansı çalıştır (0 UTC), multi-session'ı
    hedging hesaplarla sınırla.
- Hedging ise mevcut magic izolasyonu doğru; değişiklik gerekmez.

### ⚠️ İkincil bulgular
- **Trailing sahipliği (netting):** birleşik pozisyonun magic'i "ilk dolan"a ait
  olabilir; sonraki seansın trailing'i onu göremez. Hedging'de sorun yok.
- **OnTradeTransaction fill capture (1059):** `if(ds!=SYM || magic!=g_magic) return;`
  — doğru filtre, ama netting'de birleşme deal'ında magic beklenenden farklı
  gelebilir → planlı-SL/orijinal-R yakalama kaçabilir. Hedging'de sorun yok.

---

## B) Account-Level Risk Governor tasarımı

### Sorun (audit bulgusu)
`CalcLots` (603) her trade'i `g_initBal*RiskPct/100*RiskMultiplier()` ile
**instance-başına bağımsız** boyutlandırır. **Hesap düzeyinde açık-risk
toplaması YOK.** Tek hesap-geneli kontrol, *reaktif* `LossGuard` (786): equity
zaten günlük/toplam zemine düştükten **sonra** tetikler.

Sonuç: N instance (XAU/XAG/BTC×3/GER40/JP225) aynı anda **N× risk** açabilir.
Korelasyonlu bir günde (altın+gümüş aynı yön, BTC 3 seans aynı yön) tek bir
ters gap, hiçbir guard tetiklemeden **günlük −%5 zemini** aşabilir — çünkü
guard floating equity'ye bakar ama toplam stop mesafesi zeminin ötesinde olabilir.

### Tasarım — pre-trade açık-risk bütçesi (GV, race-safe)
Tek terminalde instance'lar arası **tek paylaşımlı kanal = GlobalVariables**.
Governor, açılıştan **önce** talep edilen riski paylaşımlı bir bütçeye karşı
atomik rezerve eder.

**Paylaşımlı GV'ler** (prefix `AXGOV_<login>_`, magic'ten bağımsız — hesap geneli):
- `OPEN_RISK` — şu an açık+pending toplam risk (para veya % initial).
- `DAY_NEW_RISK` — bu FTMO-gününde açılan kümülatif yeni risk.
- Her yazım `GlobalVariableSetOnCondition` (atomik compare-and-set) ile.

**Yeni input'lar (hepsi cap; sadece azaltır, asla artırmaz):**
| input | anlam | önerilen |
|---|---|---|
| `MaxTotalOpenRiskPct` | tüm instance'ların anlık açık+pending risk toplamı tavanı | 4.0 |
| `MaxPendingRiskPct` | henüz dolmamış pending emirlerin risk tavanı | 3.0 |
| `MaxCorrelatedRiskPct` | aynı korelasyon-grubunda eşzamanlı risk tavanı | 2.0 |
| `MaxNewRiskPerFtmoDayPct` | bir FTMO-gününde açılan toplam yeni risk tavanı | 4.0 |
| `SymbolGroup` | bu sembolün korelasyon grubu (metals/crypto/index) | — |

**Korelasyon grupları** (validated): metals={XAU,XAG} (yüksek korelasyon),
crypto={BTC×seanslar}, index={GER40,JP225}. Grup-içi eşzamanlı risk `MaxCorrelatedRiskPct`
ile sınırlı — özellikle XAU+XAG ve BTC-3-seans aynı-yön riskini keser.

**Pre-trade akış (CalcLots'tan ÖNCE, EnsureStops içinde emir göndermeden önce):**
```
reqRisk = plannedRiskMoney(this order)      // hedeflenen risk
// atomik rezervasyon döngüsü:
repeat up to K times:
  cur = GV(OPEN_RISK)
  if cur + reqRisk > MaxTotalOpenRiskPct*initBal/100: REJECT (skip order)
  if groupRisk(SymbolGroup) + reqRisk > MaxCorrelatedRiskPct*...: REJECT
  if GV(DAY_NEW_RISK) + reqRisk > MaxNewRiskPerFtmoDayPct*...: REJECT
  if GlobalVariableSetOnCondition(OPEN_RISK, cur+reqRisk, cur): break  // atomik başarı
  else retry (başka instance araya girdi)
```
- **Release:** pozisyon kapanınca/pending iptal/expire olunca `OnTradeTransaction`
  içinde aynı atomik desenle `OPEN_RISK -= thatRisk`. `DAY_NEW_RISK` FTMO-gün
  reset'inde sıfırlanır (`RefreshFtmoDay`).
- **Reconciliation:** OnInit ve periyodik (timer) `OPEN_RISK`'i canlı
  pozisyon+pending taramasından yeniden hesapla (GV drift/restart/çöküş
  güvenliği) — GV tek gerçek kaynak değil, cache; gerçek = broker durumu.
- **Fail-closed:** GV okunamaz/atomik-set K kez başarısız → emri **açma** (skip),
  açmaya devam etme.
- **Grup risk hesabı:** her instance kendi grubunun toplam açık riskini canlı
  pozisyon taramasıyla (magic bağımsız, sembol-grubu ile) hesaplar; GV'ler
  hız için cache.

**Neden GV + SetOnCondition:** MT5'te aynı terminaldeki instance'lar bellek
paylaşmaz; GV tek IPC. `GlobalVariableSetOnCondition` tek atomik compare-and-set
sağlar → iki instance aynı tick'te aynı headroom'u çift-rezerve edemez.

**Sınır:** Bu yalnızca **aynı terminal** içinde çalışır. Birden fazla terminal/VPS
kullanılırsa GV paylaşılmaz → o durumda ya tek terminal zorunlu, ya da harici
koordinasyon (dosya/broker sorgusu) gerekir. FTMO tek-hesap tek-terminal kurulumu
varsayılıyor.

### Governor ile beklenen etki (simülasyon)
Korelasyonlu-gün senaryosunda toplam açık risk tavanı `MaxTotalOpenRiskPct`
günlük zeminin (%5) altında tutulursa, tek-gün korelasyonlu gap'in günlük breach'i
tetikleme olasılığı ~sıfıra iner (aç­ık risk zaten < zemin). Bu, mevcut *reaktif*
guard'ı *önleyici* bir katmanla tamamlar — parity'yi bozmaz (yalnızca risk azaltır,
`decide()` mantığına dokunmaz).

---

## Audit özet tablosu
| konu | durum | aksiyon (v3.14) |
|---|---|---|
| per-session magic izolasyonu | ✅ doğru (hedging) | — |
| GV state izolasyonu | ✅ doğru | — |
| **netting vs hedging kontrolü** | ❌ **eksik** | `ACCOUNT_MARGIN_MODE` oku; netting'de BTC multi-session reddet/tek-seans |
| trailing sahipliği (netting) | ⚠️ orphan-SL riski | netting guard'ı çözer |
| account-level açık-risk cap | ❌ **eksik** | Risk Governor (GV + SetOnCondition) |
| korelasyon-grubu risk cap | ❌ eksik | `MaxCorrelatedRiskPct` + gruplar |
| günlük yeni-risk cap | ❌ eksik | `MaxNewRiskPerFtmoDayPct` |
| reaktif loss guard | ✅ var | önleyici governor ile tamamla |
