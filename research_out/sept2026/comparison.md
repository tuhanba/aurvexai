# Comparison — vary `TrailStopR`

_Each table is one experiment cell (symbol+EA+period+timeframe+deposit+leverage). Different cells — including different validation periods — are never merged, and per-symbol results are never summed into a portfolio._

## GER40.cash  (Aurvex_v314_test_utc, 2026.09.01..2026.10.02, H1, offset +3, dep 25000.0, lev 1:100.0, AvoidNews=false, RiskPct=0.46, quality=100% gerçek tik)
| TrailStopR | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 | recon |
|---|---|---|---|---|---|---|---|---|
| 0.3 | -247.20 | 14 | 8/14 | +56.51 | -116.55 | +157.5 | -404.68 | ✓ |
| 0.5 | -303.81 | 14 | 8/14 | +49.43 | -116.55 | +133.6 | -437.38 | ✓ |
| 0.75 | -220.20 | 14 | 8/14 | +59.88 | -116.55 | +137.8 | -357.95 | ✓ |

## JP225.cash  (Aurvex_v314_test_utc, 2026.09.01..2026.10.02, H1, offset +3, dep 25000.0, lev 1:100.0, AvoidNews=false, RiskPct=0.59, quality=100% gerçek tik)
| TrailStopR | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 | recon |
|---|---|---|---|---|---|---|---|---|
| 0.3 | -248.50 | 8 | 5/8 | +44.05 | -156.26 | +105.6 | -354.08 | ✓ |
| 0.5 | -227.66 | 8 | 5/8 | +48.22 | -156.26 | +109.3 | -337.00 | ✓ |
| 0.75 | -89.73 | 8 | 4/8 | +133.67 | -156.10 | +339.4 | -429.11 | ✓ |

_net_ex_top1 = net minus the single best trade (monster-dependence check); net includes commission + swap and is reconciled (recon ✓) against the report's Toplam Net Kar._
