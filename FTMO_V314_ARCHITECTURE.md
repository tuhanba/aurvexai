# FTMO v3.14 — önerilen mimari + kabul/reddet/kararsız tablosu (DÜZELTİLMİŞ)

> Kullanıcı incelemesine göre düzeltildi: H1 (BTC multi-session) **KARARSIZ**;
> H3 (Profit-Funded) **KABUL değil → KOŞULLU ADAY**; governor **dinamik**; proxy
> vs canlı-doğrulama ayrı tabloda. **Üretim EA kodu HÂLÂ değiştirilmedi.**

## 1) Tüm hipotezler — kabul / reddet / kararsız
| # | hipotez | karar | gerekçe |
|---|---|---|---|
| H1 | BTC multi-session (0/3/13) | **KARARSIZ / KOŞULLU** | Sim (proxy) faydalı görünüyordu, ama hedging varsayımına bağlı. Gerçek hesap `ACCOUNT_MARGIN_MODE` kanıtlanana + demo doğrulanana kadar açılmaz. Tek-seans güvenli. |
| H2 | Runner Carry (gold+silver) | **REDDEDİLDİ** | Gold negatif; silver tam-örneklem ~0R, monster-bağımlı, yıl-tutarsız (Step 1). **Yeniden açılmayacak.** |
| H3 | Profit-Funded Acceleration | **KOŞULLU ADAY** | Küçük sağ-kuyruk kazancı (+~0.5–1pt ort çekilen), **medyan düz/aşağı**, ruin ~denk; parametreler keskin tanımlı değil; proxy seri. Canlı funded verisi gerekli (Step 2 düzeltilmiş). |
| H4 | Account-Level Risk Governor | **KABUL (dinamik tasarım)** | Audit: hesap-düzeyi cap yok. Dinamik headroom (min-of-headrooms) + OCO çift-tetikleme + korelasyon grubu (Step 3). |
| H5 | Alpha sleeves (yeni giriş-edge) | **REDDEDİLDİ/koşulmadı** | Capstone: giriş öngörülemez; 12+ edge zaten reddedildi. |
| — | Challenge vs Funded ayrımı | **KABUL** | İki ayrı objective; `AccountPhase` ile ayrılır, karıştırılmaz. |

Look-ahead artifact çıkanlar (FBR, cross-confirmation) yeniden ambalajlanmadı.

