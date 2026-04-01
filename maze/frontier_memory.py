"""
Frontier and memory module.

Responsibilities
----------------
* Track all frontier cells with rich metadata (structural type, novelty, pressure).
* Maintain per-corridor pressure: how overused is a hallway segment?
* Store episodic "motifs" — reusable structural patterns tied to action outcomes —
  so the policy can bias itself based on what has worked or failed before in
  similar situations.

The module is purely about *what the agent has seen and remembered*.  It does not
make decisions; that is the controller's job.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Literal, Optional

from maze.types import DIRECTION_OFFSETS, Direction, Position, StructuralRole
from maze.world_model import LocalView, WorldModel

# ---------------------------------------------------------------------------
# Frontier cell record
# ---------------------------------------------------------------------------

FrontierStrategy = Literal["max_novelty", "min_dead_end_risk", "nearest", "balanced"]


@dataclass
class FrontierCell:
    """Everything the agent knows about a specific frontier cell."""

    pos: Position
    role: StructuralRole              # structural role of this frontier cell's open neighbour
    novelty_score: float              # 1.0 = never touched, decays with visits
    dead_end_risk: float              # 0‥1 estimate from local topology
    distance_from_player: int        # BFS hops from current position
    distance_from_start: int         # BFS hops from episode start
    distance_from_goal: int | None   # BFS hops to goal if known
    first_seen_step: int
    last_updated_step: int

    @property
    def score_balanced(self) -> float:
        """Composite score used by 'balanced' frontier strategy."""
        dist_penalty = self.distance_from_player * 0.05
        return self.novelty_score - self.dead_end_risk * 0.4 - dist_penalty


# ---------------------------------------------------------------------------
# Corridor pressure tracker
# ---------------------------------------------------------------------------


@dataclass
class CorridorPressure:
    """Accumulated stress for a single corridor cell."""

    visit_count: int = 0
    backtrack_count: int = 0
    penalty_events: int = 0

    @property
    def pressure(self) -> float:
        """Scalar pressure in [0, 1]."""
        raw = (
            self.visit_count * 0.12
            + self.backtrack_count * 0.25
            + self.penalty_events * 0.18
        )
        return min(1.0, raw)


# ---------------------------------------------------------------------------
# Motif memory — episodic structural patterns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MotifKey:
    """Compact identifier for a recurring structural situation."""

    role: StructuralRole
    open_degree: int            # how many traversable neighbours
    unknown_count: int          # unknown-cell neighbours
    facing: Direction
    frontier_distance_bucket: int  # quantised to 0/1/2/3+


@dataclass
class MotifRecord:
    """Accumulated outcome statistics for a motif."""

    key: MotifKey
    total_steps: int = 0
    reward_sum: float = 0.0
    penalty_sum: float = 0.0
    action_counts: dict[str, int] = field(default_factory=dict)
    action_rewards: dict[str, float] = field(default_factory=dict)
    action_penalties: dict[str, float] = field(default_factory=dict)

    def record(self, action: str, reward: float, penalty: float) -> None:
        self.total_steps += 1
        self.reward_sum += reward
        self.penalty_sum += penalty
        self.action_counts[action] = self.action_counts.get(action, 0) + 1
        self.action_rewards[action] = self.action_rewards.get(action, 0.0) + reward
        self.action_penalties[action] = self.action_penalties.get(action, 0.0) + penalty

    def best_action(self) -> str | None:
        """Return the action with the best net reward/penalty balance."""
        if not self.action_counts:
            return None
        def net(a: str) -> float:
            r = self.action_rewards.get(a, 0.0)
            p = self.action_penalties.get(a, 0.0)
            n = self.action_counts.get(a, 1)
            return (r - p) / max(1, n)
        return max(self.action_counts.keys(), key=net)

    def suggested_bias(self) -> dict[str, float]:
        """Return a {action: bias_weight} dict scaled to [-1, 1]."""
        biases: dict[str, float] = {}
        for action in self.action_counts:
            n = max(1, self.action_counts[action])
            r = self.action_rewards.get(action, 0.0) / n
            p = self.action_penalties.get(action, 0.0) / n
            biases[action] = max(-1.0, min(1.0, r - p))
        return biases


class MotifMemory:
    """
    Store and query named structural motifs.

    A motif is keyed by the agent's local structural situation (role + degree +
    unknown count + facing + quantised frontier distance).  Whenever an action
    is taken from that situation, we record the reward/penalty outcome so future
    visits can be biased accordingly.
    """

    def __init__(self, max_motifs: int = 512) -> None:
        self._records: dict[MotifKey, MotifRecord] = {}
        self._max_motifs = max_motifs

    def _make_key(self, view: LocalView) -> MotifKey:
        fd_bucket = min(3, view.frontier_distance)
        return MotifKey(
            role=view.current_role,
            open_degree=view.open_degree,
            unknown_count=len(view.unknown_neighbors),
            facing=view.facing,
            frontier_distance_bucket=fd_bucket,
        )

    def record_step(self, view: LocalView, action: str, reward: float, penalty: float) -> None:
        key = self._make_key(view)
        if key not in self._records:
            if len(self._records) >= self._max_motifs:
                # Evict least-observed motif to cap memory
                oldest = min(self._records, key=lambda k: self._records[k].total_steps)
                del self._records[oldest]
            self._records[key] = MotifRecord(key=key)
        self._records[key].record(action, reward, penalty)

    def match_motifs(self, view: LocalView) -> list[MotifRecord]:
        """Return all motif records that match the current structural situation."""
        key = self._make_key(view)
        rec = self._records.get(key)
        return [rec] if rec is not None else []

    def suggest_biases(self, view: LocalView) -> dict[str, float]:
        """
        Return a {action: bias_weight} dict combining all matching motifs.

        Positive weight → prefer this action; negative → avoid.
        """
        matches = self.match_motifs(view)
        if not matches:
            return {}
        combined: dict[str, float] = {}
        for rec in matches:
            for action, bias in rec.suggested_bias().items():
                combined[action] = combined.get(action, 0.0) + bias
        # Normalise to [-1, 1]
        if combined:
            max_abs = max(abs(v) for v in combined.values()) or 1.0
            combined = {a: v / max_abs for a, v in combined.items()}
        return combined


# ---------------------------------------------------------------------------
# FrontierManager
# ---------------------------------------------------------------------------


class FrontierManager:
    """
    Own all "where can I still go?" logic.

    Updated once per step via ``update()``.  Queries are read-only.
    """

    def __init__(self, max_frontier_cells: int = 256, overuse_threshold: float = 0.55) -> None:
        self._frontier_cells: dict[Position, FrontierCell] = {}
        self._corridor_pressure: dict[Position, CorridorPressure] = {}
        self._max_frontier_cells = max_frontier_cells
        # A corridor is considered "overused" if its pressure exceeds this threshold
        self._overuse_threshold = overuse_threshold
        # Trajectory ring buffer for backtrack detection
        self._trajectory: Deque[Position] = deque(maxlen=32)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update(
        self,
        world: WorldModel,
        player_pos: Position,
        step: int,
        visit_counts: dict[Position, int],
        penalty_this_step: float = 0.0,
    ) -> None:
        """
        Sync frontier and corridor-pressure state from the WorldModel.

        Called once per step, after ``WorldModel.update()``.
        """
        # Detect backtrack: if player_pos matches the trajectory 2 steps ago
        trajectory_list = list(self._trajectory)
        is_backtrack = len(trajectory_list) >= 2 and player_pos == trajectory_list[-2]
        self._trajectory.append(player_pos)

        # Update corridor pressure for the current cell
        if world.is_corridor(player_pos):
            cp = self._corridor_pressure.setdefault(player_pos, CorridorPressure())
            cp.visit_count = visit_counts.get(player_pos, 0)
            if is_backtrack:
                cp.backtrack_count += 1
            if penalty_this_step > 0.0:
                cp.penalty_events += 1

        # Rebuild frontier from the world model's frontier set
        current_frontier = world.frontier
        # Remove cells no longer on the frontier
        stale = [pos for pos in self._frontier_cells if pos not in current_frontier]
        for pos in stale:
            del self._frontier_cells[pos]

        # Add / refresh cells now on the frontier
        for fpos in current_frontier:
            fd = world.frontier_distance(player_pos)
            vc = visit_counts.get(fpos, 0)
            novelty = 1.0 / (1.0 + vc * 0.5)
            traversable = world.traversable_neighbors(fpos)
            dead_end_risk = 1.0 / max(1, len(traversable))  # fewer exits → higher risk

            if fpos in self._frontier_cells:
                existing = self._frontier_cells[fpos]
                self._frontier_cells[fpos] = FrontierCell(
                    pos=fpos,
                    role=world.role(fpos),
                    novelty_score=round(novelty, 4),
                    dead_end_risk=round(dead_end_risk, 4),
                    distance_from_player=fd,
                    distance_from_start=existing.distance_from_start,
                    distance_from_goal=world.goal_distance(fpos),
                    first_seen_step=existing.first_seen_step,
                    last_updated_step=step,
                )
            else:
                if len(self._frontier_cells) >= self._max_frontier_cells:
                    # Evict lowest novelty frontier cell
                    worst = min(self._frontier_cells, key=lambda p: self._frontier_cells[p].novelty_score)
                    del self._frontier_cells[worst]
                self._frontier_cells[fpos] = FrontierCell(
                    pos=fpos,
                    role=world.role(fpos),
                    novelty_score=round(novelty, 4),
                    dead_end_risk=round(dead_end_risk, 4),
                    distance_from_player=fd,
                    distance_from_start=0,  # could BFS from start if needed
                    distance_from_goal=world.goal_distance(fpos),
                    first_seen_step=step,
                    last_updated_step=step,
                )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def all_frontier_cells(self) -> list[FrontierCell]:
        return list(self._frontier_cells.values())

    def get_best_frontier(self, strategy: FrontierStrategy = "balanced") -> FrontierCell | None:
        """
        Return the highest-priority frontier cell for the given strategy.

        Parameters
        ----------
        strategy : "max_novelty" | "min_dead_end_risk" | "nearest" | "balanced"
        """
        cells = list(self._frontier_cells.values())
        if not cells:
            return None
        if strategy == "max_novelty":
            return max(cells, key=lambda c: c.novelty_score)
        if strategy == "min_dead_end_risk":
            return min(cells, key=lambda c: c.dead_end_risk)
        if strategy == "nearest":
            return min(cells, key=lambda c: c.distance_from_player)
        # balanced (default)
        return max(cells, key=lambda c: c.score_balanced)

    def has_unexplored_branch_near(self, pos: Position, world: WorldModel, radius: int = 3) -> bool:
        """
        True if there is a frontier cell within ``radius`` BFS hops of ``pos``
        that is adjacent to a junction (branching point), implying unexplored
        branches rather than dead-end corridors.
        """
        for fc in self._frontier_cells.values():
            if fc.distance_from_player <= radius and fc.role == StructuralRole.JUNCTION:
                return True
        return False

    def corridor_pressure(self, pos: Position) -> float:
        """Pressure scalar [0, 1] for a corridor cell.  0 for non-corridors."""
        cp = self._corridor_pressure.get(pos)
        return cp.pressure if cp is not None else 0.0

    def is_corridor_overused(self, pos: Position) -> bool:
        return self.corridor_pressure(pos) >= self._overuse_threshold

    def has_frontier_desert(self, threshold_steps: int = 20) -> bool:
        """
        True if the frontier set has been empty (or effectively empty) for
        ``threshold_steps`` steps — indicating the agent may be stuck in a
        fully explored sub-region with no visible new area.
        """
        return len(self._frontier_cells) == 0
