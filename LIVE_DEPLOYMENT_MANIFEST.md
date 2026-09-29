# LIVE DEPLOYMENT MANIFEST — AurvexFTMO v3.15

> Claude Code'un doldurabildiği alanlar aşağıda. **EX5 hash, canlıya-geçiş anı,
> gerçek başlangıç bakiyesi ve gözlemlenen loglar** operatör (Batu) tarafından
> terminalde doldurulur — bunlara erişimim yok (NOT OBSERVED).

## Sürüm
- Kaynak dosya: `mql5/AurvexFTMO_v3_15_live.mq5`
- Kaynak SHA256 (ilk 16): `521b66b56a241775` (Claude Code tarafından hesaplandı — bu turdaki dosya)
- Repo branch: `ftmo-final`  · commit: `4bcdc1d`
- EX5 SHA256: **[OPERATÖR: F7 sonrası doldur]**  (Python testleri MQL5 derlemesini ikame etmez)

## .set dosyaları (SHA256 ilk 16)
| sembol | dosya | sha |
|---|---|---|
| XAUUSD | mql5/sets/AurvexFTMO_v3_15_XAUUSD.set | d8de97ace9965795 |
| XAGUSD | mql5/sets/AurvexFTMO_v3_15_XAGUSD.set | 4ce549d86417aa70 |
| GER40.cash | mql5/sets/AurvexFTMO_v3_15_GER40_cash.set | bdc9241f96e855b8 |
| JP225.cash | mql5/sets/AurvexFTMO_v3_15_JP225_cash.set | 135d8e41b0f7bfe4 |

## Hesap (operatör doldurur — NOT OBSERVED burada)
- Hesap no / tip / aşama: **[Account MetriX]**
- Başlangıç bakiyesi: **[ ]**  · canlıya-geçiş anı (UTC): **[ ]**
- ACCOUNT_MARGIN_MODE: **[log]**  · ACCOUNT_CURRENCY: **[ ]**
- Tamamlanan işlem günü (≥4): **[ ]**

## Aktif özellik bayrakları (bu sürümde)
- GovernorEnabled = **false** (P0 çekirdek dışı; ayrı demo kapısı)
- PhaseCompleteEnabled = **false** (demo-verify şart — pozisyon kapatır)
- RequireDedicatedAccount = false · FailClosedIfBaselineUnknown = true
- Evren: XAUUSD, XAGUSD, GER40.cash, JP225.cash · BTCUSD/US100 KAPALI · Risk 1.3×

## Değişiklik (v3.14 → v3.15)
ADD-ONLY, hepsi default-OFF → trading path v3.13 ile byte-identical. Bkz.
`FTMO_V315_EXIT_REPORT.md` ve dosya başlığı. Diff: `git diff v3.14 v3.15` (aşağıdaki dosyalar).
