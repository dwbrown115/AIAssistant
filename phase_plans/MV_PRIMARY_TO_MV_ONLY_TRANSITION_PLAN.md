# MV Input Transition Plan V1

## Objective

Prepare a safe, evidence-driven transition from beam-dominant vision input to MV-dominant input, and then MV-only vision input.

This plan keeps decision selection in the kernel. MV is not an independent proposer; it is a vision input channel the kernel evaluates, similar to how beam input is evaluated today.

## Core Trust Contract

Decision authority order:
- Manual input (highest authority)
- Kernel-evaluated MV input, only when `mv_confidence >= 0.75` and facts-fit checks pass
- Beam/legacy vision input only as transition fallback guard

Additional rule:
- MV low-confidence outputs are hypotheses, not authoritative facts.

## Operating Constraints

- No regression in safety floors or completion rate.
- No increase in deadlock or oscillation loops.
- No hardcoded deterministic path shortcuts.
- Every MV input acceptance or rejection decision must be explainable from telemetry.

## Success Targets

- Kernel uses valid high-confidence MV input earlier for directional quality.
- Beam input dependence decreases stage by stage.
- Arbitration path remains active (not flatlined).
- MV-only vision input mode can be enabled and rolled back safely.

## Phase + Micro Structure

### Phase MVT0: Baseline and Instrumentation Contract

#### `mvt0.m1_authority_tier_telemetry`
What:
- Emit per-step authority tier: `manual`, `mv_input_primary`, `beam_guard`, `fallback`.

Why:
- Transition quality cannot be tuned without explicit control-source visibility.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Every step includes authority tier and source reason.

#### `mvt0.m2_mv_input_evaluation_schema`
What:
- Add canonical MV input evaluation payload fields:
  - `mv_confidence`
  - `facts_fit`
  - `input_accepted`
  - `input_rejection_reason`
  - `contradiction_debt`

Why:
- We need stable metrics across batches and stages.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- MV input evaluation events are queryable and consistently labeled.

#### `mvt0.m3_arbitration_health_counters`
What:
- Add counters for arbitration activity, confidence, and intervention usage.

Why:
- Current risk is inactive arbitration despite strong MV signal quality.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/parallel_reasoning_engine.py`

Exit:
- Batch summaries include arbitration activity and confidence distributions.

### Phase MVT1: MV-Primary Input with Beam Guard

#### `mvt1.m1_trust_threshold_enforcement`
What:
- Enforce `mv_confidence >= 0.75` before MV input is allowed to influence kernel scoring.

Why:
- Align behavior with explicit trust policy.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- No low-confidence MV input influences final selection except through explicit probe mode.

#### `mvt1.m2_facts_fit_required_gate`
What:
- Require facts-fit checks against known local map and contradiction debt before kernel acceptance.

Why:
- Confidence alone is insufficient when local evidence disagrees.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Kernel-used high-confidence MV inputs show `facts_fit=1`.

#### `mvt1.m3_beam_guard_only_mode`
What:
- Keep beam input only as a guard path for hard contradiction or high-risk contexts.

Why:
- Maintain safety while MV input becomes primary in normal contexts.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- Beam is no longer the primary vision input in non-contradictory contexts.

### Phase MVT2: Low-Confidence MV Probe Discipline

#### `mvt2.m1_probe_mode_for_low_confidence`
What:
- Treat low-confidence MV as optional probes with bounded budget.

Why:
- Preserve learning opportunities without policy destabilization.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Low-confidence MV uses `mv_probe` path with strict budget control.

#### `mvt2.m2_probe_outcome_scoring`
What:
- Score probe usefulness by immediate contradiction outcome and near-horizon progress.

Why:
- Probe behavior should improve calibration over time.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Probe reports include utility score and contradiction result.

#### `mvt2.m3_probe_budget_adaptation`
What:
- Dynamically tighten or relax probe budget from recent utility trend.

Why:
- Avoid fixed budgets that are too permissive or too restrictive.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Probe budget contracts under poor utility and expands under stable utility.

### Phase MVT3: Arbitration Reactivation and Trust Rebalance

#### `mvt3.m1_parallel_reactivation`
What:
- Ensure parallel reasoning enters active path with nonzero confidence updates.

Why:
- MV input cannot influence final selection if arbitration is effectively bypassed.

Touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`
- `runtime/app_runtime.py`

