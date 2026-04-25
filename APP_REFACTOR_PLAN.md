# App Refactor Plan (Monolith Split)

Date: 2026-04-19
Scope: behavior-preserving split of app.py into testable modules with incremental PRs

## 1) Current State Snapshot

Primary runtime is centered in app.py with key anchors:
- class AIAssistantApp at app.py:487
- _init_memory_db at app.py:2646
- _run_stepwise_goal_session at app.py:10389
- _build_ui at app.py:12159
- _run_sleep_cycle at app.py:12869
- _maze_agent_exploration_move at app.py:16956
- _best_exploration_move at app.py:17224
- _request_response at app.py:25732

Supporting modules already exist and should remain source-of-truth for their domains:
- adaptive_controller.py
- learned_autonomy_controller.py
- parallel_reasoning_engine.py
- governance_orchestrator.py
- maze/

## 2) Refactor Goals

- Reduce app.py from a single mega-class into composable modules.
- Preserve all current runtime behavior and env knob semantics.
- Keep Tk UI responsive and avoid introducing blocking regressions.
- Keep SQLite schema compatibility and migration safety.
- Enable smoke tests for critical paths before deeper changes.

## 3) Non-Goals

- No policy redesign.
- No tuning-default changes.
- No schema redesign beyond extraction-safe wrappers.
- No UI redesign.

## 4) Target Module Layout

Proposed package skeleton:

- runtime/
- runtime/app_state.py
- runtime/config.py
- runtime/event_log.py
- runtime/errors.py
- services/
- services/openai_gateway.py
- services/pipeline_logic.py
- navigation/
- navigation/session_runner.py
- navigation/exploration_policy.py
- navigation/maze_adapter.py
- persistence/
- persistence/memory_store.py
- persistence/schema_bootstrap.py
- maintenance/
- maintenance/sleep_cycle.py
- maintenance/hygiene.py
- ui/
- ui/main_window.py
- ui/panels.py
- ui/bindings.py

Mapping intent:
- app.py becomes thin composition root.
- AIAssistantApp keeps orchestration and widget ownership only.
- Heavy method groups move by domain to service objects with explicit dependencies.

## 5) Phase Plan

### Phase 0: Safety Baseline

Deliverables:
- Add lightweight smoke harness scripts for:
- App import and bootstrap sanity.
- DB init and schema migration path.
- Local navigation request path without API calls.
- Snapshot export/import dry-run.

Acceptance:
- Existing launch command still works.
- No behavior deltas in manual spot checks.

### Phase 1: Config Extraction

Move all env parsing from AIAssistantApp.__init__ into runtime/config.py.

Tactics:
- Create typed config objects grouped by domain:
- ModelConfig
- NavigationConfig
- MemoryConfig
- MaintenanceConfig
- UIConfig
- Keep default values exactly aligned with current code.

Acceptance:
- App starts with same defaults when env is empty.
- Existing .env knobs are honored unchanged.

### Phase 2: Persistence Split

Extract DB responsibilities around _init_memory_db and migration helpers:
- _init_memory_db
- _ensure_prediction_memory_schema
- _ensure_action_outcome_memory_schema
- _ensure_pattern_catalog_uncertainty_schema

Target:
- persistence/schema_bootstrap.py
- persistence/memory_store.py wrappers for repetitive sqlite3.connect usage.

Acceptance:
- Schema bootstrap remains idempotent.
- Existing maze_memory.sqlite3 works without manual migration.

### Phase 3: Maintenance Split

Extract:
- _run_sleep_cycle
- _maybe_run_sleep_cycle
- _run_step_hygiene
- _maybe_run_step_hygiene

Target:
- maintenance/sleep_cycle.py
- maintenance/hygiene.py

Acceptance:
- Sleep cycle summary lines and pruning behavior unchanged.
- Optional VACUUM behavior unchanged.

### Phase 4: Navigation Session Extraction

Extract from _run_stepwise_goal_session and helpers into navigation/session_runner.py.

Key boundary:
- Keep UI callbacks and status updates in app shell.
- Move core loop state transitions and selection logic to runner class.

Acceptance:
- Step-mode outputs and completion semantics match baseline.
- No increase in UI freeze incidents.

### Phase 5: Exploration Policy Extraction

Extract from:
- _best_exploration_move
- _maze_agent_exploration_move
- organism-control adapter methods

Target:
- navigation/exploration_policy.py
- navigation/maze_adapter.py

Acceptance:
- Selected move parity within expected stochastic variation.
- Guard overrides and telemetry fields remain present.

### Phase 6: Request Pipeline Split

Extract from _request_response and related logic helpers:
- _build_logic_plan
- _logic_resolve_repetition
- _logic_finalize
- _agent_propose_single_move
- _logic_evaluate_single_move

Target:
- services/pipeline_logic.py
- services/openai_gateway.py

Acceptance:
- Same fallback behavior between local kernel and OpenAI.
- Same debug panel fields.

### Phase 7: UI Composition Split

Extract from _build_ui and associated panel builders:
- ui/main_window.py
- ui/panels.py
- ui/bindings.py

Acceptance:
- Widget behavior and keyboard/mouse bindings unchanged.
- Window geometry persistence unchanged.

### Phase 8: Dead Code Decision

Evaluate kernel_runtime/app_kernel_mixin.py duplication status.

Decision options:
- Wire and adopt it as canonical runtime.
- Archive it explicitly and remove drift.

Known issue to resolve if activated:
- Missing import path in kernel_runtime/app_kernel_mixin.py:74 referencing hormone_blend_mixin.

Acceptance:
- Single canonical runtime path documented.

## 6) PR Sizing and Order

Use small PRs with rollback safety:
- PR1: runtime/config extraction only.
- PR2: persistence bootstrap/store extraction only.
- PR3: maintenance extraction only.
- PR4: navigation session extraction skeleton with parity mode.
- PR5: exploration policy extraction.
- PR6: request pipeline extraction.
- PR7: UI split.
- PR8: runtime duplication decision.

Per PR target:
- 300 to 900 changed lines where possible.
- One domain per PR.
- No cross-domain edits unless required for wiring.

## 7) Regression Gates

Manual gates per PR:
- Launch app via python app.py.
- Run one local maze request with LOCAL_NAVIGATION_KERNEL=1.
- Verify debug panel still includes logic/step logs.
- Trigger Sleep Cycle once and confirm summary output.
- Export and import snapshot once.

Automated gates to add early:
- Import smoke tests for extracted modules.
- Config parity tests against current defaults.
- Schema idempotency test for bootstrap.

## 8) Risks and Mitigations

Risk: hidden coupling via shared mutable state on self.
Mitigation: introduce explicit dependency objects and narrow method signatures.

Risk: behavior drift from env default mismatches.
Mitigation: lock defaults in config parity tests before extraction.

Risk: UI thread regressions.
Mitigation: preserve root.after boundaries and keep blocking work off UI thread.

Risk: sqlite concurrency or lock regressions.
Mitigation: centralize connection helper and keep transaction boundaries explicit.

## 9) First Implementation Slice

Recommended immediate start:
- Implement runtime/config.py and wire app.py constructor to consume typed config.
- Do not move logic yet.
- Add simple parity asserts for a handful of critical defaults.

This yields immediate readability gain with minimal behavior risk and sets up all downstream extraction phases.
