# FTMO v3.15 — ÇIKIŞ RAPORU (dürüst durum)

**Tarih:** 2026-09-29 · **Branch:** ftmo-final · Bu rapor: Claude Code'un bu turda
**gerçekte ne yaptığı**, neyi doğrulayamadığı ve operatörün yapması gerekenler.
Kâr vaadi yok; gelecek performans kesin sonuç gibi yazılmadı.

## Sert kısıtlar (bu ortam)
- **MT5 terminali / FTMO hesabı erişimi YOK** → hesap okuma, preflight, dry-run,
  Strategy Tester, ilk-fill gözlemi, aşama/tip/4-gün teyidi = **NOT OBSERVED (operatör).**
- **MQL5 derleyicisi YOK** → derleme/`.ex5`/"temiz F7" = **NOT OBSERVED (operatör).**
- Python testleri governor + phase-lock **matematiğini** doğrular; MQL5 derlemesini
  ve MT5-runtime davranışını **ikame etmez.**

## Gerçekte canlıda ne çalışıyor
- **Değişmedi.** Canlıda hâlâ arkadaşın **v3.11**'i. Bu tur repoya kod/dok ekledi;
  **hiçbir şey canlıya alınmadı, canlı input değişmedi.** (İş emri: "Bu belge iş emri;
  uygulanmış canlı çıkış raporu değildir.")

## Yapılan işler (durum)
| iş | durum | not |
|---|---|---|
| v3.15 kaynak kodu (A–E + phase-lock) | **DONE (kod)** / derleme **NOT OBSERVED** | `mql5/AurvexFTMO_v3_15_live.mq5`; statik: brace/paren dengeli, dup yok, handler tek |
| A. Baseline fail-closed | DONE (kod) | `FailClosedIfBaselineUnknown`; HistorySelect fail → yeni emir bloklanır |
| B. PhaseCompleteGuard | DONE (kod), **DEFAULT OFF** | realized-balance + cost-türevli buffer; foreign→review; partial→retry; idempotent/persistent; emergency öncelikli |
| C. Governor auto-group | DONE (kod) | SymbolGroup="" iken SymbolGroupOf(sym); governor yine default OFF |
| D. Currency/sizing | DONE (kod) | profit-ccy≠acct-ccy log'u; MaxSingleRiskMult skip korunur |
| E. Ownership preflight | DONE (kod) | foreign-exposure sayımı + uyarı; RequireDedicatedAccount ile refuse |
| Python referans testleri | **PASS** | phase-lock 13 + governor 16; `pytest tests/test_ftmo_*.py` → 139 passed |
| 4× `.set` dosyası | DONE | `mql5/sets/`; SHA'lar manifest'te |
| Manifest / precheck / rollback / speed-lab | DONE | operatör kapıları + P1 planı |
| MQL5 F7 derleme | **NOT OBSERVED** | derleyici yok — operatör F7 |
| Send-disabled dry-run | **NOT OBSERVED** | terminal yok — operatör |
| Strategy Tester (DST/gap/OCO/restart) | **NOT OBSERVED** | terminal yok — operatör |
| İlk canlı fill gözlemi | **NOT OBSERVED** | hesap yok — operatör |
| P1 hız simülasyonları | **NOT RUN** | veri yok bu ortamda; plan hazır (`FTMO_V315_SPEED_LAB.md`) |

## Değişen kod/ayar
- Yeni: `mql5/AurvexFTMO_v3_15_live.mq5` (v3.14 + A–E, hepsi default-OFF → trading path
  v3.13 ile byte-identical). v3.13/v3.14 dosyaları **değişmedi.**
- Yeni: `src/aurvex/ftmo/phase_lock.py`, `tests/test_ftmo_phase_lock.py`,
  `mql5/sets/*.set`, operatör dokümanları.
- Diff: `git diff` (v3.14 → v3.15) — sadece ekleme; strateji/giriş/çıkış/trailing/
  seans/RiskMultiplier/filtre satırları değişmedi.

## Hızda ölçülen fark
- **Henüz ölçülmedi.** P1 (first-passage) veri + OOS gerektiriyor; bu turda koşulmadı.
  Plan ve seçim kuralı hazır. **Hız iddiası yok.**

## Açık riskler
- v3.15 **derlenmedi** — F7'de hata çıkabilir; canlıya almadan önce zorunlu.
- PhaseCompleteGuard **pozisyon kapatıyor**; demo'da doğrulanmadan `true` yapılmamalı.
- Governor eşzamanlılık sertleştirmesi (lease/release-on-confirm) **tam yapılmadı** —
  bu yüzden governor P0'da kapalı; enable ayrı demo kapısına bağlı.
- 31 işlemlik KAPI-1 **pozitif canlı edge kanıtı değil**; config düzeltmeleri olasılığı
  iyileştirir ama garanti değil.

## Operatörün yapması gerekenler (sıra)
1. `FTMO_PRECHECK.md` → **F7 derle** (0/0), EX5 SHA'yı manifest'e yaz.
2. Hesap/sembol preflight (Account MetriX, açık pozisyon, BTC/US100 çöz).
3. 4 `.set` yükle, `base=25000` + log'ları doğrula, foreign-exposure uyarısı yoksa devam.
4. Send-disabled + kısa Strategy Tester senaryoları → PASS.
5. Kontrollü ilk canlı akış; ilk fill'i gözle; sapmada `LIVE_ROLLBACK.md`.
6. PhaseCompleteGuard/Governor'ı **yalnız kendi demo kapıları PASS olunca** aç.
7. KAPI-2 verisi birikince `FTMO_V315_SPEED_LAB.md`'yi koş.

**Tek cümle:** v3.15 canlıya **hazırlandı** (kod + testler + .set + operatör paketi),
ama **aktive/derlenmedi** (erişim yok) ve **hız henüz ölçülmedi** — sıradaki adımlar
operatörde ve KAPI-2'de.
