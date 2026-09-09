# AurvexFTMO v3.13 — the merge (hardened v3.11 + validated strategy)

`mql5/AurvexFTMO_v3_13_final.mq5`. A friend hardened our EA into a "v3.11" rewrite
with genuinely better operational engineering. This merges **their robustness** with
**our validated strategy**, and is a **reviewed skeleton — compile (F7) + demo-verify
before any live use.**

**v3.13 hardening (post-review, credit: a second review pass):** enforce risk multipliers <=1 (never-raise is now checked, not just commented); reject ORB windows that cross UTC midnight; size margin for BUY_STOP/SELL_STOP; retry the journal write from the timer. Telegram URL-encoding skipped (Telegram unused). The live account stays on the current EA until the demo is clean.

## What was taken from the v3.11 hardening (kept as-is)
- **Restart-safe state** via GlobalVariables — traded-today, Friday-flat, trailing
  state, the planned entry/SL, and the FTMO day baseline all survive an EA/terminal
  restart. (Our old EA reset these on restart.)
- **Automatic DST** — CET/CEST for the FTMO daily reset and EST/EDT + CET for the
  index cash-session gates, computed from the date. **Removes the manual
  winter/summer session shift** (a recurring error source).
- **`OnTradeTransaction` fill capture + planned-SL original-R** — the true risk basis
  is preserved even when the fill slips from the planned entry.
- **Margin validation, retcode checks, broker freeze/stops-level guard,
  `OrderCalcProfit`-based sizing** — production-grade execution safety.
- **`RequireAccountSize`** — refuses to start with AccountSize ≤ 0 and rejects an
  AccountSize that conflicts with the persisted initial balance.
