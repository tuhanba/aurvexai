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

## 13. v1.20 — TradingView uyumu, gün boyu işlem, trend filtresi

**Neden az işlem açılıyordu?** v1.00/v1.10'da EA sadece New York 09:30–11:30
arasında giriş yapıyordu (günde 2 saat). Günde en fazla 4 sinyal sınırı
vardı. Ayrıca **VWAP 09:30'da da sıfırlanıyordu**. Sizin TradingView
ayarınızda ise VWAP günde bir kez sıfırlanıyor ("Çapa Dönemi: Seans"). Bu
yüzden EA'nın VWAP'ı sizin grafiğinizdeki VWAP'tan farklıydı ve kesişimler
başka yerlerde oluşuyordu.

**Değişiklikler (yeni varsayılanlar):**

| Ayar | Önce | Şimdi |
|---|---|---|
| VWAP sıfırlama `InpVwapAnchor` | seans başı + 18:00 NY | **günde bir kez** (TradingView "Seans"), saat `InpVwapDailyResetNY` = 18:00 NY |
| İşlem saatleri `InpTradeAllDay` | sadece NY 09:30–11:30 | **gün boyu** (rollover, Cuma kapanışı, haber ve Oracle korumaları açık) |
| Günlük maksimum zarar `InpDailyLossLockUSD` | 250 $ | **200 $** |
| Günlük sinyal sınırı | 4 | **10** |
| HTF trend filtresi `InpUseTrend` | kapalı | **açık: H1 EMA50** (zaman dilimi seçilebilir; ikinci TF isteğe bağlı) |
| Ters sinyal `InpCloseOnOpposite` | reddediliyordu | açık pozisyonu kapatır (en az 150 s tutulmuşsa), ardından yeni giriş değerlendirilir |
| TP modu `InpTpMode` | sadece RR | RR **veya VWAP ± k·σ bandı** (TradingView band #1). Band hedefi en az 1R vermiyorsa işlem atlanır |

**Günlük hedef ve günlük zarar sınırı nasıl çalışıyor:**
- Gerçekleşmiş net kâr 200 $'a ulaşınca o **UTC günü** boyunca yeni giriş
  yapılmaz. UTC günü, Oracle'ın kendi günüyle aynıdır (00:00 UTC = New York
  19:00/20:00).
- Equity, gün başına göre 200 $ düşerse o gün için yeni giriş yapılmaz.
- Lot hesabı zaten **açık pozisyonların SL'ye kadar olan riskini** de bu 200
  $'ın içinde sayar. Örneğin iki 0,10 lot pozisyonun toplam riski 200 $'ı
  geçecekse ikinci pozisyonun lotu küçültülür. Böylece stoplar slippage'sız
  dolarsa gün içi zarar 200 $'ı geçmez. Slippage bu sınırı biraz aşabilir.

**TradingView ile kontrol:** TradingView'da XAUUSD M3 grafiğinde VWAP
çizgisinin hangi saatte sıfırdan başladığına bakın (genelde 17:00 veya 18:00
New York). Farklıysa `InpVwapDailyResetNY` değerini ona göre değiştirin.
Ayrıca TradingView'ın sembolü (OANDA, FX vb.) ile Upcomers'ın fiyat akışı ve
hacmi farklı olabilir. Tick volume farklı olduğu için VWAP değerleri birkaç
cent farklı çıkabilir.

## 14. v1.30 — İkinci backtest (v1.20) analizi ve değişiklikler

### Rapor: 01.01–22.10.2026, altın + gümüş, %96 gerçek tick

| | İşlem | Net $ | Toplam R | Not |
|---|---|---|---|---|
| Hepsi | 85 | −553 | **+1,5R** | kazanma oranı %52 |
| TP ile çıkış | 24 | +2.080 | +30,5R | |
| SL ile çıkış | 32 | −2.984 | −32,8R | |
| EMA çıkışı (AFTER_MFE) | 29 | +351 | +3,9R | %69 kazanç; v1.00'daki −33R'lik EMA çıkışı sorunu çözüldü |
| Altın | 77 | −401 | +0,3R | |
| Gümüş | 8 | −153 | +1,3R | SL başına ortalama **−157 $** (altında −87 $) |
| Pozisyon #2 (retest) | 24 | +17 | −0,6R | yaklaşık başabaş |

