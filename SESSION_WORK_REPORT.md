# AurvexAI — Çalışma Raporu (bu oturum)

**Tarih:** 2026-07-08 · **Branch:** `claude/balance-200-visual-polish-mukmgo` ·
**Testler:** 665 passed · **Live:** OFF (tasarım gereği) · **Gerçek emir:** yok.

Bu oturumda yapılan her şeyin özeti. Üç ana blok: (A) araştırma/edge keşfi,
(B) motor + risk + altyapı değişiklikleri, (C) canlı paper devreye alma.

---

## A. Araştırma — edge keşfi (kanıtla, overfit'siz)

Tüm hipotezler gerçek Binance verisiyle (data.binance.vision arşivi, ~48 coin,
5m→1d, 2.2–2.5 yıl), fee+slippage+funding dahil net, split-half + coin-dışı
holdout ve DSR deflation ile test edildi.

### Ölü kanıtlanan aileler (NO_GO — bir daha zorlanmayacak)
- **Tick/scalp (5m, 15m):** tüm directional aileler net-negatif.
- **Mean-reversion (5m, 15m, 4h):** her timeframe'de net-negatif. Kripto perp
  trend eder, geri dönmez.
- **Maker execution MR** — spread kazansa da brüt sinyal negatif, kurtarmıyor.
- **Cross-coin lead-lag** (BTC→alt) — tek barda zaten fiyatlanmış.
- **Keltner band-walk, hacim-patlaması, seans-açılış momentumu** — chop-bleed.
- **Pyramiding** (kazanana ekleme) — edge'i holdout'ta negatife çeviriyor.
- **Düşük TF taban:** 1h matematiksel taban — maliyet vergisi 1h altında brüt
  edge'i yiyor (5m 0.40R, 15m 0.23R, 1h 0.12R vergi; edge ~sabit).

### Çalışan edge (tek davranışsal edge: momentum/trend)
| Model | net Exp-R | PF | DSR | trades/gün | Verdict |
|---|---|---|---|---|---|
| **Hacim-teyitli 1h momentum (vk=2.5)** | **+0.394R** | **1.60** | **0.95** | ~3 | **ACCEPTED_FOR_PAPER** |
| Hacim-teyitli 4h momentum | +0.857R | 2.35 | 1.00 | 0.3 | ACCEPTED (yavaş) |
| Düz 1h donchian | +0.12R | 1.17 | 0.00 | 9 | RESEARCH_ONLY (DSR düşük) |
| Düz 4h donchian | +0.36R | 1.52 | 0.25 | 1.4 | RESEARCH_ONLY |
| 1h squeeze breakout | +0.05R | 1.13 | 0.07 | 1 | RESEARCH_ONLY |
| Carry (funding) | ~+4%/yıl | — | — | çok yavaş | NEEDS_MORE_DATA |

**En büyük keşif:** kırılım barının hacmini "> k × son 50 barın medyanı" ile
filtrelemek 1h momentum edge'ini **3'e katlıyor** (+0.12 → +0.39R) ve DSR
deflation'ı geçen tek 1h hücresi yapıyor. Nedensel (bar hacmi karar anında
biliniyor, lookahead yok).

### Universe optimizasyonu
- 28 aday coin tarandı; katı iki-kesitli bar (her iki yarı R>0 + holdout tabanı).
- 17 → 28 coin (11 yeni geçti: ENA, FET, GALA, GRT, JUP, SEI, STX, UNI, WIF, WLD, XLM).
- Fleet holdout: +0.116R/t2.01 → **+0.122R/t2.85, +%66 işlem**, konsantrasyon düşük.

---

## B. Motor + risk + altyapı değişiklikleri (branch commit'leri)

