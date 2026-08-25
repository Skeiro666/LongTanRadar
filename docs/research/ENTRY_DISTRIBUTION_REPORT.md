# ENTRY DISTRIBUTION REPORT

- samples: **351**
- elapsed: 3.99s | LLM: 0 | Token: 0
- round-trip cost rate: 0.00252
- reentry_score: **REENTRY_SCORE_UNCALIBRATED**
- overall: **NO_EDGE_PROVEN**

## Mode distribution (T+5 focus)

### DIRECT_CHASE (n=58, OK)
- mean=0.03707915760693519 median=0.004901960784313708 std=0.2049729377624126
- p10=-0.21481774745508087 p25=-0.08712121212121215 p75=0.16408825767182345 p90=0.3307093406948907
- best=0.6112637362637363 worst=-0.37369720241360393
- win=0.5094339622641509 LD=0.49056603773584906 MDD=-0.12776297171019527 MAE=-0.15358938517216075
- gt5=0.4528301886792453 gt10=0.33962264150943394 lt-10=0.24528301886792453
- top10% of +PnL share=0.44981857560844185
- EV net T+1open=-0.010248723589451517 net_mean=-0.010248723589451484
- risk_adjusted_return=-0.1985004414557096

### FIRST_DIVERGENCE (n=139, OK)
- mean=-0.03697817182289968 median=-0.049523366658916435 std=0.13392173774943117
- p10=-0.18732647814910025 p25=-0.1252834467120182 p75=0.029073482428114916 p90=0.11053218803349874
- best=0.5267399267399266 worst=-0.2991010208746
- win=0.3383458646616541 LD=0.2857142857142857 MDD=-0.11676145344770018 MAE=-0.1810035483273238
- gt5=0.19548872180451127 gt10=0.11278195488721804 lt-10=0.3458646616541353
- top10% of +PnL share=0.7126507134134771
- EV net T+1open=-0.02163308237234255 net_mean=-0.021633082372342547
- risk_adjusted_return=-0.19535889854674976

### PULLBACK (n=37, OK)
- mean=0.01859564264974231 median=0.011350737797956922 std=0.1000930692505124
- p10=-0.06666191325014847 p25=-0.041225081854414536 p75=0.09009103023102738 p90=0.11177019728994311
- best=0.22399203583872573 worst=-0.29543568464730285
- win=0.5428571428571428 LD=0.11428571428571428 MDD=-0.06744323710894201 MAE=-0.1585433630560133
- gt5=0.37142857142857144 gt10=0.2 lt-10=0.05714285714285714
- top10% of +PnL share=0.4015468055597703
- EV net T+1open=0.015585999024944501 net_mean=0.015585999024944515
- risk_adjusted_return=-0.05512597590472869

### REACCELERATION (n=117, OK)
- mean=-0.009380126335015221 median=-0.025439418251973267 std=0.14137018538924426
- p10=-0.1635224127552102 p25=-0.11019837030889973 p75=0.0652098950092656 p90=0.17870791628753416
- best=0.41629955947136565 worst=-0.342789598108747
- win=0.42727272727272725 LD=0.19090909090909092 MDD=-0.10073015407990286 MAE=-0.17387408935960166
- gt5=0.2636363636363636 gt10=0.20909090909090908 lt-10=0.3
- top10% of +PnL share=0.5431376049228346
- EV net T+1open=-0.0077376661221337795 net_mean=-0.0077376661221337725
- risk_adjusted_return=-0.12656338519314847

## DIRECT_CHASE by board

- 1板: n=0 status=INSUFFICIENT_SAMPLE mean=None med=None win=None LD=None rar=None
- 2板: n=0 status=INSUFFICIENT_SAMPLE mean=None med=None win=None LD=None rar=None
- 3板: n=29 status=LOW_SAMPLE mean=0.10595643826561625 med=0.09554536069719854 win=0.6538461538461539 LD=0.38461538461538464 rar=-0.07720414271577229
- 4板: n=16 status=LOW_SAMPLE mean=None med=None win=None LD=0.5714285714285714 rar=None
- 5板: n=7 status=INSUFFICIENT_SAMPLE mean=None med=None win=None LD=None rar=None
- 6+板: n=6 status=INSUFFICIENT_SAMPLE mean=None med=None win=None LD=None rar=None

## PULLBACK depth / health

- depth 0~-3%: n=1 mean=None LD=None rar=None
- depth -3%~-7%: n=6 mean=None LD=None rar=None
- depth -7%+: n=30 mean=0.019803730351856837 LD=0.13793103448275862 rar=-0.06199766428786613
- HEALTHY_PULLBACK: n=35 mean=0.019222689722611506 LD=0.12121212121212122 MDD=-0.0692364710590559 rar=-0.05781978823115887
- DANGEROUS_PULLBACK: n=2 mean=None LD=None MDD=None rar=None
- NEUTRAL_PULLBACK: n=0 mean=None LD=None MDD=None rar=None