**1. R pozitif ama dolar negatif.** Sabit lotta zarar edilen dolar, stopun
genişliğine bağlıdır. Kaybeden işlemlerde stoplar daha genişti, bu yüzden 1R
başına daha fazla dolar kaybedildi (SL'de 1R ≈ 91 $, TP'de 1R ≈ 68 $). Ayrıca
kayıplardan sonra güvenlik tavanları lotları küçülttü, kazançlar küçük lotla
geldi. **Çözüm:** risk modu. Her işlemde 1R aynı dolar tutarı olur; böylece
+R doğrudan +$ olarak yansır.

**2. Mayıs–Ekim arasında hiç işlem yok.** 29 Nisan'dan sonra EA tamamen
durdu. Equity zirvesi yaklaşık 25.290, son değer 24.447. Tutucu (trailing)
Shield tabanı ≈ 24.040 olduğu için tabana mesafe ≈ 400 $ kaldı. Bu mesafe 300
$'lık güvenlik payı ve açık riskle birlikte yeni bir işleme yetmiyor. EA işlem
yapmadığı için equity de toparlanamıyor, yani EA kalıcı olarak kilitleniyor.
- **Canlı hesapta bu doğru davranış:** Shield gerçekten zirveyi takip
  ediyorsa hesap ihlale ~400 $ uzaktadır.
- Ancak backtest'in 6 ayını boşa harcıyor ve stratejinin gücünü ölçmeyi
  engelliyor.
- **Çözüm:** `InpShieldModel = STATIC` yalnızca araştırma (tester) için.
  Canlıda TRAILING kalmalı.
- Upcomers panelindeki gerçek taban EA'nın tahmininden **düşükse**,
  `InpManualShieldFloor` + `InpTrustManualFloor = true` ile gerçek değeri
  kullanabilirsiniz. Bunu sadece paneli aynı gün kontrol ettiyseniz yapın.

**3. Gümüş pahalı.** Kontrat 5.000 oz olduğu için sabit 0,06 lotta stop başına
157 $ kayıp oluyor. Risk modunda lot otomatik küçülür.

**4. Saat dağılımı** (sunucu saati): 00–05 +8,3R, 06–14 −10,3R, 15–17 +3,8R.
Örneklem küçük (85 işlem). **Bu dağılıma bakıp seans filtresi kurmak şu an
aşırı optimizasyon olur**; daha uzun testlerde de aynı tablo çıkarsa
değerlendiririz.

### v1.30 değişiklikleri

| Değişiklik | Neden |
|---|---|
| **Lot modu varsayılanı RISK, sinyal başına %0,5** (~125 $; iki pozisyona bölünür). `InpFixedLotGold/Silver` = 0,10 artık **maksimum lot** | 1R'nin dolar karşılığı sabit kalsın, +R → +$ |
| `InpShieldModel` (TRAILING / STATIC) ve `InpTrustManualFloor` | Backtest'te kilitlenmeyi önlemek / panel değerini kullanabilmek |
| **#2 sadece #1'den daha iyi fiyattan açılır** | Raporda #2, #1'den daha kötü fiyattan açılmıştı (ör. 4670 → 4671,82); bu gerçek bir retest değil |
| **FVG filtresi** (opsiyonel, kapalı): sinyal yönünde, son N mumda oluşmuş, doldurulmamış bir Fair Value Gap aranır | İsteğiniz; etkisi teste bağlı |
| **Order block stopu** (opsiyonel): SL, hareketten önceki son ters renkli mumun ötesine konur; yoksa swing kullanılır | İsteğiniz; daha dar ve mantıklı stop olabilir |

FVG, order block ve diğer "smart money" kavramlarının işe yaradığına dair
genel kabul görmüş bir kanıt yok. Bu yüzden ikisi de **varsayılan olarak
kapalı** ve sadece optimizasyonda açık/kapalı karşılaştırılıyor.

### Önerilen sonraki test

