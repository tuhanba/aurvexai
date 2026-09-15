# FTMO Funded Growth Mode — araştırma (Step 2)

> **Kritik ayrım (karıştırma):** Challenge Mode ve Funded Mode aynı sistem
> **değildir** — objective'leri farklıdır.
> - **Challenge Mode** hedefi = *engelleri aşmadan +%10/+%5'e ulaşma olasılığı*
>   (varyans-kısıtlı bariyer problemi). Ayrı doküman:
>   `FTMO_CHALLENGE_MODE_RESEARCH.md`.
> - **Funded Mode** hedefi (bu doküman) = *zaman içinde çekilen (withdrawn)
>   toplam kârı maksimize ederken hesabı patlatmama (risk-of-ruin minimizasyonu)*.
>   Funded'da patlama = hesabı **ve** kazanılmış tamponu **ve** gelecekteki gelir
>   akışını kaybetmek — challenge'daki "tekrar dene"den **çok** daha pahalı.

## Metodoloji
- Gerçek hesap günlük getiri serisi (n=930 gün, portföy bacaklarından türetildi:
  XAU 0.35 / XAG 0.35 / BTC 0.30 / GER40 0.25 / JP225 0.45, NAS100 çıkarıldı,
  EA-eşleşen takvim-önceki-gün PDHL). Ort **+0.104%/gün**, std **1.190%/gün**.
