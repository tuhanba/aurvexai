# Backtest bulguları — gerçek-tick, 2026-09-01 → 2026-10-02 (v3.14, NowUtc fix)

> **Kaynak:** operatörün 4 AYRI tek-sembol Strategy Tester raporu (gerçek tick).
> Ortak ayar: `TesterServerUtcOffsetHours=3`, `AvoidNews=false`, AccountSize=25000.
> **Bu sonuçlar canlı EA'ya uygulanmadı.** Bulgular + test setleri + operatör adımları.

## 0. Sonuçlar — AYRI sembol testleri (PORTFÖY DEĞİL)
| sembol | strateji | TrailStopR | filtre | net USD | işlem | not |
|---|---|---|---|---|---|---|
| XAUUSD | ORB | 0 | MinRangeMedMult=1 | **+291.14** | 9 | kazananlar seans-kapanışına kadar koşuyor |
| XAGUSD | ORB | 0 | kapalı | **+202.27** | **1** | tek işlem — neden aşağıda (#3) |
| GER40.cash | PDHL | **0.5** | — | **−303.81** | 14 | %100 stop/trailing çıkış |
| JP225.cash | PDHL | **0.5** | — | **−227.66** | 8 | %100 stop/trailing çıkış |

> ⚠️ **Bunları TOPLAMA.** Her test ayrı çalıştırıldı, her biri **tam $25k** ile; ortak
> hesap yok, ortak günlük-zemin yok, korelasyon yok. Gerçek hesap 4 sembolü **tek $25k**
> üzerinde paylaşır → birleşik davranış (korelasyonlu çekilmeler, ortak DD) farklıdır.
> Bu nedenle "net toplam" bir **portföy sonucu değildir**.

## 1. GER40 & JP225 çıkış kodu + küçük kazanç nedeni (kanıtla, varsayımsız)
**Her iki endekste de 14/14 ve 8/8 çıkışın TAMAMI `sl` (stop veya trailing stop).**
Hiçbir işlem 00:00 UTC seans-kapanışına (programatik flatten) ulaşmıyor.

GER40 (14 işlem): 8 kazanç ort **+49.43**, 6 kayıp ort **−116.55** → net −303.
JP225 (8 işlem): 5 kazanç ort **+48.22**, 3 kayıp ort **−156.26** → net −227.

**Küçük kazançların nedeni = trailing — ve bu varsayım değil, kanıt:**
1. **Çıkış fiyatı geometrisi:** kazananların `sl` fiyatı girişin **kâr yönünde ötesinde**.
   Örn. GER40 short giriş 25803.44 → çıkış `sl 25782.75` (girişin ALTINDA = short kârda):
   başlangıç stop'u (short için girişin ÜSTÜNDE) olamaz → **trailing stop** aşağı kaymış
   ve geri-çekilmede vurmuş. Aynı desen tüm küçük kazançlarda (+7.2, +24.9, +32.2, +20.6,
   +1.6, +8.2).
2. **Kayıplar başlangıç stop'u:** tam ~−1R (GER40 −116 ≈ RiskPct; JP225 −156 ≈ RiskPct).
   Trailing bunları etkilemiyor (fiyat hemen aleyhe gidip ATR×1.5 başlangıç stop'una çarpıyor).
3. **Altın kontrastı (en güçlü kanıt):** XAU da ORB ama **TrailStopR=0** → çıkışların
   çoğu **seans-kapanışı** (blank close) → kazananlar koşuyor → **+291**. Endekslerde 0.5R
   trail kazananları ~+48'de kesiyor.

**Özet:** trailing kazananları ~0.4R'de kapatıyor, kayıplar tam −1R → beklenti negatif.
Kayıplar trailing'den bağımsız; sorun kazananların kesilmesi.

## 2. Test setleri — endekslerde TrailStopR 0.5 vs 0 (diğer her şey aynı)
Hazır .set dosyaları: `mql5/sets/TEST_trail0_GER40_cash.set`, `TEST_trail0_JP225_cash.set`
(yalnız `TrailStopR=0` farkı; gerisi mevcut config ile aynı).

| run | sembol | TrailStopR | diğer |
|---|---|---|---|
| A1 (baseline) | GER40.cash | **0.5** | aynı dönem, offset=3, AvoidNews=false |
| B1 (test) | GER40.cash | **0** | — |
| A2 (baseline) | JP225.cash | **0.5** | — |
| B2 (test) | JP225.cash | **0** | — |

**Not:** TrailStopR=0 ile kazananlar 00:00 UTC seans-kapanışına kadar tutulacak (altın gibi).
Kayıplar değişmez (başlangıç stop'u). Hipotez: kazananlar daha büyük olabilir **veya** gece
geri verebilir → **karar teste bağlı**, peşinen "iyileşir" demiyorum. Karşılaştır: net,
işlem sayısı, kazanç/kayıp ort, max DD, en büyük tek kazanç/kayıp.

## 3. XAG neden yalnız 1 işlem?
- XAG filtresi **KAPALI** (MinRangeMedMult=0) → filtre sebebi DEĞİL. (Altın filtresi AÇIK,
  yine de 9 işlem; gümüş filtresiz 1 işlem — ters, yani throttle başka yerden.)
- **Deals raporu atlanan günlerin nedenini İÇERMEZ** — sadece gerçekleşen işlemleri gösterir.
  Nedeni kanıtlamak için **Strategy Tester → Journal (Günlük) / Experts** log'u gerekli.
- **Gerekli log satırları** (hangisi baskın onu söyler):
  - `ORB already broken before arming; skip day` → aralık 01:00 UTC'den önce kırılıyor (gümüşün
    küçük 1h aralığı gece sık kırılır) — **en olası**.
  - `spread guard: spread ... > 12.5% of stop` → gümüşün spread'i, küçük ORB stop mesafesinin
    %12.5'ini aşıyor olabilir — **ikinci olası**.
  - `insufficient free margin ... SKIP` → marj (düşük olasılık).
  - Hiç mesaj yok → 00:00 UTC barı/aralık oluşmadı.
- Gerçekleşen tek işlem +202 (seans-kapanışı çıkışı) → gümüşün edge'i sorunlu değil,
  **frekans** bir kapı tarafından kısılıyor. Log olmadan hangisi olduğunu **tahmin etmem**.

## 4. Uzun dönem doğrulama planı (yaz/kış saati doğru) — tuning ≠ validation
**DST sorunu:** FTMO sunucusu EET/EEST (kış UTC+2 / yaz UTC+3). `TesterServerUtcOffsetHours`
**sabit** bir offset; bir DST sınırını geçen tek backtest, bir tarafta 1 saat yanlış olur
(ORB penceresi kayar → bozulabilir). Canlı EA DST'yi otomatik halleder (ServerUtcOffset her
çağrıda TimeTradeServer−TimeGMT'den); yalnız **tester'ın sabit override'ı** DST geçişinde yanlış.
- DST sınırları: Mart son Pazar (→UTC+3), Ekim son Pazar (→UTC+2). 2026: ~29 Mar, ~25 Eki.
- **Çözüm: backtest'leri DST-rejimine göre BÖL.**
  - Yaz (EEST): `TesterServerUtcOffsetHours=3`, pencere ~Mar sonu–Eki sonu içinde.
  - Kış (EET): `TesterServerUtcOffsetHours=2`, pencere ~Eki sonu–Mar sonu içinde.
- **Tuning (in-sample) ≠ Validation (untouched):**
  - Tuning: ör. **2026-04-01 → 2026-07-31** (yaz, offset 3) — TrailStopR vb. seç.
  - Validation: ör. **2026-08-01 → 2026-10-20** (yaz, offset 3; farklı pencere) **+** bir kış
    penceresi **2025-11-01 → 2026-02-28** (offset 2) — rejimler-arası sağlamlık.
  - **Aynı pencerede parametre seçip başarı ilan etme.**
- (Opsiyonel kod geliştirmesi, şimdi DEĞİL: tester offset'ini DST tarihlerinde otomatik
  değiştiren bir tester-only fonksiyon eklenebilir — canlıya dokunmadan. İstenirse ayrı iş.)

## 5. Sınırlamalar (kayıt)
- **AvoidNews=false:** sonuçlar haber-kaçınması İÇERMEZ (canlı `AvoidNews=true`). Haber
  dönemlerindeki spread/gap işlemleri dahil → bu bir **sınırlama**, canlıyla birebir değil.
- **Ayrı sembol testleri = portföy DEĞİL.** Her biri tam $25k; toplanamaz (bkz. §0).
- Tek aylık pencere + tek DST rejimi → küçük örneklem; §4 planı ile genişletilmeli.

## Operatörün uygulayacağı kısa adımlar
1. **Trail A/B (4 run):** GER40 ve JP225 için, aynı dönem (2026-09-01→10-02), offset=3,
   AvoidNews=false:
   - baseline: mevcut `.set` (TrailStopR=0.5)
   - test: `TEST_trail0_<sym>.set` (TrailStopR=0)
   Her run'ın net/işlem/kazanç-kayıp-ort/max-DD'sini bana at.
2. **XAG:** aynı testi tekrar koş, **Journal (Günlük) sekmesini** kaydet/at — yukarıdaki
   skip satırlarından hangisi baskın?
3. Sonuçları **sembol-bazında** tut; toplama.
4. (Sonra) §4 tuning/validation pencerelerini DST'ye göre böl.