`OGP_optimize_exits.set` dosyası güncellendi. Ayarlar: sadece altın, STATIC
Shield, risk modu %0,5. Optimizasyonda şunlar karşılaştırılır: #2 modu, EMA
çıkış modu, SL çarpanı, swing/OB stop, TP modu ve RR, trend filtresi, FVG
filtresi. Forward 1/3.

## 15. v1.40 — Dinamik risk, ek giriş tipi, runner

### Üçüncü rapor (1–22 Ekim 2026, sadece altın, sabit 0,10 lot)
5 işlem, +217 $, profit factor 3,4. Bütün işlemler short (H1 trendi aşağıydı).
**5 işlem istatistik olarak hiçbir şey kanıtlamaz.** Ama "günde çok az
giriş" sorununu doğruluyor: 15 işlem gününde 5 giriş.

### Yenilikler

**1. Dinamik risk (risk sadece azaltılır, hiçbir zaman artırılmaz)**

Her sinyalin riski = taban risk × aşağıdaki çarpanlar:

| Çarpan | Kural | Varsayılan |
|---|---|---|
| **Sinyal kalitesi** | 0–6 puan: H1 trend yönünde, ikinci TF trend yönünde, VWAP eğimi sinyal yönünde, fiyat uzamamış (≤0,5 ATR), momentum mumu (gövde ≥0,5 ATR), FVG var. **A** ≥4 puan: ×1,0. **B** 2–3 puan: ×0,6. **C** 0–1 puan: atlanır. | açık |
| **Kayıp serisi** | Bugün art arda 2 kayıp → ×0,5 | açık |
| **Günü koru** | Bugünkü gerçekleşmiş kâr ≥100 $ → ×0,5 (200 $ hedefe giderken kârı geri vermemek için) | açık |
| **Taban yaklaşımı** | Equity bir firma tabanına yaklaştıkça risk 600 $'lık bir aralıkta kademeli olarak ×0,25'e iner. v1.20'deki gibi aniden kilitlenmez. | açık |

Bütün çarpanlar 1'den küçük ya da 1'e eşit. Spec'teki "kayıptan sonra lot
artırma yok" ve "equity yükselince agresifleşme yok" kuralları korunuyor.

**2. Trend devam girişleri (`InpUseContinuation`) — daha fazla günlük giriş**

Klasik kesişim günde birkaç kez olur. Yeni giriş tipi, **mevcut bir trend
ayağında** fiyat EMA'ya geri çekilip yeniden trend yönünde kapandığında
girer. Koşullar:
- EMA en az 5 mumdur VWAP'ın aynı tarafında,
- H1 trendi aynı yönde,
- mum EMA ± 0,3 ATR bölgesine dokunmuş ve trend yönünde kapanmış,
- son girişten bu yana en az 10 mum geçmiş,
- aynı ayakta en fazla 2 kez.

**3. Runner (`InpSecondRunner`) — kârı büyütmek için**

Pozisyon #2'nin hedefi 3R. +1R'ye ulaşınca stop girişe çekilir, sonra 1,5 ATR
mesafeyle iz sürer. #1 normal hedefinde (1,5R) kapanır, #2 trend devam
ederse büyük hareketi yakalar.

### Test önerisi

`OGP_optimize_exits.set` güncellendi. Ayarlar: sadece altın, STATIC Shield,
risk modu, Ocak–Ekim, forward 1/3. Optimizasyonda kalite skoru, C sinyalleri
(atla / ×0,3), devam girişleri, runner, EMA çıkış modu, SL çarpanı, swing/OB
stopu ve TP RR açık/kapalı ya da farklı değerlerle karşılaştırılır.

Önce **3 aylık normal bir test** yapın ve Bülten'deki `SIGNAL SUMMARY`
bloğunu gönderin. Sinyallerin hangi sebeple reddedildiği görülmeden "daha
fazla giriş" için hangi filtrenin gevşetileceğine karar verilemez.

## 16. v1.41 — Dördüncü rapor (v1.40, 1–22 Ekim, sabit 0,10 lot)

