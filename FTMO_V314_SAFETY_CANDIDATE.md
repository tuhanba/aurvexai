# v3.14 SAFETY CANDIDATE — değişiklik raporu, testler, demo listesi, geri-dönüş

> **Durum:** SAFETY CANDIDATE. **Production'a KURULMADI, canlı inputlar
> DEĞİŞTİRİLMEDİ.** Son karar KAPI-1 + demo testinden sonra. Bu sürüm yalnızca
> **ADD-ONLY güvenlik katmanı** ekler; challenge stratejisi/giriş/çıkış/trailing/
> seans/risk-çarpanı/filtreler **aynen v3.13**.
>
> Dosya: `mql5/AurvexFTMO_v3_14_safety_candidate.mq5` (v3.13 dosyasına dokunulmadı).

## 1) Kapsam (istenen 9 madde)
| # | istek | durum |
|---|---|---|
| 1 | OnInit'te `ACCOUNT_MARGIN_MODE` oku + açıkça logla | ✅ (yalnız log, gating yok) |
| 2 | Dinamik-headroom Account-Level Risk Governor | ✅ `GovernorTryReserve` |
| 3 | Pending OCO çift-bacak rezervasyonu | ✅ her iki bacak scan'de sayılıyor |
| 4 | Restart/crash sonrası broker'dan risk reconciliation | ✅ committed = canlı scan; INFLIGHT init'te sıfır |
| 5 | Governor hatasında fail-closed | ✅ GV/OrderCalc hatası → emri açma |
| 6 | Challenge strateji/giriş/çıkış/trailing/seans/risk-çarpanı değişmesin | ✅ hiçbiri değişmedi (diff aşağıda) |
| 7 | Profit-Funded Acceleration ekleme | ✅ eklenmedi |
| 8 | BTC multi-session otomatik açma | ✅ açılmıyor (yalnız margin-mode log) |
| 9 | Gold/JP225 filtreleri değişmesin | ✅ default'lar aynen (MinRangeMedMult/PdhlMinRangeMedMult=0) |

