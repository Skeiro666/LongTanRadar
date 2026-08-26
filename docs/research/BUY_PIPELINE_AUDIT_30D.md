# LongTanRadar BUY Pipeline Audit

**Window:** 2026-07-27 → 2026-08-25 (30 days)
**Data:** reports=3 ['2026-08-21', '2026-08-24', '2026-08-25']; snapshots=176; sessions=176; cycles_deduped=11; cycles_raw=20
**Coverage:** calendar_days=30 active_days=3 missing_days=27 coverage_pct=10.0% day_status={'NOT_RUN': 27, 'HAS_REPORT_OVERWRITTEN': 3}

> Read-only audit. No BUY gates / RiskFilter / prompts / thresholds were modified.

## P0 Answers (A–I)

- **A_daily_run:** No — coverage_pct=10.0% (3/30 days with dated reports). status_counts={'NOT_RUN': 27, 'HAS_REPORT_OVERWRITTEN': 3}
- **B_gate_skip:** GATE_SKIP n=29; categories={'DEEP_BUDGET': 23, 'LLM_BUDGET': 6}. These are budget/gate rejects persisted as rating=GATE_SKIP, not full AI council decisions.
- **C_ml_profit_event_news_zero:** Dated report candidate_union.universe historically omitted ml/profit/event/news fields (serialization strip). Snapshots often still carry ml_prediction. Audit MISSING on reports ≠ runtime always computed 0. Post-36ffb97 serialize_signal_fields persists statuses on new reports.
- **D_30d_three_reports:** Only 3 active report days because (1) agent not daily-scheduled, (2) same as_of overwrites dated JSON, (3) missing_days=27. See coverage.per_day.
- **E_autostart:** Production does NOT auto-run daily with agent.autostart=false. Observed report days require manual /api/agent/start, CLI, or a prior autostart session.
- **F_full_council:** full_ai_council=26 / platform_reports=55; gate_skip=29 (deep=23, llm=6)
- **G_deep_budget_leaders:** 22/23 DEEP_BUDGET names look like material candidates (score/leader/board heuristics) blocked solely by max_deep=10 budget — not by weak signals. This is capacity throttling, not a BUY-threshold reject.
- **H_limit_up:** All sampled limit_up blocks mean 'current bar is limit-up → no open' (不追涨停). Suggested audit reason_code=LIMIT_UP_NO_ENTRY. Trading logic unchanged in this audit.
- **I_today_zero_buy:** {'focus_date': '2026-08-25', 'classification': 'AI_DID_NOT_RATE_BUY+BUDGET_GATE_SKIP+AUDIT_FIELD_STRIPPED+SPARSE_CALENDAR_COVERAGE', 'NO_BUY_REASON': 'GATE_SKIP', 'TOP_BLOCKERS': {'GATE_SKIP': 7, 'RATING_NOT_BUY:WATCH': 6, 'RATING_NOT_BUY:AVOID': 1, 'RATING_NOT_BUY:NEUTRAL': 1}, 'DATA_COVERAGE': {'report_persisted': True, 'day_status': 'HAS_REPORT_OVERWRITTEN', 'data_quality': 'LEGACY_STRIPPED_FIELDS', 'window_coverage_pct': 10.0}}

## Execution chain (agent.autostart)

- verdict: Production does NOT auto-run daily with agent.autostart=false. Observed report days require manual /api/agent/start, CLI, or a prior autostart session.
- `serve_lifespan_autostart` active=False — src/ashare/api/app.py lifespan → start_agent(run_now=True) (Only when agent.autostart=true)
- `api_agent_start` active=manual — POST /api/agent/start (Starts daemon loop; UI or operator triggers)
- `api_agent_cycle` active=manual — POST /api/agent/cycle (One-shot cycle)
- `cli_agent` active=manual — python -m ashare.main agent (One-shot run_cycle)
- `cli_research` active=manual — python -m ashare.main research (Research/report only)
- `os_cron` active=False — None (No in-repo cron/Task Scheduler wiring)

## Calendar coverage