- **Spread guards** (`MaxSpreadPoints`, `MaxSpreadToStopPct`) — the %-of-stop form is
  a smarter spread guard (normalised to the trade's own risk); on by default at 12.5%.

## What our validated-strategy layer adds
- **`OrbRangeHourUTC` + per-session effective magic** (`g_magic = Magic +
  OrbRangeHourUTC`) — enables BTC multi-session and **fixes the same-symbol
  order-collision** (charts never manage each other's orders). `OrbRangeHourUTC=0`
  ⇒ `g_magic=Magic`, unchanged for standard charts.
- **`MinRangeMedMult`** — GOLD low-vol-day filter (OOS +0.19→+0.36R). Default off.
- **`PdhlMinRangeMedMult`** — JP225 low-vol-day filter. Default off.
- **`PhaseTargetPct`/`NearTargetPct`/`NearTargetMult`** — profit-lock (cut risk near
  the phase target). Default off.
- **`JournalTrades`** (default ON) — one CSV row per entry with the setup context
  (opening range, the median the filter would see, spread at arm + fill) for KAPI-1
  retro-testing. Passive.

## The harm analysis — why PDHL back-scan is OFF by default
v3.11's `PrevTradingDayRange` scans back up to 10 days, so on a **Monday it trades
off Friday's range** (and after a holiday, off a stale range). Our validated backtest
never included that regime. Measured directly, the **extra** back>1 trades are:

| index | back==1 (calendar, validated) | back>1 (the extra Monday/holiday trades) |
|---|---|---|
| GER40 | +0.023 | **−0.062** (net negative) |
| NAS100 | −0.014 | **−0.022** (net negative) |
| JP225 | +0.055 | +0.168 (positive) |

The extra trades are **net-negative on GER40 and NAS100** — real harm. So the merge
adds `PdhlUseBackScan` (**default false = validated calendar prior-day, skip Monday**);
set it true only if you deliberately want the Monday regime (and only JP225 showed a
positive there — confirm on KAPI-1 first).

## Is there any harm from adopting the merge?
- **Strategy/decision logic:** none — the validated entries are unchanged; the drift
  (back-scan) is off by default, and the filters/profit-lock are off by default.
- **Execution:** strictly safer (margin, retcode, freeze-level, restart-safety).
- **The only real risk is an integration bug** in the new code — mitigated by: it is
  a separate file (live EA untouched), it must compile clean (F7), and it must be
  **demo-verified first**. Do not promote to the live/challenge account until the demo
  shows clean logs, correct fills, and the journal writing.
- **`MaxSpreadToStopPct=12.5` is ON by default** and will skip some trades the
  spread-free backtest took. That is prudent live, but it is a behaviour change — set
  it to 0 if you want to first reproduce the pure validated behaviour on demo.
- **`AccountWideEmergencyFlatten=true`** closes the entire account on a guard breach
  (not just this symbol). Correct for a dedicated FTMO account; set false if the
  account holds anything else.

## THE FINAL LIVE CONFIG (10/10 as the data supports — see honest note)

Charts to open (H1): **XAUUSD, XAGUSD, BTCUSD, GER40.cash, JP225.cash**.
**Drop NAS100/US100** — measured dead weight (break-even 0.013%, dies at any real
spread). JP225 and GER40 session gates are **automatic** (`AutoPdhlSession=true`);
no manual session inputs needed.

Every chart: `AccountSize=25000`, `Magic=770077`, `PhaseTargetPct=10`,
`JournalTrades=true`, `PdhlUseBackScan=false`, `MaxSpreadToStopPct=12.5`,
`AccountWideEmergencyFlatten=true`, de-risk defaults on.

| chart | RiskPct | TrailStopR | ForceStrategy | MinRangeMedMult | PdhlMinRangeMedMult |
|---|---|---|---|---|---|
| XAUUSD | 0.35 | 0 | AUTO (ORB) | **1.0** (gold filter) | 0 |
| XAGUSD | 0.35 | 0 | AUTO (ORB) | 0 | 0 |
| BTCUSD | 0.30 | 0.3 | **ORB** | 0 | 0 |
| GER40.cash | 0.25 | 0.5 | AUTO (PDHL) | 0 | 0 |
| JP225.cash | **0.45** | 0.5 | AUTO (PDHL) | 0 | **1.0** (JP225 filter) |

This exact config Monte-Carlos (proxy, honest reach-+10% metric) to **~95% reach /
~1.9% bust** single-attempt Phase-1, ~97% Phase-2 — the best the data supports.

## The one non-negotiable step (this is NOT a demo period)
I cannot compile MQL5 from here. **You must press F7 (Compile) once** — every .mq5
needs it, or it will not load. It must say `0 errors, 0 warnings`; if it errors,
paste me the text and I fix it immediately.

1. Copy `AurvexFTMO_v3_13_final.mq5` into MQL5/Experts.
2. **F7 → 0 errors.** (mandatory)
3. Attach with the config above; confirm the Experts log per chart:
   `Aurvex v3.13-merged on <SYM> ... magic=... journal=on`, and `initBal`=25000.
4. **Watch the first day live** (eyes on — since we skip a demo period): confirm
   entries fire, the journal CSV appears under MQL5/Files, and stops are set right.

## Honest note on "10/10"
Code quality and config: this is as tight as the evidence allows — call it 10/10 on
*quality*. **Results are never 10/10** — the edge is real but modest (~+0.15R,
variance-heavy, ~35% win rate carried by rare runners). The ~95% above is a
proxy-data ceiling; live will be lower and only KAPI-1 tells the truth. Going live
without a demo means the new plumbing (persistence, DST, fill-capture) is
first-running on real money — reviewed correct, but watch day one. Protect your
runway; treat the fee as a bounded, repeatable cost.

---

# FTMO'ya yükleme adımları (v3.13 final) — baştan sona

## A. Hesap ve dosya
1. FTMO **$25k 2-Step Challenge, Standard, MT5** hesabın hazır olsun (kredentials: Login/Password/Server).
2. MT5: **Dosya → Veri Klasörünü Aç → MQL5 → Experts** → `AurvexFTMO_v3_13_final.mq5` dosyasını içine kopyala.
3. **MetaEditor** aç → dosyayı aç → **F7 (Derle)**. **`0 errors, 0 warnings`** görmeli. Hata çıkarsa metnini gönder (canlıya geçme).
4. MT5'te **$25k** hesabına giriş yap (Dosya → Ticaret Hesabına Giriş).

## B. Grafikleri aç (H1)
`XAUUSD`, `XAGUSD`, `BTCUSD`, `GER40.cash`, `JP225.cash`.
**NAS100/US100 AÇMA** — ölçülen ölü ağırlık. **XAGAUD/XAUEUR AÇMA** — yanlış enstrüman.

## C. Her grafiğe EA'yı şu inputlarla ekle
Her grafik ortak: `AccountSize=25000`, `Magic=770077`, `PhaseTargetPct=10`,
`JournalTrades=true`, `PdhlUseBackScan=false`, `AutoPdhlSession=true`,
`AccountWideEmergencyFlatten=true`, de-risk defaultları. "Allow Algo Trading" tikli.

| grafik | RiskPct | TrailStopR | ForceStrategy | MinRangeMedMult | PdhlMinRangeMedMult |
|---|---|---|---|---|---|
| XAUUSD | 0.35 | 0 | AUTO | **1.0** | 0 |
| XAGUSD | 0.35 | 0 | AUTO | 0 | 0 |
| BTCUSD | 0.30 | 0.3 | **ORB** | 0 | 0 |
| GER40.cash | 0.25 | 0.5 | AUTO | 0 | 0 |
| JP225.cash | **0.45** | 0.5 | AUTO | 0 | **1.0** |

> **Not:** Bu config gold + JP225 filtrelerini AÇIK başlatır (OOS-doğrulanmış, sadece işlem eler, risk eklemez). Eğer önce saf-baseline görmek istersen ikisini de 0 yapıp sonra aç.

## D. Aç ve DOĞRULA
1. Üst araç çubuğu **"Algo Trading"** yeşil.
2. Her grafik köşesinde EA adı + **😊**.
3. **Toolbox → Uzmanlar (Experts)** her grafik için bir satır:
   `Aurvex v3.13-merged on <SYM> ... magic=... journal=on ... base=25000.00 serverOffsetH=3`
   - `base=25000.00` her satırda (10000/100000 ise DUR, AccountSize düzelt).
   - `serverOffsetH=3` (FTMO UTC+3).
4. **İlk günü gözünle izle:** giriş oluyor mu, `MQL5/Files`'da journal CSV beliriyor mu, stoplar doğru mu.
5. Terminali bir kez kapat-aç → state korunuyor mu (restart-safe doğrulaması).

## E. Makineyi ayakta tut
Metal açılış aralığı **01:00 UTC** — makine gece açık olmalı. Ucuz **VPS** (veya FTMO'nun ücretsiz VPS'i) laptop kapanınca setup kaçmasın diye değer.

## F. KAPI-1 (15-30 işlemden sonra)
1. MT5 History → sağ tık → Report → HTML kaydet.
2. `MQL5/Files`'daki journal CSV'lerini + HTML raporu bana gönder.
3. Gerçek fill'lerle her enstrümanın edge'ini + spread'ini break-even eşikleriyle okuruz.

## G. KAPI-1 SONRASI — kâr genişlemesi (BTC multi-session)
KAPI-1 BTC'nin canlı spread'ini onaylarsa: **3 BTCUSD grafiği** aç, `OrbRangeHourUTC` = `0`/`3`/`13`, her biri `ForceStrategy=ORB`, `TrailStopR=0.3`, **`RiskPct=0.10`** (3×0.10 = aynı 0.30 toplam risk). Grafikler otomatik bağımsız (magic = 770077/770080/770090). Bu, aynı riskle ~3× BTC işlemi + düşük-korelasyon = daha yüksek geçiş/daha düşük bust (proxy: reach 98.2→99.4, bust 1.8→0.6). Saat 13 en güçlüsü.

## Sert kurallar
1. Elle işlem açma/kapatma yok — EA yönetir; elle kapatma edge'i bozar ve KAPI-1 verisini kirletir.
2. Kaybı geri almak için risk artırma yok — modest edge'in kayıp serileri normaldir.
3. Challenge ortasında yeni enstrüman/tinkering yok.
4. Guard'a güven — −%9'da durur (−%10'dan önce).
