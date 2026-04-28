# MV Integration + Learned-Only Lift Tuning Plan V1

## Objective

Tune the runtime so MV is integrated as a stronger learned signal while reducing visible hard intervention behavior.

Primary goals:
- Increase learned-only decision share.
- Reduce intervention/objective-override frequency to a barely noticeable rate.
- Keep safety and completion reliability intact.

## Baseline (Latest x5, 15-maze hard batch)

Reference window:
- `Log Dump/15_mazes_hard_20260427_144001.txt`
- `Log Dump/15_mazes_hard_20260427_143157.txt`
- `Log Dump/15_mazes_hard_20260427_142211.txt`
- `Log Dump/15_mazes_hard_20260427_141704.txt`
- `Log Dump/15_mazes_hard_20260427_141022.txt`

Observed aggregate baseline:
- `learned_only`: 73.1%
- `mixed`: 9.3%
- `hardcoded_only`: 2.3%
- `unknown`: 15.4%
- intervention rate: 11.56%
- objective-override rate: 10.92%
- reasoning confidence mean: 0.0
- MV preplan ready coverage: 100%

## Target Outcomes

Primary rollout targets (phase-gated):
- `learned_only >= 84%` (Phase 2 target)
- `learned_only >= 90%` (Phase 4 target)
- `intervention_rate <= 6%` (Phase 2 target)
- `intervention_rate <= 3%` (Phase 4 target)
- `objective_override_rate <= 5%` (Phase 2 target)
- `objective_override_rate <= 2%` (Phase 4 target)
- `hardcoded_only <= 1.0%`
- `unknown <= 8%`
- reasoning confidence non-zero and informative in steady-state windows.

Safety invariants (must never regress):
- no increase in severe safety events,
- no increase in unresolved objective regressions,
- no drop in run completion reliability for hard-15 batches.

## Operating Rule

- Only one micro stage is active at a time.
- Do not advance until the stage validation gates pass.
- If any safety/stability gate fails, roll back one stage and freeze progression.

## Phase + Micro Structure

### Phase MVT0: Instrumentation and Gate Reliability

#### `mvt0.m1_preflight_parser_hardening`
What:
- Fix `preflight_dump_gate.py` numeric parsing for `refine_passes` style values (`"0."` and float-like strings).
- Add tolerant numeric coercion utility used by all numeric fields.

Why:
- Automated health checks must be reliable before behavior tuning.

Touchpoints:
- `preflight_dump_gate.py`

Exit:
- Preflight runs without parser errors on latest hard-15 dumps.

#### `mvt0.m2_intervention_taxonomy_lock`
What:
- Standardize intervention tags and reasons in step logs.
- Ensure objective override, safety override, and budget-hold are distinct and countable.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- Every intervention has exactly one canonical intervention type.

#### `mvt0.m3_reasoning_conf_signal_enable`
What:
- Wire meaningful runtime values into `telemetry_reasoning_conf` and margin fields.
- Prevent flat-zero confidence output unless signal is truly unavailable.

Touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`
- `runtime/app_runtime.py`

Exit:
- Batch-level `reasoning_conf_mean > 0` and non-trivial variance.

### Phase MVT1: MV-to-Learned Routing Bias Lift

#### `mvt1.m1_mv_prior_weight_rebalance`
What:
- Increase MV soft-prior influence in learned scoring path only.
- Keep hard override channels unchanged in this micro.

Touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`
- `runtime/app_runtime.py`

Exit:
- `learned_only` rises by at least +3 points versus baseline with no safety regression.

#### `mvt1.m2_mv_disagreement_dynamic_relief`
What:
- Refine disagreement gating so confident/fresh MV is down-weighted less aggressively when local-map contradiction is weak.
- Keep strict suppression under high contradiction.

Touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- `unknown` channel rate decreases and `mixed` shifts toward `learned_only`.

#### `mvt1.m3_objective_evidence_quality_gate`
What:
- Tighten objective-routing entry so objective pressure only ramps when evidence quality is high and persistent.
- Require freshness + confidence + consistency window for MV objective activation.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Objective activations are fewer but higher quality.

### Phase MVT2: Intervention Rate Compression (Soft-First)

#### `mvt2.m1_soft_substitution_before_override`
What:
- Before objective override fires, apply a soft learned-bias substitution pass with strict margin limits.
- Use override only if soft substitution fails gates.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- intervention rate drops by at least 25% from baseline without completion loss.

