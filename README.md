# AI Assistant (Desktop + OpenAI)

Simple desktop app: type a prompt and view the model response in a native window.

Features:
- Two-model pipeline (logic model + agent model)
- Optional local-first navigation kernel for game/maze movement, with OpenAI fallback as training wheels when needed
- Optional per-request assistant instructions
- Pipeline debug panel (logic plan + agent output)
- Step-by-step control loop (agent proposes one move, logic evaluates each move)
- Copy Output button to copy prompt, response, and pipeline debug in one click
- Mini game: move a square to a random blue target ball
- Visible 8x8 chessboard-style grid for easier navigation
- Low-noise random path blockers (impassable cells)
- Second training mode: deterministic maze layouts with difficulty levels
- Live game-state snapshot fed to models (proximity + grid)
- Proximity signals (distance + hotter/colder) fed to models each turn
- Reward system favors shortest-path movement efficiency
- Agent can output `{"moves": ["UP", "RIGHT", ...]}` to move the square
- Repeated goals (for example, "move to goal three times") execute as sequential target hits

## 1) Python environment

A local virtual environment is set up at `.venv`.

If you need to recreate it manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) API key setup

1. Put secrets in `.env.secret` (recommended), and non-secret settings in `.env`.
2. The app loads `.env` first, then `.env.secret` (secret values override).

```env
# .env.secret (recommended for secrets)
OPENAI_API_KEY=your_real_key_here
```

3. Add model and runtime choices to `.env`:

```env
OPENAI_LOGIC_MODEL=gpt-4.1-mini
OPENAI_AGENT_MODEL=gpt-4o-mini
# Optional: prefer the built-in navigation kernel for game/maze movement before using OpenAI.
LOCAL_NAVIGATION_KERNEL=1
# Optional: when local navigation stalls and OpenAI is available, fall back to the external models.
LOCAL_NAVIGATION_API_FALLBACK=1
# Optional: enable an extra logic-model repetition-resolver call (default 0 to reduce API usage).
ENABLE_LOGIC_REPETITION_RESOLVER=0
# Optional: enable logic-model finalizer for navigation responses (default 0 uses local summary text).
ENABLE_LOGIC_FINALIZER_FOR_NAVIGATION=0
# Optional: allow per-step AGENT+LOGIC hint calls in maze step mode (default 0 uses internal planner only).
MAZE_STEP_MODEL_HINTS=0
# Optional: targeted maze-only OpenAI arbitration during contradiction/stuck states.
MAZE_TARGETED_MODEL_ASSIST_ENABLE=1
# Optional: 0.0=kernel-only, 1.0=highest targeted model reliance.
MAZE_MODEL_ASSIST_RELIANCE=0.22
# Optional: max targeted maze-assist calls per goal episode and cooldown between calls.
MAZE_MODEL_ASSIST_MAX_CALLS_PER_EPISODE=6
MAZE_MODEL_ASSIST_COOLDOWN_STEPS=10
# Optional: intra-batch micro progression (batch-5.2 style) that ramps challenge as a run set advances.
MAZE_BATCH_MICRO_PROGRESSION_ENABLE=1
MAZE_BATCH_MICRO_PROGRESSION_MIN_RUN=8
MAZE_BATCH_MICRO_PROGRESSION_START_RATIO=0.2
MAZE_BATCH_MICRO_PROGRESSION_CURVE=1.15
MAZE_BATCH_MICRO_PROGRESSION_MAX_HARD_PHASE_BONUS=1
MAZE_BATCH_MICRO_PROGRESSION_MAX_OBJECTIVE_PHASE_BONUS=1
MAZE_BATCH_MICRO_PROGRESSION_ASSIST_RELIANCE_FLOOR=0.08
# Optional: additional late-batch attenuation of guard intensity and delayed stuck-reexplore triggers.
MAZE_BATCH_MICRO_PROGRESSION_GUARD_STRENGTH_REDUCTION=0.22
MAZE_BATCH_MICRO_PROGRESSION_STUCK_TRIGGER_NO_PROGRESS_BONUS=3
MAZE_BATCH_MICRO_PROGRESSION_STUCK_TRIGGER_REPEAT_BONUS=1
# Optional: stronger unresolved-objective suppression and softer cycle-avoid override at later intra-batch ramps.
MAZE_BATCH_MICRO_PROGRESSION_OBJECTIVE_UNRESOLVED_BONUS=1
MAZE_BATCH_MICRO_PROGRESSION_CYCLE_AVOID_MARGIN_REDUCTION=0.5
# Optional: if kernel-phase progression plateaus during batch execution,
# automatically inject extra harder maze runs (default difficulty: very hard).
MAZE_PLATEAU_EXTRA_HARD_ENABLE=1
MAZE_PLATEAU_EXTRA_HARD_STREAK=2
MAZE_PLATEAU_EXTRA_HARD_RUNS=1
MAZE_PLATEAU_EXTRA_HARD_MAX_TRIGGERS=2
MAZE_PLATEAU_EXTRA_HARD_MIN_BATCH_LOOP=2
MAZE_PLATEAU_EXTRA_HARD_DIFFICULTY=very hard
# Optional: persist micro progression between run sets/app restarts and require
# stronger completion quality before progress is committed.
MAZE_MICRO_PROGRESSION_PERSIST_ENABLE=1
MAZE_MICRO_PROGRESSION_PERSIST_MIN_COMPLETION_RATIO=0.9
MAZE_MICRO_PROGRESSION_PERSIST_REQUIRE_SUCCESS=1
MAZE_MICRO_PROGRESSION_PERSIST_MIN_RUN=8
# Optional: stricter persistence quality gates using completed-goal count and
# rolling batch-quality EMA (overall run-set health across recent batches).
MAZE_MICRO_PROGRESSION_PERSIST_MIN_COMPLETED_GOALS=8
MAZE_MICRO_PROGRESSION_PERSIST_MIN_BATCH_QUALITY_EMA=0.88
MAZE_MICRO_PROGRESSION_BATCH_QUALITY_EMA_DECAY=0.75
# Optional: allow persistent regression when underperformance repeats
# (for example batch 6.0 -> 5.9 after enough poor batches).
MAZE_MICRO_PROGRESSION_REGRESSION_ENABLE=1
MAZE_MICRO_PROGRESSION_REGRESSION_FAIL_STREAK=2
MAZE_MICRO_PROGRESSION_REGRESSION_MIN_RUN=8
MAZE_MICRO_PROGRESSION_REGRESSION_MAX_COMPLETION_RATIO=0.65
MAZE_MICRO_PROGRESSION_REGRESSION_MAX_BATCH_QUALITY_EMA=0.78
MAZE_MICRO_PROGRESSION_REGRESSION_MIN_COMPLETED_GOALS=0
MAZE_MICRO_PROGRESSION_REGRESSION_STEP_COUNT=1
MAZE_MICRO_PROGRESSION_REGRESSION_REQUIRE_FAILURE=1
# Optional: milliseconds between each executed game move.
GAME_MOVE_DELAY_MS=250
# Optional: milliseconds to pause on each look-around direction preview in maze step mode.
LOOK_AROUND_PREVIEW_MS=180
# Optional: auto-run shortest-path fallback when model output is ambiguous/non-executable.
ENABLE_PATH_FALLBACK=1
# Optional: logic confidence threshold (0-1) for ambiguity handling.
LOGIC_CONFIDENCE_THRESHOLD=0.55
# Optional: confidence threshold for logic repetition inference override.
REPEAT_CONFIDENCE_THRESHOLD=0.6
# Optional: max repeat-goal execution count parsed from prompts/plans.
MAX_REPEAT_EXECUTIONS=25
# Optional: reinforcement-first training mode. When enabled, step outcomes stop
# using penalty-based scoring and convert non-optimal decisions into bounded
# positive learning credit.
CONSTRUCTIVE_REINFORCEMENT_ONLY=1
CONSTRUCTIVE_LEARNING_CREDIT_SCALE=0.08
CONSTRUCTIVE_LEARNING_CREDIT_CAP=12.0
CONSTRUCTIVE_STAGNATION_CREDIT=0.25
# Optional: default maze-run count prefilled in the Enter text box as "solve X mazes".
DEFAULT_MAZE_RUN_LENGTH=10
# Optional: challenge profile toggle defaults and behavior.
# CHALLENGE_MODE_DEFAULT_ON=1 starts app with Challenge Mode enabled.
CHALLENGE_MODE_DEFAULT_ON=0
# Optional: Challenge Mode enforces hard difficulty when enabled.
CHALLENGE_MODE_FORCE_HARD_DIFFICULTY=1
# Optional: Challenge Mode prefill prompt target (clamped by MAX_REPEAT_EXECUTIONS).
CHALLENGE_MODE_RUN_LENGTH=25
# Optional: randomize Start # once when Challenge Mode is enabled.
CHALLENGE_MODE_RANDOMIZE_START_ON_ENABLE=1
# Optional: contradiction-triggered map-doubt mode to re-enable exploration when fully-mapped routing stalls.
MAZE_MAP_DOUBT_ENABLE=1
MAZE_MAP_DOUBT_REPEAT_THRESHOLD=3
MAZE_MAP_DOUBT_STALL_THRESHOLD=2
MAZE_MAP_DOUBT_COOLDOWN_STEPS=8
# Optional: stuck-loop detector + temporary re-exploration mode when movement repeats without progress.
MAZE_STUCK_REEXPLORE_ENABLE=1
MAZE_STUCK_REPEAT_THRESHOLD=4
MAZE_STUCK_NO_PROGRESS_THRESHOLD=6
MAZE_STUCK_WINDOW=14
MAZE_STUCK_REEXPLORE_COOLDOWN_STEPS=4
# Optional: stuck-mode prediction gate + scaling for low-confidence branch re-checks.
MAZE_STUCK_PREDICTION_CONF_FLOOR=0.08
MAZE_STUCK_PREDICTION_BIAS_SCALE=0.35
# Optional: unresolved micro-frontier stall detector (tiny frontier pocket + no-progress streak)
# that relaxes guard hold behavior to break local loop replay.
MICRO_FRONTIER_STALL_ENABLE=1
MICRO_FRONTIER_STALL_WINDOW_STEPS=4
MICRO_FRONTIER_STALL_UNKNOWN_MAX=2
MICRO_FRONTIER_STALL_FRONTIER_MAX=3
# Optional: include tiny unresolved closure pockets (unknown>0, frontier=0)
# in micro-stall detection so near-resolved deadlock loops still trigger guards.
MICRO_FRONTIER_STALL_INCLUDE_CLOSURE_POCKETS=1
MICRO_FRONTIER_STALL_NO_PROGRESS_MIN=8
MICRO_FRONTIER_STALL_REPEAT_MIN=1
MICRO_FRONTIER_STALL_ESCAPE_NO_PROGRESS_MIN=18
MICRO_FRONTIER_STALL_ESCAPE_REPEAT_MIN=2
MICRO_FRONTIER_STALL_ESCAPE_SCORE_MARGIN=24
MICRO_FRONTIER_STALL_ESCAPE_EMERGENCY_NO_PROGRESS_DELTA=8
# Optional: hard cap for prolonged tiny-pocket replay (for example unknown=1/frontier<=1);
# triggers one forced disambiguation detour, then rearms after cooldown.
MICRO_FRONTIER_STALL_DISAMBIGUATION_ENABLE=1
MICRO_FRONTIER_STALL_DISAMBIGUATION_NO_PROGRESS_CAP=32
MICRO_FRONTIER_STALL_DISAMBIGUATION_STREAK_CAP=10
MICRO_FRONTIER_STALL_DISAMBIGUATION_MIN_REPEAT=2
MICRO_FRONTIER_STALL_DISAMBIGUATION_COOLDOWN_STEPS=18
# Optional: score shaping while micro-frontier stall is active.
# Escape bonus favors moves that expose uncertainty/frontier signal;
# loop penalty suppresses fully-known non-progress replays in the same pocket.
MICRO_FRONTIER_STALL_SCORE_ESCAPE_BONUS_SCALE=1.0
MICRO_FRONTIER_STALL_SCORE_LOOP_PENALTY_SCALE=1.0
MICRO_FRONTIER_STALL_SCORE_MAX_BONUS=54
MICRO_FRONTIER_STALL_SCORE_MAX_PENALTY=46
# Optional: soften micro-frontier recovery from hard overrides into adaptive score influence
# (used first when override attenuation phase is active; emergencies can still force escape).
MICRO_FRONTIER_STALL_SOFT_ENABLE=1
MICRO_FRONTIER_STALL_SOFT_MARGIN=10
MICRO_FRONTIER_STALL_SOFT_REPEAT_BOOST=8
MICRO_FRONTIER_STALL_SOFT_RISK_BOOST=10
MICRO_FRONTIER_STALL_SOFT_SIGNAL_BONUS=6
# Optional: macro no-progress escape guard for unresolved non-micro loop states.
LONG_LOOP_ESCAPE_ENABLE=1
LONG_LOOP_ESCAPE_NO_PROGRESS_MIN=48
LONG_LOOP_ESCAPE_REPEAT_MIN=1
LONG_LOOP_ESCAPE_SCORE_MARGIN=36
LONG_LOOP_ESCAPE_MIN_UNKNOWN=3
LONG_LOOP_ESCAPE_EMERGENCY_NO_PROGRESS_DELTA=16
# Optional: gradual long-loop subtype learner. Reinforces loop-prone transitions
# when long-loop/deathloop guards intervene, then applies a decaying soft penalty
# in similar repeat-pressure contexts.
LONG_LOOP_SUBTYPE_LEARNING_ENABLE=1
LONG_LOOP_SUBTYPE_LEARNING_RATE=0.18
LONG_LOOP_SUBTYPE_DECAY_STEPS=220
LONG_LOOP_SUBTYPE_MAX_PENALTY=56
LONG_LOOP_SUBTYPE_MIN_REPEAT_PRESSURE=2
LONG_LOOP_SUBTYPE_PENALTY_SCALE=1.0
LONG_LOOP_SUBTYPE_RELIEF_SCALE=0.35
# Optional: extra transition taboo pressure during stuck cooldown only.
MAZE_STUCK_TRANSITION_REPEAT_BOOST=24.0
MAZE_STUCK_TRANSITION_REVERSE_BOOST=34.0
# Optional: reward penalty weight for revisiting previously visited cells.
REVISIT_PENALTY_WEIGHT=8.0
# Optional: reward penalty weight for immediate back-and-forth moves.
BACKTRACK_PENALTY_WEIGHT=12.0
# Optional: reject per-step moves that increase distance-to-target.
STRICT_PROGRESS_GUARD=1
# Optional: blocker density for random path blockers (0.08 to 0.42 used internally).
BLOCKER_DENSITY=0.18
# Optional: deterministic base seed for maze layouts.
MAZE_SEED=1337
# Optional: directional FOV max depth (forward reach in cells) for planner/runtime FOV.
# MV localization training snapshots are always generated at full grid size (NxN)
# so MV input dimensions stay aligned with the active maze size.
MAZE_FOV_DEPTH=5
# Optional: peripheral expansion amount (widens cone edges).
MAZE_FOV_PERIPHERAL=1
# Optional: cone width in degrees for biological-style field-of-view.
MAZE_FOV_CONE_DEGREES=95
# Optional: distance attenuation strength for light-like falloff.
MAZE_FOV_DISTANCE_FALLOFF=0.22
# Optional: attenuation per single-wall corner graze for ray-like around-corner peeking.
MAZE_FOV_CORNER_GRAZE_FACTOR=0.62
# Optional: half-visible wedge taper by distance (higher narrows wedges farther away).
MAZE_FOV_WEDGE_DISTANCE_SCALE=0.2
# Optional: additional side-to-side cone widening (degrees) for near-forward lateral cells.
MAZE_FOV_LATERAL_EXTRA_DEGREES=18
# Optional: near-depth range where lateral widening is strongest.
MAZE_FOV_LATERAL_NEAR_DEPTH=4.0
# Optional: lateral band width (in cells) eligible for side-visibility boosting.
MAZE_FOV_LATERAL_BAND_CELLS=2.5
# Optional: minimum half-visibility floor margin applied inside the lateral side band.
MAZE_FOV_LATERAL_FLOOR_MARGIN=0.04
# Optional: visibility thresholds (full and half-visible classification).
MAZE_FOV_FULL_THRESHOLD=0.22
MAZE_FOV_HALF_THRESHOLD=0.08
# Optional: when maze step limit is hit, return-to-start also clears known maze state (default keeps memory on same maze).
MAZE_STEP_LIMIT_RESET_ENABLE=1
RESET_MAZE_KNOWLEDGE_ON_STEP_LIMIT=0
# Optional: +/- score noise added to each maze exploration decision to reduce deterministic repeats.
DECISION_NOISE_WEIGHT=3.0
# Optional: randomly choose among moves within this score band of the best move.
EXPLORATION_TIE_BAND=2
# Optional: enable random tie/near-tie move selection and randomized frontier BFS expansion order.
EXPLORATION_RANDOMIZE_TIES=1
# Optional: extra +/- jitter used for near-best ties to avoid deterministic action replay.
EXPLORATION_TIE_NOISE=0.03
# Optional: episode-level exploration personality variation (0 disables personality archetypes).
MAZE_PERSONALITY_VARIATION=1
# Optional: recent transition window size used for loop/cycle detection.
RECENT_CYCLE_WINDOW=12
# Optional: additive penalty per repeated directed transition in recent window.
CYCLE_TRANSITION_PENALTY_WEIGHT=26.0
# Optional: additive penalty per repeated reverse transition pair (A<->B ping-pong).
CYCLE_PAIR_PENALTY_WEIGHT=34.0
# Optional: max allowed score loss when overriding a loop-prone move to escape cycles.
CYCLE_GUARD_SCORE_MARGIN=10
# Optional: additional penalty for immediate backtrack candidates when another legal non-backtrack move exists.
IMMEDIATE_BACKTRACK_HARD_PENALTY=34
# Optional: additive penalty weight for repeated transition pressure in low-information revisits.
TRANSITION_PRESSURE_REPEAT_PENALTY_WEIGHT=9
# Optional: base bonus applied when transition pressure is high and a move exits recent trap cells.
ESCAPE_BIAS_BONUS=18
# Optional: penalty for re-entering recently forced corridor cells during loop pressure.
FORCED_CORRIDOR_REENTRY_PENALTY=28
# Optional: scales recalled cause-effect penalties when a move is visibly terminal/boxed.
TRAP_CAUSE_EFFECT_PENALTY_SCALE=1.7
# Optional: repeated trap-transition count needed before a transition becomes taboo.
CYCLE_TABOO_THRESHOLD=3
# Optional: number of steps a taboo transition remains strongly suppressed.
CYCLE_TABOO_DURATION_STEPS=12
# Optional: persistent loop-risk side-edge markers (red) set from repeated trap transitions;
# marked edges receive an additive score penalty until pressure decays.
LOOP_RISK_MARK_ENABLE=1
LOOP_RISK_MARK_REPEAT_THRESHOLD=2
LOOP_RISK_MARK_MIN_VISITS=2
LOOP_RISK_MARK_UNKNOWN_MAX=0
LOOP_RISK_MARK_PENALTY=44
# Optional: large additive penalty for visibly terminal/boxed moves when non-terminal alternatives exist.
TERMINAL_CORRIDOR_HARD_VETO_PENALTY=220
# Optional: bonus for frontier-expanding choices when in high-risk revisited regions.
HIGH_RISK_FRONTIER_OVERRIDE_BONUS=26
# Optional: minimum Branch Tightening Score needed to activate branch-abandon mode.
BRANCH_TIGHTENING_ABORT_THRESHOLD=6
# Optional: additive penalty for continuing a tightening branch when escape alternatives exist.
BRANCH_TIGHTENING_ABORT_PENALTY=240
# Optional: score bonus for the escape branch selected during branch-abandon mode.
BRANCH_TIGHTENING_ESCAPE_BONUS=36
# Optional: number of recent cells to scan for remembered nearby frontier cues.
BRANCH_RECENT_FRONTIER_WINDOW=10
# Optional: max Manhattan distance when matching recent frontier memory against current origin.
BRANCH_RECENT_FRONTIER_MAX_DISTANCE=4
# Optional: enable biological-style structural interpretation signals in move scoring.
BIO_NAV_ENABLE=1
# Optional: base bonus when opening/junction geometry is detected or inferred.
BIO_NAV_OPENING_WEIGHT=18
# Optional: bonus for moves that escape tightening dead-end pressure.
BIO_NAV_DEAD_END_ESCAPE_WEIGHT=24
# Optional: novelty gain scale (unknown-neighbor increase) used by biological layer.
BIO_NAV_NOVELTY_SCALE=2.0
# Optional: forward-flow bonus when moving with corridor geometry.
BIO_NAV_CORRIDOR_FLOW_WEIGHT=8
# Optional: predictive penalty for committing into likely dead-end structure.
BIO_NAV_DEAD_END_PREDICTIVE_PENALTY=16
# Optional: penalty for recent-cell loop-risk moves without opening evidence.
BIO_NAV_LOOP_RISK_PENALTY=12
# Endocrine system (slow global modulators)
ENDOCRINE_ENABLE=1
# New hormone decays
H_CURIOSITY_DECAY=0.97
H_CAUTION_DECAY=0.93
H_PERSISTENCE_DECAY=0.965
H_MV_TRUST_DECAY=0.96
H_BOREDOM_DECAY=0.985
H_CONFIDENCE_DECAY=0.96
# Optional: anti-saturation damping near hormone bounds (prevents long-run lock-in at 0/1 edges).
HORMONE_SATURATION_HIGH_START=0.86
HORMONE_SATURATION_LOW_END=0.14
HORMONE_SATURATION_MIN_SCALE=0.30
# Optional: mild recovery pulse when caution+boredom are both persistently high.
HORMONE_DISTRESS_RECOVERY_ENABLE=1
HORMONE_DISTRESS_RECOVERY_THRESHOLD=0.86
HORMONE_DISTRESS_RECOVERY_STEP=0.016
# Optional: trigger stronger recovery when exploration_drive is deeply negative.
HORMONE_DISTRESS_EXPLORATION_DRIVE_THRESHOLD=-0.82
HORMONE_DISTRESS_DRIVE_RECOVERY_SCALE=1.55
# Optional: scales endocrine penalty updates during repeated terminal/boxed ping-pong churn.
HORMONE_TRAP_CHURN_PENALTY_SCALE=0.35
# Optional: reduce endocrine penalty shock from terminal/dead-end punishments.
HORMONE_DEAD_END_PENALTY_SCALE=0.30
HORMONE_TERMINAL_BOXED_PENALTY_SCALE=0.45
HORMONE_REPEAT_LOOP_PENALTY_SCALE=0.55
HORMONE_OUTCOME_PENALTY_CLIP=260
# Optional: keep persistence from over-locking during deep distress loops.
HORMONE_DISTRESS_PERSISTENCE_CAP=0.42
HORMONE_DISTRESS_PERSISTENCE_RELIEF_STEP=0.024
# New hormone scoring weights
HORMONE_CAUTION_DANGER_WEIGHT=18.0
HORMONE_CURIOSITY_NOVELTY_WEIGHT=14.0
HORMONE_BOREDOM_REPEAT_WEIGHT=10.0
HORMONE_CONFIDENCE_RISK_BONUS=8.0
HORMONE_MOMENTUM_BONUS_WEIGHT=6.0
HORMONE_MV_TRUST_BONUS_WEIGHT=9.0
# Phase 1-4 deprecation channels are retired in the live runtime path.
# Archived phase plans and transition helpers are in deprecated/.
# Optional: additional safety gate for objective override forcing; while unresolved uncertainty
# exceeds these caps, objective forcing stays disabled even if exit was recently visible.
OBJECTIVE_OVERRIDE_SAFE_MAX_UNKNOWN=1
OBJECTIVE_OVERRIDE_SAFE_MAX_FRONTIER=1
# Optional: adaptive objective-drive layer (soft replacement pressure for hard objective override).
# Think of this as temporary "objective excitement" when exit evidence appears.
OBJECTIVE_EXCITEMENT_ENABLE=1
OBJECTIVE_EXCITEMENT_DECAY=0.88
OBJECTIVE_EXCITEMENT_EXIT_BOOST=0.7
OBJECTIVE_EXCITEMENT_PATH_BOOST=0.18
OBJECTIVE_EXCITEMENT_MAX=2.5
OBJECTIVE_EXCITEMENT_SCORE_WEIGHT=24.0
OBJECTIVE_EXCITEMENT_PROGRESS_WEIGHT=16.0
OBJECTIVE_EXCITEMENT_CONFIDENCE_BLEND=0.35
# Optional: learned-autonomy subphase (runtime learner that attenuates hardcoded override
# channels as learned-only behavior and utility improve, and tightens unresolved objective
# override suppression when needed).
LEARNED_AUTONOMY_SUBPHASE_ENABLE=1
LEARNED_AUTONOMY_WARMUP_STEPS=120
LEARNED_AUTONOMY_EMA_DECAY=0.97
LEARNED_AUTONOMY_PHASE1_SCORE=0.62
LEARNED_AUTONOMY_PHASE2_SCORE=0.78
LEARNED_AUTONOMY_UNRESOLVED_TARGET=0.10
# Training-phase scaffold and kernel-phase progression tuning are now
# kernel-owned code defaults in runtime_kernel integration modules.
# The runtime no longer exposes TRAINING_PHASE_* or KERNEL_PHASE_* env knobs
# for these controls.
# Optional: parallel reasoning engine (runs local-score, adaptive, and
# deliberative evaluations in parallel and learns plan trust from outcomes).
PARALLEL_REASONING_ENGINE_ENABLE=1
PARALLEL_REASONING_EMA_DECAY=0.965
PARALLEL_REASONING_WARMUP_STEPS=140
PARALLEL_REASONING_MIN_CONFIDENCE=0.58
PARALLEL_REASONING_LOCAL_WEIGHT=1.0
PARALLEL_REASONING_ADAPTIVE_WEIGHT=1.0
PARALLEL_REASONING_DELIBERATIVE_WEIGHT=1.0
PARALLEL_REASONING_DELIB_UNKNOWN_WEIGHT=0.85
PARALLEL_REASONING_DELIB_FRONTIER_WEIGHT=0.95
PARALLEL_REASONING_DELIB_LOOKAHEAD_WEIGHT=0.8
PARALLEL_REASONING_DELIB_LOOP_PENALTY_WEIGHT=0.8
PARALLEL_REASONING_DELIB_HAZARD_PENALTY_WEIGHT=0.65
PARALLEL_REASONING_DELIB_CONTRADICTION_PENALTY_WEIGHT=0.55
# Optional: per-maze solve-time tracking + metaphorical fast-solve treat bonus.
MAZE_FAST_SOLVE_TREAT_ENABLE=1
MAZE_FAST_SOLVE_TREAT_MAX_BONUS=24.0
MAZE_FAST_SOLVE_TREAT_TARGET_MULTIPLIER=1.85
MAZE_FAST_SOLVE_TREAT_MIN_TARGET_SECONDS=8.0
# Deprecated legacy endocrine decays (kept for transition)
HORMONE_STRESS_DECAY=0.90
HORMONE_CURIOSITY_DECAY=0.97
HORMONE_CONFIDENCE_DECAY=0.96
HORMONE_FATIGUE_DECAY=0.98
HORMONE_REWARD_DECAY=0.95
# Deprecated legacy endocrine scoring knobs (still blended while migrating)
ENDOCRINE_STRESS_DANGER_WEIGHT=18.0
ENDOCRINE_CURIOSITY_NOVELTY_WEIGHT=14.0
ENDOCRINE_FATIGUE_REPEAT_WEIGHT=10.0
ENDOCRINE_CONFIDENCE_RISK_BONUS=8.0
ENDOCRINE_MOMENTUM_BONUS_WEIGHT=6.0
# Optional: enable live organism-control policy route for maze move arbitration.
ORGANISM_CONTROL_ENABLE=1
# Optional: recent action/position window used by organism ESCAPE_LOOP inhibition.
ORGANISM_RECENT_WINDOW=10
# Optional: enable modular maze controller (world_model + frontier_memory + veto/policy stack).
MAZE_AGENT_ENABLE=1
# Optional: action/transition cooldown steps after short cycle detection.
MAZE_AGENT_CYCLE_TABOO_DURATION=12
# Optional: consecutive corridor steps before switching into ESCAPE_CORRIDOR mode.
MAZE_AGENT_CORRIDOR_ESCAPE_THRESHOLD=5
# Optional: max steps to remain in ESCAPE_CORRIDOR mode before forced fallback choice.
MAZE_AGENT_ESCAPE_TIMEOUT=14
# Optional: corridor pressure needed to leave ESCAPE_CORRIDOR mode (lower exits sooner).
MAZE_AGENT_ESCAPE_EXIT_PRESSURE=0.25
# Optional: corridor pressure threshold where a corridor is considered overused.
MAZE_AGENT_CORRIDOR_OVERUSE_THRESHOLD=0.55
# Optional: modular controller scoring weights.
MAZE_AGENT_NOVELTY_WEIGHT=2.0
MAZE_AGENT_FRONTIER_WEIGHT=3.0
MAZE_AGENT_JUNCTION_BONUS=1.5
MAZE_AGENT_CORRIDOR_OVERUSE_PENALTY=4.0
MAZE_AGENT_DEAD_END_PENALTY=2.0
MAZE_AGENT_MOTIF_WEIGHT=1.0
MAZE_AGENT_LOOP_RISK_WEIGHT=3.0
# Optional: corridor geometry interpretation boosts.
MAZE_AGENT_CORRIDOR_FORWARD_BIAS=1.2
MAZE_AGENT_SIDE_OPEN_BIAS=0.8
# Optional: base penalty when a candidate move commits into a dead-end tip or pre-tip corridor (degree<=1, unknown neighbors<=1).
DEAD_END_END_SLAP_PENALTY=58.0
# Optional: stronger penalty for revisiting dead-end tip/pre-tip cells once learned in current maze episode.
DEAD_END_TIP_REVISIT_SLAP_PENALTY=92.0
# Optional: additive penalty when a move visibly runs into a blocked/bounds terminal end.
VISIBLE_TERMINAL_END_PENALTY=24
# Optional: score margin allowed when overriding a visible terminal-end branch.
TERMINAL_END_GUARD_MARGIN=8
# Optional: reduce terminal/boxed replacement margin while uncertainty remains unresolved.
TERMINAL_OVERRIDE_UNRESOLVED_MARGIN_REDUCTION=6
# Optional: under unresolved uncertainty, require terminal/boxed replacement moves
# to have repeat pressure no worse than the selected risky branch.
TERMINAL_OVERRIDE_REQUIRE_REPEAT_IMPROVEMENT_UNRESOLVED=1
# Optional: when enabled, never choose a visibly terminal dead-end branch if any non-terminal move is available.
TERMINAL_END_HARD_AVOID=1
# Optional: adaptive terminal/dead-end trust gate (non-punitive): scales terminal/dead-end
# suppression from observed utility and can automatically relax hard-avoid filtering when trust is low.
TERMINAL_TRUST_ADAPT_ENABLE=1
TERMINAL_TRUST_EMA_DECAY=0.97
TERMINAL_TRUST_MIN_SCALE=0.35
TERMINAL_TRUST_MAX_SCALE=1.0
TERMINAL_TRUST_WARMUP_STEPS=64
TERMINAL_TRUST_HARD_AVOID_MIN_SCALE=0.72
# Optional: additive penalty for visibly boxed corridors (walls on both sides) with no visible exit.
BOXED_CORRIDOR_NO_EXIT_PENALTY=36
# Optional: replay-memory guard to avoid repeatedly choosing recently catastrophic boxed/terminal moves.
MEMORY_RISK_REPLAY_GUARD_ENABLE=1
MEMORY_RISK_REPLAY_GUARD_MIN_REPEAT=2
MEMORY_RISK_REPLAY_GUARD_DECAY_THRESHOLD=120.0
MEMORY_RISK_REPLAY_GUARD_SCORE_MARGIN=90
MEMORY_RISK_REPLAY_GUARD_MAX_DETOUR=1
# Optional: reward (score reduction) when the exit is visibly detected along the looked corridor.
VISIBLE_EXIT_CORRIDOR_REWARD=42
# Optional: enable pseudo-3D first-person visualizer panel (`1`=on, `0`=off).
ENABLE_PSEUDO3D_VIEW=0
# Optional: maximum forward depth slices shown in the pseudo-3D visualizer.
PSEUDO3D_MAX_DEPTH=5
# Optional: max local-score margin where frontier-first may override scored move ranking.
FRONTIER_OVERRIDE_SCORE_MARGIN=6
# Optional: number of risky dead-end probes allowed per episode before stronger avoidance.
DEAD_END_LEARNING_ALLOWANCE=1
# Optional: base additive penalty for shallow dead-end commitments (depth 1-2).
SHALLOW_DEAD_END_PENALTY_BASE=18.0
# Optional: scales shallow dead-end penalty as frontier distance increases.
DEAD_END_FRONTIER_DISTANCE_SCALE=0.33
# Optional: additive penalty for revisiting known dead-end entrance cells in current episode.
REVISIT_DEAD_END_ENTRANCE_PENALTY=22.0
# Optional: additive penalty for committing into narrow known corridors (degree<=1, no unknown neighbors).
NARROW_CORRIDOR_PENALTY=8.0
# Optional: difficulty-based dead-end suppression scales.
EASY_DEAD_END_SCALE=1.5
MEDIUM_DEAD_END_SCALE=1.0
HARD_DEAD_END_SCALE=0.6
# Optional: increase dead-end suppression after each timeout reset within the same maze.
ATTEMPT_DEAD_END_ESCALATION=0.18
# Optional: run STM decay/prune/promotion every N memory steps (reduces per-step churn).
STM_PRUNING_INTERVAL_STEPS=6
# Optional: each memory access can probabilistically prune stale/unused STM entries.
STM_ACCESS_UNUSED_PRUNE_CHANCE=0.04
STM_ACCESS_UNUSED_PRUNE_MIN_AGE_STEPS=24
STM_ACCESS_UNUSED_PRUNE_MAX_ROWS=1
# Optional: periodically re-sample familiar signatures into STM to avoid over-pruning loops.
STM_FAMILIAR_RESAMPLE_INTERVAL=12
# Optional: retained memory-event history capacity in RAM (higher preserves longer run traces).
MEMORY_EVENT_LOG_MAXLEN=6000
# Optional: minimum movement-step gap between structural-memory snapshot writes.
STRUCTURAL_MEMORY_SNAPSHOT_INTERVAL_STEPS=6
# Optional: max rows retained in `maze_structural_memory` (0 disables cap).
STRUCTURAL_MEMORY_MAX_ROWS=12000
# Optional: minimum movement-step gap for automatic Memory Viewer refreshes.
MEMORY_VIEWER_REFRESH_INTERVAL_STEPS=8
# Optional: long-run efficiency profile (non-kernel cadence tuning only).
# `LONG_RUN_MODE_DEFAULT_ON=1` starts app with Long-Run Mode enabled.
LONG_RUN_MODE_DEFAULT_ON=0
LONG_RUN_MEMORY_VIEWER_REFRESH_INTERVAL_STEPS=20
LONG_RUN_STRUCTURAL_MEMORY_SNAPSHOT_INTERVAL_STEPS=14
LONG_RUN_LAYOUT_CELL_SNAPSHOT_INTERVAL_STEPS=24
LONG_RUN_ADAPTIVE_SAVE_INTERVAL_STEPS=240
LONG_RUN_ADAPTIVE_PROGRESS_REPORT_INTERVAL_STEPS=600
LONG_RUN_STEP_HYGIENE_INTERVAL_STEPS=36
LONG_RUN_STEP_HYGIENE_FULL_GC_INTERVAL_STEPS=300
LONG_RUN_STM_PRUNING_INTERVAL_STEPS=8
LONG_RUN_CAUSE_EFFECT_PRUNING_INTERVAL_STEPS=16
# Optional: sleep-cycle maintenance for long runs (prune/compress + usage reinforcement).
SLEEP_CYCLE_ENABLE=1
# Optional: run automatic sleep cycle every N movement steps (0 disables periodic auto cycle).
SLEEP_CYCLE_AUTO_INTERVAL_STEPS=0
# Optional: run an automatic sleep cycle each time a maze is completed.
SLEEP_CYCLE_AUTO_AFTER_MAZE_COMPLETION=1
# Optional: run an automatic sleep cycle after a requested run set completes successfully.
SLEEP_CYCLE_AUTO_AFTER_RUN_SET=1
# Optional: run an automatic sleep cycle immediately after each Log Dump write.
SLEEP_CYCLE_AUTO_AFTER_LOG_DUMP=1
# Optional: hormone-state pruning during sleep cycle (extra decay + pull toward homeostasis).
SLEEP_CYCLE_HORMONE_PRUNE_ENABLE=1
SLEEP_CYCLE_HORMONE_DECAY_PASSES=2
SLEEP_CYCLE_HORMONE_PULL_STRENGTH=0.08
SLEEP_CYCLE_HORMONE_EXTREME_THRESHOLD=0.95
# Optional: usage-based reinforcement boost applied during sleep cycle.
SLEEP_CYCLE_USAGE_BOOST=0.04
SLEEP_CYCLE_USAGE_RECENT_WINDOW_STEPS=96
# Optional: keep tail lengths for volatile in-RAM event logs after sleep cycle compaction.
SLEEP_CYCLE_MEMORY_EVENT_KEEP=1400
SLEEP_CYCLE_ENDOCRINE_EVENT_KEEP=240
# Optional: cap high-churn DB tables to recent rows during sleep cycle (0 disables table pruning).
SLEEP_CYCLE_ACTION_OUTCOME_KEEP_ROWS=120000
SLEEP_CYCLE_PREDICTION_KEEP_ROWS=160000
# Optional: run SQLite VACUUM after sleep-cycle pruning (off by default to avoid UI pauses).
SLEEP_CYCLE_VACUUM_ON_MANUAL=0
SLEEP_CYCLE_VACUUM_ON_AUTO=0
# Optional: export limits for Log Dump exports (0 = no truncation/full batch export).
MEMORY_EXPORT_SECTION_LIMIT=300
MEMORY_EXPORT_LOG_LIMIT=2000
MEMORY_EXPORT_DEBUG_LIMIT=3000
MEMORY_EXPORT_ASCII_MAX_LINES=220
# Optional: when enabled, strips LOOK SWEEP sections from exported ASCII blocks.
MEMORY_EXPORT_STRIP_LOOK_SECTIONS=1
# Optional: when enabled, ASCII snapshots are cropped to visible/observed areas
# and hidden cells are omitted from dense '?' output.
MAZE_ASCII_VISIBLE_ONLY=0
# Optional: number of decision steps to keep recent look-sweep snapshots in working memory context.
WORKING_MEMORY_LOOK_RETENTION_STEPS=10
# Optional: cap for retained look-sweep entries in short-term working memory context.
WORKING_MEMORY_LOOK_RETENTION_LIMIT=8
# Optional: reset-aware learning and post-reset exploration controls.
RESET_TRACE_WINDOW=48
POST_RESET_EXHAUSTION_PENALTY=120
RESET_FAILURE_TRANSITION_PENALTY=24
RESET_FAILURE_CELL_PENALTY=16
RESET_SUCCESS_TRANSITION_BONUS=10
POST_RESET_STM_RELAX_STEPS=24
# Optional: late-maze frontier lock and solved-region suppression.
FRONTIER_LOCK_UNKNOWN_THRESHOLD=3
FRONTIER_LOCK_FRONTIER_THRESHOLD=2
FRONTIER_LOCK_RETRY_BONUS=50
FRONTIER_LOCK_LOOP_PENALTY=50
SOLVED_REGION_PENALTY=500
LOOP_ENTROPY_WINDOW=8
LOOP_ENTROPY_THRESHOLD=1.2
# Optional: when frontier-lock proposes a move with severe recent punishment memory,
# allow a score fallback instead of forcing the same transition replay.
FRONTIER_LOCK_MEMORY_VETO_ENABLE=1
FRONTIER_LOCK_MEMORY_VETO_PENALTY=280
FRONTIER_LOCK_MEMORY_VETO_MARGIN=120
FRONTIER_LOCK_MEMORY_VETO_WINDOW=18
FRONTIER_LOCK_MEMORY_VETO_SCORE_MARGIN=120
# Optional: prevent forced frontier-lock/continuity moves when local score gap is too large.
FRONTIER_LOCK_FORCE_SCORE_GUARD_ENABLE=1
FRONTIER_LOCK_FORCE_SCORE_MARGIN=120
# Optional: stricter score-gap cap for unresolved objective forced-routing checks.
OBJECTIVE_UNRESOLVED_FORCE_SCORE_MARGIN=90
# Optional: batch-5.6 scaffolding: further reduce unresolved objective forced-routing score margin.
OBJECTIVE_UNRESOLVED_FORCE_SCORE_MARGIN_REDUCTION=20
# Optional: batch-5.6 scaffolding: require unresolved objective forced-routing moves
# to avoid increasing recent transition repeat pressure beyond the configured delta.
OBJECTIVE_UNRESOLVED_FORCE_REQUIRE_REPEAT_IMPROVEMENT=1
OBJECTIVE_UNRESOLVED_FORCE_REPEAT_DELTA_MAX=0
# Optional: verification-priority routing (favor direct branch/corridor verification over speculative guesses).
VERIFICATION_PRIORITY_ENABLE=1
VERIFICATION_PRIORITY_UNKNOWN_THRESHOLD=3
VERIFICATION_PRIORITY_FRONTIER_THRESHOLD=1
VERIFICATION_PRIORITY_MIN_SIGNAL=1.2
VERIFICATION_PRIORITY_SCORE_MARGIN=44
VERIFICATION_PRIORITY_CONTINUITY_BONUS=1.6
# Optional: downscale prediction authority while verification-priority mode is active.
VERIFICATION_PRIORITY_PREDICTION_SCALE=0.3
# Optional: when uncertainty is nearly resolved, force commit to the best unresolved verification branch.
LAST_UNCERTAINTY_COMMIT_ENABLE=1
LAST_UNCERTAINTY_UNKNOWN_THRESHOLD=2
LAST_UNCERTAINTY_FRONTIER_THRESHOLD=1
LAST_UNCERTAINTY_SCORE_MARGIN=64
# Optional: treat visible corridor progress like traversal progress in frontier scoring.
VISION_PROGRESS_CREDIT_ENABLE=1
VISION_PROGRESS_CREDIT_SCALE=1.0
VISION_PROGRESS_CREDIT_MIN_CLEAR_RUN=1
# Optional: longer-lived trap memory penalties for repeated catastrophic transition/cell re-entry.
LONG_TRAP_MEMORY_PENALTY_WEIGHT=18.0
LONG_TRAP_MEMORY_MAX_PENALTY=180
LONG_TRAP_MEMORY_MAX_HITS=8
# Optional: learned hazard preparedness from recent same-origin action outcomes.
HAZARD_PREPAREDNESS_ENABLE=1
HAZARD_PREPAREDNESS_WINDOW=28
HAZARD_PREPAREDNESS_MIN_SAMPLES=2
HAZARD_PREPAREDNESS_RANK_DECAY=0.7
HAZARD_PREPAREDNESS_PENALTY_SCALE=0.16
HAZARD_PREPAREDNESS_MAX_PENALTY=120
HAZARD_PREPAREDNESS_REWARD_RELIEF_SCALE=0.85
HAZARD_PREPAREDNESS_RISK_HIT_WEIGHT=16.0
HAZARD_PREPAREDNESS_SAFE_HIT_WEIGHT=12.0
# Optional: feature vector size used for cause-effect similarity retrieval.
CAUSE_EFFECT_VECTOR_DIM=24
# Optional: top-k similar cause-effect memories retrieved per move scoring.
CAUSE_EFFECT_RETRIEVAL_TOP_K=6
# Optional: minimum cosine similarity gate for cause-effect memory recall.
CAUSE_EFFECT_RETRIEVAL_MIN_SIMILARITY=0.22
# Optional: global weight for applying recalled cause-effect reward/penalty into move score.
CAUSE_EFFECT_MEMORY_WEIGHT=0.4
# Optional: local episodic map authority mode over cross-maze memory (`strict` or `soft`).
LOCAL_MAP_AUTHORITY_MODE=strict
# Optional: in `soft` mode, fraction of episodic lock strength applied to fully known cells (0.0-1.0).
LOCAL_MAP_AUTHORITY_SOFT_SCALE=0.35
# Optional: in `strict` mode, minimum cross-maze memory influence allowed for risky contexts.
STRICT_AUTHORITY_RISK_MEMORY_MIN_SCALE=0.45
# Optional: chance (0.0-1.0) to apply a small biological-style mutation when layout memory is recalled, then reconsolidate that recalled block.
LAYOUT_RECALL_MUTATION_CHANCE=0.03
# Optional: decay depth applied to one recalled cell metadata during reconsolidation mutation.
LAYOUT_RECALL_MUTATION_DECAY_STEPS=18
# Optional: machine-vision side-channel predicts player cell from local perception; kernel grades accuracy only.
MACHINE_VISION_PLAYER_LOCALIZATION_ENABLE=1
MACHINE_VISION_PLAYER_LOCALIZATION_TRAIN_ENABLE=1
# Optional: machine-vision side-channel predicts maze exit cell from local perception; kernel grades accuracy only.
MACHINE_VISION_EXIT_LOCALIZATION_ENABLE=1
MACHINE_VISION_EXIT_LOCALIZATION_TRAIN_ENABLE=1
# Optional: unseen-signature localization tuning (confidence floor + temperature prior sampling + random exploration chance).
MACHINE_VISION_UNSEEN_CONFIDENCE_FLOOR=0.08
MACHINE_VISION_UNSEEN_TEMPERATURE=1.35
MACHINE_VISION_UNSEEN_RANDOM_EXPLORE_CHANCE=0.2
# Optional: feed MV self/exit coordinate hints into kernel scoring as soft, confidence-gated bias.
MACHINE_VISION_KERNEL_HINT_ENABLE=1
MACHINE_VISION_KERNEL_HINT_MIN_CONF=0.05
MACHINE_VISION_KERNEL_EXIT_BIAS_WEIGHT=10.0
# Optional: treat high-confidence fresh MV exit localization as beam-sight-equivalent objective evidence.
MACHINE_VISION_BEAM_EQUIVALENT_MIN_CONF=0.9
MACHINE_VISION_BEAM_EQUIVALENT_MAX_SELF_ERROR=1
# Optional: how tightly MV objective equivalence is anchored to beam visibility.
# `woven` keeps MV coupled to beam by requiring current/recent beam exit visibility before MV
# can act as beam-equivalent objective evidence. `legacy` preserves prior behavior.
MV_BEAM_INTEGRATION_MODE=woven
MV_BEAM_INTEGRATION_RECENT_EXIT_STEPS=64
# Optional: master runtime switch for all machine-vision subsystems (localization, hints, preplan, overlays, MV routing).
MACHINE_VISION_ENABLE=1
# Optional: when enabled, disable MV beam-equivalent objective mode and force
# kernel route-planning from maze start -> exit using MV cellmap predictions.
MV_ROUTE_PLANNING_MODE_ENABLE=0
# Optional: at planning start, take one MV snapshot frame (no per-step MV preplan wait loop).
MV_PREPLAN_SWEEP_ENABLE=1
MV_PREPLAN_REQUIRE_EXIT=1
MV_PREPLAN_SELF_MIN_CONF=0.9
MV_PREPLAN_EXIT_MIN_CONF=0.9
MV_PREPLAN_MAX_SELF_ERROR=1
MV_PREPLAN_ACQUIRE_MAX_SWEEPS=6
# Optional: adaptive neural controller (online learner with growth/prune and persistent weights).
ADAPTIVE_CONTROLLER_ENABLE=1
# Optional: temporarily isolate adaptive learning from MV hint bias during early training.
ADAPTIVE_DISABLE_MV_HINTS=0
ADAPTIVE_SCORE_BLEND=28.0
ADAPTIVE_MAX_SCORE_ADJUST=120
ADAPTIVE_OUTCOME_SCALE=120.0
ADAPTIVE_SAVE_INTERVAL_STEPS=120
ADAPTIVE_HIDDEN_MIN=20
ADAPTIVE_HIDDEN_MAX=128
ADAPTIVE_GROWTH_STEP=4
ADAPTIVE_GROWTH_PATIENCE=120
ADAPTIVE_GROWTH_ERROR_THRESHOLD=0.22
ADAPTIVE_PRUNE_INTERVAL=500
ADAPTIVE_PRUNE_IMPORTANCE_THRESHOLD=0.008
ADAPTIVE_LEARNING_RATE=0.018
ADAPTIVE_L2=0.0008
ADAPTIVE_POLICY_MODE=hybrid
ADAPTIVE_POLICY_MIN_STEPS=120
ADAPTIVE_POLICY_SCORE_MARGIN=40
ADAPTIVE_POLICY_MIN_PRED_GAP=0.05
ADAPTIVE_POLICY_EPSILON=0.06
ADAPTIVE_REPLAY_ENABLE=1
ADAPTIVE_REPLAY_BUFFER_SIZE=6000
ADAPTIVE_REPLAY_BATCH=6
ADAPTIVE_REPLAY_UPDATES=2
# Optional: periodic GPT telemetry for adaptive weights + kernel progress.
ADAPTIVE_PROGRESS_REPORT_ENABLE=1
ADAPTIVE_PROGRESS_REPORT_MODEL=gpt-4.1-mini
ADAPTIVE_PROGRESS_REPORT_INTERVAL_STEPS=180
ADAPTIVE_PROGRESS_AUTO_TUNE=1
ADAPTIVE_PROGRESS_REPORT_MAX_NOTES_CHARS=260
# Optional: blend weight for cross-maze priors when predicting unseen cells (0..1).
PREDICTION_PRIOR_BLEND=0.35
# Optional: score reward when an unseen-structure prediction is correct.
PREDICTION_REWARD_CORRECT=4.0
# Optional: score reward when prediction is wrong but yields new information.
PREDICTION_WRONG_LEARNING_REWARD=0.8
# Optional: fraction of wrong-prediction learning credit kept before explicit penalties are applied.
PREDICTION_WRONG_LEARNING_CREDIT_SCALE=0.15
PREDICTION_WRONG_OCCUPANCY_PENALTY=2.4
PREDICTION_WRONG_SHAPE_PENALTY=1.6
# Optional: additional penalty when a high-confidence prediction is wrong.
PREDICTION_CONFIDENT_WRONG_PENALTY=2.2
# Optional: confidence threshold treated as "high confidence" for wrong-prediction penalty.
PREDICTION_CONFIDENT_THRESHOLD=0.72
# Optional: number of confidence buckets used for prediction calibration summaries.
PREDICTION_CONFIDENCE_BUCKETS=5
# Optional: blend factor for context-specific historical calibration when computing prediction confidence.
PREDICTION_CONTEXT_CONFIDENCE_BLEND=0.45
# Optional: weight applied to occupancy-channel Brier-derived prediction score.
PREDICTION_OCCUPANCY_SCORE_WEIGHT=1.0
# Optional: weight applied to shape-channel Brier-derived prediction score.
PREDICTION_SHAPE_SCORE_WEIGHT=0.85
# Optional: score bonus applied when moving into an unknown cell predicted to be a junction.
PREDICTION_JUNCTION_BIAS_WEIGHT=14.0
# Optional: score penalty applied when moving into an unknown cell predicted to be a dead-end.
PREDICTION_DEAD_END_BIAS_WEIGHT=12.0
# Optional: minimum prediction confidence required before prediction-to-planning bias can apply.
PREDICTION_PLANNING_MIN_CONF=0.08
# Optional: context shape-accuracy cutoffs used to compute context trust (<=low => no trust, >=high => full trust).
PREDICTION_CONTEXT_TRUST_LOW_SHAPE_ACC=0.10
PREDICTION_CONTEXT_TRUST_HIGH_SHAPE_ACC=0.60
# Optional: require sufficient observability before shape outcomes are scored/calibrated.
PREDICTION_SHAPE_REQUIRE_OBSERVABILITY=1
# Optional: minimum known-neighbor evidence needed for shape scoring when observability gating is enabled.
PREDICTION_SHAPE_OBSERVABILITY_MIN_NEIGHBORS=3
# Optional: enable lightweight prediction-informed 2-step lookahead bonus in move scoring.
PREDICTION_LOOKAHEAD_ENABLE=1
# Optional: rollout discount and global weight for prediction lookahead bonus.
PREDICTION_LOOKAHEAD_DISCOUNT=0.4
PREDICTION_LOOKAHEAD_WEIGHT=1.0
# Optional: standalone projection overlay module (not core kernel). Adds forward
# imagined trace reward plus backward trail replay suppression/escape bias.
MAZE_PROJECTION_MODULE_ENABLE=1
MAZE_PROJECTION_FORWARD_DEPTH=3
MAZE_PROJECTION_FORWARD_WEIGHT=1.0
MAZE_PROJECTION_BACKTRACE_WINDOW=14
MAZE_PROJECTION_BACKTRACE_PENALTY_WEIGHT=1.0
MAZE_PROJECTION_BACKTRACE_ESCAPE_WEIGHT=1.0
# Optional: cap absolute projection contribution to per-move score so projection remains a bounded heuristic tool.
MAZE_PROJECTION_SCORE_INFLUENCE_CAP=24
# Optional: scales projection contribution before cap/clamp in planner move scoring.
MAZE_PROJECTION_SCORE_INFLUENCE_SCALE=1.25
# Optional: adaptive projection trust gate (non-punitive): scales projection influence
# from observed utility instead of applying hard penalties when projection underperforms.
PROJECTION_TRUST_ADAPT_ENABLE=1
PROJECTION_TRUST_EMA_DECAY=0.97
PROJECTION_TRUST_MIN_SCALE=0.25
PROJECTION_TRUST_MAX_SCALE=1.0
PROJECTION_TRUST_WARMUP_STEPS=64
# Optional: small intrinsic reward for projection-guided planning quality
# (applied in kernel action-outcome feedback when projection signal is net-positive).
KERNEL_PROJECTION_REWARD_ENABLE=1
KERNEL_PROJECTION_REWARD_SCALE=0.08
KERNEL_PROJECTION_REWARD_MAX=3.0
```