- explanation: Dated reports are keyed by as_of and overwrite same-day files. Multiple production_cycles on one as_of collapse to one report day. Days with status=NOT_RUN had no agent/research cycle recorded.
- status_counts: `{'NOT_RUN': 27, 'HAS_REPORT_OVERWRITTEN': 3}`

| Date | Status | Cycles | Report | Note |
|---|---|---:|---|---|
| 2026-07-27 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-07-28 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-07-29 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-07-30 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-07-31 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-01 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-02 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-03 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-04 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-05 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-06 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-07 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-08 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-09 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-10 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-11 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-12 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-13 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-14 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-15 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-16 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-17 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-18 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-19 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-20 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-21 | HAS_REPORT_OVERWRITTEN | 2 | True | 2 cycles same as_of; latest report kept |
| 2026-08-22 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-23 | NOT_RUN | 0 | False | no production_cycles and no dated report |
| 2026-08-24 | HAS_REPORT_OVERWRITTEN | 12 | True | 12 cycles same as_of; latest report kept |
| 2026-08-25 | HAS_REPORT_OVERWRITTEN | 6 | True | 6 cycles same as_of; latest report kept |

## GATE_SKIP detail

- n=29 categories=`{'DEEP_BUDGET': 23, 'LLM_BUDGET': 6}`
- note: GATE_SKIP is a platform_reports rating for budget/gate rejects — not a full AI Council decision.

| Symbol | Date | reason_code | reason_detail | candidate_score | leader_score |
|---|---|---|---|---:|---:|
| 600397.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.5645661608328318 | 0.4851013116527023 |
| 600110.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.5540513880856606 | 0.38458454982498264 |
| 603709.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.5038257747087851 | 0.25854983250129054 |
| 600123.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.48359695727681423 | 0.11503892555280257 |
| 603318.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.46415716479896696 | 0.12691562376816934 |
| 603333.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.4622144531755433 | 0.5651705464879467 |
| 600691.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.4459714246618571 | 0.09325168951006754 |
| 605151.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.4385094949022522 | 0.0933604616254824 |
| 603536.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.4309186972671203 | 0.07167246838224836 |
| 600257.SH | 2026-08-21 | DEEP_BUDGET | DEEP_BUDGET | 0.35778825077122656 | 0.03415690696540903 |
| 600397.SH | 2026-08-24 | LLM_BUDGET | LLM_BUDGET | 0.6114145250774883 | 0.4802319764118713 |
| 002491.SZ | 2026-08-24 | LLM_BUDGET | LLM_BUDGET | 0.6049240858478618 | 0.5194837015854105 |
| 600971.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.5513301158374891 | 0.3085622357261596 |
| 003032.SZ | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.5426320000214332 | 0.6628363783544524 |
| 600123.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.5115250914367003 | 0.21626216600961978 |
| 600257.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.48170889392232297 | 0.13023680786772968 |
| 603318.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.47186287514131847 | 0.07570634070433341 |
| 603333.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.4530608826466127 | 0.5206501408950838 |
| 603980.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.45055760404519934 | 0.04206934489104559 |
| 603709.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.4428914048848009 | 0.08445163300419287 |
| 600691.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.44279936060026726 | -0.0015256363801889883 |
| 603536.SH | 2026-08-24 | DEEP_BUDGET | DEEP_BUDGET | 0.42922107914588414 | 0.044283217288598825 |
| 002963.SZ | 2026-08-25 | LLM_BUDGET | LLM_BUDGET | 0.2548154252631497 | 0.4970916912280468 |
| 600371.SH | 2026-08-25 | LLM_BUDGET | LLM_BUDGET | 0.24889343767629582 | 0.4694574409798928 |
| 003018.SZ | 2026-08-25 | LLM_BUDGET | LLM_BUDGET | 0.2124328873360516 | 0.08722321551797046 |
| 002686.SZ | 2026-08-25 | LLM_BUDGET | LLM_BUDGET | 0.20214961059381817 | 0.33590364931567085 |
| 002081.SZ | 2026-08-25 | DEEP_BUDGET | DEEP_BUDGET | 0.23886986915336186 | 0.44081867377151 |
| 603318.SH | 2026-08-25 | DEEP_BUDGET | DEEP_BUDGET | 0.23675453085734682 | 0.09957076843595682 |
| 002949.SZ | 2026-08-25 | DEEP_BUDGET | DEEP_BUDGET | 0.22178609801535099 | 0.40272218480576466 |

