# Shadow Observer + Risk/Margin Ayrımı + 200 USDT Aggressive Paper — Rapor

> Görev paketi: `AURVEX_CLOUDCHAT_SHADOW_RISK_MARGIN_TASK.md`.
> Mod: `AX_MODE=paper`, `LIVE_ENABLED=false`. **Hiçbir canlı işlem açılmadı, gerçek emir gönderilmedi, secret istenmedi/yazdırılmadı.**
> Bu paket bir **reconcile + verify + measure** paketiydi — sıfırdan inşa değil. İstenen özelliklerin büyük çoğunluğu clean-core'da zaten kurulu ve testliydi; yapılan iş ölçmek, eksik gözlem alanlarını kapatmak ve env'i agresif paper'a almaktı.

---

## 0. Özet (TL;DR)

| Kalem | Durum |
|---|---|
| Baseline test | **346 passed** (temiz) |
| Final test | **361 passed** (346 + 15 yeni gap testi) |
| Env value delta | 3 değer (`update_env.py` ile uygulanır) |
| Fictional key reconciliation | Eşleme tablosu uygulandı, ölü key yazılmadı |
| Risk/margin ayrımı | Doğrulandı: notional önce riskten, leverage sadece margin |
| Exposure-cap kararı | **%200 cap agresif ayarı kısıyor → agresif epoch için %400 öneriliyor** |
| Dynamic leverage / shadow / TA / TP-SL | İNŞA EDİLMEDİ — zaten var, ÖLÇÜLDÜ |
| `risk_modulation_enabled` | **false** (değişmedi) |
| `score_as_gate` | **false** (değişmedi) |
| `shadow_apply` (SHADOW_MODE=observer) | **false** (değişmedi) |
| `READY_FOR_AGGRESSIVE_PAPER` | **YES** (env uygulanınca; cap kararı operatöre) |
| `READY_FOR_LIVE` | **NO** |

---

## 1. Güncellenen Env (gerçek config key'leri)

`scripts/update_env.py` (yeni, güvenli, idempotent, dry-run default) ile uygulanır. **Sadece 3 değer değişir:**

| Gerçek key | Eski | Yeni |
|---|---|---|
| `INITIAL_PAPER_BALANCE` | 1000 | **200** |
| `RISK_PCT` | 0.5 | **2.0** |
| `MAX_DAILY_LOSS_PCT` | 3.0 | **10.0** |
| `EPOCH_LABEL` | wave3 | **aggr200_v1** (öneri; reset ile yeni temiz epoch) |

Zaten doğru (dokunulmadı): `AX_MODE=paper`, `LIVE_ENABLED=false`, `MAX_OPEN_TRADES=4`, `DASHBOARD_PORT=5000`, `SHADOW_APPLY=false`, `RISK_MODULATION_ENABLED=false`, `SCORE_AS_GATE=false`, `GLOBAL_RANKING=true`, `RANK_KEY=edge`, `LEVERAGE_POLICY=efficient`.

> Not: `config.py` default'ları (1000/0.5/3.0) ve `.env.example` **bilerek değiştirilmedi** — güvenli dökümante default budur. Agresif değerler bir *deployment seçimi* olarak `.env`'e (gitignored) yazılır; test suite default'larla çalışmaya devam eder.

### Reconcile edilen fictional key'ler

Görev dosyasındaki isimler `config.py`'nin okuduğu gerçek key'lerle eşleşmiyordu. Körlemesine eklenseydi **config.py'nin hiç okumadığı ölü key'ler** yazılır, hiçbir şey değişmezdi. `update_env.py` **yalnız gerçek key'leri** yazar:

| Görev dosyası | Gerçek key | Aksiyon |
|---|---|---|
| `EXECUTION_MODE=paper` | `AX_MODE` | zaten paper — dokunulmadı |
| `LIVE_TRADING_ENABLED=false` | `LIVE_ENABLED` | zaten false — dokunulmadı |
| `DAILY_MAX_LOSS_PCT` | `MAX_DAILY_LOSS_PCT` | **isim farkı düzeltildi** |
| `RISK_PROFILE=aggressive_paper` | *(yok)* | yazılmadı — agresyon = `RISK_PCT` |
| `MIN_RISK_PCT` / `MAX_RISK_PCT` | *(yok)* | yazılmadı — bant `RISK_PCT × modülasyon clamp [0.5,1.5] = [1.0,3.0]` |
| `SHADOW_MODE=observer` | `SHADOW_APPLY=false` | zaten false — dokunulmadı |
| `SHADOW_AUTO_APPLY=false` | `SHADOW_APPLY` | zaten false — dokunulmadı |

`update_env.py` güvenlik rayları: ALLOWED_KEYS dışında / secret key **yazmayı reddeder**; `RISK_PCT∈(0,5]`, `MAX_DAILY_LOSS_PCT∈(0,100]`, balance>0, `MAX_OPEN_TRADES≥1` doğrular; `AX_MODE=live` veya `LIVE_ENABLED=true` **asla** set etmez; secret değer (token/key) satırlarına **dokunmaz, okumaz, yazdırmaz**; `--apply`'tan önce `.env.backup.<timestamp>` alır; dry-run default'tur.

---

## 2. 200 USDT Engine-Accurate Örnek (gerçek `RiskManager` çıktısı, multiplier 1.0)

Risk bütçesi = `200 × 2/100 = 4.00 USDT`. Günlük kayıp limiti = `200 × 10/100 = 20.00 USDT`.

| Senaryo | Notional | Lev (efficient) | Margin | Full SL |
|---|---|---|---|---|
| Std stop %2.00 | 187.79 | 10 | 18.78 | **−4.00 (−1R)** |
| Std stop %2.50 (max) | 152.09 | 10 | 15.21 | **−4.00 (−1R)** |
| Buğra %4.49 | 86.58 | 10 | 8.66 | **−4.00 (−1R)** |
| Std min %0.30 | 400.00\* | 10 | 40.00 | −1.72 (exposure-cap clipped) |

`*` %0.30 stop'ta tam-boy notional ~930 USDT olurdu; **tek trade bile** `MAX_PORTFOLIO_EXPOSURE_PCT=200` (400 USDT) tavanına çarpıp 400'e kırpılıyor → max loss 4.00 değil 1.72. Bu, exposure-cap'in agresif ayarda ne kadar erken bağladığının ilk kanıtı.

Tüm uncapped stop mesafelerinde full SL **tam −1.0R** (eski −1.43R değil): sizing fee+slippage dahil (`rt_cost_frac=(0.045+0.02)/100×2=0.0013`), `position_notional = risk_amount/(stop_frac+rt_cost_frac)`. Test: `test_aggressive_paper_200.py`, `test_cost_inclusive_risk.py`.

---

## 3. Risk/Margin Ayrımı — Nasıl Doğrulandı

**Ayrık iki adım (`risk.py::evaluate`):**
1. **Notional ÖNCE riskten** boyutlanır: `position_notional = risk_amount/(stop_frac+rt_cost_frac)`. Leverage bu adıma girmez.
2. **Margin SONRA** `_solve_leverage` ile: `efficient` politikası likidasyon-güvenli en yüksek kaldıracı seçip kilitli margin'i minimize eder. `max_loss` kaldıraçtan **bağımsız sabit**.

**Leverage PnL/risk invariant testi (yeni `test_leverage_pnl_invariant.py`):** Aynı notional/entry/stop için `max_leverage ∈ {3,5,10,15}`:

| max_lev | lev | notional | margin | max_loss | liq |
|---|---|---|---|---|---|
| 3 | 3 | 187.79 | 62.60 | **4.00** | 67.17 |
| 5 | 5 | 187.79 | 37.56 | **4.00** | 80.50 |
| 10 | 10 | 187.79 | 18.78 | **4.00** | 90.50 |
| 15 | 15 | 187.79 | 12.52 | **4.00** | 93.83 |

