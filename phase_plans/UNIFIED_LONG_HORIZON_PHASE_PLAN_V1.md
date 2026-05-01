# Unified Long-Horizon Phase Plan V1

## Objective

Provide one master phased roadmap that integrates all currently approved tracks into a single execution order:
- WB (beam-woven MV integration and decoupling)
- SC (Simon + cursor enrichment)
- MV-D (structured MV visual storage migration away from ASCII-first)
- RG (realtime game generalization readiness, including Doom-oriented preparation)

This document is the single sequencing source of truth.

## Scope and Source Plans

This unified plan integrates:
- `MV_BEAM_WOVEN_INTEGRATION_PHASE_PLAN_V2`
- `SIMON_CURSOR_POST_WB_PHASE_PLAN_V1`
- `MV_STRUCTURED_VISUAL_STORAGE_MIGRATION_PLAN_V1`
- `REALTIME_GAME_GENERALIZATION_READINESS_PLAN_V1`

The source plans remain valid as detailed reference specs, but phase order is governed by this document.

Operator checklist companion:
- [UNIFIED_LONG_HORIZON_OPERATOR_CHECKLIST_V1.md](UNIFIED_LONG_HORIZON_OPERATOR_CHECKLIST_V1.md)

## Global Non-Negotiable Contracts

- App-truth remains final authority for localization correctness.
- Promotion is evidence-based and reversible.
- Safety and completion floors must not regress.
- No untraceable hardcoded forcing shortcuts.
- Deterministic replayability must be preserved for sampled runs.

## Global Promotion and Rollback Policy

- Promote after two consecutive passing windows.
- Hold on exactly one failing window.
- Roll back one phase on two consecutive failures.
- Immediate rollback on safety-critical breach.
- During major cutover phases (WB6-WB8, MV-D4, RG5+), freeze further promotion until root cause closure after any catastrophic breach.

## Master Sequence

### Block A: WB Baseline Through MV-Decoupling

#### Phase U00 (WB0): Baseline Lock and Measurement Hygiene
- Freeze run protocol and dump hygiene.
- Exit: no malformed dumps; preflight coverage complete.

#### Phase U01 (WB1): Beam-Anchored MV Objective Equivalence Stabilization
- Enforce woven anchor conditions for MV objective equivalence.
- Exit: no anchor-logic anomalies.

#### Phase U02 (WB2): Dual-Evidence Objective Gate Hardening
- Keep objective routing in beam-anchor + MV-facts dual evidence mode.
- Exit targets:
  - guard override rate <= 0.55
  - learned-only rate >= 0.35
  - unresolved objective override rate <= 0.25

#### Phase U03 (WB3): Localization Reliability Recovery Before Authority Lift
- Improve player/exit localization reliability before influence lift.
- Exit targets:
  - hard: player >= 0.70, exit >= 0.60
  - very hard: player >= 0.50, exit >= 0.40

#### Phase U04 (WB4): Controlled MV Influence Lift
- Increase influence by calibration only.
- Exit: no completion degradation over two consecutive windows.

#### Phase U05 (WB5): Stage-Gated Advanced Experiments
- Run perturbation/contradiction/isolated route-planning stress windows.
- Exit: baseline recovery within one subsequent non-perturbed hard window.

#### Phase U06 (WB6): Beam Decoupling Start (Guard Attenuation Ladder)
- Attenuation steps A/B/C with woven truth contracts retained.
- Exit: two consecutive pass windows per attenuation step.

#### Phase U07 (WB7): MV-Primary with Beam Shadow
- Keep beam as shadow audit only.
- Exit targets:
  - shadow disagreement rate <= 0.20
  - disagreement-linked catastrophic failures <= 0.05

#### Phase U08 (WB8): Full Beam Decoupling Operational Cutover
- MV-only operational path with emergency rollback switch.
- Exit: three consecutive mixed windows pass all gates.

### Block B: SC Sensorimotor Enrichment Bridge