## DEEP_BUDGET

- max_deep=10 n=23 high_quality_blocked=22
- verdict: 22/23 DEEP_BUDGET names look like material candidates (score/leader/board heuristics) blocked solely by max_deep=10 budget — not by weak signals. This is capacity throttling, not a BUY-threshold reject.
- score_summary: `{'n': 23, 'min': 0.221786, 'max': 0.564566, 'mean': 0.442635}`

## Council breakdown (full AI vs GATE_SKIP)

- platform_reports: **55**
- full_ai_council: **26**
- GATE_SKIP: **29** (DEEP_BUDGET=23, LLM_BUDGET=6)
- WATCH=23 AVOID=2 NEUTRAL=1 BUY=0
- chairman llm vs heuristic/cache among full AI: llm=0 heuristic_or_cache=0

## Signal provenance (ML / Profit / Event / News / Valuation)

- why audit showed 0: Dated report candidate_union.universe historically omitted ml/profit/event/news fields (serialization strip). Snapshots often still carry ml_prediction. Audit MISSING on reports ≠ runtime always computed 0. Post-36ffb97 serialize_signal_fields persists statuses on new reports.
- dated_report_universe: `{'ml': {'REPORT_FIELD_ABSENT': 60}, 'profit': {'REPORT_FIELD_ABSENT': 60}, 'event': {'REPORT_FIELD_ABSENT': 60}, 'news': {'REPORT_FIELD_ABSENT': 60}}`
- research_snapshots: `{'ml': {'VALID': 176}, 'profit': {'VALID': 175, 'UNAVAILABLE': 1}, 'event': {'VALID': 176}, 'news': {'VALID': 133, 'MISSING': 6, 'ZERO': 37}, 'valuation': {'UNAVAILABLE': 176}, 'n_snapshots': 176}`

## RiskFilter limit_up (display mapping only)

- n_limit_up_blocks=19 suggested=`LIMIT_UP_NO_ENTRY`
- All sampled limit_up blocks mean 'current bar is limit-up → no open' (不追涨停). Suggested audit reason_code=LIMIT_UP_NO_ENTRY. Trading logic unchanged in this audit.
- trading_logic_unchanged=True

## Production Health Table

| Date | scheduler | candidates | research | council | full_ai | gate_skip | buy | final_buy | data_quality | report |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 2026-07-27 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-07-28 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-07-29 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-07-30 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-07-31 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-01 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-02 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-03 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-04 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-05 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-06 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-07 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-08 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-09 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-10 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-11 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-12 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-13 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-14 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-15 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-16 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-17 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-18 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-19 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-20 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-21 | True | 60 | 20 | 20 | 10 | 10 | 0 | 0 | LEGACY_STRIPPED_FIELDS | True |
| 2026-08-22 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-23 | False | None | None | 0 | 0 | 0 | 0 | 0 | NO_RUN | False |
| 2026-08-24 | True | 60 | 20 | 20 | 8 | 12 | 0 | 0 | LEGACY_STRIPPED_FIELDS | True |
| 2026-08-25 | True | 60 | 20 | 15 | 8 | 7 | 0 | 0 | LEGACY_STRIPPED_FIELDS | True |

## NO_BUY_REASON_DETAIL (per day)

