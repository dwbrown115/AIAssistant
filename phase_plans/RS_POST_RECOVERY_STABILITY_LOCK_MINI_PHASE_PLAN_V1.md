# RS Post-Recovery Stability Lock Mini Phase Plan V1

Sequencing note: this plan now runs as an expanded short ladder (RS0 through RS7) with RS7 preserved as the terminal end state.

## Objective

Convert recent improvements into stable repeatable behavior by running a short targeted tuning pass focused on volatility cleanup.

Primary objective:
- Hold recent quality gains while reducing residual guard and unresolved-objective spikes.
- Progress through RS4-RS6 recertification steps before final RS7 handoff confirmation.
- Build trust in full-map MV route feeding before RS7, then hard-cut beam vision off at RS7 (runtime and UI).

## Current Context Snapshot

Based on the latest 10 hard-window dumps:
- pass/warn/fail: 5/5/0
- strongest windows show learned-only rates around 0.82 with zero guard/unresolved overrides
- pass/warn separator is currently sharp on two metrics:
   - pass windows: guard override up to `0.0474`, unresolved objective override up to `0.0272`
   - warn windows: guard override starts at `0.0523`, unresolved objective override starts at `0.0449`
- remaining risk is unresolved-objective tail pressure with occasional guard spikes

## Scope

In scope:
- guard override pressure normalization
- unresolved objective override pressure normalization
- stability confirmation under repeated hard windows

Out of scope:
- new capability expansion
- major profile redesign
- changing RS7 terminal end-state semantics

## Run Protocol

Use a short fixed protocol:
1. Run 4 consecutive hard windows.
2. Keep recipe and key runtime toggles fixed during the mini phase.
3. Evaluate each window with `preflight_dump_gate.py` (`batch4` profile).

Recommended window format:
- `15 mazes hard` per window (or equivalent fixed hard-window workload)

## Goal Gates (Data-Calibrated)

Use two gate tiers so progress is measurable while preserving a strict lock exit.

Tier A - Stabilization integration gate (window-level):
1. `preflight_status=pass`
2. `guard_override_rate <= 0.05`
3. `learned_only_rate >= 0.78`
4. `unresolved_objective_override_rate <= 0.03`

Tier B - Lock exit gate (streak-level):
1. 3 consecutive warning-free windows.
2. Per-window `guard_override_rate <= 0.05` and no single window above `0.08`.
3. Per-window `learned_only_rate >= 0.78`.
4. Unresolved objective lock:
   - at least 2 of the 3 lock windows at `unresolved_objective_override_rate <= 0.02`
   - no lock window above `0.03`

Tier C - Full-map MV trust gate (pre-cutover):
1. MV route mode is active for all windows in the trust block.
2. Cellmap readiness is stable (`ready` or `ready_relaxed`) with no sustained fallback-only behavior.
3. Objective progress is achieved via MV route authority, not beam-equivalent credit.
4. No fail windows during trust block.

## Expanded Phase Ladder (Runtime-Wired)

The live default progression is wired as:
1. RS0 - Recovery lock and evidence freeze
2. RS1 - Guard override stability lock
3. RS2 - Unresolved objective stability lock
4. RS3 - Warning-free hard-window lock
5. RS4 - Stability hold and variance compression
6. RS5 - Full-map MV trust accrual and route-authority rehearsal
7. RS6 - Cutover readiness recertification
8. RS7 - Full-map MV authority with beam runtime/UI retired (terminal end state)

Phase-level gate intent:
- RS1 exit: Tier A integrated (`>=3/4` windows satisfy Tier A).
- RS2 exit: unresolved objective remains `<=0.03` in `>=3/4` windows and `<=0.02` in `>=2/4` windows.
- RS3 exit: Tier B lock exit gate satisfied.
- RS4 exit: latest 4 windows are stability-hold quality (`>=3/4` pass, no fail, `guard_override_rate <= 0.06`, `learned_only_rate >= 0.76`).
- RS5 exit: latest 4 windows show MV trust rehearsal quality (`>=3/4` pass, no fail, Tier C satisfied).
- RS6 exit: latest 3 windows all pass with recert floor (`guard_override_rate <= 0.05`, `learned_only_rate >= 0.78`, `unresolved_objective_override_rate <= 0.03`) and Tier C held.
- RS7 exit: terminal confirmation phase governed by runtime RS7 stage completion with beam vision retired.

RS7 hard cutover policy:
- Beam-equivalent routing is disabled.
- Beam/FOV runtime credit is disabled.
- Beam/FOV UI surfaces are disabled (overlay and beam visualizer retired).
- Full-map MV route feed is the authoritative route signal.

## Targeted Tuning Surface

Adjust only the following families if gates are not met:
- guard pressure channels
- unresolved objective override channels

Do not tune unrelated subsystems during this mini phase.

Data-priority order for this cycle:
1. unresolved objective override reduction first (current tail is concentrated here)
2. guard spike suppression second (hold in the `<=0.05` band)
3. keep learned-only floor stable (`>=0.78`) while applying the above

## Decision Rules

Promotion/close-out:
- Mark Tier A as integrated when 3 of 4 windows satisfy Tier A gates.
- Move RS3 -> RS4 only when Tier B lock exit gate is satisfied.
- Close the expanded mini ladder only after RS6 recertification gates pass and RS7 reaches completion.

Hold:
- If exactly one Tier A gate misses in a window, hold settings and re-run one additional hard window.

Escalate to full tuning phase:
- If any of the following occurs, open a formal new tuning phase:
  - 2 consecutive warning windows
  - any fail window
  - repeated single-window guard spikes above `0.08`
   - unresolved objective override remains above `0.03` for 2 consecutive windows

## Evidence Package

For each window, retain:
- preflight status line
- `behavior_screen` line
- `projection_screen` line
- one short promote/hold/escalate decision note

Final mini phase summary should include:
- Tier A and Tier B gate pass/fail table across the latest 4-window cycle and final 3-window lock streak
- final recommendation:
  - `stable: continue normal progression`
  - or `unstable tail remains: start formal tuning phase`
