# Full System Tuning Report

Generated: 2026-04-27T12:15:58.067701+00:00

## Scope
- ID pattern: Log Dump/15_mazes_hard_*.txt
- OOD pattern: Log Dump/15_mazes_very_hard_*.txt
- Files per group: 2
- Status source of truth: preflight_dump_gate.py --json

## ID Per-File Results
| File | Status | Warn | Fail | Auto | Trust | Guard | Drift | Phase/Micro |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15_mazes_hard_20260427_050233.txt | PASS | 0 | 0 | 0.8002 | 0.6810 | 0.5081 | N | 7/18 |
| 15_mazes_hard_20260427_045228.txt | PASS | 0 | 0 | 0.8074 | 0.7086 | 0.5218 | N | 7/18 |

## OOD Per-File Results
| File | Status | Warn | Fail | Auto | Trust | Guard | Drift | Phase/Micro |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

## Group Means
- ID: auto=0.8038, trust=0.6948, trust_floor=0.5874, guard=0.5150
- OOD: auto=0.0000, trust=0.0000, trust_floor=0.0000, guard=0.0000

## Delta (ID - OOD)
- autonomy_mean: 0.8038
- trust_delib_mean: 0.6948
- trust_id_ood_delta: 0.6948
- guard_utility_mean: 0.5150
- learned_only_rate_mean: 0.7908
- hardcoded_only_rate_mean: 0.0103
- mixed_rate_mean: 0.0266
- phase1_intervention_utility_win3_mean: -0.5506
- projection_effectiveness_score_mean: 0.8169

## Status and Drift
- ID status counts: {'PASS': 2}
- OOD status counts: {}
- ID drift count: 0
- OOD drift count: 0

## Regression Flags
- status_not_all_pass: clear
- drift_detected: clear
- trust_drop_exceeds_threshold: TRIGGERED
- trust_mean_below_target: TRIGGERED
- trust_floor_below_target: TRIGGERED
- trust_id_ood_delta_exceeds_target: TRIGGERED
- autonomy_drop_exceeds_threshold: TRIGGERED
- guard_drop_exceeds_threshold: TRIGGERED

## Progression Consistency
- Pattern: Log Dump/15_mazes_*.txt
- Files checked: 10
- Files with issues: 0
- Total issues: 0
- Status: PASS

## Recommendations
- Prioritize OOD trust calibration and arbitration retuning before expanding OOD severity.
- Raise trust mean through calibration-focused updates before advancing trust phases.
- Address low-trust floor slices before enabling stricter trust enforcement.
- Reduce ID-OOD trust gap before promoting OOD curriculum severity.