- **2026-07-27** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-07-28** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-07-29** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-07-30** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-07-31** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-01** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-02** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-03** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-04** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-05** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-06** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-07** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-08** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-09** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-10** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-11** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-12** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-13** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-14** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-15** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-16** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-17** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-18** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-19** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-20** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-21** NO_BUY_REASON=`RATING_NOT_BUY:WATCH` blockers=`{'RATING_NOT_BUY:WATCH': 10, 'GATE_SKIP': 10}` coverage=`{'report_persisted': True, 'day_status': 'HAS_REPORT_OVERWRITTEN', 'data_quality': 'LEGACY_STRIPPED_FIELDS', 'window_coverage_pct': 10.0}`
- **2026-08-22** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-23** NO_BUY_REASON=`SYSTEM_NOT_RUN` blockers=`{'NOT_RUN': 1}` coverage=`{'report_persisted': False, 'day_status': 'NOT_RUN', 'data_quality': 'NO_RUN', 'window_coverage_pct': 10.0}`
- **2026-08-24** NO_BUY_REASON=`GATE_SKIP` blockers=`{'GATE_SKIP': 12, 'RATING_NOT_BUY:WATCH': 7, 'RATING_NOT_BUY:AVOID': 1}` coverage=`{'report_persisted': True, 'day_status': 'HAS_REPORT_OVERWRITTEN', 'data_quality': 'LEGACY_STRIPPED_FIELDS', 'window_coverage_pct': 10.0}`
- **2026-08-25** NO_BUY_REASON=`GATE_SKIP` blockers=`{'GATE_SKIP': 7, 'RATING_NOT_BUY:WATCH': 6, 'RATING_NOT_BUY:AVOID': 1, 'RATING_NOT_BUY:NEUTRAL': 1}` coverage=`{'report_persisted': True, 'day_status': 'HAS_REPORT_OVERWRITTEN', 'data_quality': 'LEGACY_STRIPPED_FIELDS', 'window_coverage_pct': 10.0}`

## Config snapshot (execution path)

- `trading.mode` = `backtest`
- `broker.mode` = `paper`
- `agent.autostart` = `False`
- `research.enabled` = `True`
- `ai.enabled` = `True`
- `ai.roundtable` = `True`
- `ai.roundtable_mode` = `sampled`
- `decision.canonical_source` = `platform_council`
- `decision.roundtable_controls_trading` = `False`
- `paper.initial_balance` = `3000`
- `trading.lot_size` = `100`
- `universe.screen.max_price` = `28.0`

**Important:** `roundtable_controls_trading=false` and `canonical_source=platform_council` — legacy Roundtable is **not** the trade decision path.

## Layer counts (summed over dated reports in window)

- Universe raw: **7031**
- Screen filtered: **2358**
- Pool: **120**
- Candidate union: **60**
- Research universe field: **60**
- Council entered (platform_reports): **55**
- Council completed: **55**
- research_rating: `{'WATCH': 23, 'GATE_SKIP': 29, 'AVOID': 2, 'NEUTRAL': 1}`
- trading_action: `{'WAIT_FOR_CONFIRMATION': 22, 'NO_ACTION': 33}`
- RiskFilter status: `{'blocked': 19, 'pass': 7, 'skipped': 29}`
- RiskFilter flags: `{'limit_up': 19, 'DEEP_BUDGET': 23, 'LLM_BUDGET': 6}`
- committee_approve: `{'true': 0, 'false': 55}`
- Final BUY: **0**
- BUY_READY signals: `{'buy_ready_alerts': 0}`

## TODAY BUY PIPELINE

- as_of: **2026-08-25**
- Candidates: **60**
- Research: **20**
- Council: **15**
- BUY rating: **0**
- STRONG_BUY: **0**
- READY entry setup: **0**
- Risk PASS: **0**
- Committee approve: **0**
- Final BUY: **0**
- NO_BUY_REASON: **RATING_NOT_BUY:WATCH**
- Top rejection reasons: `{'RATING_NOT_BUY:WATCH': 6, 'GATE_REJECT:LLM_BUDGET': 4, 'GATE_REJECT:DEEP_BUDGET': 3, 'RATING_NOT_BUY:AVOID': 1, 'RATING_NOT_BUY:NEUTRAL': 1}`

- Window no_buy_reason_distribution: `{'RATING_NOT_BUY:WATCH': 23, 'GATE_REJECT:DEEP_BUDGET': 23, 'RATING_NOT_BUY:AVOID': 2, 'GATE_REJECT:LLM_BUDGET': 6, 'RATING_NOT_BUY:NEUTRAL': 1}`
- Signal availability (missing≠zero): `{'ml_prediction': {'MISSING': 60}, 'profit_score': {'MISSING': 60}, 'event_score': {'MISSING': 60}, 'news_score': {'MISSING': 60}}`