Exit:
- `parallel_reasoning_engine` shows `steps > 0` and nonzero confidence in normal episodes.

#### `mvt3.m2_terminal_trust_rebalance`
What:
- Recalibrate terminal-guidance trust scaling so it does not suppress valid MV input.

Why:
- Persistent negative trust drift can over-penalize good MV paths.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- Terminal trust remains bounded without persistent collapse.

#### `mvt3.m3_intervention_policy_activation`
What:
- Enable intervention only when confidence and facts-fit conditions are satisfied.

Why:
- Intervention should be selective, not permanently off or overactive.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Nonzero intervention activity with stable safety metrics.

### Phase MVT4: Beam Input De-Weight Ladder and MV-Only Vision Input

#### `mvt4.m1_stage_a_guard_only`
What:
- Beam input active only as contradiction/high-risk guard.

Exit:
- Beam guard usage decreases while completion and safety remain stable.

#### `mvt4.m2_stage_b_veto_only`
What:
- Beam input only vetoes hard contradictions; no normal-route influence role.

Exit:
- Kernel-used MV action share increases without contradiction spikes.

#### `mvt4.m3_stage_c_mv_only_with_killswitch`
What:
- Enable MV-only vision input mode with emergency fallback switch.

Exit:
- MV-only remains stable for required validation windows, with rollback path intact.

## Promotion Gates (All Required)

- High-confidence input quality:
  - For `mv_confidence >= 0.75` and `facts_fit=1`, kernel-use rate >= 0.80.
- Kernel-used high-confidence contradiction rate:
  - Contradiction or rollback rate on kernel-used high-confidence MV actions <= 0.10.
- Arbitration health:
  - Nonzero arbitration confidence and activity in >= 90% of validation episodes.
- Beam dependency trend:
  - Beam guard/veto usage decreases each stage without safety/completion regressions.
- Stability safeguards:
  - No deadlock-loop increase versus baseline.

## Validation Matrix

- Per phase stage, run:
  - Hard: 15-maze batch x2
  - Very-hard: 15-maze batch x2
- Compare against baseline for:
  - Completion rate
  - Safety/stability floors
  - Oscillation rate
  - MV input kernel-use quality
  - Contradiction rate
  - Beam input usage share
  - Arbitration activity

Promotion rule:
- Advance phase only when all gates pass for two consecutive validation windows.

## Rollback Policy

Immediate rollback to prior stage if any occur:
- Safety floor breach
- Contradiction rate on kernel-used high-confidence MV > 0.15
- Deadlock loops increase by > 20% vs baseline
- Completion drops by > 5% absolute

## Proposed Environment Flags (MVT Plan)

- `MV_PRIMARY_MODE_ENABLE` (default `0`)
- `MV_CONFIDENCE_TRUST_THRESHOLD` (default `0.75`)
- `MV_FACTS_FIT_REQUIRED` (default `1`)
- `MV_LOW_CONF_PROBE_ENABLE` (default `1`)
- `MV_LOW_CONF_PROBE_MAX_STEPS` (default `2`)
- `MV_PROBE_DYNAMIC_BUDGET_ENABLE` (default `1`)
- `BEAM_GUARD_ONLY_MODE` (default `0`)
- `BEAM_HARD_CONTRADICTION_VETO_ONLY` (default `1`)
- `MV_ONLY_CUTOVER_ENABLE` (default `0`)
- `MV_ONLY_EMERGENCY_FALLBACK_ENABLE` (default `1`)

## Immediate Implementation Status

Implemented now:
- Plan definition only.

Not implemented yet:
- Runtime trust-hierarchy enforcement.
- Facts-fit input acceptance gate.
- Low-confidence probe discipline.
- Arbitration reactivation tuning.
- Beam de-weight ladder and MV-only cutover gates.
