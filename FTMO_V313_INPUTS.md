# v3.13 — her grafik için tam input değerleri ($25k) — KAPI-1 SONRASI

> **KAPI-1 GÜNCELLEMESİ (2026-09-28):** 31 gerçek işlemlik ilk canlı set analiz
> edildi (`FTMO_KAPI1_FINDINGS.md`). Karar: **BTCUSD çıkarıldı** (komisyon onu
> öldürüyor: toplam −$100 komisyonun −$98'i BTC'den, PF 0.16, en kötü bacak),
> **US100 zaten kapalı**, ve **doğrulanmış vol-filtreleri açıldı** (KAPI-1 karar
> noktasıydı). Evren artık **4 grafik: XAUUSD, XAGUSD, GER40.cash, JP225.cash.**

> **RİSK NOTU (dürüstlük):** Tablo hâlâ kullanıcının bilinçli **1.3×** tercihiyle.
> Canlı 31 işlem net **−%2.5** (negatif beklenti bu örneklemde). **Öneri:** challenge
> gidişatı negatifken 1.0×'e inmek daha güvenli (proxy patlama 5.2%→1.8%, daha yavaş
> erime, edge'in görünmesi için daha çok zaman). 1.3× kalırsa kullanıcının kararı;
> değiştirmek için onay gerek.

EA: `AurvexFTMO_v3_13_final.mq5` (hedef) veya `AurvexFTMO_v3_14_safety_candidate.mq5`
(F7+demo sonrası). **4 grafik (H1). BTCUSD ve NAS100/US100 AÇMA.**

## Grafikten grafiğe değişen inputlar (1.3× risk)

| input | XAUUSD | XAGUSD | GER40.cash | JP225.cash |
|---|---|---|---|---|
| **AccountSize** | 25000 | 25000 | 25000 | 25000 |
| **RiskPct (1.3×)** | **0.46** | **0.46** | **0.33** | **0.59** |
| **TrailStopR** | 0 | 0 | 0.5 | 0.5 |
| **ForceStrategy** | AUTO | AUTO | AUTO | AUTO |
| **MinRangeMedMult** | **1.0** ✅ | 0 | 0 | 0 |
| **PdhlMinRangeMedMult** | 0 | 0 | 0 | **1.0** ✅ |
| **PhaseTargetPct** | 10 | 10 | 10 | 10 |

(Taban 1.0× karşılaştırma: 0.35 / 0.35 / 0.25 / 0.45)

## KAPI-1 kararları (neden bu değişiklikler)
- **BTCUSD çıkarıldı:** 9 işlem, net −$291, PF 0.16; komisyon −$97.89 (işlem başına
  ~$11, 1R≈$122'nin ~%9'u). Komisyondan arındırılınca bile ~−$193 (canlı edge yok).
  Maliyet **deterministik** — varyans değil. MQL5'te komisyon işlem-öncesi güvenilir
  okunamadığından "cost gate" yerine **evrenden çıkarma** doğru çözüm.
- **US100 kapalı** (zaten): ölü ağırlık (proxy −0.014, her spread öldürür).
- **GER40 calendar-PDHL** (zaten v3.13 default `PdhlUseBackScan=false`): canlıdaki
  v3.11'in −$283'ünün kaynağı Monday back-scan'di; v3.13 Pazartesi'yi atlar.
- **Gold filtresi AÇIK** (XAUUSD MinRangeMedMult=1.0): doğrulanmış (OOS +0.19→+0.36).
  Düşük-vol günleri atlar — XAU'nun canlı kaybeden günlerini eler.
- **JP225 filtresi AÇIK** (PdhlMinRangeMedMult=1.0): doğrulanmış (+0.086R). JP225
  canlıda tek pozitif (+$165); filtre frekansı düşürür, işlem-başı edge'i artırır.
- **XAG/GER40 filtreleri KAPALI:** filtre yalnızca doğrulandığı yerde (gold, JP225);
  gerisine uygulamak overfit olurdu.
- **Short'lar:** canlıda 8 short −$626 (2 kazanç) — ama 8 işlem "kural" için az;
  ayrıca kaybeden shortların çoğu GER40/BTC'ydi (BTC çıktı, GER40 Monday düzeldi),
  o yüzden ayrı bir "short kapat" kuralı **eklenmedi** — izlenecek.

## Kritik uyarılar
- **AccountSize=25000 her grafikte** (boş/yanlış = breach riski).
- **PhaseTargetPct=10** her grafikte (profit-lock).
- **Guard değişmedi:** −%9 equity'de durur; günlük −%4. Guard'a dokunma.
- **Frekans düşecek:** filtreler açık = daha az işlem (kasıtlı — düşük-vol kaybeden
  günleri atlıyoruz; "az işlem" bir hata değil, kalite tercihi).

## Gerisi default (4 grafikte de aynı, dokunma)
OrbHours=1, OrbRangeHourUTC=0, PdhlStopATR=1.5, PdhlUseBackScan=false, NearTargetPct=1.5,
NearTargetMult=0.5, RequireAccountSize=true, LossBufferPct=1.0, Derisk (3/0.6/6/0.35),
MaxSingleRiskMult=2.0, MaxSpread=0/12.5, UseFreezeLevelGuard=true, ExtraStopBufferPts=2,
MarginSafetyFactor=1.10, AccountWideEmergencyFlatten=true, AutoPdhlSession=true,
FridayFlatten 20:00, TimerSeconds=2, AvoidNews=true, NewsBufferMin=2, DrawLevels=true,
JournalTrades=true, Magic=770077, Telegram boş. (Governor v3.14'te; default OFF.)

## Canlı v3.11 için ACİL operasyonel not (kod/demo gerektirmez)
Canlıda arkadaşının v3.11'i çalışıyor; bizim v3.13 config'i değil. **Bugün, sıfır-risk:**
- **BTCUSD grafiğini kaldır** (EA'yı o sembolde durdur) → −$291'lik bacak gider.
- **US100.cash grafiğini kaldır** → ölü ağırlık gider.
- GER40 Monday back-scan v3.11'de togglelanamıyorsa: GER40'ı duraklat **veya** v3.13'e
  geçişte otomatik düzelir. Filtreler (gold/JP225) v3.13/v3.14'e özel — v3.11'de yok.
- Tam fayda için hedef: **v3.13'i F7 derle + demo doğrula, sonra geç** (US100/BTC yok,
  GER40 calendar-PDHL, filtreler açık). Test edilmeden canlıya kurma.

## Doğrulama (Experts log)
`Aurvex ... on <SYM> ... base=25000.00 serverOffsetH=3 journal=on` — her grafikte.
XAUUSD'de `minRangeMult=1.00`, JP225'te `pdhlMinRangeMult=1.00` (filtreler açık).
