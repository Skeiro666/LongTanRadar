# 龙头宇宙完整性审计

研究口径：PRIMARY = T+1 开盘买入净收益。未改 BUY 门槛、未调用大模型、未引入新 ML、未改 Entry Mode 权重。

## 结论摘要

- 原始 EntryEvent：**8863**
- 原始 board_count=0：**0**（占比 0.00%）
- 原始 board_count≥1：**8863**
- BREAKDOWN 且 HEALTHY_PULLBACK：**166**
- 清洗后龙头有效事件：**7165**
- 非龙头（剔除）：**1698**，污染率 19.16%
- 从 board=0 修复出真实连板：**0**
- 修复后仍为 0（距最近涨停超过10日或找不到涨停）：**787**

- 买点验证 jsonl：{'available': True, 'n': 351, 'board0': 140, 'board0_pullback_like': 37, 'example': {'symbol': '000017.SZ', 'date': '2025-12-05', 'board_count': 0, 'stage': 'BREAKDOWN', 'health': None, 'entry_mode': 'REACCELERATION'}}

用户举例 `000620.SZ / 2025-12-01 / board=0 / BREAKDOWN` 来自 **entry_validation**：
非涨停日用 `boards[i-1]`（前一日若不是涨停则为 0），没有回看最近一次涨停的连板。
统一事件集 jsonl 里 board=0 为 0 条，因为它会回看最多 15 日找峰值连板；
但候选窗是「2板结束后 12 日」，超过 10 日的回踩仍被 canonical 剔除。

## board_count 定义

- 当日连板：当日连续涨停板数；非涨停日为 0
- 龙头波段板数：最近一次涨停（回看10个交易日）当天的连续板数，即龙头波段板数
- Canonical 规则：DIRECT_CHASE 需当日连板>=3；回踩/分歧/再加速需 originating 连板>=2 且距最近涨停 1–10 日。board=0 默认 NOT_LEADER_EVENT

旧数据集在**回踩日**把 `consecutive_limit_up`（当日尾板为 0）写成 board_count，因此会出现 `board=0 + BREAKDOWN + HEALTHY_PULLBACK`。这不是「普通股进了龙头池」的充分证据，而是**板数字段用错了日期**。Canonical 一律改用 originating 连板。

## 各模式污染率

- **DIRECT_CHASE**：n=1740 非龙头=2 污染率=0.11%
- **FIRST_DIVERGENCE**：n=2708 非龙头=3 污染率=0.11%
- **PULLBACK**：n=1238 非龙头=690 污染率=55.74%
- **REACCELERATION**：n=3177 非龙头=1003 污染率=31.57%

## 样本例子（旧 board=0 且 HEALTHY）

[]

## 与其它实验室的差异

- healthy_pullback_lab：独立扫描：10日内出现过 >=2 连板后的回踩日，不是 exclusive EntryMode，可能与统一事件集口径不同
- entry_validation：与统一事件集同一候选窗（3板追涨 或 2板结束后12日），但板数曾误用当日 consecutive（回踩日=0）

## BUY 管线

- 未修改。本文件只做研究清洗。
