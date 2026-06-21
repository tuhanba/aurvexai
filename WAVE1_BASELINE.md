# Wave 1 baseline (deterministic backtest)

Generated: 2026-06-21 21:02 UTC
Generator: `scripts/wave1_baseline.py` · symbols=['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'] · bars/symbol=3000 · seed=20240601

This is the post-Wave-1 baseline through the repaired engine (closed-candle
discipline, entry-bar/one-fill timing, cost-inclusive sizing, slot-aware
leverage), net of fees + assumed slippage. **Wave 2 compares against this, not
the legacy history.** `READY_FOR_PAPER: YES` is gated on this report; live stays
OFF.

## Net edge
| metric | value |
|---|---|
| start balance | 1000.00 USDT |
| end balance | 1150.44 USDT |
| return | 15.044 % |
| net PnL | 150.4374 USDT |
| expectancy / trade | 1.2749 USDT (+0.244 R) |
| avg net R | +0.2443 |
| profit factor | 1.506 |
| winrate | 52.54 % |
| max drawdown | 38.8299 USDT (3.883 %) |

## Activity
| metric | value |
|---|---|
| signals seen | 430 |
| allows | 118 |
| total trades | 118 |
| trades / day | 64.78 |
| margin-rejected signals | 0 |

## TP ladder (how far winners ran)
| step | count | transition |
|---|---|---|
| TP1 | 62 | — |
| TP2 | 44 | TP1→TP2 71.0 % |
| TP3 | 39 | TP2→TP3 88.6 % |
| SL closes | 56 | BE closes 22 |

## Cost & margin
| metric | value |
|---|---|
| total fees | 94.8877 USDT |
| fee share of turnover | 0.1301 % |
| avg margin used | 275.85 USDT |
| max margin used | 833.73 USDT |
| leverage distribution | 1x×16, 2x×51, 3x×40, 4x×6, 5x×3, 6x×2 |

## Reject reasons
  - cooldown: 233
  - score_threshold: 79

## Deferred to Wave 2
- Per-trade MAE/MFE excursion (`mae_mfe = deferred_to_wave2_replay`) — needs per-bar
  excursion capture in the replay harness.

---
_Raw metrics JSON below for tooling._