- 180 işlem-günü ufuk, **30-günlük payout döngüsü** (her 30 günde eşik üstü kâr
  çekilir, 0.5% tampon tutulur), FTMO tarzı statik zemin: günlük −%5 breach,
  toplam zemin 0.90 (başlangıcın −%10'u).
- Üretim EA paritesi: başlangıç-altı survival de-risk (dd≥3%→×0.6, dd≥6%→×0.35)
  her modelde açık.
- 20k–30k bootstrap yolu; hem **iid** hem **blok-bootstrap (uzunluk 5)** ile
  serial-dependence robustluğu.
- Metrikler: risk-of-ruin, çekilen kâr (medyan/ort), toplam P&L dağılımı
  (p5/medyan/p95), ort maxDD, expected shortfall (en kötü %5 ort P&L),
  30/60/90-günde payout olasılığı.
- Script: `scripts/ftmo_funded_growth.py` (+ `_payout.py`, `_blockboot.py`).

## Sonuçlar — 180 gün, 30-günlük payout döngüsü (iid)
| model | breach/ruin% | med çekilen | ort çekilen | p5 TP | med TP | p95 TP | maxDD | ES | pay30/60/90 |
|---|---|---|---|---|---|---|---|---|---|
| fixed1.0 | 2.59 | 16.5% | 18.6% | −6.2% | 14.5% | 45.5% | 7.5% | −9.1% | 59/73/81% |
| **fixed1.3** | **9.91** | 21.7% | 24.5% | −5.9% | 19.2% | 59.5% | 8.9% | −10.0% | 59/74/81% |
| stepped | 2.47 | 16.9% | 19.9% | −6.2% | 14.9% | 51.3% | 7.7% | −9.0% | 58/73/80% |
| stepped+guard | 1.95 | 15.7% | 18.7% | −6.3% | 13.7% | 48.3% | 7.5% | −8.7% | 57/72/79% |
| smooth | 2.53 | 16.7% | 19.9% | −6.2% | 14.7% | 51.5% | 7.8% | −9.1% | 57/72/79% |
| **smooth+guard** | **1.77** | 16.0% | 19.1% | −6.2% | 14.1% | 49.3% | 7.6% | **−8.6%** | 57/72/79% |
| hw_reset | 2.64 | 17.0% | 20.3% | −6.3% | 15.0% | 52.9% | 7.9% | −9.2% | 56/71/79% |

- **profit-funded scaling** modelleri (stepped/smooth/hw_reset): sadece
  başlangıç-üstü kârdayken büyütür ("house money"), böylece sağ-kuyruğu
  kalınlaştırır (ort çekilen 18.6→~20%, p95 TP 45→~52%) **ruin'i artırmadan**
  (~2.5% ≈ fixed1.0).
- **payout-approach guard** (payout'tan önceki 3 gün risk ×0.5): birikmiş,
  çekilmek üzere olan kârı korur. smooth: ruin 2.53→**1.77** (−0.76pt, ~%30 az),
  ES −9.1→−8.6, ort çekilen 19.9→19.1 (ihmal edilebilir maliyet).

## Robustluk — blok-bootstrap (serial dependence korunmuş)
| sampler | model | ruin% | ort çekilen | med TP |
|---|---|---|---|---|
| iid | fixed1.0 | 2.69 | 18.6% | 14.5% |
| iid | smooth | 2.46 | 20.1% | 14.9% |
| iid | smooth+guard | 2.05 | 19.1% | 14.1% |
| block5 | fixed1.0 | 1.91 | 18.2% | 14.2% |
| block5 | smooth | 2.03 | 19.2% | 14.3% |
| block5 | **smooth+guard** | **1.75** | 18.4% | 13.9% |

**Dürüst nüans:** Blok-bootstrap altında (kümelenme) **düz smooth**, fixed1.0'a
göre ruin'i marjinal **yükseltir** (2.03 vs 1.91) — yani "bedava" değil; kümelenmiş
kötü serilerde house-money büyütmesi biraz risk ekler. **guard** bunu telafi eder:
smooth+guard her iki sampler'da da en düşük ruin'e sahip (1.75 blok / 2.05 iid) ve
fixed1.0'ı **kesin** olarak dominat eder (daha az ruin + daha çok çekilen kâr).

## Karar
| model | funded için karar | neden |
|---|---|---|
| fixed1.0 | temel/kabul | güvenli ama sol-taraf odaklı; sağ-kuyruğu boşa geçiriyor |
| **fixed1.3** | **REDDEDİLDİ** | ruin ~%10 — funded'da felaket (hesap+tampon+gelir kaybı) |
| stepped | kabul | fixed1.0'dan iyi; smooth ile ~denk |
| **smooth + payout guard** | **KABUL (önerilen)** | en iyi risk-ayarlı: en düşük ruin, en iyi ES, ~en yüksek çekilen |
| hw_reset | kabul (alternatif) | smooth'a çok yakın, biraz daha agresif |

### Önerilen Funded Growth Mode parametreleri (güvenli aralık)
- **Taban risk 1.0×** (başlangıç-altında ve hw'den dd≥1.5% iken daima 1.0×).
- **profit-funded büyütme:** kârın her +%1'i için +0.08× (smooth), **tavan 1.5×**.
  (stepped alternatifi: +%2→1.15×, +%4→1.30×, +%6→1.45×.)
- **payout-approach guard:** payout'tan önceki **3 gün** risk **×0.5**.
- payout döngüsü 30 gün, çekişte 0.5% tampon bırak, üstünü çek.
- survival de-risk (üretimle aynı) daima açık.

> Bu, **challenge geçtikten SONRA** funded fazında devreye girer — challenge
> fazında değil. Challenge'da hedef bariyere ulaşmak; orada profit-funded büyütme
> mantıklı değil (henüz "house money" yok). İki mod objective'i **karışmaz**.

## Silver Carry açık/kapalı varyantı
**MOOT (koşulmadı).** Silver Runner Carry Step 1'de **reddedildi** (tam-örneklem
~0R, monster-bağımlı, yıl-tutarsız, long/short asimetrik —
`FTMO_RUNNER_CARRY_RESEARCH.md`). Reddedilmiş bir lever'ı funded varyantı olarak
geri getirmek metodoloji ihlali olurdu. Funded modeli mevcut, doğrulanmış exit
mantığı üzerine kurulu.

## Sınırlamalar
- Getiri serisi Yahoo-proxy'den; gerçek broker fill/spread KAPI-1 ile gelecek.
- Bootstrap günlük getiriyi yeniden örnekler; rejim-değişimi/uzun-hafıza
  modellenmez (blok-bootstrap kısa-vadeli kümelenmeyi yakalar, uzun trendi değil).
- "payout olasılığı" eşik-üstü herhangi bir çekiş; FTMO'nun asgari-gün/tutar
  kurallarına göre operasyonda ayarlanmalı.
