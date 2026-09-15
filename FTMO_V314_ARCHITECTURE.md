# FTMO v3.14 — önerilen mimari + kabul/reddet/kararsız tablosu

Bu, brief'teki tüm hipotezlerin (Step 1–3) final kararı ve önerilen v3.14
mimarisidir. **Üretim kodu HENÜZ değiştirilmedi** — bu bir tasarım + değişiklik
raporu. Uygulama, aşağıdaki "geri alma planı" ile ayrı bir onaylı dalga olmalı.

## 1) Tüm hipotezler — kabul / reddet / kararsız
| # | hipotez | karar | kanıt / gerekçe |
|---|---|---|---|
| H1 | BTC multi-session (0/3/13 UTC) | **KOŞULLU KABUL** | Sim: reach 98.2→99.4, mean↑ std↓. **AMA** yalnızca **hedging** hesapta; netting'de yapısal çalışmaz (audit). Netting guard şart. |
| H2 | Runner Carry Engine (gold+silver) | **REDDEDİLDİ** | Gold: net negatif. Silver: tam-örneklem ~0R, monster-bağımlı, yıl-tutarsız, long/short asimetrik (Step 1, `FTMO_RUNNER_CARRY_RESEARCH.md`). |
| H3 | Profit-Funded Acceleration (funded mode) | **KABUL** | smooth+payout-guard: en düşük ruin (1.75% blok / 2.05% iid), en iyi ES, ~en yüksek çekilen kâr; iid+blok robust (Step 2). **Sadece funded fazı.** |
| H4 | Account-Level Risk Governor | **KABUL (tasarım)** | Audit: hesap-düzeyi açık-risk cap YOK; korelasyonlu-gün breach riski. Önleyici GV-bütçe katmanı (Step 3). |
| H5 | Alpha sleeves (yeni giriş-edge'leri) | **REDDEDİLDİ / KOŞULMADI** | Capstone: kazananın ön-imzası yok; 12+ giriş-edge zaten reddedildi. P3, P0-P2 tamamlanınca değerlendirilecekti; yeniden koşmak metodoloji ihlali. |
| — | Challenge vs Funded objective ayrımı | **KABUL** | İki mod ayrı objective (bariyer-ulaşma vs çekilen-kâr/ruin). Karıştırılmaz; `AccountPhase` input ile ayrılır. |

### Daha önce reddedilenler (tekrar getirilmedi — brief talimatı)
FBR/failed-breakout, cross-confirmation, vol-targeting, HTF trend-align, coil,
align+range, cross-instrument confluence, pyramiding, metal param-tuning,
energy/commodity carry, regime-adaptive, scalp. Look-ahead artifact çıkanlar
(FBR stop=range, cross-confirmation) **yeniden ambalajlanmadı.**

## 2) Önerilen v3.14 mimarisi (v3.13 üzerine, hepsi default-off)
v3.13 = doğrulanmış üretim tabanı. v3.14 üç katman ekler; **default input'larla
v3.14 davranışı v3.13 ile aynıdır** (geri-uyumlu).

### Katman A — Netting guard (H1 düzeltmesi)
- OnInit'te `ACCOUNT_MARGIN_MODE` oku.
- `RequireHedgingForMultiSession=true` (default) iken: netting + (OrbRangeHourUTC!=0
  veya birden fazla instance aynı sembolde) → `INIT_FAILED` + net uyarı.
- Hedging'de değişiklik yok.

### Katman B — Account-Level Risk Governor (H4)
- Paylaşımlı GV bütçesi (`AXGOV_<login>_OPEN_RISK`, `_DAY_NEW_RISK`),
  `GlobalVariableSetOnCondition` ile atomik rezerve/serbest.
- Yeni cap input'ları: `MaxTotalOpenRiskPct`(0=off), `MaxPendingRiskPct`,
  `MaxCorrelatedRiskPct`, `MaxNewRiskPerFtmoDayPct`, `SymbolGroup`.
- Pre-trade: `EnsureStops` emir göndermeden önce atomik rezerve; başarısız→skip.
- Release: `OnTradeTransaction` + timer reconciliation (canlı taramadan yeniden hesap).
- **Yalnızca risk AZALTIR** — parity/`decide` mantığına dokunmaz. default 0=off →
  v3.13 davranışı. Detay: `FTMO_RISK_GOVERNOR_AND_BTC_AUDIT.md`.

### Katman C — Funded Growth Mode risk scaling (H3)
- Yeni input `AccountPhase = challenge (default) | funded`.
- **`challenge`:** `RiskMultiplier()` v3.13 ile **birebir aynı** — yalnızca azaltır
  (invariant korunur; challenge davranışı byte-identical).
- **`funded`:** profit-funded büyütme aktifleşir (smooth: +0.08×/%1 kâr, tavan 1.5×,
  hw'den dd≥1.5%→1.0×) + payout-approach guard (payout'tan önceki 3 gün ×0.5).
  Yalnızca başlangıç-üstü "house money"de büyütür; başlangıç-altı daima 1.0× +
  survival de-risk.
- **KRİTİK invariant:** büyütme (>1.0×) **yalnızca** `funded` fazında ve yalnızca
  kâr tamponu varken. Challenge fazında >1.0× asla üretilmez.

## 3) Kod-değişiklik raporu (uygulanınca)
| dosya | değişiklik | risk |
|---|---|---|
| `mql5/AurvexFTMO_v3_13_final.mq5` → `_v3_14.mq5` | Katman A/B/C input+mantık | orta; hepsi default-off gate'li |
| OnInit | `ACCOUNT_MARGIN_MODE` guard; yeni input validasyonu (caps>=0, funded scaling bounds) | düşük |
| `CalcLots`/`EnsureStops` | governor pre-trade rezervasyon | orta (atomik; fail-closed) |
| `OnTradeTransaction` | governor release | düşük |
| `RiskMultiplier` | `AccountPhase==funded` dalı (challenge dalı değişmez) | orta (parity kritik) |
| OnTimer | governor reconciliation | düşük |
| `tests/` | yeni parity testi: `AccountPhase=challenge` → v3.13 sizing byte-identical; governor default-off → no-op | — |

### Geri alma planı
1. Her katman ayrı input ile gate'li, **default = v3.13 davranışı**. Sorun çıkarsa
   ilgili input'u kapat (INIT'te), kod geri-derleme gerekmez.
