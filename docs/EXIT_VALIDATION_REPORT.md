# Exit Engine Validation Report

**Baseline:** `1afeec43228b28383718fd4fedc9c7bd6dd492fb`  
**Exit version:** `exit_v1_1`  
**Execution model:** T close signal → **T+1 open** fill (never silent T-close)  
**Scope:** Research only — BUY untouched, no live broker, no new Agents/Roles  

Raw metrics: `docs/EXIT_VALIDATION_REPORT.json`

## Verdict

**Exit Engine does NOT show clear Alpha vs No Exit on the current research bootstrap.**

Do not complicate further. Next work should go back to Feature / Label / Data density — especially high `exit_score` buckets (0.6–1.0 currently empty).

## Sample

| Item | Value |
|------|-------|
| Research entries | 50 (panel bootstrap; paper book empty) |
| Calibration rows | 50 |
| Minimum sample | 30 |
| High score buckets (0.6+) | **0 samples** |

## Thirteen Answers

1. **Monotonicity (Score ↑ → Future Return ↓)?**  
   `PARTIAL_TRUE` on the only two buckets with enough samples (0.0–0.2 → T+10 +1.1%; 0.2–0.4 → T+10 −1.7%). Full 5-bucket claim: **INSUFFICIENT** (no mass above 0.4).

2. **Exit Score IC** (n=50)  
   - T+5 Spearman **+0.195** (wrong sign for an exit score)  
   - T+10 Spearman **−0.054**  
   - T+20 Spearman **−0.117**  

3. **Features that look useful (IC_10d < −0.05)**  
   - `volatility` (−0.41)  
   - `moving_average_break` (−0.17)  
   - `momentum_decay` (−0.11)

4. **High redundancy (|corr| > 0.8)**  
   - `drawdown` ↔ `profit_loss` (Spearman ~0.96) → **RISK GROUP** double-count risk  
   - Candidate groups (config): TREND / MOMENTUM / NEWS / EVENT / RISK — do **not** auto-drop.

5. **Exit Engine vs No Exit?** **NO** (net return worse on bootstrap)

6. **Exit Engine vs Fixed Stop?** **YES** (net better than fixed stop/take)

7. **Average Profit Giveback reduction vs No Exit?**  
   ≈ **−0.06%** (engine slightly *worse* giveback — within noise)

8–10. **Early / Good / Late %** → **INSUFFICIENT_SAMPLE** (engine EXIT events with post-exit labels < minimum)

11. **Exit ML vs Heuristic?** **INSUFFICIENT_SAMPLE** — keep **HEURISTIC** (no LightGBM activation)

12. **Sample enough?** Overall n=50 ≥ 30 for coarse IC; **not** enough for high-score calibration or timing quality.

13. **Future leakage?** **PASS** (`tests/test_exit_leakage.py` — mutate future bars/news/outcomes; T+1 open integrity)

## What was fixed this stage

- Full Exit Score Calibration (T+1/5/10/20, loss/gain rates, MDD)
- Feature IC + redundancy (no auto-delete)
- Ablation: No Exit / Fixed Hold / Fixed Stop / Engine / −News / −Thesis / −Momentum / −Trend
- Gross + net costs (commission, stamp, transfer, slippage)
- T+1 open execution + EXIT_BLOCKED / EXECUTION_UNAVAILABLE
- hold_score = 1 − exit_score
- Alpha Lab **Exit Validation** UI (no misleading charts when sample thin)
- Positions card: Entry / MFE / MAE / Drawdown / Exit+Hold score / Thesis Decay / Action
- Walk-forward ML gate (time split only; train only if beats Heuristic)

## Honest next research (not productizing)

1. Collect more mid/high exit_score observations (0.4–1.0).  
2. Re-weight or prune RISK GROUP redundancy (`drawdown` / `profit_loss`).  
3. Investigate why T+5 IC has the wrong sign.  
4. Re-run ablation after denser labels — only then reconsider ML.