## 3) Launch desktop app

```bash
source .venv/bin/activate
python app.py
```

set 1: medium
set 2: hard
set 3: very hard
set 4: hard

solve 10 mazes; solve 15 mazes x2; solve 15 mazes x2; solve 15 mazes

Tuning and consolidation phase plan:
- See `phase_plans/TUNING_AND_CONSOLIDATION_PHASE_MICRO_PLAN.md` for the current stabilization phases, micro cadence, gates, and rollback rules.


This opens a dedicated app window.

UI quality-of-life:
- Window size and position are persisted between launches.
- Kernel phase-program progression state (active micro/phase, EMA metrics, and completed status) is persisted between launches.
- Use `Copy Output` to copy prompt + response + pipeline debug to clipboard.

Ambiguity tuning:
- The logic model infers repeat intent via `is_repeat_goal` and sets `execution_count`.
- Repeated navigation goals complete when score progress reaches the required target-hit count.
- Proximity metrics are refreshed into context immediately after each respawn.
- Use `LOGIC_CONFIDENCE_THRESHOLD` to make ambiguity fallback more or less aggressive.
- Use `REPEAT_CONFIDENCE_THRESHOLD` to control when repeat inference override is applied.

Game controls:
- Click the game area to focus it.
- Use Arrow keys or `W/A/S/D` to move the square.
- Use `Mode` to switch between `grid` and `maze` training games.
- In maze mode, use `Difficulty` (`easy`/`medium`/`hard`/`very hard`) for predictable algorithmic layouts.
- For MV localization training progression, prefer `hard` first, then graduate to `very hard` after stability/accuracy improves.
- Use `MV Enable` to turn machine vision on/off at runtime (disables MV localization/hints/preplan/overlays/routing when off, and clears MV Route Mode).
- Use `Fast Mode` to temporarily speed up run throughput (lower move/look delays and reduced telemetry/auto-maintenance overhead) and toggle back to restore normal timing/maintenance behavior.
- Use `Long-Run Mode` to reduce long-session overhead by slowing non-kernel maintenance/telemetry/storage cadence while preserving planner/kernel behavior.
- Challenge profile behavior can be configured via `.env` (`CHALLENGE_MODE_*` settings).
- Intra-batch micro progression can be configured via `.env` (`MAZE_BATCH_MICRO_PROGRESSION_*` settings) to gradually tighten challenge within a single run set; optional persistence/quality gates (`MAZE_MICRO_PROGRESSION_PERSIST_*`) can require stricter whole-batch quality before promotion, and regression controls (`MAZE_MICRO_PROGRESSION_REGRESSION_*`) can step progression down after repeated underperformance (for example `6.0 -> 5.9`).
- Mode and Difficulty switching is app-based and persisted between launches.
- In maze mode, model perception is directional-FOV based (biological-style): wider forward view, no vision behind, and blocker-aware occlusion.
- A dedicated pseudo-3D visualizer now renders a first-person corridor preview beside the grid using the same facing + visibility rules.
- Local/lookup ASCII views no longer add a synthetic `B` border frame; outside-grid is still treated as wall via boundary rules.
- When visible in FOV, the exit is rendered as `E` in ASCII snapshots and look sweeps.
- When visible in FOV, the current episode start cell is rendered as `S` in ASCII snapshots and look sweeps.
- Side openings that are directly observed and strongly verified as empty (or repeatedly revisited with low-information, low-frontier evidence) are marked off (non-predictive, visibility-based) and rendered as persistent orange side-edge markers on the maze canvas (not limited to current beam visibility), so each explored branch side at a junction is tracked independently.
- Repeated trap-loop branches are also marked as persistent red side-edge loop-risk markers; these marks add extra avoidance pressure in move scoring and decay automatically when repeat pressure drops.
- Beam corridor visibility now contributes one-to-one traversal-equivalent progress credit (seeing N cells down a corridor carries the same planning weight as physically walking N cells there).
- Pipeline context includes a full-grid "Directional FOV status" representation of what the agent is currently looking at.
- Pipeline context now also includes `Machine vision sees (grid-sized training snapshot)` and this view is tied directly to the same snapshot source used for MV localization training.
- The maze canvas now shows an on-map FOV visualizer: semi-transparent green cells indicate what the agent is currently looking at.
- In maze mode, target location is not provided to the models in context or mapped-memory snapshots.
- In maze mode, target-derived distance/proximity signals are disabled (no hotter/colder shortcut).
- Maze memory is three-layer:
	- Working memory (volatile): current visible local area (radius-1 visibility snapshot) plus a short retained look-sweep buffer for recent steps.
	- Short-term memory (persistent): novelty-gated pattern entries with logic-assigned names + associated ASCII pattern.
	- Long-term semantic memory (persistent): promoted high-strength short-term patterns.