`max_loss` ve `notional` her kaldıraçta **birebir aynı**; yalnız `margin` düşüyor, `liq` entry'ye yaklaşıyor. PaperExecutor seviyesinde de aynı fill → aynı realized PnL (15x canlı default'u değiştirmeden, testte `cfg.max_leverage` parametrize edilerek doğrulandı; `MAX_LEVERAGE=10` default'a dokunulmadı). Likidasyon-güvenlik invariantı (`liq_safety_buffer=2.0`) kodda zorlanıyor; %2 stop için liq-ceiling = `floor(1/(2.0×0.02+0.005)) = 22`, yani 3–15x hepsi güvenli.

> **Düşük kaldıraç gereksiz margin kilitliyor mu?** Hayır — `efficient` en yüksek güvenli kaldıracı seçer. `conservative` legacy.

---

## 4. Exposure-Cap Kararı (KRİTİK ÖLÇÜM)

200 USDT + %2 risk'te **bağlayıcı limit free margin DEĞİL, notional exposure cap.** Gerçek `RiskManager` ile 4 sıralı tam-boy %2 trade (`MAX_PORTFOLIO_EXPOSURE_PCT=200` → 400 USDT tavan):

| Trade | Notional | clip_reason | room (önce) |
|---|---|---|---|
| 1 | 187.79 | none | 400.00 |
| 2 | 187.79 | none | 212.21 |
| 3 | **24.41** | **exposure_cap** | 24.41 |
| 4 | **REJECT** | **exposure_cap** | 0.00 |

→ Toplam notional 400 (cap'e yapışık), **toplam margin sadece 40/200** — yani margin'in dibi var ama cap dolu. Agresif ayarda **~2.13 tam-boy trade** sığıyor; 4 slot'un 2'si boşa gidiyor.

**Cap %400'e (800 USDT) çıkınca:** 4 trade de tam boy (187.79×4=751 notional), **margin util %37.6**, free margin 125/200. Hiç clip yok.

**KARAR (öneri):** Agresif paper epoch'u için `MAX_PORTFOLIO_EXPOSURE_PCT`'yi **%400'e** çıkar (4 tam-boy %2 trade'in ihtiyacı %375.6; %400 yuvarlak ve güvenli). Margin hâlâ balance'ın yarısının altında, likidasyon-güvenlik invariantı korunuyor. Bu **bir env değişikliği** (`update_env.py --max-exposure-pct 400`); risk_pct/leverage'a dokunmadan yapılır. Default `.env.example`'da %200 bırakıldı (muhafazakâr); karar operatörün. Test: `test_exposure_cap_aggressive.py` her iki senaryoyu da pinler.

---

## 5. Missed-Opportunity Ayrımı (no_free_margin vs max_open_trades vs exposure_cap)