## Funnel table

| Stage | Input | Passed | Rejected | Reject Rate |
|---|---:|---:|---:|---:|
| Universe raw (screen input) | 7031 | 2358 | 4673 | 66.46% |
| Screen → Pool | 2358 | 120 | 2238 | 94.91% |
| Pool → Candidate union | 120 | 60 | 60 | 50.0% |
| Candidate → Council entered | 60 | 55 | 5 | 8.33% |
| Council completed | 55 | 55 | 0 | 0.0% |
| Council → BUY/STRONG_BUY | 55 | 0 | 55 | 100.0% |
| BUY rating → SMALL_POSITION | 0 | 0 | 0 | 0.0% |
| RiskFilter PASS (all canonical) | 55 | 7 | 48 | 87.27% |
| committee_approve true | 0 | 0 | 0 | 0.0% |

## Research gate

- config: `{'enabled': True, 'always_pass_top_n': 3, 'deep_threshold': 0.22, 'light_threshold': 0.12, 'max_deep': 10, 'max_light': 8, 'max_llm_calls': 30, 'min_candidate_score': 0.12, 'min_leader_score': 0.1, 'min_ml_prediction': 0.003, 'min_profit_score': 0.15, 'min_event_score': 0.08, 'min_news_score': 0.12, 'boost_sources': ['news', 'profit', 'event'], 'boost_score_floor': 0.08}`
- reject reasons: `{'union_rejected:NOT_ENOUGH_EVIDENCE': 78, 'union_rejected:RANKING_CUTOFF': 118, 'DEEP_BUDGET': 23, 'union_rejected:INFERRED_DISCOVERY': 3, 'union_rejected:INDUSTRY_MAP_UNAVAILABLE': 2, 'union_rejected:NOT_LIMIT_UP_NEWS_ONLY': 7}`

| Threshold | Value | Fail rate | Fail sum | Obs |
|---|---:|---:|---:|---:|
| min_candidate_score | 0.12 | 0.0% | 0 | 60 |
| min_leader_score | 0.1 | 10.0% | 2 | 20 |
| min_ml_prediction | 0.003 | 0.0% | 0 | 0 |
| min_profit_score | 0.15 | 0.0% | 0 | 0 |
| min_event_score | 0.08 | 0.0% | 0 | 0 |
| min_news_score | 0.12 | 0.0% | 0 | 0 |

Note: independent fail rates treat missing values as fail — useful to spot hard fields (e.g. ML often missing on rows).

## Score distributions (candidate universe rows)

- **candidate_score**: `{'n': 60, 'min': 0.16717, 'p25': 0.406536, 'p50': 0.488933, 'p75': 0.681095, 'p90': 0.827913, 'p95': 0.87512, 'max': 1.08975, 'mean': 0.52102}`
- **leader_score**: `{'n': 20, 'min': 0.087223, 'p25': 0.300169, 'p50': 0.455138, 'p75': 0.916847, 'p90': 1.197638, 'p95': 1.686958, 'max': 1.835139, 'mean': 0.628926}`
- **ml_prediction**: `{'n': 0}`
- **profit_score**: `{'n': 0}`
- **event_score**: `{'n': 0}`
- **news_score**: `{'n': 0}`

## Council / Chairman (snapshots in window)

