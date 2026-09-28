# KAPI-1 — ilk canlı gerçek-fill analizi ve motor güncellemesi

**Tarih:** 2026-09-28 · **Kaynak:** MT5 rapor, hesap 541438670
(`$25k FTMO Challenge 2-Step`, gerçek, FTMO Global Markets) · **Örneklem:** 31 işlem
(hepsi robot/EA), 2026-09-09 → 09-23. **Not:** canlıdaki EA arkadaşının **v3.11**'i
(bizim v3.13 config'i değil) — bu, sonucun yorumunu belirliyor.

## Genel sonuç
| metrik | değer |
|---|---|
| işlem | 31 (16 kazanç / 15 kayıp, %52 win) |
| net | **−$633.66 = −%2.53** |
| profit factor | **0.58** |
| brüt kâr / zarar | +$865.81 / −$1499.47 |
| komisyon / swap | −$100.01 / −$11.74 |
| max ardışık kayıp | 4 işlem, −$442.79 |
| balance tepe→dip | ~25.213 → 24.366 (≈ −%3.4) |
| max drawdown (rapor) | ~%0.88 |

Beklentinin altında (proxy ~+0.15R), ama **n=31 fat-tail bir edge için az** — ne
doğrular ne çürütür. Önemlisi: **zarar birkaç tanımlı yerde yoğun**, hepsi
araştırmanın önceden işaret ettiği yerler.

## İki mercek (örtüşüyorlar — aynı paranın görünümleri)
**Yön:**
| yön | işlem | win | net |
|---|---|---|---|
| long | 23 | 14 (%61) | **−$7.16** (≈başabaş) |
| short | 8 | 2 (%25) | **−$626.50** |

**Enstrüman:**
| sembol | net | PF | işlem | komisyon |
|---|---|---|---|---|
| JP225.cash | **+$165.09** | 2.29 | 6 | 0 |
| US100.cash | +$0.42 | — | 1 | 0 |
| XAGUSD | −$49.46 | 0.75 | 3 | −0.62 |
| XAUUSD | −$175.47 | 0.54 | 5 | −1.50 |
| GER40.cash | −$283.09 | 0.36 | 7 | 0 |
| BTCUSD | **−$291.15** | 0.16 | 9 | **−$97.89** |

## İki kritik bulgu
1. **BTC'yi komisyon öldürüyor.** Toplam −$100 komisyonun **−$97.89'u BTC'den**
   (~$11/işlem, 1R≈$122'nin ~%9'u). Komisyondan arındırınca bile ~−$193 (canlı edge
   yok). Bu **deterministik** (varyans değil). MQL5'te komisyon işlem-öncesi güvenilir
   okunamadığından "cost gate" yerine **evrenden çıkarma** doğru mühendislik çözümü.
2. **Zarar shortlarda / GER40'ta yoğun.** Kaybeden shortların çoğu GER40 (v3.11
   back-scan Monday — araştırma negatif demişti) ve BTC. Longlar başabaş, JP225 pozitif
   — yani sistem geneli bozuk değil.

## Motor güncellemesi (bu analizden)
Bu bir **evren/config** kararı; strateji-mantığı değişmedi (GER40 Monday düzeltmesi
zaten v3.13 default'u).
| değişiklik | gerekçe | güven |
|---|---|---|
| **BTCUSD çıkarıldı** | komisyon + canlı edge yok + proxy'de zaten marjinaldi | yüksek (maliyet deterministik) |
| **US100 kapalı** (zaten) | ölü ağırlık | yüksek |
| **GER40 calendar-PDHL** (zaten v3.13 default) | v3.11 Monday back-scan −$283'ü getirdi | yüksek |
| **Gold filtresi AÇIK** (XAU MinRangeMedMult=1.0) | doğrulanmış (OOS +0.19→+0.36); KAPI-1 karar noktasıydı | orta-yüksek |
| **JP225 filtresi AÇIK** (PdhlMinRangeMedMult=1.0) | doğrulanmış (+0.086R) | orta-yüksek |
| short kuralı EKLENMEDİ | 8 işlem az; kaybeden shortlar zaten BTC/GER40 (çözüldü) | — kasıtlı |
| risk 1.3× korundu | kullanıcı tercihi; **1.0× önerilir** (negatif gidişatta daha güvenli) | kullanıcı kararı |

Yeni evren: **XAUUSD, XAGUSD, GER40.cash, JP225.cash** (4 grafik). Detay:
`FTMO_V313_INPUTS.md`, `FTMO_V313_PER_INSTRUMENT_SETUP.md`.

## Hayatta kalma vs challenge (dürüst)
- **Hayatta kalma: sorun yok.** Max DD ~%0.88, en kötü seri −%1.8; %5 günlük / %10
  toplam zemine çok uzak. Batmıyor.
- **Challenge geçme: mevcut gidişat negatif.** +%10 hedefi için −0.21R beklenti
  yetmez. Bu config düzeltmeleri (BTC çıkar, filtreler aç, GER40 Monday fix) **risk
  artırmadan** olasılığı iyileştirir. Ama 31 işlem garanti vermez — daha çok veri gerek.

## Operasyonel (canlı v3.11, bugün — kod/demo gerektirmez)
1. **BTCUSD grafiğini kaldır** → −$291'lik bacak gider.
2. **US100.cash grafiğini kaldır** → ölü ağırlık gider.
3. GER40 Monday v3.11'de togglelanamıyorsa: GER40'ı duraklat **veya** v3.13'e geçişte
   otomatik düzelir. Filtreler v3.13/v3.14'e özel.
4. Tam fayda: **v3.13'i F7 derle + demo doğrula, sonra geç.** Test edilmeden canlıya kurma.

## Sonraki KAPI (KAPI-2)
Yeni config'le (4 enstrüman, filtreler açık) 25-30 işlem daha topla → tekrar bu analizi
koş. Hedef: config-farkı çıkarılınca kalan gerçek edge pozitif mi?
