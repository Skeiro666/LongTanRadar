# ENTRY VALIDATION REPORT

- Generated samples: **351** from **120** symbols
- Elapsed: 21.8s | LLM calls: 0 | Tokens: 0
- Params frozen: True
- Verdict: **NO_STATISTICAL_EDGE_PROVEN**

## 1. Entry Mode Performance

| Mode | n | status | T+5 mean | T+5 win | T+5 LD | MFE | MAE |
|------|---|--------|----------|---------|--------|-----|-----|
| DIRECT_CHASE | 58 | OK | 0.0371 | 0.5094 | 0.4906 | 0.2654 | -0.1536 |
| FIRST_DIVERGENCE | 139 | OK | -0.0370 | 0.3383 | 0.2857 | 0.1666 | -0.1810 |
| PULLBACK | 37 | OK | 0.0186 | 0.5429 | 0.1143 | 0.2637 | -0.1585 |
| REBREAKOUT | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — |
| REACCELERATION | 117 | OK | -0.0094 | 0.4273 | 0.1909 | 0.1752 | -0.1739 |

## 2. EXTREME path

- **DIRECT_CHASE**: n=57 status=OK T+5=0.0329 win=0.5000 LD=0.5000
- **FIRST_DIVERGENCE**: n=124 status=OK T+5=-0.0390 win=0.3220 LD=0.3220
- **PULLBACK**: n=24 status=LOW_SAMPLE T+5=0.0229 win=0.5652 LD=0.1739
- **REBREAKOUT**: n=0 status=INSUFFICIENT_SAMPLE T+5=— win=— LD=—
- **REACCELERATION**: n=95 status=OK T+5=-0.0116 win=0.4091 LD=0.2386

- Wait better than chase? **False**

## 3. Re-entry Calibration

- Verdict: **REENTRY SCORE NOT CALIBRATED**
- Spearman≈ -0.3571428571428572

## 4. Ablation (IC drop when removed)

- reacceleration: IC drop 0.0493
- structure: IC drop 0.0142
- volume: IC drop 0.0126
- confirmation: IC drop -0.0004
- pullback: IC drop -0.0296
- Most important: **reacceleration**

## 5. Walk-forward

- status: OK
- edge_stable: **False**
- reaccel_minus_chase_test: None

## 6. BUY Funnel

- ENTRY_EVENTS: 351
- DIRECT_CHASE: 58
- FIRST_DIVERGENCE: 139
- PULLBACK: 37
- REBREAKOUT: 0
- REACCELERATION: 117
- stage_EXTREME: 290
- timing_BUY_CANDIDATE: 8
- timing_BUY_READY: 0
- timing_WAIT: 294

## 7. Direct answers

1. **DIRECT_CHASE effective?** False (n=58, T+5=0.0371, win=0.5094, LD5=0.4906, status=OK)
2. **FIRST_DIVERGENCE effective?** False (n=139, T+5=-0.0370, win=0.3383, LD5=0.2857, status=OK)
3. **PULLBACK effective?** True (n=37, T+5=0.0186, win=0.5429, LD5=0.1143, status=OK)
4. **REBREAKOUT effective?** False (n=0, T+5=—, win=—, LD5=—, status=INSUFFICIENT_SAMPLE)
5. **REACCELERATION effective?** False (n=117, T+5=-0.0094, win=0.4273, LD5=0.1909, status=OK)
6. Board×Entry: see JSON `board_x_entry` (best risk among OK cells tends toward PULLBACK on mid boards).
7. Stage×Entry: see JSON `stage_x_entry` (EXTREME+DIRECT_CHASE still high LD).
8. Re-entry calibrated? **REENTRY SCORE NOT CALIBRATED**
9. Most important feature? **reacceleration**
10. BUY_READY threshold historically supported by samples? **False** (BUY_READY count in dataset timing=0)
11. Statistical edge? **NO_STATISTICAL_EDGE_PROVEN**
12. Sample sufficient? **True** (n=351)

### Interpretation (honest)

- DIRECT_CHASE may show positive average T+5 but **~50% limit-down incidence** → not a usable edge.
- FIRST_DIVERGENCE mean T+5 is **negative** in this sample → waiting alone is not enough.
- PULLBACK has better LD rate but n is modest; do **not** treat as proven alpha.
- REACCELERATION does **not** beat DIRECT_CHASE on mean T+5 here; EXTREME wait path not superior.
- reentry_score is **not monotonically** related to T+5 (NOT CALIBRATED).

## Notes

- Parameters frozen — no threshold tuning in this run.
- Edge requires calibration + walk-forward stability + EXTREME wait superiority.