- snapshots_with_council: **176**
- snapshot ratings: `{'WATCH': 139, 'AVOID': 19, 'NEUTRAL': 13, 'BUY': 5}`
- snapshot actions: `{'WAIT_FOR_CONFIRMATION': 128, 'NO_ACTION': 27, 'WATCH': 17, 'SMALL_POSITION': 4}`
- session index ratings: `{'BUY': 5, 'NEUTRAL': 13, 'WATCH': 139, 'AVOID': 19}`
- BUY/STRONG_BUY share: **2.84%**
- bear_negative_count: **176**
- valuation_unavailable_count: **174**
- stance_counts: `{'event:neutral': 108, 'valuation:neutral': 174, 'quant:bull': 121, 'bear:bear': 176, 'fundamental:neutral': 111, 'fundamental:bull': 54, 'event:bull': 64, 'quant:neutral': 55, 'event:bear': 1, 'event:unknown': 3, 'valuation:bull': 1, 'valuation:bear': 1, 'fundamental:bear': 11}`
- role `event` scores: `{'n': 173, 'min': -0.2, 'p25': 0.0, 'p50': 0.0, 'p75': 0.3, 'p90': 0.5, 'p95': 0.6, 'max': 0.759342, 'mean': 0.162094}`
- role `valuation` scores: `{'n': 176, 'min': -0.3, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'p90': 0.0, 'p95': 0.0, 'max': 0.1, 'mean': -0.001136}`
- role `quant` scores: `{'n': 176, 'min': -0.15, 'p25': 0.35, 'p50': 0.42, 'p75': 0.62, 'p90': 0.68, 'p95': 0.72, 'max': 0.834375, 'mean': 0.45308}`
- role `bear` scores: `{'n': 176, 'min': -0.85, 'p25': -0.75, 'p50': -0.75, 'p75': -0.72, 'p90': -0.65, 'p95': -0.55, 'max': -0.3, 'mean': -0.730511}`
- role `fundamental` scores: `{'n': 176, 'min': -0.8, 'p25': 0.0, 'p50': 0.25, 'p75': 0.35, 'p90': 0.45, 'p95': 0.605, 'max': 0.945479, 'mean': 0.173257}`

## BUY-rated but not Final BUY (case-by-case)

### 002412.SZ (2026-08-22)
- rating=BUY conf=0.6 action=SMALL_POSITION
- scores: candidate=0.9850176691612015 leader=1.296864661628067 ml=0.006338423998002785 profit=1.0 event=0.2571428571428571 news=None
- risk=unknown_no_canonical_row flags=[] approve=True
- **direct_reason:** `APPROVED`
- role_scores: `{'bear': {'score': -0.3, 'stance': 'bear', 'status': 'failed'}, 'valuation': {'score': 0, 'stance': 'neutral', 'status': 'unavailable'}, 'event': {'score': 0.5, 'stance': 'bull', 'status': 'ok'}, 'fundamental': {'score': 0.35, 'stance': 'neutral', 'status': 'ok'}, 'quant': {'score': 0.82, 'stance': 'bull', 'status': 'ok'}}`

### 603958.SH (2026-08-22)
- rating=BUY conf=0.65 action=SMALL_POSITION
- scores: candidate=0.798791321285264 leader=0.8830283330148724 ml=0.006338423998002785 profit=1.0 event=0.2571428571428571 news=None
- risk=unknown_no_canonical_row flags=[] approve=True
- **direct_reason:** `APPROVED`
- role_scores: `{'bear': {'score': -0.3, 'stance': 'bear', 'status': 'failed'}, 'valuation': {'score': 0, 'stance': 'neutral', 'status': 'unavailable'}, 'event': {'score': 0.24285714285714285, 'stance': 'bull', 'status': 'ok'}, 'fundamental': {'score': 0.25, 'stance': 'neutral', 'status': 'ok'}, 'quant': {'score': 0.62, 'stance': 'bull', 'status': 'ok'}}`

### 603958.SH (2026-08-22)
- rating=BUY conf=0.45 action=WAIT_FOR_CONFIRMATION
- scores: candidate=0.6352980656496925 leader=1.0023716622312622 ml=0.006338423998002785 profit=1.0 event=0.2571428571428571 news=-0.02735629801785265
- risk=unknown_no_canonical_row flags=[] approve=False
- **direct_reason:** `NO_VALID_ENTRY_SETUP:WAIT_FOR_CONFIRMATION`
- role_scores: `{'quant': {'score': 0.532877951105645, 'stance': 'bull', 'status': 'failed'}, 'bear': {'score': -0.3, 'stance': 'bear', 'status': 'failed'}, 'event': {'score': 0.532877951105645, 'stance': 'bull', 'status': 'failed'}, 'fundamental': {'score': 0.532877951105645, 'stance': 'bull', 'status': 'failed'}, 'valuation': {'score': 0.0, 'stance': 'neutral', 'status': 'unavailable'}}`