- Cause-effect memory (persistent) records action-to-outcome traces (for example: move choice -> penalty/reward signals) so the agent can remember what decisions led to punishment vs reward.
- Full map memory snapshots are no longer stored.
- Short-term pruning loop: reinforce recalled entries, decay strengths, prune weak items, promote strong items, and reindex by strength.
- Novelty gate for short-term writes: if a pattern signature is already familiar in recent working-memory exposure, it is pruned from STM insertion.
- Promotion threshold to long-term semantic memory is configurable with `SEMANTIC_PROMOTION_THRESHOLD`.
- Logic step evaluation can reuse named patterns from catalog context or assign short descriptive names to novel sections.
- Maze step policy strongly penalizes revisits/backtracks/known dead areas and biases moves toward frontier-expanding paths.
- Maze step policy is frontier-first: it follows paths toward nearest unexplored frontier and only accepts model moves when they score close to that exploration baseline.
- Exit priority rule: exploration is used until the exit is locally seen/known; once seen, step selection prioritizes shortest-path capture over exploration scoring.
- Pipeline Debug now streams live step-mode updates, including maze exploration score breakdowns per candidate move.
- Step logs also include live memory decisions via `memory_event` (for example: `novel->stm`, `familiar->pruned`, `stm:reinforced`, `semantic:reinforced`, plus prune/promotion counts).
- A Maze Memory Viewer panel in the app shows recent stored maze layouts and metadata.
- Maze difficulty also changes grid size and complexity:
	- `easy`: `8x8`, more loops/openings (simpler navigation)
	- `medium`: `10x10`, tighter corridors with balanced complexity
	- `hard`: `12x12`, tightest corridors, denser dead-ends, and longer corridors
	- `very hard`: `20x20`, lowest loop carving and strongest large-map exploration pressure
	- Safety step margin decreases by difficulty before reset-to-start (`easy` > `medium` > `hard` > `very hard`).
