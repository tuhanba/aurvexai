# Oracle Guardian Pro — MT5 Expert Advisor (XAUUSD / XAGUSD)

> **Kâr garantisi yoktur.** Hiçbir sinyalin ya da filtre kombinasyonunun kazandırdığı
> gösterilmemiştir. Bu yazılım deneyseldir. **Önce demo hesapta** çalıştırın.

> **Derleme durumu: derlenmedi, backtest yapılmadı.** MetaEditor'u Wine altında
> çalıştırmayı denedim, ancak MetaEditor anti-debug kontrolü yüzünden açılmadı
> ("A debugger has been found running in your system"). Kodu MQL5 API'sine göre
> elle kontrol ettim. Ayrıca bütün dosyalarda parantez dengesini ve her
> `StringFormat` çağrısındaki biçim belirteci / argüman sayısını otomatik olarak
> denetledim. Yine de **ilk derlemeyi siz yapacaksınız**. Derleyici hata veya
> uyarı verirse metnini bana gönderin.

> **Şartname eksik:** Mesajınız 8. bölümde, "Brokerın minimum stop mesafesi ve
> geçerli fiyat ad…" cümlesinde kesildi. 8. bölümün geri kalanı ve sonraki
> bölümler (varsa dashboard, raporlama, test teslimatları vb.) bana ulaşmadı.
> Bu kısımlar için kendi varsayılanlarımı kullandım; hepsi aşağıda açıkça
> yazılı. Eksik bölümleri gönderirseniz ona göre güncellerim.

---

## 1. Dosyalar ve kurulum

```
MQL5/Experts/OracleGuardianPro/
├── OracleGuardianPro.mq5        ana EA: olay yöneticileri, giriş karar akışı, dashboard
└── Include/
    ├── OGP_Inputs.mqh           tüm ayarlar (input) ve enum'lar
    ├── OGP_Common.mqh           log, CSV günlüğü, yardımcılar
    ├── OGP_Time.mqh             sunucu saati ↔ UTC ↔ New York/Londra, DST
    ├── OGP_History.mqh          işlem geçmişi analizi, equity üst sınırı, döngü istatistikleri
    ├── OGP_Account.mqh          canlı hesap izleme + Oracle kural motoru
    ├── OGP_Vwap.mqh             seans VWAP'ı (OHLC/4)
    ├── OGP_Sessions.mqh         seanslar, rollover, hafta sonu, haber filtresi
    ├── OGP_Trade.mqh            risk motoru (lot hesabı) + emir gönderme
    ├── OGP_Strategy.mqh         sembol verisi, kesişim sinyali, filtreler, SL/TP
    ├── OGP_Positions.mqh        pozisyon yönetimi (acil kapanış, EMA çıkışı, BE, trailing)
    └── OGP_Dashboard.mqh        grafik üstü panel
```

1. MT5'te **File → Open Data Folder** menüsünü açın ve `MQL5/Experts/` klasörüne
   gidin. `OracleGuardianPro` klasörünü **içindeki `Include` alt klasörüyle
   birlikte** buraya kopyalayın.
2. MetaEditor'da (F4) `OracleGuardianPro.mq5` dosyasını açın ve **Compile**
   (F7) ile derleyin. Sonuç `0 errors` olmalı.
3. Navigator'da *Expert Advisors* üzerinde sağ tık → Refresh. EA'yı XAUUSD
   grafiğine sürükleyin (herhangi bir zaman diliminde). *Algo Trading* açık
   olmalı.
4. **İlk açılıştan önce zorunlu ayarlar:**
   - `InpCycleStart`: şu anki payout döngüsünün başlangıcı, **sunucu saatiyle**.
     Her payout'tan sonra güncellenmeli.
   - `InpInitialBalance` = 25000.
   - Broker saati: `InpServerUtcOffsetHours` / `InpServerDst`. Canlı hesapta
     otomatik algılanır; Strategy Tester'da bu iki değer elle doğru girilmelidir.
   - Upcomers panelinde Dynamic Risk Shield tabanı görünüyorsa
     `InpManualShieldFloor` alanına girin (önerilir, bkz. §3).
   - `InpMagic` değerini kendinize özgü bir sayıyla değiştirin. Upcomers,
     başkalarıyla aynı EA'yı aynı ayarlarla çalıştırmayı yasaklıyor.

