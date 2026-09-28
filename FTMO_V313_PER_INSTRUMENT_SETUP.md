# v3.13 — enstrüman enstrüman tam kurulum (giriş/çıkış saatleri dahil) — KAPI-1 SONRASI

> **KAPI-1 (2026-09-28):** BTCUSD **çıkarıldı** (komisyon öldürüyor — bkz.
> `FTMO_KAPI1_FINDINGS.md` / `FTMO_V313_INPUTS.md`). Evren **4 enstrüman**.
> Risk **1.3×** (kullanıcı tercihi; 1.0× taban parantezde).

EA: `AurvexFTMO_v3_13_final.mq5`. Hepsi **H1 (1 saatlik)** grafik. Saatler **UTC**.
FTMO sunucusu UTC+3 ama EA otomatik çeviriyor — sen UTC düşün, log `serverOffsetH=3` göstermeli.

**Ortak çıkış kuralları (4 enstrümanda da aynı):**
- **Stop-loss** vurursa (aşağıda her enstrümanın stopu yazılı).
- **Trailing stop** (varsa) tetiklenirse.
- **Seans kapanışı: 00:00 UTC** — yeni UTC günü başında EA pozisyonu kapatır (flatten).
- **Cuma 20:00 UTC** — hafta sonu için her şeyi kapatır; Cmt/Pazar işlem yok.
- **Loss guard** −%9'da (equity) her şeyi kapatıp durur.

---

## 1) XAUUSD (Altın) — ORB
- **Strateji:** Opening Range Breakout.
- **Aralık:** 00:00–01:00 UTC (ilk saat) yüksek/alçak.
- **Giriş:** 01:00 UTC'den sonra, aralığın **ilk kırılımında** (yukarı kırarsa buy-stop, aşağı kırarsa sell-stop). Bir taraf dolunca diğeri iptal. Aralık armlamadan önce kırıldıysa → o gün pas (no-chase).
- **Filtre (AÇIK):** günün aralığı son 20 günün medyanının altındaysa o gün pas (düşük-vol-günü filtresi). Log: `minRangeMult=1.00`.
- **Stop:** aralığın karşı ucu (long → aralık alçağı; short → aralık yükseği).
- **Trailing:** YOK (0) — fat-tail koşucusunu seans kapanışına kadar bırak.
- **Çıkış:** 00:00 UTC seans kapanışı / stop / Cuma 20:00.
- **Girişler:**
  `AccountSize=25000, RiskPct=0.46, TrailStopR=0, ForceStrategy=AUTO, MinRangeMedMult=1.0, PdhlMinRangeMedMult=0, PhaseTargetPct=10` — gerisi default. (RiskPct 1.3×; taban 0.35.)

## 2) XAGUSD (Gümüş) — ORB
- **Strateji / aralık / giriş / stop / çıkış:** Altınla AYNI (00:00–01:00 UTC aralık, 01:00 UTC sonrası kırılım, stop = karşı uç, trail yok, 00:00 UTC kapanış).
- **Filtre:** KAPALI (gümüşte fayda yok — sadece altında var). `minRangeMult=0.00`.
- **Girişler:**
  `AccountSize=25000, RiskPct=0.46, TrailStopR=0, ForceStrategy=AUTO, MinRangeMedMult=0, PdhlMinRangeMedMult=0, PhaseTargetPct=10` — gerisi default. (RiskPct 1.3×; taban 0.35.)

