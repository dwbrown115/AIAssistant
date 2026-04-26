# Env Handoff Phase Micro Plan V2

## Objective

Complete the env handoff so handed-off controls exist only in kernel code and nowhere else.

Inputs:
- `phase_plans/ENV_HANDOFF_FULL_AUDIT.md`
- `phase_plans/_env_audit_tmp/*`

Guardrails:
- App/us boundary controls remain app-owned.
- No new env reader added for handed-off keys.
- Migration is impact-ranked by env type with verification after each micro stage.

## Ownership Contract For This Plan

App/us owned (stay env-driven at app boundary):
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_AGENT_MODEL`
- `OPENAI_LOGIC_MODEL`
- `PORT`
- `WERKZEUG_RUN_MAIN`
- `LOCAL_NAVIGATION_KERNEL`
- `LOCAL_NAVIGATION_API_FALLBACK`
- `LOCAL_MAP_AUTHORITY_MODE`
- `LOCAL_MAP_AUTHORITY_SOFT_SCALE`

Handoff target:
- 574 keys currently read in app runtime.

Remove now:
- 18 keys from `section_A_defined_not_read.txt`.

## Impact-Ranked Type Groups (Least -> Most)

### Removal Types (18 Total)

1. `R1_STARTUP_LEGACY` (1 key, least impact)
System: `startup_legacy_toggle_removal_system`
Keys: `AUTO_OPEN_BROWSER`

2. `R2_ADAPTIVE_GROWTH_LEGACY` (8 keys, low impact)
System: `adaptive_growth_legacy_removal_system`
Pattern: `ADAPTIVE_*` legacy growth/tuning keys no longer read in active code.

3. `R3_HORMONE_LEGACY` (7 keys, medium impact)
System: `hormone_decay_legacy_removal_system`
Pattern: `HORMONE_*` legacy decay toggles replaced by runtime behavior.

4. `R4_PROGRESSION_OVERRIDE_LEGACY` (2 keys, high impact)
System: `progression_override_legacy_removal_system`
Keys: `MAZE_BATCH_MICRO_PROGRESSION_PHASE2_REDUCTION`, `PHASE2_SOFT_OVERRIDE_ENABLE`

### Kernel-Management Types (574 Total)

1. `K1_TRUST_MEMORY_CONTROLS` (34 keys, low impact)
System: `trust_memory_kernel_management_system`
Prefixes: `TERMINAL_TRUST_`, `PROJECTION_TRUST_`, `HAZARD_PREPAREDNESS_`, `STM_`, `SEMANTIC_`, `ENDOCRINE_`

2. `K2_LEARNING_REASONING_CONTROLS` (53 keys, medium impact)
System: `learning_reasoning_kernel_management_system`
Prefixes: `ADAPTIVE_`, `LEARNED_AUTONOMY_`, `PARALLEL_REASONING_`

3. `K3_PERCEPTION_ENDOCRINE_CONTROLS` (64 keys, high impact)
System: `perception_endocrine_kernel_management_system`
Prefixes: `MACHINE_VISION_`, `HORMONE_`, `SLEEP_CYCLE_`

4. `K4_MAZE_POLICY_CONTROLS` (99 keys, high impact)
System: `maze_policy_kernel_management_system`
Prefix: `MAZE_`

5. `K5_CORE_RUNTIME_POLICY_CONTROLS` (324 keys, critical impact)
System: `core_runtime_policy_kernel_management_system`
Type: `OTHER` catch-all policy controls.

## Phase 0: Baseline Lock

### Micro 0.1: Freeze audit baseline
- Save current lists in `phase_plans/_env_audit_tmp/` as baseline artifacts.
- Confirm counts: defined 353, read 584, app-only 584, kernel-read 0.

Exit criteria:
- Baseline counts match `ENV_HANDOFF_FULL_AUDIT.md`.

### Micro 0.2: Protect boundary keepers
- Add explicit comment block in runtime startup code that lists 10 app/us keepers.
- Add CI grep check that only keeper keys are read in app boundary files.

Exit criteria:
- Any new non-keeper env read in app runtime fails validation.

## Phase 1: Immediate Cleanup

### Micro 1.1: Remove dead env definitions
- Delete all 18 keys listed in `section_A_defined_not_read.txt` from `.env` and `.env.example`.

Exit criteria:
- `section_A_defined_not_read.txt` becomes empty on re-audit.

### Micro 1.2: Mark read-not-defined as migration debt
- Treat all keys in `section_B_read_not_defined.txt` as mandatory handoff migration targets.
- Do not add these back into `.env`/`.env.example`.

Exit criteria:
- No new key from section B is introduced to env files.

## Phase 2: Impact-Ranked Handoff System

Migration pattern for each micro stage:
1. Introduce kernel code defaults in `runtime_kernel/**`.
2. Thread values through kernel runtime integration API.
3. Remove matching app-side env reads from `runtime/app_runtime.py` (and any other app file).
4. Remove migrated keys from `.env` and `.env.example`.
5. Re-run audit and validate stage gate.

### Micro 2.1
- Stage id: `p2.m1_remove_startup_legacy_envs`
- Type: `R1_STARTUP_LEGACY`
- System: `startup_legacy_toggle_removal_system`

### Micro 2.2
- Stage id: `p2.m2_remove_adaptive_growth_legacy_envs`
- Type: `R2_ADAPTIVE_GROWTH_LEGACY`
- System: `adaptive_growth_legacy_removal_system`

### Micro 2.3
- Stage id: `p2.m3_remove_hormone_decay_legacy_envs`
- Type: `R3_HORMONE_LEGACY`
- System: `hormone_decay_legacy_removal_system`

### Micro 2.4
- Stage id: `p2.m4_remove_progression_override_legacy_envs`
- Type: `R4_PROGRESSION_OVERRIDE_LEGACY`
- System: `progression_override_legacy_removal_system`

### Micro 2.5
- Stage id: `p2.m5_kernel_manage_trust_memory_controls`
- Type: `K1_TRUST_MEMORY_CONTROLS`
- System: `trust_memory_kernel_management_system`

### Micro 2.6
- Stage id: `p2.m6_kernel_manage_learning_reasoning_controls`
- Type: `K2_LEARNING_REASONING_CONTROLS`
- System: `learning_reasoning_kernel_management_system`

### Micro 2.7
- Stage id: `p2.m7_kernel_manage_perception_endocrine_controls`
- Type: `K3_PERCEPTION_ENDOCRINE_CONTROLS`
- System: `perception_endocrine_kernel_management_system`

### Micro 2.8
- Stage id: `p2.m8_kernel_manage_maze_policy_controls`
- Type: `K4_MAZE_POLICY_CONTROLS`
- System: `maze_policy_kernel_management_system`

### Micro 2.9
- Stage id: `p2.m9_kernel_manage_core_runtime_policy_controls`
- Type: `K5_CORE_RUNTIME_POLICY_CONTROLS`
- System: `core_runtime_policy_kernel_management_system`

Exit criteria:
- 18 removal keys deleted from env files.
- 574 handoff keys no longer read by app runtime.
- Handoff keys sourced from kernel code defaults only.

## Phase 3: App Boundary Hardening

### Micro 3.1: Reduce app env surface to keeper-only
- App runtime files may read only the 10 keeper keys.
- Any non-keeper key use in app code must fail CI.

Exit criteria:
- Re-audit shows app-side env reads = keeper set only.

### Micro 3.2: Kernel-only default registry
- Maintain one kernel default registry location per domain in `runtime_kernel/**`.
- Avoid split defaults between app and kernel modules.

Exit criteria:
- Handoff keys resolve from kernel code only.

## Phase 4: Validation Gates

### Micro 4.1: Static gate
- Re-run env audit.
- Confirm:
  - `section_C_app_only.txt` contains only keeper keys.
  - `section_D_app_and_kernel.txt` is empty or contains keeper-linked operational exceptions only.
  - `.env` and `.env.example` exclude handed-off keys.

Exit criteria:
- Static ownership contract satisfied.

### Micro 4.2: Runtime gate
- Run health checks on latest maze runs and normal startup flows.
- Ensure behavior parity after each wave.

Exit criteria:
- No regressions in startup, policy execution, or run stability.

### Micro 4.3: Drift prevention gate
- Add pre-merge check: non-keeper `os.getenv` in app runtime is blocked.
- Add reviewer checklist item for env ownership class.

Exit criteria:
- Ownership drift blocked by automation and review policy.

## Completion Checklist

- [ ] Bucket 1 keys removed from env files.
- [ ] Bucket 2 app/us keeper list unchanged and documented.
- [ ] Bucket 3 keys migrated to kernel code defaults.
- [ ] Phase-2 stage ids in adaptive progression match this V2 plan.
- [ ] Phase Progression UI shows active env system type, impact tier, key count, and system executor.
- [ ] App runtime reads only keeper keys.
- [ ] Kernel runtime contains handed-off policy defaults.
- [ ] Audit artifacts regenerated with target counts.
- [ ] Docs updated to reflect final ownership split.

## Done Definition

The handoff is complete when policy/tuning control keys are no longer env-driven from app runtime and exist only in kernel code, while app/us boundary controls remain explicitly app-owned.
