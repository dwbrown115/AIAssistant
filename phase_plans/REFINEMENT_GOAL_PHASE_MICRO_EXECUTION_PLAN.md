# Refinement Goal Phase + Micro Execution Plan

## Source Goal
This plan operationalizes:
- [phase_plans/NEXT_REFINEMENT_PHASE_MICRO_STAGE.md](phase_plans/NEXT_REFINEMENT_PHASE_MICRO_STAGE.md)

## Completion Criteria
The goal is complete only when all are true:
1. Runtime defaults use the six capability phases (not the legacy five).
2. Each phase has all four micro stages:
   - m1_shadow_train
   - m2_counterfactual_train
   - m3_advisory_integrate
   - m4_control_integrate
3. `KERNEL_PHASE_AUTOSTEP` is implemented and verified.
4. `KERNEL_PHASE_OBSERVATION_FLOOR` is implemented and verified.
5. Disable/re-enable semantics are preserved.
6. Governance payloads and dumps reflect active phase/micro policy state.
7. Preflight gate passes on newest hard-15 dump (normal + strict).

## Phase 0: Baseline Lock

### Micro 0.1: Baseline Snapshot
- Capture current phase program snapshot shape and current defaults.
- Record current event payload keys for:
  - adaptive_phase_target
  - adaptive_phase_transition
  - adaptive_phase_module_activation

Exit:
- Baseline recorded for regression comparison.

### Micro 0.2: Backward Compatibility Guard
- Define migration behavior for persisted legacy `kernel_phase_program_state`.
- Guarantee startup does not crash when old phase ids are present.

Exit:
- Legacy persisted state loads safely.

## Phase 1: Six-Phase Spec Convergence

### Micro 1.1: Replace Default Phase Taxonomy
- Update [adaptive_phase_program.py](adaptive_phase_program.py) default spec builder to six target phases:
  - phase_1_guess_ledger
  - phase_2_contradiction_accounting
  - phase_3_falsification_planner
  - phase_4_metric_decoupler
  - phase_5_abstraction_memory
  - phase_6_causal_counterfactual_planner

Exit:
- Default build returns six phases.

### Micro 1.2: Canonical Micro-Stage IDs
- Ensure each phase emits the exact four stage ids:
  - pX.m1_shadow_train
  - pX.m2_counterfactual_train
  - pX.m3_advisory_integrate
  - pX.m4_control_integrate

Exit:
- Snapshot and controls show canonical stage ids.

### Micro 1.3: Capability + Module Alignment
- Set capability and module ids per phase to match source goal.
- Validate module target names and objective signals map cleanly to runtime integration.

Exit:
- Runtime snapshot exposes aligned capability/module metadata.

## Phase 2: Adaptive Gate Controls

### Micro 2.1: Implement `KERNEL_PHASE_AUTOSTEP`
- Add env control parsing with safe default `1`.
- Behavior:
  - `1`: normal auto promotion.
  - `0`: collect metrics/EMAs, no automatic micro promotion.

Exit:
- With autostep off, micro index remains stable while observations update.

### Micro 2.2: Implement `KERNEL_PHASE_OBSERVATION_FLOOR`
- Add optional global observation floor override.
- Effective gate:
  - `effective_min_observations = max(stage.min_observations, global_floor)` when set.

Exit:
- Promotion gate respects effective floor.

### Micro 2.3: Surface Control-State in Policy Snapshot
- Include in policy snapshot/export:
  - autostep_enabled
  - observation_floor_override
  - effective_min_observations

Exit:
- `[KERNEL PHASE POLICY]` dump section includes these fields.

## Phase 3: Runtime Integration + Governance Integrity

### Micro 3.1: Kernel Ownership Boundary
- Keep phase runtime policy logic in:
  - [runtime_kernel/integration/kernel_phase_policy_runtime.py](runtime_kernel/integration/kernel_phase_policy_runtime.py)
- Keep app runtime methods delegating only:
  - [runtime/app_runtime.py](runtime/app_runtime.py)

Exit:
- No new duplicated kernel policy logic in app layer.

### Micro 3.2: Governance Payload Validation
- Ensure governance events carry new six-phase ids and stage/mode details.
- Verify consistency across target/transition/module activation events.

Exit:
- Event payloads reflect new map and control-state.

### Micro 3.3: Disable Semantics Regression Pass
- Validate required semantics:
  - disable pauses only that phase
  - cursor skips disabled phase
  - re-enable resumes saved micro index
  - completed_micro_total remains monotonic

Exit:
- Semantics confirmed in snapshot and event traces.

## Phase 4: Verification Gates

### Micro 4.1: Compile Gate
- Run:
  - `python -m py_compile adaptive_phase_program.py runtime/app_runtime.py runtime_kernel/integration/kernel_phase_policy_runtime.py runtime_kernel/integration/__init__.py`

Exit:
- Compile passes.

### Micro 4.2: Runtime Dump Gates (Newest Hard-15)
- Run:
  - `python preflight_dump_gate.py "Log Dump/<latest>.txt"`
  - `python preflight_dump_gate.py "Log Dump/<latest>.txt" --strict`

Exit:
- Both preflight gates pass.

### Micro 4.3: Final Checklist Review
- Verify Completion Criteria section (all 7 items) with explicit pass/fail marks.

Exit:
- All completion criteria pass.

## Execution Order
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4

## Risk Controls
- Preserve legacy persisted-state compatibility until migration is verified.
- Do not broaden log scans; validate via newest targeted hard-15 artifacts.
- Keep kernel policy ownership centralized in runtime_kernel integration modules.
