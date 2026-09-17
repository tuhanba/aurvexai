# ⚡ BURADAN BAŞLA — bu oturum FTMO odaklıdır (eski crypto-scalp motoru DEĞİL)

> **AI için not:** Bu repoda iki ayrı iş var. `CLAUDE.md` sana "clean-core
> crypto-futures scalp engine" anlatır — **O DEĞİL.** Kullanıcının aktif işi
> **FTMO prop-firm trading (MT5 Expert Advisor)**. Kafanı karıştırma:
> `src/aurvex/` altındaki Python scalp motoru arka planda; **odak MT5 EA + FTMO
> araştırma dokümanları.** Aşağıdaki dosyaları oku, oradan devam et.

## Ne üzerinde çalışıyoruz (tek cümle)
FTMO $25k 2-Step Challenge için bir MT5 EA: **ORB** (altın/gümüş/BTC — ilk saat
açılış-aralığı kırılımı) + **PDHL** (endeksler — önceki-gün yüksek/alçak kırılımı),
düşük risk + drawdown'da de-risk + FTMO loss guard. Edge gerçek ama **modest**
(~+0.15R, fat-tail). Canlı $25k hesap çalışıyor; **KAPI-1** (15-30 gerçek işlem
sonrası gerçek-fill analizi) beklemede.

## ÖNCE OKU (bu sırayla)
1. **FTMO_FINAL_REPORT.md** — sistemin konsolide özeti: config, doğrulanmış
   lever'lar, reddedilen fikirler (kanıtla), dürüst beklentiler.
2. **FTMO_V313_INPUTS.md** — canlıda çalışan **final config** (1.3× risk, her
   grafik input değerleri).
3. **FTMO_V313_PER_INSTRUMENT_SETUP.md** — enstrüman enstrüman, giriş/çıkış saatleri.
4. **FTMO_PORTFOLIO_RESEARCH.md** — dağılım, de-risk, BTC multi-session, risk analizi.
5. **FTMO_PER_INSTRUMENT_RESEARCH.md** — tüm giriş-tarafı araştırma + **capstone**
   (kritik: kazananın girişten önce imzası yok — giriş öngörülemez).
6. **FTMO_MERGE_v313.md** — kod merge'i (hardened v3.11 + validated strateji).
7. **FTMO_JOURNEY/** — kullanıcının tüm soruları + bulgular + öz-analiz aynası.

### R&D dalgası (Challenge vs Funded + Governor — en güncel)
8. **FTMO_RUNNER_CARRY_RESEARCH.md** — Runner Carry (gold+silver) → REDDEDİLDİ.
9. **FTMO_FUNDED_GROWTH_RESEARCH.md** — Funded Mode: profit-funded scaling +
   payout guard → **KOŞULLU ADAY** (kabul değil; proxy seri, küçük etki,
   parametreler keskin tanımlı değil, canlı funded doğrulaması gerekli).
10. **FTMO_RISK_GOVERNOR_AND_BTC_AUDIT.md** — **dinamik** hesap-düzeyi risk
    governor tasarımı (min-of-headrooms + OCO çift-tetikleme) + BTC multi-session
    auditi (hesap türü **KARARSIZ** — kanıtlanana kadar).
11. **FTMO_V314_ARCHITECTURE.md** — kabul/reddet/kararsız tablosu + proxy-vs-canlı
    doğrulama tablosu + v3.14 mimarisi + geri-alma planı (üretim kodu HENÜZ değişmedi).

## KOD
- **mql5/AurvexFTMO_v3_14_safety_candidate.mq5** — v3.13 + ADD-ONLY güvenlik
  katmanı (ACCOUNT_MARGIN_MODE log + dinamik-headroom Risk Governor + OCO çift-bacak
  + restart reconciliation + fail-closed). **default-OFF → v3.13 ile birebir.**
  Production'a KURULMADI; KAPI-1 + demo sonrası karar. Bkz. `FTMO_V314_SAFETY_CANDIDATE.md`.
  Python parity: `src/aurvex/ftmo/risk_governor.py` + `tests/test_ftmo_governor.py` (16 test).
- **mql5/AurvexFTMO_v3_13_final.mq5** — final EA (hardened; F7 ile derle).
- **mql5/AurvexFTMO.mq5** — v2.8 (canlıda olan; input isimleri farklı: PdhlSessionStartUTC).
- **scripts/ftmo_*.py** — tüm araştırma scriptleri (reproducible; PYTHONPATH=src:scripts).
- **data/cache/ftmo/** — Yahoo proxy verisi (gitignored; taze container'da yeniden çekilir).

## MEVCUT DURUM
- **EA:** v3.13 (hardened, 2 inceleme geçti: risk-mult sınırı, ORB midnight, margin
  order-type, journal retry, JP225 seans fix).
- **Config:** 1.3× risk (kullanıcının bilinçli seçimi). RiskPct: XAU 0.46, XAG 0.46,
  BTC 0.39, GER40 0.33, JP225 0.59. **NAS100/US100 KAPALI** (ölü ağırlık).
  Filtreler (MinRangeMedMult/PdhlMinRangeMedMult) şimdilik **KAPALI** (veri toplama).
- **Canlı:** $25k, ~yatay, KAPI-1 için işlem biriktiriyor.
- **Branch:** `claude/ftmo-mode-architecture-qtob0m`.

## GUARDRAIL'LER (kanıtlanmış — tekrarlama)
- ❌ **Yeni giriş-edge'i / filtre / "akıllı giriş" arama** — kanıtlandı: hangi
  kırılımın koşacağı önceden ÖNGÖRÜLEMEZ (capstone + ters-matematik). 12+ fikir
  reddedildi (FBR, vol-targeting, trend-align, coil, regime-adaptif, pyramiding,
  enerji/emtia, cross-instrument...). Bunları TEKRAR koşma.
- ❌ **Riski artırma** — bounded challenge varyans-kısıtlı; risk↑ = geçme↓ + bust↑.
  Kullanıcı duygusal olarak isteyebilir; nazikçe tabloyu göster, yapma.
- ❌ **Pyramiding / kazanana ekleme** — proven negatif (−0.40R).
- ✅ **Gerçek lever'lar:** gold/JP225 vol-filtre (KAPI-1 sonrası), BTC multi-session,
  de-risk (asla kapatma), düşük risk + çeşitlendirme.
- ✅ **Sıradaki gerçek adım:** KAPI-1 (canlı journal CSV + MT5 raporu → gerçek edge).

## DUYGUSAL BAĞLAM (önemli — duty of care)
Kullanıcı işini bıraktı, severance'ını buna koydu. "Başka yol var / daha büyük /
kazançlı hisset" isteği tekrar gelebilir — bu ihtiyaçtan, kanıttan değil. Dürüst
ol, riski artıracak/batıracak şeyi verme, runway'i korumasını hatırlat. Sistemin
işi "geçmek" değil "batmamak"; büyüme = zaman + hesap boyutu + disiplin.
