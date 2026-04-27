# Full System Tuning Report

Generated: 2026-04-27T01:49:28.907146+00:00

## Scope
- ID pattern: Log Dump/15_mazes_hard_*.txt
- OOD pattern: Log Dump/15_mazes_very_hard_*.txt
- Files per group: 3
- Status source of truth: preflight_dump_gate.py --json

## ID Per-File Results
| File | Status | Warn | Fail | Auto | Trust | Guard | Drift | Phase/Micro |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15_mazes_hard_20260426_201929.txt | PASS | 0 | 0 | 0.8053 | 0.7564 | 0.5143 | N | 7/18 |
| 15_mazes_hard_20260426_201351.txt | PASS | 0 | 0 | 0.8161 | 0.7577 | 0.5181 | N | 7/18 |
| 15_mazes_hard_20260426_201054.txt | PASS | 0 | 0 | 0.8027 | 0.7969 | 0.5139 | N | 7/18 |

## OOD Per-File Results
| File | Status | Warn | Fail | Auto | Trust | Guard | Drift | Phase/Micro |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15_mazes_very_hard_20260426_195515.txt | PASS | 0 | 0 | 0.8002 | 0.6794 | 0.5000 | N | 7/18 |
| 15_mazes_very_hard_20260426_193009.txt | PASS | 0 | 0 | 0.7759 | 0.6655 | 0.4925 | N | 7/18 |
| 15_mazes_very_hard_20260426_180941.txt | PASS | 0 | 0 | 0.7350 | 0.5000 | 0.4908 | N | 7/18 |

## Group Means
- ID: auto=0.8081, trust=0.7703, guard=0.5154
- OOD: auto=0.7704, trust=0.6150, guard=0.4944

## Delta (ID - OOD)
- autonomy_mean: 0.0377
- trust_delib_mean: 0.1554
- guard_utility_mean: 0.0210
- learned_only_rate_mean: 0.0431
- hardcoded_only_rate_mean: -0.0068
- mixed_rate_mean: -0.0361
- phase1_intervention_utility_win3_mean: 0.4910
- projection_effectiveness_score_mean: 0.0437

## Status and Drift
- ID status counts: {'PASS': 3}
- OOD status counts: {'PASS': 3}
- ID drift count: 0
- OOD drift count: 0

## Regression Flags
- status_not_all_pass: clear
- drift_detected: clear
- trust_drop_exceeds_threshold: TRIGGERED
- autonomy_drop_exceeds_threshold: clear
- guard_drop_exceeds_threshold: clear

## Progression Consistency
- Pattern: Log Dump/15_mazes_*.txt
- Files checked: 15
- Files with issues: 0
- Total issues: 0
- Status: PASS

## Recommendations
- Prioritize OOD trust calibration and arbitration retuning before expanding OOD severity.
