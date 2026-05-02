# MV Beam-Woven Integration Phase Plan V2

Sequencing note: unified phase ordering is now governed by `phase_plans/UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md`.

Stabilization fallback note: if WB windows destabilize before WB8/U08 endstate recertification, use `phase_plans/WB_ENDSTATE_STABILIZATION_RECOVERY_PLAN_V1.md` as the recovery overlay before resuming normal WB promotion. For complete beam decoupling recertification, run through RS7.

## Objective

Evolve machine vision as a tightly coupled companion to beam perception first, then decouple beam fully once MV demonstrates stable standalone reliability.

Core direction:
- Beam remains the structural reference channel.
- MV contributes confidence-weighted guidance and objective evidence only through beam-anchored gates.
- App-truth state (player and exit cells) remains the final authority for localization correctness.
- Full decoupling is a late-stage outcome, not an early implementation shortcut.

## Findings Incorporated

- Beam and objective routing are deeply coupled in live runtime decision flow.
- A recent very-hard window showed a hard failure profile: high override pressure, low learned-only rate, and near-zero MV localization quality.
- Woven anchor controls and telemetry have now been added in runtime:
  - MV_BEAM_INTEGRATION_MODE
  - MV_BEAM_INTEGRATION_RECENT_EXIT_STEPS
  - mv_beam_integration_mode and mv_beam_anchor_reason in step telemetry.

## Runtime Alignment Note (Current RS Recovery Ladder)

The runtime kernel phase program currently uses RS recovery stage identifiers (`rs0.*` ... `rs7.*`) for WB endstate stabilization and decoupling recertification.

To keep this plan's WB intent aligned with live runtime behavior:
- `MV_OBJECTIVE_MV_GATE_STAGE_PREFIX` is mapped to `rs0.` (early recovery objective gate activation entry).
- `MV_BEAM_RETIREMENT_STAGE_PREFIX` is mapped to `rs7.` (full decoupled cutover confirmation entry).
- Beam-retirement objective-force dampening and projection clamp checks follow `MV_BEAM_RETIREMENT_STAGE_PREFIX`.

## Non-Negotiable Contracts

- Safety and completion floors cannot regress while transitioning authority.
- MV objective equivalence must not bypass beam anchor conditions in woven mode.
- Preplan localization loops must continue to require app-truth agreement for player and exit before objective-centric sweeps are considered stable.
- All phase promotions are evidence-based and reversible.
- Beam decoupling is allowed only after decoupling readiness gates are satisfied for consecutive windows.

## Phase Structure

### Phase WB0: Baseline Lock and Measurement Hygiene

What:
- Freeze key env and mode settings for repeatable windows.
- Use one run recipe per window for clean comparability.
- Keep sleep-cycle and dump behavior consistent per run set.

Run protocol:
- Hard: 10 mazes x1, then 15 mazes x2.
- Very hard holdout: 15 mazes x1 only after hard gate passes.

Exit criteria:
- No malformed/partial dumps in the window.
- Preflight coverage complete for all dumps.

Rollback trigger:
- Any malformed dump or missing completion markers in window.

### Phase WB1: Beam-Anchored MV Objective Equivalence Stabilization

What:
- Operate with MV_BEAM_INTEGRATION_MODE=woven.
- Require beam-visible or beam-recent anchor before MV beam-equivalent objective evidence can activate.
- Verify anchor reasons in telemetry stream.

Validation focus:
- mv_beam_integration_mode should remain woven.
- mv_beam_anchor_reason should explain every accepted/suppressed beam-equivalent decision.
- mv_beam_equivalent_gate_reason should trend away from unclassified suppression.

Exit criteria:
- Hard windows complete with no anchor-logic anomalies.
- No unexpected objective forcing while anchor is absent.

Rollback trigger:
- Objective routing activates from MV equivalence while anchor reason indicates non-ready.

### Phase WB2: Dual-Evidence Objective Gate Hardening

What:
- Keep objective routing in a dual-evidence regime:
  - Beam anchor condition satisfied.
  - MV objective gate passes (facts-fit and acceptance path).
- Keep low-confidence probe behavior bounded.

Validation focus:
- Reduction in unresolved objective override pressure.
- Stable or improved completion versus WB1.

Exit criteria:
- Hard windows show:
  - guard override rate <= 0.55
  - learned-only rate >= 0.35
  - unresolved objective override rate <= 0.25

Rollback trigger:
- Guard override rises above 0.65 for a full hard window.

### Phase WB3: Localization Reliability Recovery Before Authority Lift

What:
- Prioritize localization reliability improvement before any additional MV authority increase.
- Keep preplan reacquire behavior strict and app-truth aligned.

Validation focus:
- Player and exit localization error trends.
- Contradiction debt and facts-fit rejection mix.

Exit criteria:
- Hard windows:
  - player localization accuracy >= 0.70
  - exit localization accuracy >= 0.60
