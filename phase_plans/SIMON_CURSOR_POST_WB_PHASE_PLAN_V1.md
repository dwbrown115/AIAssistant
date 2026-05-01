# Simon + Cursor Enrichment Plan (Post-WB) V1

Sequencing note: unified phase ordering is now governed by `phase_plans/UNIFIED_LONG_HORIZON_PHASE_PLAN_V1.md`.

## Objective

Add a structured sensorimotor enrichment track after WB completion using:
- Simon-style sequence memory training (perception -> working memory -> action replay)
- Cursor self-localization and cursor-target control training

Design intent:
- Extend capability after WB, not replace WB.
- Keep safety/truth contracts from WB intact.
- Treat this as developmental enrichment for stronger generalization and control precision before broader OOD tasks.

## Activation Gate (Must Pass Before Start)

Start this plan only if current WB program is complete.

Required checks:
- In `.phase_progress_state.json`, `kernel_phase_program_state.phases` shows all WB phases with `completed=1`.
- Specifically, `phase_wb8_full_beam_decoupling_operational_cutover` is `completed=1`.
- Latest two review windows show no catastrophic stability breach.
- Latest preflight checks pass without strict safety/truth regressions.

If any check fails:
- Do not start SC phases.
- Continue/repair WB progression until gate is green.

## Non-Negotiable Contracts

- App-truth remains the authority for localization correctness.
- No hidden hardcoded forcing introduced as a shortcut for Simon or cursor tasks.
- Learned-only behavior rate must not collapse relative to late-WB baseline.
- New channels must be telemetry-visible and reversible.
- Promotion is evidence-based; rollback is immediate on safety breach.

## Phase Structure

### Phase SC0: Instrumentation and Task Harness Readiness

What:
- Add dedicated telemetry tags for Simon and cursor episodes.
- Standardize run recipes and evaluation windows.
- Ensure preflight can parse new task sections cleanly.

Exit criteria:
- Structured logs exist for Simon and cursor metrics in every run.
- Preflight can summarize SC metrics without parse gaps.

Rollback trigger:
- Missing telemetry fields or malformed task dumps.

### Phase SC1: Simon Single-Step Reliability

What:
- Introduce very short Simon patterns (length 1-2).
- Train action replay from immediate perception.
- Keep environment deterministic and low noise.

Primary metrics:
- exact sequence replay rate
- invalid-action rate
- response latency consistency

Exit criteria:
- replay rate >= 0.90 for two consecutive windows
- invalid-action rate <= 0.05

Rollback trigger:
- replay rate < 0.75 for a full window.

### Phase SC2: Simon Memory Span Expansion

What:
- Increase sequence length gradually (for example 2 -> 3 -> 4 -> 5).
- Add delayed replay variants (short pause before response).
- Track confusion matrices (position errors vs symbol errors).

Primary metrics:
- span-specific replay accuracy
- error-type distribution
- recovery rate after first mistake

Exit criteria:
- length-4 replay accuracy >= 0.78
- length-5 replay accuracy >= 0.65
- recovery-on-next-trial >= 0.70

Rollback trigger:
- persistent collapse (>15% drop) across two consecutive windows.

### Phase SC3: Kernel Cell-Intent Bridge (Grid-to-Cursor Translator)

What:
- Add an intermediate control contract: kernel emits target cell intents, app executes cursor movement to that cell.
- Keep this as grid-indexed control first (row/col), not freeform pixel policy.
- Validate deterministic mapping from cell intent -> cursor screen position -> app action.

Control contract:
- Kernel output schema includes `target_cell_row`, `target_cell_col`, and optional `intent_confidence`.
- App executor validates bounds, maps cell-center coordinates, and performs cursor movement/click.
- App reports action outcome with app-truth verification (`reached_target_cell`, `cell_error_manhattan`).

Primary metrics:
- cell-intent validity rate
- cell-to-cursor execution success
- median cell error (Manhattan)
- latency from intent emission to action completion

Exit criteria:
- cell-intent validity >= 0.98
- execution success >= 0.90
- median cell error <= 0

Rollback trigger:
- invalid/out-of-bounds intent rate > 0.05 for a full window.

### Phase SC3.5: Pointer Dynamics Calibration

What:
- Calibrate app-side pointer execution quality independently from policy quality.
- Measure deterministic movement profile per board size and cell size.
- Tune click timing windows and motion smoothing before policy complexity increases.

Primary metrics:
- overshoot rate
- jitter amplitude
- click timing miss rate
- cell-center landing variance

Exit criteria:
- overshoot rate <= 0.08
- click timing miss rate <= 0.03
- landing variance stable across two windows

Rollback trigger:
- any metric degrades by >20% from previous window baseline.

### Phase SC4: Cursor Self-Localization Grounding

What:
- Train model to estimate cursor coordinates from local perception context.
- Grade against app-truth cursor location each step.
- Add confidence calibration for coordinate predictions.

Primary metrics:
- exact-hit accuracy
- Manhattan error mean/median
- calibration quality by confidence bucket

Exit criteria:
- exact-hit >= 0.70 on easy layouts and >= 0.55 on hard layouts
- median Manhattan error <= 1
- no high-confidence miscalibration drift window-over-window

