# Tuning and Consolidation Phase + Micro Plan

## Scope

This plan defines the next stabilization window after the MV preplan runtime change to snapshot-once behavior.

Primary objective:
- Preserve movement reliability and throughput gains.
- Consolidate policy behavior so regression risk is low before the next capability push.

Duration policy:
- Time-to-completion is explicitly non-gating.
- The phase ends only when stability and adaptability goals are met.
- If convergence is fast, exit early; if convergence is slower, continue until criteria are satisfied.

Current baseline assumptions:
- MV preplan is snapshot-once at planning start.
- Latest reviewed hard 15-maze runs passed relaxed preflight.
- No MV wait-loop stall signature in recent logs.

## Recovery-First Block (Run Before TC0)

This block is mandatory when recent behavior no longer matches prior stable phase behavior.

### Cohort Evidence Snapshot (2026-04-30)

Comparison basis used for recovery planning:
- Previous-phase stable quartet (all pass):
  - `15_mazes_hard_20260430_164402.txt`
  - `15_mazes_hard_20260430_164052.txt`
  - `15_mazes_hard_20260430_163847.txt`
  - `15_mazes_hard_20260430_163316.txt`
- Most-recent quartet:
  - `15_mazes_hard_20260430_204737.txt`
  - `15_mazes_hard_20260430_202906.txt`
  - `15_mazes_hard_20260430_200934.txt`
  - `15_mazes_hard_20260430_200608.txt`

Step-weighted drift (previous -> recent):
- `guard_override_rate`: `0.0054 -> 0.0312` (`+0.0258`)
- `intervention_rate`: `0.0054 -> 0.0312` (`+0.0258`)
- `unresolved_objective_override_rate`: `0.0000 -> 0.0225` (`+0.0225`)
- `learned_only_rate`: `0.8141 -> 0.7912` (`-0.0229`)
- `hardcoded_only_rate`: `0.0015 -> 0.0055` (`+0.0040`)
- MV channel note: `mv_accept_rate` improved (`+0.0232`) while `mv_reject_rate` and contradiction-debt rejection were flat/slightly better. Recovery should therefore target override pressure before MV debt knobs.

Latest-log alert snapshot (`15_mazes_hard_20260430_204737.txt`):
- `guard_override_rate = 0.0733`
- `intervention_rate = 0.0733`
- `unresolved_objective_override_rate = 0.0663`
- `learned_only_rate = 0.7435`
- `mixed_rate = 0.0628`

### Recovery Phases

#### Phase TR0: Baseline Parity Recovery (Pre-TC0)

Stage ids:
- `tr0.m1_cohort_anchor_lock`
- `tr0.m2_override_pressure_clamp`
- `tr0.m3_parity_confirmation`

Actions:
- Lock the recovery anchor cohorts above and keep them fixed for all pre-TC0 comparisons.
- Apply only pressure-reduction tuning first:
  - `OBJECTIVE_UNRESOLVED_FORCE_*`
  - `OBJECTIVE_OVERRIDE_SAFE_*`
  - `FRONTIER_LOCK_FORCE_SCORE_MARGIN`
  - `FRONTIER_LOCK_MEMORY_VETO_*`
- Defer MV contradiction-debt tuning in this block unless parity still fails after two clamp iterations.
- Re-run hard windows and compare against the fixed previous-phase quartet after each change.

Exit:
- Two consecutive recovery windows satisfy all parity gates below.

### Parity Gates (Required Before TC0)

Recovery gate (minimum to leave TR0):
- `guard_override_rate <= 0.02`
- `intervention_rate <= 0.02`
- `unresolved_objective_override_rate <= 0.01`
- `learned_only_rate >= 0.80`
- `hardcoded_only_rate <= 0.004`

Parity hold gate (target to match prior phase behavior):
- `guard_override_rate <= 0.01`
- `intervention_rate <= 0.01`
- `unresolved_objective_override_rate <= 0.005`
- `learned_only_rate >= 0.81`
- `hardcoded_only_rate <= 0.002`

If parity hold is not reached but recovery gate is stable for two windows, continue with TC0 and keep a parity watch flag active through TC1.

## Success Criteria

The phase is complete only when all conditions hold for two consecutive cycles:

Non-goal clarification:
- Elapsed wall-clock time is not a success metric for this phase.

1. Safety and integrity:
- `failures = 0` in preflight JSON.
- `shortest_route_integrity = pass`.

2. MV stall prevention:
- `mv_preplan_wait_count = 0`.
- `mv_cellmap_wait_count = 0`.
- `selected_none_count = 0`.

3. Snapshot behavior contract:
- `mv_snapshot_once_count` matches maze count for each run set.

4. Override pressure control:
- `unresolved_objective_override_rate <= 0.05` target.
- Alert band if `unresolved_objective_override_rate > 0.08`.

5. Intervention pressure control:
- `intervention_rate <= 0.10` target.
- Alert band if `intervention_rate > 0.14`.

## Change Budget

During this phase, tune only a narrow set of surfaces unless a safety blocker appears.

Allowed tuning surfaces:
- Objective forcing attenuation and unresolved-safe guards:
  - `OBJECTIVE_UNRESOLVED_FORCE_*`
  - `OBJECTIVE_OVERRIDE_SAFE_*`
- Verification/last-uncertainty routing margins:
  - `VERIFICATION_PRIORITY_*`
  - `LAST_UNCERTAINTY_*`
- Guard score margins and memory veto sensitivity:
  - `FRONTIER_LOCK_FORCE_SCORE_MARGIN`
  - `FRONTIER_LOCK_MEMORY_VETO_*`