Activation gate for Block B:
- U08 completed (`phase_wb8_full_beam_decoupling_operational_cutover` complete in phase state)
- no catastrophic stability breach in latest two windows

#### Phase U09 (SC0): Instrumentation and Task Harness Readiness
- Add SC telemetry tags and preflight parse coverage.

#### Phase U10 (SC1): Simon Single-Step Reliability
- Short sequence replay (length 1-2).
- Exit: replay >= 0.90; invalid-action <= 0.05.

#### Phase U11 (SC2): Simon Memory Span Expansion
- Expand length and delayed replay.
- Exit: length-4 >= 0.78; length-5 >= 0.65.

#### Phase U12 (SC3): Kernel Cell-Intent Bridge (Grid-to-Cursor Translator)
- Kernel emits `target_cell_row/col`; app executes cursor action.
- Exit: validity >= 0.98; execution success >= 0.90.

#### Phase U13 (SC3.5): Pointer Dynamics Calibration
- Stabilize jitter/overshoot/click timing independent of policy.
- Exit: overshoot <= 0.08; click timing miss <= 0.03.

#### Phase U14 (SC4): Cursor Self-Localization Grounding
- Predict cursor coordinates; app-truth graded.
- Exit: exact-hit >= 0.70 (easy) and >= 0.55 (hard).

#### Phase U15 (SC4.5): Perception-Action Consistency Gate
- Enforce predicted-intended-landed triad consistency.
- Exit: triad consistency >= 0.92.

#### Phase U16 (SC5): Cursor Target Pursuit Control
- Target acquisition, efficiency, jitter suppression.
- Exit: acquisition >= 0.85; efficiency >= 0.75.

#### Phase U17 (SC6): Simon + Cursor Coupled Control
- Dual-task memory + cursor execution.
- Exit: dual-task completion >= 0.70.

#### Phase U18 (SC6.5): Grid OOD Transfer Validation
- Shifted board/cell/theme/distractor evaluations.
- Exit: degradation within tolerance bands.

#### Phase U19 (SC7): Transfer Bridge Back to Maze Runtime
- Inject warmups and evaluate maze behavior deltas.
- Exit: no regression beyond agreed tolerance; at least one meaningful positive delta.

#### Phase U20 (SC7.5): Supervisor and Recovery Protocols
- Add invalid-intent burst handling, safe reset, and audit-complete override behavior.
- Exit: recovery success >= 0.95; trace completeness = 1.00.

### Block C: MV Visual Storage Modernization

#### Phase U21 (MV-D0): Schema and Contracts
- Define `mv_frame_v1` schema, versioning, validation.

#### Phase U22 (MV-D1): Dual-Write (ASCII + Structured)
- Parallel writes with sampled equivalence checks.
- Exit: equivalence pass rate >= 0.98.

#### Phase U23 (MV-D2): Retrieval and Feature API
- Add map/step-range retrieval and compact feature adapter.
- Exit: retrieval p95 within target budget.

#### Phase U24 (MV-D3): Prompt and Telemetry Transition
- Replace routine ASCII prompt blobs with structured summaries.
- Exit: lower token usage without quality regression.

#### Phase U25 (MV-D4): Structured-First, ASCII Debug-Only
- Structured becomes source of truth; ASCII stays optional debug export.
- Exit: two stable windows and no tooling gaps.

### Block D: Realtime Game Generalization Readiness (Doom-Oriented)

Activation gate for Block D:
- U20 completed (supervisor/recovery maturity)
- U25 completed (structured visual memory operational)

#### Phase U26 (RG0): Interface Contract Freeze
- Game-agnostic observation/action/reward/safety contracts.

#### Phase U27 (RG1): Realtime Budget and Tick Discipline
- Per-tick latency budget + watchdog/degraded mode.
- Exit: p95 latency within budget.

#### Phase U28 (RG2): Hierarchical Action Stack
- Separate intent selection from low-level actuator control.

#### Phase U29 (RG3): Temporal Memory and Event Credit
- Improve delayed reward attribution in longer horizons.