Rollback trigger:
- exact-hit < 0.35 in any full window.

### Phase SC4.5: Perception-Action Consistency Gate

What:
- Add a strict consistency check among predicted cursor cell, intended target cell, and app-truth landed cell.
- Block promotion when representation drift appears despite apparent task success.

Primary metrics:
- triad consistency rate
- drift incidents per 100 steps
- confidence-calibration error during mismatches

Exit criteria:
- triad consistency >= 0.92
- drift incidents <= 3 per 100 steps

Rollback trigger:
- triad consistency < 0.80 for one full window.

### Phase SC5: Cursor Target Pursuit Control

What:
- Add cursor movement objective tasks (point to target cells/regions).
- Evaluate path efficiency and jitter suppression.
- Include controlled distractors and mild occlusion variants.

Primary metrics:
- target acquisition success
- steps-to-target efficiency ratio
- overshoot/jitter rate

Exit criteria:
- acquisition success >= 0.85
- efficiency ratio >= 0.75 vs shortest path baseline
- jitter/overshoot trend non-increasing over two windows

Rollback trigger:
- acquisition success < 0.65 for one full window.

### Phase SC6: Simon + Cursor Coupled Control

What:
- Interleave Simon memory tasks with cursor execution demands.
- Require preserving sequence memory while executing cursor control.
- Stress test task switching under bounded complexity.

Primary metrics:
- dual-task completion rate
- Simon retention under cursor load
- cursor precision under Simon load

Exit criteria:
- dual-task completion >= 0.70
- single-task metric degradation <= 12% from SC2/SC5 baselines

Rollback trigger:
- dual-task completion < 0.50 for two windows.

### Phase SC6.5: Grid OOD Transfer Validation

What:
- Validate robustness under controlled distribution shift without changing core task semantics.
- Run evaluation sets with changed cell size, board dimensions, color themes, and light distractor overlays.

Primary metrics:
- relative degradation vs in-distribution baseline
- recovery latency after shift introduction
- intervention spike under shift

Exit criteria:
- degradation remains within pre-agreed tolerance bands
- no persistent intervention spike over two shifted windows

Rollback trigger:
- severe OOD collapse (degradation >25% vs baseline) in any shift class.

### Phase SC7: Transfer Bridge Back to Maze Runtime

What:
- Inject bounded Simon/cursor warmups before maze windows.
- Validate whether enrichment improves maze stability and learned behavior.
- Keep WB8 contracts active during transfer checks.

Primary metrics:
- learned-only rate delta vs late-WB baseline
- intervention utility delta
- unresolved objective override rate delta
- completion ratio delta

Exit criteria:
- no regression beyond agreed tolerance bands across two mixed windows
- at least one significant positive delta in learned behavior or stability metrics

Rollback trigger:
- any safety/truth breach or sustained maze regression beyond tolerance.

### Phase SC7.5: Supervisor and Recovery Protocols

What:
- Add explicit runtime guardrails before broad game deployment.
- Define invalid-intent burst handling, timeout-to-safe-reset behavior, and human override controls.
- Ensure all overrides are trace-tagged for audit and postmortem.

Primary metrics:
- unsafe action interception rate
- recovery success rate
- mean time to safe state
- override trace completeness

Exit criteria:
- recovery success >= 0.95
- mean time to safe state within target budget
- override trace completeness = 1.00

Rollback trigger:
- any untraceable override event or failed safety recovery incident.

## Realtime Gameplay Readiness Hooks (Doom and General Games)

- Maintain a strict action-budget contract per frame/tick (`sense -> decide -> act` within fixed latency budget).
- Separate high-level policy intent from low-level motor executor to allow device/game API portability.
- Add action masking and cooldown contracts to prevent impossible or spam actions.
- Add uncertainty-aware fallback behaviors (`hold`, `retreat`, `safe-default`) for high-risk uncertainty windows.
- Track temporal credit assignment metrics (short horizon vs long horizon reward alignment).
- Require deterministic replay traces for sampled episodes so failures are reproducible.

## Promotion and Rollback Rules

- Promote after two consecutive passing windows at current SC phase.
- Hold if exactly one window fails.
- Roll back one phase after two consecutive failing windows.
- Roll back immediately on catastrophic safety/truth breach.

## Recommended Initial Run Recipe

For initial SC0-SC2 bring-up:
- easy: short deterministic windows for metric wiring verification
- medium: first reliability holdout
- hard: first stress holdout only after SC2 pass

For SC4-SC7:
- hard-first operational windows
- very-hard exploratory holdout after hard gate pass

For SC3.5, SC4.5, SC6.5, SC7.5:
- run one in-distribution window plus one shifted/stress window before promotion

## Deliverables Per SC Phase

- window definition and config snapshot
- metric summary with pass/fail decision
- anomaly list with likely root cause tags
- explicit next action: promote, hold, rollback

## Out of Scope (V1)

- Full Minesweeper policy integration.
- Broad OOD optimization beyond readiness-level checks.
- Permanent policy authority shifts based only on one SC phase.
