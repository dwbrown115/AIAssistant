# Full Env Ownership Audit

## Scope

- Workspace: active runtime and entrypoints only.
- Included for env-read scan: `runtime/**`, `runtime_kernel/**`, `app.py`, `web_app.py`.
- Excluded: `deprecated/**`, `Log Dump/**`, `Log Dump OLD/**`, `kernel_runtime/Log Dump/**`, `.venv/**`, `__pycache__/**`, `.git/**`.
- Sources for definitions: `.env`, `.env.example`.

## Snapshot

- Defined keys (`.env` + `.env.example` unique): 353
- Read keys (active Python unique): 584
- Defined but not read: 18
- Read but not defined: 249
- Read in app runtime only: 584
- Read in kernel runtime (`runtime_kernel/**`): 0
- Read in both app and kernel: 0

Reader concentration:
- `runtime/app_runtime.py`: 577 keys
- `runtime/config.py`: 4 keys
- `web_app.py`: 4 keys

## Bucket 1: Remove Now

These keys are defined but not read in active code. Remove from `.env` and `.env.example` now.

- `ADAPTIVE_GROWTH_ERROR_THRESHOLD`
- `ADAPTIVE_GROWTH_PATIENCE`
- `ADAPTIVE_GROWTH_STEP`
- `ADAPTIVE_HIDDEN_MAX`
- `ADAPTIVE_L2`
- `ADAPTIVE_LEARNING_RATE`
- `ADAPTIVE_PRUNE_IMPORTANCE_THRESHOLD`
- `ADAPTIVE_PRUNE_INTERVAL`
- `AUTO_OPEN_BROWSER`
- `HORMONE_CONFIDENCE_DECAY`
- `HORMONE_CURIOSITY_DECAY`
- `HORMONE_DYNAMIC_LEGACY_BATCH12_SUPPRESSION_MAX`
- `HORMONE_DYNAMIC_LEGACY_ENABLE`
- `HORMONE_FATIGUE_DECAY`
- `HORMONE_REWARD_DECAY`
- `HORMONE_STRESS_DECAY`
- `MAZE_BATCH_MICRO_PROGRESSION_PHASE2_REDUCTION`
- `PHASE2_SOFT_OVERRIDE_ENABLE`

## Bucket 2: Keep App/Us Controlled

These remain app boundary controls and should not be handed off to kernel policy code.

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

## Bucket 3: Handoff To Kernel-Only Code

All remaining read keys after Bucket 2 are handoff candidates.

- Candidate total: 574
- Rule: once handed off, key cannot be read from app runtime (`runtime/app_runtime.py`, `runtime/config.py`, `web_app.py`).
- Rule: handed-off policy defaults must live only in kernel code (`runtime_kernel/**`).

Prefix distribution for 574 candidates:
- `OTHER`: 324
- `MAZE_`: 99
- `ADAPTIVE_`: 32
- `MACHINE_VISION_`: 24
- `HORMONE_`: 21
- `SLEEP_CYCLE_`: 19
- `PARALLEL_REASONING_`: 15
- `HAZARD_PREPAREDNESS_`: 9
- `STM_`: 9
- `LEARNED_AUTONOMY_`: 6
- `TERMINAL_TRUST_`: 6
- `PROJECTION_TRUST_`: 5
- `SEMANTIC_`: 3
- `ENDOCRINE_`: 2

Critical risk inside Bucket 3:
- 249 keys are currently read in code but not defined in `.env` or `.env.example`.
- This creates hidden/implicit env override surface and must be removed by migration to kernel-owned code defaults.

## Impact-Ranked Type Systems

Least-to-most impact ordering used by runtime phase progression replacement (`phase_2_impact_ranked_handoff_system`):

Removal systems (18):
- Rank 1: `R1_STARTUP_LEGACY` -> `startup_legacy_toggle_removal_system` (1)
- Rank 2: `R2_ADAPTIVE_GROWTH_LEGACY` -> `adaptive_growth_legacy_removal_system` (8)
- Rank 3: `R3_HORMONE_LEGACY` -> `hormone_decay_legacy_removal_system` (7)
- Rank 4: `R4_PROGRESSION_OVERRIDE_LEGACY` -> `progression_override_legacy_removal_system` (2)

Kernel-management systems (574):
- Rank 5: `K1_TRUST_MEMORY_CONTROLS` -> `trust_memory_kernel_management_system` (34)
- Rank 6: `K2_LEARNING_REASONING_CONTROLS` -> `learning_reasoning_kernel_management_system` (53)
- Rank 7: `K3_PERCEPTION_ENDOCRINE_CONTROLS` -> `perception_endocrine_kernel_management_system` (64)
- Rank 8: `K4_MAZE_POLICY_CONTROLS` -> `maze_policy_kernel_management_system` (99)
- Rank 9: `K5_CORE_RUNTIME_POLICY_CONTROLS` -> `core_runtime_policy_kernel_management_system` (324)

## Audit Artifacts

Generated artifact files (full lists):
- `phase_plans/_env_audit_tmp/defined_keys.txt`
- `phase_plans/_env_audit_tmp/read_keys.txt`
- `phase_plans/_env_audit_tmp/read_scope_matrix.tsv`
- `phase_plans/_env_audit_tmp/section_A_defined_not_read.txt`
- `phase_plans/_env_audit_tmp/section_B_read_not_defined.txt`
- `phase_plans/_env_audit_tmp/section_C_app_only.txt`
- `phase_plans/_env_audit_tmp/section_D_app_and_kernel.txt`
- `phase_plans/_env_audit_tmp/prefix_counts.txt`

## Enforcement Target

Done means all policy/tuning keys are kernel code defaults and app runtime is reduced to boundary inputs only.

Minimum end-state checks:
- No handoff-candidate key read via `os.getenv` or `os.environ*` in app runtime files.
- Kernel runtime owns policy defaults in code (not in `.env`).
- `.env` and `.env.example` keep only app boundary controls and non-policy operational values.