## 2. Oracle kuralları: doğrulanan ve yorumlanan kısımlar

Resmî sayfalar 23.10.2026 itibarıyla okundu.

| Kural | Sayfada yazan | EA'nın kullandığı yorum (onayınızla) |
|---|---|---|
| Dynamic Risk Shield %5 | "Taban başlangıç bakiyesinin %5 altında başlar ve equity yeni zirve yaptıkça yukarı izler." Formül verilmemiş. | **Taban = max(başlangıç × 0,95 ; en yüksek equity − başlangıç × %5 ; manuel taban)**. Bu, zirvenin %5'ini almaktan daha sıkı bir yorum. |
| Daily Drawdown %4 | Gün 00:00–23:59 UTC. Referansın balance mı equity mi olduğu yazmıyor. | **Referans = 00:00 UTC'deki equity.** Limit = %4 × min(başlangıç, gün başı equity). |
| Single Trade Loss %2 | "Hesap büyüklüğünün %2'si", slippage dahil. İhlal hesabı kapatır. | Limit = %2 × min(başlangıç, güncel equity). EA'nın iç sınırı bunun yarısı veya daha azı (varsayılan 250 USD). |
| Best Day %20 | En iyi gün, toplam kârın %20'sini aşamaz. Soft rule: aşılırsa payout ertelenir. | Dashboard'da oran gösterilir. Günlük 200 USD hedefe ulaşınca yeni giriş durur; bu, en iyi günü sınırlamaya da yardım eder. |
| Geçerli gün | Gerçekleşmiş kâr ≥ başlangıç × %0,5 (125 USD). Eşik sabit. | Her UTC günü için gerçekleşmiş **net** (komisyon ve swap dahil) hesaplanır. |
| Payout | ≥ %1 net kâr (250 USD) + 5 geçerli gün + Best Day kuralı + bütün pozisyonlar kapalı. Eşik payout sonrası sıfırlanır. | Dashboard'da "Payout" satırı. Döngü başlangıcını siz `InpCycleStart` ile girersiniz. |
| Tick scalping | **2 dakikadan kısa tutulan işlemler yasak.** | EA kendi çıkışlarını (EMA çıkışı, BE, trailing) en az `InpMinHoldSeconds` = 150 s sonra yapar. 120 s altına ayarlanamaz. |
| Martingale / grid / straddle | Yasak. | Hiçbiri yok. EA bekleyen emir kullanmadığı için haber straddle'ı yapısal olarak imkânsız. |
| EA kullanımı | Serbest. Başkalarıyla aynı EA'yı aynı ayarlarla çalıştırmak yasak. | Magic number ve ayarları kendinize göre değiştirin. |

**Sayfalarda bulunmayan ve bu yüzden kesin bilgi gibi sunulmayan noktalar:**
- Shield formülünün tam hali ve tabanın bir noktada sabitlenip sabitlenmediği.
- Payout sonrasında Shield tabanının nasıl sıfırlandığı. Payout'tan sonra
  Upcomers panelindeki tabanı `InpManualShieldFloor` alanına girmeniz önerilir.
- Upcomers'ın equity'yi hangi fiyat akışıyla ölçtüğü. EA, broker akışını
  kullanır; ikisi arasında fark olabilir.
- Ayrı "Prohibited trading strategies" makalesi okunmadı. Linki gönderirseniz
  kontrol ederim.

## 3. Canlı hesap izleme: MT5'ten okunanlar ve Upcomers'ta kalanlar

