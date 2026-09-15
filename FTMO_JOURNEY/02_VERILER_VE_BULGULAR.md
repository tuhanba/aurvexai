# Veriler ve bulgular — her sorunun karşısında ne çıktı

Her araştırmanın sonucu, tek yerde. "Gerçek + doğrulanmış" mı, yoksa "reddedildi" mi.

## ✅ GERÇEK + doğrulanmış (sisteme girdi)
| lever | sonuç |
|---|---|
| Gold düşük-vol filtresi | OOS +0.19R → +0.36R; bootstrap CI alt sınırı >0; cost-toleransı 2× |
| JP225 gerçek edge | +0.086R OOS (EA-matching, CI sıfırı dışlıyor); "breakeven" değil |
| Dağılım: NAS100/US100 kes | negatif beklenti (−0.014); break-even %0.013 (her spread öldürür) |
| Dağılım: JP225 ağırlık ↑ | 0.30 → 0.45; monoton faydalı |
| De-risk (drawdown'da kıs) | 3/0.6/6/0.35 optimal; blok-bootstrap'ta +6.5pt; asla artırma |
| BTC multi-session (KAPI-1 sonrası) | 3 korelasyonsuz seans: mean↑ std↓ bust↓ (reach 98.2→99.4) |
| Maliyet break-even tablosu | enstrüman-başına tolere edilebilir maks spread |

## ❌ REDDEDİLDİ (test edildi, kanıtla)
| fikir | neden reddedildi |
|---|---|
| FBR (kırılım fade) | look-ahead artifact; dürüst versiyon metallerde negatif |
| Çapraz-onay (+0.355) | look-ahead artifact |
| Vol-targeting (yüksek-volde büyüt) | bounded challenge'da OOS geçişi DÜŞÜRÜR |
| HTF trend-hizası | gerçek yön ama CI sıfırı kesiyor (robust değil) |
| Coil/inside own-TA | gerçek yapı ama CI sıfırı kesiyor |
| Align+range kombosu | örneklem çöküyor, +0.499→+0.034 |
| Cross-instrument confluence | fayda yok / BTC'de zarar |
| Pyramiding (kazanana ekleme) | felaket: +0.19→−0.40, varyans↑ |
| Metal parametre tuning | overfit: train↑ test↓ |
| Enerji/emtia range filtresi | imza 0.8σ ama kâra dönmüyor (simetrik) |
| Rejim-adaptif | gerçek yön ama CI sıfırı kesiyor |
| Scalp | net-negatif (önceki kampanya, NO-GO) |

## 🔬 CAPSTONE — en önemli matematiksel kanıt
Kendi birleşik TA modelimizi kurduk (öğrenilen ağırlıklar):
- Özelliklerin işlem-R ile korelasyonu **~0** (0.005–0.05).
- Skor OOS'ta **kazananı kaybedenden ayıramıyor** (top %50 = baz).
- **Ama çıplak kırılım anlamlı** (CI [+0.022, +0.278], sıfırı dışlıyor).

**Ters matematik (senin fikrin):** en büyük %20 koşucu (+3.68R) ile kaybedenler,
girişten önce **AYNI görünüyor** (fark ~0σ). Koşucunun ön-imzası yok.

**Sonuç:** Hangi kırılımın koşacağı **önceden öngörülemez.** Bu yüzden her
giriş-filtresi OOS'ta çöküyor. Bulamamamız değil — imzanın olmaması.

## Risk vs Geçme (dürüst metrik, proxy)
| risk çarpanı | metal% | +%10 ulaşma | patlama |
|---|---|---|---|
| 1.0× | 0.35 | 98.2% | 1.8% |
| **1.3× (seçilen)** | **0.46** | **94.8%** | **5.2%** |
| 2.0× | 0.70 | 84.8% | 15.2% |
| 4.0× ("maksimum") | 1.40 | 64.6% | 35.4% |

## Kod kalitesi
- İki bağımsız inceleme (Claude + ChatGPT).
- v3.13: risk-mult sınırı, ORB midnight, margin order-type, journal retry, JP225 seans fix.
- Restart-safe, oto-DST, margin/retcode/freeze guard. Kod ~9/10; **sonuç asla 10/10 değil.**