Frozen during consolidation (unless rollback emergency):
- MV preplan semantics and cadence:
  - `MV_PREPLAN_SWEEP_ENABLE`
  - `MV_PREPLAN_ACQUIRE_MAX_SWEEPS`
  - snapshot-once runtime flow
- Major subsystem architecture toggles:
  - `MACHINE_VISION_ENABLE`
  - `ORGANISM_CONTROL_ENABLE`
  - `PARALLEL_REASONING_ENGINE_ENABLE`

## Phase Plan

Execution order for this document:
- `TR0 -> TC0 -> TC1 -> TC2 -> TC3 -> TC4`

## Phase TC0: Baseline Lock

Stage ids:
- tc0.m1_baseline_manifest
- tc0.m2_metric_gate_lock
- tc0.m3_seed_protocol_lock

Actions:
- Record baseline env profile and active run protocol.
- Freeze metric gates used for pass/fail decisions.
- Lock seed/start-number sampling protocol for comparability.

Exit:
- Baseline manifest committed.
- Gate thresholds explicitly documented and used by all reviews.

## Phase TC1: Stabilization Sweep

Stage ids:
- tc1.m1_repeatability_check
- tc1.m2_pressure_watch
- tc1.m3_regression_triage

Actions:
- Run repeated hard/very-hard batches under fixed protocol.
- Track unresolved override and intervention drift.
- Triage any drift using targeted marker scans before changing knobs.

Exit:
- Two clean cycles with no MV wait regression.
- Pressure metrics inside target or clearly improving.

## Phase TC2: Narrow Retuning

Stage ids:
- tc2.m1_objective_pressure_retune
- tc2.m2_verification_margin_retune
- tc2.m3_guard_margin_retune

Actions:
- Apply one small knob family change at a time.
- Re-run matched comparison batches after each change.
- Keep all non-targeted surfaces frozen.

Exit:
- At least one pressure metric improvement without safety regression.
- No increase in deadlock signature markers.

## Phase TC3: Consolidation Hardening

Stage ids:
- tc3.m1_multi_batch_confirmation
- tc3.m2_report_unification
- tc3.m3_rollback_readiness

Actions:
- Confirm behavior on multiple fresh batches.
- Produce one canonical summary from preflight JSON + marker scan.
- Keep rollback profile ready for immediate reversion.

Exit:
- Two consecutive cycles satisfy all success criteria.
- Consolidated settings marked as candidate defaults.

## Phase TC4: Promotion Readiness

Stage ids:
- tc4.m1_final_signoff
- tc4.m2_default_profile_tag
- tc4.m3_next_phase_handoff

Actions:
- Verify strict/relaxed gate outcomes on newest runs.
- Tag stable profile as tuning baseline for next feature phase.
- Hand off unresolved watch items as explicit backlog.

Exit:
- Final signoff checklist complete.
- Next-phase work is bounded and does not reopen consolidation surfaces by default.

## Micro Plan (Adaptive Cycle, No Fixed Timeline)

Run this loop continuously until success criteria are met for two consecutive cycles.

## Cycle Step 0: Recovery parity precheck
- Run TR0 parity checks against fixed previous-phase cohort before normal consolidation looping.
- If recovery gate fails, continue TR0 clamp iterations and do not enter TC0 yet.

## Cycle Step 1: Baseline lock
- Lock current env and run protocol.
- Capture newest baseline metrics from recent runs.

## Cycle Step 2: Validation pass
- Run the standard hard/very-hard sequence.
- Evaluate all core gates and alert bands.

## Cycle Step 3: Drift triage (only if needed)
- If any pressure metric drifts, perform targeted marker triage.
- Identify exactly one tuning family for the next pass.

## Cycle Step 4: Narrow retune
- Apply one small change set.
- Re-run matched validation sequence.

## Cycle Step 5: Keep-or-revert decision
- Keep only if pressure improves without safety/stall regression.
- Otherwise rollback immediately to last clean profile.

## Cycle Step 6: Consolidation check
- When two consecutive cycles pass all criteria, mark profile as consolidated.
- Publish final summary, rollback notes, and handoff items.

## Standard Run Protocol

Use this as the default repeatable loop:

1. Start app with fixed profile.
2. Execute run set sequence:
   - `set 1: medium`
   - `set 2: hard`
   - `set 3: very hard`
   - `set 4: hard`
3. Use prompt sequence:
   - `solve 10 mazes; solve 15 mazes x2; solve 15 mazes x2; solve 15 mazes`
4. Export full log dump after each batch.
5. Run preflight relaxed, then strict on newest artifacts.
6. Run marker scan for MV wait/snapshot/deadlock signatures.

## Minimal Review Checklist (Per Cycle)

1. Preflight status:
- `failures`
- `shortest_route_integrity`

2. Behavior pressure:
- `intervention_rate`
- `unresolved_objective_override_rate`
- `guard_override_rate`

3. MV stall and snapshot contract:
- `mv_preplan_wait_count`
- `mv_cellmap_wait_count`
- `mv_snapshot_once_count`
- `selected_none_count`

4. Decision:
- Keep profile
- Retune one family
- Roll back

## Rollback Rules

Rollback immediately if any of the following occurs:
- Any preflight failure in strict mode caused by tuning change.
- Reappearance of MV wait-loop or deadlock marker pattern.
- Sustained alert-band pressure for two consecutive cycles.

Rollback target:
- Last known clean profile that satisfied all success criteria.

## Deliverables

By phase completion, produce:
- Consolidated tuning profile (env diff or config snapshot).
- Two-cycle validation summary with metric table.
- Rollback profile and trigger notes.
- Next-phase handoff list (max 5 bounded items).