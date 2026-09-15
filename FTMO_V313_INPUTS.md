# v3.13 — her grafik için tam input değerleri ($25k) — 1.3× RİSK

> **RİSK NOTU (dürüstlük):** Bu tablo, kullanıcının **bilinçli kararıyla** taban riskin
> **1.3×**'i ile yazılmıştır. Tabana (1.0×) göre: proxy geçme olasılığı **98.2% → 94.8%**,
> patlama (bust) **1.8% → 5.2%** (≈3 kat). Canlıda gerçek spread'le patlama daha yüksek
> olabilir. Bu, "olabildiğince maksimum" DEĞİL — tavsiye edilen güvenli taban 1.0×'tir;
> 1.3× kullanıcının gözü açık tercihidir. Filtreler şimdilik KAPALI (veri toplama; KAPI-1'de karar).

EA: `AurvexFTMO_v3_13_final.mq5` (veya canlıdaki `AurvexFTMO.mq5` v2.8). 5 grafik (H1).
**NAS100/US100 açma.**

## Grafikten grafiğe değişen inputlar (1.3× risk)

| input | XAUUSD | XAGUSD | BTCUSD | GER40.cash | JP225.cash |
|---|---|---|---|---|---|
| **AccountSize** | 25000 | 25000 | 25000 | 25000 | 25000 |
| **RiskPct (1.3×)** | **0.46** | **0.46** | **0.39** | **0.33** | **0.59** |
| **TrailStopR** | 0 | 0 | 0.3 | 0.5 | 0.5 |
| **ForceStrategy** | AUTO | AUTO | **ORB** | AUTO | AUTO |
| **MinRangeMedMult** | 0 | 0 | 0 | 0 | 0 |
| **PdhlMinRangeMedMult** | 0 | 0 | 0 | 0 | 0 |
| **PhaseTargetPct** | 10 | 10 | 10 | 10 | 10 |

(Taban 1.0× karşılaştırma: 0.35 / 0.35 / 0.30 / 0.25 / 0.45)

## Kritik uyarılar
- **AccountSize=25000 her grafikte** (boş/yanlış = breach riski).
- **BTC ForceStrategy=ORB** zorunlu.
- **PhaseTargetPct=10** her grafikte (profit-lock).
- **Filtreler KAPALI** (MinRangeMedMult=0, PdhlMinRangeMedMult=0) — daha çok işlem + veri toplama; KAPI-1'de aç/kapat kararı.
- **Guard değişmedi:** −%9'da (equity) durur; günlük −%4. 1.3× riskte bir kötü gün floor'a daha yakın — guard'a dokunma.

## Gerisi default (5 grafikte de aynı, dokunma)
OrbHours=1, OrbRangeHourUTC=0, PdhlStopATR=1.5, PdhlUseBackScan=false, NearTargetPct=1.5,
NearTargetMult=0.5, RequireAccountSize=true, LossBufferPct=1.0, Derisk (3/0.6/6/0.35),
MaxSingleRiskMult=2.0, MaxSpread=0/12.5, UseFreezeLevelGuard=true, ExtraStopBufferPts=2,
MarginSafetyFactor=1.10, AccountWideEmergencyFlatten=true, AutoPdhlSession=true (v3.13) /
PdhlSessionStart-End 7-20 GER40, 0-6 JP225 (v2.8), FridayFlatten 20:00, TimerSeconds=2,
AvoidNews=true, NewsBufferMin=2, DrawLevels=true, JournalTrades=true, Magic=770077, Telegram boş.

## Doğrulama (Experts log)
`Aurvex ... on <SYM> ... base=25000.00 serverOffsetH=3 journal=on` — her grafikte.
`minRangeMult=0.00`, `pdhlMinRangeMult=0.00` (filtreler kapalı).
