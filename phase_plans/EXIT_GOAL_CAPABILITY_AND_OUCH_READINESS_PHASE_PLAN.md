# Exit Goal Capability + Ouch Readiness Plan V1

## Objective

Correct the directional pursuit behavior by adding capability layers (state, confidence, rollback, arbitration), not by hardcoding fixed move sequences.

This plan also opens a safe future path for an aversive ("ouch") learned response channel while keeping training inactive for now.

## Operating Constraints

- Keep current safety and completion reliability invariant.
- Keep objective pursuit learned/evidence-driven.
- Do not force deterministic exit movement outside existing safety/objective framework.
- Keep ouch training disabled in this rollout.

## Success Targets

- Earlier directional commitment when exit evidence is present and consistent.
- Fewer oscillations between exploratory and directional behavior in low-contradiction states.
- No increase in safety regressions or deadlock loops.
- Ouch channel present as instrumentation + sample collection only (no policy actuation).

## Phase + Micro Structure

### Phase EGC0: Instrumentation and Behavioral Visibility

#### `egc0.m1_directional_intent_telemetry`
What:
- Add explicit telemetry for directional intent state, confidence, and downgrade reason.

Why:
- We need clear visibility into why pursuit is or is not selected.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_ui/state/game_state_runtime.py`

Exit:
- Logs show per-step directional-intent state transitions with confidence and reason.

#### `egc0.m2_contradiction_and_reacquire_tags`
What:
- Canonicalize contradiction, stale-evidence, and reacquisition reason tags.

Why:
- Stable taxonomy is required for tuning and future trainer labeling.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Contradiction and reacquire events are countable and consistently labeled.

#### `egc0.m3_pursuit_window_metrics`
What:
- Add rolling metrics for pursuit-window length, confidence drift, and rollback frequency.

Why:
- Needed to evaluate whether pursuit capability is stabilizing over time.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Batch metrics include pursuit-window and rollback aggregates.

### Phase EGC1: Provisional Directional Pursuit Capability

#### `egc1.m1_latent_goal_vector_blend`
What:
- Build a latent directional vector from MV exit evidence + local spatial memory confidence.
- Keep output as a soft scorer input, not a hard move lock.

Why:
- Direction should emerge from blended evidence, not fixed rule shortcuts.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- Learned path shows stronger directional bias under sustained evidence.

#### `egc1.m2_pursuit_confidence_ema`
What:
- Track pursuit confidence EMA with freshness and consistency weighting.

Why:
- Smooth confidence avoids step-to-step mode flapping.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Reduced short-horizon pursuit/explore oscillation in validation runs.

#### `egc1.m3_soft_entry_gate`
What:
- Add soft entry gate for provisional pursuit mode requiring minimum confidence and low contradiction debt.

Why:
- Prevents low-quality early directional lock-in.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Pursuit entry events are fewer but higher-quality.

### Phase EGC2: Contradiction Recovery and Rollback

#### `egc2.m1_rollback_on_evidence_break`
What:
- Trigger rollback when evidence freshness or consistency breaks beyond thresholds.

Why:
- Preserve adaptability when inferred direction becomes stale/wrong.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Rollback events happen quickly after clear contradiction spikes.

#### `egc2.m2_reacquisition_cooldown`
What:
- Add reacquisition cooldown and minimum evidence window before re-entering pursuit.

Why:
- Prevent repeated immediate flip-flop after rollback.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Lower rollback/re-enter churn in the same local region.

#### `egc2.m3_contextual_debt_repayment`
What:
- Use contradiction debt repayment logic to re-enable pursuit progressively as evidence improves.

Why:
- Recovery should be gradual and confidence-based.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Pursuit re-entry aligns with measurable debt reduction.

### Phase EGC3: Corridor and Direction Arbitration

#### `egc3.m1_corridor_direction_blend`
What:
- Blend corridor escape pressure with directional latent vector under bounded weights.

Why:
- Resolve cases where pure corridor logic suppresses useful directionality.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Improved directional progress through corridor-heavy layouts without safety regressions.

#### `egc3.m2_memory_aversive_prior`
What:
- Increase influence of learned memory on avoiding known high-risk transitions while keeping options open.

Why:
- Supports better route quality without hardcoded banned moves.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Fewer repeated high-penalty transitions in later episodes.

#### `egc3.m3_objective_pressure_ramp_smoothing`
What:
- Smooth objective pressure ramp so provisional pursuit can dominate earlier when evidence is clean.

Why:
- Prevent late abrupt objective flips that look non-intentional.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit:
- More gradual and explainable shift toward objective pursuit.

### Phase EGC4: Ouch Readiness (Training Disabled)

#### `egc4.m1_ouch_event_schema_and_buffer`
What:
- Introduce disabled-by-default ouch event schema and ring buffer capture from action outcomes.
- Add gating env vars for enable/train/threshold/scale/buffer-size.

Why:
- Creates a clean future interface for aversive training data collection.

Touchpoints:
- `runtime/app_runtime.py`

Exit:
- Ouch events are collectable when enabled; no behavior change when disabled.

#### `egc4.m2_training_interface_stub`
What:
- Add trainer-facing counters and sample placeholders without optimizer updates.

Why:
- Keeps integration seam ready for future trainer module.

Touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/learned_autonomy_controller.py`

Exit:
- Runtime exposes candidate sample counts but performs no learning updates.

#### `egc4.m3_safety_fences_for_future_activation`
What:
- Define activation fences requiring explicit train flag and phase approval.

Why:
- Prevent accidental activation from config drift.

Touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`
- `runtime/app_runtime.py`

Exit:
- Ouch training path remains inert unless all gates are explicitly enabled.

### Phase EGC5: Validation and Rollout

#### `egc5.m1_validation_matrix`
What:
- Validate on hard and very-hard batch sets, including directional edge-case seeds.

Exit:
- Directional pursuit improves without safety or completion regression.

#### `egc5.m2_report_additions`
What:
- Add report slices for pursuit-window quality, rollback frequency, and ouch candidate sample stats.

Touchpoints:
- `tuning/generate_tuning_report.py`
- `tuning/canonical_compare.py`

Exit:
- Report includes all new capability metrics.

## Immediate Implementation Status

Implemented now:
- EGC4.m1 partial scaffolding in runtime: disabled-by-default ouch event capture and buffer.

Not implemented yet:
- Active ouch learning updates.
- Any policy actuation from ouch intensity.

## New Environment Flags (Readiness Only)

- `OUCH_RESPONSE_ENABLE` (default `0`)
- `OUCH_RESPONSE_TRAIN_ENABLE` (default `0`)
- `OUCH_RESPONSE_MIN_PENALTY` (default `24.0`)
- `OUCH_RESPONSE_TAG_BOOST` (default `8.0`)
- `OUCH_RESPONSE_INTENSITY_SCALE` (default `120.0`)
- `OUCH_RESPONSE_BUFFER_SIZE` (default `512`)