- Loop/opening carving has been tightened across all difficulties to reduce overly open mazes and encourage stronger corridor structure.
- Maze generation algorithms are now difficulty-mapped:
	- `easy` (`8x8`): Prim/Kruskal variant (more branching texture, generally easier readability)
	- `medium` (`10x10`): DFS/backtracker (longer corridors and more dead-end pressure)
	- `hard` (`12x12`): alternates Recursive Division and Aldous-Broder style generation for tougher large-grid structure
	- `very hard` (`20x20`): strongly biases Aldous-Broder with occasional Recursive Division for maximal long-walk search load
- Gray blocker tiles are impassable.
- Start and end points are marked on-canvas (`S` for start, `E` at the target).
- Touch the blue ball to score; it respawns at a random location and generates a new blocker map.
- On each capture, the player also respawns to a random start cell.
- Target spawn always guarantees a traversable path from the player's current start cell.
- Target spawn is distance-conditioned to reduce lucky near exits; it selects from a min/max band of shortest-path distance relative to the farthest reachable spawn (default `75%` to `100%`), with fallback to farthest reachable when needed.
- In maze mode, if `MAZE_STEP_LIMIT_RESET_ENABLE=1` and step count reaches the map limit (`shortest path + safety margin`), the player is returned to start.
- Use `New Layout` to regenerate the current mode layout; in maze mode, `map_id` stays absolute (it does not reset to `0`).
- Use `Next Maze` (maze mode) to advance to the next deterministic maze in seed order.
- Use `Random #` (maze mode) to generate and immediately apply a random 2-6 digit `Start #` value (direct jump to that absolute deterministic `map_id`).
- Use `Refresh Memory` in the Maze Memory Viewer to manually reload recent memory rows.
- Use `Log Dump` in the Maze Memory Viewer to write a full memory export file (working/STM/semantic/structural + memory logs + current pipeline debug) into `Log Dump/`.
- Use `Log Dump Full` in the Maze Memory Viewer when you need an untruncated export for long runs (disables export row/line caps and includes richer full-detail memory sections for that dump).
- Prompt batch modifier: append `xN` to a counted maze-run instruction (for example, `run 15 mazes x6`) to execute N batches of the base run count; each batch auto-applies `Random #` before the run and writes a `Log Dump Full` file after completion.
- Batch sequence sets (prompt separators): split a multi-set run with `,`, `;`, or newlines (for example, `solve 10 mazes; solve 15 mazes x2; solve 15 mazes`).
- Per-set difficulty mapping (assistant instructions): difficulties are applied per sequence set (not per individual maze) and can be specified by index (`set 1: hard`, `set 2: very hard`) or by ordered separator list (`set difficulties: hard; very hard; hard`, or simply `hard; very hard; hard`).
- Plateau extra-hard responder env vars: `MAZE_PLATEAU_EXTRA_HARD_ENABLE`, `MAZE_PLATEAU_EXTRA_HARD_STREAK`, `MAZE_PLATEAU_EXTRA_HARD_RUNS`, `MAZE_PLATEAU_EXTRA_HARD_MAX_TRIGGERS`, `MAZE_PLATEAU_EXTRA_HARD_MIN_BATCH_LOOP`, `MAZE_PLATEAU_EXTRA_HARD_DIFFICULTY` (during batch mode, if kernel phase progression stalls for the configured streak, the runtime injects extra runs at a higher difficulty and then restores the previous difficulty).
- Use `Export Snapshot` in the Maze Memory Viewer to save a portable snapshot zip containing persistent memory (`maze_memory.sqlite3`) and adaptive neural pathways (`adaptive_brain.json`) when available.
- Use `Import Snapshot` to restore memory/neural state from snapshot files (`.zip` or legacy `.json`); you can also select an extracted `snapshot_manifest.json` directly, and the app will load sibling `maze_memory.sqlite3` / `adaptive_brain.json` files when present. Older snapshots are imported in compatibility mode and migrated to the current DB schema automatically.
- Use `Sleep Cycle` in the Maze Memory Viewer to run maintenance (usage-based reinforcement + pruning/compaction of volatile logs and high-churn run tables).
- Archive previous batches in `Log Dump OLD/`; keep active run outputs in `Log Dump/`.
- Log dump filenames are auto-generated as `{maze_count}_{maze|mazes}_{difficulty}_{timestamp}.txt`.
- Run a quick preflight gate on any dump with `python preflight_dump_gate.py "Log Dump/<file>.txt"` (`--strict` fails on warnings; `--profile relaxed` uses looser loop-pressure thresholds).
- Preflight output now includes `behavior_screen` metrics to track learned-vs-hardcoded balance (`learned_only_rate`, `hardcoded_only_rate`, `mixed_rate`) plus `unresolved_objective_override_rate` so unresolved objective-lock overconfidence is surfaced as a warning. Phase 1 telemetry adds `phase1_telemetry_coverage`, `phase1_intervention_utility_win3`, and `phase1_penalty_delta_win3` so intervention utility can be monitored over short windows without changing planner policy. Projection integration adds `projection_screen` metrics (`projection_coverage`, `projection_beneficial_rate`, `projection_clip_rate`, `projection_score_delta_avg`, `projection_score_delta_scaled_avg`) so projection influence quality can be validated directly from dumps.
- Use `Reset Memory` in the Maze Memory Viewer to completely clear persistent memory layers and volatile memory/logs.
- Use `Reset Score` to clear targets reached and reward totals.

