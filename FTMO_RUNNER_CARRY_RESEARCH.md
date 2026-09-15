# Runner Carry Engine — Hipotez B (2026-09-15)

Brief'in en önemli açık kapısı: *girişten önce runner tahmin edilemez, AMA runner
kanıtlandıktan sonra (post-entry, >=XR) onu UTC-gün-sonu zorunlu flatten'dan daha
iyi yönetebilir miyiz?* Pyramiding DEĞİL — sadece çıkış ufku + stop mimarisi.
Reproduce: `PYTHONPATH=src:scripts python scripts/ftmo_runner_carry_test.py`.

## Kurgu
ORB girişi normal. Giriş-günü UTC kapanışında açık R >= eşik (1/2/3R) ise, pozisyonu
sonraki gün(ler)e breakeven-korumalı stop'la taşı (K=1/2 gün, hafta sonu taşıma yok),
sonra kapat. Paired karşılaştırma: her taşınan işlemin carry-R'si vs gün-0-R'si.
Gerçek maliyet + gece başına swap (0 / 0.01% / 0.02%) + strict TRAIN/TEST + bootstrap CI.

## Sonuç
| enstrüman | variant | taşınan (TEST) | katkı/işlem | CI | verdict |
|---|---|---|---|---|---|
| XAUUSD | thr>=2 K=1 | 36 | -0.01R | [-1.22,+1.09] | fayda yok |
| XAUUSD | thr>=3 K=2 | 25 | **-1.08R** | [-2.64,+0.36] | zarar |
| XAGUSD | thr>=2 K=1 | 39 | **+0.69R** | [-0.13,+1.59] | umut verici (sınırda) |
| XAGUSD | thr>=3 K=2 | 28 | **+1.54R** | [-0.05,+3.47] | umut verici (sınırda) |

## Okuma
- **GOLD carry: REDDEDİLDİ.** Runner'ları gecelik devam etmiyor; taşımak geri veriyor.
- **SILVER carry: KARARSIZ-ama-en-güçlü-aday.** Etki BÜYÜK (+0.7..+1.6R/işlem), CI
  sadece kıl payı sıfırı kesiyor (alt sınır ~-0.05..-0.13) — sorun etki değil,
  küçük örneklem (~30 taşınan işlem). Swap etkiyi zar zor deliyor. Silver'ın max
  runner'ı carry ile +23R -> +40R büyüyor. Mekanik: silver daha momentumlu trend.
- **Yapısal fark tutarlı** (gold null / silver güçlü) — tek şanslı hücre değil,
  gerçek bir gold-vs-silver farkı.

## Karar (brief'in kuralına göre)
CI sıfırı DIŞLAMIYOR -> "kanıtlandı" denemez -> **KARARSIZ**. Ama şimdiye kadarki en
güçlü profit-lever adayı. **Uygulama önce KAPI-1** (gerçek silver fill'leri + gerçek
swap/gap/weekend) ile doğrulanmalı. Kod tarafı: UTC-flatten'i koşullu hale getirmek
gerekir (silver >=2R runner'da 1 gün carry, BE-stop). v3.14 adayı — ama önce canlı veri.

## Kısıtlar / eksik modelleme
- Proxy (Yahoo) veri; gerçek silver CFD swap'ı, hafta-sonu gap'i, gece spread'i farklı.
- Küçük taşınan-işlem örneklemi (~30 test) -> geniş CI. Daha çok veri = daha net karar.
- Sonraki gün ORB fırsatı: carry sırasında o enstrümanın yeni ORB'u bloklanır
  (fırsat maliyeti); ilk testte ölçülmedi, sonraki adım.
