# Self-Regulation Brain Phase Plan V1

## Objective

Build a standalone, biologically inspired self-regulation program where runtime behavior is governed by internal state and closed-loop adaptation, while preserving hard safety guarantees.

This plan is intentionally separate from env handoff.
- Env handoff governs ownership and configuration source-of-truth.
- This plan governs cognition architecture, adaptation loops, and autonomous regulation.

## Success Criteria

- The system can self-tune exploration, effort, safety strictness, and plasticity from telemetry-driven internal state.
- Adaptation remains bounded, reversible, and observable.
- Health and stability improve versus baseline without increasing severe safety interventions.

## Safety Contract

Never self-modify beyond guardrails:
- Hard ceilings/floors on all actuator outputs.
- Clamp and cooldown after instability spikes.
- Safety-critical rules remain non-overridable.
- Every adaptive decision is snapshot-visible in telemetry.
- Only soft policy overrides are challengeable; hard safety vetoes are never bypassable.

## Cognitive Architecture Model

Internal state planes:
- Homeostasis plane: stability, safety, intervention pressure, confidence quality.
- Allostasis plane: short-horizon forecast of stress/utility trends.
- Plasticity plane: bounded learning-rate and target-adaptation gain control.
- Executive plane: selects and scales regulators (explore, effort, safety, plasticity).

Signal families:
- Prediction quality: `confidence_ema`, `utility_ema`, `error_ema`.
- Distress and override pressure: `intervention_ema`, `unresolved_override_ema`.
- Runtime resilience: `stability_ema`, `transfer_ema`, `safety_ema`.
- Task pressure: completion momentum, reset rate, step-limit pressure.

## Baseline Gaps In Scope For This Program

- Learned arbitration depth: still limited if override weighting remains mostly hand-tuned.
- Representation and world-model depth: still moderate without latent transition modeling.
- Causal/counterfactual planning: still limited without model-based planning loop.
- OOD confidence: still uncertain unless explicit OOD-first validation suite is added and enforced.

## Program Phases (Separated)

### Phase SR0: Baseline + Instrumentation Contract

Stage ids:
- `sr0.m1_baseline_pack`
- `sr0.m2_signal_contract`

What we implement:
- Freeze baseline metrics and accepted operating envelope.
- Define canonical signal schema for self-regulation inputs and outputs.
- Ensure all required signals are emitted each run.

Exit criteria:
- Baseline pack is reproducible.
- Missing signal rate is zero on validation runs.

### Phase SR1: Homeostatic Core

Stage ids:
- `sr1.m1_state_registry`
- `sr1.m2_homeostasis_update_loop`
- `sr1.m3_read_only_regulators`

What we implement:
- Kernel-owned self-regulation state vector with setpoints, decay, and gain limits.
- Bounded EMA update loop producing normalized regulator factors.
- Read-only observability mode first (regulators logged but not actuating).

Primary touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`
- runtime step observation and adaptive telemetry integration path

Exit criteria:
- Homeostasis factors are stable and bounded.
- No oscillatory behavior under normal runs.

### Phase SR2: Allostatic Forecasting

Stage ids:
- `sr2.m1_trend_derivatives`
- `sr2.m2_preemptive_soft_adjust`

What we implement:
- Forecast short-horizon risk from trend derivatives.
- Trigger preemptive soft adjustments before hard intervention thresholds.

Primary touchpoints:
- `learned_autonomy_controller.py`
- `parallel_reasoning_engine.py`

Exit criteria:
- Preemptive correction occurs before peak distress in measurable scenarios.
- Intervention spike frequency declines vs SR0 baseline.

### Phase SR3: Controlled Actuation

Stage ids:
- `sr3.m1_exploration_actuator`
- `sr3.m2_effort_actuator`
- `sr3.m3_safety_strictness_actuator`

What we implement:
- Enable one actuator at a time with hard clamping and rollback.
- Start with exploration regulator, then effort pacing, then safety strictness modulation.
- Keep immutable safety core untouched.

Primary touchpoints:
- `runtime/app_runtime.py`
- kernel apply-policy runtime integration path

Exit criteria:
- Each actuator passes isolated A/B validation.
- No safety regression during staged enablement.

### Phase SR4: Bounded Plasticity

Stage ids:
- `sr4.m1_target_adapt_reenable`
- `sr4.m2_plasticity_gain_governor`

What we implement:
- Re-enable adaptive target movement behind strict health gates.
- Scale plasticity gains by homeostasis state.
- Enforce anti-drift envelope and deficit recovery constraints.

Primary touchpoints:
- `adaptive_phase_program.py`
- kernel phase defaults and snapshot policy

Exit criteria:
- Promotion target remains within bounded envelope.
- Adaptation improves progression quality without destabilization.

### Phase SR5: Immune Safety + Recovery

Stage ids:
- `sr5.m1_immune_clamp`
- `sr5.m2_recovery_cooldown`

What we implement:
- Immune clamp on instability, hazard, or unresolved override spikes.
- Cooldown and staged recovery before adaptation authority returns.

Exit criteria:
- Clamp events are explainable and reversible.
- Re-entry after clamp is stable.

### Phase SR6: Autonomous Governance

Stage ids:
- `sr6.m1_meta_policy_selection`
- `sr6.m2_self_tuning_budget_controller`
- `sr6.m3_long_horizon_stability_review`
- `sr6.m4_bounded_override_challenge`

What we implement:
- Meta-policy selects regulator presets by state regime.
- Self-tuning budget controller balances compute vs utility.
- Long-horizon drift monitor with automatic rollback triggers.
- Add bounded override challenge controller:
	- may override soft policy overrides under strict evidence;
	- may never bypass hard safety vetoes;
	- auto-reverts after horizon expiry, confidence decay, or safety signal degradation.

Exit criteria:
- Stable performance across heterogeneous run windows.
- Autonomous adjustments outperform fixed-policy baseline.
- Override challenge windows show net positive utility with no safety regressions.

## Rollout Sequence

1. SR0 and SR1 in observability-only mode.
2. SR2 forecasting with no direct actuator authority.
3. SR3 single-actuator rollout (exploration first).
4. SR4 plasticity enablement under strict gates.
5. SR5 immune safety hardening.
6. SR6 autonomous governance after sustained stability.

## Validation Gates Per Phase

Static gate:
- No new app-boundary env dependency introduced.
- Self-reg settings remain kernel-owned.

Runtime gate:
- Track: completion rate, reset pressure, intervention frequency, unresolved override rate, confidence/utility trends, memory integrity.

Stability gate:
- Reject if sustained oscillation, ratcheting pressure, or unresolved override drift is detected.

Safety gate:
- Reject if severe intervention spikes, hazard handling regression, or clamp-failure scenarios appear.
- Reject if override challenge attempts bypass hard safety veto pathways.

For override challenge mode specifically:
- challenge success rate vs reversion rate,
- safety regression rate during challenge windows,
- net quality delta versus baseline soft-override policy.

## Immediate Next 7-Day Kickoff

1. Implement SR1 state registry and snapshot fields in kernel integration.
2. Emit homeostasis factors as telemetry-only outputs.
3. Add SR2 derivative tracker in read-only mode.
4. Run existing 8-run health protocol and compare against SR0 baseline.
5. If stable, enable SR3 exploration actuator behind hard clamp rails.
6. Define soft-override vs hard-veto taxonomy before enabling `sr6.m4_bounded_override_challenge`.
