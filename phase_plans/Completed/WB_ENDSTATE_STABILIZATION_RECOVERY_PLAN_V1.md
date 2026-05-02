# WB Endstate Stabilization Recovery Plan V1

Sequencing note: master ordering is still governed by `phase_plans/UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md`. This document is a stabilization overlay used only when WB progression loses gate stability and must be recovered before resuming normal promotion.

## Objective

Run a strictly stabilization-focused recovery cycle that restores WB gate health and re-qualifies the WB endstate before continuing downstream blocks.

Primary target endstate:
- U08 (WB8) cutover readiness and stability contract restored.

Decoupling target state:
- beam is fully decoupled from routine live policy decisions.
- MV-only operational path is active for objective and routing authority.
- beam remains optional offline telemetry/audit only, with emergency re-coupling preserved.

This plan is for stabilization only. It does not introduce new capability scope.

## Scope

Applies to WB stabilization and recertification surfaces only:
- beam anchor readiness and suppression behavior
- unresolved wait pressure
- guard override pressure
- decoupling ladder readiness signals

Out of scope:
- SC feature expansion
- MV-D schema migration work
- RG adapter work

## When To Invoke This Overlay

Enter this overlay when any of the following are true during WB progression:
- two consecutive failing windows under active WB gate rules
- unresolved wait pressure remains above stabilization threshold in two consecutive windows
- guard override pressure remains above stabilization threshold in two consecutive windows
- catastrophic stability breach during WB6-WB8 surfaces

## Recovery Endstate Contract

The overlay is complete only when all conditions hold:
1. Two consecutive hard windows pass stabilization gates.
2. No catastrophic breach in the final two windows.
3. WB endstate readiness evidence is re-established for U08 continuation.
4. Full beam-decoupled profile passes endstate cutover checks.

Stabilization gates for this overlay:
- unresolved_wait_rate <= 0.10
- guard_override_rate <= 0.015
- catastrophic_breach_count = 0 per window

## Non-Negotiable Constraints

- App-truth localization authority remains final.
- No bypass of woven beam anchor contracts while in recovery.
- No expansion of objective forcing authority during recovery.
- Every promotion decision remains reversible and evidence-backed.

## Recovery Phases

## Phase RS0: Recovery Lock and Evidence Freeze

Stage ids:
- rs0.m1_recipe_lock
- rs0.m2_metric_contract_lock
- rs0.m3_baseline_snapshot_lock

Actions:
- Freeze one run recipe and one metrics contract for all recovery windows.
- Lock baseline snapshot for before versus after comparison.
- Require full preflight coverage on all evaluated dumps.

Exit criteria:
- Recipe and metric contract frozen.
- No malformed or partial dump in the lock window.

## Phase RS1: Unresolved Wait Pressure Stabilization

Stage ids:
- rs1.m1_wait_source_bucketing
- rs1.m2_objective_wait_suppression
- rs1.m3_wait_recheck_hold

Actions:
- Bucket unresolved wait by reason and stage context.
- Apply only narrow wait-pressure mitigations.
- Recheck unresolved wait after each mitigation step.

Exit criteria:
- unresolved_wait_rate <= 0.10 for two consecutive hard windows.

Rollback trigger:
- unresolved_wait_rate > 0.20 in any window.

## Phase RS2: Guard Override Normalization

Stage ids:
- rs2.m1_override_reason_partition
- rs2.m2_override_budget_rebalance
- rs2.m3_override_floor_recheck

Actions:
- Partition guard overrides by reason families.
- Reduce avoidable overrides without weakening safety veto pathways.
- Re-validate guard behavior under matched hard windows.

Exit criteria:
- guard_override_rate <= 0.015 for two consecutive hard windows.

Rollback trigger:
- guard_override_rate > 0.03 in any window.

## Phase RS3: Beam Anchor and Objective Gate Coherence

Stage ids:
- rs3.m1_anchor_reason_audit
- rs3.m2_not_recent_suppression_control
- rs3.m3_gate_reason_normalization