## Optional: launch web version

```bash
source .venv/bin/activate
python web_app.py
```

Then open `http://127.0.0.1:5050`.

## Notes

- `.env` and `.env.secret` are ignored by git.
- `organism_control.py` provides an explicit perception -> memory -> endocrine -> policy control architecture with typed data contracts (`GridState`, `Event`, `Signature`, `MemoryState`, `EndocrineState`, `ControlState`) and a `step_agent(...)` pipeline helper.
- Use `.env.secret.example` as a template for secret setup.
- Maze memory is stored locally in `maze_memory.sqlite3`.
- Deterministic layout recall now commits a full map snapshot on each maze capture; when that same `map_id` is revisited, episodic known-map hydration can restore complete open/wall structure immediately.
- Maze-mode exit placement is deterministic per map identity (seed + difficulty + algorithm), so the same deterministic `map_id` resolves to the same exit cell across runs.
- Layout recalls now support biological-style reconsolidation: each recall has a small configurable mutation chance (`LAYOUT_RECALL_MUTATION_CHANCE`), and the recalled block is written back as the latest memory version.
- Reconsolidation mutation is now soft: it decays one recalled cell's recency metadata (`LAYOUT_RECALL_MUTATION_DECAY_STEPS`) instead of removing known open/wall occupancy from the recalled map.
- Machine-vision localization training is available as side-channels (`MACHINE_VISION_PLAYER_LOCALIZATION_ENABLE`, `MACHINE_VISION_PLAYER_LOCALIZATION_TRAIN_ENABLE`, `MACHINE_VISION_EXIT_LOCALIZATION_ENABLE`, `MACHINE_VISION_EXIT_LOCALIZATION_TRAIN_ENABLE`): it predicts player and exit cell coordinates from local perception, the maze memory pipeline logs/grades exact-hit and Manhattan error accuracy, and the board renders yellow-green overlays for both (`MV` for player prediction, `MV-E` for exit prediction). Optional kernel-hint knobs (`MACHINE_VISION_KERNEL_HINT_ENABLE`, `MACHINE_VISION_KERNEL_HINT_MIN_CONF`, `MACHINE_VISION_KERNEL_EXIT_BIAS_WEIGHT`) let MV coordinates act as a soft, source/confidence-gated exploration bias, beam-equivalence knobs (`MACHINE_VISION_BEAM_EQUIVALENT_MIN_CONF`, `MACHINE_VISION_BEAM_EQUIVALENT_MAX_SELF_ERROR`) gate high-confidence MV objective evidence, and beam-integration knobs (`MV_BEAM_INTEGRATION_MODE`, `MV_BEAM_INTEGRATION_RECENT_EXIT_STEPS`) control whether MV equivalence stays beam-anchored (`woven`) or uses legacy behavior. MV preplan knobs (`MV_PREPLAN_SWEEP_ENABLE`, `MV_PREPLAN_REQUIRE_EXIT`, `MV_PREPLAN_SELF_MIN_CONF`, `MV_PREPLAN_EXIT_MIN_CONF`, `MV_PREPLAN_MAX_SELF_ERROR`, `MV_PREPLAN_ACQUIRE_MAX_SWEEPS`) now run one MV snapshot frame at planning start (instead of repeating a per-step wait/sweep loop), and `MACHINE_VISION_ENABLE=0` acts as a master kill-switch for all MV runtime behavior.
- MV route-planning mode toggle (`MV_ROUTE_PLANNING_MODE_ENABLE=1`) disables MV beam-equivalent objective mode and instead has the kernel plan a start-to-exit route directly from MV cellmap predictions (with rejoin behavior if the current cell is off the planned start-route).
- Adaptive neural controller (`ADAPTIVE_CONTROLLER_ENABLE`) adds an online-learning score term over maze decisions, stores persistent weights in `adaptive_brain.json`, can grow/prune hidden units (`ADAPTIVE_HIDDEN_MIN`..`ADAPTIVE_HIDDEN_MAX`, growth/prune knobs), supports policy arbitration modes (`ADAPTIVE_POLICY_MODE=hybrid|adaptive_first`) with warmup/margin gates, uses replay-style updates (`ADAPTIVE_REPLAY_*`), and can temporarily isolate from MV hint bias with `ADAPTIVE_DISABLE_MV_HINTS=1` while bootstrapping transferable behavior.
- STM now supports access-time stale pruning with a small probability (`STM_ACCESS_UNUSED_PRUNE_CHANCE`) so low-use entries can be gradually culled while memory is being accessed.
- Cause-effect memory is also stored in `maze_memory.sqlite3` and shown in the Memory Viewer as `Cause-Effect Memory` entries.
- Cause-effect memory is now integrated as a three-step layer: working (`recent_cause_effect`), short-term (`Cause-Effect STM`), and semantic (`Cause-Effect Semantic`) with lightweight vector similarity retrieval.
- Working memory is intentionally volatile and cleared on graceful shutdown (`WM_DELETE_WINDOW` handler).
- STM/LTM tuning env vars: `STM_REINFORCE_ALPHA`, `STM_DECAY_RATE`, `STM_PRUNE_THRESHOLD`, `SEMANTIC_PROMOTION_THRESHOLD`, `STM_PRUNING_INTERVAL_STEPS`.
- Spawn tuning env vars: `TARGET_DISTANCE_MIN_RATIO`, `TARGET_DISTANCE_MAX_RATIO` (distance band ratios applied against max reachable shortest-path distance).
- Step-limit behavior env vars: `MAZE_STEP_LIMIT_RESET_ENABLE` (`1` default = enforce return-to-start on maze timeout, `0` = disable the timeout reset entirely), `RESET_MAZE_KNOWLEDGE_ON_STEP_LIMIT` (`0` default = keep episodic known map on same-maze timeout retries, `1` = fresh exploration after timeout reset).
- Repeat-goal cap env var: `MAX_REPEAT_EXECUTIONS` (default `25`, controls the maximum requested run/maze count accepted from planner and local prompt parsing).
- Default prompt prefill env var: `DEFAULT_MAZE_RUN_LENGTH` (default `10`; preloads Enter text with `solve X mazes` so repeated maze runs can be launched without typing the command each time).
- Map-doubt loop-recovery env vars: `MAZE_MAP_DOUBT_ENABLE`, `MAZE_MAP_DOUBT_REPEAT_THRESHOLD`, `MAZE_MAP_DOUBT_STALL_THRESHOLD`, `MAZE_MAP_DOUBT_COOLDOWN_STEPS` (when a supposedly fully-mapped maze repeats the same state, objective-only routing is temporarily suppressed so the planner can re-check alternative branches and recover from wrong map assumptions).
- Stuck re-exploration env vars: `MAZE_STUCK_REEXPLORE_ENABLE`, `MAZE_STUCK_REPEAT_THRESHOLD`, `MAZE_STUCK_NO_PROGRESS_THRESHOLD`, `MAZE_STUCK_WINDOW`, `MAZE_STUCK_REEXPLORE_COOLDOWN_STEPS`, `MAZE_STUCK_PREDICTION_CONF_FLOOR`, `MAZE_STUCK_PREDICTION_BIAS_SCALE`, `MAZE_STUCK_TRANSITION_REPEAT_BOOST`, `MAZE_STUCK_TRANSITION_REVERSE_BOOST` (detects local cycling with no progress, temporarily bypasses rigid policy routing, and increases short-term suppression of repeated directed/ping-pong transitions only while stuck cooldown is active).
- Decision variability env var: `DECISION_NOISE_WEIGHT` (higher adds more exploration score jitter per decision).
- Tie-breaking variability env vars: `EXPLORATION_TIE_BAND`, `EXPLORATION_RANDOMIZE_TIES`, `EXPLORATION_TIE_NOISE` (break repeated equal-score path choices and add tiny jitter in near-best ties).
- Cycle suppression env vars: `RECENT_CYCLE_WINDOW`, `CYCLE_TRANSITION_PENALTY_WEIGHT`, `CYCLE_PAIR_PENALTY_WEIGHT`, `CYCLE_GUARD_SCORE_MARGIN` (penalize repeated transition pairs and allow guarded loop-break overrides).
- Additional anti-ping-pong env vars: `IMMEDIATE_BACKTRACK_HARD_PENALTY`, `TRANSITION_PRESSURE_REPEAT_PENALTY_WEIGHT` (raise cost for immediate backtracks and repeated local transition pressure when alternatives exist).
- Structural loop-break env vars: `ESCAPE_BIAS_BONUS`, `FORCED_CORRIDOR_REENTRY_PENALTY`, `TRAP_CAUSE_EFFECT_PENALTY_SCALE`, `CYCLE_TABOO_THRESHOLD`, `CYCLE_TABOO_DURATION_STEPS`, `TERMINAL_CORRIDOR_HARD_VETO_PENALTY`, `HIGH_RISK_FRONTIER_OVERRIDE_BONUS` (shift from additive-only penalties toward taboo/veto and escape-favoring behavior in repeated trap contexts).
- Branch-abandon mode env vars: `BRANCH_TIGHTENING_ABORT_THRESHOLD`, `BRANCH_TIGHTENING_ABORT_PENALTY`, `BRANCH_TIGHTENING_ESCAPE_BONUS`, `BRANCH_RECENT_FRONTIER_WINDOW`, `BRANCH_RECENT_FRONTIER_MAX_DISTANCE` (trigger a mode switch when a corridor is tightening and a recent nearby frontier memory exists, then penalize continued commitment and reward escape branches).
- Biological interpretation env vars: `BIO_NAV_ENABLE`, `BIO_NAV_OPENING_WEIGHT`, `BIO_NAV_DEAD_END_ESCAPE_WEIGHT`, `BIO_NAV_NOVELTY_SCALE`, `BIO_NAV_CORRIDOR_FLOW_WEIGHT`, `BIO_NAV_DEAD_END_PREDICTIVE_PENALTY`, `BIO_NAV_LOOP_RISK_PENALTY` (translate raw local geometry into structural signals: opening evidence, corridor flow, predictive dead-end suppression, and loop-risk modulation).
- Endocrine modulation env vars use biologically-inspired hormone primitives (`H_curiosity`, `H_caution`, `H_persistence`, `H_mv_trust`, `H_boredom`, `H_confidence`) configured via `H_*_DECAY` and `HORMONE_*` weights; legacy `ENDOCRINE_*` / `HORMONE_STRESS|FATIGUE|REWARD_*` knobs remain available as deprecated bridge inputs.
- Objective excitement env vars: `OBJECTIVE_EXCITEMENT_ENABLE`, `OBJECTIVE_EXCITEMENT_DECAY`, `OBJECTIVE_EXCITEMENT_EXIT_BOOST`, `OBJECTIVE_EXCITEMENT_PATH_BOOST`, `OBJECTIVE_EXCITEMENT_MAX`, `OBJECTIVE_EXCITEMENT_SCORE_WEIGHT`, `OBJECTIVE_EXCITEMENT_PROGRESS_WEIGHT`, `OBJECTIVE_EXCITEMENT_CONFIDENCE_BLEND` (adds adaptive soft capture pressure when exit evidence appears, so objective pursuit can ramp quickly without relying on hard objective override forcing).
- Learned-autonomy subphase env vars: `LEARNED_AUTONOMY_SUBPHASE_ENABLE`, `LEARNED_AUTONOMY_WARMUP_STEPS`, `LEARNED_AUTONOMY_EMA_DECAY`, `LEARNED_AUTONOMY_PHASE1_SCORE`, `LEARNED_AUTONOMY_PHASE2_SCORE`, `LEARNED_AUTONOMY_UNRESOLVED_TARGET` (adds a runtime telemetry learner that now drives a formal autonomy lifecycle state machine: `MANUAL`, `ASSISTED`, `CONSTRAINED_AUTONOMY`, `SUPERVISED_AUTONOMY`, `SUSPENDED`; transitions are justification-tagged and can be externally overridden for governance/audit).
- Phase-training scaffold controls are now kernel-owned code defaults in `runtime_kernel/integration/kernel_phase_policy_runtime.py` (no `TRAINING_PHASE_*` env surface).
- Parallel reasoning engine env vars: `PARALLEL_REASONING_ENGINE_ENABLE`, `PARALLEL_REASONING_EMA_DECAY`, `PARALLEL_REASONING_WARMUP_STEPS`, `PARALLEL_REASONING_MIN_CONFIDENCE`, `PARALLEL_REASONING_LOCAL_WEIGHT`, `PARALLEL_REASONING_ADAPTIVE_WEIGHT`, `PARALLEL_REASONING_DELIBERATIVE_WEIGHT`, `PARALLEL_REASONING_DELIB_UNKNOWN_WEIGHT`, `PARALLEL_REASONING_DELIB_FRONTIER_WEIGHT`, `PARALLEL_REASONING_DELIB_LOOKAHEAD_WEIGHT`, `PARALLEL_REASONING_DELIB_LOOP_PENALTY_WEIGHT`, `PARALLEL_REASONING_DELIB_HAZARD_PENALTY_WEIGHT`, `PARALLEL_REASONING_DELIB_CONTRADICTION_PENALTY_WEIGHT`, `PARALLEL_REASONING_PROFILE`, `PARALLEL_REASONING_MAX_BRANCHES`, `PARALLEL_REASONING_MAX_DEPTH`, `PARALLEL_REASONING_TIME_BUDGET_MS`, `PARALLEL_REASONING_TOKEN_BUDGET` (evaluates local/adaptive/deliberative signals in parallel under an explicit reasoning-budget contract; branch pruning is surfaced in telemetry so resource tradeoffs are auditable).
- Governance and contracts: shared controller contracts now define global error taxonomy (`TRANSIENT`, `PERMANENT`, `SAFETY_CRITICAL`, `POLICY_VIOLATION`, `RESOURCE_EXHAUSTION`), structured action-outcome events, autonomy transition events, module capability descriptors, developmental stages (`INFANT_KERNEL`, `JUVENILE_KERNEL`, `MATURE_KERNEL`, `RESEARCH_MODE`), and reasoning profiles (`FAST_APPROX`, `BALANCED`, `DEEP_AUDIT`). The Governance Orchestrator (`GOVERNANCE_ORCHESTRATOR_ENABLE`, `GOVERNANCE_POLICY_VERSION`, `KERNEL_DEVELOPMENT_STAGE`) collects these events into a unified introspection/audit stream.
- Kernel phase runtime policy knobs are now code-owned defaults inside `runtime_kernel/integration/kernel_phase_policy_runtime.py` (no environment-variable surface for train/integrate/control-integrate policy presets).
- Kernel phase progression controls are now code-owned defaults in `runtime_kernel/integration/kernel_phase_policy_runtime.py` (promotion caps, stage rebase, warmup dampener, target adaptation, and deficit guards no longer have a `KERNEL_PHASE_*` env surface).
- Fast-solve treat env vars: `MAZE_FAST_SOLVE_TREAT_ENABLE`, `MAZE_FAST_SOLVE_TREAT_MAX_BONUS`, `MAZE_FAST_SOLVE_TREAT_TARGET_MULTIPLIER`, `MAZE_FAST_SOLVE_TREAT_MIN_TARGET_SECONDS` (tracks wall-clock solve time for each maze episode and grants a metaphorical reward bonus when completion beats a dynamic target time derived from optimal path length and move cadence).
- Adaptive telemetry env vars: `ADAPTIVE_PROGRESS_REPORT_ENABLE`, `ADAPTIVE_PROGRESS_REPORT_MODEL`, `ADAPTIVE_PROGRESS_REPORT_INTERVAL_STEPS`, `ADAPTIVE_PROGRESS_AUTO_TUNE`, `ADAPTIVE_PROGRESS_REPORT_MAX_NOTES_CHARS` (occasionally sends adaptive weight snapshots + kernel progress to a GPT reviewer and can softly auto-tune legacy blend drift over time).
- Organism control env vars: `ORGANISM_CONTROL_ENABLE`, `ORGANISM_RECENT_WINDOW` (routes live maze move arbitration through `step_agent(...)` and `CandidateProjection` with policy switching, explicit `ESCAPE_LOOP` inhibition under loop pressure, and a catastrophic trap veto that removes cycle+terminal+boxed corridor moves from selection when alternatives exist).
- Modular maze-agent env vars: `MAZE_AGENT_ENABLE`, `MAZE_AGENT_CYCLE_TABOO_DURATION`, `MAZE_AGENT_CORRIDOR_ESCAPE_THRESHOLD`, `MAZE_AGENT_ESCAPE_TIMEOUT`, `MAZE_AGENT_ESCAPE_EXIT_PRESSURE`, `MAZE_AGENT_CORRIDOR_OVERUSE_THRESHOLD`, `MAZE_AGENT_NOVELTY_WEIGHT`, `MAZE_AGENT_FRONTIER_WEIGHT`, `MAZE_AGENT_JUNCTION_BONUS`, `MAZE_AGENT_CORRIDOR_OVERUSE_PENALTY`, `MAZE_AGENT_DEAD_END_PENALTY`, `MAZE_AGENT_MOTIF_WEIGHT`, `MAZE_AGENT_LOOP_RISK_WEIGHT`, `MAZE_AGENT_CORRIDOR_FORWARD_BIAS`, `MAZE_AGENT_SIDE_OPEN_BIAS` (enables transition-level cycle vetoes plus corridor/side-wall structural biasing in the modular controller stack).
- Exploration debug now includes `endocrine_event_last` (latest hormone delta event) so tuning can distinguish signature-driven drift vs outcome-driven shifts.
- Memory export bundles (`Log Dump`) now include a `[HORMONE PANEL]` section with hormone state, derived controls, legacy batch status, and adaptive report/autotune summaries, plus a `[KERNEL PHASE POLICY]` JSON section with target/micro-mode/objective signals, module states, active reasoning budget profile, applied mode-policy payload, and latest per-step `metric_debug` payload (base/module/blended metrics + adaptive weights + estimated score/target context).
- Sleep-cycle maintenance env vars: `SLEEP_CYCLE_ENABLE`, `SLEEP_CYCLE_AUTO_INTERVAL_STEPS`, `SLEEP_CYCLE_AUTO_AFTER_MAZE_COMPLETION`, `SLEEP_CYCLE_AUTO_AFTER_RUN_SET`, `SLEEP_CYCLE_AUTO_AFTER_LOG_DUMP`, `SLEEP_CYCLE_HORMONE_PRUNE_ENABLE`, `SLEEP_CYCLE_HORMONE_DECAY_PASSES`, `SLEEP_CYCLE_HORMONE_PULL_STRENGTH`, `SLEEP_CYCLE_HORMONE_EXTREME_THRESHOLD`, `SLEEP_CYCLE_USAGE_BOOST`, `SLEEP_CYCLE_USAGE_RECENT_WINDOW_STEPS`, `SLEEP_CYCLE_MEMORY_EVENT_KEEP`, `SLEEP_CYCLE_ENDOCRINE_EVENT_KEEP`, `SLEEP_CYCLE_ACTION_OUTCOME_KEEP_ROWS`, `SLEEP_CYCLE_PREDICTION_KEEP_ROWS`, `SLEEP_CYCLE_VACUUM_ON_MANUAL`, `SLEEP_CYCLE_VACUUM_ON_AUTO` (adds a manual `Sleep Cycle` UI action and optional auto-maintenance passes to compact volatile logs, reinforce recently used memory traces, prune high-churn run tables during long sessions, and de-saturate hormone state between maze episodes).
- Dead-end slap env vars: `DEAD_END_END_SLAP_PENALTY`, `DEAD_END_TIP_REVISIT_SLAP_PENALTY` (apply strong penalties when exploration commits into dead-end tip/pre-tip corridors, and even stronger penalties for revisits in the same maze episode).
- Terminal-end suppression env vars: `VISIBLE_TERMINAL_END_PENALTY`, `TERMINAL_END_GUARD_MARGIN`, `TERMINAL_OVERRIDE_UNRESOLVED_MARGIN_REDUCTION`, `TERMINAL_OVERRIDE_REQUIRE_REPEAT_IMPROVEMENT_UNRESOLVED`, `TERMINAL_TRUST_ADAPT_ENABLE`, `TERMINAL_TRUST_EMA_DECAY`, `TERMINAL_TRUST_MIN_SCALE`, `TERMINAL_TRUST_MAX_SCALE`, `TERMINAL_TRUST_WARMUP_STEPS`, `TERMINAL_TRUST_HARD_AVOID_MIN_SCALE` (deprioritize branches with a visibly blocked terminal cap unless alternatives are clearly worse, while tightening replacement tolerance and repeat-pressure acceptance when uncertainty is still unresolved; trust gating scales this channel from observed utility and can automatically soften hard filtering).
- Hard terminal avoidance env var: `TERMINAL_END_HARD_AVOID` (`1`=allow trust-gated filtering of visibly terminal dead-end branches when a non-terminal legal move exists; `0`=score-only behavior).
- Boxed-corridor suppression env vars: `BOXED_CORRIDOR_NO_EXIT_PENALTY`, `VISIBLE_EXIT_CORRIDOR_REWARD` (avoid corridors boxed by walls when no exit is visible; strongly prioritize corridors where a visible `E` is seen).
- Replay-memory guard env vars: `MEMORY_RISK_REPLAY_GUARD_ENABLE`, `MEMORY_RISK_REPLAY_GUARD_MIN_REPEAT`, `MEMORY_RISK_REPLAY_GUARD_DECAY_THRESHOLD`, `MEMORY_RISK_REPLAY_GUARD_SCORE_MARGIN`, `MEMORY_RISK_REPLAY_GUARD_MAX_DETOUR` (detects repeated high-penalty move replay at the same origin and swaps to safer alternatives when risk-history reduction is meaningful).
- Frontier override env var: `FRONTIER_OVERRIDE_SCORE_MARGIN` (prevents frontier-first routing from overriding clearly better local anti-loop scores).
- Working-memory look-retention env vars: `WORKING_MEMORY_LOOK_RETENTION_STEPS`, `WORKING_MEMORY_LOOK_RETENTION_LIMIT` (keep recent look sweeps in active context for short-term object permanence).
- Reset-aware exploration env vars: `RESET_TRACE_WINDOW`, `POST_RESET_EXHAUSTION_PENALTY`, `RESET_FAILURE_TRANSITION_PENALTY`, `RESET_FAILURE_CELL_PENALTY`, `RESET_SUCCESS_TRANSITION_BONUS`, `POST_RESET_STM_RELAX_STEPS` (after step-limit resets, retain a failure trace window, temporarily suppress revisiting exhausted regions/transitions that repeatedly led to timeout loops, and allow successful post-reset transitions to receive a small recovery bonus; STM novelty gate is briefly relaxed so more post-reset context can be retained).
- Frontier continuity: the maze planner now keeps a persistent frontier target within the same maze episode and tries to resume that route after timeout resets instead of immediately recomputing from purely local scores.
- Same-maze retry continuity: timeout retries now keep an explicit retry counter and preserve the frontier target even during stuck-reexplore fallback, so the planner does not drop back to purely local score replay after a reset.
- Frontier-lock env vars: `FRONTIER_LOCK_UNKNOWN_THRESHOLD`, `FRONTIER_LOCK_FRONTIER_THRESHOLD`, `FRONTIER_LOCK_RETRY_BONUS`, `FRONTIER_LOCK_LOOP_PENALTY`, `SOLVED_REGION_PENALTY`, `LOOP_ENTROPY_WINDOW`, `LOOP_ENTROPY_THRESHOLD`, `FRONTIER_LOCK_MEMORY_VETO_ENABLE`, `FRONTIER_LOCK_MEMORY_VETO_PENALTY`, `FRONTIER_LOCK_MEMORY_VETO_MARGIN`, `FRONTIER_LOCK_MEMORY_VETO_WINDOW`, `FRONTIER_LOCK_MEMORY_VETO_SCORE_MARGIN`, `FRONTIER_LOCK_FORCE_SCORE_GUARD_ENABLE`, `FRONTIER_LOCK_FORCE_SCORE_MARGIN`, `OBJECTIVE_UNRESOLVED_FORCE_SCORE_MARGIN`, `OBJECTIVE_UNRESOLVED_FORCE_SCORE_MARGIN_REDUCTION`, `OBJECTIVE_UNRESOLVED_FORCE_REQUIRE_REPEAT_IMPROVEMENT`, `OBJECTIVE_UNRESOLVED_FORCE_REPEAT_DELTA_MAX` (when the maze is down to a small unresolved frontier pocket, or retries/low-entropy motion indicate corridor replay, the planner enters a hard frontier-lock mode that routes toward the persistent frontier target, suppresses local stuck fallback/model arbitration, and heavily penalizes staying inside already solved regions; the memory-veto knobs let severe recent punishment traces override forced transition replay, while unresolved objective routing can now be further attenuated and guarded by repeat-pressure non-regression to keep behavior in scaffolding mode rather than hard forcing).
- Verification-priority env vars: `VERIFICATION_PRIORITY_ENABLE`, `VERIFICATION_PRIORITY_UNKNOWN_THRESHOLD`, `VERIFICATION_PRIORITY_FRONTIER_THRESHOLD`, `VERIFICATION_PRIORITY_MIN_SIGNAL`, `VERIFICATION_PRIORITY_SCORE_MARGIN`, `VERIFICATION_PRIORITY_CONTINUITY_BONUS`, `VERIFICATION_PRIORITY_PREDICTION_SCALE`, `LAST_UNCERTAINTY_COMMIT_ENABLE`, `LAST_UNCERTAINTY_UNKNOWN_THRESHOLD`, `LAST_UNCERTAINTY_FRONTIER_THRESHOLD`, `LAST_UNCERTAINTY_SCORE_MARGIN` (when unresolved uncertainty remains, planner prioritizes direct hallway/branch verification; and when only a tiny unresolved set remains, it commits to the best unresolved branch instead of re-looping solved corridors).
- Corridor vision-equivalence env vars: `VISION_PROGRESS_CREDIT_ENABLE`, `VISION_PROGRESS_CREDIT_SCALE`, `VISION_PROGRESS_CREDIT_MIN_CLEAR_RUN` (visible corridor depth contributes traversal-equivalent progress via effective frontier distance, so seeing a corridor end is weighted similarly to physically walking those cells).
- Long trap-memory env vars: `LONG_TRAP_MEMORY_PENALTY_WEIGHT`, `LONG_TRAP_MEMORY_MAX_PENALTY`, `LONG_TRAP_MEMORY_MAX_HITS` (catastrophic trap transitions/cells are remembered longer within the maze episode so repeated loop edges accrue stronger suppression over time).
- Hazard preparedness env vars: `HAZARD_PREPAREDNESS_ENABLE`, `HAZARD_PREPAREDNESS_WINDOW`, `HAZARD_PREPAREDNESS_MIN_SAMPLES`, `HAZARD_PREPAREDNESS_RANK_DECAY`, `HAZARD_PREPAREDNESS_PENALTY_SCALE`, `HAZARD_PREPAREDNESS_MAX_PENALTY`, `HAZARD_PREPAREDNESS_REWARD_RELIEF_SCALE`, `HAZARD_PREPAREDNESS_RISK_HIT_WEIGHT`, `HAZARD_PREPAREDNESS_SAFE_HIT_WEIGHT` (builds a learned same-origin risk profile from recent action outcomes and applies a soft relative hazard penalty, so branch selection drifts away from repeatedly catastrophic moves without hardcoded move forcing).
- Exploration debug now includes `active_retries`, `frontier_lock`, and `move_entropy`, plus per-move `frontier_lock_progress_bonus`, `frontier_lock_loop_penalty`, and `solved_region_penalty`, so late-maze loop behavior can be validated directly from the debug dump.
- Exploration debug now also reports `hazard_preparedness_penalty`, `hazard_preparedness_relative_pressure`, `hazard_preparedness_confidence`, and `hazard_preparedness_samples` per move for direct learned-vs-hardcoded validation.
- Local map authority env vars: `LOCAL_MAP_AUTHORITY_MODE`, `LOCAL_MAP_AUTHORITY_SOFT_SCALE`, `STRICT_AUTHORITY_RISK_MEMORY_MIN_SCALE` (`strict`=local episodic truth fully overrides cross-maze reward carryover on fully known cells except a configurable minimum carryover for high-risk contexts; `soft`=apply partial override using the soft scale).
- Local navigation env vars: `LOCAL_NAVIGATION_KERNEL`, `LOCAL_NAVIGATION_API_FALLBACK` (`LOCAL_NAVIGATION_KERNEL=1` makes navigation local-first, and `LOCAL_NAVIGATION_API_FALLBACK=1` lets OpenAI step in if the local kernel stalls or cannot finish cleanly).
- Low-reliance routing env vars: `ENABLE_LOGIC_REPETITION_RESOLVER`, `ENABLE_LOGIC_FINALIZER_FOR_NAVIGATION`, `MAZE_STEP_MODEL_HINTS`, `MAZE_TARGETED_MODEL_ASSIST_ENABLE`, `MAZE_MODEL_ASSIST_RELIANCE`, `MAZE_MODEL_ASSIST_MAX_CALLS_PER_EPISODE`, `MAZE_MODEL_ASSIST_COOLDOWN_STEPS` (keep normal navigation local-first, optionally allow full per-step hints, or add targeted OpenAI arbitration only during contradiction/stuck/map-doubt states; `MAZE_MODEL_ASSIST_RELIANCE` scales how eagerly those targeted calls trigger and how much override margin they get).
- Constructive reinforcement env vars: `CONSTRUCTIVE_REINFORCEMENT_ONLY`, `CONSTRUCTIVE_LEARNING_CREDIT_SCALE`, `CONSTRUCTIVE_LEARNING_CREDIT_CAP`, `CONSTRUCTIVE_STAGNATION_CREDIT` (switches maze step feedback away from penalty-based outcome scoring; non-optimal moves contribute bounded positive learning credit and all outcome traces remain constructive for reinforcement).
- Ouch readiness env vars (inactive by default): `OUCH_RESPONSE_ENABLE`, `OUCH_RESPONSE_TRAIN_ENABLE`, `OUCH_RESPONSE_MIN_PENALTY`, `OUCH_RESPONSE_TAG_BOOST`, `OUCH_RESPONSE_INTENSITY_SCALE`, `OUCH_RESPONSE_BUFFER_SIZE` (adds an aversive-event capture channel and trainer seam without changing policy unless explicitly enabled).
- Prediction-memory env vars: `PREDICTION_PRIOR_BLEND`, `PREDICTION_REWARD_CORRECT`, `PREDICTION_WRONG_LEARNING_REWARD`, `PREDICTION_WRONG_LEARNING_CREDIT_SCALE`, `PREDICTION_WRONG_OCCUPANCY_PENALTY`, `PREDICTION_WRONG_SHAPE_PENALTY`, `PREDICTION_CONFIDENT_WRONG_PENALTY`, `PREDICTION_CONFIDENT_THRESHOLD`, `PREDICTION_CONFIDENCE_BUCKETS`, `PREDICTION_CONTEXT_CONFIDENCE_BLEND`, `PREDICTION_OCCUPANCY_SCORE_WEIGHT`, `PREDICTION_SHAPE_SCORE_WEIGHT` (wrong predictions no longer stay net-positive by default; these knobs control how much informational credit remains versus how strongly wrong occupancy/shape guesses are penalized).
- Prediction-to-planning bias env vars: `PREDICTION_JUNCTION_BIAS_WEIGHT`, `PREDICTION_DEAD_END_BIAS_WEIGHT`, `PREDICTION_PLANNING_MIN_CONF`, `PREDICTION_CONTEXT_TRUST_LOW_SHAPE_ACC`, `PREDICTION_CONTEXT_TRUST_HIGH_SHAPE_ACC` (active shape predictions are context-trust weighted before influencing move scoring; low-trust contexts collapse toward occupancy-only behavior; using `0.08` as baseline enables gentle prediction influence instead of waiting for rare high-confidence spikes).
- Shape observability, lookahead, and projection env vars: `PREDICTION_SHAPE_REQUIRE_OBSERVABILITY`, `PREDICTION_SHAPE_OBSERVABILITY_MIN_NEIGHBORS`, `PREDICTION_LOOKAHEAD_ENABLE`, `PREDICTION_LOOKAHEAD_DISCOUNT`, `PREDICTION_LOOKAHEAD_WEIGHT`, `MAZE_PROJECTION_MODULE_ENABLE`, `MAZE_PROJECTION_FORWARD_DEPTH`, `MAZE_PROJECTION_FORWARD_WEIGHT`, `MAZE_PROJECTION_BACKTRACE_WINDOW`, `MAZE_PROJECTION_BACKTRACE_PENALTY_WEIGHT`, `MAZE_PROJECTION_BACKTRACE_ESCAPE_WEIGHT`, `MAZE_PROJECTION_SCORE_INFLUENCE_CAP`, `MAZE_PROJECTION_SCORE_INFLUENCE_SCALE`, `PROJECTION_TRUST_ADAPT_ENABLE`, `PROJECTION_TRUST_EMA_DECAY`, `PROJECTION_TRUST_MIN_SCALE`, `PROJECTION_TRUST_MAX_SCALE`, `PROJECTION_TRUST_WARMUP_STEPS`, `KERNEL_PROJECTION_REWARD_ENABLE`, `KERNEL_PROJECTION_REWARD_SCALE`, `KERNEL_PROJECTION_REWARD_MAX` (shape calibration updates can be gated until topology is observable; prediction lookahead adds lightweight 2-step rollout signal; projection adds a separate non-core overlay for forward imagined traces and backward trail replay suppression, then contributes as bounded score shaping rather than a hard override path, and can add a small planning feedback reward when projection guidance is net-positive; trust gating further attenuates projection influence dynamically when utility drifts).
- Prediction-memory rows now store prediction status (`pending`, `resolved`, `expired`); unresolved predictions are expired on maze/knowledge reset so they do not pollute calibration metrics.
- Prediction-memory now tracks confidence calibration by bucket and by structural context key (difficulty, boundary bucket, branch profile, dead-end risk, frontier distance bucket), so the kernel can become confident in contexts where it has actually earned that trust.
- With `LOCAL_NAVIGATION_KERNEL=1`, maze and grid navigation requests try the internal kernel first; if `OPENAI_API_KEY` is present and `LOCAL_NAVIGATION_API_FALLBACK=1`, the app can fall back to OpenAI after local progress instead of paying for every navigation step.
- If `OPENAI_API_KEY` is missing, navigation still runs locally; general chat requests still require the external API.
- Cross-maze gating rule: persistent pattern/cause-effect influence is suppressed unless the candidate is locally exploratory (`unknown_neighbors>0`, `frontier_distance>0`, `recent_backtrack==0`, and no episodic known/visited/dead-end constraint for that cell).
- Soft blend behavior: in `soft` mode, local authority uses a continuous confidence blend (Bayesian-style) from local certainty signals (known/visited/dead-end/frontier/backtrack) rather than a hard on/off gate.
- Exploration score debug now includes a branch diversity term (`branch_diversity_penalty`) to discourage over-committing to one branch at junctions.
- Dead-end suppression tuning env vars: `SHALLOW_DEAD_END_PENALTY_BASE`, `DEAD_END_FRONTIER_DISTANCE_SCALE`, `REVISIT_DEAD_END_ENTRANCE_PENALTY`, `NARROW_CORRIDOR_PENALTY`, `EASY_DEAD_END_SCALE`, `MEDIUM_DEAD_END_SCALE`, `HARD_DEAD_END_SCALE`.
- Attempt escalation env var: `ATTEMPT_DEAD_END_ESCALATION` (increases dead-end suppression per timeout attempt within the same maze).
- Personality/learning env vars: `MAZE_PERSONALITY_VARIATION`, `DEAD_END_LEARNING_ALLOWANCE` (forms run-to-run style variation and allows limited dead-end sampling for learning).
- Maze attempt visibility: score/status/debug now report how many attempts were needed to solve the latest maze episode.
- Dead-end entrance memory is retained across timeout retries for the same maze episode and resets when a new maze target/layout is spawned.
- If `OPENAI_API_KEY` is missing, the app shows a setup message in the status area.
- The logic model interprets vague instructions and delegates concrete tasks to the agent model.
