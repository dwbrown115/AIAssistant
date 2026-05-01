# Realtime Game Generalization Readiness Plan V1

Sequencing note: unified phase ordering is now governed by `phase_plans/UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md`.

## Objective

Prepare the current grid/maze-trained stack for broader game classes (including Doom-like realtime environments) without discarding existing safety and observability contracts.

This is a capability-readiness plan, not a full FPS implementation plan.

## Design Principles

- Keep policy and motor execution decoupled.
- Preserve deterministic replayability for debugging.
- Enforce safety constraints under realtime uncertainty.
- Promote only with evidence from staged stress windows.

## Capability Tracks

1. Perception Track
- Multi-channel state ingestion beyond ASCII/grid text
- Temporal stacking and motion-aware features
- Confidence and uncertainty propagation

2. Decision Track
- Action-budgeted planning (fixed ms per tick/frame)
- Hierarchical policy (`intent` -> `action primitive`)
- Risk-aware fallback actions under low confidence

3. Control Track
- Device abstraction layer (keyboard/mouse/controller)
- Action masking, cooldowns, and impossible-action filtering
- Motor smoothing and recoil/camera-stability compensation hooks

4. Learning and Evaluation Track
- Curriculum from deterministic -> stochastic -> adversarial
- OOD perturbation suites for map, UI, and dynamics shifts
- Episode replay and counterfactual analysis support

## Phase Structure

### RG0: Interface Contract Freeze

What:
- Define a game-agnostic interface for observations, action spaces, rewards, and safety events.
- Version contracts for environment adapters.

Exit criteria:
- contract tests pass for at least one existing grid task and one mock realtime task

### RG1: Realtime Budget and Tick Discipline

What:
- Introduce strict per-tick compute budget and watchdog behavior.
- Add degraded-mode path when budget is exceeded.

Primary metrics:
- decision latency p95/p99
- budget overrun frequency
- degraded-mode recovery quality

Exit criteria:
- p95 within budget on baseline realtime harness
- overrun frequency below agreed threshold

### RG2: Hierarchical Action Stack

What:
- Split high-level intent selection from low-level actuator commands.
- Keep low-level actuator deterministic and auditable.

Primary metrics:
- intent-to-action execution fidelity
- action invalidation/interception rate
- action-sequence stability

Exit criteria:
- stable execution fidelity across two windows

### RG3: Temporal Memory and Event Credit

What:
- Add short temporal context windows and event markers.
- Improve delayed reward credit assignment (survival, positioning, objective timing).

Primary metrics:
- temporal consistency score
- delayed-reward attribution stability
- intervention utility in long-horizon scenarios

Exit criteria:
- measurable gain in long-horizon benchmark without safety regression

### RG4: Controlled Adversarial/OOD Stress

What:
- Test map/UI/dynamics perturbations and partial observability stress.
- Include distractors, noisy feedback, and stochastic transitions.

Primary metrics:
- relative degradation vs in-distribution baseline
- recovery latency after perturbation
- safety event rate under stress

Exit criteria:
- degradation remains within allowed bands
- safety event rate remains below threshold

### RG5: Safety Supervisor and Human Override

What:
- Add explicit supervisor policies for unsafe behavior interception.
- Add audit-complete human override channels.

Primary metrics:
- unsafe action interception success
- mean time to safe state
- override trace completeness

Exit criteria:
- successful safe recovery in all required test scenarios
- full trace completeness in sampled audits

### RG6: Game Adapter Pilots

What:
- Pilot on simple non-grid and lightweight realtime tasks before Doom-scale complexity.
- Validate adapter portability and control abstraction.

Candidate pilot classes:
- 2D realtime dodge/shooter
- top-down action arena
- simple platform/reactive tasks

Exit criteria:
- adapter reuse across at least two game classes
- no critical regressions in core safety/replay tooling

## Doom-Oriented Options (When Ready)

- Start with reduced action space subsets (move, turn, fire) before full control set.
- Use frame-skip aware action timing to stabilize control loops.
- Add camera motion normalization and target-stability features.
- Introduce risk policy for low-health/high-threat states (`retreat`, `cover`, `disengage`).
- Track combat-relevant metrics: survival time, damage efficiency, positioning error, panic-loop rate.

## Required Infrastructure

- deterministic replay recorder with step-by-step action/state traces
- scenario pack format for repeatable stress tests
- realtime profiler for latency and budget diagnostics
- automatic failure clustering for rapid triage

## Promotion and Rollback Rules

- Promote after two consecutive passing windows.
- Hold on one failing window.
- Roll back on two consecutive failing windows.
- Immediate rollback on safety-critical breach.

## Immediate Next Steps

1. Implement RG0 interface contracts and tests.
2. Add RG1 latency budget telemetry and watchdog path.
3. Stand up one lightweight realtime pilot environment.
4. Run first OOD stress mini-suite and produce baseline report.
