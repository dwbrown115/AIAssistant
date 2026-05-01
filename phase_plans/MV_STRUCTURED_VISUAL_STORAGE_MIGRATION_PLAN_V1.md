# MV Structured Visual Storage Migration Plan V1

Sequencing note: unified phase ordering is now governed by `phase_plans/UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md`.

## Objective

Replace ASCII-first MV visual persistence with a structured, compact, retrieval-friendly representation that supports:
- higher-fidelity learning signals
- lower storage and token overhead
- fast retrieval for planning, training, and debugging

This plan is designed to run without breaking existing runtime behavior.

## Why Migrate from ASCII

ASCII is useful for human inspection but weak for long-term machine usage:
- poor density for multi-channel semantics
- lossy for confidence/probability fields
- expensive in prompts and exports at scale
- awkward for temporal sequence retrieval

## Core Data Model

Store each MV frame as structured channels with metadata.

Frame metadata:
- run_id, map_id, step_idx, episode_idx
- timestamp_ms
- grid_h, grid_w
- orientation/facing
- source flags (beam, MV, fused)

Channels (minimum):
- occupancy (wall/open/unknown)
- visibility (visible/half-visible/not visible)
- confidence (0..1)
- entities (agent, objective, hazards, interactables)
- optional motion delta (recent change map)

Optional derived features:
- frontier mask
- contradiction mask
- uncertainty heatmap

## Storage Options

Primary recommendation:
- SQLite metadata tables + BLOB payload for compact binary frame tensor

Alternative options:
- sidecar columnar files for long batch runs plus SQLite index rows
- compressed ndarray blocks per episode

Selection criteria:
- retrieval latency
- portability with snapshot export/import
- compatibility with existing dump and preflight tooling

## Migration Phases

### MV-D0: Schema and Contracts

What:
- Define canonical frame schema and versioning.
- Define encode/decode adapters and validation checks.

Exit criteria:
- schema version documented
- validator catches malformed frames reliably

### MV-D1: Dual-Write (ASCII + Structured)

What:
- Keep current ASCII writes for compatibility.
- Add structured writes in parallel.
- Log equivalence checks per sampled frame.

Exit criteria:
- structured writes present for all sampled windows
- frame equivalence pass rate >= 0.98 on sampled checks

Rollback trigger:
- structured write errors or equivalence failure spikes

### MV-D2: Retrieval and Feature API

What:
- Add API to retrieve structured frames by map_id/step range/context tags.
- Add compact feature-vector adapter for planner/trainer usage.

Exit criteria:
- retrieval p95 latency within target budget
- planner/trainer integration can consume feature adapter

### MV-D3: Prompt and Telemetry Transition

What:
- Stop emitting full ASCII blobs into routine prompt context.
- Replace with compact structured summaries and on-demand debug snippets.

Exit criteria:
- prompt token usage reduced meaningfully
- no regression in planning quality metrics

### MV-D4: Structured-First, ASCII Debug-Only

What:
- Make structured format default source of truth.
- Keep ASCII as opt-in debug export toggle only.

Exit criteria:
- two consecutive stable windows with structured-first path
- no tooling gaps in preflight/log review workflows

## Validation Metrics

- frame write success rate
- schema validation failure rate
- sampled equivalence pass rate
- retrieval latency (p50/p95)
- storage footprint delta
- prompt token usage delta
- planner quality delta

## Compatibility and Safety

- Never remove ASCII fallback until MV-D4 gate passes.
- Version all frame payloads for backward compatibility.
- Include migration helper in snapshot import path.
- Maintain app-truth authority for localization grading.

## Immediate Next Steps

1. Define `mv_frame_v1` schema and validator.
2. Implement dual-write adapter and sampled equivalence reporter.
3. Add retrieval API and benchmark report hooks.
4. Update preflight to read structured frame summary stats.
