"""
Runner — thin wiring layer between app.py and the maze package.

This module is the *only* file that app.py needs to import from the maze
package.  It exposes:

* ``MazeAgent``  — stateful object that wraps WorldModel + FrontierManager +
                   MotifMemory + AgentController and presents a single
                   ``step()`` call to the outside world.

* ``CandidateInput`` — lightweight dataclass for app.py to submit per-candidate
                       signals without exposing app internals.

* ``StepOutput``  — what a ``MazeAgent.step()`` call returns.

Integration recipe for app.py
------------------------------
1. At app startup / maze reset::

       self.maze_agent = MazeAgent(grid_size=self.grid_cells)

2. Each exploration step (replacing or supplementing the organism_control hook)::

       candidates = [
           CandidateInput(
               action=move,
               next_pos=next_cell,
               visit_count=self.episode_visited_cells.get(next_cell, 0),
               estimated_loop_risk=...,   # from _organism_candidate_projections or 0
               estimated_novelty=...,
               estimated_frontier_gain=...,
               dead_end_risk_depth=...,
           )
           for move, next_cell in legal_candidates
       ]

       out = self.maze_agent.step(
           player_pos=self.current_player_cell,
           facing=self.player_facing,
           step=self.memory_step_index,
           known_cells=self.maze_known_cells,
           wall_cells=self.blocked_cells,
           visit_counts=self.episode_visited_cells,
           candidates=candidates,
           penalty_this_step=...,   # scalar from last event, or 0
           start_pos=self.start_cell,
           goal_pos=self.end_cell if hasattr(self, 'end_cell') else None,
       )

       chosen_action = out.action
       # out.mode, out.rationale, out.veto_log available for debug

3. Record outcome for motif memory (call *after* the move resolves)::

       self.maze_agent.record_outcome(
           view=out.view,
           action=out.action,
           reward=reward_this_step,
           penalty=penalty_this_step,
       )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from maze.controller import ActionCandidate, AgentController, VetoDecision
from maze.frontier_memory import FrontierManager, MotifMemory
from maze.types import Action, AgentMode, Direction, Position
from maze.world_model import LocalView, WorldModel


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CandidateInput:
    """
    Per-candidate signals from app.py.

    All float fields default to 0 and are optional — fill in what you have
    from the existing ``_organism_candidate_projections()`` output.
    """

    action: Action
    next_pos: Position
    visit_count: int = 0
    estimated_loop_risk: float = 0.0
    estimated_novelty: float = 0.0
    estimated_frontier_gain: float = 0.0
    dead_end_risk_depth: int = 0


@dataclass
class StepOutput:
    """What MazeAgent.step() returns to the caller."""

    action: Action
    mode: AgentMode
    rationale: str
    veto_log: list[VetoDecision]
    view: LocalView   # the LocalView used this step — keep it for record_outcome()


# ---------------------------------------------------------------------------
# MazeAgent
# ---------------------------------------------------------------------------


class MazeAgent:
    """
    Stateful agent object.  Create one per episode (or call ``reset()``).

    Internally owns:
    - WorldModel        — canonical map + structural labels
    - FrontierManager   — frontier cells + corridor pressure + motifs
    - MotifMemory       — episodic structural patterns
    - AgentController   — veto + policy + executive

    All numeric parameters have sensible defaults and can be overridden via
    env vars (read in app.py and passed here).
    """

    def __init__(
        self,
        grid_size: int,
        # VetoLayer / cycle suppression
        cycle_taboo_duration: int = 12,
        # AgentController mode-switching thresholds
        corridor_step_escape_threshold: int = 5,
        escape_timeout: int = 14,
        escape_exit_pressure: float = 0.25,
        # FrontierManager corridor-overuse threshold
        corridor_overuse_threshold: float = 0.55,
        # PolicyCore scoring weights
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
        self._grid_size = grid_size
        self._init_kwargs = dict(
            cycle_taboo_duration=cycle_taboo_duration,
            corridor_step_escape_threshold=corridor_step_escape_threshold,
            escape_timeout=escape_timeout,
            escape_exit_pressure=escape_exit_pressure,
            corridor_overuse_threshold=corridor_overuse_threshold,
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
        self._world = WorldModel(grid_size=grid_size)
        self._frontier_mgr = FrontierManager(overuse_threshold=corridor_overuse_threshold)
        self._motif_mem = MotifMemory()
        self._controller = AgentController(
            cycle_taboo_duration=cycle_taboo_duration,
            corridor_step_escape_threshold=corridor_step_escape_threshold,
            escape_timeout=escape_timeout,
            escape_exit_pressure=escape_exit_pressure,
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all state for a new episode."""
        self._world = WorldModel(grid_size=self._grid_size)
        kw = self._init_kwargs
        self._frontier_mgr = FrontierManager(overuse_threshold=kw["corridor_overuse_threshold"])
        self._motif_mem = MotifMemory()
        self._controller.reset()

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    def step(
        self,
        player_pos: Position,
        facing: Direction,
        step: int,
        known_cells: Iterable[Position],
        wall_cells: Iterable[Position],
        visit_counts: dict[Position, int],
        candidates: Sequence[CandidateInput],
        penalty_this_step: float = 0.0,
        start_pos: Position | None = None,
        goal_pos: Position | None = None,
    ) -> StepOutput:
        """
        Run one agent step and return the chosen action + debug metadata.

        Parameters mimic the data already available in app.py at the point
        where _organism_live_exploration_move() is called.
        """
        # 1. Update world model
        self._world.update(
            player_pos=player_pos,
            facing=facing,
            step=step,
            known_cells=known_cells,
            wall_cells=wall_cells,
            visit_counts=visit_counts,
            start_pos=start_pos,
            goal_pos=goal_pos,
        )

        # 2. Update frontier manager
        self._frontier_mgr.update(
            world=self._world,
            player_pos=player_pos,
            step=step,
            visit_counts=visit_counts,
            penalty_this_step=penalty_this_step,
        )

        # 3. Build LocalView
        view = self._world.get_local_view(player_pos, facing, step)

        # 4. Convert CandidateInput → ActionCandidate (internal form)
        action_candidates = [
            ActionCandidate(
                action=ci.action,
                next_pos=ci.next_pos,
                visit_count=ci.visit_count,
                estimated_loop_risk=ci.estimated_loop_risk,
                estimated_novelty=ci.estimated_novelty,
                estimated_frontier_gain=ci.estimated_frontier_gain,
                dead_end_risk_depth=ci.dead_end_risk_depth,
            )
            for ci in candidates
        ]

        if not action_candidates:
            # No legal moves — return an arbitrary direction and let app.py handle it
            return StepOutput(
                action="UP",
                mode=self._controller.state.mode,
                rationale="no_candidates",
                veto_log=[],
                view=view,
            )

        # 5. Controller step (veto → policy → executive)
        action, rationale, veto_log = self._controller.step(
            candidates=action_candidates,
            world=self._world,
            frontier_mgr=self._frontier_mgr,
            motif_mem=self._motif_mem,
            view=view,
        )

        return StepOutput(
            action=action,
            mode=self._controller.state.mode,
            rationale=rationale,
            veto_log=veto_log,
            view=view,
        )

    # ------------------------------------------------------------------
    # Outcome recording (call after the move resolves)
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        view: LocalView,
        action: Action,
        reward: float,
        penalty: float,
    ) -> None:
        """
        Update MotifMemory with the outcome of the action taken in this step.

        Call this *after* the move resolves and rewards/penalties are known.
        Typically you can call it at the top of the *next* step before
        calling ``step()``, passing in the previous step's view and action.
        """
        self._motif_mem.record_step(view=view, action=action, reward=reward, penalty=penalty)

    # ------------------------------------------------------------------
    # Read-only accessors for debug / display
    # ------------------------------------------------------------------

    @property
    def world(self) -> WorldModel:
        return self._world

    @property
    def frontier_manager(self) -> FrontierManager:
        return self._frontier_mgr

    @property
    def controller_state(self) -> object:
        return self._controller.state
