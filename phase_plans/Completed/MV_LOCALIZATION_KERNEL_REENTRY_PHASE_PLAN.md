# MV Localization Kernel Reentry Plan V1.1

## Objective

Reintroduce machine vision (MV) to the kernel in a constrained way where MV only provides:
- estimated current cell,
- estimated exit cell,
- confidence for both estimates.

MV must not provide pathing guidance, route hints, or direct next-move proposals in this phase plan.
This plan assumes beam vision can be noisy and still requires graceful kernel behavior under degraded input.

## Success Criteria

- Kernel reliability remains stable while MV localization is enabled.
- MV localization improves orientation without increasing unsafe overrides.
- Trust updates reflect MV helpfulness instead of hardcoded heuristics.
- Canonical reports surface MV usage and MV impact clearly.
- Degraded or garbled vision input triggers safe down-weighting instead of brittle behavior.

## Safety Contract

Non-bypassable constraints:
- Hard safety veto pathways remain immutable.
- MV cannot emit route, waypoint, or action directives.
- Kernel consumes MV pose/exit as soft priors only.
- MV confidence/disagreement gates can down-weight or ignore MV input.
- Any MV integration remains bounded, reversible, and telemetry-visible.

## Targets

- No increase in failures or severe intervention events versus current baseline.
- MV-localization-assisted runs maintain PASS consistency.
- Trust floor does not regress below current rolling baseline by more than 0.03.
- Unresolved override rate does not regress.

## Baseline Gaps In Scope

- Current kernel can drift in long ambiguity loops before rediscovering orientation.
- Manual nudges can recover orientation but are not always available.
- MV signals exist in runtime pathways but are not yet constrained as localization-only kernel priors.
- Canonical reporting does not yet isolate MV localization contribution.

## Current Readiness Signal

- Recent behavior suggests stronger-than-expected resilience under accidental garbled vision input.
- Kernel adaptation across maze variants is currently improving faster than original conservative timing assumptions.
- Remaining concern is transfer quality outside maze domains, not maze-only competence.

## Program Phases (Phase + Micro)

### Phase MVL0: Contract Lock and Guardrails

Stage ids:
- `mvl0.m1_pose_exit_packet_contract`
- `mvl0.m2_no_route_no_action_guard`
- `mvl0.m3_mv_telemetry_contract_lock`

What we implement:
- Freeze MV packet schema for current-cell and exit-cell estimates with confidence.
- Add explicit guardrails blocking route/action content from MV packet ingestion.
- Lock telemetry keys for MV usage auditing.

Primary touchpoints:
- `runtime/app_runtime.py`
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`

Exit criteria:
- MV contract accepted by runtime and kernel bridge.
- Route/action fields are rejected or ignored by design.

### Phase MVL1: Pose and Exit Estimation Feed

Stage ids:
- `mvl1.m1_current_cell_estimator`
- `mvl1.m2_exit_cell_estimator`
- `mvl1.m3_confidence_calibration_baseline`

What we implement:
- Emit stable current-cell estimate and confidence.
- Emit stable exit-cell estimate and confidence.
- Build baseline confidence calibration measurements.

Primary touchpoints:
- `runtime/app_runtime.py`

Exit criteria:
- Pose/exit signals are emitted consistently during maze episodes.
- Confidence fields are populated and bounded.

### Phase MVL2: Kernel Bridge (Soft Priors Only)

Stage ids:
- `mvl2.m1_pose_exit_ingestion`
- `mvl2.m2_soft_prior_feature_blend`
- `mvl2.m3_missing_signal_fallback`

What we implement:
- Inject MV pose/exit packet into kernel step context.
- Blend MV signals as soft priors in scoring context only.
- Ensure deterministic fallback when MV signals are missing.

Primary touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`
- `runtime/app_runtime.py`

Exit criteria:
- Kernel behavior remains valid with MV on and off.
- No direct action from MV packet is possible.

### Phase MVL3: Confidence and Disagreement Gating

Stage ids:
- `mvl3.m1_confidence_threshold_gate`
- `mvl3.m2_local_map_disagreement_score`
- `mvl3.m3_dynamic_downweight_or_ignore`

What we implement:
- Ignore low-confidence MV localization data.
- Compute disagreement against local map/state consistency.
- Down-weight or disable MV influence under disagreement spikes.

Primary touchpoints:
- `runtime_kernel/integration/kernel_phase_policy_runtime.py`
- `runtime/app_runtime.py`

Exit criteria:
- MV influence scales down safely under uncertainty.
- No instability from contradictory MV packets.