| Commit | Ne |
|---|---|
| `76bc6d9` | Multi-strateji spec parametreleri: `:en=` (giriş kanalı), `:atr=` (stop çarpanı) + doğrulanmış 1h donchian edge |
| `9a4b0f9` | Araştırma: 1h taban kanıtı (Phase 6c) |
| `56dac08` | Universe 17→21 (frekans kaldıracı) |
| `6cebcca` | Araştırma: MR diversifier + pyramiding NO-GO (Phase 6e) |
| `9df3c8f` | Universe 17→28 (+%66 işlem) |
| `509b1e2` | Araştırma: MAX_OPEN_TRADES=4 zararlı (Phase 6g portföy sim) |
| `74cbffa` | **Risk retune:** aggressive_paper → 12 slot, %1 risk, 800% exposure |
| `dda262e` | **Friday beyin paneli** + `/api/brain` (read-only karar-zekası) |
| `a910243` | **edge_search_master harness** + hacim-teyitli 1h momentum (ACCEPTED) + `:vk=` spec |
| `fc23a81` | **SQLite thread-local fix** (dashboard concurrency bug) |

### Öne çıkanlar
1. **Risk retune (kritik):** Portföy simülasyonu `MAX_OPEN_TRADES=4`'ün edge'i
   holdout'ta **negatife** çevirdiğini gösterdi (slot doygunluğu + ters seçim).
   → 12 slot, %1 risk, 800% exposure. 12×%1 = ≤%12 eşzamanlı, 10% kill switch
   tabanı korur. Config-only, `decide()` değişmedi, parity sağlam.
2. **edge_search_master.py:** merkezi edge-search harness'ı — strateji × universe
   × TF × maliyet; net/gross ayrımı, PF, Sharpe, **DSR (multiple-trial
   deflation)**, MaxDD, trades/gün, R/gün, holdout, OOS → sıralı leaderboard +
   4-yönlü verdict (ACCEPTED/RESEARCH_ONLY/NO_GO/NEEDS_MORE_DATA).
3. **Friday beyin paneli:** shadow'un ölçtüğü her şeyi tek `/api/brain` +
   dashboard kartında topluyor. **Silinmiş CEO/consensus override GERİ
   GETİRİLMEDİ** (güvenlik kuralı #5) — bilgilendirir, asla veto etmez.
4. **SQLite fix:** dashboard'ın eşzamanlı ~18 API çağrısı tek bağlantıda
   çakışıyordu → thread-local bağlantı. Concurrency smoke-test 0 hata.

### Değişmeyenler (güvenlik kuralları korundu)
- Live 5-kapılı kilit — hiçbir kapı zayıflatılmadı, hiçbiri default açılmadı.
- Paper/live/backtest parity — `decide()` mode-agnostik kaldı.
- Shadow asla hard-veto etmez (advisory).
- Secret yok (kod/git/log/dashboard'da), `.env` gitignored.
- Model kimliği hiçbir commit/artifact'e yazılmadı.

---

## C. Canlı paper devreye alma

- **Önerilen profil** (`.env`):
  ```
  STRATEGIES="donchian_trend@1h/4h:en=48:ch=20:atr=2.0:vk=2.5 donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
  ```
  + 28-coin UNIVERSE_INCLUDE + retune (12 slot / %1 / 800%).
- **Sunucu durumu (son kontrol):** iki container Up (healthy), MULTI-STRATEGY
  modu aktif, 28 coin taranıyor, 16 setup/cycle, cycle 0'da 5 trade açıldı.
- **Bulunan 2 sorun:** (1) dashboard SQLite concurrency hatası → **düzeltildi**
  (`fc23a81`), (2) eski config'ten 11 bayat trade → temiz reset öneriliyor
  (`docker compose down -v` + `up --build`).

---

## Durum bayrakları

- **En iyi pozitif + seri model:** hacim-teyitli 1h momentum (vk=2.5).
- **`PAPER_READY: YES`** (ACCEPTED sleeve, tüm kesitler geçti).
- **`LIVE_READY: NO`** (tasarım gereği — önce forward paper testi).
- **Sıradaki adım:** temiz reset sonrası birkaç gün canlı paper → gerçek R/gün'ü
  backtest'in +1.19'uyla karşılaştır. Paralel: surfacing panelleri (edge
  leaderboard + Telegram kartı + Governor özeti).

Detaylı kanıt: `EDGE_MISSION_REPORT.md` (leaderboard + verdict'ler),
`EDGE_SEARCH_2026-07-05.md` (tüm faz logları), `AURVEXAI_RESEARCH_DOSSIER.md`.