14 işlem (v1.30'da aynı dönemde 5), +170 $, profit factor 1,52.
- **Daha fazla giriş:** devam girişleri ve B sınıfı (×0,6 → 0,06 lot) sinyaller.
- **Runner işe yaradı:** 5 Ekim'de #2 runner'ın stopu iz sürerek 4138'e taşındı;
  pozisyon +139 $ ile kapandı.
- **Dinamik risk işe yaradı:** 8 Ekim'deki kayıp serisinde lot 0,06'dan 0,03'e
  ve 0,02'ye indi.
- **Zayıf nokta:** 8 Ekim'de aynı seviyede (SL ≈ 4129–4130) 2 saat içinde art arda
  **3 short açıldı ve hepsi stop oldu**. Piyasa yataydı ve EA aynı kırılmayan
  seviyeye tekrar tekrar girdi.

**Düzeltme (`InpLossCooldownBars` = 10):** Bir pozisyon zararla kapanınca o
sembolde **aynı yönde** 10 mum (30 dakika) yeni giriş yapılmaz. Ters yöndeki
girişler serbest kalır.

## 17. v1.42 — Beşinci rapor (v1.41, 1 Ağustos – 22 Ekim, 50 işlem)

**Ayarlar:** sabit 0,10 lot, risk %0,25, TRAILING Shield. Bunlar tester'da
kalmış eski değerler; v1.30'dan beri varsayılan risk modu.

**Sonuç:** −60 $, profit factor 0,94, toplam **+1,1R**.

| | İşlem | R |
|---|---|---|
| TP | 8 | +12,2 |
| SL | 16 | −16,2 |
| Runner / BE trail | 4 | +5,3 |
| EMA çıkışı | 22 | −0,2 |
| Pozisyon #2 (runner) | 9 | +1,9 |
| Ağustos / Eylül / Ekim | 16 / 21 / 13 | +1,2 / −3,6 / +3,5 |

**Gözlemler:**
- **12 haftada strateji yaklaşık 0R üretti.** Bu sonuçla stratejinin bir
  avantajı (edge) olduğu gösterilemez.
- **Grade A sinyaller (0,10 lot) B'lerden kötü:** A'da 13 işlem, %23 kazanma,
  −4,7R. B'de (0,06 lot) 10 işlem, %80 kazanma, +5,2R. Örneklem küçük, ama
  kalite skorunun bu dönemde öngörü gücü göstermediği açık.
- **Sabit lot hâlâ dolar/R asimetrisi yaratıyor:** kazançta 1R ≈ 47 $,
  kayıpta 1R ≈ 53 $.

**v1.42:** Optimizasyon için özel kriter (`OnTester`) eklendi. Profit factor'ın
1'in üstündeki kısmı × √işlem sayısı ÷ (1 + max DD%) olarak hesaplanır. 40'tan
az işlemli sonuçlar 0 puan alır, böylece birkaç şanslı işlemle iyi görünen
ayarlar elenir. Tester'da optimizasyon kriteri olarak **"Custom max"**
seçilmeli.

**Karar noktası:** Bundan sonraki küçük değişiklikleri 3 haftalık veya 3 aylık
tek testlerle değerlendirmek, geçmiş veriye uydurmaya (overfitting) yol açar.
Doğru adım, Ocak–Ekim için **forward 1/3'lük optimizasyonu** çalıştırmak:
- Forward döneminde de PF ≥ 1,2 ve ≥ 40 işlem veren bir ayar bölgesi çıkarsa
  o ayarlarla demo hesaba geçilir.
- Çıkmazsa EMA9×VWAP M3 kesişiminin altında anlamlı bir avantaj yok demektir.
  O durumda filtre eklemeye devam etmek yerine sinyalin kendisi değişmeli.

## 18. v1.50 — Fiyat verisiyle taktik araştırması ve "time-hold" planı

### Yöntem
Dukascopy XAUUSD M1 verisi (2 Ocak – 15 Mart 2026, 57 gün) ile bir Python
simülatörü kuruldu (`research/` klasörü). M3 mumları, EMA9, OHLC/4 seans VWAP'ı
(18:00 NY reset), ATR14 ve H1 EMA50 trendi EA ile aynı mantıkla hesaplandı.
Sonuçlar R cinsinden, işlem başına 0,35 $ maliyet düşülerek verildi.

- **Ayarlama dönemi (IS):** 2 Ocak – 14 Şubat.
- **Görülmemiş kontrol dönemi (OOS):** 15 Şubat – 15 Mart.
- **Doğrulama:** simülatördeki mevcut taktik (S0) işlem başına +0,04R çıktı.
  MT5 tester'daki gerçek sonuç da ≈ 0'dı (PF 1,03). İkisi tutarlı.

### Ana bulgu: kesişim sonrası fiyat hareketi (ATR cinsinden)

| | 5 mum | 10 mum | 20 mum | **40 mum** |
|---|---|---|---|---|
| H1 trendi yönündeki kesişimler | +0,12 | −0,31 | +0,01 | **+0,86** |
| Trende karşı / trendsiz kesişimler | −0,06 | −0,10 | −0,62 | **−0,69** |

Trend yönündeki kesişimden sonra fiyat **ilk 10 mumda (30 dk) geri çekiliyor**,
sonra **2 saat içinde trend yönünde devam ediyor**. Mevcut taktik 1,5R hedef ve
erken EMA çıkışıyla tam bu geri çekilmede çıkıyor ya da stop oluyordu.

### Taktik karşılaştırması (seçilenler)

| Taktik | IS | OOS |
|---|---|---|
| S0 mevcut (kesişim + trend, TP 1,5R, EMA çıkışı) | +0,6R (PF 1,05) | +1,9R (PF 1,21) |
| S1 kesişimin tersine işlem | +0,1R | +2,8R |
| S2 EMA'ya geri çekilmede giriş | +24R | **−15,5R** (dengesiz) |
| S3 VWAP bandından dönüş | +7R | **−21R** |
| **S5 kesişim + trend, stop 2 ATR, hedef yok, 40 mum sonra çık** | **+17,4R (PF 1,33, 78 işlem)** | **+5,1R (PF 1,19, 47 işlem)** |
| S5 ama 60 mum tut | +19,8R | −17,3R |
| S5 ama stop 1,5 ATR | +26,3R | −3,5R |

Hem IS'te hem OOS'ta pozitif kalan **tek** taktik S5 oldu: SL 2 ATR, TP yok,
40 mumluk zaman çıkışı. Komşu ayarlar (30–50 mum, 1,5–2,5 ATR) da
bakılmaya değer. 60 mum ve 1,5 ATR OOS'ta kötüleşiyor.

### v1.50: `InpTradePlan = TIME_HOLD` (varsayılan)
- **Giriş:** onaylı EMA9 × VWAP kesişimi + H1 trendi aynı yönde. Kovalama
  filtresi, kalite skoru, devam girişleri ve #2 pozisyon **yok**.
- **Stop:** 2 × ATR. **Hedef yok.**
- **Çıkış:** 40 M3 mumu (2 saat) sonra kapatılır. EMA çıkışı, BE ve trailing
  yok.
- **Pozisyon kuralı:** pozisyon açıkken ters sinyal yok sayılır. Zarar sonrası
  aynı yönde 10 mumluk bekleme sürer.
- **Korumalar aynı kalır:** Oracle kuralları, günlük zarar/hedef, dinamik risk
  azaltma, haber, rollover ve Cuma kapanışı.
- Eski plan için `InpTradePlan = TARGETS` seçin.

### Riskler ve dürüst değerlendirme
- **Veri sadece 10 hafta, tek bir piyasa dönemi.** OOS'taki +5,1R de 47
  işlemlik bir sonuç; şans payı yüksek.
- **Kazanma oranı düşük (~%31), kayıp serileri uzun:** simülasyonda en büyük
  düşüş 15R. İşlem başına %0,25 risk (≈62 $) ile bu ~940 $ eder; Oracle
  sınırlarına yakın. **Risk bu planda %0,15–0,25 arasında tutulmalı.**
- Beklenen kazanç ~0,18R/işlem, günde ~2 işlem. %0,25 riskle günde
  ortalama ~20–25 $ eder. 200 $ günlük hedef bu taktikle gerçekçi değil.
- **Doğrulama şart:** MT5 tester'da **16 Mart – 22 Ekim** dönemi araştırmada
  hiç kullanılmadı. Bu dönemde de pozitifse taktik ciddiye alınabilir.
