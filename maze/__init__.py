"""
maze — modular maze-solving architecture.

Package structure
-----------------
types.py          : shared enums and type aliases (CellType, StructuralRole, AgentMode, …)
world_model.py    : WorldModel + LocalView  — canonical map and structural labels
frontier_memory.py: FrontierManager + MotifMemory — frontier tracking and episodic patterns
controller.py     : VetoLayer + PolicyCore + AgentController — three-layer decision stack
runner.py         : MazeAgent — single public entry point for app.py integration

Quick start
-----------
    from maze.runner import MazeAgent, CandidateInput

    agent = MazeAgent(grid_size=grid_cells)

    # Each exploration step:
    out = agent.step(
        player_pos=current_player_cell,
        facing=player_facing,
        step=memory_step_index,
        known_cells=maze_known_cells,
        wall_cells=blocked_cells,
        visit_counts=episode_visited_cells,
        candidates=[CandidateInput(action=m, next_pos=n) for m, n in legal_moves],
    )
    chosen_move = out.action

For the complete integration recipe, see ``maze/runner.py`` module docstring.
"""

from maze.runner import CandidateInput, MazeAgent, StepOutput
from maze.types import AgentMode, CellType, Direction, Position, StructuralRole, VetoReason
from maze.world_model import LocalView, WorldModel
from maze.frontier_memory import FrontierManager, MotifMemory
from maze.controller import AgentController, PolicyCore, VetoLayer

__all__ = [
    # Runner (main public API)
    "MazeAgent",
    "CandidateInput",
    "StepOutput",
    # Types
    "AgentMode",
    "CellType",
    "Direction",
    "Position",
    "StructuralRole",
    "VetoReason",
    # World model
    "LocalView",
    "WorldModel",
    # Frontier / memory
    "FrontierManager",
    "MotifMemory",
    # Controller layers
    "AgentController",
    "PolicyCore",
    "VetoLayer",
]
