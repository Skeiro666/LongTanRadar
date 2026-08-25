# 条件边挖掘报告

- Canonical 龙头事件：**7165**
- Canonical 回踩且 HEALTHY：**500**
- 总检验格点数：**196**（有统计 33）
- 正收益格子：13 · 负收益格子：20
- 最好格子：{'name': 'DEPTH × VOLUME:<-12% × 中缩量', 'n': 49, 't1_net': 0.007336983670546334, 'rar': -0.07567473637002398, 'ld': 0.02040816326530612, 'sample_quality': 'LOW_SAMPLE'}
- 次好格子：{'name': 'STAGE=BREAKDOWN', 'n': 36, 't1_net': 0.00554724549553056, 'rar': -0.08211225729205927, 'ld': 0.027777777777777776, 'sample_quality': 'LOW_SAMPLE'}
- 中位格子：{'name': 'BOARD=2', 'n': 457, 't1_net': -0.0008455358837702288, 'rar': -0.08332329323533406, 'ld': 0.019693654266958426, 'sample_quality': 'STRONG'}
- **多重检验警告**：组合格点很多，单独最好看的格子不能当 Edge；n<100 只能 RESEARCH_SIGNAL
- 最终判定：**NO_EDGE_PROVEN**
- Candidate Edge 格子：None
- 新闻：本阶段不把新闻写入 BUY；news 一律视为 research-unavailable
- 是否应保持 BUY 管线不变：**是**

## 健康回踩 × 连板

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 | 457 | STRONG | -0.08% | 0.01% | 0.00% | 46.61% | 1.97% | -12.00% | -15.12% | -8.33% |
| 3 | 30 | LOW_SAMPLE | -0.35% | 0.22% | 1.51% | 43.33% | 6.67% | -12.64% | -17.26% | -11.31% |
| 4 | 11 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 | 2 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

## 健康回踩 × 回撤深度

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| -1%~-3% | 8 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -3%~-5% | 38 | LOW_SAMPLE | 0.26% | -0.55% | -0.85% | 50.00% | 2.63% | -13.71% | -15.98% | -8.65% |
| -5%~-8% | 75 | LOW_SAMPLE | -0.63% | -0.77% | -0.47% | 42.67% | 5.33% | -14.85% | -17.60% | -11.29% |
| -8%~-12% | 210 | OK | -0.15% | 0.14% | 0.28% | 44.29% | 0.95% | -10.85% | -14.02% | -7.49% |
| <-12% | 169 | OK | 0.21% | 0.37% | 0.56% | 51.48% | 3.55% | -11.83% | -15.85% | -8.96% |

## 健康回踩 × 量能

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 强缩量 | 17 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 中缩量 | 104 | OK | 0.31% | 0.24% | -0.25% | 48.08% | 1.92% | -11.01% | -14.57% | -7.65% |
| 轻缩量 | 379 | STRONG | -0.18% | -0.01% | 0.37% | 46.17% | 2.64% | -12.50% | -15.81% | -9.01% |
| 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

## 健康回踩 × 阶段

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EARLY | 62 | LOW_SAMPLE | -0.35% | -0.78% | -0.09% | 45.16% | 3.23% | -9.87% | -12.13% | -7.55% |
| TREND | 123 | OK | 0.15% | 0.11% | -0.28% | 46.34% | 0.00% | -10.05% | -12.90% | -6.30% |
| ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EXTREME | 279 | OK | -0.23% | -0.25% | -0.07% | 45.52% | 3.58% | -13.80% | -17.14% | -10.06% |
| DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN | 36 | LOW_SAMPLE | 0.55% | 2.81% | 3.76% | 58.33% | 2.78% | -9.62% | -15.59% | -8.21% |

## 健康回踩 × 价格结构（T 日可知）

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 跌破关键高点 | 377 | STRONG | 0.01% | 0.25% | 0.40% | 47.48% | 1.86% | -11.28% | -14.81% | -8.04% |
| 跌破均线 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 连续大阴 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 当日跌停 | 2 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 放量破位 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 结构完好 | 121 | OK | -0.43% | -0.80% | -0.69% | 43.80% | 4.13% | -14.60% | -17.04% | -10.40% |

