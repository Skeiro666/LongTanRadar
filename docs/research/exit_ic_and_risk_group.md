# Exit IC Direction & RISK Group Analysis

**Scope:** Research calibration only  
**Production:** BUY / live broker / Exit decision logic / `exit.yaml` production weights **unchanged**  
**Exit ML:** not enabled  

Raw dump: `docs/research/exit_ic_and_risk_group_raw.json`

---

## 1. T+5 IC 根因（结论）

**Primary cause: G — Real data weak/reverse relationship**

Not A–F.

| Check | Result |
|-------|--------|
| A Exit Score direction | PASS — higher score = stronger exit pressure → HOLD / REDUCE / EXIT |
| B Forward return definition | PASS — `P_close(T+N)/P_close(T)-1` |
| C Time alignment | PASS — trading-bar offset N on sorted OHLCV |
| D Price / adj | PASS — panel `qfq` for both T and T+N |
| E IC implementation | PASS — Pearson/Spearman on paired lists; **no × −1** |
| F Sample filter | PASS — drop missing T+N; paired lengths match |
| **G Empirical** | **FAIL vs theory** — T+5 Spearman **+0.195** |

### Mechanism

- `corr(exit_score, past_5d_return) ≈ −0.87`  
  Exit score almost entirely tracks **already-weak** names.
- Those names often **mean-revert over the next ~5 sessions** → positive T+5 IC.
- Longer horizon softens: T+10 Spearman **−0.054**, T+20 **−0.117**.

**Do not flip the IC sign in code.** The math matches the definition; the economic content of the score is concurrent weakness, not a clean forward exit alpha at T+5.

---

## 2. IC 定义

```
exit_score ∈ [0,1]  = weighted mean of available exit-pressure features
hold_score           = 1 - exit_score

forward_return_Nd    = P_close(T+N) / P_close(T) - 1
N                    = trading bars in sorted panel (not calendar +N)
adj_type             = qfq (single series for T and T+N)

Expected if predictive: corr(exit_score, forward_return) < 0
```

Thresholds (unchanged): HOLD soft ≤0.30; REDUCE 0.60–0.80; EXIT >0.80.

---

## 3. 时间对齐

Example from IC Debug (trading bars):

| score_time | label_time (T+5) | bar_offset |
|------------|------------------|------------|
| 2025-10-23 | 2025-10-30 | 5 |

`label_time` is the date of index `i+5` in the bar frame, not `score_time + 5 calendar days`.

---

## 4. 样本统计

| Item | Value |
|------|-------|
| Research entries | 50 |
| Calibration rows | 50 |
| T+5 IC pairs | 50 |
| Minimum sample | 30 |
| High exit_score buckets (0.6+) | still sparse |

IC Debug exports ≥20 rows with: `score_time`, `label_time`, `score`, `future_return_*`, `price_t`, `price_t5`, `adj_type`.

---

## 5. RISK Feature Correlation

Config RISK group: `drawdown`, `volatility`, `price_extension`, `breakout_failure`, `profit_loss`  
Thresholds: HIGH ≥0.80, MEDIUM ≥0.60 (config/exit.yaml `validation`).

| Pair | Spearman | Level |
|------|----------|-------|
| **drawdown ↔ profit_loss** | **0.96** | **HIGH_REDUNDANCY** |
| others in RISK | mostly &lt;0.60 on this sample | LOW / MEDIUM |

**Yes — RISK GROUP has double-counting**, primarily drawdown vs profit_loss (both encode peak→mark pain).

---

## 6. Feature IC (Spearman)

| Feature | IC_1d | IC_5d | IC_10d | IC_20d |
|---------|-------|-------|--------|-------|
| **volatility** | **−0.57** | **−0.33** | **−0.41** | **−0.36** |
| drawdown | −0.26 | +0.02 | −0.05 | −0.14 |
| profit_loss | −0.18 | +0.08 | ~0 | −0.12 |
| price_extension | −0.03 | +0.07 | +0.14 | +0.20 |
| breakout_failure | −0.12 | +0.15 | −0.04 | −0.04 |
| moving_average_break (TREND) | −0.14 | **+0.27** | −0.17 | −0.19 |

`volatility` is the only consistently useful RISK member. Several “already weak” features flip **positive at T+5** (mean reversion).

---

## 7. Group IC (RISK weighted blend)

| Horizon | Spearman |
|---------|----------|
| T+1 | −0.39 |
| T+5 | **+0.18** (same wrong-sign pattern) |
| T+10 | ~0.02 |
| T+20 | −0.03 |

RISK GROUP as a whole is **near-zero / wrong-sign at T+5**, useful mainly at T+1 as a concurrent-stress gauge.

---

## 8. Leave-One-Out (score IC after zeroing weight)

Baseline T+5 IC ≈ +0.195.

Largest moves are small (~0.04). Removing RISK entirely does not create clean negative T+5 IC. Incremental information inside RISK is dominated by **volatility**; drawdown/profit_loss largely duplicate.

---

## 9. Ablation note

Full Exit Engine ablation vs No Exit / Fixed Stop remains as in V6.1 validation report: **no claimable Exit Alpha vs No Exit**. This stage did not re-tune production arms.

---

## 10. Candidate Weight（研究建议，未写回生产）

Current RISK → suggested (research only):

| Feature | Current | Candidate |
|---------|---------|-----------|
| drawdown | 0.10 | 0.10 |
| volatility | 0.06 | **0.069** (slight boost) |
| price_extension | 0.08 | 0.08 |
| breakout_failure | 0.08 | 0.08 |
| profit_loss | 0.04 | **0.024** (down-weight vs drawdown) |

`applied_to_production: false`

---

## 11. 是否建议修改生产权重？

**Not yet.** Suggestion only. Need denser high-score samples and a hold-out before any yaml change.

## 12. 是否继续 Heuristic？

**Yes.** Keep Heuristic. Do not enable Exit ML.

## 13. 是否具备进入 ML 的条件？

**No.**  
T+5 IC wrong sign, sparse high-score buckets, RISK redundancy, Exit Engine still not beating No Exit. Fix labels/features/sampling first.

---

## Code / UI delivered this stage

- `labels.forward_returns(..., base_mode="signal_close")` — IC path always T close→T+N close  
- `ic_debug.py` + Alpha Lab **Exit IC Debug**  
- `risk_group.py` + Alpha Lab **Exit Feature Groups** + RISK corr matrix  
- `tests/test_exit_ic_direction.py`  
- Production `weights:` in `exit.yaml` **unchanged**