## REACCELERATION paths

- AFTER_PULLBACK: n=9 mean=None LD=None rar=None
- AFTER_DIVERGENCE: n=87 mean=-0.02351107666551806 LD=0.17073170731707318 rar=-0.1345998697127564
- AFTER_EXTREME: n=18 mean=0.022765448000291323 LD=0.4375 rar=-0.18460775716678196
- DIRECT_REACCEL: n=3 mean=None LD=None rar=None
- STRUCTURE_REPAIRED: n=117 mean=-0.009380126335015221 LD=0.19090909090909092 rar=-0.12656338519314847

## Good-entry gates

- DIRECT_CHASE: NO_EDGE_PROVEN checks={'positive_ev': True, 'win_rate_ok': True, 'ld_ok': False, 'mae_ok': True, 'mdd_ok': True, 'sample_ok': True, 'risk_adj_positive': False}
- FIRST_DIVERGENCE: NO_EDGE_PROVEN checks={'positive_ev': False, 'win_rate_ok': False, 'ld_ok': False, 'mae_ok': False, 'mdd_ok': True, 'sample_ok': True, 'risk_adj_positive': False}
- PULLBACK: NO_EDGE_PROVEN checks={'positive_ev': True, 'win_rate_ok': True, 'ld_ok': True, 'mae_ok': True, 'mdd_ok': True, 'sample_ok': True, 'risk_adj_positive': False}
- REACCELERATION: NO_EDGE_PROVEN checks={'positive_ev': False, 'win_rate_ok': False, 'ld_ok': True, 'mae_ok': True, 'mdd_ok': True, 'sample_ok': True, 'risk_adj_positive': False}

## Answers

- **1_chase_mean_from_few_winners**: 是偏极端驱动：头部约10%样本贡献正收益池的 45%；均值-中位数差=0.03217719682262148. 更关键：收盘到收盘均值=0.03707915760693519，但 T+1开盘买入扣费后净期望=-0.010248723589451517（由高开/滑点吞噬）。
- **2_chase_high_ld_why**: 整体五日跌停率=0.49056603773584906。 3板 LD=0.38461538461538464 mean=0.10595643826561625 4板 LD=0.5714285714285714 mean=None 高连板追涨处于拥挤定价，次日分歧/炸板/补跌概率高。
- **3_pullback_low_ld_why**: 回踩整体 LD=0.11428571428571428（显著低于追涨）。健康回踩 LD=0.12121212121212122；危险回踩 LD=None。风险已部分释放、缩量结构更常见，故跌停率更低。
- **4_best_pullback_type**: {'best': 'health:HEALTHY_PULLBACK', 'risk_adjusted_return': -0.05781978823115887, 'n': 35, 'status': 'OK', 'mean': 0.019222689722611506, 'ld': 0.12121212121212122, 'note': 'Research ranking only; LOW_SAMPLE cells are not proven.'}
- **5_reaccel_no_edge_why**: 再加速整体 T+5 mean=-0.009380126335015221 LD=0.19090909090909092。 AFTER_DIVERGENCE: n=87 mean=-0.02351107666551806 LD=0.17073170731707318 rar=-0.1345998697127564 AFTER_EXTREME: n=18 mean=0.022765448000291323 LD=0.4375 rar=-0.18460775716678196 STRUCTURE_REPAIRED: n=117 mean=-0.009380126335015221 LD=0.19090909090909092 rar=-0.12656338519314847 当前定义偏松，可能混入未完成风险释放的假突破。
- **6_best_board_entry**: {'cell': '3|DIRECT_CHASE', 'risk_adjusted_return': -0.07720414271577229, 'n': 29, 'status': 'LOW_SAMPLE', 'limit_down_rate': 0.38461538461538464, 'note': '按 risk_adjusted_return 排序；LOW_SAMPLE 仅作线索，不构成证明。'}
- **7_continue_reentry_score**: NO — mark REENTRY_SCORE_UNCALIBRATED; do not use for BUY
- **8_risk_adjusted_entry_edge**: NO_EDGE_PROVEN
- **9_ready_for_param_opt**: False
- **10_why_buy_ready_zero**: {'dataset_timing_BUY_READY': 0, 'dataset_timing_BUY_CANDIDATE': 8, 'dataset_timing_WAIT': 294, 'dry_run_buy_ready_n': 0, 'reasons': ['多数样本处于 EXTREME/追涨，trade_timing 强制 WAIT', 'BUY_READY 需 TREND/EARLY + board>=2 + timing>=0.72，阈值未降低', 'reentry_score 未校准，不能作为放宽依据', 'research_only=true，不改 canonical BUY']}
- **overall**: NO_EDGE_PROVEN
- **pullback_net_ev_positive**: True
- **chase_net_ev_positive**: False

## Notes

- BUY thresholds unchanged.
- No LLM / No ML.
- entry_quality & risk_adjusted_entry_score are research-only.
