# v3.13 — her grafik için tam input değerleri ($25k)

EA: `AurvexFTMO_v3_13_final.mq5`. 5 grafik (H1): XAUUSD, XAGUSD, BTCUSD, GER40.cash,
JP225.cash. **NAS100/US100 açma.** Her grafiği eklerken "Allow Algo Trading" tikli.

## Sadece ŞU 7 input grafikten grafiğe değişir / default'tan farklıdır:

| input | XAUUSD | XAGUSD | BTCUSD | GER40.cash | JP225.cash |
|---|---|---|---|---|---|
| **AccountSize** | 25000 | 25000 | 25000 | 25000 | 25000 |
| **RiskPct** | 0.35 | 0.35 | 0.30 | 0.25 | 0.45 |
| **TrailStopR** | 0 | 0 | 0.3 | 0.5 | 0.5 |
| **ForceStrategy** | AUTO | AUTO | **ORB** | AUTO | AUTO |
| **MinRangeMedMult** | **1.0** | 0 | 0 | 0 | 0 |
| **PdhlMinRangeMedMult** | 0 | 0 | 0 | 0 | **1.0** |
| **PhaseTargetPct** | 10 | 10 | 10 | 10 | 10 |

## Kritik uyarılar
- **AccountSize=25000 her grafikte** (default 0'dır — boş bırakırsan EA başlamaz; yanlış girersen lot yanlış = anında breach riski).
- **RiskPct** default 0.50'dir → yukarıdaki değerleri gir (hiçbiri 0.50 değil).
- **BTCUSD'de ForceStrategy=ORB zorunlu** (AUTO, BTC'yi PDHL'e atar = negatif).
- **PhaseTargetPct=10** her grafikte (default 0 = profit-lock kapalı; 10 girince +%8.5'te riski yarıya kısar).
- **MinRangeMedMult sadece XAUUSD'de 1.0**, gerisi 0. **PdhlMinRangeMedMult sadece JP225'te 1.0**, gerisi 0.

## Bunların DIŞINDAKİ her input DEFAULT kalsın (5 grafikte de aynı):
- OrbHours=1, OrbRangeHourUTC=0, PdhlStopATR=1.5, PdhlUseBackScan=false
- NearTargetPct=1.5, NearTargetMult=0.5
- RequireAccountSize=true, LossBufferPct=1.0
- DeriskDD1Pct=3.0, DeriskMult1=0.6, DeriskDD2Pct=6.0, DeriskMult2=0.35, MaxSingleRiskMult=2.0
- MaxSpreadPoints=0, MaxSpreadToStopPct=12.5, UseFreezeLevelGuard=true, ExtraStopBufferPts=2, MarginSafetyFactor=1.10, AccountWideEmergencyFlatten=true
- AutoPdhlSession=true, PdhlStartUTCMin=-1, PdhlEndUTCMin=-1, FridayFlattenUTCMin=1200, TimerSeconds=2
- ServerUtcOffsetOverrideHours=999, TesterServerUtcOffsetHours=999 (canlıda otomatik; DOKUNMA)
- AvoidNews=true, NewsBufferMin=2, FreezeTrailInNews=true, NewsCurrencyOverride="", NewsFailClosed=true
- DrawLevels=true, JournalTrades=true, Magic=770077, TelegramToken="", TelegramChatID=""

> Seans kapıları otomatik: GER40 auto-DST (Frankfurt), JP225 sabit 0–6 UTC (Japonya DST yok). Elle seans girişi gerekmez.

## Doğrulama (Experts log, her grafik bir satır)
`Aurvex v3.13-merged on <SYM> ... magic=770077 orbHourUTC=0 minRangeMult=... pdhlMinRangeMult=... base=25000.00 serverOffsetH=3 journal=on`
- `base=25000.00` (değilse AccountSize'ı düzelt), `serverOffsetH=3`, `journal=on`.
- XAUUSD'de `minRangeMult=1.00`, JP225'te `pdhlMinRangeMult=1.00`.

## KAPI-1 sonrası (kâr genişlemesi — şimdi DEĞİL)
BTC canlı spread'i onaylanınca: tek BTCUSD yerine **3 BTCUSD grafiği**, `OrbRangeHourUTC`=0/3/13, her biri `ForceStrategy=ORB`, `TrailStopR=0.3`, **`RiskPct=0.10`**. Otomatik bağımsız (magic 770077/770080/770090).
