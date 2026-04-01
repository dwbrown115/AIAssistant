"""
Perception and world model module.

Responsibilities
----------------
* Maintain a canonical, queryable map of the maze (walls, open, frontier, unknown).
* Derive stable structural role labels (corridor, junction, dead-end, corner) for
  every known cell so higher-level modules never have to re-derive them from scratch.
* Provide a lightweight ``LocalView`` snapshot that any policy or veto layer can read
  without touching raw grid data.

Integration contract with app.py
---------------------------------
Call ``WorldModel.update()`` once per step, passing the sets that app.py already
maintains (``maze_known_cells``, ``blocked_cells``, ``episode_visited_cells``, etc.).
Everything else is read-only from the app's side.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable

from maze.types import (
    ALL_DIRECTIONS,
    DIRECTION_OFFSETS,
    CellType,
    Direction,
    Position,
    StructuralRole,
)


_LEFT_OF: dict[Direction, Direction] = {
    "UP": "LEFT",
    "LEFT": "DOWN",
    "DOWN": "RIGHT",
    "RIGHT": "UP",
}

_RIGHT_OF: dict[Direction, Direction] = {
    "UP": "RIGHT",
    "RIGHT": "DOWN",
    "DOWN": "LEFT",
    "LEFT": "UP",
}

_BACK_OF: dict[Direction, Direction] = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}


# ---------------------------------------------------------------------------
# LocalView – the "what can I see right now" snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NeighborInfo:
    """State and label for a single adjacent cell."""

    direction: Direction
    position: Position
    cell_type: CellType
    role: StructuralRole
    visit_count: int


@dataclass(frozen=True)
class LocalView:
    """
    Compact snapshot of the agent's immediate situation.

    Produced by ``WorldModel.get_local_view()`` and consumed by the controller
    layers without any further access to the full world model.
    """

    player_pos: Position
    facing: Direction
    step: int

    # Immediate neighbours (up / right / down / left)
    neighbors: tuple[NeighborInfo, ...]

    # Derived structural facts about *this* cell
    current_role: StructuralRole
    current_visit_count: int

    # Frontier proximity
    frontier_distance: int          # 0 = current cell touches unknown
    nearest_frontier_pos: Position | None

    # Goal proximity (filled when goal is visible to BFS, else None)
    goal_distance: int | None
    goal_direction: Direction | None

    # Convenience flags
    @property
    def is_corridor(self) -> bool:
        return self.current_role == StructuralRole.CORRIDOR

    @property
    def is_junction(self) -> bool:
        return self.current_role == StructuralRole.JUNCTION

    @property
    def is_dead_end(self) -> bool:
        return self.current_role == StructuralRole.DEAD_END

    @property
    def traversable_neighbors(self) -> tuple[NeighborInfo, ...]:
        return tuple(n for n in self.neighbors if n.cell_type in (CellType.OPEN, CellType.FRONTIER, CellType.START, CellType.END))

    @property
    def unknown_neighbors(self) -> tuple[NeighborInfo, ...]:
        return tuple(n for n in self.neighbors if n.cell_type == CellType.UNKNOWN)

    @property
    def open_degree(self) -> int:
        return len(self.traversable_neighbors)

    def neighbor_for(self, direction: Direction) -> NeighborInfo | None:
        for n in self.neighbors:
            if n.direction == direction:
                return n
        return None

    @property
    def front_neighbor(self) -> NeighborInfo | None:
        return self.neighbor_for(self.facing)

    @property
    def left_neighbor(self) -> NeighborInfo | None:
        return self.neighbor_for(_LEFT_OF[self.facing])

    @property
    def right_neighbor(self) -> NeighborInfo | None:
        return self.neighbor_for(_RIGHT_OF[self.facing])

    @property
    def back_neighbor(self) -> NeighborInfo | None:
        return self.neighbor_for(_BACK_OF[self.facing])

    @staticmethod
    def _is_wallish(neighbor: NeighborInfo | None) -> bool:
        if neighbor is None:
            return True
        return neighbor.cell_type == CellType.WALL

    @property
    def front_is_wall(self) -> bool:
        return self._is_wallish(self.front_neighbor)

    @property
    def left_is_wall(self) -> bool:
        return self._is_wallish(self.left_neighbor)

    @property
    def right_is_wall(self) -> bool:
        return self._is_wallish(self.right_neighbor)

    @property
    def back_is_wall(self) -> bool:
        return self._is_wallish(self.back_neighbor)


# ---------------------------------------------------------------------------
# VisitRecord – per-cell accounting
# ---------------------------------------------------------------------------


@dataclass
class CellRecord:
    """All we remember about a single grid cell."""

    cell_type: CellType = CellType.UNKNOWN
    role: StructuralRole = StructuralRole.UNKNOWN
    visit_count: int = 0
    last_visited_step: int = -1
    # Corridor pressure: incremented when the agent backtracks through this cell
    backtrack_count: int = 0


# ---------------------------------------------------------------------------
# WorldModel
# ---------------------------------------------------------------------------


class WorldModel:
    """
    Stable, queryable representation of the maze from the agent's perspective.

    All mutation happens through ``update()``.  Everything else is read-only.
    """

    def __init__(self, grid_size: int) -> None:
        self._grid_size = grid_size
        # Cell records keyed by (row, col) position
        self._cells: dict[Position, CellRecord] = {}
        # Cached frontier set (cells adjacent to UNKNOWN with a known-open neighbour)
        self._frontier: set[Position] = set()
        # The player's last position, used to detect backtracks
        self._prev_player_pos: Position | None = None
        # Special cells
        self.start_pos: Position | None = None
        self.goal_pos: Position | None = None

    # ------------------------------------------------------------------
    # Public mutation
    # ------------------------------------------------------------------

    def update(
        self,
        player_pos: Position,
        facing: Direction,
        step: int,
        known_cells: Iterable[Position],
        wall_cells: Iterable[Position],
        visit_counts: dict[Position, int],
        start_pos: Position | None = None,
        goal_pos: Position | None = None,
    ) -> None:
        """
        Merge new observation data from app.py into the world model.

        Parameters
        ----------
        player_pos   : current player grid cell (row, col)
        facing       : current facing direction
        step         : episode step index
        known_cells  : all cells app.py considers known-open (maze_known_cells)
        wall_cells   : all cells app.py considers walls (blocked_cells)
        visit_counts : episode-scoped visit count per cell (episode_visited_cells)
        start_pos    : start cell if known
        goal_pos     : goal/end cell if known
        """
        if start_pos is not None:
            self.start_pos = start_pos
        if goal_pos is not None:
            self.goal_pos = goal_pos

        # Absorb wall cells
        for wc in wall_cells:
            rec = self._cells.setdefault(wc, CellRecord())
            rec.cell_type = CellType.WALL
            rec.role = StructuralRole.UNKNOWN  # walls have no structural role

        # Absorb known open cells
        for kc in known_cells:
            rec = self._cells.setdefault(kc, CellRecord())
            if rec.cell_type not in (CellType.START, CellType.END):
                rec.cell_type = CellType.OPEN
            vc = visit_counts.get(kc, 0)
            if vc != rec.visit_count:
                rec.visit_count = vc

        # Mark start / goal
        if self.start_pos is not None:
            self._cells.setdefault(self.start_pos, CellRecord()).cell_type = CellType.START
        if self.goal_pos is not None:
            self._cells.setdefault(self.goal_pos, CellRecord()).cell_type = CellType.END

        # Update player cell visit timestamp and detect backtrack
        player_rec = self._cells.setdefault(player_pos, CellRecord())
        player_rec.last_visited_step = step
        if self._prev_player_pos is not None and player_pos == self._prev_player_pos:
            pass  # no movement
        elif self._prev_player_pos is not None:
            prev_rec = self._cells.get(self._prev_player_pos)
            if prev_rec is not None and player_pos == self._prev_player_pos:
                pass  # same cell
            # Detect explicit backtrack: if we moved back to the cell we were at 2 steps ago
            # (handled in FrontierMemory with trajectory history — kept simple here)

        self._prev_player_pos = player_pos

        # Rebuild structural roles for cells whose neighbourhoods may have changed.
        # We do a targeted refresh: the player's current cell + all traversable neighbours.
        to_refresh: set[Position] = {player_pos}
        for n in self._raw_traversable_neighbors(player_pos):
            to_refresh.add(n)

        for pos in to_refresh:
            self._refresh_role(pos)

        # Rebuild frontier
        self._rebuild_frontier()

    # ------------------------------------------------------------------
    # Structural role queries
    # ------------------------------------------------------------------

    def is_corridor(self, pos: Position) -> bool:
        rec = self._cells.get(pos)
        return rec is not None and rec.role == StructuralRole.CORRIDOR

    def is_junction(self, pos: Position) -> bool:
        rec = self._cells.get(pos)
        return rec is not None and rec.role == StructuralRole.JUNCTION

    def is_dead_end(self, pos: Position) -> bool:
        rec = self._cells.get(pos)
        return rec is not None and rec.role == StructuralRole.DEAD_END

    def cell_type(self, pos: Position) -> CellType:
        rec = self._cells.get(pos)
        return rec.cell_type if rec is not None else CellType.UNKNOWN

    def role(self, pos: Position) -> StructuralRole:
        rec = self._cells.get(pos)
        return rec.role if rec is not None else StructuralRole.UNKNOWN

    def visit_count(self, pos: Position) -> int:
        rec = self._cells.get(pos)
        return rec.visit_count if rec is not None else 0

    # ------------------------------------------------------------------
    # Neighbour queries
    # ------------------------------------------------------------------

    def neighbors_of(self, pos: Position) -> list[tuple[Direction, Position, CellType, StructuralRole]]:
        """Return (direction, neighbour_pos, cell_type, structural_role) for all 4 cardinal neighbours."""
        result = []
        for direction in ALL_DIRECTIONS:
            dr, dc = DIRECTION_OFFSETS[direction]
            npos: Position = (pos[0] + dr, pos[1] + dc)
            if not self._in_bounds(npos):
                continue
            ct = self.cell_type(npos)
            sr = self.role(npos)
            result.append((direction, npos, ct, sr))
        return result

    def traversable_neighbors(self, pos: Position) -> list[Position]:
        """Open / frontier / start / end cells adjacent to pos."""
        result = []
        for direction in ALL_DIRECTIONS:
            dr, dc = DIRECTION_OFFSETS[direction]
            npos: Position = (pos[0] + dr, pos[1] + dc)
            if not self._in_bounds(npos):
                continue
            ct = self.cell_type(npos)
            if ct not in (CellType.WALL, CellType.UNKNOWN):
                result.append(npos)
        return result

    # ------------------------------------------------------------------
    # Frontier queries
    # ------------------------------------------------------------------

    @property
    def frontier(self) -> frozenset[Position]:
        return frozenset(self._frontier)

    def frontier_distance(self, start: Position, max_depth: int = 12) -> int:
        """BFS distance from start to the nearest frontier cell."""
        if self._unknown_neighbor_count(start) > 0:
            return 0
        queue: deque[tuple[Position, int]] = deque([(start, 0)])
        seen: set[Position] = {start}
        while queue:
            pos, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for nxt in self._raw_traversable_neighbors(pos):
                if nxt in seen:
                    continue
                nd = depth + 1
                if self._unknown_neighbor_count(nxt) > 0:
                    return nd
                seen.add(nxt)
                queue.append((nxt, nd))
        return max_depth + 1

    def nearest_frontier_pos(self, start: Position, max_depth: int = 12) -> Position | None:
        """BFS to find the nearest frontier cell, returning its position."""
        if self._unknown_neighbor_count(start) > 0:
            return start
        queue: deque[tuple[Position, int]] = deque([(start, 0)])
        seen: set[Position] = {start}
        while queue:
            pos, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for nxt in self._raw_traversable_neighbors(pos):
                if nxt in seen:
                    continue
                nd = depth + 1
                if self._unknown_neighbor_count(nxt) > 0:
                    return nxt
                seen.add(nxt)
                queue.append((nxt, nd))
        return None

    # ------------------------------------------------------------------
    # Goal queries
    # ------------------------------------------------------------------

    def goal_distance(self, start: Position, max_depth: int = 999) -> int | None:
        """BFS distance to the goal. Returns None if goal is unknown."""
        if self.goal_pos is None:
            return None
        if start == self.goal_pos:
            return 0
        queue: deque[tuple[Position, int]] = deque([(start, 0)])
        seen: set[Position] = {start}
        while queue:
            pos, depth = queue.popleft()
            if depth >= max_depth:
                return None
            for nxt in self._raw_traversable_neighbors(pos):
                if nxt in seen:
                    continue
                nd = depth + 1
                if nxt == self.goal_pos:
                    return nd
                seen.add(nxt)
                queue.append((nxt, nd))
        return None

    def direction_toward_goal(self, start: Position) -> Direction | None:
        """Return the first direction of the BFS shortest path to the goal."""
        if self.goal_pos is None:
            return None
        if start == self.goal_pos:
            return None
        # BFS tracking parent
        parent: dict[Position, tuple[Position, Direction]] = {}
        queue: deque[Position] = deque([start])
        seen: set[Position] = {start}
        found = False
        while queue and not found:
            pos = queue.popleft()
            for direction in ALL_DIRECTIONS:
                dr, dc = DIRECTION_OFFSETS[direction]
                npos: Position = (pos[0] + dr, pos[1] + dc)
                if npos in seen or not self._in_bounds(npos):
                    continue
                ct = self.cell_type(npos)
                if ct in (CellType.WALL,):
                    continue
                parent[npos] = (pos, direction)
                if npos == self.goal_pos:
                    found = True
                    break
                if ct != CellType.UNKNOWN:
                    seen.add(npos)
                    queue.append(npos)
        if not found:
            return None
        # Trace back to find first step
        cur = self.goal_pos
        while cur in parent and parent[cur][0] != start:
            cur = parent[cur][0]
        return parent[cur][1] if cur in parent else None

    # ------------------------------------------------------------------
    # LocalView factory
    # ------------------------------------------------------------------

    def get_local_view(self, player_pos: Position, facing: Direction, step: int) -> LocalView:
        """Build a fully computed LocalView for the current agent position."""
        neighbor_infos: list[NeighborInfo] = []
        for direction, npos, ct, sr in self.neighbors_of(player_pos):
            vc = self.visit_count(npos)
            neighbor_infos.append(NeighborInfo(direction=direction, position=npos, cell_type=ct, role=sr, visit_count=vc))

        current_rec = self._cells.get(player_pos, CellRecord())
        fd = self.frontier_distance(player_pos)
        nfp = self.nearest_frontier_pos(player_pos)
        gd = self.goal_distance(player_pos)
        gdir = self.direction_toward_goal(player_pos) if self.goal_pos is not None else None

        return LocalView(
            player_pos=player_pos,
            facing=facing,
            step=step,
            neighbors=tuple(neighbor_infos),
            current_role=current_rec.role,
            current_visit_count=current_rec.visit_count,
            frontier_distance=fd,
            nearest_frontier_pos=nfp,
            goal_distance=gd,
            goal_direction=gdir,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _in_bounds(self, pos: Position) -> bool:
        r, c = pos
        return 0 <= r < self._grid_size and 0 <= c < self._grid_size

    def _raw_traversable_neighbors(self, pos: Position) -> list[Position]:
        """Traversable neighbours using internal cell records (no CellType.UNKNOWN)."""
        result = []
        for direction in ALL_DIRECTIONS:
            dr, dc = DIRECTION_OFFSETS[direction]
            npos: Position = (pos[0] + dr, pos[1] + dc)
            if not self._in_bounds(npos):
                continue
            ct = self.cell_type(npos)
            if ct not in (CellType.WALL, CellType.UNKNOWN):
                result.append(npos)
        return result

    def _unknown_neighbor_count(self, pos: Position) -> int:
        count = 0
        for direction in ALL_DIRECTIONS:
            dr, dc = DIRECTION_OFFSETS[direction]
            npos: Position = (pos[0] + dr, pos[1] + dc)
            if not self._in_bounds(npos):
                continue
            if self.cell_type(npos) == CellType.UNKNOWN:
                count += 1
        return count

    def _refresh_role(self, pos: Position) -> None:
        """Recompute and store the structural role for a single cell."""
        rec = self._cells.get(pos)
        if rec is None or rec.cell_type in (CellType.WALL, CellType.UNKNOWN):
            return

        traversable = self._raw_traversable_neighbors(pos)
        n = len(traversable)

        if n == 0:
            rec.role = StructuralRole.ISOLATED
        elif n == 1:
            rec.role = StructuralRole.DEAD_END
        elif n == 2:
            # Corridor if the two neighbours are directly opposite (collinear)
            a, b = traversable
            dr_a = a[0] - pos[0]
            dc_a = a[1] - pos[1]
            dr_b = b[0] - pos[0]
            dc_b = b[1] - pos[1]
            if dr_a == -dr_b and dc_a == -dc_b:
                rec.role = StructuralRole.CORRIDOR
            else:
                rec.role = StructuralRole.CORNER
        else:
            rec.role = StructuralRole.JUNCTION

    def _rebuild_frontier(self) -> None:
        """Recompute the frontier set from scratch."""
        new_frontier: set[Position] = set()
        for pos, rec in self._cells.items():
            if rec.cell_type in (CellType.OPEN, CellType.START, CellType.END):
                if self._unknown_neighbor_count(pos) > 0:
                    new_frontier.add(pos)
        self._frontier = new_frontier
