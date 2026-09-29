# FTMO v3.15 SPEED LAB — hız araştırma planı (P1)

> **Durum: PLAN + metodoloji. Sonuç ÜRETİLMEDİ bu turda.** Dürüst sebep: canlı
> tick/fill serisi ve proxy veri cache'i bu çalışma alanında yok (gitignored;
> yeniden çekmek ağ + zaman ister), gerçek hesap fill'lerine erişimim yok. Aşağısı,
> P1 koşulduğunda uyulacak katı çerçeve. **Kanıt gelmeden hiçbir hız-politikası
> canlıya açılmaz** (iş emri P1 kapısı).

## Objective
Başarı = yalnız P&L değil: **(a) hedefe varış süresi** (takvim + işlem günü) ve
**(b) hedefe varmadan hesabı kaybetme olasılığı** birlikte. İki aşama ayrı:
Challenge +%10, sonra Verification +%5; her aşamada ≥4 işlem günü + kapalı-pozisyon
koşulu. Günlük sınır 00:00 CE(S)T bakiyesinden.

## Veri & metodoloji (zorunlu disiplin)
- **İki seri ayrı raporlanır:** (1) Yahoo-proxy türetilmiş (mevcut araştırma tabanı),
  (2) gerçek MT5 timestamp'li fill/tick (KAPI verisi). Proxy sonuç canlı expectancy
  sayılmaz.
- **Kronolojik TRAIN / VALIDATION / untouched TEST**; walk-forward; gün/hafta blok
  bootstrap. **Aynı dönemde parametre seçip başarı ilan etme.**
- Semboller **bağımsız IID trade gibi karıştırılmaz** — aynı-gün ortak şoklar ve OCO
  çift-fill korunur.
- Maliyetler: spread + komisyon + swap + **%0,7 FX conversion** (profit-ccy ≠ acct-ccy
  olan GER40/JP225 için sembol özelliklerinden doğrula) + slippage; **çifte sayma yok**.
  `OrderCalcProfit` tek başına tüm masraf modeli değildir.

## Karşılaştırılacak politikalar (P0 temeli = mevcut 1,3×/de-risk)
1. mevcut 1,3× + de-risk (baseline)
2. 1,0× referans
3. 1,3× + PhaseCompleteGuard (hedefe varınca bankla)
4. hedefe-mesafe + günlük-kalan-headroom'a bağlı, **account-wide sınırlı** risk policy
   (mevcut stop/hard-cap'i aşmaz, ≥4 gün kuralını ihlal etmez)

## Üretilecek tablo (asgari)
| Metrik | çıktı |
|---|---|
| Hız | median days-to-pass (Challenge + iki-aşama toplam); P(pass ≤ 20/30/45 işlem günü); takvim günü |
| Kayıp | P(fail) + neden ayrımı: günlük floor / toplam floor / hedeften geri dönüş / maliyet |
| Dağılım | P10/P50/P90 geçiş süresi, max DD, ort. günlük net kâr, spread/komisyon/FX payı |
| Dayanıklılık | untouched OOS, dönem/sembol kırılımı, blok-bootstrap CI, 2× spread/slippage + gap stresi |

## Seçim kuralı (Pareto)
Aday, baseline'a karşı **OOS'ta geçiş süresini azaltırken** başarısızlık olasılığını
**önceden yazılı bütçenin dışına** çıkarmamalı. `P(pass ≤ 30)` artışı **tek bir
runner/güne** bağımlıysa (remove-top-1 ile çöküyorsa) **reddedilir**. Belirsizlik
sayı + CI ile verilir; "hızlandı" iddiası yalnız ortalama kârla kurulmaz. Fark yoksa
**canlı policy değişmez.**

## Sıra (iş emri 3.2)
1. **Fırsat kaybı:** v3.11'de BTC-komisyon + GER40-Monday etkisini gerçek fill'de ayır;
   v3.13 4-sembol sinyal sıklığı, reddedilen sinyal nedenleri, OCO'nun kaçırdığı hareket,
   net R/trade. **KAPI-2 = ilk 25–30 yeni-config işlemi** (üretim mekanik hataları bunu beklemez).
2. **Exit optimizasyonu:** XAU/XAG ORB fat-tail'i bozmadan causal time-exit / seans-sonu
   varyantı / MFE koruması / hedefe-yakın account-exit; GER40/JP225 trailing 0,5R ayrı.
   **Aynı-bar geleceği kullanma** (look-ahead yasak); net (gross değil) + tail kaybı + days-to-pass.
3. **News A/B:** BLOCK / ALLOW / TAG_ONLY ayrı. ±2dk blackout ORB gününü tamamen
   kaçırıyor mu ölç. `AvoidNews=false` üretim default'u OLMAZ; net fayda OOS çıkarsa
   yalnız Evaluation için feature-flag + haber spread/gap stresi. Funded'a geçişte
   otomatik kural kontrolü.
4. **Bağımsız scalp/satellite (P3, en son):** ORB'yi küçük TF'de sıklaştırmak yeni alpha
   DEĞİL. Gerçek tick/bid-ask/komisyon/latency/slippage/%0,7 ile mean-reversion,
   intraday-trend-continuation, momentum ayrı sleeve. Başlangıç ARAŞTIRMA aralığı
   3–8 işlem/gün + düşük tek-işlem riski + ayrı günlük sleeve limiti (canlı ayar değil).
   Core ile aynı kayıp-günlerine yığılma + korelasyon zorunlu. Pozitif+sağlam OOS yoksa
   `SATELLITE_ENABLED=false`. FTMO sunucusuna aşırı trafik üretme.

## Çıktı dokümanı
Koşulunca: varsayımlar, veri provenance, iki-aşamalı first-passage tablosu, CI'ler,
adayın OOS + stres performansı, **GO/NO-GO**. Yeni scalp kârlı çıkmazsa **açıkça
"başarısız"** yaz.
