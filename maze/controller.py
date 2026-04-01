"""
Decision and control module.

Three stacked layers
--------------------
1. **Reflex layer** (``VetoLayer``)
   Fast, local hard rules — walls, known traps, cycle-detected repeated moves.
   Any action that fails the reflex layer is *immediately* rejected before reaching
   the deliberative layer.  This replaces the scattered ``is_catastrophic_trap``
   checks scattered across ``organism_control.py``.

2. **Deliberative layer** (``PolicyCore``)
   Medium-term heuristic scoring.  Takes the surviving candidate actions, the
   LocalView, frontier metadata, and motif biases, and produces a *ranked* list
   of (action, score, rationale_tags) tuples.  Pure-function style — no mutable
   state, so it can be swapped out or unit-tested independently.

3. **Executive layer** (``AgentController``)
   Global mode switching and final decision.  Owns mutable state (current mode,
   trajectory history, corridor escape counter).  Calls Layers 1 and 2, then
   applies executive overrides (e.g. "we've been in ESCAPE_CORRIDOR for 8 steps
   without gaining a frontier — push harder").

The hallway problem is addressed specifically:
- The VetoLayer rejects re-entry into a corridor cell whose pressure exceeds the
  overuse threshold *unless* it is the only option.
- PolicyCore strongly prefers junction-adjacent frontier cells over known-corridor
  dead-ends.
- AgentController switches to ESCAPE_CORRIDOR early (based on corridor pressure)
  and stays there until a genuine frontier cell is reached.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Sequence

from maze.frontier_memory import FrontierManager, MotifMemory
from maze.types import (
    ALL_DIRECTIONS,
    DIRECTION_OFFSETS,
    OPPOSITE,
    Action,
    AgentMode,
    Direction,
    Position,
    StructuralRole,
    VetoReason,
)
from maze.world_model import LocalView, WorldModel

# ---------------------------------------------------------------------------
# Data types shared across layers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionCandidate:
    """Input to the deliberative layer — a legal action + projected next cell."""

    action: Action
    next_pos: Position
    # App-supplied precomputed signals (optional — filled when available)
    visit_count: int = 0
    estimated_loop_risk: float = 0.0
    estimated_novelty: float = 0.0
    estimated_frontier_gain: float = 0.0
    dead_end_risk_depth: int = 0


@dataclass(frozen=True)
class ScoredAction:
    """Output of PolicyCore.score_candidates()."""

    action: Action
    next_pos: Position
    score: float
    rationale: tuple[str, ...]


@dataclass
class VetoDecision:
    """Outcome of the veto layer for a single candidate."""

    action: Action
    vetoed: bool
    reason: VetoReason | None


# ---------------------------------------------------------------------------
# 1. Reflex / Veto Layer
# ---------------------------------------------------------------------------

# How many times an action must appear in the recent window to be cycle-banned
_CYCLE_BAN_REPEAT_THRESHOLD = 3
# A corridor cell with pressure >= this triggers a veto (unless no alternatives)
_CORRIDOR_VETO_PRESSURE = 0.55


class VetoLayer:
    """
    Hard guardrail layer.

    Operates on the *action* level (not position level) for speed.  All rules
    are local: short trajectory history + corridor pressure from FrontierManager.

    Rules applied in priority order
    --------------------------------
    1. Cycle guard  — repeated A↔B oscillation banned for CYCLE_TABOO_DURATION steps.
    2. Corridor overuse — re-entering a known-overused corridor cell is vetoed
       when safer alternatives exist.
    3. Dead-end revisit — moving into a confirmed dead-end cell (1 open neighbour)
       that has already been visited is vetoed when other candidates remain.
    """

    def __init__(self, cycle_taboo_duration: int = 12) -> None:
        self._cycle_taboo_duration = cycle_taboo_duration
        # (action, expires_at_step) taboo list
        self._taboo: list[tuple[Action, int]] = []
        self._trajectory: Deque[tuple[Position, Action]] = deque(maxlen=24)
        # (from_pos, to_pos, expires_at_step) transition-level taboo entries
        self._taboo_transitions: list[tuple[Position, Position, int]] = []

    def record_move(self, pos: Position, action: Action, step: int) -> None:
        """Called *after* a move is committed so trajectory stays current."""
        self._trajectory.append((pos, action))
        # Detect A↔B oscillation in last 4 positions
        if len(self._trajectory) >= 4:
            tail = [a for _, a in list(self._trajectory)[-4:]]
            if tail[0] == tail[2] and tail[1] == tail[3] and tail[0] != tail[1]:
                # Ban both directions of the oscillation
                expires = step + self._cycle_taboo_duration
                existing_taboo_actions = {a for a, _ in self._taboo}
                for banned_action in (tail[0], tail[1]):
                    if banned_action not in existing_taboo_actions:
                        self._taboo.append((banned_action, expires))

        if len(self._trajectory) >= 2:
            prev_pos, prev_action = self._trajectory[-2]
            cur_pos, _ = self._trajectory[-1]
            if prev_pos != cur_pos:
                # Ban immediate reverse transition pair A->B and B->A for cooldown.
                expires = step + self._cycle_taboo_duration
                self._taboo_transitions.append((prev_pos, cur_pos, expires))
                self._taboo_transitions.append((cur_pos, prev_pos, expires))

    def _active_taboo_actions(self, step: int) -> set[Action]:
        self._taboo = [(a, e) for a, e in self._taboo if e > step]
        return {a for a, _ in self._taboo}

    def _transition_is_taboo(self, from_pos: Position, to_pos: Position, step: int) -> bool:
        self._taboo_transitions = [
            (frm, to, exp)
            for frm, to, exp in self._taboo_transitions
            if exp > step
        ]
        for frm, to, _exp in self._taboo_transitions:
            if frm == from_pos and to == to_pos:
                return True
        return False

    def _cycle_forbidden(self, step: int) -> set[Action]:
        """Actions forbidden by simple repeat-count in the recent window."""
        if not self._trajectory:
            return set()
        action_counts = Counter(a for _, a in self._trajectory)
        return {a for a, count in action_counts.items() if count >= _CYCLE_BAN_REPEAT_THRESHOLD}

    def filter(
        self,
        candidates: Sequence[ActionCandidate],
        world: WorldModel,
        frontier_mgr: FrontierManager,
        step: int,
    ) -> tuple[list[ActionCandidate], list[VetoDecision]]:
        """
        Return (approved_candidates, veto_log).

        If *all* candidates would be vetoed, the hard-veto rules are relaxed
        (soft-fail) and the cycle guard is lifted, returning the least-bad option.
        """
        taboo = self._active_taboo_actions(step)
        cycle_forbidden = self._cycle_forbidden(step)

        decisions: list[VetoDecision] = []
        approved: list[ActionCandidate] = []

        for c in candidates:
            reason: VetoReason | None = None
            from_pos = self._trajectory[-1][0] if self._trajectory else None

            # Rule 1: taboo from detected oscillation
            if c.action in taboo:
                reason = VetoReason.CYCLE_DETECTED
            elif from_pos is not None and self._transition_is_taboo(from_pos, c.next_pos, step):
                reason = VetoReason.CYCLE_DETECTED

            # Rule 2: corridor overuse (only when not already vetoed)
            elif frontier_mgr.is_corridor_overused(c.next_pos) and world.is_corridor(c.next_pos):
                reason = VetoReason.CORRIDOR_OVERUSE

            # Rule 3: dead-end revisit
            elif (
                world.is_dead_end(c.next_pos)
                and c.visit_count > 0
            ):
                reason = VetoReason.DEAD_END_REVISIT

            decisions.append(VetoDecision(action=c.action, vetoed=reason is not None, reason=reason))
            if reason is None:
                approved.append(c)

        if not approved:
            # Soft-fail: relax taboo and corridor veto, keep only dead-end revisit
            for c in candidates:
                if not (world.is_dead_end(c.next_pos) and c.visit_count > 1):
                    approved.append(c)

        if not approved:
            # Complete fallback: take whatever is least-visited
            approved = list(candidates)

        return approved, decisions


# ---------------------------------------------------------------------------
# 2. Deliberative Layer / Policy Core
# ---------------------------------------------------------------------------


class PolicyCore:
    """
    Pure-function style action scorer.

    Takes legal (post-veto) candidates and scores each one.  No mutable state.
    The scoring is designed so the hallway corridor naturally scores *lower* than
    a junction-adjacent frontier once the corridor pressure and motif biases are
    included.

    Weights
    -------
    novelty_weight          : reward for visiting an unknown-neighbour cell
    frontier_weight         : reward for reducing frontier distance
    junction_bonus          : bonus for moving toward a junction (high-degree cell)
    corridor_overuse_penalty: penalty applied when entering a high-pressure corridor
    dead_end_penalty        : penalty for entering a dead-end
    motif_weight            : how strongly motif memory biases the score
    loop_risk_weight        : penalty from app-supplied estimated_loop_risk
    """

    def __init__(
        self,
        novelty_weight: float = 2.0,
        frontier_weight: float = 3.0,
        junction_bonus: float = 1.5,
        corridor_overuse_penalty: float = 4.0,
        dead_end_penalty: float = 2.0,
        motif_weight: float = 1.0,
        loop_risk_weight: float = 3.0,
        corridor_forward_bias: float = 1.2,
        side_open_bias: float = 0.8,
    ) -> None:
        self.novelty_weight = novelty_weight
        self.frontier_weight = frontier_weight
        self.junction_bonus = junction_bonus
        self.corridor_overuse_penalty = corridor_overuse_penalty
        self.dead_end_penalty = dead_end_penalty
        self.motif_weight = motif_weight
        self.loop_risk_weight = loop_risk_weight
        self.corridor_forward_bias = corridor_forward_bias
        self.side_open_bias = side_open_bias

    def score_candidates(
        self,
        candidates: Sequence[ActionCandidate],
        world: WorldModel,
        frontier_mgr: FrontierManager,
        motif_mem: MotifMemory,
        view: LocalView,
    ) -> list[ScoredAction]:
        """
        Score each candidate action and return a sorted list (best first).
        """
        biases = motif_mem.suggest_biases(view)
        scored: list[ScoredAction] = []

        for c in candidates:
            rationale: list[str] = []
            score = 0.0

            # Novelty
            novelty_bonus = c.estimated_novelty * self.novelty_weight
            score += novelty_bonus
            if novelty_bonus > 0:
                rationale.append(f"novelty+{novelty_bonus:.2f}")

            # Frontier gain
            frontier_bonus = c.estimated_frontier_gain * self.frontier_weight
            score += frontier_bonus
            if frontier_bonus > 0:
                rationale.append(f"frontier+{frontier_bonus:.2f}")

            # Junction bonus: heading toward a junction is structurally valuable
            next_role = world.role(c.next_pos)
            if next_role == StructuralRole.JUNCTION:
                score += self.junction_bonus
                rationale.append("junction_bonus")

            # Corridor geometry bias: when in a corridor, prefer keeping forward flow.
            if view.is_corridor and c.action == view.facing and not view.front_is_wall:
                score += self.corridor_forward_bias
                rationale.append("corridor_forward_bias")

            # Side-wall asymmetry: if one side is blocked and the other is open,
            # bias toward the open-side turn to break hallway lock-in.
            if view.left_is_wall and not view.right_is_wall and c.action == "RIGHT":
                score += self.side_open_bias
                rationale.append("side_open_bias_right")
            elif view.right_is_wall and not view.left_is_wall and c.action == "LEFT":
                score += self.side_open_bias
                rationale.append("side_open_bias_left")

            # Corridor overuse penalty
            cp = frontier_mgr.corridor_pressure(c.next_pos)
            if cp > 0.0:
                penalty = cp * self.corridor_overuse_penalty
                score -= penalty
                rationale.append(f"corridor_pressure-{penalty:.2f}")

            # Dead-end penalty
            if world.is_dead_end(c.next_pos):
                score -= self.dead_end_penalty
                rationale.append("dead_end-")

            # Loop risk penalty (from app-level signals)
            loop_pen = c.estimated_loop_risk * self.loop_risk_weight
            score -= loop_pen
            if loop_pen > 0:
                rationale.append(f"loop_risk-{loop_pen:.2f}")

            # Motif bias
            motif_bias = biases.get(c.action, 0.0) * self.motif_weight
            score += motif_bias
            if abs(motif_bias) > 0.05:
                rationale.append(f"motif{'+'if motif_bias>=0 else ''}{motif_bias:.2f}")

            scored.append(ScoredAction(action=c.action, next_pos=c.next_pos, score=round(score, 4), rationale=tuple(rationale)))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored


# ---------------------------------------------------------------------------
# 3. Executive Layer
# ---------------------------------------------------------------------------


@dataclass
class ControllerState:
    """Mutable state owned by AgentController."""

    mode: AgentMode = AgentMode.EXPLORE_FRONTIER
    mode_entered_step: int = 0
    consecutive_corridor_steps: int = 0
    escape_steps_taken: int = 0
    last_action: Action | None = None
    last_pos: Position | None = None


class AgentController:
    """
    Top-level orchestrator.

    Decides which mode to be in, calls VetoLayer then PolicyCore, and applies
    executive overrides when needed.

    Mode transitions
    ----------------
    EXPLORE_FRONTIER  →  ESCAPE_CORRIDOR : corridor pressure too high, or N
                                           corridor steps in a row
    ESCAPE_CORRIDOR   →  EXPLORE_FRONTIER : agent reaches a junction or new frontier
    Any               →  GOAL_DIRECTED   : goal is visible and within BFS range

    ESCAPE_CORRIDOR behaviour
    -------------------------
    In escape mode the PolicyCore is run with heavier corridor-overuse penalties
    and the VetoLayer uses a stricter pressure threshold.  If the agent doesn't
    reach a junction after ``escape_timeout`` steps, we brute-force the least-
    visited candidate (same as organism_control.py's current fallback).
    """

    def __init__(
        self,
        cycle_taboo_duration: int = 12,
        corridor_step_escape_threshold: int = 5,
        escape_timeout: int = 14,
        escape_exit_pressure: float = 0.25,
        # PolicyCore weights forwarded at construction
        novelty_weight: float = 2.0,
        frontier_weight: float = 3.0,
        junction_bonus: float = 1.5,
        corridor_overuse_penalty: float = 4.0,
        dead_end_penalty: float = 2.0,
        motif_weight: float = 1.0,
        loop_risk_weight: float = 3.0,
        corridor_forward_bias: float = 1.2,
        side_open_bias: float = 0.8,
    ) -> None:
        self._veto = VetoLayer(cycle_taboo_duration=cycle_taboo_duration)
        self._policy = PolicyCore(
            novelty_weight=novelty_weight,
            frontier_weight=frontier_weight,
            junction_bonus=junction_bonus,
            corridor_overuse_penalty=corridor_overuse_penalty,
            dead_end_penalty=dead_end_penalty,
            motif_weight=motif_weight,
            loop_risk_weight=loop_risk_weight,
            corridor_forward_bias=corridor_forward_bias,
            side_open_bias=side_open_bias,
        )
        self._state = ControllerState()
        self._cycle_taboo_duration = cycle_taboo_duration
        self._corridor_step_escape_threshold = corridor_step_escape_threshold
        self._escape_timeout = escape_timeout
        self._escape_exit_pressure = escape_exit_pressure
        # Save base weights so mode-switching overrides are proportional
        self._base_corridor_overuse_penalty = corridor_overuse_penalty
        self._base_frontier_weight = frontier_weight

    @property
    def state(self) -> ControllerState:
        return self._state

    def reset(self) -> None:
        """Call at the start of each new episode."""
        self._veto = VetoLayer(cycle_taboo_duration=self._cycle_taboo_duration)
        self._state = ControllerState()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def step(
        self,
        candidates: Sequence[ActionCandidate],
        world: WorldModel,
        frontier_mgr: FrontierManager,
        motif_mem: MotifMemory,
        view: LocalView,
    ) -> tuple[Action, str, list[VetoDecision]]:
        """
        Choose an action for this step.

        Returns
        -------
        action       : the chosen action string
        rationale    : human-readable explanation tag string
        veto_log     : list of VetoDecision for debug output
        """
        step = view.step

        # --- Executive: determine mode ---
        mode = self._select_mode(view, frontier_mgr, step)
        self._state.mode = mode

        # --- Reflex layer ---
        approved, veto_log = self._veto.filter(candidates, world, frontier_mgr, step)

        # --- Deliberative layer ---
        # Adjust PolicyCore weights based on mode
        if mode == AgentMode.ESCAPE_CORRIDOR:
            # Heavier corridor penalty during escape
            self._policy.corridor_overuse_penalty = self._base_corridor_overuse_penalty * 1.75
            self._policy.frontier_weight = self._base_frontier_weight * 1.5
        elif mode == AgentMode.GOAL_DIRECTED:
            self._policy.frontier_weight = self._base_frontier_weight * 0.33
        else:
            self._policy.corridor_overuse_penalty = self._base_corridor_overuse_penalty
            self._policy.frontier_weight = self._base_frontier_weight

        scored = self._policy.score_candidates(approved, world, frontier_mgr, motif_mem, view)

        if not scored:
            # Should not normally happen — fall back to first candidate
            fallback = candidates[0].action if candidates else "UP"
            return fallback, "fallback_no_scored", veto_log

        # --- Executive override: GOAL_DIRECTED ---
        if mode == AgentMode.GOAL_DIRECTED and view.goal_direction is not None:
            cycle_vetoed_actions = {
                v.action
                for v in veto_log
                if v.vetoed and v.reason == VetoReason.CYCLE_DETECTED
            }
            for sc in scored:
                if sc.action == view.goal_direction:
                    if sc.action in cycle_vetoed_actions:
                        for alt in scored:
                            if alt.action not in cycle_vetoed_actions:
                                self._commit(alt.action, view.player_pos, step)
                                return (
                                    alt.action,
                                    f"exec_goal_directed_cycle_avoid goal_dir={sc.action} alt={alt.action}",
                                    veto_log,
                                )
                    self._commit(sc.action, view.player_pos, step)
                    return sc.action, f"exec_goal_directed goal_dir={sc.action}", veto_log

        # --- Executive override: ESCAPE forced ---
        if mode == AgentMode.ESCAPE_CORRIDOR and self._state.escape_steps_taken >= self._escape_timeout:
            # Brute-force least-visited
            best = min(approved, key=lambda c: (c.visit_count, c.estimated_loop_risk, -c.estimated_novelty))
            self._commit(best.action, view.player_pos, step)
            return best.action, f"exec_escape_timeout action={best.action}", veto_log

        best_action = scored[0].action
        rationale_str = f"mode={mode.name} {' '.join(scored[0].rationale)}"
        self._commit(best_action, view.player_pos, step)
        return best_action, rationale_str, veto_log

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_mode(self, view: LocalView, frontier_mgr: FrontierManager, step: int) -> AgentMode:
        """Determine the current executive mode."""
        # Goal visible → highest priority
        if view.goal_distance is not None and view.goal_distance <= 20:
            return AgentMode.GOAL_DIRECTED

        # Corridor escape: entered after pressure or repeated corridor steps
        current_pressure = frontier_mgr.corridor_pressure(view.player_pos)
        in_overused_corridor = view.is_corridor and current_pressure >= 0.4

        if view.is_corridor:
            self._state.consecutive_corridor_steps += 1
        else:
            self._state.consecutive_corridor_steps = 0

        should_escape = (
            self._state.consecutive_corridor_steps >= self._corridor_step_escape_threshold
            or in_overused_corridor
        )

        if should_escape:
            if self._state.mode != AgentMode.ESCAPE_CORRIDOR:
                self._state.mode_entered_step = step
                self._state.escape_steps_taken = 0
            return AgentMode.ESCAPE_CORRIDOR

        # Remain in escape mode until we hit a junction or low-pressure area
        if self._state.mode == AgentMode.ESCAPE_CORRIDOR:
            escaped = (
                view.is_junction
                or current_pressure < self._escape_exit_pressure
            )
            if not escaped:
                self._state.escape_steps_taken += 1
                return AgentMode.ESCAPE_CORRIDOR
            # Successfully escaped
            self._state.consecutive_corridor_steps = 0

        return AgentMode.EXPLORE_FRONTIER

    def _commit(self, action: Action, pos: Position, step: int) -> None:
        """Record the committed move for veto-layer trajectory tracking."""
        self._veto.record_move(pos, action, step)
        self._state.last_action = action
        self._state.last_pos = pos
