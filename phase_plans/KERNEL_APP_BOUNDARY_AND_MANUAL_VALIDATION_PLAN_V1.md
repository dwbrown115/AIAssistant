# Kernel-App Boundary and Manual Validation Plan V1

## Objective

Resolve the architecture and ownership concerns from the audit with explicit runtime boundaries:
- kernel owns policy and learning behavior
- app owns orchestration and state handoff
- UI owns rendering only
- validation remains manual-first with evidence artifacts

This plan is the review target for the next refactor tranche.

## Direct Resolution of Audit Findings

1. Web path separation (`web_app.py`) is effectively deprecated risk
- Decision: treat current web path separation as non-blocking legacy scope.
- Policy: no new feature work depends on web/runtime unification unless explicitly requested.

2. Deprecated runtime copy exists for posterity
- Decision: deprecated code is archival, not active runtime.
- Policy:
  - keep `deprecated/` for historical traceability.
  - enforce zero active imports from deprecated runtime paths.
  - preserve a lightweight periodic import check in manual review.

3. Endocrine logic, MV routing behavior, and kernel policy toggles must move to kernel ownership
- Decision: move these controls behind kernel integration surfaces.
- Policy:
  - app may pass context and receive decisions.
  - app must not own default policy logic for endocrine, MV routing, or kernel-phase toggle behavior.

4. Phase progress semantics across phases and phase-set changes
- Decision:
  - within a single active phase-set lineage, the completed state of phase N is the baseline for phase N+1.
  - across phase-set signature/version changes, restore is reset-gated (no blind carryover from old signatures).
- Policy:
  - preserve forward baseline handoff inside the same phase-set.
  - require signature/version compatibility gates for cross-set restoration.

5. Config surface is fragmented
- Decision: split app-controlled versus kernel-controlled variables into explicit ownership groups.
- Policy:
  - app settings: UI/runtime shell, launch/UX cadence, non-policy display controls.
  - kernel settings: planning/policy/learning/safety/phase behavior.
  - document ownership in one canonical map and keep defaults kernel-side where applicable.

6. UI extraction is partial
- Decision: reinforce app-as-data-provider and UI-as-renderer contract.
- Policy:
  - app computes state and emits display payloads.
  - UI modules render payloads and forward interactions; no policy decisions in UI layer.

7. Validation strategy
- Decision: manual testing is primary.
- Policy:
  - no requirement to build broad automated test coverage for this tranche.
  - use manual run protocol plus log/preflight evidence to validate behavior.

## Boundary Contract (Target State)

Kernel-owned domains:
- endocrine modulation primitives and scoring influence
- MV routing authority and beam/MV gate behavior
- kernel phase policy defaults, mode-policy payloads, and progression controls
- phase compatibility decisions and baseline carryover rules

App-owned domains:
- process lifecycle and runtime wiring
- state aggregation and payload assembly for UI panels
- user command intake, run initiation, and artifact export actions

UI-owned domains:
- panel/layout composition
- visualization of app-provided state
- user gesture forwarding back to app handlers

## Implementation Tracks

### Track A: Kernel Ownership Extraction

Scope:
- move endocrine, MV routing policy toggles, and kernel phase toggles from app-managed logic to kernel integration modules.

Deliverables:
- explicit kernel APIs for each moved control family.
- app runtime reduced to call-in/call-out orchestration for those families.

Exit criteria:
- app no longer sets behavioral defaults in these families.
- kernel modules are single source of truth for those defaults.

### Track B: Phase Baseline and Signature Rules

Scope:
- formalize baseline carryover and reset behavior.

Deliverables:
- documented compatibility ladder:
  - same phase-set signature: allow sequential baseline handoff.
  - changed signature/version: reset-gated restore path.

Exit criteria:
- no ambiguous cross-set carryover.
- baseline handoff is preserved for in-lineage progression.

### Track C: Config Ownership Split

Scope:
- publish canonical ownership map for env/runtime knobs.

Deliverables:
- one ownership matrix with columns:
  - variable/payload
  - owner (`app` or `kernel`)
  - source of default
  - runtime mutability

Exit criteria:
- every active toggle has one declared owner.
- duplicate ownership paths are removed.

### Track D: UI Render-Only Cleanup

Scope:
- remove remaining UI decision logic where present.

Deliverables:
- UI modules consume app payloads and callbacks only.
- policy decisions remain in app/kernel layers.

Exit criteria:
- UI files contain no policy computation branches beyond presentation concerns.

## Manual Validation Protocol (Primary)

### Window Recipe

Use fixed comparison windows with deterministic settings where practical:
1. medium set
2. hard set
3. very hard set
4. hard set

Example command profile:
- `solve 10 mazes; solve 15 mazes x2; solve 15 mazes x2; solve 15 mazes`

### Required Evidence Per Window

1. Human visual review notes
- loop behavior quality
- unresolved-objective behavior
- frontier-lock/recovery behavior
- MV routing behavior stability
- phase transition behavior

2. Artifact evidence
- log dump file reference
- preflight summary output
- short promote/hold/rollback note

3. Boundary integrity checks
- confirm deprecated runtime remains disconnected from live imports.
- confirm moved control families are kernel-driven.
- confirm UI panels only render app-provided payloads.

### Pass Rule

A change window passes only if both are true:
1. manual visual checklist passes
2. artifact/preflight evidence shows no regression beyond accepted thresholds

## Review Checklist (Concise)

Architecture:
- endocrine ownership is kernel-side
- MV routing ownership is kernel-side
- kernel policy toggles are kernel-side
- app/runtime remains orchestration-focused

Phase semantics:
- phase N terminal state seeds phase N+1 in same lineage
- changed phase-set signatures do not silently reuse incompatible snapshots

Config:
- app/kernel ownership map is explicit
- no duplicate owners for a live variable

UI:
- render-only behavior preserved
- no policy branching in UI modules

Validation:
- manual notes captured
- evidence artifacts captured
- promote/hold/rollback decision logged

## Rollback and Safety

Rollback triggers:
- repeated visual regressions in loop/recovery behavior
- unresolved objective spikes beyond accepted operating band
- evidence of cross-signature snapshot misuse
- any reintroduction of app-owned kernel policy defaults

Rollback action:
- revert last tuning tranche only
- preserve evidence package and write a short cause summary

## Out of Scope

- broad automated unit/integration test expansion for this tranche
- large web runtime reintegration work
- deletion of deprecated archival code kept for posterity

## Success Definition

This plan is successful when:
1. kernel/app/UI boundaries are explicit and upheld in code ownership
2. phase progression semantics are deterministic and reviewable
3. config ownership is clear and non-duplicative
4. manual validation workflow is repeatable and evidence-backed