#### `mvt2.m2_override_budget_strictness_tuning`
What:
- Lower non-critical override budget and strengthen budget-hold behavior.
- Decay budget slower within short windows to prevent override bursts.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- consecutive override streaks shorten; objective override rate decreases.

#### `mvt2.m3_unresolved_context_override_guard`
What:
- Add stronger unresolved-context veto for objective override in high-unknown/high-frontier states unless progression confidence is sufficient.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- fewer overrides in unresolved map states; no rise in deadlock loops.

### Phase MVT3: Memory-Driven Learned Selection Lift

#### `mvt3.m1_cause_effect_priority_lift`
What:
- Increase effect of high-confidence cause-effect semantic recalls in learned selection path.
- Keep penalty clipping bounded.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- `learned_only` rises while `unknown` falls.

#### `mvt3.m2_stm_to_semantic_promotion_quality_tuning`
What:
- Tune STM prune/reinforce thresholds for higher-quality semantic promotion under hard mazes.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Higher semantic reinforcement hit rate during runs.

#### `mvt3.m3_pattern_uncertainty_feedback_loop`
What:
- Feed pattern uncertainty directly into learned path confidence scaling to avoid late hardcoded takeovers.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- reduced `hardcoded_only` tails in late-episode sections.

### Phase MVT4: Objective Override Near-Invisibility

#### `mvt4.m1_objective_excitement_soft_capture_refine`
What:
- Increase soft objective excitement effectiveness so capture pressure remains mostly learned-path.
- Narrow hard objective override trigger window.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- objective override rate <= 2.5% in hard-15 validation window.

#### `mvt4.m2_terminal_and_frontier_guard_coherence`
What:
- Improve coherence between terminal guard, frontier lock, and objective pressure so fallback to hard override is rare.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- override events are mostly safety-critical or final-edge cases.

#### `mvt4.m3_phase_policy_cap_for_hardcoded_channel`
What:
- Add explicit policy cap target for hardcoded channel activation in normal operation.
- Keep emergency bypass for safety-critical events.

Touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- `hardcoded_only <= 1.0%` while safety remains stable.

### Phase MVT5: Validation, Rollout, and Freeze

#### `mvt5.m1_batch_validation_matrix`
What:
- Validate on:
  - hard: `15 mazes x5`
  - very hard: `15 mazes x3`
  - mixed random start batches.

Exit:
- All core targets pass in at least two consecutive cycles.

#### `mvt5.m2_canonical_report_and_gate_update`
What:
- Add/confirm canonical report fields for:
  - learned-only rate,
  - intervention rate,
  - objective override rate,
  - unknown rate,
  - reasoning confidence distribution.

Touchpoints:
- `tuning/canonical_metrics_schema.json`
- `tuning/canonical_compare.py`
- `tuning/generate_tuning_report.py`

Exit:
- report emits new fields and gate thresholds are enforceable.

#### `mvt5.m3_freeze_and_regression_guard`
What:
- Freeze tuned defaults after passing matrix.
- Add regression guard policy and rollback trigger thresholds.

Touchpoints:
- `runtime_kernel/integration/kernel_env_defaults.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- Stable defaults committed and guarded.

## Metrics Contract for This Plan

Track per run and aggregate across validation windows:
- `learned_only_rate`
- `mixed_rate`
- `hardcoded_only_rate`
- `unknown_rate`
- `intervention_rate`
- `objective_override_rate`
- `mv_preplan_ready_coverage`
- `mv_beam_equivalent_rate`
- `mv_objective_activate_rate`
- `reasoning_conf_mean`
- `reasoning_conf_std`
- completion ratio and unresolved objective warnings

## Stop Conditions

Immediately halt advancement when any occurs:
- safety regression or severe event increase,
- completion reliability drop > 3 points from baseline,
- unresolved objective warning trend rises over two consecutive windows,
- oscillatory override bursts reappear after a reduction stage.

## Fast-Track Execution Notes

When all gates are green, allow two micro stages in one cycle for MVT1 and MVT2 only.
Do not fast-track MVT4 and MVT5.

## Immediate Next Micro to Start

- Start with `mvt0.m1_preflight_parser_hardening` so automated gating is reliable.
- Then run `mvt0.m2_intervention_taxonomy_lock` and `mvt0.m3_reasoning_conf_signal_enable` before any behavior-weight tuning.