## 二维交叉（n<100 不得称 Edge）

### BOARD × DEPTH

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 × -1%~-3% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × -3%~-5% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × -5%~-8% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × -8%~-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × <-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × -1%~-3% | 7 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × -3%~-5% | 36 | LOW_SAMPLE | 0.24% | -0.25% | -0.60% | 50.00% | 0.00% | -14.00% | -16.15% | -7.83% |
| 2 × -5%~-8% | 69 | LOW_SAMPLE | -1.01% | -1.37% | -1.26% | 39.13% | 5.80% | -14.89% | -17.25% | -11.67% |
| 2 × -8%~-12% | 194 | OK | -0.13% | 0.15% | 0.03% | 44.33% | 0.00% | -10.97% | -13.96% | -7.11% |
| 2 × <-12% | 151 | OK | 0.40% | 0.64% | 0.73% | 52.98% | 3.31% | -11.52% | -15.49% | -8.50% |
| 3 × -1%~-3% | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × -3%~-5% | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × -5%~-8% | 5 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × -8%~-12% | 11 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × <-12% | 12 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × -1%~-3% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × -3%~-5% | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × -5%~-8% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × -8%~-12% | 5 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × <-12% | 5 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × -1%~-3% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × -3%~-5% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × -5%~-8% | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × -8%~-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × <-12% | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × -1%~-3% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × -3%~-5% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × -5%~-8% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × -8%~-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × <-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × -1%~-3% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × -3%~-5% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × -5%~-8% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × -8%~-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × <-12% | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

### BOARD × VOLUME

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × 轻缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × 强缩量 | 16 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × 中缩量 | 94 | LOW_SAMPLE | 0.41% | 0.21% | -0.19% | 48.94% | 2.13% | -10.20% | -13.83% | -7.25% |
| 2 × 轻缩量 | 347 | STRONG | -0.19% | 0.03% | 0.15% | 45.82% | 1.73% | -12.62% | -15.69% | -8.64% |
| 2 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × 中缩量 | 9 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × 轻缩量 | 21 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × 强缩量 | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × 中缩量 | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × 轻缩量 | 9 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × 轻缩量 | 2 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × 轻缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × 轻缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

### BOARD × STAGE

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × EXTREME | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 1 × BREAKDOWN | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × EARLY | 62 | LOW_SAMPLE | -0.35% | -0.78% | -0.09% | 45.16% | 3.23% | -9.87% | -12.13% | -7.55% |
| 2 × TREND | 123 | OK | 0.15% | 0.11% | -0.28% | 46.34% | 0.00% | -10.05% | -12.90% | -6.30% |
| 2 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × EXTREME | 245 | OK | -0.28% | -0.29% | -0.39% | 44.90% | 2.86% | -14.05% | -17.27% | -9.92% |
| 2 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 2 × BREAKDOWN | 27 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × EXTREME | 25 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 3 × BREAKDOWN | 5 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × EXTREME | 8 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 4 × BREAKDOWN | 3 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × EXTREME | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 5 × BREAKDOWN | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × EXTREME | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 6 × BREAKDOWN | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × EARLY | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × TREND | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × ACCELERATION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × EXTREME | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × DISTRIBUTION | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| 7+ × BREAKDOWN | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

