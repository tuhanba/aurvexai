# Settings check — /root/.claude/uploads/d1d33024-c0e3-5504-99ab-ed179ff5d423

- reports found: 9 · comparable: 6 (2 cell-families) · standalone: 2 · mismatched(settings error): 0 · rejected(field/offset/reconciliation error): 1

## REJECTED — field / offset / data-quality / reconciliation error
- `65a2ccf2-Trade_report-541438670_2026-09-28_13-13.html` (?): missing symbol; missing period_from; missing period_to; missing ea; missing TesterServerUtcOffsetHours; missing AvoidNews; missing modelling-quality (Tarihin Kalite); missing/corrupt summary field 'Başlangıç Mevduatı' — monetary values cannot be verified (not published); missing/corrupt summary field 'Kaldıraç' — monetary values cannot be verified (not published); missing/corrupt summary field 'Toplam Net Kar' — monetary values cannot be verified (not published); missing/corrupt summary field 'Toplam İşlem' — monetary values cannot be verified (not published); no parseable deals and no summary trade count (not published as a 0 result)

## STANDALONE — single run for the cell (kept, but no sibling to compare)
- `0454e085-XAUGUSD.html` (XAGUSD · Aurvex_v314_test_utc · 2026.09.01..2026.10.02 · H1 · dep 25000.0 · lev 1:100.0): TrailStopR=0.0 — logged to ledger; comparison needs ≥2 runs in the SAME cell varying only this.
- `b7ffd390-ReportTester-541438670.html` (XAUUSD · Aurvex_v314_test_utc · 2026.09.01..2026.10.02 · H1 · dep 25000.0 · lev 1:100.0): TrailStopR=0 — logged to ledger; comparison needs ≥2 runs in the SAME cell varying only this.

