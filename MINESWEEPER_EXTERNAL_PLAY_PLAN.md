# External Minesweeper Play Plan

## Objective
Enable the existing kernel to play a real external Minesweeper client through only user-approved controls.

## Non-Goals
- Do not build a Minesweeper game into this app.
- Do not read process memory or use hidden game state.
- Do not bypass UI constraints with direct board access unless explicitly approved.

## Core Constraint
The agent must behave like a constrained operator:
1. Observe what is visible through allowed perception channels.
2. Decide using kernel policy and uncertainty handling.
3. Act only through approved input controls.
4. Log decisions and actions for auditability.

## Approved Control Surface (Draft)
Define this first and freeze it before implementation.

### Observation Channels
- Screen capture of a bounded game window region.
- Optional template matching or classifier inference for tile states.
- Optional OCR only if the selected client displays textual counters needed for control.

### Action Channels
- Mouse move to target cell center.
- Left click (reveal).
- Right click (flag/unflag).
- Optional chord click if the client supports it and you allow it.

### Safety and Governance Controls
- Global pause hotkey.
- Emergency stop hotkey.
- Max actions per second.
- Allowed window title/process whitelist.
- Deny action if foreground window is not the approved game window.

### Forbidden by Default
- Process memory inspection.
- Window message injection that bypasses normal input path.
- Direct board parsing from DOM/internal API unless explicitly approved.

## System Architecture

### 1) Client Adapter Layer
Responsibilities:
- Locate and track the approved game window.
- Maintain capture bounds and coordinate transforms.
- Validate focus and input safety before each action.

Outputs:
- Stable screenshot frames.
- Clickable cell coordinate map.

### 2) Perception Layer
Responsibilities:
- Classify each tile into: unknown, revealed-number, blank, flag, exploded, mine (if shown).
- Detect board reset/win/loss states.
- Track perception confidence per cell.

Outputs:
- Board belief state.
- Confidence map.

### 3) State Builder (Kernel Bridge)
Responsibilities:
- Convert board belief into kernel-friendly state features.
- Expose uncertainty explicitly.
- Preserve episode memory between moves.

Outputs:
- Step state object for policy evaluation.

### 4) Policy Layer
Responsibilities:
- Use deterministic Minesweeper logic where certainty exists.
- Use kernel uncertainty policy for guess decisions.
- Rank candidate actions by risk, expected information gain, and survival probability.

Outputs:
- Action proposal plus confidence and rationale.

### 5) Action Executor
Responsibilities:
- Rate-limit and execute approved clicks.
- Verify post-action frame change.
- Retry or abort on misalignment/focus drift.

Outputs:
- Action outcome event stream.

### 6) Telemetry and Audit
Responsibilities:
- Record frame hash, chosen action, confidence, and outcome.
- Tag manual override or forced stop events.
- Export run summaries for gate checks.

Outputs:
- Reproducible run logs.

## Minimal Contracts

### Action Contract
- action_type: reveal | flag | chord | noop
- row, col
- confidence
- expected_risk
- reason_code

### Perception Contract
- board_width, board_height
- tile_state_grid
- tile_confidence_grid
- game_phase: running | won | lost | unknown

### Safety Contract
- allowed_window_active: bool
- emergency_stop: bool
- action_rate_ok: bool

## Phase Plan

### Phase 0: Control Contract and Target Client Selection
Deliverables:
- Selected external client(s) and version pin.
- Approved control manifest.
- Safety requirements and stop conditions.

Exit Criteria:
- You approve the exact allowed controls and forbidden channels.

### Phase 1: Perception-Only Mode
Deliverables:
- Window lock, capture, and board segmentation.
- Tile classifier with confidence outputs.
- Replay viewer for perception verification.

Exit Criteria:
- Tile classification accuracy >= 99.0% on a labeled sample set.
- Coordinate mapping error <= 1 pixel median and <= 3 pixels p99.

### Phase 2: Read-Only Solver Baseline (No Clicks)
Deliverables:
- Deterministic logic solver running on perceived board state.
- Guess policy baseline with risk score output.

Exit Criteria:
- Decision consistency on replay tests >= 99.5%.
- No action attempted in read-only mode.

### Phase 3: Controlled Actuation
Deliverables:
- Safe input executor with foreground verification and rate limits.
- Dry-run mode that renders intended actions without clicking.

Exit Criteria:
- Misclick rate <= 0.2% over 1000 actions.
- Zero actions issued when target window is not active.

### Phase 4: Kernel Integration
Deliverables:
- Kernel policy adapter for uncertainty and exploration control.
- Telemetry tags separating deterministic vs adaptive decisions.

Exit Criteria:
- Adaptive decisions improve win rate vs deterministic baseline at equal risk budget.
- Manual override frequency remains low and explainable.

### Phase 5: Robustness and Transfer
Deliverables:
- Multi-client validation pack (if you want transfer).
- Stress tests: UI theme changes, scaling, latency, and focus interruptions.

Exit Criteria:
- Stable performance degradation under perturbation bands.
- No unsafe actions during fault injection.

## Metrics That Matter
- Win rate by board difficulty.
- Survival probability after first guess event.
- Wrong-flag rate.
- Perception confidence calibration error.
- Misclick rate and off-target action rate.
- Intervention rate (manual pause/stop, safety vetoes).
- Decision latency per move.

## Suggested User-Control Manifest (Example)
Use this as a starting shape for a config file.

- allowed_clients: [name, version]
- allowed_actions: [reveal, flag, chord]
- max_actions_per_second
- require_foreground_window: true
- allow_chord: true|false
- pause_hotkey
- stop_hotkey
- capture_region_policy: locked_window_only
- prohibited_channels: [memory_read, hidden_api]

## Risks and Mitigations

### Risk: Perception error creates unsafe clicks
Mitigation:
- Confidence gating and no-click fallback.
- Frame-diff verification after action.

### Risk: UI drift or scaling mismatch
Mitigation:
- Calibration routine at startup.
- Continuous coordinate sanity checks.

### Risk: Hidden brittleness in uncertainty policy
Mitigation:
- Track adaptive-vs-deterministic split and compare outcomes.
- Add explicit guess-quality dashboards.

### Risk: Focus theft causes accidental external clicks
Mitigation:
- Foreground window hard check before each action.
- Immediate stop on window mismatch.

## First Implementation Sprint (Execution Order)
1. Pick one external Minesweeper client and freeze version.
2. Implement window detection plus bounded capture.
3. Build tile-state classifier and confidence map.
4. Build read-only decision loop with full telemetry.
5. Add dry-run overlay and safety hotkeys.
6. Enable controlled reveal/flag clicks behind safety gates.

## Definition of Ready to Start Coding
- Approved control manifest is signed off.
- Target client and difficulty set are selected.
- Acceptance thresholds for perception and input safety are fixed.
- Logging schema for action and perception events is fixed.

## Definition of Done for Initial External Play
- Agent completes full games on the external client using only allowed controls.
- Safety constraints never violate approved boundaries.
- Run exports show reproducible perception-action traces.
- Performance is measurable and stable across repeated sessions.