### 002412.SZ (2026-08-22)
- rating=BUY conf=0.65 action=SMALL_POSITION
- scores: candidate=0.9256989101066111 leader=1.1650451970623106 ml=0.006338423998002785 profit=1.0 event=0.2571428571428571 news=None
- risk=unknown_no_canonical_row flags=[] approve=True
- **direct_reason:** `APPROVED`
- role_scores: `{'bear': {'score': -0.3, 'stance': 'bear', 'status': 'failed'}, 'valuation': {'score': 0, 'stance': 'neutral', 'status': 'unavailable'}, 'event': {'score': 0.6, 'stance': 'bull', 'status': 'ok'}, 'fundamental': {'score': 0.35, 'stance': 'neutral', 'status': 'ok'}, 'quant': {'score': 0.78, 'stance': 'bull', 'status': 'ok'}}`

### 603958.SH (2026-08-22)
- rating=BUY conf=0.65 action=SMALL_POSITION
- scores: candidate=0.8524958194326393 leader=1.0023716622312622 ml=0.006338423998002785 profit=1.0 event=0.2571428571428571 news=None
- risk=unknown_no_canonical_row flags=[] approve=True
- **direct_reason:** `APPROVED`
- role_scores: `{'bear': {'score': -0.3, 'stance': 'bear', 'status': 'failed'}, 'valuation': {'score': 0, 'stance': 'neutral', 'status': 'unavailable'}, 'event': {'score': 0.5, 'stance': 'bull', 'status': 'ok'}, 'fundamental': {'score': 0.25, 'stance': 'neutral', 'status': 'ok'}, 'quant': {'score': 0.72, 'stance': 'bull', 'status': 'ok'}}`

## Roundtable vs Platform Council

- report roundtable entries: `[{'as_of': '2026-08-21', 'source': 'disabled', 'controls_trading': False, 'benchmark_only': True, 'schedule_reason': 'sampled_skip_run_1_every_10', 'n_roles': 0}, {'as_of': '2026-08-24', 'source': 'disabled', 'controls_trading': False, 'benchmark_only': True, 'schedule_reason': 'sampled_skip_run_12_every_10', 'n_roles': 0}, {'as_of': '2026-08-25', 'source': 'disabled', 'controls_trading': False, 'benchmark_only': True, 'schedule_reason': 'sampled_skip_run_22_every_10', 'n_roles': 0}]`
- note: Legacy roundtable is benchmark-only when controls_trading=false; canonical_source=platform_council.

## Production cycles

- 2026-08-21 `research_20260822_173908` candidates=60 research=20 buy=0 fills=0
- 2026-08-24 `research_20260824_094859` candidates=61 research=20 buy=0 fills=0
- 2026-08-24 `research_20260824_173241` candidates=64 research=20 buy=0 fills=0
- 2026-08-24 `research_20260824_203849` candidates=62 research=20 buy=0 fills=0
- 2026-08-24 `research_20260824_234902` candidates=60 research=20 buy=0 fills=0
- 2026-08-24 `research_20260825_033805` candidates=60 research=20 buy=0 fills=0
- 2026-08-24 `research_20260825_065322` candidates=60 research=20 buy=0 fills=0
- 2026-08-25 `research_20260825_095032` candidates=None research=0 buy=0 fills=0
- 2026-08-25 `research_20260825_100511` candidates=None research=0 buy=0 fills=0
- 2026-08-25 `research_20260825_153253` candidates=60 research=20 buy=0 fills=0
- 2026-08-25 `research_20260826_090009` candidates=60 research=20 buy=0 fills=0

## Live reconciliation (advisory only)

