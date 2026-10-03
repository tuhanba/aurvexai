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

---

# EK — Trail A/B sonucu + XAG orders analizi (ikinci tur)

## A. Trail=0 iki endekste de DAHA KÖTÜ → trailing kalıyor
Operatör testi: GER40 ve JP225'te TrailStopR=0, 0.5'e göre **daha kötü.** Bu nedenle
**"trailing'i kaldır" önerisi KAPATILDI.** TrailStopR=0.5 endekslerde korunuyor.

**Mekanizma (0.5 verisinden + deterministik mantık — neden 0 kötü):**
- Giriş mantığı trailing'den bağımsız → 0.5 ve 0 run'larında **aynı girişler**.
- 0.5'te kazananlar: fiyat ≥0.5R lehe gidip trailing'i armlıyor, sonra geri-çekilmede
  trailing stop küçük kârı **bankalıyor**.
- 0'da aynı giriş: trailing yok → pozisyon ya 00:00 UTC seans-kapanışına kadar tutulur,
  **ya da** fiyat girişin altına/üstüne −1R'ye kadar dönerse **tam −1R kayıp** olur.
- **Flip eden işlemler (0.5 kazanç → 0 kayıp):** lehe hareketten (trailing'i armlayan ~0.5R)
  SONRA fiyatın girişi geçip −1R başlangıç stop'una kadar **tam geri dönmesi**. 0.5 kârı
  dönüşten önce kilitledi; 0 tüm dönüşü yedi. 0.5 verisindeki küçük-trailing-kazançları
  (+1.6, +7.2, +8.2, +20.6, +24.9, +32.2) birincil flip adayları (trail'i zar zor armlayıp
  geri çekilmişler).

> **Tam eşleştirme için Trail=0 raporunun deal'leri gerekli** (bende yalnız 0.5 var).
> Trail=0 GER40+JP225 raporunu atarsan, giriş-zamanına göre eşleştirip her flip işlemin
> 0.5-çıkış vs 0-çıkış fiyatını yan yana tablolarım.

## B. Sonraki TEK-DEĞİŞKENLİ deney (bulgulara göre) — TrailStopR sweep
Bulgu: trailing dönüşlere karşı koruyor (0.5>0). Soru: 0.5 optimal mi, yoksa **daha sıkı**
bir trail flip'leri daha erken yakalayıp daha az mı kaybettirir? (Daha gevşek → Trail=0'a
yaklaşır, ki daha kötü olduğunu gördük.) → Hipotez **daha sıkı trail** yönünü işaret ediyor.

**Tek değişken: TrailStopR ∈ {0.3, 0.5(baseline), 0.75}**, gerisi aynı (dönem, offset=3,
AvoidNews=false). Hazır .set: `TEST_trail03_*`, `TEST_trail075_*` (+ mevcut 0.5).
Karşılaştır: net, işlem sayısı, kazanç/kayıp ort, flip sayısı, max DD. **Tuning penceresinde
seç, ayrı pencerede doğrula** (§4). Trail tuning overfit riski taşır — tek ayı kanıt sayma.

