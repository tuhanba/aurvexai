# FTMO Funded Growth Mode — araştırma (Step 2, DÜZELTİLMİŞ)

> **Bu doküman kullanıcı incelemesine göre düzeltildi.** Önceki sürüm (a) seriyi
> yanlışlıkla "gerçek hesap günlük getiri serisi" diye adlandırdı, (b) parametre
> seçimi ile final değerlendirmeyi ayırmadı, (c) yalnızca en iyi varyantı gösterdi,
> (d) smooth+guard'ın fixed1.0'ı "kesin domine ettiğini" yazdı. Hepsi düzeltildi.

## Veri kaynağı — DÜZELTME (önemli)
Kullanılan günlük getiri serisi **gerçek hesap serisi DEĞİLDİR.** Yahoo-proxy
verisinden (`ftmo_trail_probe.load`) türetilmiş **portföy-bacağı simülasyon
serisidir**: her enstrümanın backtest günlük-R'leri, taban ağırlıklarla
(XAU 0.35 / XAG 0.35 / BTC 0.30 / GER40 0.25 / JP225 0.45, NAS100 çıkarıldı,
EA-eşleşen takvim-önceki-gün PDHL) hesap günlük getirisine çevrildi. Yani tüm
aşağıdaki sayılar **proxy** kanıttır; **canlı doğrulama (KAPI-1) gerektirir.**

## Objective (challenge'dan ayrı — karıştırma)
Funded hedefi = *zaman içinde çekilen (withdrawn) kârı maksimize ederken hesabı
patlatmama (risk-of-ruin minimizasyonu).* Funded'da patlama = hesap + tampon +
gelir akışı kaybı. Challenge Mode (bariyer-ulaşma) ayrı objective'tir.

## Metodoloji — DÜZELTME
- **Kronolojik split:** seri (n=930) zamana göre sıralı; ilk **%60 TRAIN** (n=558,
  ort +0.099%/gün, std 1.249%), son **%40 untouched TEST** (n=372, ort +0.110%,
  std 1.094%). Split `ftmo_deep_portfolio.py`'deki 0.60 konvansiyonuyla aynı.
- **Parametre taraması yalnızca TRAIN'de.** TEST yalnızca **bir kez**, sonda okunur.
- **Blok-bootstrap (L=5) TEST üzerinde** ayrıca — serial dependence.
- 180 işlem-günü, 30-günlük payout döngüsü, 12k bootstrap yolu/config.
- **Parametre provenance (dürüstlük):** +0.08×/%1, tavan 1.5×, guard 3-gün ×0.5
  değerleri önceki turda **veriye optimize edilerek DEĞİL, yargı/konvansiyonla**
  seçilmişti. Bu tur komşu-ızgara ile test edildi (aşağıda). Izgara **düz** çıktı
  (hücreler arası fark MC gürültüsü içinde) → veri **hiçbir hücreyi keskin biçimde
  tercih etmiyor**; "optimal parametre" iddiası sahte-kesinlik olur.
- Script: `scripts/ftmo_funded_growth_grid.py` (reproducible).

## Referanslar
| split | model | ruin% | med çekilen | ort çekilen | med TP | ort TP |
|---|---|---|---|---|---|---|
| TRAIN | fixed1.0 | 4.18 | 15.8% | 18.3% | 13.3% | 15.6% |
| TRAIN | fixed1.3 | 14.28 | 21.0% | 24.3% | 18.3% | 21.4% |
| TEST | fixed1.0 | 1.10 | 18.1% | 19.6% | 16.7% | 17.9% |
| TEST | fixed1.3 | 4.91 | 23.1% | 25.4% | 21.4% | 23.3% |

## Komşu-ızgara — smooth (guard YOK), rate × cap (TÜM varyantlar)
**TRAIN** (ruin ~%4.0–4.6 tüm hücrelerde ≈ fixed1.0; med çekilen ~15.8–16.2 ≈ sabit):
| rate\cap | 1.2 | 1.3 | 1.4 | 1.5 |
|---|---|---|---|---|
| 0.04 | 4.29 / 19.3 | 4.57 / 18.9 | 4.08 / 19.0 | 4.27 / 18.9 |
| 0.06 | 4.03 / 19.0 | 4.60 / 19.2 | 4.12 / 19.5 | 4.09 / 19.6 |
| 0.08 | 4.23 / 19.0 | 4.36 / 19.4 | 4.54 / 19.6 | 4.09 / 19.6 |
| 0.10 | 3.98 / 18.9 | 4.39 / 19.4 | 4.47 / 19.5 | 4.01 / 19.5 |

