# Unified Long-Horizon Operator Checklist V1

Use this checklist with the unified roadmap to make promotion decisions consistent and auditable.

Companion plan:
- [UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md](UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md)

## Window-Level Decision Record (Use Every Phase)

Record these fields for every evaluation window:
- active_phase_id
- window_id
- run_recipe_id
- pass_fail
- promote_hold_rollback
- safety_breach_flag
- top_anomaly_tags
- root_cause_summary
- next_window_recipe

Required artifacts every window:
- preflight output summary
- phase metric summary snapshot
- decision note (promote, hold, rollback)
- rollback rationale (if rollback)

## Global Hard Stops

Do not promote if any of the following are true:
- safety-critical breach is unresolved
- required artifact bundle is incomplete
- pass criteria are met only by malformed or partial dumps
- deterministic replay is unavailable for sampled failure traces

## Phase Checklist Map (U00-U42)

### Block A: WB

- U00 (WB0)
pass_fail fields: dump_integrity_pass, preflight_coverage_complete
required artifacts: full dump list, preflight coverage report, run protocol snapshot

- U01 (WB1)
pass_fail fields: anchor_logic_anomaly_count, unexpected_objective_force_without_anchor
required artifacts: anchor reason telemetry summary, objective gate audit sample

- U02 (WB2)
pass_fail fields: guard_override_rate, learned_only_rate, unresolved_objective_override_rate
required artifacts: behavior screen summary, dual-evidence gate report

- U03 (WB3)
pass_fail fields: player_localization_accuracy_hard, exit_localization_accuracy_hard, player_localization_accuracy_vhard, exit_localization_accuracy_vhard
required artifacts: localization metric report, contradiction debt summary

- U04 (WB4)
pass_fail fields: completion_ratio_delta_win2, guard_override_delta_win2
required artifacts: completion trend report, intervention utility trend

- U05 (WB5)
pass_fail fields: perturbation_recovery_within_one_window, contradiction_recovery_pass
required artifacts: perturbation experiment logs, recovery comparison report

- U06 (WB6)
pass_fail fields: attenuation_step_pass, completion_drop_vs_wb4_median
required artifacts: attenuation step report, unresolved override trend

- U07 (WB7)
pass_fail fields: shadow_disagreement_rate, disagreement_linked_catastrophic_failure_rate
required artifacts: beam-shadow disagreement audit, failure linkage report

- U08 (WB8)
pass_fail fields: mixed_window_pass_streak, localization_floor_maintained
required artifacts: cutover stability pack, emergency rollback drill snapshot

### Block B: SC

- U09 (SC0)
pass_fail fields: sc_telemetry_coverage, preflight_sc_parse_pass
required artifacts: SC telemetry schema checklist, parser verification output

- U10 (SC1)
pass_fail fields: simon_replay_rate_short, simon_invalid_action_rate
required artifacts: Simon short-span results, latency consistency summary

- U11 (SC2)
pass_fail fields: simon_len4_accuracy, simon_len5_accuracy, recovery_next_trial_rate
required artifacts: span-wise confusion matrix, delayed replay report

- U12 (SC3)
pass_fail fields: cell_intent_validity_rate, cell_to_cursor_execution_success, cell_error_manhattan_median
required artifacts: kernel intent schema validation, executor outcome summary

- U13 (SC3.5)
pass_fail fields: pointer_overshoot_rate, click_timing_miss_rate, landing_variance_stability
required artifacts: pointer dynamics calibration report, board-size comparison summary

- U14 (SC4)
pass_fail fields: cursor_exact_hit_easy, cursor_exact_hit_hard, cursor_manhattan_error_median
required artifacts: cursor localization accuracy report, calibration bucket summary

- U15 (SC4.5)
pass_fail fields: triad_consistency_rate, drift_incidents_per_100_steps
required artifacts: perception-action consistency log, mismatch confidence analysis

- U16 (SC5)
pass_fail fields: cursor_target_acquisition_success, cursor_efficiency_ratio, cursor_jitter_trend
required artifacts: target pursuit episode report, distractor robustness summary

- U17 (SC6)
pass_fail fields: dual_task_completion_rate, single_task_degradation_vs_baseline
required artifacts: dual-task benchmark report, memory-load tradeoff summary

