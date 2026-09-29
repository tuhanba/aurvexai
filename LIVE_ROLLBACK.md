# LIVE ROLLBACK — AurvexFTMO v3.15 → v3.13 (tek adım)

> Bir sorunda (beklenmedik lot/SL/sembol, guard/phase yanlış davranışı) **anında**
> güvenli hâle dönüş. Governor + phase-lock zaten default OFF, o yüzden çoğu senaryoda
> tek gereken flag'i kapatmak veya EA'yı geri almaktır.

## Seviye 1 — özelliği kapat (kod değişmeden, en hızlı)
- **PhaseCompleteGuard sorunu:** `PhaseCompleteEnabled=false` yap (input) → guard
  tamamen devre dışı; pozisyon kapatma mantığı çalışmaz.
- **Governor sorunu:** `GovernorEnabled=false` (zaten default).
- Bu iki flag OFF iken v3.15'in trading path'i **v3.13 ile birebir**.

## Seviye 2 — v3.13'e dön (EA değişimi)
- Grafiklerden `AurvexFTMO_v3_15_live`'ı kaldır → `AurvexFTMO_v3_13_final`'ı ekle
  (aynı `.set` mantığı; v3.15-özel inputlar v3.13'te yok, gerisi aynı).
- v3.13 dosyası hiç değişmedi → davranış birebir bilinen hâl.
- **DİKKAT:** v3.11'e dönme — BTC/US100'ü açık bırakan eski ayarları geri getirir.
  Dönülecek taban **v3.13** (4 enstrüman, BTC/US100 kapalı).

## Seviye 3 — acil düz + kilit
- Zarar/güvenlik acili: EA'nın `AccountWideEmergencyFlatten=true` guard'ı zaten
  breach'te düzler. Manuel: tüm pending iptal + pozisyon kapat (operatör).
- Yeni emirleri durdur: ilgili grafiklerden EA'yı kaldır veya Algo Trading'i kapat.

## GV temizliği (gerekirse)
- Governor: sadece `AXGOV_<login>_INFLIGHT` sil (F3 → Global Variables).
- Phase-lock: `AX312_FTMO_<login>_PHASE_DONE` sil (yanlış LOCK takıldıysa).
- **Dokunma:** strateji/FTMO state GV'leri `AX3_*`, `AX312_FTMO_*` (INIT_BAL/FTMO_BAL/
  GUARD_*) — bunları silmek gün-taban bakiyesini kaybettirir.

## Geri-dönüş sonrası
- Hangi seviyeye dönüldüğü, sebep, o anki bakiye/pozisyon `FTMO_V315_EXIT_REPORT.md`'ye
  yazılsın. Kök-neden çözülmeden aynı flag tekrar açılmaz.