### DEPTH × VOLUME

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| -1%~-3% × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -1%~-3% × 中缩量 | 1 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -1%~-3% × 轻缩量 | 7 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -1%~-3% × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -1%~-3% × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -3%~-5% × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -3%~-5% × 中缩量 | 6 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -3%~-5% × 轻缩量 | 32 | LOW_SAMPLE | -0.15% | -1.36% | -1.52% | 43.75% | 3.12% | -15.17% | -16.79% | -9.64% |
| -3%~-5% × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -3%~-5% × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -5%~-8% × 强缩量 | 3 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -5%~-8% × 中缩量 | 9 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -5%~-8% × 轻缩量 | 63 | LOW_SAMPLE | -0.82% | -0.73% | -0.79% | 41.27% | 4.76% | -14.97% | -17.69% | -11.33% |
| -5%~-8% × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -5%~-8% × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -8%~-12% × 强缩量 | 6 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -8%~-12% × 中缩量 | 39 | LOW_SAMPLE | -0.51% | -1.06% | -0.21% | 35.90% | 0.00% | -8.89% | -12.05% | -6.53% |
| -8%~-12% × 轻缩量 | 165 | OK | -0.04% | 0.48% | 0.49% | 46.06% | 1.21% | -11.41% | -14.70% | -7.81% |
| -8%~-12% × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| -8%~-12% × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| <-12% × 强缩量 | 8 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| <-12% × 中缩量 | 49 | LOW_SAMPLE | 0.73% | 0.97% | -1.03% | 53.06% | 2.04% | -11.65% | -15.17% | -7.57% |
| <-12% × 轻缩量 | 112 | OK | 0.06% | 0.22% | 1.46% | 50.89% | 3.57% | -11.95% | -16.30% | -9.34% |
| <-12% × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| <-12% × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |

### STAGE × VOLUME

| 分组 | n | 样本 | T+1净 | T+3净 | T+5净 | 胜率 | 跌停率 | MAE | MDD | 风险调整 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EARLY × 强缩量 | 6 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EARLY × 中缩量 | 14 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EARLY × 轻缩量 | 42 | LOW_SAMPLE | -0.07% | 0.06% | 1.24% | 52.38% | 2.38% | -9.54% | -12.49% | -7.15% |
| EARLY × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EARLY × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| TREND × 强缩量 | 4 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| TREND × 中缩量 | 29 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| TREND × 轻缩量 | 90 | LOW_SAMPLE | -0.03% | 0.06% | -0.59% | 44.44% | 0.00% | -10.45% | -13.36% | -6.71% |
| TREND × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| TREND × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| ACCELERATION × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| ACCELERATION × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| ACCELERATION × 轻缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| ACCELERATION × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| ACCELERATION × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EXTREME × 强缩量 | 7 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EXTREME × 中缩量 | 53 | LOW_SAMPLE | 0.50% | 0.85% | -0.05% | 50.94% | 1.89% | -12.46% | -16.92% | -8.62% |
| EXTREME × 轻缩量 | 219 | OK | -0.37% | -0.43% | 0.09% | 43.84% | 3.65% | -14.23% | -17.39% | -10.34% |
| EXTREME × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| EXTREME × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| DISTRIBUTION × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| DISTRIBUTION × 中缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| DISTRIBUTION × 轻缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| DISTRIBUTION × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| DISTRIBUTION × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN × 强缩量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN × 中缩量 | 8 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN × 轻缩量 | 28 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN × 正常量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |
| BREAKDOWN × 放量 | 0 | INSUFFICIENT_SAMPLE | — | — | — | — | — | — | — | — |


## n≥100 且 T+1 净>0 且风险调整>0 的格子

[]

## Walk-forward

[]

## 必须回答的问题

1. 8863 里多少是真正龙头？清洗后 **7165**。
2. board=0 为什么存在？回踩日误用当日 consecutive_limit_up=0；其中 0 条可修复为真实连板。
3. 是否有普通股票污染？旧集可能混入查找失败的事件；canonical 已剔除无法证明 2 连板来源的样本。
4. 清洗后还剩多少？**7165**。
5. PULLBACK 哪些条件最好？见多重检验 best/second/median，禁止只看最好格子。
6. 是否存在 n≥100 的正 EV 格子？**0** 个满足 n≥100 且 T+1 净>0 且 RAR>0。
7. Walk-forward 是否仍成立？见上文；判定=NO_EDGE_PROVEN。
8. 是否存在真正 Candidate Edge？**否**。
9. 当前 BUY pipeline 是否应保持不变？**是。**