- U18 (SC6.5)
pass_fail fields: ood_relative_degradation, intervention_spike_under_shift
required artifacts: shifted-distribution evaluation pack, recovery latency report

- U19 (SC7)
pass_fail fields: maze_completion_delta, learned_only_delta, unresolved_override_delta
required artifacts: warmup-to-maze transfer report, delta dashboard snapshot

- U20 (SC7.5)
pass_fail fields: recovery_success_rate, mean_time_to_safe_state, override_trace_completeness
required artifacts: supervisor drill logs, human override audit bundle

### Block C: MV-D

- U21 (MV-D0)
pass_fail fields: schema_version_locked, validator_pass_rate
required artifacts: mv_frame_v1 schema document, validator test output

- U22 (MV-D1)
pass_fail fields: structured_write_success_rate, sampled_equivalence_pass_rate
required artifacts: dual-write status report, sampled equivalence diff summary

- U23 (MV-D2)
pass_fail fields: retrieval_latency_p95, retrieval_correctness_pass
required artifacts: retrieval benchmark report, feature adapter integration test

- U24 (MV-D3)
pass_fail fields: prompt_token_usage_delta, planner_quality_regression_flag
required artifacts: prompt payload comparison, quality parity report

- U25 (MV-D4)
pass_fail fields: structured_first_stability_streak, tooling_gap_count
required artifacts: structured-first cutover report, ASCII-debug fallback verification

### Block D: RG

- U26 (RG0)
pass_fail fields: contract_test_pass_grid, contract_test_pass_mock_realtime
required artifacts: interface contract test bundle, adapter conformance report

- U27 (RG1)
pass_fail fields: decision_latency_p95, budget_overrun_frequency, degraded_mode_recovery_pass
required artifacts: realtime latency profile, watchdog activation log

- U28 (RG2)
pass_fail fields: intent_to_action_fidelity, action_invalidation_rate, sequence_stability
required artifacts: hierarchical control trace pack, actuator determinism report

- U29 (RG3)
pass_fail fields: temporal_consistency_score, delayed_reward_attribution_stability
required artifacts: temporal memory evaluation, long-horizon utility summary

- U30 (RG4)
pass_fail fields: stress_degradation_within_band, stress_safety_event_rate
required artifacts: adversarial and OOD stress suite report, recovery latency summary

- U31 (RG5)
pass_fail fields: unsafe_action_interception_success, safe_recovery_success, override_audit_completeness
required artifacts: supervisor safety drill pack, intervention event ledger

- U32 (RG6)
pass_fail fields: multi_game_adapter_reuse_pass, core_tooling_regression_flag
required artifacts: pilot game comparison report, portability assessment

### Block E: Robustness, Governance, Release

- U33
pass_fail fields: hidden_holdout_degradation_within_band
required artifacts: holdout-only evaluation report, anti-overfit drift summary

- U34
pass_fail fields: unresolved_high_severity_exploit_count
required artifacts: exploit detector output, tagged trace export bundle

- U35
pass_fail fields: retained_skill_regression_flag
required artifacts: retention suite dashboard, forgetting trend report

- U36
pass_fail fields: required_genre_pass_count, cross_game_floor_maintained
required artifacts: cross-genre benchmark matrix, gate decision summary

- U37
pass_fail fields: overload_safe_mode_pass, overload_recovery_latency_within_budget
required artifacts: resource exhaustion stress pack, degraded-mode validation

- U38
pass_fail fields: intervention_ladder_activation_correctness, intervention_trace_completeness
required artifacts: escalation ladder drill report, intervention audit traces

- U39
pass_fail fields: high_severity_failure_family_mapping_rate
required artifacts: failure clustering report, family-level remediation plan

- U40
pass_fail fields: storage_growth_within_budget, retrieval_latency_within_budget
required artifacts: retention policy report, long-run storage churn benchmark

- U41
pass_fail fields: release_channel_promotion_cycle_pass, rollback_drill_pass
required artifacts: channel promotion log, rollback snapshot verification

- U42
pass_fail fields: critical_security_violation_count, policy_guard_test_pass
required artifacts: security hardening report, misuse threat test summary

## Operator Sign-Off Template

- phase_id:
- window_id:
- pass_fail:
- decision:
- blocker_flags:
- rollback_required:
- reviewed_by:
- timestamp:
