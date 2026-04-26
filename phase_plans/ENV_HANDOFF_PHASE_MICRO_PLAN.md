# Env Handoff Phase + Micro Plan

Superseded: This plan is retained for history only.

Active replacement:
- `phase_plans/ENV_HANDOFF_PHASE_MICRO_PLAN_V2.md`

Runtime wiring replacement:
- `adaptive_phase_program.py` phase `phase_2_impact_ranked_handoff_system` now uses impact-ranked env type systems from V2.

## Goal
Complete env ownership handoff so kernel policy knobs are kernel-owned, app/security vars stay app-owned, and repository structure has one canonical kernel runtime path.

## Canonical Kernel Runtime
- Canonical path: runtime_kernel/
- App host/runtime adapter path: runtime/
- Archived legacy code: deprecated/kernel_runtime_legacy/

Target state for active runtime code:
- Exactly one active kernel runtime folder: runtime_kernel/
- No active references to retired kernel_runtime/ path names.

## Ownership Contract

### App/Security-Owned
- OPENAI_API_KEY
- OPENAI_LOGIC_MODEL
- OPENAI_AGENT_MODEL
- OPENAI_MODEL
- HOST
- PORT
- FLASK_DEBUG
- REQUEST_METHOD
- SERVER_NAME
- SERVER_PORT
- SCRIPT_NAME
- QUERY_STRING
- REMOTE_ADDR

Rules:
- Boundary and transport concerns remain app-owned.
- Secrets stay in .env.secret and are never exported raw in dumps.

### Kernel-Owned
- ADAPTIVE_*
- LEARNED_AUTONOMY_*
- TRAINING_PHASE_*
- PARALLEL_REASONING_*
- Kernel phase runtime policy presets (code-owned defaults in kernel integration)
- Kernel phase disable/autostep/observation-floor runtime controls (app state + in-code defaults)
- MACHINE_VISION_*
- MAZE_MICRO_PROGRESSION_*
- MAZE_BATCH_MICRO_PROGRESSION_*
- SLEEP_CYCLE_*
- STM_*
- SEMANTIC_*
- PROJECTION_TRUST_*
- TERMINAL_TRUST_*
- HAZARD_PREPAREDNESS_*

Rules:
- Policy/tuning vars are consumed in kernel modules under runtime_kernel/.
- New kernel behavior knobs use kernel-oriented namespaces only.
- Disable-list values must use canonical phase ids from adaptive_phase_program phase specs.

### Shared Operational
- LOCAL_NAVIGATION_KERNEL
- LOCAL_NAVIGATION_API_FALLBACK

Rules:
- App owns mode/fallback orchestration.
- Kernel owns policy once local mode is active.

## Phase 1: Ownership Inventory Freeze

### Micro 1.1: Build Canonical Inventory
- Run env scan only on active paths (runtime_kernel/, runtime/, app.py, kernel modules).
- Exclude deprecated/ from ownership decisions.

Exit criteria:
- One reviewed inventory of env vars with owner classification.

### Micro 1.2: Classify Every Var
- Label each env var as app/security-owned, kernel-owned, or shared operational.
- Document all exceptions with a short rationale.

Exit criteria:
- No unclassified env vars in active runtime paths.

### Micro 1.3: Drift Gate
- Add review rule: new env vars require ownership tag before merge.

Exit criteria:
- Ownership classification present for each newly introduced env var.

## Phase 2: Runtime Handoff Enforcement

### Micro 2.1: Kernel Consumption Pass
- Ensure kernel-owned knobs are read in runtime_kernel/ modules or kernel controller files.
- Keep app runtime as adapter/delegator where possible.
- Verify disable-list config ingestion occurs before phase target selection.
- Verify current active target resolution continues to skip disabled/completed phases.

Exit criteria:
- Kernel-owned vars are not introduced as new app-only control logic.
- Disable-list/app adapter ordering is preserved during runtime initialization.

### Micro 2.2: Security Boundary Pass
- Keep secret-bearing vars at app boundary only.
- Verify dump/export paths redact secret-bearing fields.

Exit criteria:
- No raw secrets in debug/memory export payloads.

### Micro 2.3: Shared Ops Boundary
- Confirm LOCAL_NAVIGATION_* behavior remains orchestration-only at app layer.

Exit criteria:
- Shared operational vars do not leak into unrelated kernel policy branching.

### Micro 2.4: Adaptive Phase Control Surface Integrity
- Validate runtime control surface for adaptive phase progression:
  - phase disable toggles (runtime state)
  - autostep toggle (runtime state)
  - observation-floor override (runtime state)
- Enforce canonical phase-id examples in docs/config templates.
- Correct reference example to use phase_4_metric_decoupler (not phase_4_metric_decoupling).

Exit criteria:
- All adaptive phase control vars are classified kernel-owned and wired.
- Control surface examples map to real phase ids in active specs.

## Phase 3: Single-Folder Kernel Runtime Convergence

### Micro 3.1: Path Hygiene
- Remove stale references to retired kernel_runtime/ from active scripts/tools/docs where applicable.
- Keep runtime_kernel/ as the only active kernel runtime path.

Exit criteria:
- No active tooling points to kernel_runtime/ as a live folder.

### Micro 3.2: Archive Boundary
- Keep deprecated/kernel_runtime_legacy/ treated as archive only.
- Exclude deprecated/ from active scans, runtime wiring, and ownership decisions.

Exit criteria:
- Archive code has zero impact on active runtime behavior.

### Micro 3.3: Communication Update
- Update docs to explicitly state:
  - runtime_kernel/ is canonical kernel runtime,
  - runtime/ is app host adapter,
  - deprecated/kernel_runtime_legacy/ is historical archive.

Exit criteria:
- No ambiguity in folder ownership expectations.

## Phase 4: Validation Gates

### Micro 4.1: Static Validation
- Run compile checks on touched runtime files.

Exit criteria:
- Compile passes for modified Python files.

### Micro 4.2: Runtime Health Gate
- Run latest dump preflight normal + strict.
- Validate governance/introspection payloads include adaptive phase runtime policy, target, and transition telemetry.
- Track utility stability while phase progression remains data-driven (avoid treating phase completion alone as success).

Exit criteria:
- Preflight passes after env ownership and path hygiene updates.
- Runtime snapshots include adaptive phase policy + metric debug + transition visibility.
- Utility volatility is explicitly recorded for follow-up tuning if present.

### Micro 4.3: Completion Checklist
- One canonical active kernel runtime folder confirmed.
- Env ownership split documented and enforced.
- Security boundary retained for secret/process vars.
- No stale kernel_runtime live references in active tooling.
- Adaptive phase control surface uses canonical phase ids and is reflected in runtime policy snapshots.

Exit criteria:
- Checklist complete.

## Done Definition
The handoff is done when active runtime behavior and tooling treat runtime_kernel/ as the sole kernel runtime path, env ownership is classified and enforced, and security-owned vars remain app-boundary controlled.