- Very hard exploratory window:
  - player localization accuracy >= 0.50
  - exit localization accuracy >= 0.40

Rollback trigger:
- Any window with player or exit localization accuracy < 0.25.

### Phase WB4: Controlled MV Influence Lift (Not Authority Flip)

What:
- Increase MV influence by calibration, not by bypass.
- Keep beam guard channels active.
- Lift only score influence and tie-break quality where metrics justify.

Validation focus:
- Completion, loop pressure, and intervention utility.
- No sharp increase in contradiction or replay behaviors.

Exit criteria:
- Hard and very-hard windows remain above WB3 localization floors.
- No degradation in completion ratio over two consecutive windows.

Rollback trigger:
- Two consecutive windows with worsening completion and rising guard overrides.

### Phase WB5: Stage-Gated Advanced Experiments

What:
- Run optional stress experiments only after WB4 stability:
  - beam perturbation toggles
  - contradiction injection toggles
  - route-planning mode trials on isolated windows
- Keep experiment windows isolated from baseline windows.

Validation focus:
- Recovery time after perturbation.
- Trust-ratchet stability under induced contradictions.

Exit criteria:
- Recovery to baseline quality within one subsequent non-perturbed hard window.

Rollback trigger:
- Failure to recover within one non-perturbed hard window.

### Phase WB6: Beam Decoupling Start (Guard Attenuation Ladder)

What:
- Begin decoupling by reducing beam from guard-plus-context toward veto-only behavior.
- Keep MV_BEAM_INTEGRATION_MODE=woven while attenuation is active.
- Keep objective and preplan truth contracts unchanged.

Attenuation ladder:
- Step A: beam guard only in hard contradictions.
- Step B: beam veto only for safety-critical contradictions.
- Step C: beam telemetry shadow remains on, policy influence near-zero.

Validation focus:
- No completion collapse during attenuation steps.
- No spike in unresolved objective overrides or repeated loop pressure.

Exit criteria:
- Two consecutive hard windows pass at each attenuation step.
- Very-hard holdout remains above WB3 localization floors.

Rollback trigger:
- Any attenuation step causes >15% completion drop versus WB4 baseline median.

### Phase WB7: MV-Primary with Beam Shadow (Decoupling Verification)

What:
- Keep beam channel in shadow-only validation role.
- Compare shadow beam signals against live MV decisions for disagreement auditing.
- Do not allow shadow beam to override live MV path unless emergency rollback flag is set.

Validation focus:
- Shadow disagreement rate.
- Whether disagreements predict real failures or benign divergence.

Exit criteria:
- Shadow disagreement rate <= 0.20 on hard windows.
- Disagreement-linked catastrophic failures <= 0.05.
- No regression in preflight behavior screen versus WB6.

Rollback trigger:
- Shadow disagreement rate > 0.35 for two consecutive hard windows.

### Phase WB8: Full Beam Decoupling (Operational Cutover)

What:
- Run MV-only operational path for objective evidence and routing influence.
- Beam remains disabled for routine policy, optionally retained only as offline audit telemetry.
- Keep explicit emergency rollback switch available for immediate re-coupling.

Cutover guardrails:
- Maintain app-truth localization authority and preplan truth checks.
- Keep rollback-to-WB7 on first confirmed stability breach.

Exit criteria:
- Three consecutive mixed windows (hard plus very hard) pass all safety and completion gates.
- Localization quality remains at or above WB3 floors.

Rollback trigger:
- Any catastrophic stability breach, or two consecutive failing windows.

## Promotion Rules

- Promote only after two consecutive passing windows at the current phase.
- Hold phase if exactly one window fails.
- Roll back one phase if two consecutive windows fail, or if any rollback trigger fires.
- During WB6-WB8, roll back immediately on catastrophic breach and freeze further attenuation until root cause is closed.

## Recommended Immediate Config

- MV_BEAM_INTEGRATION_MODE=woven
- MV_BEAM_INTEGRATION_RECENT_EXIT_STEPS=64
- MV_OBJECTIVE_MV_GATE_STAGE_PREFIX=tc0.
- MV_BEAM_RETIREMENT_STAGE_PREFIX=tc6.
- MV_PREPLAN_SWEEP_ENABLE=1
- MV_PREPLAN_REQUIRE_EXIT=1
- MV_ONLY_CUTOVER_ENABLE=0
- MV_ONLY_EMERGENCY_FALLBACK_ENABLE=1
- Keep existing strict app-truth preplan readiness checks enabled.

## Operational Review Cadence

- After each window:
  - Run preflight on all new dumps.
  - Summarize pass/fail against current phase gates.
  - Record decision: promote, hold, or rollback.

## Deliverables Per Phase

- Phase note with:
  - window definition
  - metric summary
  - anomalies and likely causes
  - next decision and exact next run recipe
