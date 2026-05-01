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

## Post-Change Recovery and Extension Path

### Required Immediate Action (Rerun Before Extending)

If recent post-change validation windows are mixed (for example one clean run and one unstable run), rerun `MVT4` before introducing new stressors.

Why:
- Extension phases (blackouts/contradictions) are useful only after base de-weight behavior is stable.
- If stage-gated controls are not active in telemetry, extension results are not attributable.

Rerun gate:
- Re-run `mvt4.m1 -> mvt4.m3` sequence with normal matrix windows.
- Require two consecutive windows where:
  - `unresolved_objective_override_rate <= 0.03`
  - `guard_override_rate <= 0.08`
  - MV input acceptance is stable without contradiction-debt spikes.

Only after this gate passes, enable the extension phases below.

### Phase MVT5: Beam Reliability Stress (Intermittent Blackout Curriculum)

#### `mvt5.m1_beam_blackout_low_dose`
What:
- Inject intermittent beam-only blackouts while keeping MV path fully available.
- Start with low dose: `5% -> 10%` of decision steps.

Why:
- Teaches kernel to stop over-trusting beam continuity and rely on MV/facts-fit signal.

Safety bounds:
- Blackout burst length max: `2-4` steps.
- Cooldown between bursts: at least `6-10` steps.
- Do not blackout both beam and MV together.

Exit:
- No regression in completion/safety.
- Beam-guard dependence decreases while MV accepted-input share holds or improves.

#### `mvt5.m2_beam_blackout_burst_and_recovery`
What:
- Increase blackout burst difficulty slightly (`8% -> 12%` total blackout exposure), still beam-only.

Why:
- Validates short-horizon recovery quality under sensor intermittency.

Safety bounds:
- Cap max burst at `5` steps.
- Roll back if unresolved override rate rises above `0.03` for two consecutive windows.

Exit:
- Recovery latency remains bounded; no deadlock-loop increase.

#### `mvt5.m3_blackout_failsafe_and_rollforward`
What:
- Validate blackout kill-switch and automatic rollback behavior under stress.

Why:
- Ensures blackouts are a training perturbation, not an uncontrolled deployment mode.

Exit:
- Kill-switch behaves deterministically.
- Roll-forward criteria remain satisfied for two windows.

### Phase MVT6: Contradiction Robustness and Source Trust Calibration

#### `mvt6.m1_beam_contradiction_injection`
What:
- Inject low-dose contradictory beam evidence against local facts-fit.
- Start at `3% -> 5%` of steps.

Why:
- Trains explicit source reliability separation: unreliable beam hints should be demoted.

Safety bounds:
- Keep clean-data majority (`>= 90%` clean steps).
- Contradiction events must be labeled in telemetry for attribution.

Exit:
- Beam contradiction rejection rate rises without safety regression.

#### `mvt6.m2_mv_contradiction_microdose`
What:
- Add very small MV contradiction injections (`<= 2%`) with immediate telemetry labeling.

Why:
- Avoid overfitting to MV as infallible while preserving MV-primary policy.

Safety bounds:
- Never exceed `5%` MV contradiction exposure.
- Stop immediately if contradiction-debt or rollback rate breaches policy caps.

Exit:
- Kernel preserves facts-fit discipline and recovers without oscillation spikes.

#### `mvt6.m3_source_reliability_adaptation`
What:
- Adapt source trust weights from recent contradiction utility (beam vs MV), bounded by safety floor.

Why:
- Encodes reliability as evidence-driven and reversible, not hardcoded.

Exit:
- Stable reliability separation and no completion/safety regression.

### Blackouts and Contradictions: Beneficial vs Harmful

Beneficial when:
- Doses are low and staged.
- Perturbations are source-targeted and labeled.
- Clean-data majority remains dominant.
- Event timing is unpredictable to the kernel but bounded by policy caps.
- Runs are replayable via seeded perturbation schedulers.

Harmful when:
- Exposure is too high (`> 10-15%` sustained).
- Perturbations hit beam and MV simultaneously early.
- Contradiction labels are missing, causing training contamination.
- Event timing is deterministic/predictable to policy logic (easy to game).
- Event timing is fully unbounded/noisy (non-reproducible eval drift).

### Perturbation Scheduling Policy (How to Inject)

Use stochastic timing with deterministic control.

Required behavior:
- Random and unpredictable to the kernel when blackouts/contradictions happen.
- Fixed target exposure bands per phase window (do not drift upward during a window).
- Seeded scheduler so runs are reproducible for A/B and regression analysis.

Implementation contract:
- Sample event starts from seeded PRNG.
- Apply burst/cooldown constraints:
  - Max burst length enforced.
  - Minimum cooldown enforced.
- Apply hard exposure cap per window (for example, per 15-maze validation window).
- Keep clean-data majority (recommended `>= 90%` clean steps in early extension phases).
- Emit event logs for every perturbation: `type`, `source`, `start_step`, `duration`, `seed`, `window_budget_used`.