## 3) GER40.cash (DAX) — PDHL
- **Strateji:** Previous-Day High/Low breakout (dünün — takvim önceki günün — yüksek/alçağı).
- **Giriş SAATİ (otomatik, DST'li):** sadece Frankfurt nakit seansında armlar:
  - **Yaz (CEST): 07:00–15:30 UTC**
  - **Kış (CET): 08:00–16:30 UTC**
  - `AutoPdhlSession=true` bunu otomatik yapar — elle saat girme.
- **Giriş:** bu pencerede, dünün aralığının ilk kırılımında. Pazartesi Pazar barı olmadığı için **Pazartesi işlem yok** (doğrulanmış davranış; `PdhlUseBackScan=false`).
- **Stop:** ATR(14) × 1.5.
- **Trailing:** 0.5R.
- **Çıkış:** 00:00 UTC kapanış / stop / 0.5R trailing / Cuma 20:00. (Seans kapanınca pozisyon stop+trail korumasıyla tutulur, gece flatten 00:00 UTC'de.)
- **Girişler:**
  `AccountSize=25000, RiskPct=0.33, TrailStopR=0.5, ForceStrategy=AUTO, MinRangeMedMult=0, PdhlMinRangeMedMult=0, PhaseTargetPct=10` — gerisi default. (RiskPct 1.3×; taban 0.25.)

## 4) JP225.cash (Nikkei) — PDHL
- **Strateji:** Previous-Day High/Low breakout.
- **Giriş SAATİ:** sadece **00:00–06:00 UTC** (Tokyo nakit; Japonya DST yok, sabit). Otomatik.
- **Giriş:** bu pencerede dünün aralığının ilk kırılımında. Pazartesi işlem yok.
- **Filtre (AÇIK):** dünün aralığı son 20 günün medyanının altındaysa pas. Log: `pdhlMinRangeMult=1.00`.
- **Stop:** ATR(14) × 1.5.
- **Trailing:** 0.5R.
- **Çıkış:** 00:00 UTC kapanış / stop / 0.5R trailing / Cuma 20:00.
- **Girişler:**
  `AccountSize=25000, RiskPct=0.59, TrailStopR=0.5, ForceStrategy=AUTO, MinRangeMedMult=0, PdhlMinRangeMedMult=1.0, PhaseTargetPct=10` — gerisi default. (RiskPct 1.3×; taban 0.45.)

---

## Açmayacakların
- **BTCUSD** — **KAPI-1'de çıkarıldı** (2026-09-28): 9 canlı işlem net −$291, PF 0.16,
  komisyon −$97.89 (~$11/işlem). Maliyet deterministik olarak modest edge'i yiyor.
  Daha çok canlı veri + düşük-komisyon broker olmadan açma.
- **NAS100 / US100** — ölçülen ölü ağırlık (herhangi gerçek spread'de negatif). Açma.
- **XAGAUD, XAUEUR** ve diğer quote-varyantları — farklı enstrüman (FX overlay), doğrulanmadı.

## "Gerisi default" ne demek (4 grafikte de dokunma)
OrbHours=1, OrbRangeHourUTC=0, PdhlStopATR=1.5, PdhlUseBackScan=false, NearTargetPct=1.5,
NearTargetMult=0.5, RequireAccountSize=true, LossBufferPct=1.0, Derisk (3/0.6/6/0.35),
MaxSingleRiskMult=2.0, MaxSpreadPoints=0, MaxSpreadToStopPct=12.5, UseFreezeLevelGuard=true,
ExtraStopBufferPts=2, MarginSafetyFactor=1.10, AccountWideEmergencyFlatten=true,
AutoPdhlSession=true, PdhlStartUTCMin=-1, PdhlEndUTCMin=-1, FridayFlattenUTCMin=1200,
TimerSeconds=2, ServerUtcOffsetOverrideHours=999, TesterServerUtcOffsetHours=999,
AvoidNews=true, NewsBufferMin=2, FreezeTrailInNews=true, NewsCurrencyOverride="",
NewsFailClosed=true, DrawLevels=true, JournalTrades=true, Magic=770077, Telegram boş.

## Her grafik için doğrulama (Experts log)
`Aurvex v3.13-merged on <SYM> ... magic=770077 orbHourUTC=0 minRangeMult=X pdhlMinRangeMult=Y base=25000.00 serverOffsetH=3 journal=on`
- **base=25000.00** her satırda. Değilse AccountSize yanlış → DUR.
- XAUUSD: `minRangeMult=1.00`. JP225: `pdhlMinRangeMult=1.00`. Diğerleri 0.00.
- Metaller `strat=ORB`, GER40/JP225 `strat=PDHL`. (BTC yok — çıkarıldı.)
