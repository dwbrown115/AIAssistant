"""Shared type aliases and enums for the maze package."""
from __future__ import annotations

from enum import Enum, auto
from typing import Literal, Tuple

# ---------------------------------------------------------------------------
# Primitive aliases
# ---------------------------------------------------------------------------

Direction = Literal["UP", "RIGHT", "DOWN", "LEFT"]
Action = Literal["UP", "RIGHT", "DOWN", "LEFT"]
Position = Tuple[int, int]

ALL_DIRECTIONS: tuple[Direction, ...] = ("UP", "RIGHT", "DOWN", "LEFT")

DIRECTION_OFFSETS: dict[str, tuple[int, int]] = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}

OPPOSITE: dict[str, str] = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}


# ---------------------------------------------------------------------------
# Cell classification
# ---------------------------------------------------------------------------


class CellType(Enum):
    """What the agent knows about a cell in the grid."""

    UNKNOWN = auto()   # never observed
    WALL = auto()      # impassable
    OPEN = auto()      # visited / known-passable
    FRONTIER = auto()  # borders explored space but not yet entered
    START = auto()
    END = auto()


class StructuralRole(Enum):
    """Structural role derived from local topology of a known cell."""

    CORRIDOR = auto()   # exactly 2 traversable neighbours, collinear (straight hallway)
    CORNER = auto()     # exactly 2 traversable neighbours, non-collinear (L-turn)
    JUNCTION = auto()   # 3 or more traversable neighbours (branching point)
    DEAD_END = auto()   # exactly 1 traversable neighbour
    ISOLATED = auto()   # 0 traversable neighbours (should not normally occur)
    UNKNOWN = auto()    # cell not yet analysed


# ---------------------------------------------------------------------------
# Mode / policy labels
# ---------------------------------------------------------------------------


class AgentMode(Enum):
    """High-level execution mode chosen by the executive layer."""

    EXPLORE_FRONTIER = auto()    # seek new cells
    ESCAPE_CORRIDOR = auto()     # break out of a detected loop / hallway
    GOAL_DIRECTED = auto()       # navigate toward a known goal


class VetoReason(Enum):
    """Why the veto layer rejected an action."""

    WALL = auto()
    KNOWN_TRAP = auto()
    CORRIDOR_OVERUSE = auto()
    CYCLE_DETECTED = auto()
    DEAD_END_REVISIT = auto()