*(hücre = ruin% / ort çekilen%; med çekilen tüm hücrelerde ~16% ≈ fixed1.0'ın 15.8%)*

**TEST (untouched)** — aynı ızgara:
| rate\cap | 1.2 | 1.3 | 1.4 | 1.5 |
|---|---|---|---|---|
| 0.04 | 0.88 / 20.5 | 1.18 / 20.7 | 1.10 / 20.7 | 1.31 / 20.9 |
| 0.06 | 1.08 / 20.7 | 1.21 / 20.8 | 1.06 / 20.9 | 1.08 / 20.8 |
| 0.08 | 1.06 / 20.9 | 1.04 / 20.8 | 1.18 / 21.1 | 0.88 / 21.4 |
| 0.10 | 1.15 / 20.7 | 1.21 / 20.9 | 1.00 / 21.2 | 1.10 / 21.2 |

**Okuma:** ızgara **düz**. rate/cap seçimi sonucu anlamlı değiştirmiyor (fark
~±0.5pt, MC gürültüsü içinde). smooth, fixed1.0'a göre **ort çekilen** +~1–1.8pt
(TEST 19.6→~20.8), ama **med çekilen** neredeyse aynı (18.1→~18.5). Yani kazanç
**sağ-kuyrukta**, medyan trader'ın çektiği tutar pek değişmiyor.

## Komşu-ızgara — smooth+guard (rate=0.08, cap=1.5), gün × çarpan
| split | guard | ruin% | med çekilen | ort çekilen | med TP |
|---|---|---|---|---|---|
| TRAIN | 2g ×0.5 | 3.72 | 15.1% | 18.7% | 12.8% |
| TRAIN | 2g ×0.7 | 3.57 | 15.7% | 19.2% | 13.2% |
| TRAIN | 3g ×0.5 | 3.71 | 15.4% | 18.5% | 12.9% |
| TRAIN | 3g ×0.7 | 3.61 | 15.2% | 18.7% | 12.8% |
| TRAIN | 5g ×0.5 | 2.95 | 14.8% | 18.2% | 12.4% |
| TRAIN | 5g ×0.7 | 3.33 | 15.3% | 18.6% | 12.9% |
| TEST | 2g ×0.5 | 0.89 | 18.2% | 20.9% | 16.7% |
| TEST | 2g ×0.7 | 1.02 | 18.2% | 20.8% | 16.8% |
| TEST | 3g ×0.5 | 0.73 | 17.8% | 20.3% | 16.4% |
| TEST | 3g ×0.7 | 0.93 | 18.1% | 20.6% | 16.7% |
| TEST | 5g ×0.5 | 0.68 | 17.0% | 19.5% | 15.5% |
| TEST | 5g ×0.7 | 0.78 | 17.8% | 20.3% | 16.4% |

**Okuma:** guard **bedava değil.** Ruin'i düşürür (TRAIN 4.1→~3.6, 5-gün ×0.5 ile
2.95; TEST 1.1→~0.7) **ama çekilen kârı da düşürür** — hem medyan hem ortalama.
Guard ne kadar uzun/sert (5g ×0.5) o kadar çok ruin↓ ama withdrawn↓. Bu bir
**risk-tercihi takası**, kesin iyileştirme değil.

## Blok-bootstrap TEST (en muhafazakâr görünüm)
| model | ruin% | med çekilen | ort çekilen | med TP |
|---|---|---|---|---|
| fixed1.0 | 0.53 | 18.2% | 19.6% | 16.8% |
| smooth r=.08 cap1.5 | 0.76 | 17.9% | 20.6% | 16.4% |
| smooth+guard 3g ×0.5 | 0.46 | 17.2% | 20.3*? | 15.9% |
| smooth+guard 3g ×0.7 | 0.62 | 17.8% | 20.3% | 16.5% |

*(smooth+guard 3g×0.5 ort çekilen 19.5% — fixed1.0 ile ≈ aynı.)*

**Kritik dürüst okuma (önceki "kesin domine" iddiası GERİ ÇEKİLDİ):**
- Düz **smooth**, fixed1.0'a göre ort çekilen **+1.0pt** ama **med çekilen DAHA
  DÜŞÜK** (17.9 < 18.2) **ve ruin DAHA YÜKSEK** (0.76 > 0.53). Domine etmiyor —
  sağ-kuyruğu medyan/ruin karşılığında satın alıyor.
- **smooth+guard 3g×0.5**: ruin daha düşük (0.46) ama çekilen (medyan+ortalama)
  fixed1.0'ın altında/eşit. Guard, withdrawn karşılığında ruin alıyor.
- **smooth+guard 3g×0.7** (yumuşak guard): orta yol — ort +0.7pt, ruin ~denk,
  medyan biraz altında.

## KARAR — KOŞULLU KABUL / ARAŞTIRMA ADAYI (KABUL değil)
| model | funded kararı | neden |
|---|---|---|
| fixed1.0 | temel | güvenli; en yüksek medyan çekilen, en düşük ruin |
| **fixed1.3** | **REDDEDİLDİ** | ruin funded'da felaket (TRAIN 14%, TEST 4.9%) |
| smooth (profit-funded) | **KOŞULLU ADAY** | küçük sağ-kuyruk kazancı (+~0.5–1pt ort), medyan düz/aşağı, ruin ~denk-yukarı; parametreler keskin tanımlı değil |
| smooth+guard | **KOŞULLU ADAY** | ruin↓ ama withdrawn↓ takası; risk-tercihi meselesi |

**Sonuç:** Profit-Funded Acceleration **kabul edilmedi**; küçük, gerçek ama
zayıf-tanımlı bir sağ-kuyruk lever'ı olarak **araştırma adayı**. Etki proxy seride
MC gürültüsüne yakın; parametreler veri tarafından keskin seçilemiyor. **Canlı
funded verisi (challenge geçildikten sonra) olmadan devreye alınmamalı.**

## Silver Carry açık/kapalı
**MOOT** — Silver Runner Carry Step 1'de **reddedildi** (gold+silver). Yeniden
açılmadı, funded varyantı olarak ambalajlanmadı.

## Sınırlamalar
- **Proxy seri** — gerçek broker fill/spread/komisyon yok (KAPI-1 ile gelecek).
- Bootstrap günlük getiriyi yeniden örnekler; rejim-değişimi/uzun-hafıza yok
  (blok-bootstrap yalnız kısa kümelenmeyi yakalar).
- Ruin nadir olay (~%1–4); 12k yol MC gürültüsü ±0.3pt seviyesinde — hücreler-arası
  küçük farklar anlamlı değil.