2. v3.14 ayrı dosya (`_v3_14.mq5`); v3.13 dokunulmadan kalır → grafikte eski EA'ya
   dönmek anında.
3. Governor GV drift'i: `AccountWideEmergencyFlatten` + GV sil (`GlobalVariablesDeleteAll("AXGOV_")`)
   ile temiz reset.
4. Parity testi geçmeden (challenge sizing v3.13 ile aynı) v3.14 canlıya alınmaz.

## 4) Doğrulama kapısı (v3.14 canlı-öncesi)
1. `pytest` yeşil (mevcut 12 parite testi + yeni challenge-parity + governor-noop).
2. `AccountPhase=challenge` + tüm governor cap=0 → sizing v3.13 ile **birebir**.
3. Hedging demo: BTC 3-seans magic izolasyonu; netting demo: OnInit reddi doğrulanır.
4. Governor: 2-instance eşzamanlı rezervasyon race testi (çift-rezerve yok).
5. **KAPI-1 hâlâ önkoşul:** funded scaling ancak challenge geçilip funded fazına
   girilince + 15-30 gerçek işlem gerçek-fill analizinden sonra açılır.

---
**Tek cümle:** v3.14, edge'i büyütmez (kanıt: giriş öngörülemez) — **hayatta kalmayı
sağlamlaştırır** (netting guard + hesap-düzeyi risk tavanı) ve **funded fazında**
kazanılmış kârı disiplinli biçimde bileşiklendirir (profit-funded scaling + payout
guard). Challenge davranışı değişmez.