```json
{
  "total_trades": 118,
  "winrate": 52.54,
  "expectancy": 1.2749,
  "expectancy_r": 0.2443,
  "profit_factor": 1.506,
  "avg_r": 0.2443,
  "avg_win": 7.2212,
  "avg_loss": -5.3085,
  "gross_profit": 447.7125,
  "gross_loss": 297.275,
  "net_pnl": 150.4374,
  "total_fees": 94.8877,
  "tp1_hit_rate": 52.54,
  "sl_hit_rate": 47.46,
  "tp_closes": 39,
  "sl_closes": 56,
  "be_closes": 22,
  "max_drawdown": 38.8299,
  "equity_curve": [
    10.8835,
    18.4982,
    27.2655,
    22.2387,
    17.1648,
    26.2912,
    29.4512,
    24.3545,
    19.29,
    14.2507,
    17.1017,
    12.0722,
    7.0636,
    2.0498,
    4.0605,
    10.5197,
    5.5186,
    0.5426,
    -4.4277,
    -9.3788,
    -2.303,
    6.8306,
    9.466,
    19.2622,
    28.4545,
    37.5219,
    40.2269,
    35.0818,
    29.9305,
    24.8072,
    19.7098,
    14.6127,
    24.1238,
    19.055,
    27.8955,
    22.7908,
    25.21,
    20.1038,
    23.2964,
    32.7317,
    42.0097,
    44.1407,
    53.9546,
    48.7423,
    51.2814,
    46.0491,
    40.8449,
    50.5669,
    45.3414,
    53.886,
    59.7059,
    54.4648,
    62.8185,
    71.5963,
    66.3474,
    68.8984,
    79.376,
    74.0364,
    76.5676,
    71.2284,
    65.8966,
    76.0761,
    70.7254,
    72.7157,
    81.4238,
    76.0741,
    70.751,
    65.4281,
    60.1132,
    54.8516,
    64.2028,
    75.4925,
    78.4376,
    87.9249,
    82.4607,
    92.4883,
    103.0947,
    97.5991,
    107.4458,
    101.9834,
    96.5249,
    103.9212,
    98.435,
    105.1922,
    99.6636,
    94.1508,
    88.6654,
    98.1931,
    104.1652,
    115.4299,
    126.4019,
    120.8467,
    115.2915,
    109.78,
    111.6778,
    120.9815,
    115.4282,
    117.6989,
    127.4314,
    121.9099,
    133.0628,
    135.6679,
    130.0268,
    131.3202,
    125.6968,
    136.0505,
    130.3721,
    141.6986,
    145.3356,
    139.6506,
    133.9816,
    128.3635,
    139.5001,
    133.8418,
    143.8209,
    138.1532,
    147.9108,
    150.4374
  ],
  "by_symbol": [
    {
      "key": "ETHUSDT",
      "trades": 28,
      "winrate": 71.4,
      "net_pnl": 92.8004,
      "expectancy": 3.3143
    },
    {
      "key": "BTCUSDT",
      "trades": 32,
      "winrate": 53.1,
      "net_pnl": 53.4595,
      "expectancy": 1.6706
    },
    {
      "key": "SOLUSDT",
      "trades": 30,
      "winrate": 46.7,
      "net_pnl": 7.3021,
      "expectancy": 0.2434
    },
    {
      "key": "BNBUSDT",
      "trades": 28,
      "winrate": 39.3,
      "net_pnl": -3.1245,
      "expectancy": -0.1116
    }
  ],
  "by_setup": [
    {
      "key": "trend_continuation",
      "trades": 89,
      "winrate": 52.8,
      "net_pnl": 130.4347,
      "expectancy": 1.4656
    },
    {
      "key": "volume_expansion",
      "trades": 8,
      "winrate": 62.5,
      "net_pnl": 18.8038,
      "expectancy": 2.3505
    },
    {
      "key": "momentum_breakout",
      "trades": 18,
      "winrate": 50.0,
      "net_pnl": 10.1776,
      "expectancy": 0.5654
    },
    {
      "key": "liquidity_sweep",
      "trades": 3,
      "winrate": 33.3,
      "net_pnl": -8.9786,
      "expectancy": -2.9929
    }
  ],
  "by_side": [
    {
      "key": "LONG",
      "trades": 69,
      "winrate": 53.6,
      "net_pnl": 97.8178,
      "expectancy": 1.4176
    },
    {
      "key": "SHORT",
      "trades": 49,
      "winrate": 51.0,
      "net_pnl": 52.6197,
      "expectancy": 1.0739
    }
  ],
  "by_hour": [
    {
      "key": "02:00 UTC",
      "trades": 7,
      "winrate": 71.4,
      "net_pnl": 32.2969,
      "expectancy": 4.6138
    },
    {
      "key": "20:00 UTC",
      "trades": 7,
      "winrate": 71.4,
      "net_pnl": 31.0823,
      "expectancy": 4.4403
    },
    {
      "key": "13:00 UTC",
      "trades": 6,
      "winrate": 83.3,
      "net_pnl": 29.8095,
      "expectancy": 4.9683
    },
    {
      "key": "10:00 UTC",
      "trades": 5,
      "winrate": 80.0,
      "net_pnl": 21.7441,
      "expectancy": 4.3488
    },
    {
      "key": "18:00 UTC",
      "trades": 7,
      "winrate": 57.1,
      "net_pnl": 19.4323,
      "expectancy": 2.776
    },
    {
      "key": "14:00 UTC",
      "trades": 4,
      "winrate": 75.0,
      "net_pnl": 17.9027,
      "expectancy": 4.4757
    },
    {
      "key": "09:00 UTC",
      "trades": 5,
      "winrate": 60.0,
      "net_pnl": 17.518,
      "expectancy": 3.5036
    },
    {
      "key": "16:00 UTC",
      "trades": 4,
      "winrate": 75.0,
      "net_pnl": 16.6751,
      "expectancy": 4.1688
    },
    {
      "key": "08:00 UTC",
      "trades": 4,
      "winrate": 75.0,
      "net_pnl": 13.3161,
      "expectancy": 3.329
    },
    {
      "key": "23:00 UTC",
      "trades": 2,
      "winrate": 100.0,
      "net_pnl": 12.7106,
      "expectancy": 6.3553
    },
    {
      "key": "01:00 UTC",
      "trades": 9,
      "winrate": 44.4,
      "net_pnl": 10.4608,
      "expectancy": 1.1623
    },
    {
      "key": "06:00 UTC",
      "trades": 7,
      "winrate": 57.1,
      "net_pnl": 7.1276,
      "expectancy": 1.0182
    },
    {
      "key": "15:00 UTC",
      "trades": 6,
      "winrate": 66.7,
      "net_pnl": 6.0663,
      "expectancy": 1.011
    },
    {
      "key": "21:00 UTC",
      "trades": 1,
      "winrate": 100.0,
      "net_pnl": 2.5511,
      "expectancy": 2.5511
    },
    {
      "key": "03:00 UTC",
      "trades": 4,
      "winrate": 50.0,
      "net_pnl": 2.2309,
      "expectancy": 0.5577
    },
    {
      "key": "00:00 UTC",
      "trades": 4,
      "winrate": 50.0,
      "net_pnl": 0.0159,
      "expectancy": 0.004
    },
    {
      "key": "19:00 UTC",
      "trades": 3,
      "winrate": 33.3,
      "net_pnl": -2.1215,
      "expectancy": -0.7072
    },
    {
      "key": "07:00 UTC",
      "trades": 4,
      "winrate": 25.0,
      "net_pnl": -3.9253,
      "expectancy": -0.9813
    },
    {
      "key": "12:00 UTC",
      "trades": 6,
      "winrate": 33.3,
      "net_pnl": -9.5833,
      "expectancy": -1.5972
    },
    {
      "key": "05:00 UTC",
      "trades": 5,
      "winrate": 20.0,
      "net_pnl": -10.1813,
      "expectancy": -2.0363
    },
    {
      "key": "22:00 UTC",
      "trades": 2,
      "winrate": 0.0,
      "net_pnl": -10.6787,
      "expectancy": -5.3394
    },
    {
      "key": "04:00 UTC",
      "trades": 4,
      "winrate": 25.0,
      "net_pnl": -12.2666,
      "expectancy": -3.0667
    },
    {
      "key": "17:00 UTC",
      "trades": 7,
      "winrate": 28.6,
      "net_pnl": -15.2158,
      "expectancy": -2.1737
    },
    {
      "key": "11:00 UTC",
      "trades": 5,
      "winrate": 0.0,
      "net_pnl": -26.5302,
      "expectancy": -5.306
    }
  ],
  "start_balance": 1000.0,
  "end_balance": 1150.4374,
  "return_pct": 15.044,
  "signals_seen": 430,
  "allows": 118,
  "symbols": [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT"
  ],
  "bars_per_symbol": {
    "BTCUSDT": 3000,
    "ETHUSDT": 3000,
    "SOLUSDT": 3000,
    "BNBUSDT": 3000
  },
  "tp1_hits": 62,
  "tp2_hits": 44,
  "tp3_hits": 39,
  "tp1_to_tp2_rate": 71.0,
  "tp2_to_tp3_rate": 88.6,
  "leverage_dist": {
    "1": 16,
    "2": 51,
    "3": 40,
    "4": 6,
    "5": 3,
    "6": 2
  },
  "avg_margin_used": 275.85,
  "max_margin_used": 833.73,
  "fees_total": 94.8877,
  "fee_share_of_turnover_pct": 0.1301,
  "trades_per_day": 64.78,
  "margin_rejected_signals": 0,
  "reject_reasons": {
    "cooldown": 233,
    "score_threshold": 79
  },
  "mae_mfe": "deferred_to_wave2_replay"
}
```