Recommended defaults for extension phases:
- `MVT5` blackout schedule:
  - Event timing: random (seeded)
  - Exposure band: `5% -> 10%`
  - Burst max: `4` (phase m1), `5` (phase m2)
  - Cooldown min: `8`
- `MVT6` contradiction schedule:
  - Beam contradiction exposure: `3% -> 5%` (seeded random timing)
  - MV contradiction exposure: `<= 2%` initially, hard cap `<= 5%`
  - Never inject beam+MV contradiction on the same step in early windows.

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
- Extension-phase enable gate:
  - Before `MVT5`/`MVT6`, require two consecutive windows with:
    - `unresolved_objective_override_rate <= 0.03`
    - `guard_override_rate <= 0.08`

## Trust Ratchet and Manual Progression Policy

### Trust ratchet contract (MV influence)

Policy:
- MV influence is multiplied by a bounded trust-ratchet scale, not directly set to full strength.
- Trust increases slowly on stable evidence and decreases quickly on contradiction/facts-fit failure.
- Ratchet has promote/demote hysteresis windows to avoid oscillation.

Signals:
- Positive evidence:
  - `mv_input_accepted=1`
  - `mv_input_facts_fit=1`
  - no active contradiction injection
  - positive immediate outcome (`progress_delta > 0` or reward > penalty)
- Negative evidence:
  - `facts_fit_contradiction_debt` or `facts_fit_cellmap_blocked`
  - active beam/MV contradiction event
  - repeated accepted MV influence with negative outcome

Ratchet behavior:
- Promote window example: `6` stable steps -> small trust increase (`+0.08` level).
- Demote window example: `2` adverse steps -> stronger trust decrease (`-0.16` level).
- Scale bounds example: `[0.35, 1.0]`.
- Low-confidence probe mode remains bounded and additionally ratchet-scaled.

Required telemetry fields:
- `mv_trust_ratchet_scale`
- `mv_trust_ratchet_level`
- `mv_trust_ratchet_quality_ema`
- `mv_trust_ratchet_promote_streak`
- `mv_trust_ratchet_demote_streak`

### Manual progression mode (autostep disabled)

Policy:
- Disable kernel phase autoprogression by default during trust-ratchet validation windows.
- Progression owner is human-in-the-loop: phase/micro moves happen only after log review.

Required runtime behavior:
- `kernel_phase_autostep_enable = 0` at startup/restore.
- Manual controls stay available for explicit micro/phase step changes.
- Persist disabled state, but also enforce manual mode on restore to prevent drift.

Promotion workflow in manual mode:
- Run validation window.
- Review telemetry + safety/contradiction metrics.
- Decide: hold, advance micro, advance phase, or regress.


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

Extension rule:
- Do not start `MVT5` or `MVT6` until `MVT4` rerun gate passes.
- Pause or rollback extension phases immediately on safety-floor breach.

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
- `MV_BEAM_BLACKOUT_ENABLE` (default `0`)
- `MV_BEAM_BLACKOUT_RATE` (default `0.05`)
- `MV_BEAM_BLACKOUT_BURST_MAX_STEPS` (default `4`)
- `MV_BEAM_BLACKOUT_COOLDOWN_STEPS` (default `8`)
- `MV_BEAM_BLACKOUT_RANDOM_ENABLE` (default `1`)
- `MV_BEAM_BLACKOUT_SEED` (default `1337`)
- `MV_BEAM_BLACKOUT_WINDOW_MAX_EVENTS` (default `0`, `0` means rate-driven only)
- `MV_BEAM_CONTRADICTION_INJECT_ENABLE` (default `0`)
- `MV_BEAM_CONTRADICTION_RATE` (default `0.03`)
- `MV_MV_CONTRADICTION_INJECT_ENABLE` (default `0`)
- `MV_MV_CONTRADICTION_RATE` (default `0.01`)
- `MV_CONTRADICTION_RANDOM_ENABLE` (default `1`)
- `MV_CONTRADICTION_SEED` (default `7331`)
- `MV_CONTRADICTION_WINDOW_MAX_EVENTS` (default `0`, `0` means rate-driven only)
- `MV_PERTURBATION_NO_OVERLAP_ENABLE` (default `1`)
- `MV_PERTURBATION_EVENT_LOG_ENABLE` (default `1`)
- `MV_SOURCE_RELIABILITY_ADAPT_ENABLE` (default `0`)

## Immediate Implementation Status

Implemented now:
- Manual progression mode default (`kernel_phase_autostep_enable=0`) and restore-time enforcement.
- Runtime MV trust-ratchet integration with hysteresis and bounded scaling.
- Trust-ratchet telemetry emission in step logs and move breakdown.

Not implemented yet:
- Full automation for promote/demote decisions from aggregated batch windows.
- Batch-level ratchet governance hooks in phase policy runtime.
