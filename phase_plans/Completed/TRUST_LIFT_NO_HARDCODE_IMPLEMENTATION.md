# Trust Lift Brain Phase Plan V2

## Objective

Implement a full trust-lift program where trust quality is learned from outcome reliability and context, while preserving hard safety guarantees and avoiding hardcoded trust rules.

This plan is implementation-first:
- trust signals are learned from telemetry and outcomes,
- phase progression is gated by canonical reports,
- rollout is one micro-stage at a time.

## Success Criteria

- Deliberative trust quality improves without safety regression.
- Trust calibration remains stable across hard and OOD-tagged sets.
- Intervention utility does not degrade as trust rises.
- Canonical reports remain contradiction-free and reproducible.

## Safety Contract

Non-bypassable constraints:
- Hard safety veto pathways remain immutable.
- No handcrafted trust boosts by maze pattern, difficulty label, or ad-hoc exception.
- All trust adaptation remains bounded, reversible, and telemetry-visible.
- Promotion/override drift constraints remain enforced.

## Targets

- Hard trust mean >= 0.82
- Hard trust floor >= 0.72
- ID-OOD trust delta < 0.10
- No increase in failures, drift, or severe intervention events

## Baseline Gaps In Scope

- Trust currently depends heavily on global EMA behavior and can miss context-specific degradation.
- Channel arbitration can still overreact in low-confidence spans.
- Intervention aftermath signals are underused as trust supervision.
- Canonical trust gates are not yet explicit enough for enforcement.

## Program Phases (Phase + Micro)

### Phase TL0: Baseline Lock + Trust Contract

Stage ids:
- `tl0.m1_baseline_pack_lock`
- `tl0.m2_trust_contract_schema`
- `tl0.m3_reporting_contract_lock`

What we implement:
- Freeze baseline trust metrics and acceptance bands.
- Lock trust metric definitions and canonical thresholds.
- Ensure preflight JSON remains status source-of-truth.

Exit criteria:
- Baseline reruns are reproducible.
- Canonical report fields and thresholds are versioned.

### Phase TL1: Calibration Trust Core

Stage ids:
- `tl1.m1_outcome_label_contract`
- `tl1.m2_calibration_scoring_update`
- `tl1.m3_compat_telemetry_bridge`

What we implement:
- Define outcome labels from progress and reward/penalty signals.
- Replace or augment trust updates with calibration scoring (for example Brier-style).
- Preserve existing telemetry compatibility.

Primary touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`

Exit criteria:
- Trust updates are reliability-driven and bounded.
- No hardcoded pattern-specific trust logic appears.

### Phase TL2: Context-Conditioned Reliability

Stage ids:
- `tl2.m1_context_bucket_model`
- `tl2.m2_context_trust_memory`
- `tl2.m3_global_context_blend`

What we implement:
- Add lightweight context buckets (unknown, loop, hazard, frontier).
- Track channel reliability per context online.
- Blend global trust with context trust during arbitration.

Primary touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`
- optional telemetry in `runtime/app_runtime.py`

Exit criteria:
- Trust degradation under stressed contexts is reduced.
- Memory and runtime overhead remain bounded.

### Phase TL3: Soft Arbitration Refinement

Stage ids:
- `tl3.m1_margin_sensitive_weighting`
- `tl3.m2_probe_policy_smoothing`
- `tl3.m3_oscillation_guard_for_arbitration`

What we implement:
- Tune channel blend by learned trust and confidence margin.
- Keep low-confidence probing but smooth transitions.
- Prevent brittle strategy flips from short noise bursts.

Primary touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`

Exit criteria:
- Confidence and trust move coherently.
- Arbitration oscillation is reduced without safety loss.

### Phase TL4: Intervention-Outcome Learning

Stage ids:
- `tl4.m1_intervention_outcome_capture`
- `tl4.m2_helpful_vs_nonhelpful_labeling`
- `tl4.m3_trust_feedback_fusion`

What we implement:
- Capture intervention aftermath as supervised trust signal.
- Distinguish beneficial vs non-beneficial intervention outcomes.
- Fuse intervention-derived labels into trust updates.

Primary touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/parallel_reasoning_engine.py`

Exit criteria:
- Intervention utility trend is stable or improved.
- Unresolved override trend does not regress.

### Phase TL5: OOD Trust Curriculum

Stage ids:
- `tl5.m1_near_ood_stabilization`
- `tl5.m2_mid_ood_generalization`
- `tl5.m3_far_ood_guarded_trials`

What we implement:
- Run severity-staged OOD trust validation.
- Tune only learned mechanisms introduced in TL1-TL4.
- Advance severity only after stable cycles.

Primary touchpoints:
- Canonical tuning pipeline and reports

Exit criteria:
- OOD trust drop remains below threshold.
- Safety pass rates remain stable.

### Phase TL6: Canonical Trust Gates + Enforcement

Stage ids:
- `tl6.m1_trust_gate_schema`
- `tl6.m2_report_gate_emit`
- `tl6.m3_warning_then_blocking_rollout`

What we implement:
- Add explicit trust-quality gates (mean, floor, delta).
- Emit trust gate status in canonical report outputs.
- Roll from report-only to warning, then blocking after stability.

Primary touchpoints:
- `tuning/canonical_metrics_schema.json`
- `tuning/generate_tuning_report.py`

Exit criteria:
- Trust regressions are automatically surfaced and enforceable.
- Gate false-positive rate is low across repeated cycles.

## Rollout Sequence

1. TL0 contract lock.
2. TL1 calibration core.
3. TL2 context conditioning.
4. TL3 arbitration refinement.
5. TL4 intervention learning.
6. TL5 OOD curriculum.
7. TL6 trust gate enforcement.

## Validation Gates Per Phase

Static gate:
- No new app-boundary env dependency introduced.
- No hardcoded trust exceptions by layout/difficulty.

Runtime gate:
- Track: trust mean/floor/delta, confidence margin, intervention utility, unresolved override rate, guard utility, status/drift.

Stability gate:
- Reject on sustained oscillation, repeated trust collapse windows, or persistent negative within-file trust drift.

Safety gate:
- Reject on any severe safety regression, drift regression, or PASS consistency break.

## Immediate 7-Day Kickoff

1. Implement TL1 trust calibration update path.
2. Add compatibility telemetry checks and snapshot fields.
3. Run before/after newest hard set review (10 files).
4. Generate canonical report and compare trust gates.
5. If stable, start TL2 context bucket scaffolding in telemetry-only mode.
6. Publish first trust-lift checkpoint report artifact.

## Operating Rule

Only one micro stage is active at a time.
Do not advance to the next micro stage until current validation gates pass.
