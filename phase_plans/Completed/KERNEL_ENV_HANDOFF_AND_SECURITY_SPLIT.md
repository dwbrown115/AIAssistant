# Kernel Env Handoff And Security Split

## Purpose

This document defines:
- which environment variables are owned by the app/security boundary,
- which environment variables are owned by kernel runtime policy,
- how ownership is enforced,
- and which kernel runtime folder is canonical.

Execution plan: see `phase_plans/ENV_HANDOFF_PHASE_MICRO_PLAN_V2.md` for phase/micro implementation sequencing and validation gates.

## Canonical Runtime Path

- Active kernel runtime code lives in `runtime_kernel/`.
- Legacy duplicate runtime code is archived in `deprecated/kernel_runtime_legacy/`.
- `kernel_runtime/` at repository root is intentionally retired.

## Env Loading Boundary

- App startup loads `.env` first, then `.env.secret`.
- `.env.secret` overrides `.env` for secret values.
- Secret values are never written into log dumps or exported debug traces.

## Ownership Split

### App/Security-Owned Variables

These are host, transport, or secret boundary concerns and remain app-owned:
- `OPENAI_API_KEY`
- model routing identifiers (`OPENAI_LOGIC_MODEL`, `OPENAI_AGENT_MODEL`, `OPENAI_MODEL`)
- web host/runtime variables (`HOST`, `PORT`, `FLASK_DEBUG`)
- process/request infrastructure variables (`REQUEST_METHOD`, `SERVER_NAME`, `SERVER_PORT`, `SCRIPT_NAME`, `QUERY_STRING`, `REMOTE_ADDR`)

Rules:
- Treat as boundary inputs.
- Do not persist raw secret values in memory exports.
- Pass only required capability/state into kernel runtime (not unrestricted secret surfaces).

### Kernel Runtime-Owned Variables

These are learning/control policy knobs and are kernel-owned:
- adaptive policy and controller tuning (`ADAPTIVE_*`)
- autonomy lifecycle and progression (`LEARNED_AUTONOMY_*`, `TRAINING_PHASE_*`)
- parallel reasoning policy and budgets (`PARALLEL_REASONING_*`)
- progression and memory tuning (`MAZE_MICRO_PROGRESSION_*`, `MAZE_BATCH_MICRO_PROGRESSION_*`, `SLEEP_CYCLE_*`, `STM_*`, `SEMANTIC_*`)
- perception/planning modulation and trust (`MACHINE_VISION_*`, `PROJECTION_TRUST_*`, `TERMINAL_TRUST_*`, `HAZARD_PREPAREDNESS_*`)
- kernel phase policy controls (`KERNEL_PHASE_POLICY_*`)

Rules:
- These can be consumed by kernel runtime modules directly.
- Any new kernel behavior knob should be namespaced to an existing kernel-oriented prefix.

### Shared Operational Variables

These are consumed at app boundary and influence kernel execution mode:
- `LOCAL_NAVIGATION_KERNEL`
- `LOCAL_NAVIGATION_API_FALLBACK`

Rules:
- App owns transport/fallback orchestration.
- Kernel owns internal decision policy once local mode is active.

## Inventory And Drift Control

- Use `script.py` for targeted env inventory in active kernel paths.
- `script.py` excludes archived code in `deprecated/` and scans `runtime_kernel/` as canonical runtime.
- Review new env additions against this split before merging.

## Change Management

When adding new env variables:
1. Classify as `app/security-owned`, `kernel-owned`, or `shared operational`.
2. Place secrets in `.env.secret` only.
3. Ensure log/export surfaces redact secret-bearing tokens.
4. Keep new kernel knobs within kernel namespaces and runtime modules.
