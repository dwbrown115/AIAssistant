"""Optional forward/backward projection overlay for maze move scoring.

This module is intentionally separate from core planner logic. It provides
"imagination" signals that can be blended into any caller's score model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

Position = tuple[int, int]
NeighborFn = Callable[[Position], Sequence[Position]]
CountFn = Callable[[Position], int]
KnownFn = Callable[[Position], bool]


@dataclass(frozen=True)
class ProjectionConfig:
    enabled: bool = True
    forward_depth: int = 3
    forward_weight: float = 1.0
    backtrace_window: int = 14
    backtrace_penalty_weight: float = 1.0
    backtrace_escape_weight: float = 1.0


@dataclass(frozen=True)
class ProjectionOutcome:
    forward_bonus: int
    backward_penalty: int
    backward_escape_bonus: int
    forward_path: tuple[Position, ...]
    forward_progress_signal: float
    forward_novelty_signal: float
    forward_trap_signal: float
    backward_loop_pressure: float
    backward_seen_ratio: float


class ProjectionModule:
    """Compute projection bonuses/penalties from lightweight imagined traces."""

    def __init__(self, config: ProjectionConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        origin: Position,
        candidate: Position,
        origin_frontier_distance: int,
        candidate_unknown_neighbors: int,
        candidate_frontier_distance: int,
        recent_path: Sequence[Position],
        traversable_neighbors_fn: NeighborFn,
        unknown_neighbor_count_fn: CountFn,
        frontier_distance_fn: CountFn,
        fully_known_fn: KnownFn,
    ) -> ProjectionOutcome:
        if not self.config.enabled:
            return ProjectionOutcome(
                forward_bonus=0,
                backward_penalty=0,
                backward_escape_bonus=0,
                forward_path=(),
                forward_progress_signal=0.0,
                forward_novelty_signal=0.0,
                forward_trap_signal=0.0,
                backward_loop_pressure=0.0,
                backward_seen_ratio=0.0,
            )

        (
            forward_bonus,
            forward_path,
            forward_progress_signal,
            forward_novelty_signal,
            forward_trap_signal,
        ) = self._forward_projection(
            origin=origin,
            candidate=candidate,
            origin_frontier_distance=origin_frontier_distance,
            traversable_neighbors_fn=traversable_neighbors_fn,
            unknown_neighbor_count_fn=unknown_neighbor_count_fn,
            frontier_distance_fn=frontier_distance_fn,
        )

        backward_penalty, backward_escape_bonus, backward_loop_pressure, backward_seen_ratio = (
            self._backward_projection(
                origin=origin,
                candidate=candidate,
                candidate_unknown_neighbors=candidate_unknown_neighbors,
                candidate_frontier_distance=candidate_frontier_distance,
                origin_frontier_distance=origin_frontier_distance,
                recent_path=recent_path,
                unknown_neighbor_count_fn=unknown_neighbor_count_fn,
                fully_known_fn=fully_known_fn,
            )
        )

        return ProjectionOutcome(
            forward_bonus=forward_bonus,
            backward_penalty=backward_penalty,
            backward_escape_bonus=backward_escape_bonus,
            forward_path=tuple(forward_path),
            forward_progress_signal=round(forward_progress_signal, 3),
            forward_novelty_signal=round(forward_novelty_signal, 3),
            forward_trap_signal=round(forward_trap_signal, 3),
            backward_loop_pressure=round(backward_loop_pressure, 3),
            backward_seen_ratio=round(backward_seen_ratio, 3),
        )

    def _forward_projection(
        self,
        *,
        origin: Position,
        candidate: Position,
        origin_frontier_distance: int,
        traversable_neighbors_fn: NeighborFn,
        unknown_neighbor_count_fn: CountFn,
        frontier_distance_fn: CountFn,
    ) -> tuple[int, list[Position], float, float, float]:
        depth = max(1, int(self.config.forward_depth))
        path: list[Position] = [candidate]
        previous = origin
        current = candidate

        for _ in range(max(0, depth - 1)):
            next_candidates = [
                nxt
                for nxt in traversable_neighbors_fn(current)
                if nxt != previous
            ]
            if not next_candidates:
                break

            def _rank(nxt: Position) -> tuple[float, int, int, int, int]:
                unknown_n = max(0, int(unknown_neighbor_count_fn(nxt)))
                frontier_n = max(0, int(frontier_distance_fn(nxt)))
                degree_n = len(traversable_neighbors_fn(nxt))
                signal = (unknown_n * 2.2) + max(0.0, (4.0 - float(frontier_n)) * 0.8)
                if degree_n >= 3:
                    signal += 0.9
                if degree_n <= 1 and unknown_n == 0:
                    signal -= 1.3
                return (signal, unknown_n, -frontier_n, degree_n, -nxt[0] - nxt[1])

            next_candidates.sort(key=_rank, reverse=True)
            nxt = next_candidates[0]
            path.append(nxt)
            previous, current = current, nxt

        if not path:
            return 0, [], 0.0, 0.0, 0.0

        frontier_vals = [max(0, int(frontier_distance_fn(cell))) for cell in path]
        best_frontier = min(frontier_vals) if frontier_vals else max(0, int(origin_frontier_distance))
        progress_signal = max(0.0, float(max(0, int(origin_frontier_distance)) - best_frontier))

        unknown_vals = [max(0, int(unknown_neighbor_count_fn(cell))) for cell in path]
        novelty_signal = sum(min(2, val) for val in unknown_vals) / max(1.0, float(len(path)))

        trap_signal = 0.0
        for cell in path:
            degree = len(traversable_neighbors_fn(cell))
            if degree <= 1 and max(0, int(unknown_neighbor_count_fn(cell))) == 0:
                trap_signal += 1.0

        raw_bonus = (progress_signal * 6.0) + (novelty_signal * 4.0) - (trap_signal * 3.0)
        forward_bonus = max(
            0,
            int(round(raw_bonus * max(0.0, float(self.config.forward_weight)))),
        )
        return forward_bonus, path, progress_signal, novelty_signal, trap_signal

    def _backward_projection(
        self,
        *,
        origin: Position,
        candidate: Position,
        candidate_unknown_neighbors: int,
        candidate_frontier_distance: int,
        origin_frontier_distance: int,
        recent_path: Sequence[Position],
        unknown_neighbor_count_fn: CountFn,
        fully_known_fn: KnownFn,
    ) -> tuple[int, int, float, float]:
        window = max(4, int(self.config.backtrace_window))
        if not recent_path:
            return 0, 0, 0.0, 0.0

        trail = list(recent_path[-window:])
        if not trail or trail[-1] != origin:
            trail.append(origin)
        if len(trail) < 2:
            return 0, 0, 0.0, 0.0

        previous_cell = trail[-2]
        counts = Counter(trail)
        repeat_hits = sum(max(0, count - 1) for count in counts.values())
        loop_pressure = max(0.0, min(1.0, repeat_hits / max(1.0, float(len(trail) - 1))))

        known_count = 0
        for cell in trail:
            if fully_known_fn(cell) or max(0, int(unknown_neighbor_count_fn(cell))) == 0:
                known_count += 1
        seen_ratio = max(0.0, min(1.0, known_count / max(1.0, float(len(trail)))))

        raw_penalty = 0.0
        if candidate == previous_cell:
            raw_penalty += 8.0 + (12.0 * loop_pressure)
        if candidate in trail[:-1]:
            raw_penalty += 4.0 + (8.0 * loop_pressure)
        if candidate in trail and max(0, int(candidate_unknown_neighbors)) == 0:
            raw_penalty += 3.0 * (0.5 + seen_ratio)

        backward_penalty = max(
            0,
            int(round(raw_penalty * max(0.0, float(self.config.backtrace_penalty_weight)))),
        )

        escape_raw = 0.0
        frontier_improves = (
            max(0, int(candidate_frontier_distance)) < max(0, int(origin_frontier_distance))
        )
        if candidate not in trail:
            if max(0, int(candidate_unknown_neighbors)) > 0 or frontier_improves:
                escape_raw += 5.0 + (6.0 * loop_pressure)
            elif loop_pressure >= 0.4:
                escape_raw += 3.0

        backward_escape_bonus = max(
            0,
            int(round(escape_raw * max(0.0, float(self.config.backtrace_escape_weight)))),
        )

        return backward_penalty, backward_escape_bonus, loop_pressure, seen_ratio