#### Phase U30 (RG4): Controlled Adversarial and OOD Stress
- Shift tests across UI/map/dynamics/noise/partial observability.

#### Phase U31 (RG5): Safety Supervisor and Human Override
- Unsafe action interception and audit-complete overrides.

#### Phase U32 (RG6): Game Adapter Pilots
- Pilot lightweight realtime games before Doom-scale complexity.

### Block E: Robustness, Governance, and Release Hardening

Activation gate for Block E:
- U32 completed (at least two pilot game classes pass baseline gates)

#### Phase U33: Hidden Holdout and Anti-Overfitting Gate
- Create private holdout scenarios excluded from training/tuning loops.
- Track holdout-only performance drift relative to visible benchmark suites.
- Exit: holdout degradation remains within approved variance band over two windows.

#### Phase U34: Reward-Hacking and Shortcut Exploit Detection
- Add detectors for degenerate policy behavior (stall farming, looped exploit scoring, low-risk objective gaming).
- Add automatic exploit-tagged trace export for triage.
- Exit: no unresolved high-severity exploit pattern in two consecutive windows.

#### Phase U35: Catastrophic Forgetting Control
- Add retention suites for previously mastered capabilities (WB and SC milestones).
- Enforce retention floors during all new training phases.
- Exit: no retained-skill regression beyond tolerance across two windows.

#### Phase U36: Cross-Game Generalization Gate
- Require passing performance across multiple game genres before single-game optimization push.
- Minimum target set: at least three distinct game classes.
- Exit: all required classes pass agreed completion/safety floors.

#### Phase U37: Latency and Resource Exhaustion Resilience
- Run overload tests (CPU pressure, frame-drop bursts, delayed input streams, memory pressure).
- Validate degraded-mode behavior and recovery time.
- Exit: safe degraded operation with bounded recovery latency in all required stress profiles.

#### Phase U38: Human-In-The-Loop Intervention Ladder
- Formalize escalation ladder (`warn`, `throttle`, `freeze`, `safe_mode`, `manual_takeover`, `full_stop`).
- Require trace-tagged intervention reasons and outcomes.
- Exit: ladder activates correctly and audit trails are complete in sampled drills.

#### Phase U39: Replay Forensics and Failure Clustering
- Cluster failures by causal family, not one-off symptom.
- Integrate cluster summaries into phase review reports.
- Exit: >90% of high-severity failures mapped to tracked failure families.

#### Phase U40: Data Lifecycle and Retention Governance
- Define retention/compaction/expiration policies for logs, frame stores, and memory DB artifacts.
- Validate long-run stability under sustained storage churn.
- Exit: storage growth and retrieval latency remain within operational budgets.

#### Phase U41: Versioned Policy Release Channels
- Introduce `experimental`, `candidate`, and `stable` policy channels.
- Add channel-specific promotion gates and rollback snapshots.
- Exit: at least one complete promotion cycle from experimental to stable with successful rollback drill.

#### Phase U42: Security and Abuse Surface Hardening
- Constrain input/control scopes and unsafe automation boundaries.
- Add misuse-oriented threat checks and policy guard tests.
- Exit: no unresolved critical security/policy violations in release candidate windows.

## Doom and General-Game Readiness Options (Apply During U26-U32)

- Start with reduced action subsets before full control spaces.
- Enforce fixed action budgets per frame/tick (`sense -> decide -> act`).
- Use action masking/cooldown contracts to prevent impossible actions.
- Track combat/realtime metrics: survival time, damage efficiency, positioning error, panic-loop rate.
- Keep deterministic replay traces for sampled episodes and failures.

## Review Cadence

After each window:
- run preflight on new dumps
- publish pass/fail versus active phase gates
- record promote/hold/rollback decision
- attach short anomaly and root-cause notes

## Immediate Execution Start Point

- Continue at the currently active WB phase in runtime state.
- Use this unified sequence for all future promotion decisions.
- Do not begin Block B until U08 is formally complete.
- Do not begin Block E until U32 is formally complete.
