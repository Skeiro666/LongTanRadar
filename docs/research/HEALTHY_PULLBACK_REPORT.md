# HEALTHY PULLBACK LAB REPORT

- pullback scans: **849** from **250** symbols
- healthy: **79**
- elapsed: 32.99s | LLM: 0 | Token: 0
- cost rate: 0.00252
- verdict: **NO_EDGE_PROVEN**

## By health

- **HEALTHY_PULLBACK**: n=79 status=OK mean=-0.0010833139631391824 win=0.4931506849315068 LD=0.2465753424657534 net_ev=0.0028311068748648194 rar=-0.12705837056064187
- **DANGEROUS_PULLBACK**: n=199 status=OK mean=-0.02911071001065177 win=0.372972972972973 LD=0.34594594594594597 net_ev=-0.012257912170190649 rar=-0.2067199871559225
- **NEUTRAL_PULLBACK**: n=571 status=OK mean=-0.008264577988372462 win=0.44265232974910396 LD=0.1917562724014337 net_ev=-0.002574697207345704 rar=-0.1229667635190316

## Depth / Board

- depth 0~-3%: n=70 mean=-0.0015595824099428586 LD=0.2 net_ev=0.004175755825762746 rar=-0.11801883682820374
- depth -3%~-7%: n=316 mean=-0.018250122492656923 LD=0.254071661237785 net_ev=-0.01037428430920128 rar=-0.15948113732506122
- depth -7%+: n=463 mean=-0.009846930916440564 LD=0.22072072072072071 net_ev=-0.0013158622456505356 rar=-0.13412934818804315
- HP 2板: n=45 mean=0.01998401282385538 LD=0.20512820512820512 net_ev=0.025987679567555717 rar=-0.08244855405835895
- HP 3板: n=8 mean=None LD=None net_ev=None rar=None
- HP 4板: n=3 mean=None LD=None net_ev=None rar=None
- HP 5板: n=3 mean=None LD=None net_ev=None rar=None
- HP 6+板: n=0 mean=None LD=None net_ev=None rar=None

## Buy now vs wait reaccel

- prefer: **BUY_ON_HEALTHY_PULLBACK**
- buy_now: {'n': 79, 'status': 'OK', 'mean': -0.0010833139631391824, 'median': -0.0025662959794695572, 'win': 0.4931506849315068, 'ld': 0.2465753424657534, 'mdd': -0.07934737346897801, 'mae': -0.1800162178049405, 'rar': -0.12705837056064187, 'net_ev': 0.0028311068748648194, 'net_mean': 0.002831106874864823}
- wait_reaccel: {'n': 49, 'status': 'OK', 'mean': -0.03138900222942881, 'median': -0.03436988543371522, 'win': 0.3469387755102041, 'ld': 0.1836734693877551, 'mdd': -0.10252432532303099, 'mae': -0.19316488217210984, 'rar': -0.1469368791766586, 'net_ev': -0.0310803661472408, 'net_mean': -0.031080366147240805}

## Condition importance (net EV drop when removed)

- volume_contraction: 0.004780409949086323
- no_big_red: 0.0006667349568007727
- no_high_open_low_close: 0.00014443678133873455
- no_structure_break: 0.0
- not_volume_dump: 0.0
- down_days_lt_3: -0.00022211803479427888

## Walk-forward

- {'status': 'OK', 'n': 79, 'train': {'n': 47, 'date_start': '2021-02-03', 'date_end': '2026-05-22', 'mean': 0.010582076469440108, 'ld': 0.14893617021276595, 'rar': -0.07411931419899151, 'net_ev': 0.016561776699906598, 'status': 'OK'}, 'validation': {'n': 16, 'date_start': '2026-05-26', 'date_end': '2026-07-03', 'mean': -0.06379559339399939, 'ld': 0.5625, 'rar': -0.33684390304399336, 'net_ev': -0.06034018425940607, 'status': 'LOW_SAMPLE'}, 'test': {'n': 16, 'date_start': '2026-07-06', 'date_end': '2026-08-20', 'mean': None, 'ld': 0.2, 'rar': None, 'net_ev': None, 'status': 'LOW_SAMPLE'}, 'net_ev_sign_stable': False}

## Strict checks

- {'positive_net_ev': True, 'ld_ok': False, 'sample_ok': True, 'wf_sign_stable': False, 'rar_nonneg': False, 'good_entry_gate': False}

## Answers

1. Healthy pullback net EV: 0.0028311068748648194
2. Healthy vs dangerous: {'healthy': {'n': 79, 'status': 'OK', 'mean': -0.0010833139631391824, 'median': -0.0025662959794695572, 'win': 0.4931506849315068, 'ld': 0.2465753424657534, 'mdd': -0.07934737346897801, 'mae': -0.1800162178049405, 'rar': -0.12705837056064187, 'net_ev': 0.0028311068748648194, 'net_mean': 0.002831106874864823}, 'dangerous': {'n': 199, 'status': 'OK', 'mean': -0.02911071001065177, 'median': -0.045327364297705786, 'win': 0.372972972972973, 'ld': 0.34594594594594597, 'mdd': -0.11305639212837928, 'mae': -0.18068315966364096, 'rar': -0.2067199871559225, 'net_ev': -0.012257912170190649, 'net_mean': -0.012257912170190663}}
3. Best depth: {'best': '0~-3%', 'rar': -0.11801883682820374, 'n': 70, 'status': 'OK', 'mean': -0.0015595824099428586, 'median': -0.016759776536312887, 'win': 0.35384615384615387, 'ld': 0.2, 'mdd': -0.0929185088365218, 'mae': -0.19136463385709945, 'net_ev': 0.004175755825762746, 'net_mean': 0.004175755825762743}
4. Best board: {'best': '2', 'rar': -0.08244855405835895, 'n': 45, 'status': 'OK', 'mean': 0.01998401282385538, 'median': 0.03169276659209541, 'win': 0.5897435897435898, 'ld': 0.20512820512820512, 'mdd': -0.061275390174685085, 'mae': -0.14300981007490826, 'net_ev': 0.025987679567555717, 'net_mean': 0.02598767956755572}
5. Path preference: BUY_ON_HEALTHY_PULLBACK
6. Most important condition: volume_contraction
7. Ready for BUY_CANDIDATE research? False
8. Edge: **NO_EDGE_PROVEN**

## Notes

- BUY thresholds unchanged; not wired to BUY pipeline.
- reentry_score remains UNCALIBRATED.
- No LLM / No ML.
