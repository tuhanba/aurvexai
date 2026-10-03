# Comparison — vary `TrailStopR`

## GER40.cash  (period 2026.09.01..2026.10.02, offset 3, AvoidNews=false, RiskPct=0.46)
| TrailStopR | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 |
|---|---|---|---|---|---|---|---|
| 0.3 | -247.20 | 14 | 8/14 | +56.51 | -116.55 | +157.5 | -404.68 |
| 0.5 | -303.81 | 14 | 8/14 | +49.43 | -116.55 | +133.6 | -437.38 |
| 0.75 | -220.20 | 14 | 8/14 | +59.88 | -116.55 | +137.8 | -357.95 |

## JP225.cash  (period 2026.09.01..2026.10.02, offset 3, AvoidNews=false, RiskPct=0.59)
| TrailStopR | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 |
|---|---|---|---|---|---|---|---|
| 0.3 | -248.50 | 8 | 5/8 | +44.05 | -156.26 | +105.6 | -354.08 |
| 0.5 | -227.66 | 8 | 5/8 | +48.22 | -156.26 | +109.3 | -337.00 |
| 0.75 | -89.73 | 8 | 4/8 | +133.67 | -156.10 | +339.4 | -429.11 |

_net_ex_top1 = net minus the single best trade (monster-dependence check). Per-symbol only — these are separate instruments, never summed into a portfolio._