## C. XAG tek-işlem nedeni — ORDERS tablosundan (log olmadan büyük ölçüde çözüldü)
XAG raporunun **emir (orders)** tablosu nedeni gösterdi:
1. **Çoğu gün (09-02…09-21 vb.) HİÇ emir yok** → EA o günler **armlamadan önce** çıktı
   → "ORB zaten arming'den önce kırıldı" (gümüşün küçük 00:00–01:00 aralığı 01:00 UTC'ye
   kadar kırılıyor) veya aralık oluşmadı. (Kesin ayrım için Journal log'u.)
2. **Armlayan günlerde (09-01, 09-22) ONLARCA OCO emri PLACE/CANCEL churn'ü, hiç fill yok.**
   AvoidNews=false (news bloğu yok), pozisyon yok, tradedToday yok → tek flap kaynağı
   **SpreadAllowed** (`if(!SpreadAllowed){DeletePendings;return;}`). Yani **spread guard
   (MaxSpreadToStopPct=12.5) gümüşün spread'ini, küçük ORB stop mesafesinin %12.5'ine karşı
   sürekli reddediyor** → emirler place-cancel churn'üne giriyor, fiyat emirler canlıyken
   kırmıyor → fill yok.
3. Yalnız **09-28** (gümüşte büyük düşüş) bir sell-stop doldu → tek işlem +202.

**Önemli çerçeve (aceleyle gevşetme):** Spread guard'ın gümüşü reddetmesi muhtemelen
**DOĞRU risk-kaçınması** — spread, küçük stop'a göre büyükse o işlem zaten maliyet-ölümlü
(KAPI-1'deki BTC gibi). Yani düşük frekans kısmen guard'ın **işini yapması**. `MaxSpreadToStopPct`'yi
gevşetmek maliyet-ölümlü gümüş işlemleri ekleyebilir — veri olmadan yapma.

**Kesinleştirme:** Journal log'u hâlâ (1) pre-break vs no-range ve (2) spread-guard
reddinin gün-sayısını verir. Export edip at: `ORB already broken before arming`,
`spread guard: spread ... > 12.5% of stop`, `insufficient free margin` satır sayıları.

## Güncel operatör adımları
1. **TrailStopR sweep (6 run):** GER40+JP225 × {0.3, 0.5, 0.75}. Netleri + flip sayılarını at.
2. **Trail=0 raporunu** (GER40+JP225) at → birebir 0.5-vs-0 flip tablosu çıkarayım.
3. **XAG Journal log'u** export et → pre-break vs spread-guard gün-sayısı.
4. Sonuçlar sembol-bazında; toplama.

---

# EK-2 — TrailStopR sweep sonuçları (0.3 / 0.5 / 0.75) + robustluk

## Sonuç tablosu (aynı dönem, aynı girişler)
| sembol | trail | net | win | avgW | avgL | maxW | remove-top-1 |
|---|---|---|---|---|---|---|---|
| GER40 | 0.3 | −247.20 | 8/14 | +56.5 | −116.6 | +157.5 | — |
| GER40 | **0.5** (mevcut) | **−303.81** | 8/14 | +49.4 | −116.6 | +133.6 | — |
| GER40 | 0.75 | −220.20 | 8/14 | +59.9 | −116.6 | +137.8 | — |
| JP225 | 0.3 | −248.50 | 5/8 | +44.1 | −156.3 | +105.6 | **−354.1** |
| JP225 | **0.5** (mevcut) | **−227.66** | 5/8 | +48.2 | −156.3 | +109.3 | **−337.0** |
| JP225 | 0.75 | **−89.73** | 4/8 | +133.7 | −156.1 | +339.4 | **−429.1** |

## Okuma (dürüst, overfit tuzağına düşmeden)
1. **Kaybedenler üç trail'de de BİREBİR AYNI** (−115..−168, tam −1R başlangıç stop'u).
   Trailing yalnız kazananın ne kadarını yakaladığını değiştiriyor; kaybı etkilemiyor.
   Yani kazanç/kayıp asimetrisi (avgL ≫ avgW) **trail ile çözülmüyor.**
2. **0.5 belirgin optimal DEĞİL** — GER40'ta 0.3 ve 0.75 ikisi de 0.5'i geçti; ama fark
   ~tek-işlem gürültüsü (~$80) ve **hepsi net-negatif.**
3. **JP225 0.75 (−89.7) cazip görünüyor AMA tamamen TEK işleme bağlı:** 2026-10-01 +339.4
   runner. **Remove-top-1 → 0.75 net −429.1 (üçünün EN KÖTÜSÜ; 0.5'in −337'sinden beter).**
   Klasik monster-bağımlılık / overfit. **0.75'i benimseme.**
4. **Gevşek trail = daha çok flip-to-loss:** 2026-09-24 işlemi 0.3→+25, 0.5→+1.6,
   **0.75→−155.6** (tam dönüş −1R). Önceki turda anlattığım flip mekanizması **veriyle teyit.**
5. **Tüm trail değerlerinde her iki endeks net-negatif** bu ayda. Trail ikinci-derece;
   birinci-derece sorun endeks PDHL kitabının bu ayda para kaybetmesi.

## KARAR
- **TrailStopR=0.5 kalsın; 0.3/0.75'e geçme.** JP225 0.75 tek-runner overfit (remove-top-1
  onu en kötü yapıyor); GER40 farkları tek-işlem gürültüsü. **Tek aylık, tek-DST, ayrı-sembol
  veriyle hiçbir trail değişikliği gerekçelenmiyor.** Canlıya dokunma.
- **Single-variable trail tuning TÜKENDİ** — daha fazla trail değeri denemek overfit üretir.

## Sonraki adım (bulgulara göre — artık trail değil, DOĞRULAMA)
Asıl soru: endeks PDHL'in **herhangi bir pozitif beklentisi var mı**, yoksa (scalp/BTC gibi)
yapısal negatif mi? Bunu tek ay söyleyemez. Bu yüzden sıradaki iş **parametre tweak değil,
çok-aylık OOS doğrulama** (§4 planı):
1. §4 tuning/validation pencerelerini DST'ye göre böl (yaz offset 3 / kış offset 2).
2. Her endeksi **birkaç ay** OOS koş; trail=0.5 sabit. Net-pozitif mi, remove-top-N'e
   dayanıklı mı, yıl/çeyrek tutarlı mı?
3. Endeks OOS'ta yapısal negatifse: trail/stop tweak kurtarmaz → endeks ağırlığını/varlığını
   sorgula (dürüst, KAPI-1 BTC gibi). Pozitifse: o zaman stop/trail ince-ayarı anlamlı.
