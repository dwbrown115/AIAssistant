# Full Goal Phase + Micro-Step Execution Plan

## Goal
Fully achieve the target kernel adaptive phase program defined in `phase_plans/NEXT_REFINEMENT_PHASE_MICRO_STAGE.md` by:
- replacing legacy runtime phase taxonomy with the target six-capability phase map,
- preserving adaptive promotion semantics,
- implementing missing control-surface knobs,
- completing kernel-first integration and validation gates.

## Current Gap Summary
Known gaps from audit:
- Runtime default phase map still uses legacy 5 phases in `adaptive_phase_program.py`.
- Missing control-surface knobs:
  - `KERNEL_PHASE_AUTOSTEP`
  - `KERNEL_PHASE_OBSERVATION_FLOOR`
- Core adaptive progression and governance emission are already present.

## Delivery Phases

## Phase 1: Spec Convergence
Objective: Align runtime phase and micro-stage specs with the target six-capability map.

### m1: Canonical IDs and Labels
- Define canonical phase ids and module ids exactly as target doc:
  - `phase_1_guess_ledger`
  - `phase_2_contradiction_accounting`
  - `phase_3_falsification_planner`
  - `phase_4_metric_decoupler`
  - `phase_5_abstraction_memory`
  - `phase_6_causal_counterfactual_planner`
- Keep micro-stage ids consistent:
  - `.m1_shadow_train`
  - `.m2_counterfactual_train`
  - `.m3_advisory_integrate`
  - `.m4_control_integrate`

Exit criteria:
- `build_default_kernel_phase_specs()` returns six phases with four micro stages each.

### m2: Capability and Signal Mapping
- Update each phase `capability`, `module_id`, and stage labels to match target intent.
- Map objective signals per micro stage to preserve training -> integration progression semantics.

Exit criteria:
- Snapshot output shows six phases and correct stage ids/labels in runtime state.

### m3: Backward Compatibility Bridge
- Add migration handling for persisted `kernel_phase_program_state`:
  - ignore unknown legacy phase ids,
  - preserve matching ids when possible,
  - do not crash on old payloads.

Exit criteria:
- App can start with old window/persistence state files without exceptions.

## Phase 2: Control-Surface Completion
Objective: Implement missing env controls and ensure behavior is observable.

### m1: `KERNEL_PHASE_OBSERVATION_FLOOR`
- Add optional global floor override in progression gating path.
- Effective min observations per stage:
  - `max(stage.min_observations, KERNEL_PHASE_OBSERVATION_FLOOR)` when override is set.

Exit criteria:
- Gate thresholds change when env var is set.
- Behavior visible in debug/governance payload (effective floor included).

### m2: `KERNEL_PHASE_AUTOSTEP`
- Implement `KERNEL_PHASE_AUTOSTEP` runtime flag:
  - `1`: current automatic observe/promote behavior (default).
  - `0`: freeze automatic progression promotions while still collecting EMAs/metrics.
- Manual phase/micro controls must continue to work when autostep is off.

Exit criteria:
- With autostep off, observations and EMAs change but micro index does not auto-advance.

### m3: Policy Snapshot Surfacing
- Extend kernel phase policy snapshot payload to include:
  - `autostep_enabled`
  - `observation_floor_override`
  - `effective_min_observations` for current micro.

Exit criteria:
- `[KERNEL PHASE POLICY]` dump section shows these fields.

## Phase 3: Kernel-First Runtime Integration Hardening
Objective: Ensure phase ownership stays in kernel integration module and app remains adapter/UI host.

### m1: Ownership Boundary Enforcement
- Keep phase policy logic in `runtime_kernel/integration/kernel_phase_policy_runtime.py`.
- Keep app methods in `runtime/app_runtime.py` as delegators only for kernel-phase runtime policy functions.

Exit criteria:
- No new kernel-phase policy logic reintroduced into app runtime method bodies.

### m2: Governance and Transition Integrity
- Confirm transition events and target/module activation events include new phase ids and mode details.
- Confirm disabled-phase behavior emits consistent payloads.

Exit criteria:
- `adaptive_phase_target`, `adaptive_phase_transition`, and `adaptive_phase_module_activation` contain new map identifiers.

### m3: Disable Semantics Validation
- Verify disable semantics remain correct under new map:
  - disabled phase paused only,
  - cursor skips disabled,
  - re-enable resumes prior micro index,
  - completed micro count remains monotonic.

Exit criteria:
- Behavior validated in runtime snapshots and preflight-compatible dumps.

## Phase 4: Verification and Gates
Objective: prove behavior with deterministic checks before declaring complete.

### m1: Static and Compile Checks
- Run:
  - `python -m py_compile adaptive_phase_program.py runtime/app_runtime.py runtime_kernel/integration/kernel_phase_policy_runtime.py runtime_kernel/integration/__init__.py`

Exit criteria:
- Compile succeeds with no errors.

### m2: Runtime Health and Dump Gates
- Execute a hard-15 run and validate latest dump:
  - `python preflight_dump_gate.py "Log Dump/<latest>.txt"`
  - `python preflight_dump_gate.py "Log Dump/<latest>.txt" --strict`

Exit criteria:
- Normal and strict preflight pass.

### m3: Goal-Completion Checklist
All must be true:
- Six-phase capability map live in runtime defaults.
- Four micro stages per phase with target ids.
- `KERNEL_PHASE_AUTOSTEP` implemented and validated.
- `KERNEL_PHASE_OBSERVATION_FLOOR` implemented and validated.
- Kernel policy snapshot exposes new control-surface fields.
- Governance events and dumps reflect new map and runtime policy.

Exit criteria:
- Checklist complete and documented in follow-up note.

## Suggested Execution Order
1. Implement Phase 1 (spec convergence) in `adaptive_phase_program.py`.
2. Implement Phase 2 controls and snapshot fields.
3. Validate boundary integrity and governance outputs (Phase 3).
4. Run compile + strict dump gates (Phase 4).

## Risk Controls
- Preserve backward compatibility with persisted window state payloads.
- Avoid broad log scans; use newest targeted dump checks only.
- Keep app runtime free of newly duplicated kernel policy logic.

## Done Definition
This plan is complete when runtime behavior and dumps prove full alignment with `phase_plans/NEXT_REFINEMENT_PHASE_MICRO_STAGE.md`, including control-surface completeness and strict preflight health.