**MT5'ten doğrudan ve kesin okunanlar:** balance, equity, floating P/L, margin,
free margin, margin level, para birimi, kaldıraç, açık pozisyonlar, işlem
geçmişi (deal'ler, komisyon, swap) ve spread.

**MT5'ten okunamayanlar** (Upcomers sunucusunda tutulur): Shield tabanı, bu
tabanın izlediği en yüksek equity, Upcomers'ın 00:00 UTC'de kaydettiği equity
ve payout döngüsünün sıfırlanması.

EA bu değerler için kendi referanslarını tutar ve **her birinin kaynağını
dashboard'da gösterir**:

| Etiket | Anlamı | Yeni giriş |
|---|---|---|
| `OBSERVED` | EA değeri canlı olarak gördü. | serbest |
| `RECONSTRUCTED(conservative)` | EA o anda çalışmıyordu. Değer, işlem geçmişi ve M1 mumlarının en uç fiyatlarından hesaplanan **üst sınır** ile tahmin edildi (aşağıya bakın). | serbest |
| `MANUAL` | Upcomers panelinden siz girdiniz. | serbest |
| `UNKNOWN` | Değer belirlenemedi. | **engelli** + uyarı |

**Tutucu yeniden hesaplama nasıl yapılıyor:** EA'nın equity'yi görmediği her
dönem için (ilk kurulum, yeniden başlatma, bağlantı kopması, kaçırılan UTC gece
yarısı) EA, işlem geçmişinden bakiye eğrisini çıkarır. O dönemde açık olan her
pozisyon için M1 mumlarındaki en uç fiyatla elde edilebilecek **en yüksek**
floating kârı ekler. Böylece o dönemde equity'nin gerçekten ulaşabileceği
değerin **üst sınırı** bulunur. Bu üst sınır gerçek zirveden yüksek çıkabilir;
bu durumda taban gereğinden sıkı olur ve EA daha temkinli davranır. Hiçbir
zaman gevşemez. M1 verisi bulunamazsa değer `UNKNOWN` olur ve yeni girişler
durur.

Durum dosyası `MQL5/Files/OGP_state_<login>.txt` konumunda tutulur: zirve,
gün başı, son görülme zamanı. EA yeniden başladığında arada geçen süre için
yukarıdaki üst sınır hesabını yapar.

**Equity bazlı hesap:** lot büyüklüğü her işlemde **güncel equity** üzerinden
hesaplanır. Balance 25.000, equity 24.800 ise risk 24.800 × %0,25 olur. Equity
yükselse de risk yüzdesi sabit kalır; kayıptan sonra lot artırma yoktur.

## 4. Risk motoru (her işlemden önce)

1. Equity ve bakiye okunur; Oracle referansları güncellenir.
2. Temel risk = **equity × `InpRiskPct`** (varsayılan %0,25 ≈ 62,5 USD).
3. Diğer metalde **aynı yönde** EA pozisyonu varsa risk × `InpCorrelatedRiskFactor`
   (0,5). İsteğe bağlı olarak zıt yönler tamamen engellenebilir.
4. Bu risk aşağıdaki tavanların en küçüğüyle sınırlanır:
   - birleşik planlı risk tavanı: başlangıç × %0,5 (125 USD) − açık EA risk;
   - tek işlem tavanı: min(`InpMaxSingleTradeLossUSD` = 250, Oracle tek işlem
     limitinin yarısı);
   - iç günlük kilit boşluğu: 250 − (gün başı − equity) − bütün pozisyonların
     SL'ye kadar kalan riski;
   - firma günlük taban boşluğu: equity − günlük taban − 300 güvenlik payı − açık risk;
   - Shield boşluğu: equity − Shield tabanı − 300 güvenlik payı − açık risk.
5. **Lot başına zarar** = (giriş → SL zararı) + (SL'de slippage payı) + lot başı
   komisyon. Zarar `OrderCalcProfit` ile hesaplanır, böylece tick size, tick
   value ve contract size otomatik olarak dikkate alınır. Spread de işin
   içindedir: alışta giriş ask, çıkış bid fiyatından olur.
6. Lot = izin verilen risk / lot başına zarar. Sonuç brokerın hacim adımına
   **aşağı** yuvarlanır.
7. **Minimum lot bile izin verilen riski aşıyorsa işlem iptal edilir.** EA lotu
   minimuma yükseltmez.
8. Margin kontrolü yapılır: free margin'in %10'u yedekte tutulur.
9. Emir mutlaka bir SL ile gider. Dolumdan sonra pozisyonda SL yoksa EA hemen
   SL koymaya çalışır; koyamazsa pozisyonu kapatır.

**Kalıcı korumalar:**
- Equity bir tabana `InpFloorSafetyUSD` (300) kadar yaklaşırsa yeni girişler durur.
- `InpEmergencyBufferUSD` (120) kadar yaklaşırsa **bütün EA pozisyonları kapatılır**.
- Tek bir pozisyonun floating zararı `InpPositionEmergencyUSD` (350; Oracle
  limiti 500) değerine ulaşırsa o pozisyon kapatılır.
- Günlük iç kilit: equity gün başına göre 250 USD düşerse o UTC günü boyunca
  yeni giriş yapılmaz.
- Hesapta SL'siz herhangi bir pozisyon varsa (manuel işlemler dahil) yeni
  girişler durur.
- Martingale, grid ve zarar sonrası lot artırma yoktur.

**Slippage uyarısı:** SL bir piyasa emridir. Hızlı piyasada veya fiyat
boşluğunda gerçek kayıp, planlanandan fazla olabilir. Ayrılan slippage payı
(altın 0,25, gümüş 0,015 fiyat birimi) bunu yalnızca kısmen karşılar. Planlanan
risk (≈62 USD) ile Oracle tek işlem limiti (500 USD) arasında geniş bir pay
bırakılmasının sebebi budur.

## 5. Strateji

**VWAP:** (O+H+L+C)/4 × hacim / hacim; M3 mumları üzerinden, seans
başlangıcından itibaren. MT5'te yerleşik bir VWAP göstergesi olmadığı için
hesaplama `OGP_Vwap.mqh` içinde yapılır ve kaynak kodda açıklanmıştır.
- Auto modunda, kontrol edilen her mumda real volume varsa real volume
  kullanılır; yoksa tick volume. Altın ve gümüş CFD'lerinde sonuç genelde tick
  volume'dur. Kullanılan tür dashboard'da gösterilir.
- **Sıfırlama:** etkin seansların başlangıcında ve isteğe bağlı olarak metallerin
  günlük açılışında (18:00 New York). Sıfırlamadan sonraki ilk
  `InpMinBarsAfterReset` (2) mumdaki kesişimler dikkate alınmaz; bu mumlarda
  VWAP tek bir mumdan oluşur ve gürültülüdür.

**EMA:** `iMA(M3, 9, EMA, Close)`, standart hesaplama. Grafiğin zaman dilimi
ne olursa olsun bütün hesaplar M3 üzerinden yapılır.

**Giriş modları:**
- **Confirmed (varsayılan):** kesişim, kapanmış mumlarda bar[2] → bar[1]
  arasında aranır. Emir yeni mumun ilk tick'inde gönderilir. Kapanmamış mum
  verisi kullanılmaz.
- **Live:** canlı EMA ile canlı VWAP'ın tick'ten tick'e işaret değiştirmesi.
  Bir mumda en fazla bir deneme yapılır. Bağlantı kopması, 180 saniyeden uzun
  tick boşluğu veya VWAP sıfırlaması sonrasında EA yeni bir kesişim bekler.
  **Bu modda sinyal mum kapanmadan geri dönebilir (repaint).**

**Yeniden giriş kuralı:** aynı yönde ikinci giriş için önce ters yönde bir
kesişim gerekir (`InpRequireNewSignal`). Aynı fiyat hareketine tekrar tekrar
girilmez.

**Filtreler:** her biri ayrı bir modül ve ayrı bir input'tur. Ret sebepleri
Journal'a yazılır.

| Filtre | Varsayılan | Neden |
|---|---|---|
| ATR min/max, spike mumu, spread, spread/ATR | **AÇIK** | güvenlik |
| Kovalama (fiyat VWAP'tan 1 ATR'den uzak) | **AÇIK** | şartnamede "kovalamayı engelle" isteniyor |
| M15 EMA50 trend | kapalı | test edilmedi |
| H1 EMA50 trend | kapalı | test edilmedi |
| Breakout / momentum (+ retest seçeneği) | kapalı | test edilmedi |
| Pullback ile yeniden giriş | kapalı | test edilmedi |

Şartnamede "performansı gerçekten iyileştirdiği gösterilmeyen filtreleri
varsayılan olarak açma" deniyor. Hiçbir filtre henüz test edilmediği için
yalnızca güvenlik filtreleri açık. Test planı §9'da.

**Stop-loss:** max(1,5 × ATR ; son 10 mumun swing low/high'ı + tampon).
Brokerın minimum stop mesafesi (stops/freeze level) + spread uygulanır.
**SL 3 × ATR'den genişse işlem atlanır.** TP = 1,5R (ayarlanabilir, 0 = TP yok).

## 6. Pozisyon yönetimi

Öncelik sırası:
1. **Hesap acil durumu:** equity bir tabana yakınsa bütün EA pozisyonları kapanır.
2. **Pozisyon acil durumu:** floating zarar 350 USD'ye ulaşırsa pozisyon kapanır.
3. **Cuma kapanışı:** 16:15 New York'ta EA pozisyonları kapanır. Metal
   piyasası hafta sonu kapalı ve payout için de bütün pozisyonların kapalı
   olması gerekiyor.
4. **SL'siz pozisyon:** EA hemen SL koyar; koyamazsa pozisyonu kapatır.
5. **EMA çıkışı:** M3 mum EMA'nın ters tarafında kapanırsa pozisyon kapanır.
   Pozisyon **en az 150 saniye** tutulmuş olmalıdır; daha erken gelen sinyal
   ertelenir.
6. Break-even ve ATR trailing isteğe bağlıdır (varsayılan kapalı). Pozisyon
   150 saniye tutulmadan çalışmazlar; değişiklikler en az 30 saniye arayla
   yapılır, böylece aşırı emir güncellemesi olmaz.

1–4 numaralı adımlar hesabı korumak için minimum tutma süresini beklemez.
**Önemli sınırlama:** brokerdaki SL veya TP 2 dakikadan önce tetiklenirse
işlem 2 dakikadan kısa sürmüş olur. Bunu kesin olarak engellemenin tek yolu
SL'yi kaldırmak olurdu, ki bu daha büyük bir risk. TP en az 1,5R ve SL en az
1,5 ATR olduğu için bu nadirdir, ama imkânsız değildir. Upcomers'a sorup
netleştirmenizi öneririm.

## 7. Zaman ve haber

- **Seans filtresi** açık; varsayılan seans New York 09:30–11:30. Londra ve
  özel seans isteğe bağlı. `InpTradeAllDay` ile seans filtresi devre dışı
  bırakılabilir.
- **Rollover bloğu:** 16:30–18:30 New York (spread genişler). **Cuma:**
  14:00'ten sonra yeni giriş yok, 16:15'te kapanış.
- **Saat dönüşümü:** sunucu → UTC → New York/Londra. ABD ve AB DST kuralları
  kodda tanımlı. Canlı hesapta broker farkı
  `TimeTradeServer() − TimeGMT()` ile otomatik bulunur; bu yüzden PC saati
  doğru olmalı. Tester'da elle girilen kural kullanılır.
- **Haber filtresi:** MQL5 ekonomik takvimi kullanılır. Yüksek önemdeki USD
  olaylarının 15 dakika öncesi ve sonrasında **yalnızca yeni giriş**
  engellenir.
  - **Güvenilirlik:** takvim **Strategy Tester'da yoktur**, canlıda da eksik
    veya gecikmeli olabilir. Takvim okunamazsa dashboard'da uyarı çıkar;
    varsayılan davranış girişlere izin vermektir (`InpNewsFail` ile
    engellemeye çevrilebilir).
  - Oracle haber sırasında işlem açmayı yasaklamıyor; bu filtre gönüllü bir
    korumadır. Yasaklı olan straddle/bracket emirlerdir ve EA bunları
    yapamaz.

## 8. Dashboard ve loglar

Dashboard'da şunlar gösterilir: hesap (balance, equity, floating, margin),
Oracle referansları ve **kaynak etiketleri**, tabanlara olan mesafe, günlük
kilit, bugünkü gerçekleşmiş kâr/hedef, işlem sayısı, döngü net kârı, geçerli
günler, best day oranı, payout durumu, açık planlı risk, her sembol için
spread/ATR/EMA/VWAP/hacim türü/trend, son sinyal ve karar, haber durumu.

Journal'daki her satır `[OGP]` ile başlar. Aynı kayıtlar ayrıca
`MQL5/Files/OGP_journal_<login>.csv` dosyasına yazılır. Kategoriler: SIGNAL,
REJECT (sebebiyle), RISK (lot hesabının bütün tavanlarıyla), ORDER, MODIFY,
CLOSE, DEAL, ORACLE, SESSION, NEWS, DATA, SYSTEM.

## 9. Test planı

**A. Derleme ve demo**
1. 0 hata ile derlenmeli.
2. Demo hesapta Journal'da şunlar görünmeli: `ready:` satırları, sunucu/UTC/NY
   saatleri ve Shield ile gün başı değerlerinin **kaynak etiketleri**.
3. `InpCycleStart` alanına geçmiş bir tarih girin: `RECONSTRUCTED` görünmeli.
   Upcomers panelindeki değerle karşılaştırın.
4. `InpManualShieldFloor` alanına equity'nin hemen altında bir değer girin:
   "within safety" sebebiyle girişler engellenmeli.

**B. Strategy Tester** (Every tick based on real ticks, M3, bakiye 25.000)
- `InpServerUtcOffsetHours`/`InpServerDst` değerlerini brokerınıza göre ayarlayın.
- Haber filtresi tester'da çalışmaz (dashboard ve log bunu belirtir).
- İlk test: sadece altın, Confirmed mod, filtre seti varsayılan. Kontrol
  edilecekler: her işlemde SL var mı, planlanan risk ≈ equity'nin %0,25'i mi,
  günlük işlem sayısı en fazla 4 mü, 150 saniyeden önce EA çıkışı yapılmış mı
  (yapılmamalı).

**C. Filtre karşılaştırma matrisi** (her metal için ayrı, en az 6–12 ay,
gerçek tick verisi, komisyon dahil):

| # | Ayar |
|---|---|
| 0 | Temel (varsayılan) |
| 1 | + M15 trend |
| 2 | + H1 trend |
| 3 | + Breakout |
| 4 | + Breakout + retest |
| 5 | + Pullback modu |
| 6 | Live mod (temel ayarlarla) |
| 7 | TP 2R / TP yok + EMA çıkışı |

Her satır için şunları kaydedin: işlem sayısı, net kâr, profit factor, en
büyük gün içi equity düşüşü, en kötü işlem, en iyi gün / toplam oranı,
geçerli gün sayısı. **Bir filtreyi ancak verinin farklı dönemlerinde de
(walk-forward) iyileşme gösteriyorsa** açık hale getirin. Aşırı optimizasyondan
kaçınmak için parametre taraması dar tutulmalı.

**D. Dayanıklılık (demo):** bağlantıyı 3 dakikadan uzun süre kesin; EA'yı açık
pozisyonla yeniden başlatın; manuel olarak SL'siz bir pozisyon açın (girişler
engellenmeli); Cuma kapanışını gözlemleyin.

## 10. Bilinen sınırlamalar ve riskler

- **Derlenmedi, test edilmedi** (bkz. en üst).
- Shield formülü resmî olarak yayımlanmadığı için yorumlandı (tutucu yorum).
  Payout sonrası davranış bilinmiyor.
- Upcomers equity'yi kendi fiyat akışıyla ölçebilir; broker akışıyla küçük
  farklar olabilir. 300 USD'lik güvenlik payının sebebi budur.
- Yeniden hesaplanan üst sınırlar çok tutucu olabilir; bu durumda EA, Upcomers
  limitinden daha erken durur.
- Netting hesapta pozisyon tersine dönerse (INOUT) geçmiş analizi yaklaşık
  sonuç verir.
- SL'de slippage ve hafta içi fiyat boşlukları planlanan riski aşabilir.
- 2 dakikadan önce broker SL/TP'sinin tetiklenmesi (bkz. §6).
- Haber takvimi tester'da yok; canlıda güvenilirliği MetaQuotes'a bağlı.
- DST kuralları kodda sabit; broker farklı bir tarihte geçiş yaparsa saatler
  bir saat kayabilir.
- Altın ve gümüş birlikte çalıştırıldığında grafikte olmayan sembol 1 saniyelik
  zamanlayıcıyla işlenir.
- Günlük 200 USD hedef bir **üst durma noktasıdır**, garanti değildir. %0,25
  riskle bu hedefe ulaşmak için yaklaşık 3R net gerekir; çoğu gün ulaşılamaz.

## 11. Benim yaptığım varsayımlar (eksik şartname bölümleri)

- Varsayılan TP 1,5R (şartnamede "1:1,5 veya 1:2" deniyor).
- Minimum tutma süresi 150 saniye (Oracle tick-scalping kuralı 2 dakika + pay).
- Cuma kapanışı varsayılan olarak açık.
- Rollover bloğu 16:30–18:30 New York.
- Komisyon varsayımı lot başına 7 USD (gidiş-dönüş). Brokerınıza göre ayarlayın.
- Fiyat birimiyle verilen ATR, spread ve slippage eşikleri tahmindir. 2 veya 3
  basamaklı altın fiyatlamasından etkilenmezler, ama piyasa koşullarına göre
  ayarlanmaları gerekir.

## 12. v1.10 — İlk backtest analizi ve değişiklikler

### Rapor (01.01–22.10.2026, XAUUSD + XAGUSD, %96 gerçek tick, v1.00 varsayılanları)

| Çıkış türü | İşlem | Net | Ortalama R | Ortanca süre |
|---|---|---|---|---|
| TP | 21 | +1.382 USD | +1,51R | 17 dk |
| SL | 5 | −275 USD | −1,02R | 5 dk |
| **EMA çıkışı** | **167** | **−1.695 USD** | **−0,20R** | **9 dk** |
| Toplam | 193 | −588 USD | toplam −6,4R | |

Bu tablo şunları gösteriyor:
- Kaybın tamamı EMA çıkışından geliyor. İşlemlerin %87'si, ortalama 9
  dakika sonra ve çoğu −0,6R ile −0,1R arasında EMA çıkışıyla kapanmış.
- TP'ye ulaşan işlemler +1,5R kazandırmış. SL'ye çok az işlem ulaşmış (5).
- Gümüş (44 işlem, −5,5R) altından (149 işlem, −0,9R) daha kötü.
- Lotlar küçük kalmış: ortalama 0,05. Sebebi, %0,25 risk ile ortalama 11 USD'lik
  altın stopunun bir araya gelmesi.
- Sunucu saatiyle 17:00 dilimi (New York 10:00) en kötü saat: −4,4R.
- Bu rapor bir SL/TP kombinasyonunun daha iyi olacağını **kanıtlamaz**. EMA
  çıkışıyla erken kapanan işlemlerin, çıkış olmasaydı SL'ye mi TP'ye mi
  gideceği rapordan bilinemez. Bunu sadece yeni testler gösterir.

### Değişiklikler

1. **Sabit lot modu** (`InpLotMode = FIXED`, varsayılan): her pozisyon için
   0,10 lot (altın ve gümüş ayrı ayarlanır). **Lot hiçbir zaman artırılmaz.**
   Bir güvenlik tavanı (firma kuralları, günlük kilit, birleşik risk) 0,10
   lotu kaldırmıyorsa EA lotu küçültür ve bunu loga yazar. Eski davranış için
   `InpLotMode = RISK` seçin; bu modda risk sinyal başına hesaplanır ve iki
   pozisyona bölünür.
2. **Sinyal başına iki pozisyon** (`InpSecondEntry`):
   - `ON_RETEST` (varsayılan): #1 sinyalde açılır. #2, en fazla 10 mum içinde
     fiyat EMA/VWAP bölgesine geri gelip (±0,25 ATR) bir M3 mumu sinyal
     yönünde kapanırsa açılır. **İki pozisyonun SL'si ve hedefi aynıdır**;
     hedefe gelince ikisi birlikte kapanır. #1 kapanırsa, EMA VWAP'ın ters
     tarafına geçerse veya süre dolarsa #2 iptal edilir.
   - `AT_SIGNAL`: iki pozisyon da sinyalde açılır. #1 1R'de, #2 son hedefte
     kapanır. #1 hedefe ulaşınca #2'nin stopu girişe (break-even) çekilir.
   - `OFF`: eski tek pozisyon davranışı.
   - Günlük işlem sayısı **sinyal** olarak sayılır; #2 ayrı bir işlem
     sayılmaz.
3. **EMA çıkışı modu** (`InpEmaExitMode`):
   - `AFTER_MFE` (yeni varsayılan): EMA çıkışı ancak işlem bir noktada
     +0,5R kâra ulaştıktan sonra devreye girer. Daha önce stop ve hedef
     belirleyicidir.
   - `ALWAYS`: eski davranış.
   - `OFF`: yalnızca SL/TP/BE/trailing ve güvenlik kapanışları.
   - **Bu varsayılan bir hipotezdir.** Rapor, eski kuralın zararlı olduğunu
     gösteriyor; yeni kuralın daha iyi olduğunu henüz göstermiyor.
4. `InpMaxTotalRiskPct` 0,5'ten **1,0**'a çıktı. Bu yapılmasaydı 2 × 0,10 lot
   altın pozisyonu açılamazdı.

### Risk hesabı (0,10 lot altın, kontrat 100 oz)

- 1 USD'lik fiyat hareketi pozisyon başına **10 USD** eder. Ortalama 11
  USD'lik stopla bir pozisyonun riski ≈ **112 USD**; iki pozisyon ≈ **225 USD**
  (hesabın %0,9'u). Bu, v1.00'daki ≈ 50 USD'nin yaklaşık 4,5 katı.
- Günlük iç kilit 250 USD olduğu için, iki pozisyonu birden stop olan bir
  sinyal o günün işlemlerini fiilen bitirir. Bu bilinçli bir koruma. 250
  USD'yi yükseltirseniz firma günlük limitine (1.000 USD) daha hızlı
  yaklaşırsınız.
- **Gümüşte 0,10 lot çok daha riskli:** kontrat 5.000 oz, 1 USD hareket 500
  USD eder. 0,38 USD'lik ortalama stopta pozisyon başına ≈ 190 USD risk
  vardır. Tavanlar lotu otomatik küçültür, ama önerim gümüşü önce kapalı
  tutmak (`InpSymbols = Gold only`) ya da gümüş lotunu 0,02 yapmak.

### SL/TP optimizasyonu: nasıl yapılır

`OGP_optimize_exits.set` dosyası hazır. Strategy Tester'da:
1. *Girdiler* sekmesinde sağ tıklayın → **Yükle** → bu dosyayı seçin.
2. Optimizasyon: **"Hızlı genetik algoritma"**. Modelleme: gerçek tick'ler.
   **İleri (forward): 1/3**. Bu son seçenek önemli: optimizasyonun bulduğu
   en iyi ayarların, görülmemiş son 1/3'lük veride de çalışıp çalışmadığını
   gösterir.
3. Taranan parametreler: EMA çıkış modu (3), SL ATR çarpanı (1,0–2,5), yapısal
   SL (açık/kapalı), TP RR (1,0–3,0), ikinci pozisyon modu (3). Toplam yaklaşık
   1.080 kombinasyon; genetik algoritma bunların bir kısmını dener.
4. **Sadece en iyi sonucu seçmeyin.** Şu üç koşulu birlikte sağlayan ve
   komşu ayarları da benzer sonuç veren bir bölgeyi seçin:
   - forward dönemde profit factor > 1,2,
   - en az 100 işlem,
   - maksimum equity düşüşü < %4.
   Tek başına parlayan bir sonuç büyük ihtimalle aşırı optimizasyondur.