`{'note': 'Live reconciliation is advisory; not a BUY gate.', 'pending_reassessments': 10, 'trigger_counts': {'BREAK_LIMIT': 10, 'REASSESSMENT_CANDIDATE': 10, 'BREAK_LIMIT_PERSISTED': 10, 'ROUND_TABLE_REASSESS_REQUIRED': 10, 'RESEARCH_LIVE_DIVERGENCE': 8, 'PRICE_WEAKENING': 8, 'primary:RESEARCH_LIVE_DIVERGENCE': 8, 'primary:BREAK_LIMIT_PERSISTED': 2}, 'state_counts_from_snapshot_meta': {}}`

## Paper account

`{'cash': None, 'equity': None, 'positions': 0, 'keys': ['state', 'trades', 'updated_at']}`

## Keyword counts

`{'BUY_READY': 0, 'BUY_rating_canonical': 0, 'STRONG_BUY_rating_canonical': 0, 'BUY_rating_snapshots': 5, 'STRONG_BUY_rating_snapshots': 0, 'SMALL_POSITION_canonical': 0, 'SMALL_POSITION_snapshots': 4, 'committee_approve_true': 0}`

## Bottlenecks (ranked)

### P0: Canonical path: Council/Chairman produced 0 BUY/STRONG_BUY
- id: `COUNCIL_NO_BUY_RATING`
- evidence: `Council entered=55, BUY+STRONG_BUY=0, ratings={'WATCH': 23, 'GATE_SKIP': 29, 'AVOID': 2, 'NEUTRAL': 1}`

### P1: RiskFilter systematically blocks limit-up opens
- id: `RISK_LIMIT_UP`
- evidence: `limit_up flags=19, risk_status={'blocked': 19, 'pass': 7, 'skipped': 29}`

### P2: Research gate budget skips many names before full council
- id: `RESEARCH_GATE_BUDGET`
- evidence: `gate reasons={'union_rejected:NOT_ENOUGH_EVIDENCE': 78, 'union_rejected:RANKING_CUTOFF': 118, 'DEEP_BUDGET': 23, 'union_rejected:INFERRED_DISCOVERY': 3, 'union_rejected:INDUSTRY_MAP_UNAVAILABLE': 2, 'union_rejected:NOT_LIMIT_UP_NEWS_ONLY': 7}`

### None: Snapshots contain BUY ratings but dated report canonical_decisions do not
- id: `SNAPSHOT_BUY_NOT_IN_CANONICAL`
- evidence: `snapshot BUY/STRONG_BUY=5, snapshot SMALL_POSITION=4, canonical BUY=0`

### None: Per-name reasons BUY-rated names did not become Final BUY
- id: `BUY_RATED_CASE_REASONS`
- evidence: `{'APPROVED': 4, 'NO_VALID_ENTRY_SETUP:WAIT_FOR_CONFIRMATION': 1}`

## Final answers

- **why_no_buy:** `{'id': 'COUNCIL_NO_BUY_RATING', 'severity': 'P0', 'title': 'Canonical path: Council/Chairman produced 0 BUY/STRONG_BUY', 'evidence': "Council entered=55, BUY+STRONG_BUY=0, ratings={'WATCH': 23, 'GATE_SKIP': 29, 'AVOID': 2, 'NEUTRAL': 1}", 'rank': 'P0'}`
- **too_few_candidates:** `False`
- **research_gate_too_strict:** `False`
- **ml_too_strict:** `False`
- **council_too_conservative:** `True`
- **chairman_too_conservative:** `True`
- **no_small_position:** `True`
- **riskfilter_all_reject:** `False`
- **committee_approve_issue:** `False`
- **paper_cash_lot_issue:** `True`
- **live_recon_mis_kill:** `False`
- **buy_ready_without_approve:** `False`
- **roundtable_vs_council:** `{'canonical_source': 'platform_council', 'roundtable_controls_trading': False}`
- **ml_dist:** `{'n': 0}`
- **candidate_dist:** `{'n': 60, 'min': 0.16717, 'p25': 0.406536, 'p50': 0.488933, 'p75': 0.681095, 'p90': 0.827913, 'p95': 0.87512, 'max': 1.08975, 'mean': 0.52102}`
- **n_buy_rated_cases_explained:** `5`
- **live_recon_summary:** `{'pending': 10, 'states': {}}`

---
Audit complete. No strategy parameters were changed.