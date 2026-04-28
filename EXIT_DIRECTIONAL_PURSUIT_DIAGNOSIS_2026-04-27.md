# Exit Directional Pursuit Diagnosis (2026-04-27)

## User Report (Logged)
- Concern: the agent does not appear to consistently internalize directional movement semantics in behavior (`UP` means up, etc.) when routing toward an exit coordinate.
- Expected behavior:
  1. If an exit coordinate is available, attempt the most direct route toward it.
  2. If that route fails, follow corridors while maintaining general directional pressure toward the exit region.

## What The Runtime Currently Does

### 1. Direction semantics are implemented correctly in code
- Movement mapping is cardinal and consistent (`UP`, `DOWN`, `LEFT`, `RIGHT`) via one-cell neighbor transforms.
- Pathing and distance computations use those same transforms.
- Conclusion: this is not a low-level "UP means wrong direction" bug.

### 2. Strong direct routing exists only under strict objective conditions
- Objective route mode is driven when exit is known/visible in episodic map, or when MV beam-equivalent checks pass.
- In that mode, shortest-path and objective guards are used.
- This matches expected direct-routing behavior only after high-confidence/strict criteria are satisfied.

### 3. Pre-objective behavior is mostly soft bias, not a committed provisional pursuit mode
- During exploration scoring, MV exit alignment contributes only a score bonus/penalty.
- That signal competes with many larger safety/loop/dead-end penalties.
- There is no dedicated, stateful "provisional exit pursuit" mode that says:
  - commit to moving generally toward predicted exit,
  - tolerate short detours,
  - then fall back when contradiction evidence accumulates.

## Evidence Snapshot From Latest Run
- Latest run shows repeated objective-routing lines once strict activation happened (`Objective routing: exit visible/known...`, `MV-OBJECTIVE-ACTIVATE`, `MV-BEAM-EQUIVALENT`).
- This indicates the hard objective path works when gated conditions are met.
- The gap is before that threshold: directional intent toward predicted exit is not strongly staged as its own behavior mode.

## Do We Need Training Or Code?

## Decision
- Primary need: code/policy changes.
- Secondary need: targeted training can improve confidence quality, but training alone will not create the missing behavior contract.

## Why Code First
- The planner currently lacks an explicit intermediate policy state for "provisional coordinate pursuit with contradiction-aware rollback".
- Soft bonuses alone are too easy to overpower by anti-loop and hazard channels.

## Where Training Helps
- Better MV calibration and confidence reliability improve when provisional mode should engage/disengage.
- But training cannot enforce deterministic mode transitions or guard logic by itself.

## Recommended Implementation (Next Patch)

1. Add a provisional pursuit mode (new planner state)
- Trigger when MV exit prediction is usable and stable for N steps.
- Objective: minimize Manhattan distance to predicted exit while preserving safety constraints.

2. Add contradiction-aware rollback
- Exit provisional mode if contradiction signals rise (repeat loops, no-progress streak, local map contradictions).
- Then hand control to frontier/corridor exploration with retained directional bias.

3. Add corridor-follow + directional pressure blend
- When no direct progress move exists, prefer corridor-continuation that reduces projected distance to predicted exit region.
- Keep this weaker than hard safety vetoes but stronger than generic novelty when in provisional mode.

4. Add explicit telemetry fields
- `mode=provisional_exit_pursuit`
- `pred_exit_cell`, `pred_exit_conf`, `dist_to_pred_before/after`, `contradiction_budget`, `rollback_reason`
- This makes it obvious whether behavior is doing what we expect.

5. Add feature flags and tunables
- `MV_PROVISIONAL_PURSUIT_ENABLE=1`
- `MV_PROVISIONAL_MIN_CONF`
- `MV_PROVISIONAL_STABILITY_STEPS`
- `MV_PROVISIONAL_MAX_NO_PROGRESS`
- `MV_PROVISIONAL_DIRECTION_BIAS_WEIGHT`
- `MV_PROVISIONAL_ROLLBACK_CONTRADICTION_THRESHOLD`

## Acceptance Criteria
- Before true exit confirmation, logs show sustained provisional directional pressure toward predicted exit (with occasional safe detours).
- On contradiction, planner exits provisional mode and returns to corridor/frontier search.
- Once exit is confirmed/beam-equivalent, planner resumes strict objective shortest-path capture.
- Fewer long non-productive loops where predicted exit direction is known but behavior appears aimless.

## Practical Conclusion
- Plain-language summary: before objective gating, the runtime can treat the exit more like a cue it stumbles into than the dominant reward target; after gating, exit capture becomes the dominant goal policy.
- This is mainly a missing planner behavior stage, not a broken coordinate system.
- Implement the provisional pursuit mode first; then tune/training can refine confidence and switching quality.