Actions:
- Audit anchor-ready versus suppressed decisions.
- Reduce avoidable `beam_not_recent` churn under stabilization settings.
- Normalize gate-reason mix away from unclassified suppression.

Exit criteria:
- No anchor-logic anomaly in two consecutive windows.
- Objective forcing while anchor is non-ready is not observed.

## Phase RS4: Stability Hold and Variance Compression

Stage ids:
- rs4.m1_consecutive_pass_hold
- rs4.m2_variance_band_check
- rs4.m3_regression_tripwire_check

Actions:
- Hold settings fixed and run repeated hard windows.
- Confirm metric variance compresses into stable band.
- Verify no hidden regression signatures during hold.

Exit criteria:
- Two consecutive windows pass all stabilization gates.
- No new high-severity anomaly family introduced.

## Phase RS5: WB6-WB8 Readiness Rehearsal

Stage ids:
- rs5.m1_attenuation_readiness_probe
- rs5.m2_shadow_disagreement_probe
- rs5.m3_cutover_guard_probe

Actions:
- Rehearse attenuation and shadow-readiness checks with stabilization settings frozen.
- Validate disagreement behavior is bounded before resuming WB6-WB8 flow.
- Confirm emergency rollback path remains hot.

Exit criteria:
- No catastrophic breach during rehearsal windows.
- Readiness evidence package is complete for WB progression resume.

## Phase RS6: Endstate Recertification and Handoff

Stage ids:
- rs6.m1_u08_contract_recheck
- rs6.m2_resume_point_confirm
- rs6.m3_handoff_publish

Actions:
- Recheck U08 contract surfaces against latest stable windows.
- Confirm exact WB resume point and next window recipe.
- Publish stabilization summary and handoff decision.

Exit criteria:
- U08 endstate readiness re-certified.
- Resume decision is explicit: resume WB phase progression or remain in RS hold.

## Phase RS7: Full Beam-Decoupled Cutover Confirmation

Stage ids:
- rs7.m1_decoupled_profile_apply
- rs7.m2_decoupled_window_validation
- rs7.m3_decoupled_handoff_freeze

Actions:
- Apply decoupled operational profile for WB endstate confirmation:
  - MV_ONLY_CUTOVER_ENABLE=1
  - MV_ONLY_EMERGENCY_FALLBACK_ENABLE=1
  - MV_BEAM_RETIREMENT_STAGE_PREFIX=tc6.
- Validate that beam is not used for routine policy authority in cutover windows.
- Keep emergency rollback-to-WB7 path available and tested.

Exit criteria:
- Two consecutive mixed windows pass while decoupled profile is active.
- No catastrophic breach in decoupled windows.
- Handoff package confirms full beam decoupling is operationally stable.

Rollback trigger:
- Any catastrophic breach in decoupled windows.
- Two consecutive failing decoupled windows.

## Promotion and Rollback Rules (Overlay)

- Promote one RS phase only after two consecutive passing windows for that phase.
- Hold if exactly one window fails.
- Roll back one RS phase on two consecutive failures.
- Immediate rollback to RS0 on catastrophic stability breach.
- While RS7 is active, immediate rollback to RS6 on any catastrophic breach.

## Standard Recovery Run Protocol

- Hard windows are primary signal for this overlay.
- Baseline evaluation unit: one 15-maze hard window per decision cycle.
- Run two consecutive windows before any promote decision.
- Very-hard probes are optional until RS5 and are never used to bypass hard-window failures.

## Required Artifacts Per Recovery Window

- preflight coverage summary
- stabilization metric snapshot
  - unresolved_wait_rate
  - guard_override_rate
  - catastrophic_breach_count
- promote/hold/rollback decision note
- top anomaly tags and short root-cause summary

## Resume Rule Back To Unified WB Flow

When RS6 exits successfully:
- return control to unified sequence at the interrupted WB point
- do not advance into Block B until U08 endstate is confirmed under unified gates

When RS7 exits successfully:
- mark WB full beam-decoupled endstate as re-certified.
- resume unified sequence from U08 completion state.
