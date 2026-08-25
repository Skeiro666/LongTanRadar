# ENTRY DATASET REPORT

- events: **8863**
- symbols: 1157
- trading days covered: 1462 (2020-04-13 -> 2026-08-24)
- PRIMARY execution: **T+1_open_net**
- research scale (>=3000): **True**
- pullback edge verdict: **NO_EDGE_PROVEN**
- LLM/ML/Token: 0/0/0

## Expand status

- {'note': 'EM zt_pool empty; expanded via index+mainboard bars', 'cached_after': 1157, 'downloaded_this_run': 899, 'still_missing': 1924, 'n_events': 8863, 'research_scale_ok': True, 'pullback_edge': 'NO_EDGE_PROVEN', 'modes': {'DIRECT_CHASE': 1740, 'FIRST_DIVERGENCE': 2708, 'PULLBACK': 1238, 'REBREAKOUT': 0, 'REACCELERATION': 3177}, 'llm': 0, 'tokens': 0}

## By mode (PRIMARY = T+1 open net)

- **DIRECT_CHASE**: n=1740 quality=STRONG_SAMPLE net=-0.015720883154594963 win=0.3854166666666667 LD=0.5225694444444444 rar=-0.3364890653725219
- **FIRST_DIVERGENCE**: n=2708 quality=STRONG_SAMPLE net=-0.011275729195952133 win=0.38928172683289913 LD=0.2761443989579457 rar=-0.20811567823620053
- **PULLBACK**: n=1238 quality=STRONG_SAMPLE net=-0.005005595955627673 win=0.4108463434675431 LD=0.06655710764174198 rar=-0.10583916466954724
- **REBREAKOUT**: n=0 quality=INSUFFICIENT_SAMPLE net=None win=None LD=None rar=None
- **REACCELERATION**: n=3177 quality=STRONG_SAMPLE net=-0.007076716645961562 win=0.4216182048040455 LD=0.15960809102402024 rar=-0.15523609568139723

## Pullback by health

- **HEALTHY_PULLBACK**: n=1122 quality=STRONG_SAMPLE net=-0.00394640764875554 LD=0.06781193490054249 rar=-0.10583368278071238
- **DANGEROUS_PULLBACK**: n=116 quality=STRONG_SAMPLE net=-0.015559310076353621 LD=0.05405405405405406 rar=-0.1060729485129715
- **NEUTRAL_PULLBACK**: n=0 quality=INSUFFICIENT_SAMPLE net=None LD=None rar=None

## Limit-up history index

- {'n_symbols': 1157, 'n_dates': 1608, 'n_limit_up_rows': 24064, 'date_start': '2020-01-02', 'date_end': '2026-08-25', 'source': 'daily_bars.limit_up', 'note': "Rebuilt from as-of bars; not backfilled from today's zt pool."}
