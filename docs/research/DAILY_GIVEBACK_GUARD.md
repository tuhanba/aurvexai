# Daily give-back guard — intraday equity trailing lock (2026-07-20)

Owner ask: *"günlük hedefe ulaşmaya çalışırken +%8 yaptın diyelim, +%7'den
negatife geri de dönebilir. Bunu engellemek istiyorum."* — a day can peak, then
bleed the gain back to flat or negative before anything banks it. Prevent that.

## The gap this closes

The deployed daily profit **target** (adaptive 8%→10%) only fires **AT the
target** — it flattens the day the moment intraday MTM gain reaches the target.
A day that peaks **below** the target (e.g. +6% in chop, target 8%) and then
reverses is **completely unprotected**: the target never triggers, and the −10%
kill is far away, so the peak can bleed all the way back. That is exactly the
"+8% → +7% → negative" give-back the owner described.

## The guard

A per-day **high-water trailing lock**, independent of the target:

- Track the intraday peak of today's gain (equity − day-open baseline),
  persisted in DB meta (survives restarts, resets at the day rollover).
- **Arm** once the peak clears `DAILY_GIVEBACK_ARM_PCT` % of day-open equity
  (default 4%) — so tiny wiggles never trigger; only a *meaningful* peak arms.
- **Bank + lock** the day when the live gain gives back more than
  `DAILY_GIVEBACK_FRAC` of that armed peak (default 0.33 → banks at 67% of the
  peak). On a +8% peak that means flattening on the way down through +5.36%.

It uses the **same MTM flatten primitive** as the target (parity-safe: paper +
armed live reduce-only) and sets the same day-lock, so entries lock for the rest
of the logical day exactly like a target hit. Reason code: `DAILY_GIVEBACK`.

**It never caps a runner.** A true runner day keeps making new peaks, so the
gain stays near the peak and the guard never fires — it rides to the target.
The guard only bites when the day **tops and reverses**, which is precisely the
event the owner wants to stop.

## Does it help or hurt? (data, not intuition)

Swept arm × give-back on the real 5-leg OOS stream (1754 days, 5.69y, day-block
bootstrap) under the deployed adaptive target + −10% kill
(`scripts/giveback_guard_sweep.py`):

```
                    config  medCAGR%  medMaxDD%    MAR  avgDayR%  guard-fired
    baseline (no giveback)     -34.5       97.6  -0.35    -0.016      --
         arm3% giveback25%     -27.3       96.3  -0.28    +0.015      61 (3%)
         arm4% giveback33%     -30.4       97.1  -0.31    -0.001      37 (2%)
         arm5% giveback50%     -33.3       97.3  -0.34    -0.013      16 (1%)
```

- Every armed/tight cell **improves** MAR and average day-return vs baseline;
  the tighter early-arm cells (arm 3–4%, give-back 25–33%) are best.
- It fires on only **~2–3% of days** — a rare, surgical bank, not a frequent cap.
- Unlike TP-laddering (−37% expectancy, `the exit-mechanism note`), the guard is
  expectancy-**neutral-to-positive** because it preserves the runner tail.

**Crucial caveat (honest):** this closed-R proxy **understates** the benefit.
It builds the intraday path from *closed-trade* R only, so it cannot see the
scariest give-back — an **open** winner marking to +8% then marking back to
negative before it closes. That unrealized round-trip is invisible to closed R
but is exactly what the guard catches live. So the true benefit is **larger**
than the table shows. The paper window (which logs every guard event and the
subsequent path) is the definitive arbiter.

## Deployment

Enabled in the paper block (`apply_fast_paper_env.py`) at the data-informed
conservative setting **arm 4% / give-back 33%** — paper is where a safety
feature gets validated. Defaults in code are **OFF** (project rule: nothing
defaults on). Tune or disable with one command:

```
python scripts/update_env.py --giveback-arm-pct 4 --giveback-frac 0.33 --apply
python scripts/update_env.py --no-giveback-guard --apply
```

Reason code `DAILY_GIVEBACK` appears on the closed trade and in the Telegram
alert (🛟 "Geri-verme koruması devrede"). Config-gated, parity-safe, reversible.