Reject-reason'lar **gözlem amaçlı** (observe-only) ayrıştırıldı — karar yolu değişmedi:
- **`no_free_margin` / `exposure_cap` / `min_notional`:** risk-gate reject'leri `source='rejected'` shadow olarak izleniyor. Reject reason'ı **additive yan tablo** `shadow_reject_reason(shadow_id, reason)` ile saklanıyor (shadows tablosunun kolon düzeni değişmedi → mevcut pozisyonel insert'ler bozulmadı). Dashboard bunları normalize edip **win% + avg_r** ile gösteriyor.
- **`max_open_trades`:** Bu sinyaller ALLOW'du (tradeable) ama slot bulamadı → **paper** shadow popülasyonunda izlenir, rejected değil. Bu yüzden sayımı funnel'ın `ranked_out` (qualified-but-no-slot) toplamından gelir (`missed_max_open_trades_n`). Bu fark raporda şeffaf.

Canlı dashboard çıktısı (örnek, seed'li):
```
missed_opportunity_resolved_n : 3
missed_no_free_margin_n       : 2   (win% 50.0, avg_r 0.20)
missed_exposure_cap_n         : 1   (win% 100.0, avg_r 1.40)
missed_min_notional_n         : 0
missed_max_open_trades_n      : 0   (funnel ranked_out)
```
Test: `test_dashboard_aggressive_fields.py` (reason roundtrip + win%/avg_r).

---

## 6. Shadow (Observer-First)

- **Nasıl bağlı:** İki popülasyon — `paper` (açılan/tradeable) + `rejected` (score≥45 ama açılmayan). `(symbol, side, setup_type, signal_bar_ts)` ile dedup. Stop motorun normalize ettiği gibi normalize edilir (proxy R ↔ paper R ayrışmaz).
- **Otomatik karar veriyor mu? → HAYIR.** `SHADOW_APPLY=false` ve `RISK_MODULATION_ENABLED=false` iken sizing **byte-identical** (golden `test_no_behavior_change_T1.py`). Shadow bir trade'i REJECT'e çeviremez; yetki aşamalı (0–50 gözlem / 50–100 soft score delta / 100+ risk multiplier) ve hiçbiri kapalı flag'lerde sizing'e dokunmaz.
- **Gerçek-exit mi proxy mi:** `update()` TP1-vs-SL proxy (net-of-cost R). `ladder_replay()` tam-ladder (TP1→BE→TP2→TP3 + runner) offline replay. İkisi de DB'yi değiştirmez.
- **Eklenen alan/tablo:** `shadow_reject_reason` yan tablosu (yalnız gözlem; reject reason ↔ outcome). Mevcut shadow şeması ve testleri korundu.
- **Öneriler nerede:** `/api/shadow` (stage + setup avg_r + score_delta/risk_multiplier önerisi, `apply_automatically:false`), `/api/score_validity` (PREDICTIVE/ANTI_PREDICTIVE/INSUFFICIENT verdict + `risk_modulation_enabled`).

Doğrulanan mevcut testler: `test_shadow_learner.py`, `test_shadow_blockB.py` (no-veto + epoch filter + `test_shadow_cannot_change_position_size`), `test_shadow_dedup.py`, `test_shadow_epoch_isolation.py` — hepsi yeşil.

---

## 7. Dashboard'a Eklenen Alanlar (`/api/portfolio_metrics`)

`risk_pct`, `max_daily_loss_pct`, `daily_realized_pnl`, `daily_loss_budget_usdt`, `daily_loss_used_pct`, `active_strategy_profile`, `leverage_policy`, `max_leverage`, `max_portfolio_exposure_pct`, `risk_modulation_enabled`, `max_loss_if_all_sl_usdt` (= `open_risk_usdt`'nin açık-isimli aliası: "tüm açık trade SL olursa max loss"), `missed_opportunity_by_reason`, `missed_no_free_margin_n`, `missed_exposure_cap_n`, `missed_min_notional_n`, `missed_max_open_trades_n`. `risk_modulation_enabled=false` iken multiplier 1.0 raporlanır.

---

## 8. TA Replay/Ablation + TP/SL Karşılaştırma

**İnşa edilmedi — ölçüldü** (direktif #4). Offline backtest (`python main.py backtest`, sentetik veri, 4 sembol × 1500 bar):

| Metrik | Değer |
|---|---|
| total_trades | 70 |
| winrate | 48.57% |
| expectancy | +0.42 USDT (**+0.086R**) |
| profit_factor | 1.161 |
| max_drawdown | 41.59 |
| TP1→TP2 geçiş | 66.7% |
| TP2→TP3 geçiş | 50.0% |
| BE closes | 22 / SL closes | 36 / TP closes 11 |
| avg_margin_used | 54.73 / leverage_dist | {10: 70} |

> **Önemli:** Bu sentetik veri — TA ablation (EMA hizası/eğimi vs Ichimoku vs Supertrend vs ATR-percentile vs session-VWAP) ve TP/SL model karşılaştırması (scale-out vs trailing vs time-stop) **gerçek OOS veride** anlamlı olur. Araç hazır (`backtest.py` + `walkforward.py`, `funding_rate_8h` real-data run'da set edilir); yeni gösterge/exit **default'a sessizce eklenmedi**. Kural korundu: aynı bilgiyi veren göstergeler alternatif olarak yarışır, kazanan kalır. TP3 tüm pozisyonu kapatıyorsa TP3-sonrası stop taşıma anlamsız — yalnız `RUNNER_FRAC>0` ile anlamlı (`test_runner_trailing.py`). Bu, bir sonraki forward-research adımı olarak operatöre bırakıldı.

---

## 9. Test Sonuçları

- **Baseline:** 346 passed.
- **Final:** **361 passed** (yeni 15 test).
- Yeni dosyalar: `test_aggressive_paper_200.py` (200 USDT sizing, full SL=−1R, daily=20), `test_leverage_pnl_invariant.py` (3/5/10/15 max_loss sabit), `test_exposure_cap_aggressive.py` (cap %200 bağlıyor / %400 açıyor), `test_dashboard_aggressive_fields.py` (yeni alanlar + reason breakdown + modülasyon=false→1.0).
- Mevcut risk/shadow/dashboard/parity testleri (cost_inclusive, efficient_leverage, slot_aware, risk_modulation, no_behavior_change_T1, paper_live_parity, shadow_*) yeşil kaldı.
- Offline `python main.py demo` uçtan uca tamamlandı (40 cycle).

---

## 10. Docker / Health (Termius — tek-tek, `&&` yok)

```
1) cp .env ".env.backup.$(date +%Y%m%d_%H%M%S)"
2) python3 scripts/update_env.py --paper-balance 200 --risk-pct 2.0 --daily-loss 10.0 --epoch-label aggr200_v1 --dry-run
3) python3 scripts/update_env.py --paper-balance 200 --risk-pct 2.0 --daily-loss 10.0 --epoch-label aggr200_v1 --apply
4) python3 scripts/update_env.py --max-exposure-pct 400 --apply
5) python3 main.py reset
6) docker compose up -d --build
7) curl -s http://localhost:5000/health
8) curl -s http://localhost:5000/api/portfolio_metrics
9) curl -s http://localhost:5000/api/shadow
10) docker compose logs --tail=80 engine
11) docker compose logs --tail=80 dashboard
```

> Adım 4 (exposure cap %400) opsiyonel ama agresif ayarın 4 slotu da kullanması için **önerilir** (Bölüm 4). Adım 5 `reset` **geri dönüşsüz**: açık paper trade + ledger 200 USDT'ye sıfırlanır, **shadow history korunur**. Docker servis adları: `engine`, `dashboard` (port 5000). Kontroller: `portfolio_metrics` → `risk_pct=2.0`, `max_daily_loss_pct=10.0`, `balance=200`, `risk_modulation_enabled=false`, `max_leverage=10`; `/api/status` → `live_enabled:false`.

---

## 11. Final Durum

- `SHADOW_MODE=observer` (= `SHADOW_APPLY=false`) ✅
- `RISK_MODULATION_ENABLED=false` ✅
- `SCORE_AS_GATE=false` ✅
- Shadow otomatik karar veriyor mu? → **HAYIR**
- Negatif expectancy'de risk artırılmadı; agresyon yalnız `RISK_PCT` + (kapalı) modülasyon clamp ile sınırlı.
- Live trading açılmadı, gerçek emir gönderilmedi, secret istenmedi/yazdırılmadı.
- **`READY_FOR_AGGRESSIVE_PAPER: YES`** (env uygulandığında; exposure-cap kararı operatöre)
- **`READY_FOR_LIVE: NO`**