## 2) v3.13 → v3.14 değişiklik raporu
**Eklenen (ADD-ONLY):**
- 8 yeni input (`GovernorEnabled=false` + tamponlar/tavanlar/retry) — hepsi default-OFF.
- Governor fonksiyon bloğu (`EnsureStops`'tan hemen önce):
  `GovPrefix / GovInflightGet / GovInflightReset / GovInflightAdd`
  (atomik `GlobalVariableSetOnCondition`), `SymbolGroupOf`, `PositionRiskFromNow`,
  `PendingRiskEntryToSL`, `ScanCommittedRisk`, `ScanGroupRisk`,
  `GovHeadroomAllowed`, `GovernorTryReserve`, `GovernorRelease`.
- OnInit: governor input validasyonu (negatif tampon/retry<1 → INIT_PARAMETERS_INCORRECT),
  `ACCOUNT_MARGIN_MODE` oku+logla, `GovInflightReset()`, başlangıç log'una `governor=on/off`.
- `EnsureStops` her iki OCO bacağı **governor gate** ile sarıldı.

**Değişen/çıkan satırlar (diff `<`):** yalnızca (a) dosya başlığı + `#property version`,
(b) BUY/SELL emir blokları **`if(pass){}` sarmalayıcısına taşındı** (silinmedi —
SavePlan/BuyStop/SellStop/CheckTradeCall aynen içeride), (c) OnInit son Notify metni.
**Hiçbir** strateji/giriş/çıkış/trailing/seans/filtre/`RiskMultiplier` satırı
değişmedi veya silinmedi.

**Governor gate (byte-identical kanıtı):**
```
double rNew=0; bool pass=true;
if(GovernorEnabled) pass=GovernorTryReserve(sym,buyPrice,buySL,lot,rNew);
if(pass) { SavePlan(...); trade.BuyStop(...); if(GovernorEnabled) GovernorRelease(rNew); ... }
```
`GovernorEnabled=false` → `pass=true` kısa-devre, `GovernorTryReserve` **hiç
çağrılmaz**, `GovernorRelease` **hiç çağrılmaz** → SavePlan+BuyStop v3.13 ile
birebir aynı. Governor yan-etkisi sıfır.

### Governor mantığı (dinamik headroom)
```
allowed = min(dayHeadroom, overallHeadroom) - slipGapBuf - safetyPad - costBuf
committed = ScanCommittedRisk() + INFLIGHT      // canlı scan (restart-safe) + race token
reserve rNew (atomik) -> committed+rNew <= allowed ? PLACE : rollback+REJECT
```
- `dayHeadroom/overallHeadroom` = `LossGuardOk()` ile **aynı** zemin formülleri
  (equity bazlı → realized + floating birlikte).
- `ScanCommittedRisk` = açık pozisyonlar (şu-an→SL worst-case) + pending emirler
  (entry→SL, **her iki OCO bacağı**). Hesap-geneli (tüm magic'ler).
- SL'siz pozisyon/pending → risk = tüm hesap (bloklar), fail-closed.
- **Yalnızca azaltır/reddeder; asla riski artırmaz** (rNew olduğu gibi kullanılır).

## 3) Test sonuçları
**Python referans modeli** (`src/aurvex/ftmo/risk_governor.py`) MQL5 governor
matematiğini birebir yansıtır; `tests/test_ftmo_governor.py` ile test edilir.
```
pytest tests/test_ftmo_governor.py  -> 16 passed
pytest -k ftmo                       -> 126 passed (110 mevcut + 16 governor)
```
Kapsanan (algoritma):
- Governor-OFF pass-through (rNew olduğu gibi, yan etki yok) + never-raise.
- min(daily, overall) bağlayıcı headroom; daily-bind / overall-bind / derin-zarar.
- Tamponların (slip/safety/cost) allowed'ı tam miktar düşürmesi.
- Realized + floating zararın equity üzerinden headroom'u tüketmesi ve red.
- Açık + pending risk toplamının bütçeyi tüketmesi.
- **OCO çift-bacak:** iki bacak sayılıyor; ikinci bacak sığmıyorsa red.
- **Race:** paylaşılan INFLIGHT ile iki instance çift-commit edemiyor
  (reserve-then-validate); ikisi de sığıyorsa ikisi de geçiyor.
- **Reconciliation:** crash'ten sızan rezerv init'te sıfırlanıyor; committed
  yine canlı scan'den doğru.
- Statik tavanlar (MaxTotalOpenRiskPct / MaxCorrelatedRiskPct) bağlayıcı olabiliyor.

> ⚠️ **MQL5 derleme (F7) BURADA yapılamaz** (MetaEditor yok). Süslü parantez/
> parantez dengesi ve idiomlar doğrulandı; **F7 derlemesi demo'dan önce zorunlu.**
> Python testleri governor **matematiğini** doğrular; MT5-runtime davranışı (fill/
> partial/restart/crash/netting/hedging) demo'da doğrulanır (§4).

## 4) Demo doğrulama kontrol listesi (MT5 gerekli)
Hesap: **DEMO** (challenge/funded değil). AccountSize gerçek değeriyle.

**A. Derleme + parity (governor OFF)**
- [ ] F7 hatasız derlenir (0 error, 0 warning hedef).
- [ ] `GovernorEnabled=false` ile v3.13 ile yan yana: aynı sembol/aynı gün aynı
      giriş kararları ve **aynı lot** (log karşılaştır). Birebir olmalı.
- [ ] Başlangıç log'unda `ACCOUNT_MARGIN_MODE=...` görünür.

**B. Governor ON — headroom**
- [ ] `GovernorEnabled=true`. Günlük zemine yakınken yeni emir **reddedilir**
      ("rejected by governor" log'u), zemin uzakken kabul edilir.
- [ ] Gün içi realized zarar sonrası allowed düşer; floating zarar (açık pozisyon)
      da allowed'ı düşürür (equity bazlı) — ikisi ayrı ayrı gözlenir.
- [ ] slip/safety/cost tamponları allowed'ı beklenen miktar düşürür.

**C. OCO çift-bacak**
- [ ] Tek enstrümanda ORB: iki bacak reserve edilir; toplam risk zemini aşacaksa
      ikinci bacak reddedilir.
- [ ] **Gap-through testi:** her iki bacağın da dolduğu hızlı-piyasa senaryosu
      (mümkünse tester'da) → hesap zemini aşılmaz; çift-fill sonrası davranış loglanır.

**D. Fill / partial / iptal**
- [ ] Bir bacak dolunca karşı bacak iptal edilir (`OnTradeTransaction`); INFLIGHT
      sızıntısı yok (init dışı 0'a döner).
- [ ] **Partial fill:** kısmi dolumda pozisyon riski + kalan pending riski doğru
      toplanır (scan gerçek hacmi okur).

**E. Restart / crash reconciliation**
- [ ] Açık pozisyon + pending varken EA kaldır-tak: committed canlı scan'den
      yeniden doğru hesaplanır; INFLIGHT 0'a resetlenir.
- [ ] Terminal kapat-aç (crash simülasyonu): aynı — sızan rezerv temizlenir.

**F. İki instance race**
- [ ] Aynı hesapta iki farklı sembolde iki EA; ikisi aynı anda emir vermeye
      çalışınca toplam açık risk zemini aşmaz (biri reddedilir).

**G. Netting vs Hedging (AYRI raporla)**
- [ ] **Hedging demo:** margin-mode log `RETAIL_HEDGING`; magic izolasyonu doğru;
      multi-session (opsiyonel) ayrı pozisyonlar.
- [ ] **Netting demo:** margin-mode log `RETAIL_NETTING`; aynı sembolde ikinci
      giriş birleşir → davranış gözlenir ve **ayrı raporlanır**; multi-session
      açılmaz. Governor (hesap-geneli scan) her iki modda da doğru toplamalı.

**H. Fail-closed**
- [ ] OrderCalc/GV hatası enjekte edilirse (ör. geçersiz SL) emir açılmaz, log net.

## 5) Canlıya geçiş + tek-adımda v3.13'e dönüş
**Geçiş (KAPI-1 + demo sonrası, ayrı owner kararı):**
1. §4'ün tamamı yeşil + F7 temiz.
2. Grafikte v3.13 EA'yı kaldır, `AurvexFTMO_v3_14_safety_candidate` ekle,
   **aynı input'lar** + `GovernorEnabled=false` (önce parity), izle.
3. Bir gün parity sonrası `GovernorEnabled=true`, tamponlar default; izle.

**Tek-adım geri dönüş (herhangi bir sorunda):**
- **Anında:** grafikten v3.14'ü kaldır, `AurvexFTMO_v3_13_final` EA'yı geri ekle
  (aynı input'lar). v3.13 dosyası hiç değişmedi → davranış birebir eski hâli.
- **Alternatif (EA'yı değiştirmeden):** input `GovernorEnabled=false` yap → governor
  tamamen devre dışı, v3.14 davranışı = v3.13.
- **GV temizliği (gerekirse):** `AXGOV_<login>_INFLIGHT` global değişkenini sil
  (Terminal → F3 → sil) veya EA yeniden başlat (init'te 0'lanır). Strateji/FTMO
  state GV'lerine (`AX3_*`, `AX312_FTMO_*`) dokunma.
- Not: v3.14 hiçbir kalıcı governor state tutmaz (committed her zaman canlı
  scan'den) → geri dönüş temiz, artık bırakmaz.

## 6) Sınırlar
- MQL5 F7 derlemesi bu ortamda yapılamadı (MetaEditor yok) — demo öncesi zorunlu.
- Governor tek-terminal içi çalışır (GV IPC); çoklu terminal/VPS'te GV paylaşılmaz.
- Python testleri matematik parity'sini doğrular, MT5-runtime'ı değil — o demo'da.
- Bu sürüm production'a **kurulmadı**; canlı input'lar **değişmedi**.