## 2) Proxy kanıt vs canlı-doğrulama gerektiren (ayrı tablo — kullanıcı talebi)
| bulgu | kanıt tipi | canlı doğrulama gerekli mi |
|---|---|---|
| Çıplak kırılım edge'i (girişten önce imza yok) | proxy backtest + capstone | evet — KAPI-1 gerçek-fill |
| Gold/JP225 vol-filtresi faydası | proxy OOS + CI | evet — KAPI-1 |
| Dağılım (NAS100 kes, JP225 ağırlık↑) | proxy | evet — KAPI-1 |
| De-risk (drawdown'da kıs) | proxy blok-bootstrap | kısmen — canlı DD davranışı |
| **H1 BTC multi-session** | proxy sim | **evet — + hesap türü + demo hedging/netting** |
| **H3 Profit-Funded scaling/guard** | proxy TRAIN/TEST/blok | **evet — canlı funded serisi (challenge sonrası)** |
| **H4 Risk Governor (dinamik)** | tasarım + audit | **evet — demo: headroom hesabı, OCO çift-fill, 2-instance race** |
| Maliyet break-even tablosu | proxy | evet — gerçek spread/komisyon |

**Kural:** Yukarıdaki hiçbir proxy sonucu, canlı doğrulama (KAPI-1 / demo) olmadan
production davranışını değiştirmek için yeterli **değildir.**

## 3) Önerilen v3.14 mimarisi (v3.13 üzerine, hepsi default-off → v3.13 paritesi)
### Katman A — Hesap-türü görünürlüğü (H1)
- OnInit'te `ACCOUNT_MARGIN_MODE` **oku + logla** (Print + journal). Otomatik
  reddetme yok.
- Multi-session yalnızca `ConfirmHedgingVerified=true` (default false) + demo
  doğrulaması sonrası. Aksi halde tek-seans.

### Katman B — Dinamik Risk Governor (H4)
- `GovernorEnabled` (default false). Pre-trade: `allowedNew = min(dayHeadroom,
  overallHeadroom) − openStopRisk − pendingWorst(OCO çift) − slipGapBuf − costBuf`.
- Paylaşımlı GV `AXGOV_<login>_COMMITTED`, `GlobalVariableSetOnCondition` atomik,
  fail-closed, timer reconciliation. Detay: `FTMO_RISK_GOVERNOR_AND_BTC_AUDIT.md`.
- Yalnızca risk azaltır; `decide`/parity dokunulmaz.

### Katman C — Funded-fazı scaling (H3, KOŞULLU)
- `AccountPhase = challenge (default) | funded`.
- **challenge:** `RiskMultiplier()` v3.13 ile **birebir** (yalnız azaltır; byte-identical).
- **funded:** smooth profit-funded scaling (+rate/%1, tavan) + opsiyonel payout guard
  — **yalnızca canlı funded doğrulaması sonrası açılır** (KOŞULLU ADAY olduğu için
  default kapalı). Parametreler keskin tanımlı olmadığından tek "optimal" set
  dayatılmaz; muhafazakâr başlangıç (rate 0.06, cap 1.3, guard 3g ×0.7) önerilir,
  canlı veriyle revize edilir.

## 4) Kod-değişiklik raporu (uygulanınca — HENÜZ uygulanmadı)
| dosya | değişiklik | risk |
|---|---|---|
| `_v3_13_final.mq5` → `_v3_14.mq5` | Katman A/B/C, hepsi default-off | orta; gate'li |
| OnInit | `ACCOUNT_MARGIN_MODE` oku+logla; yeni input validasyonu | düşük |
| `CalcLots`/`EnsureStops` | dinamik headroom rezervasyonu (pre-trade) | orta; fail-closed |
| `OnTradeTransaction` | governor release + OCO iptal-onay | orta |
| `RiskMultiplier` | `AccountPhase==funded` dalı (challenge dalı değişmez) | orta; parity kritik |
| OnTimer | governor reconciliation | düşük |
| `tests/` | challenge-parity (v3.13 birebir) + governor-noop + OCO-double testleri | — |

### Geri alma planı
1. Her katman default-off → default davranış = v3.13. Sorunda input'u kapat.
2. v3.14 ayrı dosya; v3.13 dokunulmaz → anında geri dönüş.
3. Governor GV drift: `GlobalVariablesDeleteAll("AXGOV_")` + emergency flatten.
4. Parity testi (challenge sizing v3.13 birebir) geçmeden canlıya alınmaz.

## 5) Doğrulama kapısı (v3.14 canlı-öncesi)
1. `pytest` FTMO paketi yeşil + yeni challenge-parity/governor-noop/OCO testleri.
2. `AccountPhase=challenge` + governor off → sizing v3.13 ile **birebir**.
3. Demo: `ACCOUNT_MARGIN_MODE` log; hedging'de multi-session izolasyon; netting'de
   birleşme davranışı ölçülür.
4. Demo: governor headroom hesabı, OCO çift-fill senaryosu, 2-instance race.
5. **KAPI-1 önkoşulu değişmedi:** hiçbir proxy sonucu canlı doğrulama olmadan
   production'a girmez. Funded scaling ancak challenge geçilip funded fazına
   girilince + canlı funded verisiyle açılır.

---
**Tek cümle:** v3.14 edge'i büyütmez (giriş öngörülemez) — **hayatta kalmayı**
sağlamlaştırır (hesap-türü görünürlüğü + dinamik headroom governor + OCO koruması).
Funded scaling zayıf-tanımlı bir aday olarak default-kapalı kalır. Challenge
davranışı değişmez; hiçbir şey canlı doğrulama olmadan production'a girmez.
