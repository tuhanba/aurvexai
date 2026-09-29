# FTMO v3.15 — CANLI ÖNCESİ PREFLIGHT (operatör: Batu)

> Bu adımlar **terminal/hesap erişimi gerektirir** — Claude Code bunları
> çalıştıramadı (MT5/FTMO erişimi + MQL5 derleyicisi yok). Her satırın sonucunu
> **PASS / FAIL / NOT OBSERVED** olarak işaretle; sayısal broker değerini ve log
> referansını yaz. Bir adım FAIL ise **canlı aktivasyon durur.**

## 0. Derleme (operatör, MetaEditor)
- [ ] `mql5/AurvexFTMO_v3_15_live.mq5` MetaEditor'da **F7** → **0 error, 0 warning**.
- [ ] Üretilen `.ex5` sürümü 3.15; kaynak commit + EX5 SHA'yı `LIVE_DEPLOYMENT_MANIFEST.md`'ye yaz.
- [ ] Not: Python referans testleri (governor + phase-lock, 29 test) **geçiyor** ama
      **MQL5 derlemesinin yerine geçmez.** F7 zorunlu.

## 1. Hesap & sembol preflight (send-disabled)
- [ ] Hesap tipi **FTMO 2-Step Challenge** mi? Aşama (Challenge/Verification)? — Account MetriX'ten teyit.
- [ ] Başlangıç bakiyesi, mevcut bakiye, equity, `ACCOUNT_CURRENCY`, `ACCOUNT_MARGIN_MODE`,
      sunucu saati, FTMO gün başlangıcı — logla (EA başlangıç log'u bunları basar).
- [ ] Açık pozisyon + pending emirler listelendi mi? Başka EA / manuel işlem var mı?
- [ ] Tamamlanmış işlem günü sayısı (≥4 kuralı için) — Account MetriX.
- [ ] **BTCUSD ve US100.cash EA grafikleri durduruldu**; o sembollerdeki açık
      pozisyon/pending ticket/magic bazında çözüldü (grafik kapatmak yetmez).
- [ ] 4 sembolün **broker adı** Market Watch'tan bire bir eşlendi (sessiz eşleme yok);
      point değeri, min lot/step, `SYMBOL_CURRENCY_PROFIT` doğrulandı.
- [ ] Mevcut pozisyonların SL'si ve hangi EA sürümüne ait olduğu saptandı; aynı
      pozisyonu iki EA yönetmiyor.

## 2. Config yükleme (4 grafik, H1)
- [ ] Her grafiğe ilgili `.set` yüklendi (`mql5/sets/AurvexFTMO_v3_15_<sym>.set`):
      XAUUSD / XAGUSD / GER40.cash / JP225.cash. `.set` SHA'ları manifest'te.
- [ ] **AccountSize=25000** (BAŞLANGIÇ bakiyesi) her grafikte. Yanlışsa DUR.
- [ ] Başlangıç log'unda: `base=25000.00`, XAUUSD `minRangeMult=1.00`, JP225
      `pdhlMinRangeMult=1.00`, diğerleri 0.00, `governor=off`, `phaseLock=off`.
- [ ] `ACCOUNT_MARGIN_MODE=...` log'u görünür (netting/hedging teyidi).
- [ ] Foreign-exposure uyarısı: EA "FOREIGN position" uyarısı basıyorsa hesap
      Aurvex'e ayrılmamış → kapsam operatörce çözülene kadar aktivasyon durur.

## 3. Kritik kod davranışı (send-disabled / Strategy Tester)
- [ ] **FTMO floor & günlük reset:** CE(S)T yaz/kış geçişi, önceki-gün kârının
      ertesi gün limite etkisi, terminal-kapalı gece yarısı, restart — event bazında
      doğru gün + taban bakiye. `g_ftmoOpenBal` kurulamazsa yeni emir DURUYOR mu?
      (`FailClosedIfBaselineUnknown=true`, log'da "baseline uncertain".)
- [ ] **Guard tampon:** günlük −%4 / toplam −%9 tepki eşiği; hedefle karışmıyor.
- [ ] **Emergency loss-flatten** phase-lock'tan öncelikli (OnTick/OnTimer'da önce).
- [ ] **Boyut/maliyet:** min lot risk hedefini `MaxSingleRiskMult`(=2.0) katından
      fazla aşarsa işlem SKIP; profit-currency ≠ account-currency ise FX-adj log'u.
- [ ] **PhaseCompleteGuard** yalnız **demo'da** ayrı doğrulandıktan sonra açılır
      (aşağı bak). P0 canlıda **kapalı**.

## 4. Governor & phase-lock (P0'da KAPALI — ayrı demo kapısı)
- [ ] Governor `false`. (Enable etmek için ayrı demo: race, OCO çift-bacak,
      release-on-confirm, restart — `FTMO_V314_SAFETY_CANDIDATE.md`.)
- [ ] PhaseCompleteGuard demo: hesap target+buffer'a gelince pending iptal + OUR
      pozisyon kapatma + re-check + kalıcı LOCK; kısmi kapanışta LOCK yok/retry;
      foreign varsa operatör-review; restart/çoklu-instance/günlük-reset'te bozulmuyor;
      emergency-flatten önce. **Bunlar PASS olmadan `PhaseCompleteEnabled=true` yapma.**

## 5. İlk canlı akış (kontrollü)
- [ ] Send-disabled log'ları temiz (OrderSend=0 statik incelemeyle de doğrulandı).
- [ ] 4 sembol + seçili 1.3× (veya 1.0×) canlıya alındı; **ilk emir/ilk fill** MT5
      order history'den gözlendi.
- [ ] İlk trade beklenmedik lot/SL/sembol/gün-sınırı/maliyete sahipse: yeni emirleri
      kilitle, ilgili EA'yı geri al (`LIVE_ROLLBACK.md`). v3.11'e aceleyle dönme
      (BTC/US100 açık kalır).

## 6. Çıkış kaydı
Her adımın sonucunu `FTMO_V315_EXIT_REPORT.md`'ye PASS/FAIL/NOT OBSERVED + sayısal
değer + log referansı olarak yaz. Erişilemeyen veri = NOT OBSERVED (test edilmiş gibi işaretleme).