### Phase MVL4: Trust-Supervised Localization Integration

Stage ids:
- `mvl4.m1_mv_helpfulness_labeling`
- `mvl4.m2_trust_feedback_hook`
- `mvl4.m3_intervention_safe_fusion`

What we implement:
- Label MV usage outcomes as helpful, neutral, or non-helpful.
- Feed labels into trust/feedback updates.
- Ensure trust blending remains bounded and intervention-safe.

Primary touchpoints:
- `runtime_kernel/parallel_reasoning_engine.py`
- `runtime/app_runtime.py`

Exit criteria:
- Trust responds to MV contribution quality, not hardcoded rules.
- Intervention utility does not regress.

### Phase MVL5: Robustness Curriculum

Stage ids:
- `mvl5.m1_mv_dropout_resilience`
- `mvl5.m2_latency_and_jitter_tolerance`
- `mvl5.m3_focus_drift_recovery`
- `mvl5.m4_garbled_vision_chaos_trials`

What we implement:
- Add controlled MV dropout windows to prevent dependence.
- Validate behavior under latency/jitter perturbations.
- Validate safe handling of focus/window drift scenarios.
- Inject garbled and partially-corrupted localization packets to test trust-safe degradation paths.

Primary touchpoints:
- `runtime/app_runtime.py`

Exit criteria:
- Kernel remains functional and safe with intermittent MV loss.
- No unsafe actions under perturbation.
- Garbled-input trials show graceful fallback with no severe safety regressions.

### Phase MVL6: Canonical Reporting and Rollout Gates

Stage ids:
- `mvl6.m1_mv_localization_metrics_schema`
- `mvl6.m2_report_emit_and_warning_mode`
- `mvl6.m3_optional_blocking_gate_rollout`

What we implement:
- Add MV localization metrics to canonical schema/report outputs.
- Emit warning-mode regressions for MV trust and safety impact.
- Add optional blocking gate after repeated stable cycles.

Primary touchpoints:
- `tuning/canonical_metrics_schema.json`
- `tuning/canonical_compare.py`
- `tuning/generate_tuning_report.py`

Exit criteria:
- MV localization regressions are visible and enforceable.
- Gate false-positive rate remains low on repeated runs.

## Rollout Sequence

1. MVL0 contract and guardrails.
2. MVL1 pose and exit estimation feed.
3. MVL2 kernel bridge (soft prior only).
4. MVL3 confidence and disagreement gating.
5. MVL4 trust-supervised localization integration.
6. MVL5 robustness curriculum.
7. MVL6 canonical reporting and rollout gates.

## Fast-Track Execution Mode

- Default cadence is accelerated when phase gates are already green.
- Multiple micro stages may be completed in one day, but only after per-stage validation gates pass.
- If any stability or safety gate fails, execution drops back to one-stage-at-a-time conservative mode.

## Validation Gates Per Phase

Static gate:
- No new app-boundary dependency that bypasses approved controls.
- No MV route/action hint fields accepted by kernel bridge.

Runtime gate:
- Track: mv_pose_used, mv_pose_confidence, mv_exit_confidence, mv_disagreement_score, trust mean/floor/delta, intervention utility, unresolved override rate, status/drift.

Stability gate:
- Reject on oscillation spikes, repeated trust collapse windows, or repeated MV disagreement excursions.

Safety gate:
- Reject on any severe safety regression, drift regression, or PASS consistency break.

## Immediate Fast-Track Kickoff (Target: 1-3 Days If Gates Stay Green)

1. Implement MVL0 packet contract and no-route guardrail enforcement.
2. Wire MVL1 pose/exit confidence emissions in runtime telemetry.
3. Implement MVL2 soft-prior kernel bridge with strict fallback behavior.
4. Add MVL3 confidence/disagreement down-weight logic.
5. Run latest 10 hard logs with MV localization on and off.
6. Generate canonical comparison report including MV localization fields.
7. Run MVL5 garbled-vision chaos trials before enabling broader exposure.

## Post-Maze Transition: Beam Vision to Proper MV

- Beam vision remains the interim localization signal while maze program wraps.
- Proper MV replaces beam vision only after parity gates pass on localization accuracy and confidence calibration.
- During handoff, keep the same localization-only contract (pose, exit, confidence) so policy integration does not change.
- Any proper-MV extension beyond localization-only is out of scope for this plan and requires a new gated phase plan.

## Operating Rule

Only one micro stage is active at a time.
Do not advance to the next micro stage until current validation gates pass.
