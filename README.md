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
# Optional: contradiction-triggered map-doubt mode to re-enable exploration when fully-mapped routing stalls.
MAZE_MAP_DOUBT_ENABLE=1
MAZE_MAP_DOUBT_REPEAT_THRESHOLD=3
MAZE_MAP_DOUBT_STALL_THRESHOLD=2
MAZE_MAP_DOUBT_COOLDOWN_STEPS=8
# Optional: stuck-loop detector + temporary re-exploration mode when movement repeats without progress.
MAZE_STUCK_REEXPLORE_ENABLE=1
MAZE_STUCK_REPEAT_THRESHOLD=3
MAZE_STUCK_NO_PROGRESS_THRESHOLD=4
MAZE_STUCK_WINDOW=18
MAZE_STUCK_REEXPLORE_COOLDOWN_STEPS=10
# Optional: stuck-mode prediction gate + scaling for low-confidence branch re-checks.
MAZE_STUCK_PREDICTION_CONF_FLOOR=0.08
MAZE_STUCK_PREDICTION_BIAS_SCALE=0.35
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
# Optional: directional FOV max depth (forward reach in cells).
MAZE_FOV_DEPTH=4
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
HORMONE_STRESS_DECAY=0.90
HORMONE_CURIOSITY_DECAY=0.97
HORMONE_CONFIDENCE_DECAY=0.96
HORMONE_FATIGUE_DECAY=0.98
HORMONE_REWARD_DECAY=0.95
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
# Optional: when enabled, never choose a visibly terminal dead-end branch if any non-terminal move is available.
TERMINAL_END_HARD_AVOID=1
# Optional: additive penalty for visibly boxed corridors (walls on both sides) with no visible exit.
BOXED_CORRIDOR_NO_EXIT_PENALTY=36
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
```

## 3) Launch desktop app

```bash
source .venv/bin/activate
python app.py
```

This opens a dedicated app window.

UI quality-of-life:
- Window size and position are persisted between launches.
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
- In maze mode, use `Difficulty` (`easy`/`medium`/`hard`) for predictable algorithmic layouts.
- Mode and Difficulty switching is app-based and persisted between launches.
- In maze mode, model perception is directional-FOV based (biological-style): wider forward view, no vision behind, and blocker-aware occlusion.
- A dedicated pseudo-3D visualizer now renders a first-person corridor preview beside the grid using the same facing + visibility rules.
- Local/lookup ASCII views are now framed with a `B` wall boundary so edge-looking includes explicit wall context.
- When visible in FOV, the exit is rendered as `E` in ASCII snapshots and look sweeps.
- Pipeline context includes a full-grid "Directional FOV status" representation of what the agent is currently looking at.
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
	- Safety step margin decreases by difficulty before reset-to-start (`easy` > `medium` > `hard`).
- Loop/opening carving has been tightened across all difficulties to reduce overly open mazes and encourage stronger corridor structure.
- Maze generation algorithms are now difficulty-mapped:
	- `easy` (`8x8`): Prim/Kruskal variant (more branching texture, generally easier readability)
	- `medium` (`10x10`): DFS/backtracker (longer corridors and more dead-end pressure)
	- `hard` (`12x12`): alternates Recursive Division and Aldous-Broder style generation for tougher large-grid structure
- Gray blocker tiles are impassable.
- Start and end points are marked on-canvas (`S` for start, `E` at the target).
- Touch the blue ball to score; it respawns at a random location and generates a new blocker map.
- On each capture, the player also respawns to a random start cell.
- Target spawn always guarantees a traversable path from the player's current start cell.
- Target spawn is distance-conditioned to reduce lucky near exits; it selects from a min/max band of shortest-path distance relative to the farthest reachable spawn (default `75%` to `100%`), with fallback to farthest reachable when needed.
- In maze mode, if `MAZE_STEP_LIMIT_RESET_ENABLE=1` and step count reaches the map limit (`shortest path + safety margin`), the player is returned to start.
- Use `New Layout` to regenerate the current mode layout; in maze mode, `map_id` stays absolute (it does not reset to `0`).
- Use `Next Maze` (maze mode) to advance to the next deterministic maze in seed order.
- Use `Start #` + `Set Start` (maze mode) to jump directly to a specific absolute deterministic `map_id`.
- Use `Refresh Memory` in the Maze Memory Viewer to manually reload recent memory rows.
- Use `Copy Memory + Logs` in the Maze Memory Viewer to copy the full memory export (working/STM/semantic/structural + memory logs + current pipeline debug) to clipboard.
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
- STM now supports access-time stale pruning with a small probability (`STM_ACCESS_UNUSED_PRUNE_CHANCE`) so low-use entries can be gradually culled while memory is being accessed.
- Cause-effect memory is also stored in `maze_memory.sqlite3` and shown in the Memory Viewer as `Cause-Effect Memory` entries.
- Cause-effect memory is now integrated as a three-step layer: working (`recent_cause_effect`), short-term (`Cause-Effect STM`), and semantic (`Cause-Effect Semantic`) with lightweight vector similarity retrieval.
- Working memory is intentionally volatile and cleared on graceful shutdown (`WM_DELETE_WINDOW` handler).
- STM/LTM tuning env vars: `STM_REINFORCE_ALPHA`, `STM_DECAY_RATE`, `STM_PRUNE_THRESHOLD`, `SEMANTIC_PROMOTION_THRESHOLD`, `STM_PRUNING_INTERVAL_STEPS`.
- Spawn tuning env vars: `TARGET_DISTANCE_MIN_RATIO`, `TARGET_DISTANCE_MAX_RATIO` (distance band ratios applied against max reachable shortest-path distance).
- Step-limit behavior env vars: `MAZE_STEP_LIMIT_RESET_ENABLE` (`1` default = enforce return-to-start on maze timeout, `0` = disable the timeout reset entirely), `RESET_MAZE_KNOWLEDGE_ON_STEP_LIMIT` (`0` default = keep episodic known map on same-maze timeout retries, `1` = fresh exploration after timeout reset).
- Repeat-goal cap env var: `MAX_REPEAT_EXECUTIONS` (default `25`, controls the maximum requested run/maze count accepted from planner and local prompt parsing).
- Map-doubt loop-recovery env vars: `MAZE_MAP_DOUBT_ENABLE`, `MAZE_MAP_DOUBT_REPEAT_THRESHOLD`, `MAZE_MAP_DOUBT_STALL_THRESHOLD`, `MAZE_MAP_DOUBT_COOLDOWN_STEPS` (when a supposedly fully-mapped maze repeats the same state, objective-only routing is temporarily suppressed so the planner can re-check alternative branches and recover from wrong map assumptions).
- Stuck re-exploration env vars: `MAZE_STUCK_REEXPLORE_ENABLE`, `MAZE_STUCK_REPEAT_THRESHOLD`, `MAZE_STUCK_NO_PROGRESS_THRESHOLD`, `MAZE_STUCK_WINDOW`, `MAZE_STUCK_REEXPLORE_COOLDOWN_STEPS`, `MAZE_STUCK_PREDICTION_CONF_FLOOR`, `MAZE_STUCK_PREDICTION_BIAS_SCALE`, `MAZE_STUCK_TRANSITION_REPEAT_BOOST`, `MAZE_STUCK_TRANSITION_REVERSE_BOOST` (detects local cycling with no progress, temporarily bypasses rigid policy routing, and increases short-term suppression of repeated directed/ping-pong transitions only while stuck cooldown is active).
- Decision variability env var: `DECISION_NOISE_WEIGHT` (higher adds more exploration score jitter per decision).
- Tie-breaking variability env vars: `EXPLORATION_TIE_BAND`, `EXPLORATION_RANDOMIZE_TIES`, `EXPLORATION_TIE_NOISE` (break repeated equal-score path choices and add tiny jitter in near-best ties).
- Cycle suppression env vars: `RECENT_CYCLE_WINDOW`, `CYCLE_TRANSITION_PENALTY_WEIGHT`, `CYCLE_PAIR_PENALTY_WEIGHT`, `CYCLE_GUARD_SCORE_MARGIN` (penalize repeated transition pairs and allow guarded loop-break overrides).
- Additional anti-ping-pong env vars: `IMMEDIATE_BACKTRACK_HARD_PENALTY`, `TRANSITION_PRESSURE_REPEAT_PENALTY_WEIGHT` (raise cost for immediate backtracks and repeated local transition pressure when alternatives exist).
- Structural loop-break env vars: `ESCAPE_BIAS_BONUS`, `FORCED_CORRIDOR_REENTRY_PENALTY`, `TRAP_CAUSE_EFFECT_PENALTY_SCALE`, `CYCLE_TABOO_THRESHOLD`, `CYCLE_TABOO_DURATION_STEPS`, `TERMINAL_CORRIDOR_HARD_VETO_PENALTY`, `HIGH_RISK_FRONTIER_OVERRIDE_BONUS` (shift from additive-only penalties toward taboo/veto and escape-favoring behavior in repeated trap contexts).
- Branch-abandon mode env vars: `BRANCH_TIGHTENING_ABORT_THRESHOLD`, `BRANCH_TIGHTENING_ABORT_PENALTY`, `BRANCH_TIGHTENING_ESCAPE_BONUS`, `BRANCH_RECENT_FRONTIER_WINDOW`, `BRANCH_RECENT_FRONTIER_MAX_DISTANCE` (trigger a mode switch when a corridor is tightening and a recent nearby frontier memory exists, then penalize continued commitment and reward escape branches).
- Biological interpretation env vars: `BIO_NAV_ENABLE`, `BIO_NAV_OPENING_WEIGHT`, `BIO_NAV_DEAD_END_ESCAPE_WEIGHT`, `BIO_NAV_NOVELTY_SCALE`, `BIO_NAV_CORRIDOR_FLOW_WEIGHT`, `BIO_NAV_DEAD_END_PREDICTIVE_PENALTY`, `BIO_NAV_LOOP_RISK_PENALTY` (translate raw local geometry into structural signals: opening evidence, corridor flow, predictive dead-end suppression, and loop-risk modulation).
- Endocrine modulation env vars: `ENDOCRINE_ENABLE`, `HORMONE_STRESS_DECAY`, `HORMONE_CURIOSITY_DECAY`, `HORMONE_CONFIDENCE_DECAY`, `HORMONE_FATIGUE_DECAY`, `HORMONE_REWARD_DECAY`, `ENDOCRINE_STRESS_DANGER_WEIGHT`, `ENDOCRINE_CURIOSITY_NOVELTY_WEIGHT`, `ENDOCRINE_FATIGUE_REPEAT_WEIGHT`, `ENDOCRINE_CONFIDENCE_RISK_BONUS`, `ENDOCRINE_MOMENTUM_BONUS_WEIGHT` (stateful hormone/neural-state regulation that modulates loop aversion, novelty drive, risk tolerance, and momentum).
- Organism control env vars: `ORGANISM_CONTROL_ENABLE`, `ORGANISM_RECENT_WINDOW` (routes live maze move arbitration through `step_agent(...)` and `CandidateProjection` with policy switching, explicit `ESCAPE_LOOP` inhibition under loop pressure, and a catastrophic trap veto that removes cycle+terminal+boxed corridor moves from selection when alternatives exist).
- Modular maze-agent env vars: `MAZE_AGENT_ENABLE`, `MAZE_AGENT_CYCLE_TABOO_DURATION`, `MAZE_AGENT_CORRIDOR_ESCAPE_THRESHOLD`, `MAZE_AGENT_ESCAPE_TIMEOUT`, `MAZE_AGENT_ESCAPE_EXIT_PRESSURE`, `MAZE_AGENT_CORRIDOR_OVERUSE_THRESHOLD`, `MAZE_AGENT_NOVELTY_WEIGHT`, `MAZE_AGENT_FRONTIER_WEIGHT`, `MAZE_AGENT_JUNCTION_BONUS`, `MAZE_AGENT_CORRIDOR_OVERUSE_PENALTY`, `MAZE_AGENT_DEAD_END_PENALTY`, `MAZE_AGENT_MOTIF_WEIGHT`, `MAZE_AGENT_LOOP_RISK_WEIGHT`, `MAZE_AGENT_CORRIDOR_FORWARD_BIAS`, `MAZE_AGENT_SIDE_OPEN_BIAS` (enables transition-level cycle vetoes plus corridor/side-wall structural biasing in the modular controller stack).
- Exploration debug now includes `endocrine_event_last` (latest hormone delta event) so tuning can distinguish signature-driven drift vs outcome-driven shifts.
- Dead-end slap env vars: `DEAD_END_END_SLAP_PENALTY`, `DEAD_END_TIP_REVISIT_SLAP_PENALTY` (apply strong penalties when exploration commits into dead-end tip/pre-tip corridors, and even stronger penalties for revisits in the same maze episode).
- Terminal-end suppression env vars: `VISIBLE_TERMINAL_END_PENALTY`, `TERMINAL_END_GUARD_MARGIN` (deprioritize branches with a visibly blocked terminal cap unless alternatives are clearly worse).
- Hard terminal avoidance env var: `TERMINAL_END_HARD_AVOID` (`1`=filter out visibly terminal dead-end branches whenever a non-terminal legal move exists; `0`=score-only behavior).
- Boxed-corridor suppression env vars: `BOXED_CORRIDOR_NO_EXIT_PENALTY`, `VISIBLE_EXIT_CORRIDOR_REWARD` (avoid corridors boxed by walls when no exit is visible; strongly prioritize corridors where a visible `E` is seen).
- Frontier override env var: `FRONTIER_OVERRIDE_SCORE_MARGIN` (prevents frontier-first routing from overriding clearly better local anti-loop scores).
- Working-memory look-retention env vars: `WORKING_MEMORY_LOOK_RETENTION_STEPS`, `WORKING_MEMORY_LOOK_RETENTION_LIMIT` (keep recent look sweeps in active context for short-term object permanence).
- Reset-aware exploration env vars: `RESET_TRACE_WINDOW`, `POST_RESET_EXHAUSTION_PENALTY`, `RESET_FAILURE_TRANSITION_PENALTY`, `RESET_FAILURE_CELL_PENALTY`, `RESET_SUCCESS_TRANSITION_BONUS`, `POST_RESET_STM_RELAX_STEPS` (after step-limit resets, retain a failure trace window, temporarily suppress revisiting exhausted regions/transitions that repeatedly led to timeout loops, and allow successful post-reset transitions to receive a small recovery bonus; STM novelty gate is briefly relaxed so more post-reset context can be retained).
- Frontier continuity: the maze planner now keeps a persistent frontier target within the same maze episode and tries to resume that route after timeout resets instead of immediately recomputing from purely local scores.
- Same-maze retry continuity: timeout retries now keep an explicit retry counter and preserve the frontier target even during stuck-reexplore fallback, so the planner does not drop back to purely local score replay after a reset.
- Frontier-lock env vars: `FRONTIER_LOCK_UNKNOWN_THRESHOLD`, `FRONTIER_LOCK_FRONTIER_THRESHOLD`, `FRONTIER_LOCK_RETRY_BONUS`, `FRONTIER_LOCK_LOOP_PENALTY`, `SOLVED_REGION_PENALTY`, `LOOP_ENTROPY_WINDOW`, `LOOP_ENTROPY_THRESHOLD` (when the maze is down to a small unresolved frontier pocket, or retries/low-entropy motion indicate corridor replay, the planner enters a hard frontier-lock mode that routes toward the persistent frontier target, suppresses local stuck fallback/model arbitration, and heavily penalizes staying inside already solved regions).
- Exploration debug now includes `active_retries`, `frontier_lock`, and `move_entropy`, plus per-move `frontier_lock_progress_bonus`, `frontier_lock_loop_penalty`, and `solved_region_penalty`, so late-maze loop behavior can be validated directly from the debug dump.
- Local map authority env vars: `LOCAL_MAP_AUTHORITY_MODE`, `LOCAL_MAP_AUTHORITY_SOFT_SCALE`, `STRICT_AUTHORITY_RISK_MEMORY_MIN_SCALE` (`strict`=local episodic truth fully overrides cross-maze reward carryover on fully known cells except a configurable minimum carryover for high-risk contexts; `soft`=apply partial override using the soft scale).
- Local navigation env vars: `LOCAL_NAVIGATION_KERNEL`, `LOCAL_NAVIGATION_API_FALLBACK` (`LOCAL_NAVIGATION_KERNEL=1` makes navigation local-first, and `LOCAL_NAVIGATION_API_FALLBACK=1` lets OpenAI step in if the local kernel stalls or cannot finish cleanly).
- Low-reliance routing env vars: `ENABLE_LOGIC_REPETITION_RESOLVER`, `ENABLE_LOGIC_FINALIZER_FOR_NAVIGATION`, `MAZE_STEP_MODEL_HINTS`, `MAZE_TARGETED_MODEL_ASSIST_ENABLE`, `MAZE_MODEL_ASSIST_RELIANCE`, `MAZE_MODEL_ASSIST_MAX_CALLS_PER_EPISODE`, `MAZE_MODEL_ASSIST_COOLDOWN_STEPS` (keep normal navigation local-first, optionally allow full per-step hints, or add targeted OpenAI arbitration only during contradiction/stuck/map-doubt states; `MAZE_MODEL_ASSIST_RELIANCE` scales how eagerly those targeted calls trigger and how much override margin they get).
- Prediction-memory env vars: `PREDICTION_PRIOR_BLEND`, `PREDICTION_REWARD_CORRECT`, `PREDICTION_WRONG_LEARNING_REWARD`, `PREDICTION_WRONG_LEARNING_CREDIT_SCALE`, `PREDICTION_WRONG_OCCUPANCY_PENALTY`, `PREDICTION_WRONG_SHAPE_PENALTY`, `PREDICTION_CONFIDENT_WRONG_PENALTY`, `PREDICTION_CONFIDENT_THRESHOLD`, `PREDICTION_CONFIDENCE_BUCKETS`, `PREDICTION_CONTEXT_CONFIDENCE_BLEND`, `PREDICTION_OCCUPANCY_SCORE_WEIGHT`, `PREDICTION_SHAPE_SCORE_WEIGHT` (wrong predictions no longer stay net-positive by default; these knobs control how much informational credit remains versus how strongly wrong occupancy/shape guesses are penalized).
- Prediction-to-planning bias env vars: `PREDICTION_JUNCTION_BIAS_WEIGHT`, `PREDICTION_DEAD_END_BIAS_WEIGHT`, `PREDICTION_PLANNING_MIN_CONF`, `PREDICTION_CONTEXT_TRUST_LOW_SHAPE_ACC`, `PREDICTION_CONTEXT_TRUST_HIGH_SHAPE_ACC` (active shape predictions are context-trust weighted before influencing move scoring; low-trust contexts collapse toward occupancy-only behavior; using `0.08` as baseline enables gentle prediction influence instead of waiting for rare high-confidence spikes).
- Shape observability and lookahead env vars: `PREDICTION_SHAPE_REQUIRE_OBSERVABILITY`, `PREDICTION_SHAPE_OBSERVABILITY_MIN_NEIGHBORS`, `PREDICTION_LOOKAHEAD_ENABLE`, `PREDICTION_LOOKAHEAD_DISCOUNT`, `PREDICTION_LOOKAHEAD_WEIGHT` (shape calibration updates can be gated until topology is observable; optional lightweight 2-step prediction rollout adds a small frontier/junction-aware planning bonus).
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
