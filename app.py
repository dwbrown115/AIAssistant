import os
import threading
import tkinter as tk
import json
import math
import random
import re
import sqlite3
from collections import deque
from tkinter import scrolledtext

from dotenv import load_dotenv
from openai import OpenAI
from organism_control import (
    CandidateProjection,
    ControlState as OrganismControlState,
    EndocrineState as OrganismEndocrineState,
    Event as OrganismEvent,
    GridState as OrganismGridState,
    MemoryState as OrganismMemoryState,
    Signature as OrganismSignature,
    is_catastrophic_trap as organism_is_catastrophic_trap,
    step_agent as organism_step_agent,
)
from maze.runner import CandidateInput, MazeAgent, StepOutput as MazeStepOutput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env.secret"), override=True)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(OPENAI_API_KEY\s*=\s*)([^\s]+)"), r"\1[REDACTED_API_KEY]"),
    (re.compile(r"(Authorization:\s*Bearer\s+)([^\s]+)", flags=re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
)

_PREDICTION_SHAPE_LABELS: tuple[str, ...] = ("wall", "dead_end", "corridor", "corner", "junction")


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class Hormone:
    def __init__(self, value: float = 0.0, decay: float = 0.95, min_val: float = 0.0, max_val: float = 1.0) -> None:
        self.value = float(value)
        self.decay = float(decay)
        self.min_val = float(min_val)
        self.max_val = float(max_val)

    def update(self, delta: float) -> None:
        self.value = max(self.min_val, min(self.max_val, self.value + float(delta)))

    def tick(self) -> None:
        self.value = max(self.min_val, min(self.max_val, self.value * self.decay))


class EndocrineSystem:
    """Slow global modulators that bias move selection and memory behavior."""

    def __init__(self) -> None:
        self.stress = Hormone(value=0.2, decay=float(os.getenv("HORMONE_STRESS_DECAY", "0.90")))
        self.curiosity = Hormone(value=0.35, decay=float(os.getenv("HORMONE_CURIOSITY_DECAY", "0.97")))
        self.confidence = Hormone(value=0.30, decay=float(os.getenv("HORMONE_CONFIDENCE_DECAY", "0.96")))
        self.fatigue = Hormone(value=0.15, decay=float(os.getenv("HORMONE_FATIGUE_DECAY", "0.98")))
        self.reward = Hormone(value=0.20, decay=float(os.getenv("HORMONE_REWARD_DECAY", "0.95")))
        self._last_decay_step = -1
        self._last_signature_step = -1

    def tick(self, step_index: int) -> None:
        if int(step_index) == self._last_decay_step:
            return
        self._last_decay_step = int(step_index)
        for hormone in [self.stress, self.curiosity, self.confidence, self.fatigue, self.reward]:
            hormone.tick()

    def update_from_signature(self, signature: dict, step_index: int) -> None:
        if int(step_index) == self._last_signature_step:
            return
        self._last_signature_step = int(step_index)

        dead_end_risk = int(signature.get("dead_end_risk", 0) or 0)
        dead_end_depth = int(signature.get("dead_end_risk_depth", 0) or 0)
        unknown_neighbors = int(signature.get("unknown_neighbors", 0) or 0)
        frontier_distance = int(signature.get("frontier_distance", 0) or 0)
        visit_bucket = int(signature.get("visit_bucket", 0) or 0)
        recent_backtrack = int(signature.get("recent_backtrack", 0) or 0)
        transition_pressure = int(signature.get("transition_pressure_bucket", 0) or 0)
        risky_branches = int(signature.get("visible_risky_branches", 0) or 0)

        stress_delta = (
            (dead_end_risk * 0.035)
            + (min(6, dead_end_depth) * 0.015)
            + (transition_pressure * 0.03)
            + (recent_backtrack * 0.03)
            + (risky_branches * 0.02)
        )
        if unknown_neighbors == 0:
            stress_delta += 0.02
        if frontier_distance >= 3:
            stress_delta += 0.02
        self.stress.update(stress_delta)

        curiosity_delta = (unknown_neighbors * 0.05)
        if frontier_distance <= 1:
            curiosity_delta += 0.04
        if risky_branches == 0 and unknown_neighbors == 0:
            curiosity_delta -= 0.03
        self.curiosity.update(curiosity_delta)

        fatigue_delta = (visit_bucket * 0.03) + (transition_pressure * 0.035) + (recent_backtrack * 0.04)
        if unknown_neighbors == 0:
            fatigue_delta += 0.02
        self.fatigue.update(fatigue_delta)

        confidence_delta = 0.0
        if dead_end_risk == 0 and unknown_neighbors > 0 and visit_bucket <= 1:
            confidence_delta += 0.03
        if dead_end_risk >= 2 or recent_backtrack > 0:
            confidence_delta -= 0.03
        self.confidence.update(confidence_delta)

        reward_delta = 0.0
        if frontier_distance <= 1:
            reward_delta += 0.025
        if unknown_neighbors >= 2:
            reward_delta += 0.03
        if transition_pressure >= 2:
            reward_delta -= 0.02
        self.reward.update(reward_delta)

    def update_from_outcome(self, outcome_value: float, reward_signal: float, penalty_signal: float, tags: list[str]) -> None:
        outcome = float(outcome_value)
        reward = max(0.0, float(reward_signal))
        penalty = max(0.0, float(penalty_signal))
        tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}

        if reward > 0.0 or outcome > 0.0:
            self.reward.update(0.06 + min(0.18, reward / 300.0))
            self.confidence.update(0.04 + min(0.12, max(0.0, outcome) / 400.0))
            self.stress.update(-0.05)
            self.fatigue.update(-0.03)
            if "novelty_reward" in tag_set or "frontier_visible" in tag_set:
                self.curiosity.update(0.03)
        elif penalty > 0.0 or outcome < 0.0:
            self.stress.update(0.06 + min(0.24, penalty / 260.0))
            self.fatigue.update(0.05 + min(0.18, penalty / 300.0))
            self.confidence.update(-(0.05 + min(0.15, penalty / 320.0)))
            self.reward.update(-0.04)
            if "cycle_pair" in tag_set or "transition_repeat" in tag_set:
                self.curiosity.update(-0.03)

    def state(self) -> dict[str, float]:
        return {
            "stress": round(self.stress.value, 4),
            "curiosity": round(self.curiosity.value, 4),
            "confidence": round(self.confidence.value, 4),
            "fatigue": round(self.fatigue.value, 4),
            "reward": round(self.reward.value, 4),
        }

    def neural_state(self) -> dict[str, float]:
        exploration_drive = (self.curiosity.value + self.reward.value) - self.fatigue.value
        risk_aversion = self.stress.value - self.confidence.value
        momentum = (self.reward.value + self.confidence.value) - (0.5 * self.stress.value)
        return {
            "exploration_drive": round(exploration_drive, 4),
            "risk_aversion": round(risk_aversion, 4),
            "momentum": round(momentum, 4),
        }


class AIAssistantApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI Assistant")
        self.default_geometry = "820x620"
        self.window_state_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".window_state.json",
        )
        self._geometry_save_after_id = None
        self._saved_sash_x = None
        self.memory_db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "maze_memory.sqlite3",
        )
        self.root.geometry(self.default_geometry)
        self.root.minsize(680, 520)

        self.client = None
        self.logic_model = os.getenv("OPENAI_LOGIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
        self.agent_model = os.getenv("OPENAI_AGENT_MODEL", "gpt-4o-mini")
        self.local_navigation_kernel = os.getenv("LOCAL_NAVIGATION_KERNEL", "1") == "1"
        self.local_navigation_api_fallback = os.getenv("LOCAL_NAVIGATION_API_FALLBACK", "1") == "1"
        self.enable_logic_repetition_resolver = os.getenv("ENABLE_LOGIC_REPETITION_RESOLVER", "0") == "1"
        self.enable_logic_finalizer_for_navigation = os.getenv("ENABLE_LOGIC_FINALIZER_FOR_NAVIGATION", "0") == "1"
        self.maze_step_model_hints = os.getenv("MAZE_STEP_MODEL_HINTS", "0") == "1"
        self.maze_targeted_model_assist_enable = os.getenv("MAZE_TARGETED_MODEL_ASSIST_ENABLE", "1") == "1"
        self.maze_model_assist_reliance = min(
            1.0,
            max(0.0, float(os.getenv("MAZE_MODEL_ASSIST_RELIANCE", "0.22"))),
        )
        self.maze_model_assist_max_calls_per_episode = max(
            0,
            int(os.getenv("MAZE_MODEL_ASSIST_MAX_CALLS_PER_EPISODE", "6")),
        )
        self.maze_model_assist_cooldown_steps = max(
            0,
            int(os.getenv("MAZE_MODEL_ASSIST_COOLDOWN_STEPS", "10")),
        )

        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.client = OpenAI(api_key=api_key)

        self.status_var = tk.StringVar(value="Ready")
        self.score_var = tk.StringVar(value="Targets reached: 0")
        self.targets_reached = 0
        self.total_reward = 0.0
        self.episode_steps = 0
        self.episode_optimal_steps = 0
        self.episode_step_limit = 0
        self.episode_start_player_cell = (0, 0)
        self.current_target_cell = (0, 0)
        self.current_player_cell = (0, 0)
        self._sticky_objective_target: tuple[int, int] | None = None
        self._sticky_objective_path: list[str] = []
        self.auto_goal_hits_remaining = 0
        self.goal_session_active = False
        self.goal_session_start_hits = 0
        self.goal_session_target_hits = 0
        self.last_manhattan_distance = 0
        self.episode_revisit_steps = 0
        self.episode_backtracks = 0
        self.episode_visited_cells: dict[tuple[int, int], int] = {}
        self.prev_player_cell = (0, 0)
        self.prev_prev_player_cell = (0, 0)

        self.canvas_width = 360
        self.canvas_height = 360
        self.enable_pseudo3d_view = os.getenv("ENABLE_PSEUDO3D_VIEW", "0") == "1"
        self.pseudo3d_width = 360
        self.pseudo3d_height = 220
        self.pseudo3d_max_depth = max(2, int(os.getenv("PSEUDO3D_MAX_DEPTH", "5")))
        self.grid_cells = 8
        self.cell_size = self.canvas_width // self.grid_cells
        self.player_size = 24
        self.target_radius = 12
        self.player_speed = self.cell_size
        self.blocker_density = float(os.getenv("BLOCKER_DENSITY", "0.18"))
        self.blocked_cells: set[tuple[int, int]] = set()
        self.layout_mode = tk.StringVar(value="grid")
        self.maze_difficulty = tk.StringVar(value="medium")
        self.maze_seed_base = int(os.getenv("MAZE_SEED", "1337"))
        self.target_distance_min_ratio = float(os.getenv("TARGET_DISTANCE_MIN_RATIO", "0.75"))
        self.target_distance_max_ratio = float(os.getenv("TARGET_DISTANCE_MAX_RATIO", "1.0"))
        self.maze_fov_depth = int(os.getenv("MAZE_FOV_DEPTH", "4"))
        self.maze_fov_peripheral = int(os.getenv("MAZE_FOV_PERIPHERAL", "1"))
        self.maze_fov_cone_degrees = float(os.getenv("MAZE_FOV_CONE_DEGREES", "95"))
        self.maze_fov_full_threshold = float(os.getenv("MAZE_FOV_FULL_THRESHOLD", "0.22"))
        self.maze_fov_half_threshold = float(os.getenv("MAZE_FOV_HALF_THRESHOLD", "0.08"))
        self.maze_fov_distance_falloff = float(os.getenv("MAZE_FOV_DISTANCE_FALLOFF", "0.22"))
        self.maze_fov_corner_graze_factor = float(os.getenv("MAZE_FOV_CORNER_GRAZE_FACTOR", "0.62"))
        self.maze_fov_wedge_distance_scale = float(os.getenv("MAZE_FOV_WEDGE_DISTANCE_SCALE", "0.2"))
        if self.maze_fov_half_threshold > self.maze_fov_full_threshold:
            self.maze_fov_half_threshold = self.maze_fov_full_threshold
        self.layout_generation_index = 0
        self.layout_event_index = 0
        self.maze_map_start_var = tk.StringVar(value="0")
        self.memory_run_id_var = tk.StringVar(value="")
        self.current_maze_algorithm = ""
        self.player_facing = "UP"
        self.current_maze_episode_id = 0
        self.maze_known_cells: dict[tuple[int, int], str] = {}
        self.prediction_contradiction_debt: dict[tuple[int, int], float] = {}
        self.prediction_context_contradiction_debt: dict[str, float] = {}
        self.mental_sweep_cells: dict[tuple[int, int], str] = {}
        self._last_saved_structural_signature = ""
        self._last_saved_layout_cell_signature = ""
        self.layout_recall_last_map_id = -1
        self.layout_recall_last_restored = 0
        self.layout_recall_last_total = 0
        self.layout_recall_last_rejected = 0
        self.layout_recall_last_source = "none"
        self.layout_recall_mutation_chance = min(
            1.0,
            max(0.0, float(os.getenv("LAYOUT_RECALL_MUTATION_CHANCE", "0.03"))),
        )
        self.layout_recall_mutation_decay_steps = max(
            1,
            int(os.getenv("LAYOUT_RECALL_MUTATION_DECAY_STEPS", "18")),
        )
        self.working_memory_active: dict[str, str] = {}
        self.working_memory_look_sweep: dict[str, dict[str, str]] = {}
        self.working_memory_look_sweep_step = -1
        self.working_memory_look_retention_steps = max(0, int(os.getenv("WORKING_MEMORY_LOOK_RETENTION_STEPS", "10")))
        self.working_memory_look_history: deque[dict[str, object]] = deque(
            maxlen=max(1, int(os.getenv("WORKING_MEMORY_LOOK_RETENTION_LIMIT", "8")))
        )
        self._semantic_reinforce_recent: dict[str, int] = {}
        self.working_memory_recent_signatures: deque[str] = deque(maxlen=24)
        self._last_wm_signature_logged = ""
        self._last_wm_signature_logged_step = -1
        self.stm_familiar_resample_interval = int(os.getenv("STM_FAMILIAR_RESAMPLE_INTERVAL", "12"))
        self.cause_effect_vector_dim = max(12, int(os.getenv("CAUSE_EFFECT_VECTOR_DIM", "24")))
        self.cause_effect_retrieval_top_k = max(1, int(os.getenv("CAUSE_EFFECT_RETRIEVAL_TOP_K", "6")))
        self.cause_effect_retrieval_min_similarity = float(os.getenv("CAUSE_EFFECT_RETRIEVAL_MIN_SIMILARITY", "0.22"))
        self.cause_effect_memory_weight = float(os.getenv("CAUSE_EFFECT_MEMORY_WEIGHT", "0.4"))
        authority_mode_raw = os.getenv("LOCAL_MAP_AUTHORITY_MODE", "strict").strip().lower()
        self.local_map_authority_mode = authority_mode_raw if authority_mode_raw in {"strict", "soft"} else "strict"
        self.strict_authority_risk_memory_min_scale = min(
            1.0,
            max(0.0, float(os.getenv("STRICT_AUTHORITY_RISK_MEMORY_MIN_SCALE", "0.45"))),
        )
        self.local_map_authority_soft_scale = min(
            1.0,
            max(0.0, float(os.getenv("LOCAL_MAP_AUTHORITY_SOFT_SCALE", "0.35"))),
        )
        self.prediction_prior_blend = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_PRIOR_BLEND", str(self.local_map_authority_soft_scale)))),
        )
        self.prediction_reward_correct = float(os.getenv("PREDICTION_REWARD_CORRECT", "4.0"))
        self.prediction_reward_wrong_learning = float(os.getenv("PREDICTION_WRONG_LEARNING_REWARD", "0.8"))
        self.prediction_wrong_learning_credit_scale = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_WRONG_LEARNING_CREDIT_SCALE", "0.15"))),
        )
        self.prediction_wrong_occupancy_penalty = max(
            0.0,
            float(os.getenv("PREDICTION_WRONG_OCCUPANCY_PENALTY", "2.4")),
        )
        self.prediction_wrong_shape_penalty = max(
            0.0,
            float(os.getenv("PREDICTION_WRONG_SHAPE_PENALTY", "1.6")),
        )
        self.prediction_confident_wrong_penalty = float(os.getenv("PREDICTION_CONFIDENT_WRONG_PENALTY", "2.2"))
        self.prediction_confident_threshold = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_CONFIDENT_THRESHOLD", "0.72"))),
        )
        self.prediction_confidence_buckets = max(
            3,
            min(10, int(os.getenv("PREDICTION_CONFIDENCE_BUCKETS", "5"))),
        )
        self.prediction_context_confidence_blend = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_CONTEXT_CONFIDENCE_BLEND", "0.28"))),
        )
        self.prediction_context_min_support = max(
            1,
            int(os.getenv("PREDICTION_CONTEXT_MIN_SUPPORT", "8")),
        )
        self.prediction_planning_min_conf = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_PLANNING_MIN_CONF", "0.12"))),
        )
        self.prediction_context_trust_low_shape_acc = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_CONTEXT_TRUST_LOW_SHAPE_ACC", "0.20"))),
        )
        self.prediction_context_trust_high_shape_acc = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_CONTEXT_TRUST_HIGH_SHAPE_ACC", "0.75"))),
        )
        if self.prediction_context_trust_high_shape_acc < self.prediction_context_trust_low_shape_acc:
            self.prediction_context_trust_high_shape_acc = self.prediction_context_trust_low_shape_acc
        self.prediction_occupancy_score_weight = max(
            0.0,
            float(os.getenv("PREDICTION_OCCUPANCY_SCORE_WEIGHT", "1.0")),
        )
        self.prediction_shape_score_weight = max(
            0.0,
            float(os.getenv("PREDICTION_SHAPE_SCORE_WEIGHT", "0.65")),
        )
        self.prediction_shape_require_observability = os.getenv("PREDICTION_SHAPE_REQUIRE_OBSERVABILITY", "1") == "1"
        self.prediction_shape_observability_min_neighbors = max(
            1,
            min(4, int(os.getenv("PREDICTION_SHAPE_OBSERVABILITY_MIN_NEIGHBORS", "3"))),
        )
        self.prediction_lookahead_enable = os.getenv("PREDICTION_LOOKAHEAD_ENABLE", "1") == "1"
        self.prediction_lookahead_discount = min(
            1.0,
            max(0.0, float(os.getenv("PREDICTION_LOOKAHEAD_DISCOUNT", "0.4"))),
        )
        self.prediction_lookahead_weight = max(
            0.0,
            float(os.getenv("PREDICTION_LOOKAHEAD_WEIGHT", "1.0")),
        )
        self.prediction_memory_active: dict[tuple[int, int], dict[str, object]] = {}
        self.prediction_junction_bias_weight = max(
            0.0,
            float(os.getenv("PREDICTION_JUNCTION_BIAS_WEIGHT", "14.0")),
        )
        self.prediction_dead_end_bias_weight = max(
            0.0,
            float(os.getenv("PREDICTION_DEAD_END_BIAS_WEIGHT", "12.0")),
        )
        self.prediction_recent_results: deque[dict[str, object]] = deque(maxlen=80)
        self.prediction_score_total = 0.0
        self.prediction_score_current_maze = 0.0
        self.prediction_resolved_count = 0
        self.prediction_correct_count = 0
        self.prediction_shape_correct_count = 0
        self.prediction_shape_scored_count = 0
        self.prediction_fully_correct_count = 0
        self.prediction_expired_count = 0
        self.prediction_occupancy_brier_total = 0.0
        self.prediction_shape_brier_total = 0.0
        self._prediction_context_stats_cache: dict[str, dict[str, float]] = {}
        self._prediction_context_trust_cache: dict[str, float] = {}
        self.endocrine_enabled = os.getenv("ENDOCRINE_ENABLE", "1") == "1"
        self.endocrine = EndocrineSystem()
        self.endocrine_stress_danger_weight = float(os.getenv("ENDOCRINE_STRESS_DANGER_WEIGHT", "18.0"))
        self.endocrine_curiosity_novelty_weight = float(os.getenv("ENDOCRINE_CURIOSITY_NOVELTY_WEIGHT", "14.0"))
        self.endocrine_fatigue_repeat_weight = float(os.getenv("ENDOCRINE_FATIGUE_REPEAT_WEIGHT", "10.0"))
        self.endocrine_confidence_risk_bonus = float(os.getenv("ENDOCRINE_CONFIDENCE_RISK_BONUS", "8.0"))
        self.endocrine_momentum_bonus_weight = float(os.getenv("ENDOCRINE_MOMENTUM_BONUS_WEIGHT", "6.0"))
        self.endocrine_event_log: deque[str] = deque(maxlen=160)
        self._last_endocrine_trace_step = -1
        self.organism_control_enable = os.getenv("ORGANISM_CONTROL_ENABLE", "1") == "1"
        self.organism_recent_window = max(6, int(os.getenv("ORGANISM_RECENT_WINDOW", "10")))
        self.organism_memory_state = OrganismMemoryState()
        self.organism_endocrine_state = OrganismEndocrineState()
        self.organism_control_state = OrganismControlState()
        self.organism_last_step_debug = ""
        self.maze_agent_enable = os.getenv("MAZE_AGENT_ENABLE", "1") == "1"
        self.maze_agent_cycle_taboo_duration = max(4, int(os.getenv("MAZE_AGENT_CYCLE_TABOO_DURATION", "12")))
        self.maze_agent_corridor_escape_threshold = max(2, int(os.getenv("MAZE_AGENT_CORRIDOR_ESCAPE_THRESHOLD", "5")))
        self.maze_agent_escape_timeout = max(4, int(os.getenv("MAZE_AGENT_ESCAPE_TIMEOUT", "14")))
        self.maze_agent_escape_exit_pressure = max(0.0, float(os.getenv("MAZE_AGENT_ESCAPE_EXIT_PRESSURE", "0.25")))
        self.maze_agent_corridor_overuse_threshold = max(0.1, float(os.getenv("MAZE_AGENT_CORRIDOR_OVERUSE_THRESHOLD", "0.55")))
        self.maze_agent_novelty_weight = max(0.0, float(os.getenv("MAZE_AGENT_NOVELTY_WEIGHT", "2.0")))
        self.maze_agent_frontier_weight = max(0.0, float(os.getenv("MAZE_AGENT_FRONTIER_WEIGHT", "3.0")))
        self.maze_agent_junction_bonus = max(0.0, float(os.getenv("MAZE_AGENT_JUNCTION_BONUS", "1.5")))
        self.maze_agent_corridor_overuse_penalty = max(0.0, float(os.getenv("MAZE_AGENT_CORRIDOR_OVERUSE_PENALTY", "4.0")))
        self.maze_agent_dead_end_penalty = max(0.0, float(os.getenv("MAZE_AGENT_DEAD_END_PENALTY", "2.0")))
        self.maze_agent_motif_weight = max(0.0, float(os.getenv("MAZE_AGENT_MOTIF_WEIGHT", "1.0")))
        self.maze_agent_loop_risk_weight = max(0.0, float(os.getenv("MAZE_AGENT_LOOP_RISK_WEIGHT", "3.0")))
        self.maze_agent_corridor_forward_bias = max(0.0, float(os.getenv("MAZE_AGENT_CORRIDOR_FORWARD_BIAS", "1.2")))
        self.maze_agent_side_open_bias = max(0.0, float(os.getenv("MAZE_AGENT_SIDE_OPEN_BIAS", "0.8")))
        self.maze_agent = self._build_maze_agent()
        self.bio_nav_enable = os.getenv("BIO_NAV_ENABLE", "1") == "1"
        self.bio_nav_opening_weight = max(0, int(os.getenv("BIO_NAV_OPENING_WEIGHT", "18")))
        self.bio_nav_dead_end_escape_weight = max(0, int(os.getenv("BIO_NAV_DEAD_END_ESCAPE_WEIGHT", "24")))
        self.bio_nav_novelty_scale = max(0.0, float(os.getenv("BIO_NAV_NOVELTY_SCALE", "2.0")))
        self.bio_nav_corridor_flow_weight = max(0, int(os.getenv("BIO_NAV_CORRIDOR_FLOW_WEIGHT", "8")))
        self.bio_nav_dead_end_predictive_penalty = max(
            0, int(os.getenv("BIO_NAV_DEAD_END_PREDICTIVE_PENALTY", "16"))
        )
        self.bio_nav_loop_risk_penalty = max(0, int(os.getenv("BIO_NAV_LOOP_RISK_PENALTY", "12")))
        self.memory_event_log: deque[str] = deque(maxlen=1200)
        self.memory_export_section_limit = max(1, int(os.getenv("MEMORY_EXPORT_SECTION_LIMIT", "6")))
        self.memory_export_log_limit = max(20, int(os.getenv("MEMORY_EXPORT_LOG_LIMIT", "240")))
        self.memory_export_debug_limit = max(20, int(os.getenv("MEMORY_EXPORT_DEBUG_LIMIT", "180")))
        self.memory_export_ascii_max_lines = max(6, int(os.getenv("MEMORY_EXPORT_ASCII_MAX_LINES", "12")))
        self.memory_export_strip_look_sections = os.getenv("MEMORY_EXPORT_STRIP_LOOK_SECTIONS", "1") == "1"
        self.memory_step_index = 0
        self.stm_reinforce_alpha = float(os.getenv("STM_REINFORCE_ALPHA", "0.2"))
        self.stm_decay_rate = float(os.getenv("STM_DECAY_RATE", "0.97"))
        self.stm_prune_threshold = float(os.getenv("STM_PRUNE_THRESHOLD", "0.15"))
        self.semantic_promotion_threshold = float(os.getenv("SEMANTIC_PROMOTION_THRESHOLD", "1.2"))
        self.stm_pruning_interval_steps = max(1, int(os.getenv("STM_PRUNING_INTERVAL_STEPS", "6")))
        self.stm_access_unused_prune_chance = min(
            1.0,
            max(0.0, float(os.getenv("STM_ACCESS_UNUSED_PRUNE_CHANCE", "0.04"))),
        )
        self.stm_access_unused_prune_min_age_steps = max(
            1,
            int(os.getenv("STM_ACCESS_UNUSED_PRUNE_MIN_AGE_STEPS", "24")),
        )
        self.stm_access_unused_prune_max_rows = max(
            1,
            int(os.getenv("STM_ACCESS_UNUSED_PRUNE_MAX_ROWS", "1")),
        )
        self._last_stm_pruning_step = -10_000
        self.maze_recent_cells: deque[tuple[int, int]] = deque(maxlen=18)
        self.reset_epoch = 0
        self.step_limit_reset_count = 0
        self._last_step_reset_memory_step = 0
        self.same_maze_retry_count = 0
        self._same_maze_retry_last_step = -1
        self._same_maze_retry_frontier_target: tuple[int, int] | None = None
        self._post_reset_exhausted_cells: set[tuple[int, int]] = set()
        self._post_reset_exhausted_transitions: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        self._post_reset_cell_failure_counts: dict[tuple[int, int], int] = {}
        self._post_reset_transition_failure_counts: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
        self._post_reset_transition_success_counts: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
        self._cell_visit_reset_epoch: dict[tuple[int, int], int] = {}
        self._reset_trace_window = max(16, int(os.getenv("RESET_TRACE_WINDOW", "48")))
        self._reset_trace: deque[dict[str, object]] = deque(maxlen=self._reset_trace_window)
        self._persistent_frontier_target: tuple[int, int] | None = None
        self.post_reset_exhaustion_penalty = int(os.getenv("POST_RESET_EXHAUSTION_PENALTY", "120"))
        self.reset_failure_transition_penalty = int(os.getenv("RESET_FAILURE_TRANSITION_PENALTY", "24"))
        self.reset_failure_cell_penalty = int(os.getenv("RESET_FAILURE_CELL_PENALTY", "16"))
        self.reset_success_transition_bonus = int(os.getenv("RESET_SUCCESS_TRANSITION_BONUS", "10"))
        self.post_reset_stm_relax_steps = max(0, int(os.getenv("POST_RESET_STM_RELAX_STEPS", "24")))
        self._post_reset_stm_relax_remaining = 0
        self.frontier_lock_unknown_threshold = max(0, int(os.getenv("FRONTIER_LOCK_UNKNOWN_THRESHOLD", "3")))
        self.frontier_lock_frontier_threshold = max(0, int(os.getenv("FRONTIER_LOCK_FRONTIER_THRESHOLD", "2")))
        self.frontier_lock_retry_bonus = max(0, int(os.getenv("FRONTIER_LOCK_RETRY_BONUS", "50")))
        self.frontier_lock_loop_penalty = max(0, int(os.getenv("FRONTIER_LOCK_LOOP_PENALTY", "50")))
        self.solved_region_penalty = max(0, int(os.getenv("SOLVED_REGION_PENALTY", "500")))
        self.loop_entropy_window = max(4, int(os.getenv("LOOP_ENTROPY_WINDOW", "8")))
        self.loop_entropy_threshold = max(0.0, float(os.getenv("LOOP_ENTROPY_THRESHOLD", "1.2")))
        self.recent_forced_corridor_cells: deque[tuple[int, int]] = deque(
            maxlen=max(4, int(os.getenv("FORCED_CORRIDOR_MEMORY_WINDOW", "6")))
        )
        self.recent_cycle_window = max(6, int(os.getenv("RECENT_CYCLE_WINDOW", "12")))
        self.cycle_transition_penalty_weight = float(os.getenv("CYCLE_TRANSITION_PENALTY_WEIGHT", "26.0"))
        self.cycle_pair_penalty_weight = float(os.getenv("CYCLE_PAIR_PENALTY_WEIGHT", "34.0"))
        self.cycle_guard_score_margin = int(os.getenv("CYCLE_GUARD_SCORE_MARGIN", "10"))
        self.visible_terminal_end_penalty = int(os.getenv("VISIBLE_TERMINAL_END_PENALTY", "40"))
        self.terminal_end_guard_margin = int(os.getenv("TERMINAL_END_GUARD_MARGIN", "8"))
        self.terminal_end_hard_avoid = os.getenv("TERMINAL_END_HARD_AVOID", "1") == "1"
        self.boxed_corridor_no_exit_penalty = int(os.getenv("BOXED_CORRIDOR_NO_EXIT_PENALTY", "60"))
        self.visible_exit_corridor_reward = int(os.getenv("VISIBLE_EXIT_CORRIDOR_REWARD", "42"))
        self.frontier_override_score_margin = int(os.getenv("FRONTIER_OVERRIDE_SCORE_MARGIN", "6"))
        self.no_progress_repeat_penalty = int(os.getenv("NO_PROGRESS_REPEAT_PENALTY", "22"))
        self.loop_commitment_penalty = int(os.getenv("LOOP_COMMITMENT_PENALTY", "28"))
        self.immediate_backtrack_hard_penalty = int(os.getenv("IMMEDIATE_BACKTRACK_HARD_PENALTY", "52"))
        self.transition_pressure_repeat_penalty_weight = int(
            os.getenv("TRANSITION_PRESSURE_REPEAT_PENALTY_WEIGHT", "9")
        )
        self.escape_bias_bonus = int(os.getenv("ESCAPE_BIAS_BONUS", "18"))
        self.forced_corridor_reentry_penalty = int(os.getenv("FORCED_CORRIDOR_REENTRY_PENALTY", "28"))
        self.trap_context_cause_effect_penalty_scale = float(
            os.getenv("TRAP_CAUSE_EFFECT_PENALTY_SCALE", "1.7")
        )
        self.cycle_taboo_threshold = max(2, int(os.getenv("CYCLE_TABOO_THRESHOLD", "2")))
        self.cycle_taboo_duration_steps = max(4, int(os.getenv("CYCLE_TABOO_DURATION_STEPS", "18")))
        self.terminal_corridor_hard_veto_penalty = int(
            os.getenv("TERMINAL_CORRIDOR_HARD_VETO_PENALTY", "220")
        )
        self.high_risk_frontier_override_bonus = int(
            os.getenv("HIGH_RISK_FRONTIER_OVERRIDE_BONUS", "26")
        )
        self.maze_step_limit_reset_enable = os.getenv("MAZE_STEP_LIMIT_RESET_ENABLE", "1") == "1"
        self.branch_tightening_abort_threshold = max(
            2, int(os.getenv("BRANCH_TIGHTENING_ABORT_THRESHOLD", "6"))
        )
        self.branch_tightening_abort_penalty = max(
            0, int(os.getenv("BRANCH_TIGHTENING_ABORT_PENALTY", "240"))
        )
        self.branch_tightening_escape_bonus = max(
            0, int(os.getenv("BRANCH_TIGHTENING_ESCAPE_BONUS", "36"))
        )
        self.branch_recent_frontier_window = max(
            4, int(os.getenv("BRANCH_RECENT_FRONTIER_WINDOW", "10"))
        )
        self.branch_recent_frontier_max_distance = max(
            2, int(os.getenv("BRANCH_RECENT_FRONTIER_MAX_DISTANCE", "4"))
        )
        self.recent_trap_transition_events: deque[tuple[int, tuple[int, int], tuple[int, int]]] = deque(maxlen=24)
        self.taboo_transitions: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
        self.dead_end_end_slap_penalty = float(os.getenv("DEAD_END_END_SLAP_PENALTY", "58.0"))
        self.dead_end_tip_revisit_slap_penalty = float(os.getenv("DEAD_END_TIP_REVISIT_SLAP_PENALTY", "92.0"))
        self.semantic_reinforce_cooldown_steps = max(0, int(os.getenv("SEMANTIC_REINFORCE_COOLDOWN_STEPS", "6")))
        self.tie_random_requires_novel = os.getenv("TIE_RANDOM_REQUIRES_NOVEL", "1") == "1"
        self.maze_recent_transitions: deque[tuple[tuple[int, int], tuple[int, int]]] = deque(
            maxlen=max(24, self.recent_cycle_window * 3)
        )
        self.move_delay_ms = int(os.getenv("GAME_MOVE_DELAY_MS", "250"))
        self.look_preview_delay_ms = int(os.getenv("LOOK_AROUND_PREVIEW_MS", "180"))
        self.player_x = (self.cell_size - self.player_size) // 2
        self.player_y = (self.cell_size - self.player_size) // 2
        self.movement_rules = (
            "Movement rules: The player is a square. Valid moves are UP, DOWN, LEFT, RIGHT. "
            "Each move shifts exactly one grid cell and cannot leave canvas bounds. "
            "Blocked cells are impassable and cannot be entered. "
            "Mode GRID uses low-noise random blockers. Mode MAZE uses deterministic maze algorithms with "
            "difficulty levels (easy/medium/hard). Goal: touch the blue target circle. Reward objective: "
            "maximize efficiency by using the shortest path."
        )
        self.game_state_lock = threading.Lock()
        self.latest_game_state = "Game state not initialized."
        self.pending_agent_moves: list[str] = []
        self.agent_move_animation_active = False
        self.enable_path_fallback = os.getenv("ENABLE_PATH_FALLBACK", "1") == "1"
        self.logic_confidence_threshold = float(os.getenv("LOGIC_CONFIDENCE_THRESHOLD", "0.55"))
        self.repeat_confidence_threshold = float(os.getenv("REPEAT_CONFIDENCE_THRESHOLD", "0.6"))
        self.max_repeat_executions = max(1, min(250, int(os.getenv("MAX_REPEAT_EXECUTIONS", "25"))))
        self.maze_map_doubt_enable = os.getenv("MAZE_MAP_DOUBT_ENABLE", "1") == "1"
        self.maze_map_doubt_repeat_threshold = max(
            2,
            int(os.getenv("MAZE_MAP_DOUBT_REPEAT_THRESHOLD", "3")),
        )
        self.maze_map_doubt_stall_threshold = max(
            1,
            int(os.getenv("MAZE_MAP_DOUBT_STALL_THRESHOLD", "2")),
        )
        self.maze_map_doubt_cooldown_steps = max(
            1,
            int(os.getenv("MAZE_MAP_DOUBT_COOLDOWN_STEPS", "8")),
        )
        self.maze_stuck_reexplore_enable = os.getenv("MAZE_STUCK_REEXPLORE_ENABLE", "1") == "1"
        self.maze_stuck_repeat_threshold = max(
            2,
            int(os.getenv("MAZE_STUCK_REPEAT_THRESHOLD", "3")),
        )
        self.maze_stuck_no_progress_threshold = max(
            2,
            int(os.getenv("MAZE_STUCK_NO_PROGRESS_THRESHOLD", "4")),
        )
        self.maze_stuck_window = max(
            8,
            int(os.getenv("MAZE_STUCK_WINDOW", "18")),
        )
        self.maze_stuck_reexplore_cooldown_steps = max(
            2,
            int(os.getenv("MAZE_STUCK_REEXPLORE_COOLDOWN_STEPS", "10")),
        )
        self.maze_stuck_prediction_conf_floor = min(
            1.0,
            max(0.0, float(os.getenv("MAZE_STUCK_PREDICTION_CONF_FLOOR", "0.08"))),
        )
        self.maze_stuck_prediction_bias_scale = max(
            0.0,
            float(os.getenv("MAZE_STUCK_PREDICTION_BIAS_SCALE", "0.35")),
        )
        self.maze_stuck_transition_repeat_boost = max(
            0.0,
            float(os.getenv("MAZE_STUCK_TRANSITION_REPEAT_BOOST", "24.0")),
        )
        self.maze_stuck_transition_reverse_boost = max(
            0.0,
            float(os.getenv("MAZE_STUCK_TRANSITION_REVERSE_BOOST", "34.0")),
        )
        self.exploration_tie_noise = max(
            0.0,
            float(os.getenv("EXPLORATION_TIE_NOISE", "0.03")),
        )
        self._maze_reexplore_cooldown_remaining = 0
        self._maze_stuck_trigger_count = 0
        self._maze_model_assist_calls_used = 0
        self._maze_model_assist_cooldown_remaining = 0
        # Loop-escape tracking: detect catastrophic penalty spirals
        self._recent_step_penalties = deque(maxlen=6)  # Last 6 step outcomes
        # Pulse set when a step-limit timeout reset occurs; consumed by step loop
        # to clear stale no-progress / stuck-reexplore state for the new attempt.
        self._maze_timeout_reset_pulse = False
        self.max_step_iterations = int(os.getenv("MAX_STEP_ITERATIONS", "240"))
        self.revisit_penalty_weight = float(os.getenv("REVISIT_PENALTY_WEIGHT", "8.0"))
        self.backtrack_penalty_weight = float(os.getenv("BACKTRACK_PENALTY_WEIGHT", "12.0"))
        self.strict_progress_guard = os.getenv("STRICT_PROGRESS_GUARD", "1") == "1"
        # Keep episodic map memory across timeout retries by default for the same maze.
        self.reset_maze_knowledge_on_step_limit = os.getenv("RESET_MAZE_KNOWLEDGE_ON_STEP_LIMIT", "0") == "1"
        self.decision_noise_weight = float(os.getenv("DECISION_NOISE_WEIGHT", "3.0"))
        self.exploration_tie_band = int(os.getenv("EXPLORATION_TIE_BAND", "2"))
        self.exploration_randomize_ties = os.getenv("EXPLORATION_RANDOMIZE_TIES", "1") == "1"
        self.personality_variation_enabled = os.getenv("MAZE_PERSONALITY_VARIATION", "1") == "1"
        self.dead_end_learning_allowance_base = int(os.getenv("DEAD_END_LEARNING_ALLOWANCE", "1"))
        self.shallow_dead_end_penalty_base = float(os.getenv("SHALLOW_DEAD_END_PENALTY_BASE", "18.0"))
        self.dead_end_frontier_distance_scale = float(os.getenv("DEAD_END_FRONTIER_DISTANCE_SCALE", "0.33"))
        self.revisit_dead_end_entrance_penalty = float(os.getenv("REVISIT_DEAD_END_ENTRANCE_PENALTY", "22.0"))
        self.narrow_corridor_penalty = float(os.getenv("NARROW_CORRIDOR_PENALTY", "8.0"))
        self.easy_dead_end_scale = float(os.getenv("EASY_DEAD_END_SCALE", "1.5"))
        self.medium_dead_end_scale = float(os.getenv("MEDIUM_DEAD_END_SCALE", "1.0"))
        self.hard_dead_end_scale = float(os.getenv("HARD_DEAD_END_SCALE", "0.6"))
        self.attempt_dead_end_escalation = float(os.getenv("ATTEMPT_DEAD_END_ESCALATION", "0.18"))
        self._decision_noise_rng = random.Random()
        self._decision_noise_cache: dict[tuple[int, tuple[int, int], str], int] = {}
        self._planner_rng = random.Random()
        self._last_planner_choice_debug = ""
        self._personality_rng = random.Random()
        self.maze_personality_name = "Balanced Mapper"
        self.maze_personality: dict[str, object] = {}
        self.episode_dead_end_learn_events = 0
        self.episode_dead_end_samples: set[tuple[int, int]] = set()
        self.episode_dead_end_entrances: set[tuple[int, int]] = set()
        self.episode_dead_end_tip_cells: set[tuple[int, int]] = set()
        self.episode_maze_attempt_count = 1
        self.last_maze_solve_attempts = 0
        self.last_normalized_goal = ""

        self._init_memory_db()

        self._build_ui()
        self._update_score_label()
        self._restore_window_geometry()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_shutdown)

        if not self.client:
            if self.local_navigation_kernel:
                self.status_var.set("Missing OPENAI_API_KEY; local navigation kernel remains available")
            else:
                self.status_var.set("Missing OPENAI_API_KEY in .env or .env.secret")

    @staticmethod
    def _parse_json_payload(raw_text: str) -> dict:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and start < end:
                text = text[start : end + 1]
        return json.loads(text)

    def _roll_maze_personality(self) -> None:
        base_allowance = max(0, self.dead_end_learning_allowance_base)
        if not self.personality_variation_enabled:
            self.maze_personality_name = "Balanced Mapper"
            self.maze_personality = {
                "dead_end_penalty_scale": 1.0,
                "novelty_reward_scale": 1.0,
                "branch_diversity_scale": 1.0,
                "corridor_penalty_scale": 1.0,
                "dead_end_allowance": base_allowance,
                "direction_bias": {"UP": 0, "DOWN": 0, "LEFT": 0, "RIGHT": 0},
            }
            return

        archetypes = [
            {
                "name": "Curious Scout",
                "dead_end_penalty_scale": 0.85,
                "novelty_reward_scale": 1.25,
                "branch_diversity_scale": 0.9,
                "corridor_penalty_scale": 0.9,
                "dead_end_allowance": base_allowance + 1,
                "direction_bias": {"UP": 0, "DOWN": -1, "LEFT": 0, "RIGHT": -1},
            },
            {
                "name": "Cautious Cartographer",
                "dead_end_penalty_scale": 1.35,
                "novelty_reward_scale": 0.95,
                "branch_diversity_scale": 1.2,
                "corridor_penalty_scale": 1.15,
                "dead_end_allowance": max(0, base_allowance - 1),
                "direction_bias": {"UP": 0, "DOWN": 0, "LEFT": 0, "RIGHT": 0},
            },
            {
                "name": "Right-Hand Rover",
                "dead_end_penalty_scale": 1.0,
                "novelty_reward_scale": 1.1,
                "branch_diversity_scale": 1.0,
                "corridor_penalty_scale": 1.0,
                "dead_end_allowance": base_allowance,
                "direction_bias": {"UP": 0, "DOWN": -1, "LEFT": 2, "RIGHT": -2},
            },
            {
                "name": "Left-Hand Rover",
                "dead_end_penalty_scale": 1.0,
                "novelty_reward_scale": 1.1,
                "branch_diversity_scale": 1.0,
                "corridor_penalty_scale": 1.0,
                "dead_end_allowance": base_allowance,
                "direction_bias": {"UP": 0, "DOWN": -1, "LEFT": -2, "RIGHT": 2},
            },
            {
                "name": "Balanced Mapper",
                "dead_end_penalty_scale": 1.0,
                "novelty_reward_scale": 1.0,
                "branch_diversity_scale": 1.0,
                "corridor_penalty_scale": 1.0,
                "dead_end_allowance": base_allowance,
                "direction_bias": {"UP": 0, "DOWN": 0, "LEFT": 0, "RIGHT": 0},
            },
        ]

        chosen = self._personality_rng.choice(archetypes)
        self.maze_personality_name = str(chosen["name"])
        self.maze_personality = {
            "dead_end_penalty_scale": float(chosen["dead_end_penalty_scale"]),
            "novelty_reward_scale": float(chosen["novelty_reward_scale"]),
            "branch_diversity_scale": float(chosen["branch_diversity_scale"]),
            "corridor_penalty_scale": float(chosen["corridor_penalty_scale"]),
            "dead_end_allowance": int(chosen["dead_end_allowance"]),
            "direction_bias": dict(chosen["direction_bias"]),
        }

    def _init_memory_db(self) -> None:
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute("DROP TABLE IF EXISTS maze_layout_memory")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_structural_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        mode TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        grid_size INTEGER NOT NULL,
                        start_cell TEXT NOT NULL,
                        player_cell TEXT NOT NULL,
                        open_cells INTEGER NOT NULL,
                        blocked_cells INTEGER NOT NULL,
                        unknown_cells INTEGER NOT NULL,
                        frontier_cells INTEGER NOT NULL,
                        junction_cells INTEGER NOT NULL,
                        corridor_cells INTEGER NOT NULL,
                        dead_end_cells INTEGER NOT NULL,
                        loop_estimate INTEGER NOT NULL,
                        details_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_layout_cell_memory (
                        maze_layout_id INTEGER NOT NULL,
                        difficulty TEXT NOT NULL,
                        grid_size INTEGER NOT NULL,
                        cell_row INTEGER NOT NULL,
                        cell_col INTEGER NOT NULL,
                        cell_token TEXT NOT NULL,
                        last_seen_step INTEGER NOT NULL DEFAULT 0,
                        seen_count INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (
                            maze_layout_id,
                            difficulty,
                            grid_size,
                            cell_row,
                            cell_col
                        )
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_pattern_catalog (
                        pattern_signature TEXT PRIMARY KEY,
                        pattern_name TEXT NOT NULL,
                        seen_count INTEGER NOT NULL DEFAULT 1,
                        last_reason TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_short_term_memory (
                        pattern_signature TEXT PRIMARY KEY,
                        pattern_name TEXT NOT NULL,
                        ascii_pattern TEXT NOT NULL,
                        recall_count INTEGER NOT NULL DEFAULT 0,
                        strength REAL NOT NULL DEFAULT 0.0,
                        created_step INTEGER NOT NULL DEFAULT 0,
                        last_recalled_step INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_semantic_memory (
                        pattern_signature TEXT PRIMARY KEY,
                        pattern_name TEXT NOT NULL,
                        ascii_pattern TEXT NOT NULL,
                        recall_count INTEGER NOT NULL DEFAULT 0,
                        strength REAL NOT NULL DEFAULT 0.0,
                        promoted_from_stm INTEGER NOT NULL DEFAULT 1,
                        first_promoted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_action_outcome_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        maze_layout_id INTEGER NOT NULL DEFAULT 0,
                        step_index INTEGER NOT NULL,
                        mode TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        player_cell TEXT NOT NULL,
                        action_taken TEXT NOT NULL,
                        outcome_label TEXT NOT NULL,
                        outcome_value REAL NOT NULL,
                        reward_signal REAL NOT NULL DEFAULT 0.0,
                        penalty_signal REAL NOT NULL DEFAULT 0.0,
                        reason_tags TEXT NOT NULL DEFAULT '',
                        details_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                self._ensure_action_outcome_memory_schema(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_cause_effect_stm (
                        cause_key TEXT PRIMARY KEY,
                        action_taken TEXT NOT NULL,
                        reason_tags TEXT NOT NULL,
                        vector_json TEXT NOT NULL,
                        avg_outcome REAL NOT NULL DEFAULT 0.0,
                        recall_count INTEGER NOT NULL DEFAULT 1,
                        strength REAL NOT NULL DEFAULT 0.25,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_cause_effect_semantic (
                        cause_key TEXT PRIMARY KEY,
                        action_taken TEXT NOT NULL,
                        reason_tags TEXT NOT NULL,
                        vector_json TEXT NOT NULL,
                        avg_outcome REAL NOT NULL DEFAULT 0.0,
                        recall_count INTEGER NOT NULL DEFAULT 1,
                        strength REAL NOT NULL DEFAULT 0.25,
                        promoted_from_stm INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS maze_prediction_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        resolved_at TEXT,
                        maze_layout_id INTEGER NOT NULL,
                        step_created INTEGER NOT NULL,
                        step_resolved INTEGER,
                        cell_row INTEGER NOT NULL,
                        cell_col INTEGER NOT NULL,
                        predicted_label TEXT NOT NULL,
                        predicted_shape TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        p_open REAL NOT NULL,
                        p_blocked REAL NOT NULL,
                        shape_distribution_json TEXT NOT NULL DEFAULT '{}',
                        prior_shape_distribution_json TEXT NOT NULL DEFAULT '{}',
                        prediction_context_key TEXT NOT NULL DEFAULT '',
                        prediction_context_json TEXT NOT NULL DEFAULT '{}',
                        confidence_bucket INTEGER NOT NULL DEFAULT 0,
                        local_open_prob REAL NOT NULL,
                        prior_open_prob REAL NOT NULL,
                        resolution_status TEXT NOT NULL DEFAULT 'pending',
                        expiry_reason TEXT NOT NULL DEFAULT '',
                        actual_label TEXT NOT NULL DEFAULT '',
                        actual_shape TEXT NOT NULL DEFAULT '',
                        is_correct INTEGER,
                        is_shape_correct INTEGER,
                        occupancy_brier REAL NOT NULL DEFAULT 0.0,
                        shape_brier REAL NOT NULL DEFAULT 0.0,
                        occupancy_score_delta REAL NOT NULL DEFAULT 0.0,
                        shape_score_delta REAL NOT NULL DEFAULT 0.0,
                        score_delta REAL NOT NULL DEFAULT 0.0
                    )
                    """
                )
                self._ensure_prediction_memory_schema(conn)
                conn.commit()
        except Exception:  # noqa: BLE001
            return

    def _ensure_prediction_memory_schema(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute("PRAGMA table_info(maze_prediction_memory)").fetchall()
        except Exception:  # noqa: BLE001
            return

        column_names = {str(row[1]) for row in rows if len(row) > 1}
        required_columns = {
            "shape_distribution_json": "TEXT NOT NULL DEFAULT '{}'",
            "prior_shape_distribution_json": "TEXT NOT NULL DEFAULT '{}'",
            "prediction_context_key": "TEXT NOT NULL DEFAULT ''",
            "prediction_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "confidence_bucket": "INTEGER NOT NULL DEFAULT 0",
            "resolution_status": "TEXT NOT NULL DEFAULT 'pending'",
            "expiry_reason": "TEXT NOT NULL DEFAULT ''",
            "is_shape_correct": "INTEGER",
            "occupancy_brier": "REAL NOT NULL DEFAULT 0.0",
            "shape_brier": "REAL NOT NULL DEFAULT 0.0",
            "occupancy_score_delta": "REAL NOT NULL DEFAULT 0.0",
            "shape_score_delta": "REAL NOT NULL DEFAULT 0.0",
        }
        for column_name, column_spec in required_columns.items():
            if column_name in column_names:
                continue
            conn.execute(f"ALTER TABLE maze_prediction_memory ADD COLUMN {column_name} {column_spec}")

        if "resolution_status" in required_columns:
            conn.execute(
                """
                UPDATE maze_prediction_memory
                SET resolution_status = CASE
                    WHEN actual_label IN ('open', 'blocked') THEN 'resolved'
                    ELSE 'pending'
                END
                WHERE resolution_status IS NULL OR resolution_status = '' OR resolution_status = 'pending'
                """
            )

    def _ensure_action_outcome_memory_schema(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute("PRAGMA table_info(maze_action_outcome_memory)").fetchall()
        except Exception:  # noqa: BLE001
            return

        column_names = {str(row[1]) for row in rows if len(row) > 1}
        if "maze_layout_id" not in column_names:
            conn.execute(
                "ALTER TABLE maze_action_outcome_memory ADD COLUMN maze_layout_id INTEGER NOT NULL DEFAULT 0"
            )

    def _maze_safety_margin(self) -> int:
        difficulty = self._normalized_maze_difficulty()
        if difficulty == "easy":
            return 8
        if difficulty == "hard":
            return 3
        return 5

    def _reset_maze_known_map(self) -> None:
        self._expire_pending_predictions("maze_reset")
        self._clear_sticky_objective_path()
        self.maze_known_cells = {}
        self.prediction_contradiction_debt.clear()
        self.prediction_context_contradiction_debt.clear()
        self._last_saved_structural_signature = ""
        self._last_saved_layout_cell_signature = ""
        self.layout_recall_last_map_id = -1
        self.layout_recall_last_restored = 0
        self.layout_recall_last_total = 0
        self.layout_recall_last_rejected = 0
        self.layout_recall_last_source = "none"
        self.maze_recent_cells.clear()
        self.maze_recent_transitions.clear()
        self.recent_forced_corridor_cells.clear()
        self.recent_trap_transition_events.clear()
        self.taboo_transitions.clear()
        self.reset_epoch = 0
        self.step_limit_reset_count = 0
        self._last_step_reset_memory_step = 0
        self.same_maze_retry_count = 0
        self._same_maze_retry_last_step = -1
        self._same_maze_retry_frontier_target = None
        self._post_reset_exhausted_cells.clear()
        self._post_reset_exhausted_transitions.clear()
        self._post_reset_cell_failure_counts.clear()
        self._post_reset_transition_failure_counts.clear()
        self._post_reset_transition_success_counts.clear()
        self._cell_visit_reset_epoch.clear()
        self._reset_trace.clear()
        self._persistent_frontier_target = None
        self._post_reset_stm_relax_remaining = 0
        self._clear_prediction_memory_state(clear_score=False)

    def _clear_prediction_memory_state(self, clear_score: bool = False) -> None:
        self.prediction_memory_active.clear()
        self.prediction_recent_results.clear()
        self._prediction_context_stats_cache.clear()
        self._prediction_context_trust_cache.clear()
        self.prediction_score_current_maze = 0.0
        if clear_score:
            self.prediction_score_total = 0.0
            self.prediction_resolved_count = 0
            self.prediction_correct_count = 0
            self.prediction_shape_correct_count = 0
            self.prediction_shape_scored_count = 0
            self.prediction_fully_correct_count = 0
            self.prediction_expired_count = 0
            self.prediction_occupancy_brier_total = 0.0
            self.prediction_shape_brier_total = 0.0

    def _register_prediction_contradiction(
        self,
        cell: tuple[int, int],
        context_key: str,
        severity: float,
    ) -> None:
        magnitude = max(0.0, float(severity))
        if magnitude <= 0.0:
            return

        affected_cells = {cell: 1.0}
        for neighbor in self._traversable_neighbors(cell):
            affected_cells[neighbor] = max(affected_cells.get(neighbor, 0.0), 0.55)

        for affected_cell, weight in affected_cells.items():
            current = float(self.prediction_contradiction_debt.get(affected_cell, 0.0) or 0.0)
            self.prediction_contradiction_debt[affected_cell] = min(4.5, current + (magnitude * weight))

        if context_key:
            current_context = float(self.prediction_context_contradiction_debt.get(context_key, 0.0) or 0.0)
            self.prediction_context_contradiction_debt[context_key] = min(3.0, current_context + magnitude)

    def _prediction_local_contradiction_debt(self, cell: tuple[int, int]) -> float:
        direct = float(self.prediction_contradiction_debt.get(cell, 0.0) or 0.0)
        neighbor_debt = 0.0
        for neighbor in self._traversable_neighbors(cell):
            neighbor_debt = max(
                neighbor_debt,
                float(self.prediction_contradiction_debt.get(neighbor, 0.0) or 0.0),
            )
        return min(5.0, direct + (neighbor_debt * 0.45))

    def _maze_objective_override_safe(self) -> bool:
        if self.maze_known_cells.get(self.current_target_cell, "") != "E":
            return False

        path = self._shortest_path_moves_between_cells(self.current_player_cell, self.current_target_cell)
        if not path:
            return False

        probe_cell = self.current_player_cell
        prefix_len = min(4, len(path))
        min_frontier_distance = self._frontier_distance(self.current_player_cell)
        peak_contradiction_debt = self._prediction_local_contradiction_debt(self.current_player_cell)
        for move in path[:prefix_len]:
            probe_cell = self._neighbor_for_move(probe_cell, move)
            if probe_cell == self.current_player_cell or self._is_blocked_cell(probe_cell):
                return False
            if probe_cell not in self.maze_known_cells:
                return False
            min_frontier_distance = min(min_frontier_distance, self._frontier_distance(probe_cell))
            peak_contradiction_debt = max(peak_contradiction_debt, self._prediction_local_contradiction_debt(probe_cell))

        if min_frontier_distance <= 1:
            return False
        if peak_contradiction_debt >= 1.35:
            return False
        return True

    def _prediction_accuracy(self) -> float:
        if self.prediction_resolved_count <= 0:
            return 0.0
        return self.prediction_correct_count / max(1, self.prediction_resolved_count)

    def _prediction_shape_accuracy(self) -> float:
        if self.prediction_shape_scored_count <= 0:
            return 0.0
        return self.prediction_shape_correct_count / max(1, self.prediction_shape_scored_count)

    def _prediction_full_accuracy(self) -> float:
        if self.prediction_shape_scored_count <= 0:
            return 0.0
        return self.prediction_fully_correct_count / max(1, self.prediction_shape_scored_count)

    def _prediction_avg_occupancy_brier(self) -> float:
        if self.prediction_resolved_count <= 0:
            return 0.0
        return self.prediction_occupancy_brier_total / max(1, self.prediction_resolved_count)

    def _prediction_avg_shape_brier(self) -> float:
        if self.prediction_shape_scored_count <= 0:
            return 0.0
        return self.prediction_shape_brier_total / max(1, self.prediction_shape_scored_count)

    def _prediction_confidence_bucket(self, confidence: float) -> int:
        bucket_count = max(1, int(self.prediction_confidence_buckets))
        clipped = max(0.0, min(0.999999, float(confidence)))
        return min(bucket_count - 1, int(clipped * bucket_count))

    def _prediction_bucket_label(self, bucket_index: int) -> str:
        bucket_count = max(1, int(self.prediction_confidence_buckets))
        bucket = max(0, min(bucket_count - 1, int(bucket_index)))
        lower = bucket / bucket_count
        upper = (bucket + 1) / bucket_count
        return f"{lower:.1f}-{upper:.1f}"

    def _normalize_distribution(self, values: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        total = 0.0
        for key, value in values.items():
            clipped = max(0.0, float(value or 0.0))
            normalized[key] = clipped
            total += clipped
        if total <= 0.0:
            fallback = 1.0 / max(1, len(_PREDICTION_SHAPE_LABELS))
            return {label: fallback for label in _PREDICTION_SHAPE_LABELS}
        for key in list(normalized.keys()):
            normalized[key] = normalized[key] / total
        return normalized

    def _binary_brier_score(self, p_positive: float, actual_positive: int) -> float:
        p_open = max(0.0, min(1.0, float(p_positive)))
        y_open = 1.0 if int(actual_positive) == 1 else 0.0
        return ((p_open - y_open) ** 2) + (((1.0 - p_open) - (1.0 - y_open)) ** 2)

    def _multiclass_brier_score(self, distribution: dict[str, float], actual_label: str) -> float:
        norm = self._normalize_distribution(distribution)
        total = 0.0
        for label in _PREDICTION_SHAPE_LABELS:
            target = 1.0 if label == actual_label else 0.0
            total += (float(norm.get(label, 0.0)) - target) ** 2
        return total

    def _score_prediction_channel(self, brier_score: float, weight: float) -> float:
        normalized_fit = max(0.0, min(1.0, 1.0 - (float(brier_score) / 2.0)))
        base_score = self.prediction_reward_wrong_learning + (
            (self.prediction_reward_correct - self.prediction_reward_wrong_learning) * normalized_fit
        )
        return float(base_score) * float(weight)

    def _prediction_context_payload(
        self,
        origin_cell: tuple[int, int],
        candidate_cell: tuple[int, int],
        known_open_neighbors: int,
        known_blocked_neighbors: int,
    ) -> dict[str, object]:
        try:
            signature_text = self._current_pattern_signature(current_cell=origin_cell)
            signature = json.loads(signature_text) if signature_text else {}
        except Exception:  # noqa: BLE001
            signature = {}

        candidate_row, candidate_col = candidate_cell
        boundary_bucket = 1 if (candidate_row in {0, self.grid_cells - 1} or candidate_col in {0, self.grid_cells - 1}) else 0
        payload = {
            "difficulty": str(signature.get("difficulty", self._normalized_maze_difficulty()) or self._normalized_maze_difficulty()),
            "boundary_bucket": boundary_bucket,
            "branch_profile": str(signature.get("branch_profile", "") or ""),
            "dead_end_risk": min(3, int(signature.get("dead_end_risk", 0) or 0)),
            "frontier_distance_bucket": min(3, int(signature.get("frontier_distance", 0) or 0)),
            "origin_known_degree": min(4, int(signature.get("known_degree", 0) or 0)),
            "origin_unknown_neighbors": min(4, int(signature.get("unknown_neighbors", 0) or 0)),
            "candidate_known_open_neighbors": min(4, int(known_open_neighbors)),
            "candidate_known_blocked_neighbors": min(4, int(known_blocked_neighbors)),
        }
        payload["context_key"] = (
            f"d={payload['difficulty']}|bb={payload['boundary_bucket']}|bp={payload['branch_profile']}"
            f"|dr={payload['dead_end_risk']}|fd={payload['frontier_distance_bucket']}"
        )
        return payload

    def _prediction_context_stats(self, context_key: str) -> dict[str, float]:
        stats = {
            "support": 0.0,
            "occ_accuracy": 0.0,
            "shape_accuracy": 0.0,
            "avg_confidence": 0.0,
            "occ_brier": 0.0,
            "shape_brier": 0.0,
        }
        if not context_key:
            return stats
        cached = self._prediction_context_stats_cache.get(context_key)
        if cached is not None:
            return cached
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*),
                           AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END),
                           AVG(CASE WHEN is_shape_correct IS NOT NULL THEN CASE WHEN is_shape_correct = 1 THEN 1.0 ELSE 0.0 END END),
                           AVG(confidence),
                           AVG(occupancy_brier),
                           AVG(CASE WHEN is_shape_correct IS NOT NULL THEN shape_brier END)
                    FROM maze_prediction_memory
                    WHERE resolution_status = 'resolved'
                      AND prediction_context_key = ?
                    """,
                    (context_key,),
                ).fetchone()
        except Exception:  # noqa: BLE001
            return stats

        if not row:
            return stats
        support, occ_accuracy, shape_accuracy, avg_confidence, occ_brier, shape_brier = row
        stats.update(
            {
                "support": float(support or 0.0),
                "occ_accuracy": float(occ_accuracy or 0.0),
                "shape_accuracy": float(shape_accuracy or 0.0),
                "avg_confidence": float(avg_confidence or 0.0),
                "occ_brier": float(occ_brier or 0.0),
                "shape_brier": float(shape_brier or 0.0),
            }
        )
        self._prediction_context_stats_cache[context_key] = stats.copy()
        return stats

    def _prediction_shape_context_trust(self, context_key: str) -> float:
        if not context_key:
            return 0.0
        cached = self._prediction_context_trust_cache.get(context_key)
        if cached is not None:
            return cached

        stats = self._prediction_context_stats(context_key)
        support = float(stats.get("support", 0.0))
        shape_acc = float(stats.get("shape_accuracy", 0.0))
        low = float(self.prediction_context_trust_low_shape_acc)
        high = float(self.prediction_context_trust_high_shape_acc)

        if shape_acc <= low:
            acc_trust = 0.0
        elif shape_acc >= high:
            acc_trust = 1.0
        else:
            denom = max(1e-6, (high - low))
            acc_trust = (shape_acc - low) / denom

        support_scale = min(1.0, support / max(1.0, float(self.prediction_context_min_support)))
        trust = max(0.0, min(1.0, acc_trust * support_scale))
        self._prediction_context_trust_cache[context_key] = trust
        return trust

    def _is_prediction_shape_observable(self, cell: tuple[int, int], actual_label: str) -> bool:
        if not self.prediction_shape_require_observability:
            return True
        if actual_label == "blocked":
            return True
        if int(self.episode_visited_cells.get(cell, 0) or 0) > 0:
            return True
        if self._is_fully_known_current_maze_cell(cell):
            return True

        known_neighbor_evidence = 0
        row, col = cell
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr = row + dr
            nc = col + dc
            if nr < 0 or nr >= self.grid_cells or nc < 0 or nc >= self.grid_cells:
                known_neighbor_evidence += 1
                continue
            if (nr, nc) in self.maze_known_cells:
                known_neighbor_evidence += 1
        return known_neighbor_evidence >= int(self.prediction_shape_observability_min_neighbors)

    def _prediction_candidate_bias(self, cell: tuple[int, int]) -> tuple[int, int, float, float]:
        pred = self.prediction_memory_active.get(cell)
        if not isinstance(pred, dict):
            return 0, 0, 0.0, 0.0

        p_open = float(pred.get("p_open", 0.5) or 0.5)
        confidence = float(pred.get("confidence", 0.0) or 0.0)
        min_conf = float(self.prediction_planning_min_conf)
        if self._maze_reexplore_cooldown_remaining > 0:
            min_conf = min(min_conf, float(self.maze_stuck_prediction_conf_floor))
        if p_open < 0.5 or confidence < min_conf:
            return 0, 0, 0.0, 0.0

        context_key = str(pred.get("prediction_context_key", "") or "")
        context_trust = self._prediction_shape_context_trust(context_key)
        local_contradiction_debt = self._prediction_local_contradiction_debt(cell)
        context_contradiction_debt = float(self.prediction_context_contradiction_debt.get(context_key, 0.0) or 0.0)
        if context_trust <= 0.0:
            return 0, 0, context_trust, 0.0
        if context_trust < 0.45 and confidence < 0.72:
            return 0, 0, context_trust, 0.0

        contradiction_scale = max(
            0.0,
            1.0 - min(0.9, (local_contradiction_debt * 0.22) + (context_contradiction_debt * 0.16)),
        )
        if contradiction_scale <= 0.12 and confidence < 0.9:
            return 0, 0, context_trust, 0.0

        effective_conf = max(0.0, min(1.0, confidence * context_trust * contradiction_scale))
        shape_distribution = pred.get("shape_distribution")
        if not isinstance(shape_distribution, dict):
            return 0, 0, context_trust, effective_conf

        junction_prob = float(shape_distribution.get("junction", 0.0) or 0.0)
        dead_end_prob = float(shape_distribution.get("dead_end", 0.0) or 0.0)

        bias_scale = 1.0
        if self._maze_reexplore_cooldown_remaining > 0:
            bias_scale = max(0.0, float(self.maze_stuck_prediction_bias_scale))
        junction_bonus = int(round(junction_prob * effective_conf * self.prediction_junction_bias_weight * bias_scale))
        dead_end_penalty = int(round(dead_end_prob * effective_conf * self.prediction_dead_end_bias_weight * bias_scale))
        return max(0, junction_bonus), max(0, dead_end_penalty), context_trust, effective_conf

    def _prediction_two_step_lookahead_bonus(self, origin: tuple[int, int], candidate: tuple[int, int]) -> int:
        if not self.prediction_lookahead_enable or self.prediction_lookahead_weight <= 0.0:
            return 0

        best_signal = 0.0
        for second in self._traversable_neighbors(candidate):
            if second == origin:
                continue
            unknown_neighbors_2 = self._unknown_neighbor_count(second)
            open_degree_2 = len(self._traversable_neighbors(second))
            frontier_distance_2 = self._frontier_distance(second)

            # Lightweight rollout signal: frontier gain + junction potential - dead-end risk.
            signal = 0.0
            signal += unknown_neighbors_2 * 1.35
            if open_degree_2 >= 3:
                signal += 1.1
            if frontier_distance_2 <= 1:
                signal += 0.7
            if open_degree_2 <= 1 and unknown_neighbors_2 == 0:
                signal -= 1.2

            j2, d2, _ctx2, _eff2 = self._prediction_candidate_bias(second)
            signal += ((j2 - d2) * 0.35)
            best_signal = max(best_signal, signal)

        if best_signal <= 0.0:
            return 0
        discounted = best_signal * float(self.prediction_lookahead_discount)
        return max(0, int(round(discounted * float(self.prediction_lookahead_weight))))

    def _context_adjusted_prediction_confidence(self, base_confidence: float, context_key: str) -> float:
        base = max(0.05, min(0.99, float(base_confidence)))
        stats = self._prediction_context_stats(context_key)
        support = float(stats.get("support", 0.0))
        if support < float(self.prediction_context_min_support):
            return base
        context_confidence = (
            (0.55 * float(stats.get("occ_accuracy", 0.0)))
            + (0.30 * float(stats.get("shape_accuracy", 0.0)))
            + (0.15 * max(0.0, 1.0 - (float(stats.get("occ_brier", 0.0)) / 2.0)))
        )
        support_scale = support / (support + float(self.prediction_context_min_support) + 4.0)
        blend = self.prediction_context_confidence_blend * support_scale
        return max(0.05, min(0.99, ((1.0 - blend) * base) + (blend * context_confidence)))

    def _prediction_confidence_bucket_rows(self) -> list[tuple]:
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT confidence_bucket,
                           COUNT(*) AS total,
                           AVG(confidence) AS avg_confidence,
                           AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) AS occ_accuracy,
                           AVG(CASE WHEN is_shape_correct IS NOT NULL THEN CASE WHEN is_shape_correct = 1 THEN 1.0 ELSE 0.0 END END) AS shape_accuracy,
                           AVG(occupancy_brier) AS occ_brier,
                           AVG(CASE WHEN is_shape_correct IS NOT NULL THEN shape_brier END) AS shape_brier
                    FROM maze_prediction_memory
                    WHERE resolution_status = 'resolved'
                    GROUP BY confidence_bucket
                    ORDER BY confidence_bucket ASC
                    """
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _prediction_context_rows(self, limit: int = 5) -> list[tuple]:
        capped_limit = max(1, min(20, int(limit)))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT prediction_context_key,
                           COUNT(*) AS total,
                           AVG(confidence) AS avg_confidence,
                           AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) AS occ_accuracy,
                              AVG(CASE WHEN is_shape_correct IS NOT NULL THEN CASE WHEN is_shape_correct = 1 THEN 1.0 ELSE 0.0 END END) AS shape_accuracy,
                           AVG(occupancy_brier) AS occ_brier,
                              AVG(CASE WHEN is_shape_correct IS NOT NULL THEN shape_brier END) AS shape_brier
                    FROM maze_prediction_memory
                    WHERE resolution_status = 'resolved'
                      AND prediction_context_key != ''
                    GROUP BY prediction_context_key
                    ORDER BY total DESC, occ_accuracy DESC
                    LIMIT ?
                    """,
                    (capped_limit,),
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _actual_cell_shape_label(self, cell: tuple[int, int]) -> str:
        if self._is_blocked_cell(cell):
            return "wall"
        neighbors = self._traversable_neighbors(cell)
        degree = len(neighbors)
        if degree <= 1:
            return "dead_end"
        if degree >= 3:
            return "junction"
        dr1 = neighbors[0][0] - cell[0]
        dc1 = neighbors[0][1] - cell[1]
        dr2 = neighbors[1][0] - cell[0]
        dc2 = neighbors[1][1] - cell[1]
        if dr1 == -dr2 and dc1 == -dc2:
            return "corridor"
        return "corner"

    def _estimate_prediction_shape_key(
        self,
        known_open_neighbors: int,
        known_blocked_neighbors: int,
    ) -> str:
        if known_blocked_neighbors >= 3:
            return "dead_end"
        if known_open_neighbors >= 3:
            return "junction"
        if known_open_neighbors == 2 and known_blocked_neighbors <= 1:
            return "corridor"
        if known_open_neighbors == 1 and known_blocked_neighbors >= 1:
            return "corner"
        if known_open_neighbors == 0 and known_blocked_neighbors >= 2:
            return "wall_band"
        return "mixed"

    def _prediction_prior_open_rate_by_shape(self) -> dict[str, float]:
        rates: dict[str, float] = {}
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT predicted_shape,
                           SUM(CASE WHEN actual_label = 'open' THEN 1 ELSE 0 END) AS open_hits,
                           COUNT(*) AS total_hits
                    FROM maze_prediction_memory
                    WHERE actual_label IN ('open', 'blocked')
                    GROUP BY predicted_shape
                    """
                ).fetchall()
            for shape, open_hits, total_hits in rows:
                total = int(total_hits or 0)
                if total <= 0:
                    continue
                rates[str(shape)] = float(open_hits or 0) / float(total)
        except Exception:  # noqa: BLE001
            return rates
        return rates

    def _prediction_prior_shape_distribution(self) -> dict[str, float]:
        counts = {label: 0.0 for label in _PREDICTION_SHAPE_LABELS}
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT actual_shape, COUNT(*)
                    FROM maze_prediction_memory
                    WHERE resolution_status = 'resolved'
                      AND actual_shape IN ('wall', 'dead_end', 'corridor', 'corner', 'junction')
                    GROUP BY actual_shape
                    """
                ).fetchall()
            for actual_shape, total_hits in rows:
                label = str(actual_shape)
                if label not in counts:
                    continue
                counts[label] = float(total_hits or 0.0)
        except Exception:  # noqa: BLE001
            return self._normalize_distribution({label: 1.0 for label in _PREDICTION_SHAPE_LABELS})

        if sum(counts.values()) <= 0.0:
            return self._normalize_distribution({label: 1.0 for label in _PREDICTION_SHAPE_LABELS})
        return self._normalize_distribution(counts)

    def _estimate_prediction_shape_distribution(
        self,
        known_open_neighbors: int,
        known_blocked_neighbors: int,
        boundary_blocked_neighbors: int,
        p_open: float,
        prior_distribution: dict[str, float],
        two_open_are_opposite: bool = False,
    ) -> dict[str, float]:
        blocked_evidence = known_blocked_neighbors + boundary_blocked_neighbors
        unknown_neighbors = max(0, 4 - known_open_neighbors - blocked_evidence)
        expected_open_degree = known_open_neighbors + (unknown_neighbors * p_open)

        local_weights = {
            "wall": max(0.02, (1.0 - p_open) * (1.0 + (0.25 * boundary_blocked_neighbors))),
            "dead_end": max(0.02, p_open * (1.25 - abs(expected_open_degree - 1.0))),
            "corridor": max(0.02, p_open * (1.15 - abs(expected_open_degree - 2.0))),
            "corner": max(0.02, p_open * (0.35 + (0.65 if known_open_neighbors == 1 else 0.0))),
            "junction": max(0.02, p_open * (1.15 - abs(expected_open_degree - 3.0))),
        }
        if blocked_evidence >= 3 and known_open_neighbors <= 1:
            local_weights["dead_end"] += 0.45 * max(0.2, p_open)
        if known_open_neighbors == 2:
            local_weights["corridor"] += 0.25 * max(0.2, p_open)
        if known_open_neighbors >= 2 and unknown_neighbors >= 1:
            local_weights["junction"] += 0.35 * max(0.2, p_open)
        # When we know exactly which 2 directions are open, we can distinguish
        # corridor (opposite neighbors) from corner (adjacent neighbors) directly.
        if known_open_neighbors == 2:
            if two_open_are_opposite:
                local_weights["corridor"] += 0.45 * max(0.2, p_open)
                local_weights["corner"] = max(0.02, local_weights["corner"] - 0.30)
            else:
                local_weights["corner"] += 0.40 * max(0.2, p_open)
                local_weights["corridor"] = max(0.02, local_weights["corridor"] - 0.20)
        if known_open_neighbors == 1 and unknown_neighbors >= 1:
            local_weights["corner"] += 0.2 * max(0.2, p_open)

        normalized_local = self._normalize_distribution(local_weights)
        alpha = self.prediction_prior_blend
        blended = {
            label: ((1.0 - alpha) * normalized_local.get(label, 0.0)) + (alpha * prior_distribution.get(label, 0.0))
            for label in _PREDICTION_SHAPE_LABELS
        }
        return self._normalize_distribution(blended)

    def _expire_pending_predictions(self, reason: str) -> None:
        if not self.prediction_memory_active:
            return

        step_resolved = int(self.memory_step_index)
        pending_rows: list[tuple[int, tuple[int, int], str, str]] = []
        db_ids: list[int] = []
        for cell, record in list(self.prediction_memory_active.items()):
            prediction_id = record.get("id")
            predicted_label = str(record.get("predicted_label", "open"))
            predicted_shape = str(record.get("predicted_shape", "corridor"))
            pending_rows.append((int(prediction_id or 0), cell, predicted_label, predicted_shape))
            if prediction_id is not None:
                db_ids.append(int(prediction_id))

        if db_ids:
            try:
                with sqlite3.connect(self.memory_db_path) as conn:
                    conn.executemany(
                        """
                        UPDATE maze_prediction_memory
                        SET resolved_at = CURRENT_TIMESTAMP,
                            step_resolved = ?,
                            resolution_status = 'expired',
                            expiry_reason = ?
                        WHERE id = ?
                        """,
                        [(step_resolved, reason, prediction_id) for prediction_id in db_ids],
                    )
                    conn.commit()
            except Exception:  # noqa: BLE001
                pass

        for _prediction_id, cell, predicted_label, predicted_shape in pending_rows:
            self.prediction_expired_count += 1
            self.prediction_recent_results.appendleft(
                {
                    "step": step_resolved,
                    "cell": cell,
                    "predicted_label": predicted_label,
                    "predicted_shape": predicted_shape,
                    "actual_label": "",
                    "actual_shape": "",
                    "confidence": 0.0,
                    "score_delta": 0.0,
                    "status": "expired",
                    "expiry_reason": reason,
                }
            )
            self._append_memory_log(
                f"prediction_expired cell={cell[0]},{cell[1]} predicted={predicted_label}/{predicted_shape} reason={reason}"
            )

        self.prediction_memory_active.clear()

    def _queue_frontier_predictions(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        if not self.maze_known_cells:
            return

        prior_by_shape = self._prediction_prior_open_rate_by_shape()
        prior_shape_distribution = self._prediction_prior_shape_distribution()
        alpha = self.prediction_prior_blend

        for known_cell, token in list(self.maze_known_cells.items()):
            if token not in {".", "P", "E"}:
                continue
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                candidate = self._neighbor_for_move(known_cell, move)
                if candidate == known_cell:
                    continue
                if candidate in self.maze_known_cells:
                    continue
                if candidate in self.prediction_memory_active:
                    continue

                row, col = candidate
                known_open_neighbors = 0
                known_blocked_neighbors = 0
                boundary_blocked_neighbors = 0
                open_direction_offsets: list[tuple[int, int]] = []
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nr = row + dr
                    nc = col + dc
                    if nr < 0 or nr >= self.grid_cells or nc < 0 or nc >= self.grid_cells:
                        boundary_blocked_neighbors += 1
                        continue
                    neighbor_cell = (nr, nc)
                    neighbor_token = self.maze_known_cells.get(neighbor_cell)
                    if neighbor_token is None:
                        continue
                    if neighbor_token == "#":
                        known_blocked_neighbors += 1
                    else:
                        known_open_neighbors += 1
                        open_direction_offsets.append((dr, dc))

                local_blocked_evidence = known_blocked_neighbors + (boundary_blocked_neighbors * 1.25)
                local_open_prob = (known_open_neighbors + 1.0) / (
                    known_open_neighbors + local_blocked_evidence + 2.0
                )
                shape_key = self._estimate_prediction_shape_key(known_open_neighbors, known_blocked_neighbors)
                prior_open_prob = float(prior_by_shape.get(shape_key, 0.5))
                p_open = ((1.0 - alpha) * local_open_prob) + (alpha * prior_open_prob)
                p_open = max(0.01, min(0.99, p_open))
                p_blocked = 1.0 - p_open
                context_payload = self._prediction_context_payload(
                    known_cell,
                    candidate,
                    known_open_neighbors,
                    known_blocked_neighbors,
                )
                context_key = str(context_payload.get("context_key", ""))
                two_open_are_opposite = (
                    known_open_neighbors == 2
                    and len(open_direction_offsets) == 2
                    and open_direction_offsets[0][0] == -open_direction_offsets[1][0]
                    and open_direction_offsets[0][1] == -open_direction_offsets[1][1]
                )
                shape_distribution = self._estimate_prediction_shape_distribution(
                    known_open_neighbors,
                    known_blocked_neighbors,
                    boundary_blocked_neighbors,
                    p_open,
                    prior_shape_distribution,
                    two_open_are_opposite=two_open_are_opposite,
                )
                predicted_shape = max(shape_distribution.items(), key=lambda item: item[1])[0]
                confidence = max(0.05, min(0.99, abs((p_open * 2.0) - 1.0)))
                confidence = self._context_adjusted_prediction_confidence(confidence, context_key)
                confidence_bucket = self._prediction_confidence_bucket(confidence)
                predicted_label = "open" if p_open >= 0.5 else "blocked"

                prediction_record: dict[str, object] = {
                    "id": None,
                    "step_created": int(self.memory_step_index),
                    "predicted_label": predicted_label,
                    "predicted_shape": predicted_shape,
                    "confidence": float(confidence),
                    "p_open": float(p_open),
                    "p_blocked": float(p_blocked),
                    "shape_distribution": shape_distribution,
                    "prior_shape_distribution": prior_shape_distribution,
                    "prediction_context_key": context_key,
                    "prediction_context": context_payload,
                    "confidence_bucket": int(confidence_bucket),
                    "local_open_prob": float(local_open_prob),
                    "prior_open_prob": float(prior_open_prob),
                }

                try:
                    with sqlite3.connect(self.memory_db_path) as conn:
                        cursor = conn.execute(
                            """
                            INSERT INTO maze_prediction_memory (
                                maze_layout_id,
                                step_created,
                                cell_row,
                                cell_col,
                                predicted_label,
                                predicted_shape,
                                confidence,
                                p_open,
                                p_blocked,
                                shape_distribution_json,
                                prior_shape_distribution_json,
                                prediction_context_key,
                                prediction_context_json,
                                confidence_bucket,
                                local_open_prob,
                                prior_open_prob
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(self.current_maze_episode_id),
                                int(self.memory_step_index),
                                int(row),
                                int(col),
                                predicted_label,
                                predicted_shape,
                                float(round(confidence, 4)),
                                float(round(p_open, 4)),
                                float(round(p_blocked, 4)),
                                json.dumps(shape_distribution, sort_keys=True),
                                json.dumps(prior_shape_distribution, sort_keys=True),
                                context_key,
                                json.dumps(context_payload, sort_keys=True),
                                int(confidence_bucket),
                                float(round(local_open_prob, 4)),
                                float(round(prior_open_prob, 4)),
                            ),
                        )
                        prediction_record["id"] = int(cursor.lastrowid)
                        conn.commit()
                except Exception:  # noqa: BLE001
                    prediction_record["id"] = None

                self.prediction_memory_active[candidate] = prediction_record

    def _resolve_visible_predictions(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        if not self.prediction_memory_active:
            return

        resolved_cells = [cell for cell in self.prediction_memory_active if cell in self.maze_known_cells]
        if not resolved_cells:
            return

        for cell in resolved_cells:
            record = self.prediction_memory_active.pop(cell, None)
            if not record:
                continue
            predicted_label = str(record.get("predicted_label", "open"))
            predicted_shape = str(record.get("predicted_shape", "corridor"))
            context_key = str(record.get("prediction_context_key", "") or "")
            confidence = float(record.get("confidence", 0.0) or 0.0)
            p_open = float(record.get("p_open", 0.5) or 0.5)
            shape_distribution = record.get("shape_distribution")
            if not isinstance(shape_distribution, dict):
                shape_distribution = {label: (1.0 / len(_PREDICTION_SHAPE_LABELS)) for label in _PREDICTION_SHAPE_LABELS}
            prediction_id = record.get("id")

            actual_label = "blocked" if self._is_blocked_cell(cell) else "open"
            actual_shape = self._actual_cell_shape_label(cell)
            is_correct = int(predicted_label == actual_label)
            shape_scorable = self._is_prediction_shape_observable(cell, actual_label)
            is_shape_correct: int | None = int(predicted_shape == actual_shape) if shape_scorable else None

            occupancy_brier = self._binary_brier_score(p_open, 1 if actual_label == "open" else 0)
            shape_brier = self._multiclass_brier_score(shape_distribution, actual_shape) if shape_scorable else 0.0
            occupancy_score_delta = self._score_prediction_channel(
                occupancy_brier,
                self.prediction_occupancy_score_weight,
            )
            if not is_correct:
                wrong_credit = float(self.prediction_reward_wrong_learning) * float(self.prediction_wrong_learning_credit_scale)
                wrong_penalty = max(
                    float(self.prediction_wrong_occupancy_penalty),
                    float(occupancy_brier) * (float(self.prediction_reward_correct) + 1.0),
                )
                occupancy_score_delta = (wrong_credit - wrong_penalty) * float(self.prediction_occupancy_score_weight)
                if confidence >= self.prediction_confident_threshold:
                    occupancy_score_delta -= float(self.prediction_confident_wrong_penalty)

            shape_score_delta = self._score_prediction_channel(
                shape_brier,
                self.prediction_shape_score_weight,
            ) if shape_scorable else 0.0
            if shape_scorable and not int(is_shape_correct or 0):
                wrong_shape_credit = (
                    float(self.prediction_reward_wrong_learning)
                    * float(self.prediction_wrong_learning_credit_scale)
                    * 0.5
                )
                wrong_shape_penalty = max(
                    float(self.prediction_wrong_shape_penalty),
                    float(shape_brier) * ((float(self.prediction_reward_correct) * 0.8) + 0.5),
                )
                shape_score_delta = (wrong_shape_credit - wrong_shape_penalty) * float(self.prediction_shape_score_weight)
            score_delta = occupancy_score_delta + shape_score_delta

            contradiction_severity = 0.0
            if not is_correct:
                contradiction_severity += 0.7 + (confidence * 0.9)
            if shape_scorable and not int(is_shape_correct or 0):
                contradiction_severity += 0.45 + (max(0.0, confidence - 0.45) * 0.7)
            if contradiction_severity > 0.0:
                self._register_prediction_contradiction(cell, context_key, contradiction_severity)

            self.prediction_occupancy_brier_total += occupancy_brier
            if is_correct:
                self.prediction_correct_count += 1
            if shape_scorable:
                self.prediction_shape_scored_count += 1
                self.prediction_shape_brier_total += shape_brier
                if int(is_shape_correct or 0):
                    self.prediction_shape_correct_count += 1
                if is_correct and int(is_shape_correct or 0):
                    self.prediction_fully_correct_count += 1
            occupancy_brier = round(occupancy_brier, 4)
            shape_brier = round(shape_brier, 4)
            occupancy_score_delta = round(occupancy_score_delta, 3)
            shape_score_delta = round(shape_score_delta, 3)
            score_delta = round(score_delta, 3)

            self.prediction_resolved_count += 1
            self.prediction_score_total = round(self.prediction_score_total + score_delta, 3)
            self.prediction_score_current_maze = round(self.prediction_score_current_maze + score_delta, 3)

            result_payload = {
                "step": int(self.memory_step_index),
                "cell": cell,
                "predicted_label": predicted_label,
                "actual_label": actual_label,
                "predicted_shape": predicted_shape,
                "actual_shape": actual_shape,
                "confidence": round(confidence, 3),
                "occupancy_brier": occupancy_brier,
                "shape_brier": shape_brier,
                "occupancy_score_delta": occupancy_score_delta,
                "shape_score_delta": shape_score_delta,
                "score_delta": score_delta,
                "correct": bool(is_correct),
                "shape_correct": bool(is_shape_correct) if shape_scorable else False,
                "shape_scored": bool(shape_scorable),
                "status": "resolved",
            }
            self.prediction_recent_results.appendleft(result_payload)
            self._append_memory_log(
                (
                    "prediction_result "
                    f"cell={cell[0]},{cell[1]} predicted={predicted_label}/{predicted_shape} "
                    f"actual={actual_label}/{actual_shape} confidence={round(confidence, 3)} "
                    f"occ_brier={occupancy_brier} shape_brier={shape_brier} "
                    f"shape_scored={shape_scorable} "
                    f"score_delta={score_delta}"
                )
            )

            try:
                if prediction_id is None:
                    continue
                with sqlite3.connect(self.memory_db_path) as conn:
                    conn.execute(
                        """
                        UPDATE maze_prediction_memory
                        SET resolved_at = CURRENT_TIMESTAMP,
                            step_resolved = ?,
                            resolution_status = 'resolved',
                            expiry_reason = '',
                            actual_label = ?,
                            actual_shape = ?,
                            is_correct = ?,
                            is_shape_correct = ?,
                            occupancy_brier = ?,
                            shape_brier = ?,
                            occupancy_score_delta = ?,
                            shape_score_delta = ?,
                            score_delta = ?
                        WHERE id = ?
                        """,
                        (
                            int(self.memory_step_index),
                            actual_label,
                            actual_shape,
                            is_correct,
                            is_shape_correct,
                            float(occupancy_brier),
                            float(shape_brier),
                            float(occupancy_score_delta),
                            float(shape_score_delta),
                            float(score_delta),
                            int(prediction_id),
                        ),
                    )
                    conn.commit()
            except Exception:  # noqa: BLE001
                continue

        if resolved_cells:
            self._prediction_context_stats_cache.clear()
            self._prediction_context_trust_cache.clear()

    def _recent_prediction_rows(self, limit: int = 12) -> list[tuple]:
        capped_limit = max(1, min(200, int(limit)))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT created_at, resolved_at, step_created, step_resolved,
                           cell_row, cell_col, predicted_label, predicted_shape,
                              confidence, prediction_context_key, confidence_bucket, resolution_status, expiry_reason,
                          actual_label, actual_shape, is_correct, is_shape_correct,
                          occupancy_brier, shape_brier,
                          occupancy_score_delta, shape_score_delta, score_delta
                    FROM maze_prediction_memory
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (capped_limit,),
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _update_maze_known_map(
        self,
        player_row: int,
        player_col: int,
        radius: int = 1,
        facing: str | None = None,
    ) -> None:
        if self._normalized_layout_mode() != "maze":
            return

        facing_for_view = facing or self.player_facing
        edge_context_cells = self._edge_context_probe_cells(player_row, player_col, facing_for_view)

        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                vis_kind = self._local_visibility_kind(player_row, player_col, row, col, facing=facing_for_view)
                cell = (row, col)
                in_edge_context = cell in edge_context_cells
                if vis_kind == "none" and not in_edge_context:
                    continue

                # Cells rendered in the current ASCII view are authoritative for
                # structural classification. This includes side-context probes and
                # half-visible local cells that are shown as open/blocked in the view.
                if cell in self.blocked_cells:
                    self.maze_known_cells[cell] = "#"
                elif vis_kind != "none" and cell == self.current_target_cell:
                    self.maze_known_cells[cell] = "E"
                else:
                    self.maze_known_cells[cell] = "."

        self.maze_known_cells[(player_row, player_col)] = "P"

    def _is_local_cell_visible(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
        facing: str | None = None,
    ) -> bool:
        return self._local_visibility_kind(origin_row, origin_col, row, col, facing=facing) != "none"

    def _local_visibility_kind(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
        facing: str | None = None,
    ) -> str:
        if row < 0 or row >= self.grid_cells or col < 0 or col >= self.grid_cells:
            return "none"
        if row == origin_row and col == origin_col:
            return "full"
        strength = self._visibility_strength(origin_row, origin_col, row, col, facing=facing)
        if strength < self.maze_fov_half_threshold:
            return "none"
        # Central cone remains full-visible, while peripheral/low-light cells
        # are half-visible similar to biological peripheral acuity.
        if strength < self.maze_fov_full_threshold:
            return "half"
        return "full"

    def _visibility_strength(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
        facing: str | None = None,
    ) -> float:
        if row < 0 or row >= self.grid_cells or col < 0 or col >= self.grid_cells:
            return 0.0
        dr = row - origin_row
        dc = col - origin_col
        if dr == 0 and dc == 0:
            return 1.0

        fv_r, fv_c = self._facing_vector_for(facing)
        forward = dr * fv_r + dc * fv_c
        if forward <= 0:
            return 0.0

        max_forward = max(1.0, float(self.maze_fov_depth) + 0.5)
        if forward > max_forward:
            return 0.0

        distance = math.hypot(dr, dc)
        if distance <= 0.0:
            return 0.0

        base_half_angle = max(28.0, min(88.0, self.maze_fov_cone_degrees / 2.0))
        peripheral_bonus = max(0.0, float(self.maze_fov_peripheral) - 1.0) * 4.0
        half_angle = max(28.0, min(88.0, base_half_angle + peripheral_bonus))
        cos_limit = math.cos(math.radians(half_angle))
        cos_theta = forward / distance
        if cos_theta < cos_limit:
            return 0.0

        los_clear, corner_graze_steps = self._line_of_sight_metrics(origin_row, origin_col, row, col)
        if not los_clear:
            return 0.0

        angle_factor = (cos_theta - cos_limit) / max(1e-6, (1.0 - cos_limit))
        distance_factor = 1.0 / (1.0 + max(0.0, self.maze_fov_distance_falloff) * (distance ** 2))
        graze_factor = max(0.25, min(1.0, self.maze_fov_corner_graze_factor))
        corner_factor = graze_factor ** max(0, corner_graze_steps)
        strength = angle_factor * distance_factor * corner_factor
        return max(0.0, min(1.0, strength))

    def _facing_vector_for(self, facing: str | None) -> tuple[int, int]:
        facing_value = (facing or self.player_facing or "UP").strip().upper()
        return {
            "UP": (-1, 0),
            "DOWN": (1, 0),
            "LEFT": (0, -1),
            "RIGHT": (0, 1),
        }.get(facing_value, (-1, 0))

    def _facing_vector(self) -> tuple[int, int]:
        return self._facing_vector_for(self.player_facing)

    def _is_cell_in_forward_fov(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
        facing: str | None = None,
    ) -> bool:
        dr = row - origin_row
        dc = col - origin_col
        if dr == 0 and dc == 0:
            return True
        fv_r, fv_c = self._facing_vector_for(facing)
        forward = dr * fv_r + dc * fv_c
        if forward <= 0:
            return False
        if forward > max(1.0, float(self.maze_fov_depth) + 0.5):
            return False
        distance = math.hypot(dr, dc)
        if distance <= 0.0:
            return True
        base_half_angle = max(28.0, min(88.0, self.maze_fov_cone_degrees / 2.0))
        peripheral_bonus = max(0.0, float(self.maze_fov_peripheral) - 1.0) * 4.0
        half_angle = max(28.0, min(88.0, base_half_angle + peripheral_bonus))
        cos_limit = math.cos(math.radians(half_angle))
        return (forward / distance) >= cos_limit

    def _line_points(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
    ) -> list[tuple[int, int]]:
        # Bresenham-style integer line for visibility tests.
        x0, y0 = origin_col, origin_row
        x1, y1 = col, row
        points: list[tuple[int, int]] = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            points.append((y0, x0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        return points

    def _has_line_of_sight(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
    ) -> bool:
        clear, _corner_graze_steps = self._line_of_sight_metrics(origin_row, origin_col, row, col)
        return clear

    def _line_of_sight_metrics(
        self,
        origin_row: int,
        origin_col: int,
        row: int,
        col: int,
    ) -> tuple[bool, int]:
        points = self._line_points(origin_row, origin_col, row, col)
        if len(points) <= 1:
            return (True, 0)

        corner_graze_steps = 0
        prev_row, prev_col = points[0]
        for idx in range(1, len(points)):
            cur_row, cur_col = points[idx]

            # Ignore the destination cell for occlusion checks; only intermediate
            # blockers should block LOS.
            if idx < len(points) - 1 and self._is_blocked_cell((cur_row, cur_col)):
                return (False, 0)

            step_r = cur_row - prev_row
            step_c = cur_col - prev_col
            if step_r != 0 and step_c != 0:
                side_a = (prev_row, cur_col)
                side_b = (cur_row, prev_col)
                block_a = self._is_blocked_cell(side_a)
                block_b = self._is_blocked_cell(side_b)
                # Fully closed diagonal corner blocks sight entirely.
                if block_a and block_b:
                    return (False, 0)
                # Single-wall diagonal transition is a corner graze: keep sight,
                # but attenuate visibility strength (partial around-corner peek).
                if block_a != block_b:
                    corner_graze_steps += 1

            prev_row, prev_col = cur_row, cur_col
        return (True, corner_graze_steps)

    def _store_current_maze_memory_snapshot(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        self._store_structural_memory_snapshot()
        self._store_layout_cell_memory_snapshot()

    def _normalized_layout_cell_token(self, token: str) -> str:
        if token == "#":
            return "#"
        if token in {".", "P", "S", "E"}:
            return "."
        return ""

    def _layout_cell_rows_from_known_map(self) -> list[tuple[int, int, str]]:
        rows: list[tuple[int, int, str]] = []
        for (row, col), token in self.maze_known_cells.items():
            normalized = self._normalized_layout_cell_token(str(token))
            if not normalized:
                continue
            rows.append((int(row), int(col), normalized))
        rows.sort(key=lambda item: (item[0], item[1]))
        return rows

    def _store_layout_cell_memory_snapshot(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        if int(self.current_maze_episode_id) < 0:
            return

        rows = self._layout_cell_rows_from_known_map()
        if not rows:
            return

        difficulty = self._normalized_maze_difficulty()
        grid_size = int(self.grid_cells)
        map_id = int(self.current_maze_episode_id)
        signature = (
            f"{map_id}:{difficulty}:{grid_size}:"
            + "|".join(f"{row}:{col}:{token}" for row, col, token in rows)
        )
        if signature == self._last_saved_layout_cell_signature:
            return

        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO maze_layout_cell_memory (
                        maze_layout_id,
                        difficulty,
                        grid_size,
                        cell_row,
                        cell_col,
                        cell_token,
                        last_seen_step,
                        seen_count,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(maze_layout_id, difficulty, grid_size, cell_row, cell_col)
                    DO UPDATE SET
                        cell_token = excluded.cell_token,
                        last_seen_step = excluded.last_seen_step,
                        seen_count = maze_layout_cell_memory.seen_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [
                        (
                            map_id,
                            difficulty,
                            grid_size,
                            int(row),
                            int(col),
                            token,
                            int(self.memory_step_index),
                        )
                        for row, col, token in rows
                    ],
                )
                conn.commit()
            self._last_saved_layout_cell_signature = signature
        except Exception:  # noqa: BLE001
            return

    def _store_complete_layout_cell_memory_snapshot(self, maze_layout_id: int | None = None) -> None:
        if self._normalized_layout_mode() != "maze":
            return

        map_id = int(self.current_maze_episode_id if maze_layout_id is None else maze_layout_id)
        if map_id < 0:
            return

        difficulty = self._normalized_maze_difficulty()
        grid_size = int(self.grid_cells)
        rows: list[tuple[int, int, str]] = []
        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                token = "#" if (row, col) in self.blocked_cells else "."
                rows.append((row, col, token))

        if not rows:
            return

        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO maze_layout_cell_memory (
                        maze_layout_id,
                        difficulty,
                        grid_size,
                        cell_row,
                        cell_col,
                        cell_token,
                        last_seen_step,
                        seen_count,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(maze_layout_id, difficulty, grid_size, cell_row, cell_col)
                    DO UPDATE SET
                        cell_token = excluded.cell_token,
                        last_seen_step = excluded.last_seen_step,
                        seen_count = maze_layout_cell_memory.seen_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    [
                        (
                            map_id,
                            difficulty,
                            grid_size,
                            int(row),
                            int(col),
                            token,
                            int(self.memory_step_index),
                        )
                        for row, col, token in rows
                    ],
                )
                conn.commit()
            open_cells = len([1 for _row, _col, token in rows if token == "."])
            blocked_cells = len(rows) - open_cells
            self._last_saved_layout_cell_signature = ""
            self._append_memory_log(
                (
                    "[LAYOUT-COMMIT: "
                    f"map_id={map_id} cells={len(rows)} open={open_cells} blocked={blocked_cells} "
                    f"difficulty={difficulty} grid={grid_size}]"
                )
            )
        except Exception:  # noqa: BLE001
            return

    def _overwrite_layout_cell_memory_block(
        self,
        map_id: int,
        difficulty: str,
        grid_size: int,
        rows: list[tuple[int, int, str]],
        decayed_cell: tuple[int, int] | None = None,
        decay_steps: int = 0,
    ) -> None:
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    DELETE FROM maze_layout_cell_memory
                    WHERE maze_layout_id = ? AND difficulty = ? AND grid_size = ?
                    """,
                    (int(map_id), difficulty, int(grid_size)),
                )
                if rows:
                    conn.executemany(
                        """
                        INSERT INTO maze_layout_cell_memory (
                            maze_layout_id,
                            difficulty,
                            grid_size,
                            cell_row,
                            cell_col,
                            cell_token,
                            last_seen_step,
                            seen_count,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        """,
                        [
                            (
                                int(map_id),
                                difficulty,
                                int(grid_size),
                                int(row),
                                int(col),
                                token,
                                (
                                    max(0, int(self.memory_step_index) - max(0, int(decay_steps)))
                                    if decayed_cell is not None and (int(row), int(col)) == decayed_cell
                                    else int(self.memory_step_index)
                                ),
                            )
                            for row, col, token in rows
                        ],
                    )
                conn.commit()
        except Exception:  # noqa: BLE001
            return

    def _apply_layout_recall_mutation(
        self,
        restored_map: dict[tuple[int, int], str],
    ) -> tuple[dict[tuple[int, int], str], bool, str, tuple[int, int] | None]:
        chance = float(self.layout_recall_mutation_chance)
        if chance <= 0.0:
            return (restored_map, False, "", None)

        mutable_map = dict(restored_map)
        if not mutable_map:
            return (mutable_map, False, "", None)

        rng = self._event_rng()
        if rng.random() >= chance:
            return (mutable_map, False, "", None)

        mutable_cells = [
            cell
            for cell, token in mutable_map.items()
            if token in {".", "#"} and cell != self.current_player_cell
        ]
        if len(mutable_cells) < 2:
            return (mutable_map, False, "", None)

        cell = rng.choice(mutable_cells)
        token = str(mutable_map.get(cell, "") or "")
        detail = f"decay={cell[0]},{cell[1]} token={token}"
        return (mutable_map, True, detail, cell)

    def _load_layout_cell_memory_snapshot(self) -> None:
        self.layout_recall_last_map_id = int(self.current_maze_episode_id)
        self.layout_recall_last_restored = 0
        self.layout_recall_last_total = 0
        self.layout_recall_last_rejected = 0
        self.layout_recall_last_source = "none"

        if self._normalized_layout_mode() != "maze":
            return
        map_id = int(self.current_maze_episode_id)
        if map_id < 0:
            return

        difficulty = self._normalized_maze_difficulty()
        grid_size = int(self.grid_cells)
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT cell_row, cell_col, cell_token
                    FROM maze_layout_cell_memory
                    WHERE maze_layout_id = ? AND difficulty = ? AND grid_size = ?
                    ORDER BY cell_row, cell_col
                    """,
                    (map_id, difficulty, grid_size),
                ).fetchall()
        except Exception:  # noqa: BLE001
            return

        if not rows:
            self.layout_recall_last_source = "db-miss"
            return

        restored_map: dict[tuple[int, int], str] = {}
        rejected = 0
        for row, col, token in rows:
            cell = (int(row), int(col))
            normalized = self._normalized_layout_cell_token(str(token))
            if not normalized:
                rejected += 1
                continue
            if normalized == "#" and cell not in self.blocked_cells:
                rejected += 1
                continue
            if normalized == "." and cell in self.blocked_cells:
                rejected += 1
                continue
            restored_map[cell] = normalized

        player_cell = self.current_player_cell
        if player_cell:
            restored_map[player_cell] = "P"

        restored_map, mutated, mutation_detail, decayed_cell = self._apply_layout_recall_mutation(restored_map)

        self.maze_known_cells = restored_map
        restored_cells = len([token for token in restored_map.values() if token in {"#", "."}])
        reconsolidated_rows = self._layout_cell_rows_from_known_map()
        self._overwrite_layout_cell_memory_block(
            map_id,
            difficulty,
            grid_size,
            reconsolidated_rows,
            decayed_cell=decayed_cell,
            decay_steps=self.layout_recall_mutation_decay_steps if mutated else 0,
        )

        self.layout_recall_last_restored = int(restored_cells)
        self.layout_recall_last_total = int(len(rows))
        self.layout_recall_last_rejected = int(rejected)
        self.layout_recall_last_source = "db-hit"
        self._last_saved_layout_cell_signature = ""
        self._append_memory_log(
            (
                "[LAYOUT-RECALL: "
                f"map_id={map_id} restored={restored_cells} total={len(rows)} rejected={rejected} "
                f"difficulty={difficulty} grid={grid_size} mutated={1 if mutated else 0}]"
            )
        )
        self._append_memory_log(
            (
                "[LAYOUT-RECONSOLIDATE: "
                f"map_id={map_id} rows={len(reconsolidated_rows)} mutated={1 if mutated else 0} "
                f"detail={mutation_detail or 'none'} difficulty={difficulty} grid={grid_size}]"
            )
        )

    def _known_open_cells(self) -> set[tuple[int, int]]:
        return {
            cell
            for cell, token in self.maze_known_cells.items()
            if token in {".", "P", "S", "E"}
        }

    def _known_open_neighbors(self, cell: tuple[int, int], open_cells: set[tuple[int, int]]) -> list[tuple[int, int]]:
        neighbors: list[tuple[int, int]] = []
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            nxt = self._neighbor_for_move(cell, move)
            if nxt != cell and nxt in open_cells:
                neighbors.append(nxt)
        return neighbors

    def _build_structural_summary(self) -> dict:
        open_cells = self._known_open_cells()
        blocked_cells = {cell for cell, token in self.maze_known_cells.items() if token == "#"}

        known_total = len(open_cells) + len(blocked_cells)
        unknown_cells = max(0, (self.grid_cells * self.grid_cells) - known_total)

        frontier_cells = 0
        junction_cells = 0
        corridor_cells = 0
        dead_end_cells = 0
        edge_count = 0

        for cell in open_cells:
            row, col = cell
            unknown_neighbors = 0
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr = row + dr
                nc = col + dc
                if nr < 0 or nr >= self.grid_cells or nc < 0 or nc >= self.grid_cells:
                    continue
                if (nr, nc) not in self.maze_known_cells:
                    unknown_neighbors += 1
            if unknown_neighbors > 0:
                frontier_cells += 1

            neighbors = self._known_open_neighbors(cell, open_cells)
            degree = len(neighbors)
            edge_count += degree
            if degree >= 3:
                junction_cells += 1
            elif degree == 2:
                corridor_cells += 1
            elif degree <= 1:
                dead_end_cells += 1

        # Each undirected edge is counted twice in degree sum.
        undirected_edges = edge_count // 2
        nodes = len(open_cells)
        loop_estimate = max(0, undirected_edges - nodes + 1) if nodes > 0 else 0

        summary = {
            "open_cells": nodes,
            "blocked_cells": len(blocked_cells),
            "unknown_cells": unknown_cells,
            "frontier_cells": frontier_cells,
            "junction_cells": junction_cells,
            "corridor_cells": corridor_cells,
            "dead_end_cells": dead_end_cells,
            "loop_estimate": loop_estimate,
            "recent_path": list(self.maze_recent_cells),
        }
        return summary

    def _store_structural_memory_snapshot(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        try:
            summary = self._build_structural_summary()
            signature_payload = {
                "difficulty": self._normalized_maze_difficulty(),
                "grid_size": self.grid_cells,
                "start": self.episode_start_player_cell,
                "player": self.current_player_cell,
                "summary": summary,
            }
            signature = json.dumps(signature_payload, sort_keys=True)
            if signature == self._last_saved_structural_signature:
                return

            self._last_saved_structural_signature = signature
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO maze_structural_memory (
                        mode, difficulty, grid_size, start_cell, player_cell,
                        open_cells, blocked_cells, unknown_cells, frontier_cells,
                        junction_cells, corridor_cells, dead_end_cells, loop_estimate,
                        details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "maze",
                        self._normalized_maze_difficulty(),
                        self.grid_cells,
                        json.dumps(self.episode_start_player_cell),
                        json.dumps(self.current_player_cell),
                        int(summary["open_cells"]),
                        int(summary["blocked_cells"]),
                        int(summary["unknown_cells"]),
                        int(summary["frontier_cells"]),
                        int(summary["junction_cells"]),
                        int(summary["corridor_cells"]),
                        int(summary["dead_end_cells"]),
                        int(summary["loop_estimate"]),
                        json.dumps(summary, separators=(",", ":")),
                    ),
                )
                conn.commit()
            self._refresh_memory_viewer()
        except Exception:  # noqa: BLE001
            return

    def _sanitize_pattern_name(self, raw_name: str) -> str:
        name = (raw_name or "").strip()
        if not name:
            return ""
        name = re.sub(r"[^A-Za-z0-9 _\-/]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name[:40]

    def _local_planner_pattern_name(self, pattern_signature: str) -> str:
        if not pattern_signature:
            return "local-planner"
        try:
            payload = json.loads(pattern_signature)
        except Exception:  # noqa: BLE001
            return "local-planner"

        branch_profile = str(payload.get("branch_profile", "") or "")
        unknown_neighbors = int(payload.get("unknown_neighbors", 0) or 0)
        known_degree = int(payload.get("known_degree", 0) or 0)
        dead_end_risk = int(payload.get("dead_end_risk", 0) or 0)

        name = (
            f"kernel bp={branch_profile[:4]} "
            f"u={min(9, max(0, unknown_neighbors))} "
            f"k={min(9, max(0, known_degree))} "
            f"dr={min(9, max(0, dead_end_risk))}"
        ).strip()
        return self._sanitize_pattern_name(name) or "local-planner"

    def _current_pattern_signature(self, current_cell: tuple[int, int] | None = None) -> str:
        if self._normalized_layout_mode() != "maze":
            return ""
        current = current_cell if current_cell is not None else self.current_player_cell
        self._update_maze_known_map(current[0], current[1], radius=1, facing=self.player_facing)
        open_cells = self._known_open_cells()
        known_degree = len(self._known_open_neighbors(current, open_cells)) if current in open_cells else 0
        unknown_neighbors = self._unknown_neighbor_count(current)
        frontier_distance = min(6, self._frontier_distance(current, max_depth=6))
        visit_bucket = min(3, self.episode_visited_cells.get(current, 0))
        recent_backtrack = 1 if current == self.prev_prev_player_cell else 0
        dead_end_risk = 0
        row, col = current
        boundary_bucket = 1 if (row in {0, self.grid_cells - 1} or col in {0, self.grid_cells - 1}) else 0

        profile_tokens: list[str] = []
        visible_risky_branches = 0
        deterministic_dead_end_paths = 0
        max_dead_end_risk_depth = 0
        visible_dead_end_risk_depth = 0
        narrow_corridor_branches = 0
        for move in ["UP", "RIGHT", "DOWN", "LEFT"]:
            nxt = self._neighbor_for_move(current, move)
            if nxt == current or self._is_blocked_cell(nxt):
                profile_tokens.append("B")
                continue
            scan = self._directional_edge_scan(current[0], current[1], move)
            scan_clear_run = int(scan.get("clear_run", 0) or 0)
            scan_boxed = bool(scan.get("boxed_corridor_without_exit", False))
            scan_frontier = bool(scan.get("frontier_visible", False))
            scan_junction = bool(scan.get("junction_visible", False))
            scan_exit = bool(scan.get("exit_visible", False))
            scan_edge = str(scan.get("edge_type", ""))
            scan_boxed_side_steps = int(scan.get("boxed_side_steps", 0) or 0)
            scan_terminal = (
                scan_clear_run >= 1
                and scan_edge in {"blocked", "bounds", "occluded"}
                and (not scan_frontier)
                and (not scan_junction)
                and (not scan_exit)
            )
            scan_narrow = (
                scan_clear_run >= 2
                and scan_boxed_side_steps >= max(1, scan_clear_run - 1)
                and (not scan_junction)
                and (not scan_exit)
            )

            sampled_depth = self._dead_end_risk_depth(current, move)
            if sampled_depth > 0:
                deterministic_dead_end_paths += 1
                max_dead_end_risk_depth = max(max_dead_end_risk_depth, sampled_depth)

            if scan_boxed or scan_terminal:
                visible_risky_branches += 1
                visible_dead_end_risk_depth = max(visible_dead_end_risk_depth, scan_clear_run)
                profile_tokens.append("R")
                continue

            if scan_narrow:
                narrow_corridor_branches += 1

            unknown_n = self._unknown_neighbor_count(nxt)
            if unknown_n > 0:
                profile_tokens.append("U")
                continue
            profile_tokens.append("O")

        open_options = sum(1 for token in profile_tokens if token != "B")
        if open_options <= 1 and unknown_neighbors <= 2:
            dead_end_risk = max(dead_end_risk, 1)

        # Perception-first risk: if the current facing beam can already see a
        # boxed/terminal channel, mark dead-end pressure before reaching tip.
        facing_scan = self._directional_edge_scan(current[0], current[1], self.player_facing)
        facing_clear_run = int(facing_scan.get("clear_run", 0) or 0)
        facing_edge = str(facing_scan.get("edge_type", ""))
        facing_boxed_steps = int(facing_scan.get("boxed_side_steps", 0) or 0)
        facing_frontier = bool(facing_scan.get("frontier_visible", False))
        facing_junction = bool(facing_scan.get("junction_visible", False))
        facing_exit = bool(facing_scan.get("exit_visible", False))
        facing_boxed_channel = facing_boxed_steps >= max(1, facing_clear_run - 1)
        facing_terminal_seen = (
            facing_clear_run >= 1
            and facing_edge in {"blocked", "bounds", "occluded"}
            and (not facing_exit)
        )
        if facing_boxed_channel and facing_terminal_seen:
            dead_end_risk = max(dead_end_risk, 3 if facing_clear_run >= 2 else 2)
            visible_dead_end_risk_depth = max(visible_dead_end_risk_depth, facing_clear_run)
        elif facing_terminal_seen and (not facing_frontier) and (not facing_junction):
            dead_end_risk = max(dead_end_risk, 2)
            visible_dead_end_risk_depth = max(visible_dead_end_risk_depth, facing_clear_run)
        elif facing_boxed_channel and facing_clear_run >= 1 and (not facing_exit):
            dead_end_risk = max(dead_end_risk, 1)

        if known_degree <= 1 and unknown_neighbors <= 1:
            dead_end_risk = max(dead_end_risk, 1)
        if visible_risky_branches > 0:
            dead_end_risk = max(dead_end_risk, min(3, 1 + visible_risky_branches))
        if narrow_corridor_branches > 0:
            dead_end_risk = max(dead_end_risk, 1)
        if deterministic_dead_end_paths > 0:
            dead_end_risk = max(dead_end_risk, min(3, 1 + deterministic_dead_end_paths))
        if visible_dead_end_risk_depth > 0:
            dead_end_risk = max(dead_end_risk, min(3, 1 + (visible_dead_end_risk_depth // 2)))
        if known_degree <= 1 and unknown_neighbors == 0:
            dead_end_risk = max(dead_end_risk, 3)

        recent_transition_pressure = 0
        if self.maze_recent_transitions:
            for frm, to in list(self.maze_recent_transitions)[-self.recent_cycle_window :]:
                if frm == current or to == current:
                    recent_transition_pressure += 1
        transition_pressure_bucket = min(3, recent_transition_pressure // 2)
        signature_payload = {
            "difficulty": self._normalized_maze_difficulty(),
            "grid_size": self.grid_cells,
            "known_degree": known_degree,
            "unknown_neighbors": unknown_neighbors,
            "frontier_distance": frontier_distance,
            "visit_bucket": visit_bucket,
            "recent_backtrack": recent_backtrack,
            "dead_end_risk": dead_end_risk,
            "facing": self.player_facing,
            "boundary_bucket": boundary_bucket,
            "branch_profile": "".join(profile_tokens),
            "visible_risky_branches": visible_risky_branches,
            "dead_end_risk_depth": min(6, max(max_dead_end_risk_depth, visible_dead_end_risk_depth)),
            "transition_pressure_bucket": transition_pressure_bucket,
        }
        return json.dumps(signature_payload, sort_keys=True, separators=(",", ":"))

    def _canonical_pattern_signature(self, pattern_signature: str) -> str:
        if not pattern_signature:
            return ""
        try:
            payload = json.loads(pattern_signature)
        except Exception:  # noqa: BLE001
            return pattern_signature
        if not isinstance(payload, dict):
            return pattern_signature

        known_degree = int(payload.get("known_degree", 0) or 0)
        unknown_neighbors = int(payload.get("unknown_neighbors", 0) or 0)
        frontier_distance = int(payload.get("frontier_distance", 0) or 0)
        dead_end_risk = int(payload.get("dead_end_risk", 0) or 0)
        risk_depth = int(payload.get("dead_end_risk_depth", 0) or 0)
        visible_risky_branches = int(payload.get("visible_risky_branches", 0) or 0)
        transition_pressure_bucket = int(payload.get("transition_pressure_bucket", 0) or 0)

        if frontier_distance <= 0:
            frontier_bucket = 0
        elif frontier_distance <= 2:
            frontier_bucket = 1
        else:
            frontier_bucket = 2

        if risk_depth <= 0:
            risk_depth_bucket = 0
        elif risk_depth <= 2:
            risk_depth_bucket = 1
        else:
            risk_depth_bucket = 2

        canonical_payload = {
            "difficulty": str(payload.get("difficulty", self._normalized_maze_difficulty()) or ""),
            "grid_size": int(payload.get("grid_size", self.grid_cells) or self.grid_cells),
            "known_degree_bucket": min(3, max(0, known_degree)),
            "unknown_neighbors_bucket": min(2, max(0, unknown_neighbors)),
            "frontier_bucket": frontier_bucket,
            "dead_end_risk_bucket": min(3, max(0, dead_end_risk)),
            "risk_depth_bucket": risk_depth_bucket,
            "boundary_bucket": int(payload.get("boundary_bucket", 0) or 0),
            "branch_profile": str(payload.get("branch_profile", "") or ""),
            "visible_risky_branches_bucket": min(2, max(0, visible_risky_branches)),
            "transition_pressure_bucket": min(3, max(0, transition_pressure_bucket)),
        }
        return json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))

    def _pattern_catalog_context(self, limit: int = 10) -> str:
        if self._normalized_layout_mode() != "maze":
            return "(pattern catalog inactive outside maze mode)"
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT pattern_name, seen_count, pattern_signature
                    FROM maze_pattern_catalog
                    ORDER BY seen_count DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            if not rows:
                return "(no named patterns yet)"
            lines: list[str] = []
            for pattern_name, seen_count, pattern_signature in rows:
                lines.append(
                    f"- {pattern_name} (seen={seen_count}) signature={pattern_signature}"
                )
            return "\n".join(lines)
        except Exception:  # noqa: BLE001
            return "(pattern catalog unavailable)"

    def _record_pattern_name(self, pattern_signature: str, pattern_name: str, reason: str) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        pattern_signature = self._canonical_pattern_signature(pattern_signature)
        safe_name = self._sanitize_pattern_name(pattern_name)
        if not pattern_signature or not safe_name:
            return
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO maze_pattern_catalog (
                        pattern_signature, pattern_name, seen_count, last_reason, updated_at
                    ) VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(pattern_signature) DO UPDATE SET
                        pattern_name=excluded.pattern_name,
                        seen_count=maze_pattern_catalog.seen_count + 1,
                        last_reason=excluded.last_reason,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (pattern_signature, safe_name, (reason or "")[:280]),
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            return

    def _working_memory_snapshot(self, current_cell: tuple[int, int] | None = None) -> tuple[str, str]:
        if self._normalized_layout_mode() != "maze":
            return ("", "")
        cell = current_cell if current_cell is not None else self.current_player_cell
        row, col = cell
        signature = self._canonical_pattern_signature(self._current_pattern_signature(current_cell=cell))
        ascii_pattern = self._build_local_status_snapshot(row, col, radius=1, facing=self.player_facing)
        if self.working_memory_look_sweep and self.working_memory_look_sweep_step == self.memory_step_index:
            sections: list[str] = []
            for direction in ["UP", "RIGHT", "DOWN", "LEFT"]:
                payload = self.working_memory_look_sweep.get(direction)
                if not payload:
                    continue
                look_ascii = payload.get("ascii", "")
                if not look_ascii:
                    continue
                sections.append(f"[LOOK {direction}]\n{look_ascii}")
            if sections:
                ascii_pattern = f"{ascii_pattern}\n\n[LOOK SWEEP]\n" + "\n\n".join(sections)

        look_retention = max(0, int(self.working_memory_look_retention_steps))
        if look_retention > 0 and self.working_memory_look_history:
            recent_sections: list[str] = []
            for entry in reversed(self.working_memory_look_history):
                step = int(entry.get("step", -10_000))
                if self.memory_step_index - step > look_retention:
                    continue
                look_map = entry.get("look_ascii", {})
                if not isinstance(look_map, dict):
                    continue
                per_direction: list[str] = []
                for direction in ["UP", "RIGHT", "DOWN", "LEFT"]:
                    look_ascii = str(look_map.get(direction, "") or "")
                    if not look_ascii:
                        continue
                    per_direction.append(f"[LOOK {direction}]\n{look_ascii}")
                if not per_direction:
                    continue
                player_cell = str(entry.get("player_cell", ""))
                recent_sections.append(
                    f"[STEP {step} player_cell={player_cell}]\n" + "\n\n".join(per_direction)
                )

            if recent_sections:
                ascii_pattern = f"{ascii_pattern}\n\n[RECENT LOOK MEMORY]\n" + "\n\n".join(recent_sections)

        recent_action_rows = self._recent_action_outcome_rows(limit=3)
        cause_effect_recent_lines = [
            (
                f"step={step_index} action={action_taken} outcome={outcome_label} "
                f"reward={round(reward_signal, 2)} penalty={round(penalty_signal, 2)} "
                f"tags={reason_tags or '(none)'}"
            )
            for _created_at, step_index, action_taken, outcome_label, _outcome_value, reward_signal, penalty_signal, reason_tags, _player_cell, _details_json in recent_action_rows
        ]
        self.working_memory_active = {
            "signature": signature,
            "ascii": ascii_pattern,
            "player_cell": str(cell),
            "cause_effect_recent": "\n".join(cause_effect_recent_lines) if cause_effect_recent_lines else "",
        }
        if signature:
            # Avoid over-counting identical signatures from repeated UI refreshes
            # within the same step. Novelty should reflect traversal changes.
            if (
                signature != self._last_wm_signature_logged
                or self.memory_step_index != self._last_wm_signature_logged_step
            ):
                self.working_memory_recent_signatures.append(signature)
                self._last_wm_signature_logged = signature
                self._last_wm_signature_logged_step = self.memory_step_index
        return (signature, ascii_pattern)

    def _is_novel_for_stm(self, pattern_signature: str) -> bool:
        if not pattern_signature:
            return False
        recent = list(self.working_memory_recent_signatures)
        if not recent:
            return True
        # Novelty gate should be tolerant to repeated camera refreshes and only
        # suppress clearly repetitive signatures within the recent trajectory.
        window_size = 10
        repeat_allowance = 2
        if self._post_reset_stm_relax_remaining > 0:
            window_size = 14
            repeat_allowance = 4
        window = recent[-window_size:]
        return window.count(pattern_signature) <= repeat_allowance

    def _reinforce_stm_item(self, conn: sqlite3.Connection, pattern_signature: str) -> bool:
        row = conn.execute(
            """
            SELECT recall_count, strength
            FROM maze_short_term_memory
            WHERE pattern_signature = ?
            """,
            (pattern_signature,),
        ).fetchone()
        if not row:
            return False
        recall_count, strength = row
        conn.execute(
            """
            UPDATE maze_short_term_memory
            SET recall_count = ?,
                strength = ?,
                last_recalled_step = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE pattern_signature = ?
            """,
            (
                int(recall_count) + 1,
                float(strength) + self.stm_reinforce_alpha,
                self.memory_step_index,
                pattern_signature,
            ),
        )
        return True

    def _reinforce_semantic_item(self, conn: sqlite3.Connection, pattern_signature: str, pattern_name: str) -> bool:
        # Cooldown prevents one recurring signature from dominating semantic memory
        # and masking decision-context changes.
        last_step = self._semantic_reinforce_recent.get(pattern_signature, -10_000)
        if (self.memory_step_index - last_step) < self.semantic_reinforce_cooldown_steps:
            return False
        row = conn.execute(
            """
            SELECT recall_count, strength
            FROM maze_semantic_memory
            WHERE pattern_signature = ?
            """,
            (pattern_signature,),
        ).fetchone()
        if not row:
            return False
        recall_count, strength = row
        conn.execute(
            """
            UPDATE maze_semantic_memory
            SET pattern_name = ?,
                recall_count = ?,
                strength = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE pattern_signature = ?
            """,
            (
                pattern_name,
                int(recall_count) + 1,
                float(strength) + (self.stm_reinforce_alpha * 0.5),
                pattern_signature,
            ),
        )
        self._semantic_reinforce_recent[pattern_signature] = self.memory_step_index
        return True

    def _insert_stm_item(self, conn: sqlite3.Connection, pattern_signature: str, pattern_name: str, ascii_pattern: str) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO maze_short_term_memory (
                pattern_signature, pattern_name, ascii_pattern,
                recall_count, strength, created_step, last_recalled_step, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                pattern_signature,
                pattern_name,
                ascii_pattern,
                1,
                max(0.25, self.stm_reinforce_alpha),
                self.memory_step_index,
                self.memory_step_index,
            ),
        )

    def _stochastic_prune_unused_stm_on_access(
        self,
        conn: sqlite3.Connection,
        active_signature: str,
    ) -> int:
        chance = float(self.stm_access_unused_prune_chance)
        if chance <= 0.0:
            return 0

        rng = self._event_rng()
        if rng.random() >= chance:
            return 0

        min_age = max(1, int(self.stm_access_unused_prune_min_age_steps))
        max_rows = max(1, int(self.stm_access_unused_prune_max_rows))
        rows = conn.execute(
            """
            SELECT pattern_signature
            FROM maze_short_term_memory
            WHERE pattern_signature != ?
              AND (? - last_recalled_step) >= ?
            ORDER BY strength ASC, last_recalled_step ASC, updated_at ASC
            LIMIT ?
            """,
            (active_signature, int(self.memory_step_index), min_age, max_rows),
        ).fetchall()
        if not rows:
            return 0

        conn.executemany(
            "DELETE FROM maze_short_term_memory WHERE pattern_signature = ?",
            [(str(signature),) for (signature,) in rows],
        )
        return len(rows)

    def _run_stm_pruning_cycle(self) -> dict:
        result = {"promoted": 0, "pruned": 0}
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    UPDATE maze_short_term_memory
                    SET strength = strength * ?,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (self.stm_decay_rate,),
                )

                promote_rows = conn.execute(
                    """
                    SELECT pattern_signature, pattern_name, ascii_pattern, recall_count, strength
                    FROM maze_short_term_memory
                    WHERE strength >= ?
                    """,
                    (self.semantic_promotion_threshold,),
                ).fetchall()

                for pattern_signature, pattern_name, ascii_pattern, recall_count, strength in promote_rows:
                    conn.execute(
                        """
                        INSERT INTO maze_semantic_memory (
                            pattern_signature, pattern_name, ascii_pattern,
                            recall_count, strength, promoted_from_stm, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        ON CONFLICT(pattern_signature) DO UPDATE SET
                            pattern_name = excluded.pattern_name,
                            ascii_pattern = excluded.ascii_pattern,
                            recall_count = maze_semantic_memory.recall_count + excluded.recall_count,
                            strength = max(maze_semantic_memory.strength, excluded.strength),
                            promoted_from_stm = maze_semantic_memory.promoted_from_stm + 1,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (pattern_signature, pattern_name, ascii_pattern, int(recall_count), float(strength)),
                    )
                result["promoted"] = len(promote_rows)

                pruned_rows = conn.execute(
                    "DELETE FROM maze_short_term_memory WHERE strength < ?",
                    (self.stm_prune_threshold,),
                )
                result["pruned"] = int(pruned_rows.rowcount or 0)
                conn.execute(
                    "DELETE FROM maze_short_term_memory WHERE strength >= ?",
                    (self.semantic_promotion_threshold,),
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            return {"promoted": 0, "pruned": 0}
        return result

    def _process_pattern_memory(self, pattern_name: str) -> str:
        if self._normalized_layout_mode() != "maze":
            decision = "memory:inactive"
            self._append_memory_log(decision)
            return decision
        safe_name = self._sanitize_pattern_name(pattern_name)
        if not safe_name:
            decision = "memory:no-pattern-name"
            self._append_memory_log(decision)
            return decision

        pattern_signature = self.working_memory_active.get("signature", "")
        ascii_pattern = self.working_memory_active.get("ascii", "")
        if not pattern_signature or not ascii_pattern:
            pattern_signature, ascii_pattern = self._working_memory_snapshot()
        pattern_signature = self._canonical_pattern_signature(pattern_signature)
        if not pattern_signature:
            decision = "memory:no-signature"
            self._append_memory_log(decision)
            return decision

        decision = ""

        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                in_stm = self._reinforce_stm_item(conn, pattern_signature)
                in_semantic = self._reinforce_semantic_item(conn, pattern_signature, safe_name)

                if in_semantic:
                    decision = "semantic:reinforced"
                elif in_stm:
                    decision = "stm:reinforced"
                elif self._is_novel_for_stm(pattern_signature):
                    self._insert_stm_item(conn, pattern_signature, safe_name, ascii_pattern)
                    decision = "novel->stm"
                else:
                    # Periodically re-sample familiar signatures into STM so memory
                    # can recover from over-pruning in repetitive corridors.
                    interval = max(0, int(self.stm_familiar_resample_interval))
                    if interval > 0 and (self.memory_step_index % interval == 0):
                        self._insert_stm_item(conn, pattern_signature, safe_name, ascii_pattern)
                        decision = "familiar->stm-resample"
                    else:
                        decision = "familiar->pruned"

                access_pruned = self._stochastic_prune_unused_stm_on_access(conn, pattern_signature)
                if access_pruned > 0:
                    decision += f"|access_pruned={access_pruned}"

                conn.commit()
        except Exception:  # noqa: BLE001
            decision = "memory:error"
            self._append_memory_log(decision)
            return decision

        prune_result = {"promoted": 0, "pruned": 0}
        if (self.memory_step_index - self._last_stm_pruning_step) >= self.stm_pruning_interval_steps:
            prune_result = self._run_stm_pruning_cycle()
            self._last_stm_pruning_step = self.memory_step_index
        promoted = int(prune_result.get("promoted", 0) or 0)
        pruned = int(prune_result.get("pruned", 0) or 0)
        if promoted > 0:
            decision += f"|promoted={promoted}"
        if pruned > 0:
            decision += f"|pruned={pruned}"
        final_decision = decision or "memory:noop"
        self._append_memory_log(
            f"pattern_name={safe_name} decision={final_decision} signature={pattern_signature}"
        )
        return final_decision

    def _clear_working_memory(self) -> None:
        self.working_memory_active = {}
        self.working_memory_look_sweep = {}
        self.working_memory_look_sweep_step = -1
        self.working_memory_look_history.clear()
        self.working_memory_recent_signatures.clear()

    def _archive_working_memory_look_sweep(self) -> None:
        if not self.working_memory_look_sweep:
            return
        look_ascii: dict[str, str] = {}
        for direction in ["UP", "RIGHT", "DOWN", "LEFT"]:
            payload = self.working_memory_look_sweep.get(direction)
            if not payload:
                continue
            ascii_pattern = str(payload.get("ascii", "") or "")
            if not ascii_pattern:
                continue
            look_ascii[direction] = ascii_pattern
        if not look_ascii:
            return
        self.working_memory_look_history.append(
            {
                "step": self.memory_step_index,
                "player_cell": str(self.current_player_cell),
                "look_ascii": look_ascii,
            }
        )

    def _clear_working_memory_look_sweep(self, keep_recent: bool = True) -> None:
        if keep_recent:
            self._archive_working_memory_look_sweep()
        self.working_memory_look_sweep = {}
        self.working_memory_look_sweep_step = -1

    def _capture_working_memory_look_snapshot(self, facing: str) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        direction = (facing or "").strip().upper()
        if direction not in {"UP", "RIGHT", "DOWN", "LEFT"}:
            return

        signature = self.working_memory_active.get("signature", "")
        ascii_pattern = self.working_memory_active.get("ascii", "")
        if not signature or not ascii_pattern:
            return

        if self.working_memory_look_sweep_step != self.memory_step_index:
            self.working_memory_look_sweep = {}
            self.working_memory_look_sweep_step = self.memory_step_index

        self.working_memory_look_sweep[direction] = {
            "signature": signature,
            "ascii": ascii_pattern,
        }

    def _append_memory_log(self, message: str) -> None:
        self.memory_event_log.append(f"step={self.memory_step_index} {message}")

    def _endocrine_delta_text(self, before: dict[str, float], after: dict[str, float]) -> str:
        fields = ["stress", "curiosity", "confidence", "fatigue", "reward"]
        deltas: list[str] = []
        for field in fields:
            prev = float(before.get(field, 0.0))
            curr = float(after.get(field, 0.0))
            delta = curr - prev
            if abs(delta) >= 0.0005:
                deltas.append(f"{field}:{delta:+.3f}")
        return " ".join(deltas)

    def _append_endocrine_event(self, source: str, detail: str) -> None:
        text = (detail or "").strip()
        if not text:
            return
        event_line = f"step={self.memory_step_index} source={source} {text}"
        self.endocrine_event_log.append(event_line)
        self._append_memory_log(f"endocrine_event source={source} {text}")

    def _record_action_outcome_memory(
        self,
        action_taken: str,
        outcome_value: float,
        reward_signal: float,
        penalty_signal: float,
        reason_tags: list[str] | tuple[str, ...] | None = None,
        details: dict | None = None,
        player_cell: tuple[int, int] | None = None,
    ) -> None:
        action = (action_taken or "").strip().upper() or "UNKNOWN_ACTION"
        mode = self._normalized_layout_mode()
        difficulty = self._normalized_maze_difficulty() if mode == "maze" else "n/a"
        cell = player_cell if player_cell is not None else self.current_player_cell
        tags = [str(tag).strip() for tag in (reason_tags or []) if str(tag).strip()]
        tag_text = ",".join(tags[:12])
        outcome_score = float(outcome_value)
        reward_value = max(0.0, float(reward_signal))
        penalty_value = max(0.0, float(penalty_signal))
        if outcome_score >= 0.01:
            outcome_label = "reward"
        elif outcome_score <= -0.01:
            outcome_label = "punishment"
        else:
            outcome_label = "neutral"

        details_payload = details or {}
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO maze_action_outcome_memory (
                        maze_layout_id,
                        step_index,
                        mode,
                        difficulty,
                        player_cell,
                        action_taken,
                        outcome_label,
                        outcome_value,
                        reward_signal,
                        penalty_signal,
                        reason_tags,
                        details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(self.current_maze_episode_id),
                        int(self.memory_step_index),
                        mode,
                        difficulty,
                        json.dumps(cell),
                        action,
                        outcome_label,
                        float(round(outcome_score, 4)),
                        float(round(reward_value, 4)),
                        float(round(penalty_value, 4)),
                        tag_text,
                        json.dumps(details_payload, separators=(",", ":")),
                    ),
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            return

        self._process_cause_effect_memory(
            action_taken=action,
            reason_tags=tags,
            outcome_score=outcome_score,
            details=details_payload,
        )

        if self.endocrine_enabled:
            before_state = self.endocrine.state()
            self.endocrine.update_from_outcome(
                outcome_value=outcome_score,
                reward_signal=reward_value,
                penalty_signal=penalty_value,
                tags=tags,
            )
            after_state = self.endocrine.state()
            delta_text = self._endocrine_delta_text(before_state, after_state)
            tag_summary = ",".join(tags[:6]) if tags else "none"
            self._append_endocrine_event(
                "outcome",
                (
                    f"delta=[{delta_text or 'none'}] outcome={round(outcome_score, 2)} "
                    f"reward={round(reward_value, 2)} penalty={round(penalty_value, 2)} tags={tag_summary}"
                ),
            )

        from_cell_obj = details_payload.get("from_cell")
        to_cell_obj = details_payload.get("to_cell")
        from_cell: tuple[int, int] | None = None
        to_cell: tuple[int, int] | None = None
        if isinstance(from_cell_obj, (list, tuple)) and len(from_cell_obj) == 2:
            try:
                from_cell = (int(from_cell_obj[0]), int(from_cell_obj[1]))
            except Exception:  # noqa: BLE001
                from_cell = None
        if isinstance(to_cell_obj, (list, tuple)) and len(to_cell_obj) == 2:
            try:
                to_cell = (int(to_cell_obj[0]), int(to_cell_obj[1]))
            except Exception:  # noqa: BLE001
                to_cell = None
        self._register_transition_trap_event(
            from_cell=from_cell,
            to_cell=to_cell,
            reason_tags=tags,
            outcome_score=outcome_score,
        )

        self._append_memory_log(
            f"cause_effect action={action} outcome={outcome_label} "
            f"reward={round(reward_value, 2)} penalty={round(penalty_value, 2)} tags={tag_text or '(none)'}"
        )

        self._record_reset_trace_event(
            action=action,
            outcome_score=outcome_score,
            reward_value=reward_value,
            penalty_value=penalty_value,
            tags=tags,
            from_cell=from_cell,
            to_cell=to_cell,
        )

    def _record_reset_trace_event(
        self,
        *,
        action: str,
        outcome_score: float,
        reward_value: float,
        penalty_value: float,
        tags: list[str],
        from_cell: tuple[int, int] | None,
        to_cell: tuple[int, int] | None,
    ) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        self._reset_trace.append(
            {
                "step": int(self.memory_step_index),
                "action": str(action),
                "outcome": float(outcome_score),
                "reward": float(reward_value),
                "penalty": float(penalty_value),
                "tags": list(tags[:12]),
                "from_cell": from_cell,
                "to_cell": to_cell,
            }
        )

    def _capture_post_reset_learning(self) -> None:
        if self._normalized_layout_mode() != "maze":
            return

        exhausted_cells: set[tuple[int, int]] = set(list(self.maze_recent_cells)[-self._reset_trace_window :])
        exhausted_transitions: set[tuple[tuple[int, int], tuple[int, int]]] = set(
            list(self.maze_recent_transitions)[-self._reset_trace_window :]
        )

        for cell, visits in self.episode_visited_cells.items():
            if int(visits) < 2:
                continue
            if cell not in self.maze_known_cells:
                continue
            if self._unknown_neighbor_count(cell) == 0:
                exhausted_cells.add(cell)

        failure_tag_set = {
            "cycle_pair",
            "transition_repeat",
            "dead_end_entrance_revisit",
            "visible_terminal",
            "boxed_corridor",
            "immediate_backtrack",
            "branch_diversity",
        }

        for event in list(self._reset_trace)[-self._reset_trace_window :]:
            try:
                outcome_score = float(event.get("outcome", 0.0) or 0.0)
            except Exception:  # noqa: BLE001
                outcome_score = 0.0
            event_tags = {str(tag) for tag in event.get("tags", []) if str(tag)}
            from_cell = event.get("from_cell")
            to_cell = event.get("to_cell")
            transition = None
            if isinstance(from_cell, tuple) and isinstance(to_cell, tuple):
                transition = (from_cell, to_cell)

            if outcome_score <= -1.0 and (event_tags & failure_tag_set):
                if isinstance(to_cell, tuple):
                    self._post_reset_cell_failure_counts[to_cell] = (
                        int(self._post_reset_cell_failure_counts.get(to_cell, 0) or 0) + 1
                    )
                    exhausted_cells.add(to_cell)
                if transition is not None:
                    self._post_reset_transition_failure_counts[transition] = (
                        int(self._post_reset_transition_failure_counts.get(transition, 0) or 0) + 1
                    )
                    exhausted_transitions.add(transition)
            elif outcome_score >= 1.0 and transition is not None:
                self._post_reset_transition_success_counts[transition] = (
                    int(self._post_reset_transition_success_counts.get(transition, 0) or 0) + 1
                )

        self._post_reset_exhausted_cells.update(exhausted_cells)
        self._post_reset_exhausted_transitions.update(exhausted_transitions)

    def _vector_norm(self, vector: list[float]) -> list[float]:
        if not vector:
            return []
        norm = math.sqrt(sum((value * value) for value in vector))
        if norm <= 1e-9:
            return [0.0 for _ in vector]
        return [value / norm for value in vector]

    def _token_to_index(self, token: str) -> int:
        return abs(hash(token)) % self.cause_effect_vector_dim

    def _cause_effect_vector(self, action_taken: str, reason_tags: list[str], details: dict | None) -> list[float]:
        vec = [0.0 for _ in range(self.cause_effect_vector_dim)]
        tokens = [f"action:{action_taken.upper()}"]
        for tag in reason_tags[:12]:
            tokens.append(f"tag:{tag}")
        detail_payload = details or {}
        edge_type = str(detail_payload.get("edge_type", "") or "")
        if edge_type:
            tokens.append(f"edge:{edge_type}")
        unknown_neighbors = int(detail_payload.get("unknown_neighbors", 0) or 0)
        open_degree = int(detail_payload.get("open_degree", 0) or 0)
        frontier_distance = int(detail_payload.get("frontier_distance", 0) or 0)
        tokens.extend(
            [
                f"unknown_bucket:{min(3, max(0, unknown_neighbors))}",
                f"degree_bucket:{min(4, max(0, open_degree))}",
                f"frontier_bucket:{min(6, max(0, frontier_distance))}",
                f"difficulty:{self._normalized_maze_difficulty()}",
            ]
        )
        for token in tokens:
            idx = self._token_to_index(token)
            vec[idx] += 1.0
        return self._vector_norm(vec)

    def _vector_cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        return float(sum((x * y) for x, y in zip(a, b)))

    def _parse_vector_json(self, payload: str) -> list[float]:
        try:
            vec = json.loads(payload)
            if not isinstance(vec, list):
                return []
            parsed = [float(value) for value in vec]
            if len(parsed) != self.cause_effect_vector_dim:
                return []
            return parsed
        except Exception:  # noqa: BLE001
            return []

    def _cause_effect_key(self, action_taken: str, reason_tags: list[str], details: dict | None = None) -> str:
        normalized_tags = sorted({tag.strip().lower() for tag in reason_tags if tag.strip()})
        detail_payload = details or {}
        edge_type = str(detail_payload.get("edge_type", "") or "")
        unknown_neighbors = int(detail_payload.get("unknown_neighbors", 0) or 0)
        open_degree = int(detail_payload.get("open_degree", 0) or 0)
        frontier_distance = int(detail_payload.get("frontier_distance", 0) or 0)
        key_payload = {
            "action": action_taken.upper(),
            "difficulty": self._normalized_maze_difficulty(),
            "tags": normalized_tags[:6],
            "edge": edge_type[:16],
            "unknown_bucket": min(3, max(0, unknown_neighbors)),
            "degree_bucket": min(4, max(0, open_degree)),
            "frontier_bucket": min(6, max(0, frontier_distance)),
        }
        return json.dumps(key_payload, sort_keys=True, separators=(",", ":"))

    def _process_cause_effect_memory(
        self,
        action_taken: str,
        reason_tags: list[str],
        outcome_score: float,
        details: dict,
    ) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        cause_key = self._cause_effect_key(action_taken, reason_tags, details)
        vector = self._cause_effect_vector(action_taken, reason_tags, details)
        vector_json = json.dumps(vector, separators=(",", ":"))
        tag_text = ",".join(sorted({tag.strip() for tag in reason_tags if tag.strip()}))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                sem_row = conn.execute(
                    """
                    SELECT recall_count, strength, avg_outcome
                    FROM maze_cause_effect_semantic
                    WHERE cause_key = ?
                    """,
                    (cause_key,),
                ).fetchone()
                if sem_row:
                    recall_count, strength, avg_outcome = sem_row
                    next_recall = int(recall_count) + 1
                    next_avg = ((float(avg_outcome) * int(recall_count)) + float(outcome_score)) / max(1, next_recall)
                    conn.execute(
                        """
                        UPDATE maze_cause_effect_semantic
                        SET avg_outcome = ?,
                            recall_count = ?,
                            strength = ?,
                            vector_json = ?,
                            reason_tags = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE cause_key = ?
                        """,
                        (
                            float(next_avg),
                            next_recall,
                            float(strength) + (self.stm_reinforce_alpha * 0.5),
                            vector_json,
                            tag_text,
                            cause_key,
                        ),
                    )
                else:
                    stm_row = conn.execute(
                        """
                        SELECT recall_count, strength, avg_outcome
                        FROM maze_cause_effect_stm
                        WHERE cause_key = ?
                        """,
                        (cause_key,),
                    ).fetchone()
                    if stm_row:
                        recall_count, strength, avg_outcome = stm_row
                        next_recall = int(recall_count) + 1
                        next_avg = ((float(avg_outcome) * int(recall_count)) + float(outcome_score)) / max(1, next_recall)
                        conn.execute(
                            """
                            UPDATE maze_cause_effect_stm
                            SET avg_outcome = ?,
                                recall_count = ?,
                                strength = ?,
                                vector_json = ?,
                                reason_tags = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE cause_key = ?
                            """,
                            (
                                float(next_avg),
                                next_recall,
                                float(strength) + self.stm_reinforce_alpha,
                                vector_json,
                                tag_text,
                                cause_key,
                            ),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO maze_cause_effect_stm (
                                cause_key, action_taken, reason_tags, vector_json,
                                avg_outcome, recall_count, strength, updated_at
                            ) VALUES (?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                            """,
                            (
                                cause_key,
                                action_taken.upper(),
                                tag_text,
                                vector_json,
                                float(outcome_score),
                                max(0.25, self.stm_reinforce_alpha),
                            ),
                        )
                conn.commit()
        except Exception:  # noqa: BLE001
            return
        self._run_cause_effect_pruning_cycle()

    def _run_cause_effect_pruning_cycle(self) -> None:
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                conn.execute(
                    """
                    UPDATE maze_cause_effect_stm
                    SET strength = strength * ?,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (self.stm_decay_rate,),
                )
                promote_rows = conn.execute(
                    """
                    SELECT cause_key, action_taken, reason_tags, vector_json,
                           avg_outcome, recall_count, strength
                    FROM maze_cause_effect_stm
                    WHERE strength >= ?
                    """,
                    (self.semantic_promotion_threshold,),
                ).fetchall()
                for row in promote_rows:
                    conn.execute(
                        """
                        INSERT INTO maze_cause_effect_semantic (
                            cause_key, action_taken, reason_tags, vector_json,
                            avg_outcome, recall_count, strength, promoted_from_stm, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                        ON CONFLICT(cause_key) DO UPDATE SET
                            action_taken = excluded.action_taken,
                            reason_tags = excluded.reason_tags,
                            vector_json = excluded.vector_json,
                            avg_outcome = (maze_cause_effect_semantic.avg_outcome + excluded.avg_outcome) / 2.0,
                            recall_count = maze_cause_effect_semantic.recall_count + excluded.recall_count,
                            strength = max(maze_cause_effect_semantic.strength, excluded.strength),
                            promoted_from_stm = maze_cause_effect_semantic.promoted_from_stm + 1,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        row,
                    )
                conn.execute(
                    "DELETE FROM maze_cause_effect_stm WHERE strength >= ?",
                    (self.semantic_promotion_threshold,),
                )
                conn.execute(
                    "DELETE FROM maze_cause_effect_stm WHERE strength < ?",
                    (self.stm_prune_threshold,),
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            return

    def _cause_effect_retrieval_signal(
        self,
        move: str,
        reason_tags: list[str],
        details: dict,
    ) -> tuple[float, float, list[str]]:
        action_key = f"MOVE_{str(move or '').strip().upper()}"
        query_vec = self._cause_effect_vector(f"MOVE_{move}", reason_tags, details)
        if not query_vec:
            return (0.0, 0.0, [])

        scored: list[tuple[float, float, float, str]] = []
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                stm_rows = conn.execute(
                    """
                    SELECT action_taken, vector_json, avg_outcome, strength, reason_tags
                    FROM maze_cause_effect_stm
                    ORDER BY updated_at DESC
                    LIMIT 48
                    """
                ).fetchall()
                sem_rows = conn.execute(
                    """
                    SELECT action_taken, vector_json, avg_outcome, strength, reason_tags
                    FROM maze_cause_effect_semantic
                    ORDER BY updated_at DESC
                    LIMIT 48
                    """
                ).fetchall()
        except Exception:  # noqa: BLE001
            return (0.0, 0.0, [])

        for action_taken, vector_json, avg_outcome, strength, tags in [*sem_rows, *stm_rows]:
            if str(action_taken or "").strip().upper() != action_key:
                continue
            vec = self._parse_vector_json(vector_json)
            if not vec:
                continue
            sim = self._vector_cosine(query_vec, vec)
            if sim < self.cause_effect_retrieval_min_similarity:
                continue
            scored.append((sim, float(avg_outcome), float(strength), str(tags or "")))

        if not scored:
            return (0.0, 0.0, [])

        scored.sort(key=lambda item: item[0] * item[2], reverse=True)
        top_rows = scored[: self.cause_effect_retrieval_top_k]
        weighted_sum = 0.0
        total_weight = 0.0
        tag_accumulator: dict[str, float] = {}
        risk_tags = {
            "dead_end_slap",
            "dead_end_tip_revisit",
            "dead_end_entrance_revisit",
            "transition_repeat",
            "cycle_pair",
            "visible_terminal",
            "boxed_corridor",
            "immediate_backtrack",
            "branch_diversity",
        }
        positive_tags = {
            "novelty_reward",
            "visible_open_decision",
            "visible_exit",
            "frontier_visible",
            "junction_visible",
        }
        query_tags = {tag.strip() for tag in reason_tags if tag and tag.strip()}
        query_has_risk = any(tag in risk_tags for tag in query_tags)
        edge_type = str((details or {}).get("edge_type", "") or "")
        query_is_terminal_edge = edge_type in {"blocked", "bounds", "occluded"}
        query_is_risky_context = query_has_risk or query_is_terminal_edge
        for sim, avg_outcome, strength, tags in top_rows:
            weight = max(0.0, sim) * max(0.05, strength)
            tags_list = [part.strip() for part in tags.split(",") if part.strip()]
            row_tags = set(tags_list)
            has_risk = any(tag in risk_tags for tag in tags_list)
            has_positive = any(tag in positive_tags for tag in tags_list)
            adjusted_outcome = avg_outcome
            tag_overlap = row_tags.intersection(query_tags)

            if query_is_risky_context and not tag_overlap:
                # In risky contexts, suppress unrelated rows, especially positive ones.
                if adjusted_outcome > 0:
                    continue
                weight *= 0.35

            if query_has_risk and (not has_risk):
                # In trap-like queries, positive-only histories should not dominate.
                weight *= 0.2

            if adjusted_outcome > 0 and has_risk and not has_positive:
                # Legacy data may contain risky-only tags with positive outcomes.
                # Ignore those rows so retrieval does not reward trap contexts.
                adjusted_outcome = 0.0
            elif adjusted_outcome > 0 and has_risk and has_positive:
                # Mixed rows are allowed but positive signal is damped.
                adjusted_outcome *= 0.25

            if query_has_risk and adjusted_outcome > 0 and not row_tags.intersection(risk_tags):
                # Suppress positive carryover from safe contexts in risky queries.
                adjusted_outcome = 0.0

            if (not query_has_risk) and adjusted_outcome < 0 and row_tags.intersection(risk_tags):
                # Avoid over-penalizing in clearly safer query contexts.
                adjusted_outcome *= 0.45

            weighted_sum += adjusted_outcome * weight
            total_weight += weight
            for tag in tags_list:
                if query_is_risky_context and tag_overlap and tag not in query_tags and tag not in risk_tags:
                    # Keep risky-context debug tags focused on relevant/risk signals.
                    continue
                tag_accumulator[tag] = tag_accumulator.get(tag, 0.0) + weight

        if total_weight <= 1e-9:
            return (0.0, 0.0, [])

        blended_outcome = weighted_sum / total_weight
        scaled = blended_outcome * max(0.0, self.cause_effect_memory_weight)
        penalty = max(0.0, -scaled)
        reward = max(0.0, scaled)
        if query_is_risky_context and reward > 0.0:
            # Terminal/boxed/dead-end contexts should not receive strong positive memory boosts.
            reward *= 0.05
        ranked_tags = sorted(tag_accumulator.items(), key=lambda item: item[1], reverse=True)
        return (penalty, reward, [tag for tag, _weight in ranked_tags[:4]])

    def _recent_action_outcome_rows(self, limit: int = 8) -> list[tuple]:
        capped_limit = max(1, min(200, int(limit)))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT created_at, step_index, action_taken, outcome_label,
                           outcome_value, reward_signal, penalty_signal, reason_tags,
                           player_cell, details_json
                    FROM maze_action_outcome_memory
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (capped_limit,),
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _run_action_outcome_rows(self, maze_layout_id: int, limit: int = 600) -> list[tuple]:
        capped_limit = max(1, min(2000, int(limit)))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT created_at, maze_layout_id, step_index, action_taken, outcome_label,
                           outcome_value, reward_signal, penalty_signal, reason_tags,
                           player_cell, details_json
                    FROM maze_action_outcome_memory
                    WHERE maze_layout_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (int(maze_layout_id), capped_limit),
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _run_prediction_rows(self, maze_layout_id: int, limit: int = 1200) -> list[tuple]:
        capped_limit = max(1, min(5000, int(limit)))
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT created_at, step_created, step_resolved, cell_row, cell_col,
                           predicted_label, predicted_shape, confidence,
                           prediction_context_key, confidence_bucket, resolution_status, expiry_reason,
                           actual_label, actual_shape, is_correct, is_shape_correct,
                           occupancy_brier, shape_brier,
                           occupancy_score_delta, shape_score_delta, score_delta
                    FROM maze_prediction_memory
                    WHERE maze_layout_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (int(maze_layout_id), capped_limit),
                ).fetchall()
            return rows
        except Exception:  # noqa: BLE001
            return []

    def _memory_log_text_for_step_range(self, step_min: int, step_max: int) -> str:
        if step_max < step_min:
            return "(no memory log events for run)"
        filtered: list[str] = []
        for line in self.memory_event_log:
            match = re.match(r"step=(\d+)\s", line)
            if not match:
                continue
            step_index = int(match.group(1))
            if step_min <= step_index <= step_max:
                filtered.append(line)
        return "\n".join(filtered) if filtered else "(no memory log events for run)"

    def _memory_export_text_for_run(self, maze_layout_id: int) -> str:
        run_id = int(maze_layout_id)
        action_rows = self._run_action_outcome_rows(run_id)
        prediction_rows = self._run_prediction_rows(run_id)
        if not action_rows and not prediction_rows:
            return f"[RUN LOGS]\nmaze_layout_id={run_id}\n(no rows found)"

        step_values = [int(row[2]) for row in action_rows if len(row) > 2]
        if step_values:
            step_min = min(step_values)
            step_max = max(step_values)
        else:
            created_steps = [int(row[1]) for row in prediction_rows if len(row) > 1 and row[1] is not None]
            resolved_steps = [int(row[2]) for row in prediction_rows if len(row) > 2 and row[2] is not None]
            all_steps = created_steps + resolved_steps
            step_min = min(all_steps) if all_steps else 0
            step_max = max(all_steps) if all_steps else 0

        action_text = "\n".join(
            (
                f"[{created_at}] step={step_index} action={action_taken} outcome={outcome_label} "
                f"value={round(float(outcome_value or 0.0), 2)} reward={round(float(reward_signal or 0.0), 2)} "
                f"penalty={round(float(penalty_signal or 0.0), 2)} tags={reason_tags or '(none)'} "
                f"cell={player_cell}"
            )
            for created_at, _maze_layout_id, step_index, action_taken, outcome_label, outcome_value, reward_signal, penalty_signal, reason_tags, player_cell, _details_json in action_rows
        ) or "(none)"

        prediction_text = "\n".join(
            (
                f"[{created_at}] step={step_created}->{step_resolved if step_resolved is not None else '?'} "
                f"cell=({cell_row},{cell_col}) pred={predicted_label}/{predicted_shape} "
                f"actual={(actual_label or '?')}/{(actual_shape or '?')} conf={round(float(confidence or 0.0), 3)} "
                f"ctx={prediction_context_key or '(none)'} conf_bin={self._prediction_bucket_label(int(confidence_bucket or 0))} "
                f"status={resolution_status or 'pending'} expiry={expiry_reason or '(none)'} "
                f"occ={'yes' if int(is_correct or 0) == 1 else 'no' if actual_label else 'pending'} "
                f"shape={'yes' if int(is_shape_correct or 0) == 1 else 'no' if actual_shape else 'pending'} "
                f"brier_occ={round(float(occupancy_brier or 0.0), 3)} brier_shape={round(float(shape_brier or 0.0), 3)} "
                f"score_occ={round(float(occupancy_score_delta or 0.0), 3)} "
                f"score_shape={round(float(shape_score_delta or 0.0), 3)} score_total={round(float(score_delta or 0.0), 3)}"
            )
            for created_at, step_created, step_resolved, cell_row, cell_col, predicted_label, predicted_shape, confidence, prediction_context_key, confidence_bucket, resolution_status, expiry_reason, actual_label, actual_shape, is_correct, is_shape_correct, occupancy_brier, shape_brier, occupancy_score_delta, shape_score_delta, score_delta in prediction_rows
        ) or "(none)"

        memory_logs = self._memory_log_text_for_step_range(step_min, step_max)
        return (
            "[RUN LOGS]\n"
            f"maze_layout_id={run_id}\n"
            f"step_range={step_min}-{step_max}\n\n"
            "[Action Outcomes]\n"
            f"{action_text}\n\n"
            "[Predictive Memory]\n"
            f"{prediction_text}\n\n"
            "[Memory Logs]\n"
            f"{memory_logs}"
        )

    def _memory_log_text(self, limit: int | None = 200) -> str:
        if not self.memory_event_log:
            return "(no memory log events yet)"
        events = list(self.memory_event_log)
        if isinstance(limit, int) and limit > 0:
            events = events[-limit:]
        return "\n".join(events)

    def _tail_text_lines(self, text: str, limit: int) -> tuple[str, int, bool]:
        if not text:
            return ("", 0, False)
        lines = text.splitlines()
        total = len(lines)
        capped_limit = max(1, int(limit))
        if total <= capped_limit:
            return ("\n".join(lines), total, False)
        return ("\n".join(lines[-capped_limit:]), total, True)

    def _memory_export_text(self) -> str:
        memory_text = self._maze_memory_view_text(limit=self.memory_export_section_limit, compact=True)
        memory_logs = self._memory_log_text(limit=self.memory_export_log_limit)
        memory_log_total = len(self.memory_event_log)
        debug_text = self.debug_output.get("1.0", tk.END).strip() if hasattr(self, "debug_output") else ""
        debug_tail, debug_total, debug_truncated = self._tail_text_lines(debug_text, self.memory_export_debug_limit)
        memory_header = f"[MEMORY] (top {self.memory_export_section_limit} rows per persisted section)"
        memory_logs_header = "[MEMORY LOGS]"
        if memory_log_total > self.memory_export_log_limit:
            memory_logs_header = (
                f"[MEMORY LOGS] (showing last {self.memory_export_log_limit} of {memory_log_total} events)"
            )
        pipeline_header = "[PIPELINE DEBUG]"
        if debug_truncated:
            pipeline_header = (
                f"[PIPELINE DEBUG] (showing last {self.memory_export_debug_limit} of {debug_total} lines)"
            )
        return (
            f"{memory_header}\n"
            f"{memory_text or '(empty)'}\n\n"
            f"{memory_logs_header}\n"
            f"{redact_secrets(memory_logs) or '(empty)'}\n\n"
            f"{pipeline_header}\n"
            f"{redact_secrets(debug_tail) or '(empty)'}"
        )

    def _on_shutdown(self) -> None:
        # Final decay/prune/promote pass before app exit.
        self._run_stm_pruning_cycle()
        self._clear_working_memory()
        self.root.destroy()

    def _maze_memory_context(self) -> str:
        if self._normalized_layout_mode() != "maze":
            return ""
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                structural = conn.execute(
                    """
                    SELECT difficulty, grid_size, start_cell, player_cell, open_cells, blocked_cells,
                           unknown_cells, frontier_cells, junction_cells, corridor_cells, dead_end_cells,
                           loop_estimate
                    FROM maze_structural_memory
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
                stm_rows = conn.execute(
                    """
                    SELECT pattern_name, pattern_signature, strength, recall_count
                    FROM maze_short_term_memory
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT 5
                    """
                ).fetchall()
                semantic_rows = conn.execute(
                    """
                    SELECT pattern_name, pattern_signature, strength, recall_count
                    FROM maze_semantic_memory
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT 5
                    """
                ).fetchall()
                action_rows = conn.execute(
                    """
                    SELECT step_index, action_taken, outcome_label, reward_signal,
                           penalty_signal, reason_tags
                    FROM maze_action_outcome_memory
                    ORDER BY id DESC
                    LIMIT 6
                    """
                ).fetchall()
                layout_recall_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_cells,
                        SUM(CASE WHEN cell_token = '#' THEN 1 ELSE 0 END) AS blocked_cells,
                        SUM(CASE WHEN cell_token = '.' THEN 1 ELSE 0 END) AS open_cells,
                        MAX(updated_at) AS last_updated_at
                    FROM maze_layout_cell_memory
                    WHERE maze_layout_id = ? AND difficulty = ? AND grid_size = ?
                    """,
                    (
                        int(self.current_maze_episode_id),
                        self._normalized_maze_difficulty(),
                        int(self.grid_cells),
                    ),
                ).fetchone()
                cause_stm_rows = conn.execute(
                    """
                    SELECT action_taken, reason_tags, avg_outcome, strength, recall_count
                    FROM maze_cause_effect_stm
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT 5
                    """
                ).fetchall()
                cause_sem_rows = conn.execute(
                    """
                    SELECT action_taken, reason_tags, avg_outcome, strength, recall_count
                    FROM maze_cause_effect_semantic
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT 5
                    """
                ).fetchall()

            if not structural:
                return "(no structural maze memory rows yet)"

            (
                difficulty,
                grid_size,
                start_cell,
                player_cell,
                open_cells,
                blocked_cells,
                unknown_cells,
                frontier_cells,
                junction_cells,
                corridor_cells,
                dead_end_cells,
                loop_estimate,
            ) = structural
            episodic_summary = self._episodic_memory_summary()

            wm_signature = self.working_memory_active.get("signature", "(none)")
            wm_ascii = self.working_memory_active.get("ascii", "(none)")
            wm_cause_effect = self.working_memory_active.get("cause_effect_recent", "")
            stm_text = "\n".join(
                f"- {name} strength={round(strength, 3)} recall={recall} signature={sig}"
                for name, sig, strength, recall in stm_rows
            ) or "(no short-term entries)"
            semantic_text = "\n".join(
                f"- {name} strength={round(strength, 3)} recall={recall} signature={sig}"
                for name, sig, strength, recall in semantic_rows
            ) or "(no semantic entries)"
            action_text = "\n".join(
                f"- step={step} action={action} outcome={outcome} reward={round(reward, 2)} "
                f"penalty={round(penalty, 2)} tags={tags or '(none)'}"
                for step, action, outcome, reward, penalty, tags in action_rows
            ) or "(no cause-effect entries)"
            prediction_rows = self._recent_prediction_rows(limit=8)
            calibration_bucket_rows = self._prediction_confidence_bucket_rows()
            calibration_bucket_text = "\n".join(
                (
                    f"- conf_bin={self._prediction_bucket_label(bucket_index)} count={int(total or 0)} "
                    f"avg_conf={round(float(avg_confidence or 0.0), 3)} "
                    f"occ_acc={round(float(occ_accuracy or 0.0), 3)} "
                    f"shape_acc={round(float(shape_accuracy or 0.0), 3)} "
                    f"occ_brier={round(float(occ_brier or 0.0), 3)} "
                    f"shape_brier={round(float(shape_brier or 0.0), 3)}"
                )
                for bucket_index, total, avg_confidence, occ_accuracy, shape_accuracy, occ_brier, shape_brier in calibration_bucket_rows
            ) or "(no calibration bucket stats)"
            calibration_context_rows = self._prediction_context_rows(limit=5)
            calibration_context_text = "\n".join(
                (
                    f"- ctx={context_key} count={int(total or 0)} avg_conf={round(float(avg_confidence or 0.0), 3)} "
                    f"occ_acc={round(float(occ_accuracy or 0.0), 3)} shape_acc={round(float(shape_accuracy or 0.0), 3)} "
                    f"occ_brier={round(float(occ_brier or 0.0), 3)} shape_brier={round(float(shape_brier or 0.0), 3)}"
                )
                for context_key, total, avg_confidence, occ_accuracy, shape_accuracy, occ_brier, shape_brier in calibration_context_rows
            ) or "(no context calibration stats)"
            prediction_text = "\n".join(
                (
                    f"- step={step_created}->{step_resolved if step_resolved is not None else '?'} "
                    f"cell=({cell_row},{cell_col}) pred={predicted_label}/{predicted_shape} "
                    f"actual={(actual_label or '?')}/{(actual_shape or '?')} "
                    f"conf={round(float(confidence), 3)} "
                    f"ctx={prediction_context_key or '(none)'} "
                    f"conf_bin={self._prediction_bucket_label(int(confidence_bucket or 0))} "
                    f"status={resolution_status or 'pending'} "
                    f"occ={'yes' if int(is_correct or 0) == 1 else 'no' if actual_label else 'pending'} "
                    f"shape={'yes' if int(is_shape_correct or 0) == 1 else 'no' if actual_shape else 'pending'} "
                    f"brier_occ={round(float(occupancy_brier or 0.0), 3)} "
                    f"brier_shape={round(float(shape_brier or 0.0), 3)} "
                    f"score_occ={round(float(occupancy_score_delta or 0.0), 3)} "
                    f"score_shape={round(float(shape_score_delta or 0.0), 3)} "
                    f"score_total={round(float(score_delta or 0.0), 3)}"
                )
                for _created_at, _resolved_at, step_created, step_resolved, cell_row, cell_col, predicted_label, predicted_shape, confidence, prediction_context_key, confidence_bucket, resolution_status, _expiry_reason, actual_label, actual_shape, is_correct, is_shape_correct, occupancy_brier, shape_brier, occupancy_score_delta, shape_score_delta, score_delta in prediction_rows
            ) or "(no prediction entries)"
            cause_stm_text = "\n".join(
                f"- {action} avg_outcome={round(avg, 3)} strength={round(strength, 3)} recall={recall} tags={tags or '(none)'}"
                for action, tags, avg, strength, recall in cause_stm_rows
            ) or "(no cause-effect STM entries)"
            cause_sem_text = "\n".join(
                f"- {action} avg_outcome={round(avg, 3)} strength={round(strength, 3)} recall={recall} tags={tags or '(none)'}"
                for action, tags, avg, strength, recall in cause_sem_rows
            ) or "(no cause-effect semantic entries)"
            layout_total = int((layout_recall_row[0] if layout_recall_row else 0) or 0)
            layout_blocked = int((layout_recall_row[1] if layout_recall_row else 0) or 0)
            layout_open = int((layout_recall_row[2] if layout_recall_row else 0) or 0)
            layout_updated_at = str((layout_recall_row[3] if layout_recall_row else "") or "")

            return (
                "memory_priority_rule: episodic current-maze map overrides cross-maze pattern memory; "
                "persistent memory is advisory only for unknown or partially known cells.\n"
                f"local_map_authority_mode={self.local_map_authority_mode} "
                f"soft_scale={round(self.local_map_authority_soft_scale, 3)}\n"
                f"maze_layout_id={self.current_maze_episode_id}\n"
                "layout_recall_exact_match: "
                f"source={self.layout_recall_last_source} restored={self.layout_recall_last_restored} "
                f"total={self.layout_recall_last_total} rejected={self.layout_recall_last_rejected} "
                f"persisted_cells={layout_total} persisted_open={layout_open} persisted_blocked={layout_blocked} "
                f"persisted_updated_at={layout_updated_at or '(none)'}\n"
                f"difficulty={difficulty}, grid_size={grid_size}, start_cell={start_cell}, player_cell={player_cell}, "
                "target_location=hidden\n"
                f"structure: open={open_cells}, blocked={blocked_cells}, unknown={unknown_cells}, "
                f"frontier={frontier_cells}, junctions={junction_cells}, corridors={corridor_cells}, "
                f"dead_ends={dead_end_cells}, loop_estimate={loop_estimate}\n\n"
                "episodic_memory_current_maze:\n"
                f"known_open={episodic_summary['known_open']} known_blocked={episodic_summary['known_blocked']} "
                f"unknown={episodic_summary['unknown']} frontier={episodic_summary['frontier']} "
                f"junctions={episodic_summary['junctions']} corridors={episodic_summary['corridors']} "
                f"dead_ends={episodic_summary['dead_ends']} fully_known_open={episodic_summary['fully_known_open']} "
                f"visited_cells={episodic_summary['visited_cells']}\n\n"
                "working_memory_active (episodic local view):\n"
                f"signature={wm_signature}\n"
                f"ascii:\n{wm_ascii}\n\n"
                f"working_cause_effect_recent (episodic):\n{wm_cause_effect or '(none)'}\n\n"
                "predictive_memory:\n"
                f"pending={len(self.prediction_memory_active)} resolved={self.prediction_resolved_count} expired={self.prediction_expired_count} "
                f"occ_correct={self.prediction_correct_count} occ_accuracy={round(self._prediction_accuracy(), 3)} "
                f"shape_correct={self.prediction_shape_correct_count} shape_accuracy={round(self._prediction_shape_accuracy(), 3)} "
                f"full_accuracy={round(self._prediction_full_accuracy(), 3)} "
                f"occ_brier_avg={round(self._prediction_avg_occupancy_brier(), 3)} "
                f"shape_brier_avg={round(self._prediction_avg_shape_brier(), 3)} "
                f"score_current={round(self.prediction_score_current_maze, 2)} "
                f"score_total={round(self.prediction_score_total, 2)}\n"
                f"{prediction_text}\n\n"
                "prediction_confidence_calibration:\n"
                f"{calibration_bucket_text}\n\n"
                "prediction_context_calibration:\n"
                f"{calibration_context_text}\n\n"
                "cross_maze_short_term_patterns:\n"
                f"{stm_text}\n\n"
                "cross_maze_long_term_semantic_memory:\n"
                f"{semantic_text}\n\n"
                "cross_maze_cause_effect_short_term_memory:\n"
                f"{cause_stm_text}\n\n"
                "cross_maze_cause_effect_semantic_memory:\n"
                f"{cause_sem_text}\n\n"
                "recent_action_outcomes_current_maze:\n"
                f"{action_text}"
            )
        except Exception:  # noqa: BLE001
            return "(maze structural memory unavailable)"

    def _compact_ascii_for_export(self, ascii_text: str, max_lines: int) -> str:
        text = (ascii_text or "").strip()
        if not text:
            return ""
        if self.memory_export_strip_look_sections:
            for marker in ["\n\n[LOOK SWEEP]", "\n\n[RECENT LOOK MEMORY]"]:
                marker_index = text.find(marker)
                if marker_index >= 0:
                    text = text[:marker_index].rstrip()
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text
        omitted = len(lines) - max_lines
        return "\n".join(lines[:max_lines] + [f"... ({omitted} more lines)"])

    def _maze_memory_view_text(self, limit: int | None = 3, compact: bool = False) -> str:
        try:
            limit_value = limit if isinstance(limit, int) and limit > 0 else 1_000_000
            with sqlite3.connect(self.memory_db_path) as conn:
                stm_rows = conn.execute(
                    """
                    SELECT pattern_name, pattern_signature, ascii_pattern, strength, recall_count, updated_at
                    FROM maze_short_term_memory
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                semantic_rows = conn.execute(
                    """
                    SELECT pattern_name, pattern_signature, ascii_pattern, strength, recall_count, updated_at
                    FROM maze_semantic_memory
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                structural_rows = conn.execute(
                    """
                    SELECT id, created_at, difficulty, grid_size, start_cell, player_cell,
                           open_cells, blocked_cells, unknown_cells, frontier_cells,
                           junction_cells, corridor_cells, dead_end_cells, loop_estimate
                    FROM maze_structural_memory
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                action_rows = conn.execute(
                    """
                    SELECT created_at, step_index, action_taken, outcome_label,
                           outcome_value, reward_signal, penalty_signal, reason_tags,
                           player_cell
                    FROM maze_action_outcome_memory
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                cause_stm_rows = conn.execute(
                    """
                    SELECT action_taken, reason_tags, avg_outcome, strength, recall_count, updated_at
                    FROM maze_cause_effect_stm
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                cause_sem_rows = conn.execute(
                    """
                    SELECT action_taken, reason_tags, avg_outcome, strength, recall_count, updated_at
                    FROM maze_cause_effect_semantic
                    ORDER BY strength DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                prediction_rows = conn.execute(
                    """
                    SELECT created_at, step_created, step_resolved, cell_row, cell_col,
                           predicted_label, predicted_shape, confidence,
                          prediction_context_key, confidence_bucket, resolution_status, expiry_reason,
                          actual_label, actual_shape, is_correct, is_shape_correct,
                          occupancy_brier, shape_brier,
                          occupancy_score_delta, shape_score_delta, score_delta
                    FROM maze_prediction_memory
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()
                layout_summary_rows = conn.execute(
                    """
                    SELECT maze_layout_id, difficulty, grid_size,
                           SUM(CASE WHEN cell_token = '#' THEN 1 ELSE 0 END) AS blocked_cells,
                           SUM(CASE WHEN cell_token = '.' THEN 1 ELSE 0 END) AS open_cells,
                           COUNT(*) AS total_cells,
                           MAX(updated_at) AS updated_at
                    FROM maze_layout_cell_memory
                    GROUP BY maze_layout_id, difficulty, grid_size
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit_value,),
                ).fetchall()

            blocks: list[str] = []
            episodic_summary = self._episodic_memory_summary()
            blocks.append("[Episodic Memory - current maze]")
            blocks.append(
                (
                    f"maze_layout_id={self.current_maze_episode_id}\n"
                    f"local_map_authority_mode={self.local_map_authority_mode} "
                    f"soft_scale={round(self.local_map_authority_soft_scale, 3)}\n"
                    "layout_recall_exact_match="
                    f"{self.layout_recall_last_source} "
                    f"restored={self.layout_recall_last_restored} "
                    f"total={self.layout_recall_last_total} "
                    f"rejected={self.layout_recall_last_rejected}\n"
                    f"known_open={episodic_summary['known_open']} known_blocked={episodic_summary['known_blocked']} "
                    f"unknown={episodic_summary['unknown']} frontier={episodic_summary['frontier']} "
                    f"junctions={episodic_summary['junctions']} corridors={episodic_summary['corridors']} "
                    f"dead_ends={episodic_summary['dead_ends']} fully_known_open={episodic_summary['fully_known_open']} "
                    f"visited_cells={episodic_summary['visited_cells']}\n"
                    "priority_rule=episodic current-maze knowledge overrides cross-maze pattern memory"
                )
            )
            blocks.append("[Working Memory - episodic local view]")
            if self.working_memory_active:
                wm_ascii_text = self.working_memory_active.get("ascii", "")
                if compact:
                    wm_ascii_text = self._compact_ascii_for_export(
                        wm_ascii_text,
                        self.memory_export_ascii_max_lines,
                    )
                blocks.append(
                    "signature={sig}\nplayer_cell={cell}\nascii:\n{ascii}".format(
                        sig=self.working_memory_active.get("signature", ""),
                        cell=self.working_memory_active.get("player_cell", ""),
                        ascii=wm_ascii_text,
                    )
                )
                cause_effect_recent = self.working_memory_active.get("cause_effect_recent", "")
                if cause_effect_recent:
                    blocks.append(f"recent_cause_effect:\n{cause_effect_recent}")
            else:
                blocks.append("(empty)")

            blocks.append("[Cross-Maze Short-Term Patterns]")
            if stm_rows:
                for pattern_name, pattern_signature, ascii_pattern, strength, recall_count, updated_at in stm_rows:
                    ascii_view = ascii_pattern
                    if compact:
                        ascii_view = self._compact_ascii_for_export(
                            ascii_pattern,
                            self.memory_export_ascii_max_lines,
                        )
                    blocks.append(
                        (
                            f"{pattern_name} strength={round(strength, 3)} recall={recall_count} updated={updated_at}\n"
                            f"signature={pattern_signature}\n"
                            f"ascii:\n{ascii_view}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Cross-Maze Long-Term Semantic Memory]")
            if semantic_rows:
                for pattern_name, pattern_signature, ascii_pattern, strength, recall_count, updated_at in semantic_rows:
                    ascii_view = ascii_pattern
                    if compact:
                        ascii_view = self._compact_ascii_for_export(
                            ascii_pattern,
                            self.memory_export_ascii_max_lines,
                        )
                    blocks.append(
                        (
                            f"{pattern_name} strength={round(strength, 3)} recall={recall_count} updated={updated_at}\n"
                            f"signature={pattern_signature}\n"
                            f"ascii:\n{ascii_view}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Action Outcomes - current maze]")
            if action_rows:
                for row in action_rows:
                    (
                        created_at,
                        step_index,
                        action_taken,
                        outcome_label,
                        outcome_value,
                        reward_signal,
                        penalty_signal,
                        reason_tags,
                        player_cell,
                    ) = row
                    blocks.append(
                        (
                            f"[{created_at}] step={step_index} action={action_taken} cell={player_cell}\n"
                            f"outcome={outcome_label} value={round(outcome_value, 3)} "
                            f"reward={round(reward_signal, 2)} penalty={round(penalty_signal, 2)}\n"
                            f"tags={reason_tags or '(none)'}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Predictive Memory - unseen structure guesses]")
            blocks.append(
                (
                    f"pending={len(self.prediction_memory_active)} resolved={self.prediction_resolved_count} expired={self.prediction_expired_count} "
                    f"occ_accuracy={round(self._prediction_accuracy(), 3)} shape_accuracy={round(self._prediction_shape_accuracy(), 3)} "
                    f"full_accuracy={round(self._prediction_full_accuracy(), 3)} "
                    f"occ_brier_avg={round(self._prediction_avg_occupancy_brier(), 3)} "
                    f"shape_brier_avg={round(self._prediction_avg_shape_brier(), 3)} "
                    f"score_current={round(self.prediction_score_current_maze, 2)} "
                    f"score_total={round(self.prediction_score_total, 2)}"
                )
            )
            if prediction_rows:
                for row in prediction_rows:
                    (
                        created_at,
                        step_created,
                        step_resolved,
                        cell_row,
                        cell_col,
                        predicted_label,
                        predicted_shape,
                        confidence,
                        prediction_context_key,
                        confidence_bucket,
                        resolution_status,
                        expiry_reason,
                        actual_label,
                        actual_shape,
                        is_correct,
                        is_shape_correct,
                        occupancy_brier,
                        shape_brier,
                        occupancy_score_delta,
                        shape_score_delta,
                        score_delta,
                    ) = row
                    correctness = (
                        resolution_status or "pending"
                    )
                    blocks.append(
                        (
                            f"[{created_at}] step={step_created}->{step_resolved if step_resolved is not None else '?'} "
                            f"cell=({cell_row},{cell_col}) pred={predicted_label}/{predicted_shape} "
                            f"actual={(actual_label or '?')}/{(actual_shape or '?')} "
                            f"confidence={round(float(confidence), 3)} result={correctness} "
                            f"ctx={prediction_context_key or '(none)'} conf_bin={self._prediction_bucket_label(int(confidence_bucket or 0))} "
                            f"occ={'yes' if int(is_correct or 0) == 1 else 'no' if actual_label else correctness} "
                            f"shape={'yes' if int(is_shape_correct or 0) == 1 else 'no' if actual_shape else correctness} "
                            f"brier_occ={round(float(occupancy_brier or 0.0), 3)} "
                            f"brier_shape={round(float(shape_brier or 0.0), 3)} "
                            f"score_occ={round(float(occupancy_score_delta or 0.0), 3)} "
                            f"score_shape={round(float(shape_score_delta or 0.0), 3)} "
                            f"score_delta={round(float(score_delta or 0.0), 3)}"
                            f"{f' expiry_reason={expiry_reason}' if expiry_reason else ''}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Prediction Confidence Calibration]")
            calibration_bucket_rows = self._prediction_confidence_bucket_rows()
            if calibration_bucket_rows:
                for bucket_index, total, avg_confidence, occ_accuracy, shape_accuracy, occ_brier, shape_brier in calibration_bucket_rows:
                    blocks.append(
                        (
                            f"conf_bin={self._prediction_bucket_label(int(bucket_index or 0))} count={int(total or 0)} "
                            f"avg_conf={round(float(avg_confidence or 0.0), 3)} occ_acc={round(float(occ_accuracy or 0.0), 3)} "
                            f"shape_acc={round(float(shape_accuracy or 0.0), 3)} occ_brier={round(float(occ_brier or 0.0), 3)} "
                            f"shape_brier={round(float(shape_brier or 0.0), 3)}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Prediction Context Calibration]")
            calibration_context_rows = self._prediction_context_rows(limit=6)
            if calibration_context_rows:
                for context_key, total, avg_confidence, occ_accuracy, shape_accuracy, occ_brier, shape_brier in calibration_context_rows:
                    blocks.append(
                        (
                            f"ctx={context_key} count={int(total or 0)} avg_conf={round(float(avg_confidence or 0.0), 3)} "
                            f"occ_acc={round(float(occ_accuracy or 0.0), 3)} shape_acc={round(float(shape_accuracy or 0.0), 3)} "
                            f"occ_brier={round(float(occ_brier or 0.0), 3)} shape_brier={round(float(shape_brier or 0.0), 3)}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Cross-Maze Cause-Effect STM]")
            if cause_stm_rows:
                for action_taken, reason_tags, avg_outcome, strength, recall_count, updated_at in cause_stm_rows:
                    blocks.append(
                        (
                            f"{action_taken} avg_outcome={round(avg_outcome, 3)} strength={round(strength, 3)} "
                            f"recall={recall_count} updated={updated_at}\n"
                            f"tags={reason_tags or '(none)'}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Cross-Maze Cause-Effect Semantic]")
            if cause_sem_rows:
                for action_taken, reason_tags, avg_outcome, strength, recall_count, updated_at in cause_sem_rows:
                    blocks.append(
                        (
                            f"{action_taken} avg_outcome={round(avg_outcome, 3)} strength={round(strength, 3)} "
                            f"recall={recall_count} updated={updated_at}\n"
                            f"tags={reason_tags or '(none)'}"
                        )
                    )
            else:
                blocks.append("(empty)")

            blocks.append("[Layout Cell Memory - exact deterministic recall]")
            if layout_summary_rows:
                for (
                    maze_layout_id,
                    difficulty,
                    grid_size,
                    blocked_cells,
                    open_cells,
                    total_cells,
                    updated_at,
                ) in layout_summary_rows:
                    blocks.append(
                        (
                            f"layout_id={maze_layout_id} difficulty={difficulty} grid={grid_size} "
                            f"cells={int(total_cells or 0)} open={int(open_cells or 0)} "
                            f"blocked={int(blocked_cells or 0)} updated={updated_at}"
                        )
                    )
            else:
                blocks.append("(empty)")

            if structural_rows:
                blocks.append("[Structural Memory - persistent across runs]")
                for row in structural_rows:
                    (
                        row_id,
                        created_at,
                        difficulty,
                        grid_size,
                        start_cell,
                        player_cell,
                        open_cells,
                        blocked_cells,
                        unknown_cells,
                        frontier_cells,
                        junction_cells,
                        corridor_cells,
                        dead_end_cells,
                        loop_estimate,
                    ) = row
                    blocks.append(
                        (
                            f"[Structure #{row_id}] {created_at}\n"
                            f"difficulty={difficulty} grid={grid_size} start={start_cell} player={player_cell}\n"
                            f"open={open_cells} blocked={blocked_cells} unknown={unknown_cells} "
                            f"frontier={frontier_cells} junctions={junction_cells} corridors={corridor_cells} "
                            f"dead_ends={dead_end_cells} loop_estimate={loop_estimate}"
                        )
                    )

            if not blocks:
                return "No maze memory rows yet."
            return "\n\n".join(blocks)
        except Exception as exc:  # noqa: BLE001
            return f"Maze memory unavailable: {exc}"

    def _refresh_memory_viewer(self) -> None:
        if not hasattr(self, "memory_view_output"):
            return
        if hasattr(self, "memory_run_id_var") and not self.memory_run_id_var.get().strip() and self.current_maze_episode_id > 0:
            self.memory_run_id_var.set(str(self.current_maze_episode_id))
        text = self._maze_memory_view_text(limit=3)
        self.memory_view_output.config(state=tk.NORMAL)
        self.memory_view_output.delete("1.0", tk.END)
        self.memory_view_output.insert(tk.END, text)
        self.memory_view_output.config(state=tk.DISABLED)

    def _build_logic_plan(self, user_prompt: str, assistant_instructions: str) -> dict:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        planner_instruction = (
            "You are the LOGIC model in a two-model architecture. Interpret vague user intent and "
            "translate it into concrete steps for an AGENT model. Respond with JSON only using this schema: "
            '{"delegate": boolean, "intent_summary": string, "agent_task": string, '
            '"direct_response": string, "success_criteria": string, '
            '"confidence": number, "normalized_goal": string, "is_repeat_goal": boolean, '
            '"execution_count": integer}. '
            "Rules: Set delegate=true when execution work should be handed to the agent model. "
            "If delegate=false, put the final user answer in direct_response. "
            "If delegate=true, direct_response should be an empty string and agent_task must be specific. "
            "Confidence is 0.0 to 1.0. normalized_goal should be the canonical, concise objective statement. "
            "execution_count should be >=1 and represent how many times the task should be executed. "
            "You must infer whether the goal is repeated from user intent and set is_repeat_goal accordingly."
        )

        response = self.client.responses.create(
            model=self.logic_model,
            input=[
                {"role": "system", "content": planner_instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context (if relevant):\n"
                        f"{game_context}\n\n{self.movement_rules}"
                    ),
                },
                {
                    "role": "system",
                    "content": f"Score/progress context:\n{score_context}",
                },
                {
                    "role": "system",
                    "content": (
                        "Prior normalized goal memory (use when user request is ambiguous or repeated): "
                        f"{self.last_normalized_goal or '(none)'}"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        )
        plan = self._parse_json_payload(response.output_text)
        return {
            "delegate": bool(plan.get("delegate", False)),
            "intent_summary": str(plan.get("intent_summary", "")),
            "agent_task": str(plan.get("agent_task", "")),
            "direct_response": str(plan.get("direct_response", "")),
            "success_criteria": str(plan.get("success_criteria", "")),
            "confidence": float(plan.get("confidence", 0.0) or 0.0),
            "normalized_goal": str(plan.get("normalized_goal", "")),
            "is_repeat_goal": bool(plan.get("is_repeat_goal", False)),
            "execution_count": int(plan.get("execution_count", 1) or 1),
        }

    def _run_agent_task(self, user_prompt: str, plan: dict, assistant_instructions: str) -> str:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        task_instruction = (
            "You are the AGENT model. Execute the assigned task exactly and return a practical result. "
            "Do not ask follow-up questions unless absolutely required. Be concrete and actionable. "
            "For game navigation, prioritize shortest-path movement based on player and target cell coordinates. "
            "Avoid overexplaining; focus on efficient moves. "
            "If game movement is needed, include JSON with a 'moves' array using UP/DOWN/LEFT/RIGHT, "
            "for example: {\"moves\": [\"RIGHT\", \"DOWN\"]}."
        )
        response = self.client.responses.create(
            model=self.agent_model,
            input=[
                {"role": "system", "content": task_instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context (if relevant):\n"
                        f"{game_context}\n\n{self.movement_rules}"
                    ),
                },
                {
                    "role": "system",
                    "content": f"Score/progress context:\n{score_context}",
                },
                {
                    "role": "user",
                    "content": (
                        f"Original user message:\n{user_prompt}\n\n"
                        f"Intent summary:\n{plan['intent_summary']}\n\n"
                        f"Assigned task:\n{plan['agent_task']}\n\n"
                        f"Success criteria:\n{plan['success_criteria']}"
                    ),
                },
            ],
        )
        return response.output_text.strip() or "No task output returned."

    def _logic_resolve_repetition(self, user_prompt: str, plan: dict, assistant_instructions: str) -> dict:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        resolver_instruction = (
            "You are the LOGIC model repetition resolver. Determine whether the user intent requires repeated "
            "task execution and how many times. Return JSON only with schema: "
            '{"is_repeat_goal": boolean, "execution_count": integer, "confidence": number, "reason": string}. '
            "Rules: execution_count must be >=1. If unsure, use confidence < 0.6. "
            "Examples: 'capture target 3 times' => is_repeat_goal=true, execution_count=3. "
            "'capture target' => is_repeat_goal=false, execution_count=1."
        )
        response = self.client.responses.create(
            model=self.logic_model,
            input=[
                {"role": "system", "content": resolver_instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Context from planner:\n"
                        f"intent_summary={plan.get('intent_summary', '')}\n"
                        f"normalized_goal={plan.get('normalized_goal', '')}\n"
                        f"planner_is_repeat_goal={plan.get('is_repeat_goal', False)}\n"
                        f"planner_execution_count={plan.get('execution_count', 1)}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context:\n"
                        f"{game_context}\n\nScore/progress context:\n{score_context}"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        )
        try:
            payload = self._parse_json_payload(response.output_text)
            return {
                "is_repeat_goal": bool(payload.get("is_repeat_goal", False)),
                "execution_count": max(1, min(self.max_repeat_executions, int(payload.get("execution_count", 1) or 1))),
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
                "reason": str(payload.get("reason", "No reason provided.")),
            }
        except Exception:  # noqa: BLE001
            return {
                "is_repeat_goal": bool(plan.get("is_repeat_goal", False)),
                "execution_count": max(1, min(self.max_repeat_executions, int(plan.get("execution_count", 1) or 1))),
                "confidence": 0.0,
                "reason": "Repetition resolver JSON parse failed; kept planner values.",
            }

    def _logic_finalize(self, user_prompt: str, plan: dict, agent_output: str, assistant_instructions: str) -> str:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        finalizer_instruction = (
            "You are the LOGIC model and final user-facing assistant. Use agent output as evidence, "
            "then produce the final response. Keep it clear and directly useful."
        )
        response = self.client.responses.create(
            model=self.logic_model,
            input=[
                {"role": "system", "content": finalizer_instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context (if relevant):\n"
                        f"{game_context}\n\n{self.movement_rules}"
                    ),
                },
                {
                    "role": "system",
                    "content": f"Score/progress context:\n{score_context}",
                },
                {
                    "role": "user",
                    "content": (
                        f"User message:\n{user_prompt}\n\n"
                        f"Intent summary:\n{plan['intent_summary']}\n\n"
                        f"Agent output:\n{agent_output}"
                    ),
                },
            ],
        )
        return response.output_text.strip() or "No text response returned."

    def _logic_approve_agent_instructions(
        self,
        user_prompt: str,
        plan: dict,
        agent_output: str,
        candidate_moves: list[str],
        assistant_instructions: str,
    ) -> dict:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        reviewer_instruction = (
            "You are the LOGIC model safety/quality reviewer. Review AGENT instructions before execution. "
            "Approve only if instructions are aligned with user intent, movement rules, and game context. "
            "Prefer the most efficient path and reject needlessly long or wandering move sequences. "
            "If the goal requires repetition, evaluate efficiency per target cycle rather than expecting one long static route. "
            "Return JSON only with schema: {\"approved\": boolean, \"reason\": string, \"moves\": string[]}. "
            "Moves may only contain UP, DOWN, LEFT, RIGHT. If not approved, return an empty moves list."
        )

        response = self.client.responses.create(
            model=self.logic_model,
            input=[
                {"role": "system", "content": reviewer_instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context:\n"
                        f"{game_context}\n\n{self.movement_rules}"
                    ),
                },
                {
                    "role": "system",
                    "content": f"Score/progress context:\n{score_context}",
                },
                {
                    "role": "user",
                    "content": (
                        f"User message:\n{user_prompt}\n\n"
                        f"Intent summary:\n{plan['intent_summary']}\n\n"
                        f"Assigned task:\n{plan['agent_task']}\n\n"
                        f"Agent output:\n{agent_output}\n\n"
                        f"Candidate moves:\n{candidate_moves}"
                    ),
                },
            ],
        )

        try:
            approval = self._parse_json_payload(response.output_text)
            approved = bool(approval.get("approved", False))
            reason = str(approval.get("reason", "No reason provided."))
            raw_moves = approval.get("moves", [])
            reviewed_moves = self._normalize_moves(raw_moves if isinstance(raw_moves, list) else [])
            if not approved:
                reviewed_moves = []
            return {"approved": approved, "reason": reason, "moves": reviewed_moves}
        except Exception:  # noqa: BLE001
            return {
                "approved": False,
                "reason": "Logic approval response was not valid JSON.",
                "moves": [],
            }

    def _agent_propose_single_move(self, user_prompt: str, plan: dict, assistant_instructions: str) -> dict:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        instruction = (
            "You are the AGENT model proposing exactly one next move for the game. "
            "Return JSON only: {\"move\": \"UP|DOWN|LEFT|RIGHT\", \"reason\": string}. "
            "Prioritize shortest-path progress toward completing the task."
        )
        response = self.client.responses.create(
            model=self.agent_model,
            input=[
                {"role": "system", "content": instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context:\n"
                        f"{game_context}\n\nScore/progress context:\n{score_context}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original user message:\n{user_prompt}\n\n"
                        f"Intent summary:\n{plan['intent_summary']}\n\n"
                        f"Task:\n{plan['agent_task']}\n\n"
                        f"Success criteria:\n{plan['success_criteria']}"
                    ),
                },
            ],
        )
        try:
            payload = self._parse_json_payload(response.output_text)
            moves = self._normalize_moves([payload.get("move", "")])
            return {
                "move": moves[0] if moves else "",
                "reason": str(payload.get("reason", "No reason provided.")),
            }
        except Exception:  # noqa: BLE001
            parsed = self._extract_moves(response.output_text)
            return {
                "move": parsed[0] if parsed else "",
                "reason": "Fallback parsed from non-JSON agent output.",
            }

    def _logic_evaluate_single_move(
        self,
        user_prompt: str,
        plan: dict,
        proposed_move: str,
        assistant_instructions: str,
    ) -> dict:
        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        pattern_signature = self._current_pattern_signature()
        pattern_catalog = self._pattern_catalog_context(limit=10)
        instruction = (
            "You are the LOGIC model evaluator for one move. Determine whether the proposed move helps progress "
            "toward the goal. Return JSON only: "
            '{"approved": boolean, "move": "UP|DOWN|LEFT|RIGHT", "gets_closer": boolean, "reason": string, '
            '"pattern_name": string}. '
            "If not approved, provide a corrected move in 'move'. "
            "For pattern_name, first try to reuse a name from the pattern catalog when signatures are similar. "
            "If no good match exists, create a short descriptive pattern name (1-4 words)."
        )
        response = self.client.responses.create(
            model=self.logic_model,
            input=[
                {"role": "system", "content": instruction},
                {
                    "role": "system",
                    "content": (
                        "Follow these operator instructions for behavior and constraints. "
                        f"Operator instructions:\n{assistant_instructions or '(none)'}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "Game perception context:\n"
                        f"{game_context}\n\nScore/progress context:\n{score_context}\n\n"
                        f"Pattern catalog:\n{pattern_catalog}\n\n"
                        f"Current local pattern signature:\n{pattern_signature}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User message:\n{user_prompt}\n\n"
                        f"Intent summary:\n{plan['intent_summary']}\n\n"
                        f"Task:\n{plan['agent_task']}\n\n"
                        f"Proposed move:\n{proposed_move}"
                    ),
                },
            ],
        )
        try:
            payload = self._parse_json_payload(response.output_text)
            normalized = self._normalize_moves([payload.get("move", "")])
            reason_text = str(payload.get("reason", "No reason provided."))
            pattern_name = self._sanitize_pattern_name(str(payload.get("pattern_name", "")))
            self._record_pattern_name(pattern_signature, pattern_name, reason_text)
            memory_event = self._process_pattern_memory(pattern_name)
            return {
                "approved": bool(payload.get("approved", False)),
                "move": normalized[0] if normalized else "",
                "gets_closer": bool(payload.get("gets_closer", False)),
                "reason": reason_text,
                "pattern_name": pattern_name,
                "memory_event": memory_event,
            }
        except Exception:  # noqa: BLE001
            return {
                "approved": False,
                "move": "",
                "gets_closer": False,
                "reason": "Logic move-eval response parse failed.",
                "pattern_name": "",
                "memory_event": "memory:eval-parse-failed",
            }

    def _should_request_targeted_maze_model_assist(
        self,
        *,
        map_doubt_active: bool,
        stuck_reexplore_active: bool,
        fully_mapped_now: bool,
        exit_visible_now: bool,
        local_contradiction_pressure: float,
        current_cell_repeats: int,
        no_progress_steps: int,
        legal_move_count: int,
    ) -> tuple[bool, str, float]:
        if not self.client:
            return (False, "", 0.0)
        if not self.maze_targeted_model_assist_enable:
            return (False, "", 0.0)
        if self.maze_model_assist_reliance <= 0.0:
            return (False, "", 0.0)
        if self.maze_step_model_hints:
            return (False, "", 0.0)
        if self.maze_model_assist_max_calls_per_episode <= 0:
            return (False, "", 0.0)
        if self._maze_model_assist_calls_used >= self.maze_model_assist_max_calls_per_episode:
            return (False, "", 0.0)
        if self._maze_model_assist_cooldown_remaining > 0:
            return (False, "", 0.0)
        if legal_move_count < 2:
            return (False, "", 0.0)

        trigger_strength = 0.0
        trigger_reasons: list[str] = []
        if map_doubt_active:
            trigger_strength += 0.42
            trigger_reasons.append("map_doubt")
        if stuck_reexplore_active:
            trigger_strength += 0.34
            trigger_reasons.append("stuck_reexplore")
        if fully_mapped_now and (not exit_visible_now):
            trigger_strength += 0.24
            trigger_reasons.append("hidden_exit")
        if local_contradiction_pressure > 0.0:
            trigger_strength += min(0.45, local_contradiction_pressure * 0.18)
            if local_contradiction_pressure >= 1.0:
                trigger_reasons.append("contradiction_debt")
        if current_cell_repeats >= self.maze_stuck_repeat_threshold:
            trigger_strength += 0.12
        if no_progress_steps >= self.maze_stuck_no_progress_threshold:
            trigger_strength += 0.12

        threshold = 0.92 - (0.55 * float(self.maze_model_assist_reliance))
        return (
            trigger_strength >= threshold,
            ",".join(trigger_reasons) or "pressure_spike",
            round(trigger_strength, 3),
        )

    def _targeted_maze_model_assist(
        self,
        user_prompt: str,
        plan: dict,
        assistant_instructions: str,
        trigger_reason: str,
        trigger_strength: float,
        candidate_rows: list[tuple[str, dict[str, object]]],
    ) -> dict[str, object]:
        if not self.client or not candidate_rows:
            return {"used": False, "move": "", "confidence": 0.0, "reason": "", "trigger": trigger_reason}

        self._maze_model_assist_calls_used += 1
        self._maze_model_assist_cooldown_remaining = max(0, int(self.maze_model_assist_cooldown_steps))

        game_context = self._get_game_state_snapshot()
        score_context = self._score_context()
        pattern_signature = self._current_pattern_signature()
        candidate_lines: list[str] = []
        for move, breakdown in candidate_rows:
            candidate_lines.append(
                (
                    f"{move}: score={int(breakdown.get('score', 0) or 0)} "
                    f"base={int(breakdown.get('base_score_without_noise', breakdown.get('score', 0)) or 0)} "
                    f"frontier_dist={int(breakdown.get('frontier_distance', 0) or 0)} "
                    f"unknown_neighbors={int(breakdown.get('unknown_neighbors', 0) or 0)} "
                    f"dead_end_depth={int(breakdown.get('dead_end_risk_depth', 0) or 0)} "
                    f"transition_repeat={int(breakdown.get('transition_repeat_penalty', 0) or 0)} "
                    f"cycle_pair={int(breakdown.get('cycle_pair_penalty', 0) or 0)} "
                    f"immediate_backtrack={int(breakdown.get('immediate_backtrack_hard_penalty', 0) or 0)} "
                    f"contradiction_debt={round(float(breakdown.get('local_contradiction_debt', 0.0) or 0.0), 2)} "
                    f"probe_bonus={int(breakdown.get('contradiction_probe_bonus', 0) or 0)}"
                )
            )

        instruction = (
            "You are the targeted LOGIC arbiter for maze navigation. Intervene only when the local planner may be "
            "stuck in a contradiction-heavy or loop-heavy pocket. Use the local candidate scores as priors, not as "
            "commands. Choose exactly one move from the provided candidate list, or abstain if the best-scored move "
            "already looks correct. Return JSON only with schema: "
            '{"use_model": boolean, "move": "UP|DOWN|LEFT|RIGHT|", "confidence": number, "reason": string}. '
            "Rules: never invent a move outside the candidate list; prefer moves that verify contradicted local structure, "
            "break repetition, or preserve optionality; avoid immediate backtracks or visibly terminal commitments unless "
            "all options are bad."
        )

        try:
            response = self.client.responses.create(
                model=self.logic_model,
                input=[
                    {"role": "system", "content": instruction},
                    {
                        "role": "system",
                        "content": (
                            "Follow these operator instructions for behavior and constraints. "
                            f"Operator instructions:\n{assistant_instructions or '(none)'}"
                        ),
                    },
                    {
                        "role": "system",
                        "content": (
                            "Trigger context:\n"
                            f"trigger={trigger_reason}\n"
                            f"trigger_strength={trigger_strength}\n"
                            f"reliance={round(self.maze_model_assist_reliance, 3)}\n\n"
                            f"Game perception context:\n{game_context}\n\n"
                            f"Score/progress context:\n{score_context}\n\n"
                            f"Current pattern signature:\n{pattern_signature}\n\n"
                            "Candidate moves:\n"
                            f"{"\n".join(candidate_lines)}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Original user message:\n{user_prompt}\n\n"
                            f"Intent summary:\n{plan.get('intent_summary', '')}\n\n"
                            f"Task:\n{plan.get('agent_task', '') or plan.get('normalized_goal', '')}"
                        ),
                    },
                ],
            )
            payload = self._parse_json_payload(response.output_text)
            use_model = bool(payload.get("use_model", False))
            move_list = self._normalize_moves([payload.get("move", "")])
            chosen_move = move_list[0] if move_list else ""
            legal_moves = {move for move, _breakdown in candidate_rows}
            if chosen_move not in legal_moves:
                chosen_move = ""
                use_model = False
            return {
                "used": use_model and bool(chosen_move),
                "move": chosen_move,
                "confidence": max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0))),
                "reason": str(payload.get("reason", "No reason provided.")),
                "trigger": trigger_reason,
            }
        except Exception:  # noqa: BLE001
            return {
                "used": False,
                "move": "",
                "confidence": 0.0,
                "reason": "Targeted maze-model assist call failed.",
                "trigger": trigger_reason,
            }

    def _execute_single_move_blocking(self, move: str) -> None:
        if not move:
            return
        done = threading.Event()

        def do_move() -> None:
            vectors = {
                "UP": (0, -self.player_speed),
                "DOWN": (0, self.player_speed),
                "LEFT": (-self.player_speed, 0),
                "RIGHT": (self.player_speed, 0),
            }
            dx, dy = vectors[move]
            self._move_player(dx, dy)
            done.set()

        self.root.after(0, do_move)
        done.wait(timeout=2.0)

    def _run_stepwise_goal_session(
        self,
        user_prompt: str,
        plan: dict,
        assistant_instructions: str,
        local_kernel_only: bool = False,
    ) -> dict:
        requested_count = self._extract_execution_count(plan)
        maze_mode = self._normalized_layout_mode() == "maze"
        # Scale the iteration budget with requested repeats so larger repeat goals
        # are not cut off by a fixed global cap.
        per_hit_budget = max(24, self.grid_cells * self.grid_cells)
        iteration_budget = max(self.max_step_iterations, requested_count * per_hit_budget)
        self.goal_session_active = True
        self.goal_session_start_hits = self.targets_reached
        self.goal_session_target_hits = max(1, requested_count)
        self.auto_goal_hits_remaining = self.goal_session_target_hits

        step_logs: list[str] = []
        iterations = 0
        map_doubt_cooldown = 0
        map_doubt_triggers = 0
        map_doubt_stall_count = 0
        self._maze_reexplore_cooldown_remaining = 0
        self._maze_stuck_trigger_count = 0
        self._maze_model_assist_calls_used = 0
        self._maze_model_assist_cooldown_remaining = 0
        self._recent_step_penalties.clear()
        recent_state_keys: deque[tuple[tuple[int, int], str]] = deque(maxlen=18)
        recent_positions: deque[tuple[int, int]] = deque(maxlen=max(8, self.maze_stuck_window))
        no_progress_steps = 0
        best_distance_seen = self._distance_from_target_for_cell(self.current_player_cell)

        while iterations < iteration_budget:
            completed, remaining = self._goal_session_progress()
            self.auto_goal_hits_remaining = remaining
            if remaining <= 0:
                break

            self.root.after(
                0,
                lambda rem=remaining, comp=completed: self.status_var.set(
                    f"Step mode: {rem} target hits remaining (completed {comp}/{self.goal_session_target_hits})"
                ),
            )

            if maze_mode:
                self._preview_look_directions_blocking(self._available_look_directions())

            use_model_step_calls = (not local_kernel_only) and ((not maze_mode) or self.maze_step_model_hints)
            if not use_model_step_calls:
                pattern_signature = self._current_pattern_signature() if maze_mode else ""
                pattern_name = self._local_planner_pattern_name(pattern_signature) if maze_mode else "local-planner"
                memory_event = "local_planner"
                if maze_mode:
                    self._record_pattern_name(
                        pattern_signature,
                        pattern_name,
                        "Kernel-only maze step planner",
                    )
                    memory_event = self._process_pattern_memory(pattern_name)
                proposal = {
                    "move": "",
                    "reason": "Step-model hints disabled; using internal planner selection.",
                }
                proposed_move = ""
                evaluation = {
                    "approved": False,
                    "move": "",
                    "gets_closer": False,
                    "reason": "Internal planner selected move without external step proposal/eval.",
                    "pattern_name": pattern_name,
                    "memory_event": memory_event,
                    # proposal_source clarifies this is normal kernel-only operation,
                    # not a missing or failed external proposal.
                    "proposal_source": "kernel",
                }
            else:
                proposal = self._agent_propose_single_move(user_prompt, plan, assistant_instructions)
                proposed_move = proposal["move"]

                evaluation = self._logic_evaluate_single_move(
                    user_prompt,
                    plan,
                    proposed_move,
                    assistant_instructions,
                )
                evaluation["proposal_source"] = "model"
            exploration_snapshot = ""

            fallback_used = False
            guard_override = False
            guard_reason = ""
            selected_move = ""
            end_episode_early = False
            if maze_mode:
                if self._maze_reexplore_cooldown_remaining > 0:
                    self._maze_reexplore_cooldown_remaining = max(0, self._maze_reexplore_cooldown_remaining - 1)
                if self._maze_model_assist_cooldown_remaining > 0:
                    self._maze_model_assist_cooldown_remaining = max(0, self._maze_model_assist_cooldown_remaining - 1)
                recent_state_keys.append((self.current_player_cell, self.player_facing))
                recent_positions.append(self.current_player_cell)
                current_state = recent_state_keys[-1]
                current_state_repeats = sum(1 for state in recent_state_keys if state == current_state)
                current_cell_repeats = sum(1 for cell in recent_positions if cell == self.current_player_cell)
                _episode_summary = self._episodic_memory_summary()
                _known_open_now = int(_episode_summary.get("known_open") or 0)
                _unknown_now = int(_episode_summary.get("unknown") or 0)
                _frontier_now = int(_episode_summary.get("frontier") or 0)
                if self._maze_timeout_reset_pulse:
                    # New attempt after timeout reset: clear stale progression/stuck counters.
                    no_progress_steps = 0
                    best_distance_seen = self._distance_from_target_for_cell(self.current_player_cell)
                    self._maze_reexplore_cooldown_remaining = 0
                    self._maze_timeout_reset_pulse = False
                _target_row, _target_col = self.current_target_cell
                exit_visible_now = (
                    self.maze_known_cells.get(self.current_target_cell, "") == "E"
                    and self._is_local_cell_visible(
                        self.current_player_cell[0],
                        self.current_player_cell[1],
                        _target_row,
                        _target_col,
                        facing=self.player_facing,
                    )
                )
                fully_mapped_now = self._maze_episode_fully_mapped() or (
                    _known_open_now > 0 and _unknown_now <= 0 and _frontier_now <= 0
                )
                map_doubt_active = self.maze_map_doubt_enable and map_doubt_cooldown > 0
                if map_doubt_active:
                    map_doubt_cooldown = max(0, map_doubt_cooldown - 1)
                if self._post_reset_stm_relax_remaining > 0:
                    self._post_reset_stm_relax_remaining = max(0, self._post_reset_stm_relax_remaining - 1)

                target_known_in_episode = self.maze_known_cells.get(self.current_target_cell, "") == "E"
                target_path_now = self._shortest_path_moves_between_cells(
                    self.current_player_cell,
                    self.current_target_cell,
                )
                sticky_objective_move = self._sticky_objective_move()
                sticky_objective_active = bool(target_known_in_episode and sticky_objective_move)
                retry_capture_active = bool(
                    target_known_in_episode
                    and (sticky_objective_active or target_path_now)
                    and self._active_same_maze_retry_count() > 0
                )
                objective_priority_active = bool(target_known_in_episode and (sticky_objective_active or target_path_now)) and (
                    sticky_objective_active
                    or retry_capture_active
                    or fully_mapped_now
                    or (exit_visible_now and _unknown_now <= 1 and _frontier_now <= 1)
                )
                retry_continuity_active = self._retry_continuity_active() and (_unknown_now > 0 or _frontier_now > 0)
                frontier_lock_active = self._frontier_lock_active(_unknown_now, _frontier_now)

                current_distance_maze = self._distance_from_target_for_cell(self.current_player_cell)
                if current_distance_maze < best_distance_seen:
                    best_distance_seen = current_distance_maze
                    no_progress_steps = 0
                else:
                    no_progress_steps += 1

                stuck_reexplore_active = self.maze_stuck_reexplore_enable and self._maze_reexplore_cooldown_remaining > 0
                local_contradiction_pressure = self._prediction_local_contradiction_debt(self.current_player_cell)
                repeat_trigger_threshold = max(
                    2,
                    self.maze_stuck_repeat_threshold - (1 if local_contradiction_pressure >= 1.4 else 0),
                )
                no_progress_trigger_threshold = max(
                    2,
                    self.maze_stuck_no_progress_threshold - (1 if local_contradiction_pressure >= 1.4 else 0),
                )
                objective_relax_guard_note = ""
                if (
                    objective_priority_active
                    and (_unknown_now > 0 or _frontier_now > 0)
                    and current_cell_repeats >= repeat_trigger_threshold
                    and no_progress_steps >= no_progress_trigger_threshold
                ):
                    objective_priority_active = False
                    if sticky_objective_active:
                        self._clear_sticky_objective_path()
                        sticky_objective_active = False
                        sticky_objective_move = ""
                    objective_relax_guard_note = (
                        "[OBJECTIVE-RELAX-GUARD: loop-pressure released objective lock "
                        f"repeats={current_cell_repeats} no_progress={no_progress_steps}]"
                    )
                should_trigger_stuck_reexplore = (
                    self.maze_stuck_reexplore_enable
                    and self._maze_reexplore_cooldown_remaining == 0
                    and (not objective_priority_active)
                    and (not sticky_objective_active)
                    and (not frontier_lock_active)
                    and (not exit_visible_now)
                    and current_cell_repeats >= repeat_trigger_threshold
                    and no_progress_steps >= no_progress_trigger_threshold
                    and (_unknown_now > 0 or _frontier_now > 0 or (not fully_mapped_now))
                )
                if should_trigger_stuck_reexplore:
                    # Escalate re-explore duration when repeated stuck episodes occur.
                    _trigger_escalation = min(20, (self._maze_stuck_trigger_count // 2) * 5)
                    self._maze_reexplore_cooldown_remaining = (
                        self.maze_stuck_reexplore_cooldown_steps + _trigger_escalation
                    )
                    self._maze_stuck_trigger_count += 1
                    stuck_reexplore_active = True

                if stuck_reexplore_active and (
                    objective_priority_active
                    or sticky_objective_active
                    or retry_continuity_active
                    or frontier_lock_active
                ):
                    # Do not let exploration recovery suppress objective routing
                    # once target is known or a retry frontier target is available.
                    self._maze_reexplore_cooldown_remaining = 0
                    stuck_reexplore_active = False

                if self.maze_map_doubt_enable and fully_mapped_now and current_state_repeats >= self.maze_map_doubt_repeat_threshold:
                    map_doubt_stall_count += 1
                else:
                    map_doubt_stall_count = max(0, map_doubt_stall_count - 1)

                if self.maze_map_doubt_enable and fully_mapped_now and map_doubt_stall_count >= self.maze_map_doubt_stall_threshold:
                    map_doubt_cooldown = max(map_doubt_cooldown, self.maze_map_doubt_cooldown_steps)
                    map_doubt_triggers += 1
                    map_doubt_stall_count = 0
                    map_doubt_active = True

                # Hidden-exit override: If the maze is fully mapped and the target exit is known
                # (whether visible or just in memory), suppress map-doubt and force navigation mode.
                hidden_exit_override_triggered = False
                if map_doubt_active and fully_mapped_now:
                    # Check if exit is known (in maze_known_cells as "E")
                    exit_known = self.maze_known_cells.get(self.current_target_cell, "") == "E"
                    if exit_known or exit_visible_now:
                        map_doubt_active = False
                        map_doubt_cooldown = 0
                        hidden_exit_override_triggered = True

                # Loop-escape detection: Force navigation when penalties are catastrophic.
                # This prevents thrashing in high-penalty deadlock regions.
                loop_escape_override_triggered = False
                if len(self._recent_step_penalties) >= 4:
                    cumulative_recent_penalty = sum(self._recent_step_penalties)
                    if cumulative_recent_penalty < -450:  # Catastrophic penalty threshold
                        loop_escape_override_triggered = True

                objective_move = ""
                objective_risk_guard_note = ""
                navigation_mode_lock = False
                # NAVIGATION MODE: If fully mapped OR penalties are catastrophic,
                # force objective routing to exit (pure navigation, not exploration).
                if sticky_objective_active:
                    objective_move = sticky_objective_move
                    navigation_mode_lock = True
                elif objective_priority_active:
                    if target_path_now:
                        self._prime_sticky_objective_path(target_path_now)
                    objective_move = target_path_now[0] if target_path_now else ""
                    navigation_mode_lock = True
                elif fully_mapped_now or loop_escape_override_triggered:
                    objective_move = self._best_maze_objective_move()
                    navigation_mode_lock = True
                elif (not map_doubt_active) and (not stuck_reexplore_active):
                    objective_move = self._best_maze_objective_move()
                elif map_doubt_active:
                    # Map-doubt active but NOT fully mapped: still exploring alternatives
                    guard_override = True
                    guard_reason = (
                        "Map-doubt override: suppressing objective-only routing to re-check nearby branches. "
                        f"cooldown={map_doubt_cooldown} repeats={current_state_repeats} "
                        f"unknown={_unknown_now} frontier={_frontier_now}"
                    )
                    if hidden_exit_override_triggered:
                        guard_reason += f" [HIDDEN-EXIT-OVERRIDE: exit known, resuming navigation mode]"
                elif stuck_reexplore_active:
                    guard_override = True
                    guard_reason = (
                        "Stuck re-explore override: suppressing objective routing and forcing branch re-checks. "
                        f"cooldown={self._maze_reexplore_cooldown_remaining} repeats={current_cell_repeats} "
                        f"no_progress={no_progress_steps} unknown={_unknown_now} frontier={_frontier_now}"
                    )
                    if objective_relax_guard_note:
                        guard_reason += f" {objective_relax_guard_note}"
                if objective_move:
                    objective_move, objective_risk_guard_note = self._objective_move_with_risk_guard(objective_move)
                    enforce_objective_progress = bool(
                        target_path_now
                        and (
                            fully_mapped_now
                            or (
                                target_known_in_episode
                                and (_unknown_now <= 1 and _frontier_now <= 1)
                                and (not map_doubt_active)
                                and (not stuck_reexplore_active)
                            )
                        )
                    )
                    if enforce_objective_progress and target_path_now:
                        objective_move, objective_progress_guard_note = self._objective_progress_guard(
                            objective_move,
                            target_path_now[0],
                            enforce_strict_progress=True,
                        )
                        if objective_progress_guard_note:
                            objective_risk_guard_note = (
                                f"{objective_risk_guard_note} {objective_progress_guard_note}".strip()
                                if objective_risk_guard_note
                                else objective_progress_guard_note
                            )
                if objective_move:
                    selected_move = objective_move
                    fallback_used = True
                    guard_override = True
                    # Capture diagnostic state at the moment of override so logs can
                    # assert "exit was actually in FOV" rather than just "guard fired".
                    _t_row, _t_col = self.current_target_cell
                    _exit_in_fov = (
                        self.maze_known_cells.get(self.current_target_cell, "") == "E"
                        and self._is_local_cell_visible(
                            self.current_player_cell[0],
                            self.current_player_cell[1],
                            _t_row,
                            _t_col,
                            facing=self.player_facing,
                        )
                    )
                    _ep_summary = self._episodic_memory_summary()
                    _unknown_at_override = int(_ep_summary.get("unknown") or 0)
                    _frontier_at_override = int(_ep_summary.get("frontier") or 0)
                    reason_suffix = ""
                    if loop_escape_override_triggered:
                        _cumulative_penalty = sum(self._recent_step_penalties)
                        reason_suffix = f" [LOOP-ESCAPE-OVERRIDE: cumulative_penalty={_cumulative_penalty}]"
                    if retry_capture_active:
                        reason_suffix += (
                            f" [RETRY-CAPTURE-OVERRIDE: retries={self._active_same_maze_retry_count()} "
                            f"path_len={len(target_path_now)}]"
                        )
                    if sticky_objective_active:
                        reason_suffix += f" [STICKY-OBJECTIVE: path_len={len(self._sticky_objective_path)}]"
                    if objective_risk_guard_note:
                        reason_suffix += f" {objective_risk_guard_note}"
                    guard_reason = (
                        f"Objective override: exit visible/known, prioritizing capture path. "
                        f"exit_in_fov={_exit_in_fov} "
                        f"unknown={_unknown_at_override} frontier={_frontier_at_override}"
                        + reason_suffix
                    )
                elif fully_mapped_now and (not map_doubt_active) and (not frontier_lock_active):
                    # Once mapping has converged (unknown=0 and frontier=0),
                    # never fall back to open-ended exploration: either take a
                    # shortest-path capture step or terminate this episode.
                    _path_to_target = self._shortest_path_moves_between_cells(
                        self.current_player_cell,
                        self.current_target_cell,
                    )
                    if _path_to_target:
                        self._prime_sticky_objective_path(_path_to_target)
                        selected_move, objective_risk_guard_note = self._objective_move_with_risk_guard(_path_to_target[0])
                        selected_move, objective_progress_guard_note = self._objective_progress_guard(
                            selected_move,
                            _path_to_target[0],
                            enforce_strict_progress=True,
                        )
                        if objective_progress_guard_note:
                            objective_risk_guard_note = (
                                f"{objective_risk_guard_note} {objective_progress_guard_note}".strip()
                                if objective_risk_guard_note
                                else objective_progress_guard_note
                            )
                        navigation_mode_lock = True
                        fallback_used = True
                        guard_override = True
                        _risk_suffix = f" {objective_risk_guard_note}" if objective_risk_guard_note else ""
                        guard_reason = (
                            "Fully-mapped policy: forcing shortest-path capture step "
                            f"(len={len(_path_to_target)}).{_risk_suffix}"
                        )
                    else:
                        end_episode_early = True
                        guard_override = True
                        guard_reason = (
                            "Fully-mapped policy: no route to target from current cell; "
                            "ending episode to avoid exploration loop."
                        )

                best_explore = self._best_exploration_move()
                if not selected_move and not end_episode_early:
                    selected_move = best_explore
                    fallback_used = bool(best_explore)

                targeted_assist_move = ""
                legal_candidate_rows: list[tuple[str, dict[str, object]]] = []
                for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                    if not self._is_valid_traversal_move(move):
                        continue
                    legal_candidate_rows.append((move, self._exploration_move_breakdown(move)))
                should_use_targeted_assist, assist_trigger_reason, assist_trigger_strength = (
                    self._should_request_targeted_maze_model_assist(
                        map_doubt_active=map_doubt_active,
                        stuck_reexplore_active=stuck_reexplore_active,
                        fully_mapped_now=fully_mapped_now,
                        exit_visible_now=exit_visible_now,
                        local_contradiction_pressure=local_contradiction_pressure,
                        current_cell_repeats=current_cell_repeats,
                        no_progress_steps=no_progress_steps,
                        legal_move_count=len(legal_candidate_rows),
                    )
                )
                if (
                    (not use_model_step_calls)
                    and (not navigation_mode_lock)
                    and (not objective_move)
                    and (not frontier_lock_active)
                    and (not fully_mapped_now)
                    and should_use_targeted_assist
                ):
                    tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
                    legal_candidate_rows.sort(
                        key=lambda item: (int(item[1].get("score", 0) or 0), tie_order.get(item[0], 9))
                    )
                    assist_candidate_count = max(2, min(4, 2 + int(round(self.maze_model_assist_reliance * 2))))
                    assist_result = self._targeted_maze_model_assist(
                        user_prompt,
                        plan,
                        assistant_instructions,
                        assist_trigger_reason,
                        assist_trigger_strength,
                        legal_candidate_rows[:assist_candidate_count],
                    )
                    if assist_result.get("move"):
                        targeted_assist_move = str(assist_result.get("move") or "")
                        proposed_move = targeted_assist_move
                        evaluation["proposal_source"] = "targeted_model"
                        evaluation["reason"] = str(assist_result.get("reason") or "")
                        evaluation["move"] = targeted_assist_move
                        evaluation["gets_closer"] = bool(
                            self._distance_after_single_move(targeted_assist_move) <= current_distance_maze
                        )
                        assist_breakdown = next(
                            (breakdown for move, breakdown in legal_candidate_rows if move == targeted_assist_move),
                            self._exploration_move_breakdown(targeted_assist_move),
                        )
                        planner_breakdown = self._exploration_move_breakdown(selected_move) if selected_move else None
                        assist_score = int(assist_breakdown.get("score", 0) or 0)
                        planner_score = int(planner_breakdown.get("score", 0) or 0) if planner_breakdown else 0
                        assist_margin = max(2, int(round(4 + (self.maze_model_assist_reliance * 24))))
                        if bool(assist_result.get("used")) and ((not selected_move) or assist_score <= planner_score + assist_margin):
                            prior_reason = guard_reason
                            selected_move = targeted_assist_move
                            fallback_used = False
                            guard_override = True
                            evaluation["approved"] = True
                            guard_reason = (
                                f"Targeted-model override: trigger={assist_trigger_reason} strength={assist_trigger_strength} "
                                f"selected '{targeted_assist_move}' over planner '{best_explore or '(none)'}' "
                                f"(assist_score={assist_score}, planner_score={planner_score}, margin={assist_margin})."
                            )
                            if prior_reason:
                                guard_reason = f"{prior_reason} {guard_reason}".strip()
                        else:
                            evaluation["approved"] = False
                            guard_override = True
                            assist_hold_reason = (
                                f"Targeted-model hold: suggested '{targeted_assist_move}' under trigger={assist_trigger_reason} "
                                f"but planner kept '{selected_move or best_explore or '(none)'}' "
                                f"(assist_score={assist_score}, planner_score={planner_score}, margin={assist_margin})."
                            )
                            guard_reason = f"{guard_reason} {assist_hold_reason}".strip() if guard_reason else assist_hold_reason

                model_candidate = ""
                if evaluation["approved"] and evaluation["move"]:
                    model_candidate = evaluation["move"]
                elif self._is_valid_traversal_move(proposed_move):
                    model_candidate = proposed_move

                if (
                    (not navigation_mode_lock)
                    and (not frontier_lock_active)
                    and model_candidate
                    and self._is_valid_traversal_move(model_candidate)
                    and best_explore
                ):
                    if model_candidate == best_explore:
                        selected_move = model_candidate
                        fallback_used = False
                    else:
                        candidate_breakdown = self._exploration_move_breakdown(model_candidate)
                        best_breakdown = self._exploration_move_breakdown(best_explore)
                        candidate_score = candidate_breakdown["score"]
                        best_score = best_breakdown["score"]
                        score_gap = candidate_score - best_score
                        guard_override = True
                        guard_reason = (
                            f"Plan-hold override: planner chose '{best_explore}' "
                            f"(score={best_score}, base={best_breakdown.get('base_score_without_noise', best_score)}, "
                            f"noise={best_breakdown.get('decision_noise', 0)}) over model '{model_candidate}' "
                            f"(score={candidate_score}, base={candidate_breakdown.get('base_score_without_noise', candidate_score)}, "
                            f"noise={candidate_breakdown.get('decision_noise', 0)}), gap={score_gap}."
                        )

                # Anti-oscillation guard: avoid A-B-A-B ping-pong unless
                # immediate backtrack is the only legal traversal option.
                if (not navigation_mode_lock) and (not frontier_lock_active) and selected_move and self._is_valid_traversal_move(selected_move):
                    selected_next = self._neighbor_for_move(self.current_player_cell, selected_move)
                    if selected_next == self.prev_prev_player_cell:
                        selected_breakdown = self._exploration_move_breakdown(selected_move)
                        selected_score = int(selected_breakdown["score"])
                        tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
                        alternatives: list[tuple[str, int]] = []
                        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                            if not self._is_valid_traversal_move(move):
                                continue
                            nxt = self._neighbor_for_move(self.current_player_cell, move)
                            if nxt == self.prev_prev_player_cell:
                                continue
                            breakdown = self._exploration_move_breakdown(move)
                            alternatives.append((move, int(breakdown["score"])))

                        if alternatives:
                            alternatives.sort(key=lambda item: (item[1], tie_order.get(item[0], 9)))
                            replacement_move, replacement_score = alternatives[0]
                            max_guard_margin = max(0, int(self.cycle_guard_score_margin))
                            should_override = replacement_score <= selected_score + max_guard_margin
                            if replacement_move != selected_move and should_override:
                                prior_reason = guard_reason
                                guard_override = True
                                fallback_used = True
                                selected_move = replacement_move
                                oscillation_reason = (
                                    f"Anti-oscillation override: replaced immediate backtrack with '{replacement_move}' "
                                    f"(score={replacement_score} vs {selected_score}, margin={max_guard_margin})."
                                )
                                guard_reason = (
                                    f"{prior_reason} {oscillation_reason}".strip()
                                    if prior_reason
                                    else oscillation_reason
                                )

                # Cycle guard: avoid stepping into recently revisited cells
                # when a reasonably-scored non-recent option exists.
                if (not navigation_mode_lock) and (not frontier_lock_active) and selected_move and self._is_valid_traversal_move(selected_move):
                    selected_next = self._neighbor_for_move(self.current_player_cell, selected_move)
                    selected_visits = self.episode_visited_cells.get(selected_next, 0)
                    recent_window_size = max(8, self.recent_cycle_window)
                    recent_window = set(list(self.maze_recent_cells)[-recent_window_size:])
                    selected_forward_count, selected_reverse_count = self._recent_transition_counts(
                        self.current_player_cell,
                        selected_next,
                    )
                    selected_is_transition_cycle = (selected_forward_count > 0 or selected_reverse_count > 0)
                    if (selected_visits > 0 and selected_next in recent_window) or selected_is_transition_cycle:
                        selected_breakdown = self._exploration_move_breakdown(selected_move)
                        selected_score = int(selected_breakdown["score"])
                        tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
                        alternatives: list[tuple[str, int]] = []
                        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                            if move == selected_move or not self._is_valid_traversal_move(move):
                                continue
                            nxt = self._neighbor_for_move(self.current_player_cell, move)
                            if nxt in recent_window:
                                continue
                            alt_forward_count, alt_reverse_count = self._recent_transition_counts(
                                self.current_player_cell,
                                nxt,
                            )
                            if alt_forward_count > 0 or alt_reverse_count > 0:
                                continue
                            b = self._exploration_move_breakdown(move)
                            alternatives.append((move, int(b["score"])))

                        if alternatives:
                            alternatives.sort(key=lambda item: (item[1], tie_order.get(item[0], 9)))
                            replacement_move, replacement_score = alternatives[0]
                            # Allow a modest score margin to escape loops without
                            # forcing obviously bad moves.
                            if replacement_score <= selected_score + max(0, self.cycle_guard_score_margin):
                                prior_reason = guard_reason
                                guard_override = True
                                fallback_used = True
                                selected_move = replacement_move
                                cycle_reason = (
                                    f"Cycle-avoid override: replaced loop-prone move with '{replacement_move}' "
                                    f"(score={replacement_score} vs {selected_score}, "
                                    f"transition_counts={selected_forward_count}/{selected_reverse_count})."
                                )
                                guard_reason = (
                                    f"{prior_reason} {cycle_reason}".strip()
                                    if prior_reason
                                    else cycle_reason
                                )

                # Look-sweep guard: if a move visibly leads into a terminal or
                # boxed corridor with no visible exit, prefer a safer
                # alternative within a modest score margin.
                if (not navigation_mode_lock) and (not frontier_lock_active) and selected_move and self._is_valid_traversal_move(selected_move):
                    selected_risky = (
                        self._is_move_visibly_terminal_dead_end(self.current_player_cell, selected_move)
                        or self._is_move_visibly_boxed_corridor_without_exit(self.current_player_cell, selected_move)
                    )
                    if selected_risky:
                        selected_breakdown = self._exploration_move_breakdown(selected_move)
                        selected_score = int(selected_breakdown["score"])
                        tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
                        alternatives: list[tuple[str, int]] = []
                        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                            if move == selected_move or not self._is_valid_traversal_move(move):
                                continue
                            if (
                                self._is_move_visibly_terminal_dead_end(self.current_player_cell, move)
                                or self._is_move_visibly_boxed_corridor_without_exit(self.current_player_cell, move)
                            ):
                                continue
                            b = self._exploration_move_breakdown(move)
                            alternatives.append((move, int(b["score"])))

                        if alternatives:
                            alternatives.sort(key=lambda item: (item[1], tie_order.get(item[0], 9)))
                            replacement_move, replacement_score = alternatives[0]
                            if replacement_score <= selected_score + max(0, self.terminal_end_guard_margin):
                                prior_reason = guard_reason
                                guard_override = True
                                fallback_used = True
                                selected_move = replacement_move
                                terminal_reason = (
                                    f"Terminal/boxed-corridor override: replaced risky branch with '{replacement_move}' "
                                    f"(score={replacement_score} vs {selected_score})."
                                )
                                guard_reason = (
                                    f"{prior_reason} {terminal_reason}".strip()
                                    if prior_reason
                                    else terminal_reason
                                )
            elif evaluation["approved"] and evaluation["move"]:
                selected_move = evaluation["move"]
            elif self.enable_path_fallback:
                path = self._shortest_path_moves_to_target()
                if path:
                    selected_move = path[0]
                    fallback_used = True

            current_distance = self._distance_from_target_for_cell(self.current_player_cell)
            selected_distance = self._distance_after_single_move(selected_move) if selected_move else current_distance
            if (not maze_mode) and self.strict_progress_guard and selected_move and selected_distance > current_distance:
                guard_move = self._best_progress_move()
                if guard_move:
                    guard_override = True
                    guard_reason = (
                        f"Selected move '{selected_move}' increased distance ({current_distance}->{selected_distance}); "
                        f"overridden to '{guard_move}'."
                    )
                    selected_move = guard_move
                    selected_distance = self._distance_after_single_move(selected_move)

            if end_episode_early:
                step_logs.append(
                    f"step={iterations + 1} proposal_source={evaluation.get('proposal_source', 'model')} "
                    f"proposed={proposed_move or '(none)'} selected=(none) approved={evaluation['approved']} "
                    f"gets_closer={evaluation['gets_closer']} kernel_move_used={fallback_used} "
                    f"guard_override={guard_override} pattern_name={evaluation.get('pattern_name', '')} "
                    f"memory_event={evaluation.get('memory_event', '')} distance_before={current_distance} "
                    f"distance_after={selected_distance} reason={guard_reason}"
                )
                break

            if not selected_move:
                break

            if maze_mode and self._is_valid_traversal_move(selected_move):
                selected_breakdown = self._exploration_move_breakdown(selected_move)
                if (
                    int(selected_breakdown.get("forced_single_exit", 0) or 0) > 0
                    and int(selected_breakdown.get("transition_pressure_bucket", 0) or 0) > 0
                ):
                    next_cell = self._neighbor_for_move(self.current_player_cell, selected_move)
                    if next_cell != self.current_player_cell:
                        self.recent_forced_corridor_cells.append(next_cell)
                decision_score = float(selected_breakdown.get("score", 0))
                outcome_value = -decision_score
                reward_signal = max(0.0, -decision_score)
                penalty_signal = max(0.0, decision_score)
                if int(selected_breakdown.get("forced_single_exit", 0) or 0) > 0 and outcome_value < 0:
                    # Avoid writing huge punishment traces for unavoidable moves.
                    capped_penalty = min(12.0, penalty_signal)
                    penalty_signal = capped_penalty
                    reward_signal = 0.0
                    outcome_value = -capped_penalty
                tags: list[str] = []
                risk_tag_fields = [
                    ("dead_end_end_slap_penalty", "dead_end_slap"),
                    ("dead_end_tip_revisit_slap_penalty", "dead_end_tip_revisit"),
                    ("revisit_dead_end_entrance_penalty", "dead_end_entrance_revisit"),
                    ("transition_repeat_penalty", "transition_repeat"),
                    ("cycle_pair_penalty", "cycle_pair"),
                    ("visible_terminal_end_penalty", "visible_terminal"),
                    ("boxed_corridor_penalty", "boxed_corridor"),
                    ("immediate_backtrack_hard_penalty", "immediate_backtrack"),
                    ("branch_diversity_penalty", "branch_diversity"),
                ]
                if outcome_value < -0.01:
                    # Keep risk causes only on punishment traces.
                    for field, tag in risk_tag_fields:
                        if float(selected_breakdown.get(field, 0) or 0) > 0:
                            tags.append(tag)
                elif outcome_value > 0.01:
                    # Keep progress context on reward traces.
                    if float(selected_breakdown.get("novelty_reward", 0) or 0) > 0:
                        tags.append("novelty_reward")
                    if int(selected_breakdown.get("visible_open_decision", 0) or 0) > 0:
                        tags.append("visible_open_decision")
                    if int(selected_breakdown.get("visible_exit_corridor", 0) or 0) > 0:
                        tags.append("visible_exit")
                    if bool(selected_breakdown.get("edge_frontier", False)):
                        tags.append("frontier_visible")
                    if bool(selected_breakdown.get("edge_junction", False)):
                        tags.append("junction_visible")
                self._record_action_outcome_memory(
                    action_taken=f"MOVE_{selected_move}",
                    outcome_value=outcome_value,
                    reward_signal=reward_signal,
                    penalty_signal=penalty_signal,
                    reason_tags=tags,
                    details={
                        "score": decision_score,
                        "base_score": selected_breakdown.get("base_score_without_noise", decision_score),
                        "decision_noise": selected_breakdown.get("decision_noise", 0),
                        "unknown_neighbors": selected_breakdown.get("unknown_neighbors", 0),
                        "open_degree": selected_breakdown.get("open_degree", 0),
                        "frontier_distance": selected_breakdown.get("frontier_distance", 0),
                        "edge_type": selected_breakdown.get("edge_type", ""),
                        "from_cell": list(self.current_player_cell),
                        "to_cell": list(self._neighbor_for_move(self.current_player_cell, selected_move)),
                    },
                    player_cell=self.current_player_cell,
                )
                # Track recent penalties for loop-escape detection
                self._recent_step_penalties.append(penalty_signal)

            if maze_mode:
                self._set_player_facing_from_move(selected_move)
                # Update perception before movement so the viewer reflects
                # look/decision orientation immediately.
                self.root.after(0, self._refresh_game_state)

            self._execute_single_move_blocking(selected_move)
            if maze_mode:
                # Look-sweep WM is transient per decision cycle.
                self._clear_working_memory_look_sweep()
            iterations += 1

            step_logs.append(
                f"step={iterations} "
                f"proposal_source={evaluation.get('proposal_source', 'model')} "
                f"proposed={proposed_move or '(none)'} selected={selected_move} "
                f"approved={evaluation['approved']} gets_closer={evaluation['gets_closer']} "
                f"kernel_move_used={fallback_used} guard_override={guard_override} "
                f"pattern_name={evaluation.get('pattern_name', '') or '(none)'} "
                f"memory_event={evaluation.get('memory_event', '') or 'memory:unknown'} "
                f"distance_before={'hidden' if maze_mode else current_distance} "
                f"distance_after={'hidden' if maze_mode else selected_distance} "
                f"reason={evaluation['reason']} {guard_reason}".strip()
            )

            live_tail = "\n".join(step_logs[-12:])
            live_debug = f"[STEP MODE LIVE]\n{live_tail}"
            if maze_mode:
                exploration_snapshot = self._format_exploration_candidates()
                live_debug += f"\n\n[EXPLORATION SCORES]\n{exploration_snapshot}"
            self.root.after(0, self._set_debug_text, live_debug)

        completed, remaining = self._goal_session_progress()
        success = remaining == 0
        if success:
            self.root.after(0, lambda: self.status_var.set("Step mode complete"))
        elif iterations >= iteration_budget:
            self.root.after(0, lambda: self.status_var.set("Step mode stopped: max iterations reached"))

        self._end_auto_goal_session()
        return {
            "requested_count": requested_count,
            "iterations": iterations,
            "completed": completed,
            "remaining": remaining,
            "success": success,
            "map_doubt_triggers": map_doubt_triggers,
            "stuck_reexplore_triggers": self._maze_stuck_trigger_count,
            "step_log": "\n".join(step_logs),
        }

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, padx=14, pady=14)
        container.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(container, text="AI Assistant", font=("Helvetica", 18, "bold"))
        title.pack(anchor="w", pady=(0, 8))

        panes = tk.PanedWindow(container, orient=tk.HORIZONTAL, sashwidth=6)
        panes.pack(fill=tk.BOTH, expand=True)
        self.main_panes = panes
        self.main_panes.bind("<ButtonRelease-1>", self._on_pane_resize)

        assistant_frame = tk.Frame(panes)
        game_frame = tk.Frame(panes)
        panes.add(assistant_frame, minsize=440)
        panes.add(game_frame, minsize=280)

        instruction_label = tk.Label(assistant_frame, text="Assistant Instructions (optional)")
        instruction_label.pack(anchor="w")

        self.instructions_input = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=4)
        self.instructions_input.pack(fill=tk.X, expand=False, pady=(4, 10))

        prompt_label = tk.Label(assistant_frame, text="Enter text")
        prompt_label.pack(anchor="w")

        self.prompt_input = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=7)
        self.prompt_input.pack(fill=tk.X, expand=False, pady=(4, 10))

        controls = tk.Frame(assistant_frame)
        controls.pack(fill=tk.X, pady=(0, 10))

        self.send_btn = tk.Button(controls, text="Send", width=12, command=self.on_send)
        self.send_btn.pack(side=tk.LEFT)

        clear_btn = tk.Button(controls, text="Clear", width=12, command=self.clear_text)
        clear_btn.pack(side=tk.LEFT, padx=(8, 0))

        copy_btn = tk.Button(controls, text="Copy Output", width=12, command=self.copy_pipeline_bundle)
        copy_btn.pack(side=tk.LEFT, padx=(8, 0))

        status = tk.Label(controls, textvariable=self.status_var, anchor="w")
        status.pack(side=tk.LEFT, padx=(16, 0))

        response_label = tk.Label(assistant_frame, text="Response")
        response_label.pack(anchor="w")

        self.response_output = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
        self.response_output.pack(fill=tk.BOTH, expand=True, pady=(4, 10))

        debug_label = tk.Label(assistant_frame, text="Pipeline Debug")
        debug_label.pack(anchor="w")

        self.debug_output = scrolledtext.ScrolledText(assistant_frame, wrap=tk.WORD, height=10, state=tk.DISABLED)
        self.debug_output.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        game_title = tk.Label(game_frame, text="Mini Game", font=("Helvetica", 14, "bold"))
        game_title.pack(anchor="w")

        game_note = tk.Label(game_frame, text="Move the square to the blue ball. Use Arrow keys or WASD.")
        game_note.pack(anchor="w", pady=(2, 8))

        self.game_canvas = tk.Canvas(
            game_frame,
            width=self.canvas_width,
            height=self.canvas_height,
            bg="#f5f7ff",
            highlightthickness=1,
            highlightbackground="#b6bfd3",
        )
        self.game_canvas.pack(fill=tk.NONE, expand=False)

        if self.enable_pseudo3d_view:
            pseudo3d_label = tk.Label(game_frame, text="Pseudo-3D Visualizer (preview)")
            pseudo3d_label.pack(anchor="w", pady=(8, 4))

            self.pseudo3d_canvas = tk.Canvas(
                game_frame,
                width=self.pseudo3d_width,
                height=self.pseudo3d_height,
                bg="#0f1220",
                highlightthickness=1,
                highlightbackground="#3b4667",
            )
            self.pseudo3d_canvas.pack(fill=tk.NONE, expand=False)

        game_controls = tk.Frame(game_frame)
        game_controls.pack(fill=tk.X, pady=(8, 0))
        tk.Label(game_controls, text="Mode").pack(side=tk.LEFT)
        mode_menu = tk.OptionMenu(game_controls, self.layout_mode, "grid", "maze", command=self._on_layout_settings_changed)
        mode_menu.config(width=7)
        mode_menu.pack(side=tk.LEFT, padx=(6, 8))

        tk.Label(game_controls, text="Difficulty").pack(side=tk.LEFT)
        diff_menu = tk.OptionMenu(
            game_controls,
            self.maze_difficulty,
            "easy",
            "medium",
            "hard",
            command=self._on_layout_settings_changed,
        )
        diff_menu.config(width=7)
        diff_menu.pack(side=tk.LEFT, padx=(6, 8))

        tk.Button(game_controls, text="Reset Target", command=self._spawn_target).pack(side=tk.LEFT)
        tk.Button(game_controls, text="New Layout", command=self._regenerate_blockers).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(game_controls, text="Next Maze", command=self._next_maze_layout).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(game_controls, text="Start #").pack(side=tk.LEFT, padx=(10, 4))
        tk.Entry(game_controls, textvariable=self.maze_map_start_var, width=6).pack(side=tk.LEFT)
        tk.Button(game_controls, text="Set Start", command=self._set_maze_start_number).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(game_controls, text="Reset Score", command=self._reset_score).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(game_controls, textvariable=self.score_var).pack(side=tk.LEFT, padx=(10, 0))

        memory_header = tk.Frame(game_frame)
        memory_header.pack(fill=tk.X, pady=(10, 4))
        tk.Label(memory_header, text="Maze Memory Viewer", font=("Helvetica", 10, "bold")).pack(side=tk.LEFT)
        tk.Label(memory_header, text="Run #").pack(side=tk.RIGHT, padx=(8, 4))
        tk.Entry(memory_header, textvariable=self.memory_run_id_var, width=8).pack(side=tk.RIGHT)
        tk.Button(memory_header, text="Copy Run Logs", command=self.copy_run_logs_bundle).pack(
            side=tk.RIGHT,
            padx=(8, 0),
        )
        tk.Button(memory_header, text="Copy Memory + Logs", command=self.copy_memory_bundle).pack(
            side=tk.RIGHT,
            padx=(8, 0),
        )
        tk.Button(memory_header, text="Reset Memory", command=self.reset_memory_store).pack(
            side=tk.RIGHT,
            padx=(8, 0),
        )
        tk.Button(memory_header, text="Refresh Memory", command=self._refresh_memory_viewer).pack(side=tk.RIGHT)

        self.memory_view_output = scrolledtext.ScrolledText(game_frame, wrap=tk.WORD, height=11, state=tk.DISABLED)
        self.memory_view_output.pack(fill=tk.BOTH, expand=True)

        self._init_game()
        self._refresh_memory_viewer()

        self.root.bind("<Command-Return>", self._on_cmd_enter)

    def _set_debug_text(self, text: str) -> None:
        safe_text = redact_secrets(text)
        self.debug_output.config(state=tk.NORMAL)
        self.debug_output.delete("1.0", tk.END)
        self.debug_output.insert(tk.END, safe_text)
        self.debug_output.config(state=tk.DISABLED)

    def _restore_window_geometry(self) -> None:
        try:
            if not os.path.exists(self.window_state_path):
                return
            with open(self.window_state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            geometry = payload.get("geometry", "").strip()
            if geometry:
                self.root.geometry(geometry)

            saved_mode = str(payload.get("layout_mode", "")).strip().lower()
            if saved_mode in {"grid", "maze"}:
                self.layout_mode.set(saved_mode)

            saved_difficulty = str(payload.get("maze_difficulty", "")).strip().lower()
            if saved_difficulty in {"easy", "medium", "hard"}:
                self.maze_difficulty.set(saved_difficulty)

            self._on_layout_settings_changed()

            saved_sash = payload.get("pane_sash_x")
            if isinstance(saved_sash, int):
                self._saved_sash_x = saved_sash
                self.root.after(50, self._restore_pane_sash)
        except Exception:  # noqa: BLE001
            # If window-state file is missing/corrupt, continue with defaults.
            return

    def _restore_pane_sash(self) -> None:
        if self._saved_sash_x is None:
            return
        if not hasattr(self, "main_panes"):
            return
        try:
            self.root.update_idletasks()
            max_sash = max(200, self.main_panes.winfo_width() - 220)
            sash_x = min(max(200, self._saved_sash_x), max_sash)
            self.main_panes.sash_place(0, sash_x, 1)
        except Exception:  # noqa: BLE001
            return

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        if self._geometry_save_after_id is not None:
            self.root.after_cancel(self._geometry_save_after_id)
        self._geometry_save_after_id = self.root.after(300, self._save_window_geometry)

    def _on_pane_resize(self, _event: tk.Event) -> None:
        if self._geometry_save_after_id is not None:
            self.root.after_cancel(self._geometry_save_after_id)
        self._geometry_save_after_id = self.root.after(120, self._save_window_geometry)

    def _save_window_geometry(self) -> None:
        self._geometry_save_after_id = None
        try:
            payload = {"geometry": self.root.winfo_geometry()}
            payload["layout_mode"] = self._normalized_layout_mode()
            payload["maze_difficulty"] = self._normalized_maze_difficulty()
            if hasattr(self, "main_panes"):
                sash_x, _ = self.main_panes.sash_coord(0)
                payload["pane_sash_x"] = int(sash_x)
            with open(self.window_state_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except Exception:  # noqa: BLE001
            return

    def copy_pipeline_bundle(self) -> None:
        prompt_text = self.prompt_input.get("1.0", tk.END).strip()
        instruction_text = self.instructions_input.get("1.0", tk.END).strip()
        response_text = self.response_output.get("1.0", tk.END).strip()
        debug_text = self.debug_output.get("1.0", tk.END).strip()

        bundle = (
            "[PROMPT]\n"
            f"{redact_secrets(prompt_text) or '(empty)'}\n\n"
            "[ASSISTANT INSTRUCTIONS]\n"
            f"{redact_secrets(instruction_text) or '(none)'}\n\n"
            "[RESPONSE]\n"
            f"{redact_secrets(response_text) or '(empty)'}\n\n"
            "[PIPELINE DEBUG]\n"
            f"{redact_secrets(debug_text) or '(empty)'}"
        )

        self.root.clipboard_clear()
        self.root.clipboard_append(bundle)
        self.root.update_idletasks()
        self.status_var.set("Copied response + pipeline to clipboard")

    def copy_memory_bundle(self) -> None:
        bundle = redact_secrets(self._memory_export_text())
        self.root.clipboard_clear()
        self.root.clipboard_append(bundle)
        self.root.update_idletasks()
        self.status_var.set("Copied memory + memory logs to clipboard")

    def copy_run_logs_bundle(self) -> None:
        raw_run_id = self.memory_run_id_var.get().strip() if hasattr(self, "memory_run_id_var") else ""
        if not raw_run_id:
            self.status_var.set("Enter a run ID first")
            return
        try:
            run_id = int(raw_run_id)
        except ValueError:
            self.status_var.set("Run ID must be an integer")
            return

        bundle = redact_secrets(self._memory_export_text_for_run(run_id))
        self.root.clipboard_clear()
        self.root.clipboard_append(bundle)
        self.root.update_idletasks()
        self.status_var.set(f"Copied run logs for run {run_id}")

    def reset_memory_store(self) -> None:
        memory_tables = [
            "maze_structural_memory",
            "maze_layout_cell_memory",
            "maze_pattern_catalog",
            "maze_short_term_memory",
            "maze_semantic_memory",
            "maze_action_outcome_memory",
            "maze_cause_effect_stm",
            "maze_cause_effect_semantic",
            "maze_prediction_memory",
        ]
        try:
            with sqlite3.connect(self.memory_db_path) as conn:
                for table_name in memory_tables:
                    conn.execute(f"DELETE FROM {table_name}")
                # Reset AUTOINCREMENT counters so memory IDs restart after wipe.
                for table_name in memory_tables:
                    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))
                conn.commit()
        except Exception:  # noqa: BLE001
            self.status_var.set("Failed to reset memory store")
            return

        self._clear_working_memory()
        self._reset_maze_known_map()
        self._semantic_reinforce_recent.clear()
        self._last_wm_signature_logged = ""
        self._last_wm_signature_logged_step = -1
        self._reset_organism_control_state()
        self.memory_step_index = 0
        self._last_endocrine_trace_step = -1
        self.episode_dead_end_learn_events = 0
        self.episode_dead_end_samples = set()
        self.episode_dead_end_entrances = set()
        self.episode_dead_end_tip_cells = set()
        self._clear_prediction_memory_state(clear_score=True)
        self.memory_event_log.clear()
        self.endocrine_event_log.clear()
        self._refresh_memory_viewer()
        self._refresh_game_state()
        self.status_var.set("Memory store fully reset")

    def _refresh_game_state(self) -> None:
        px1, py1, px2, py2 = self.game_canvas.coords(self.player)
        tx1, ty1, tx2, ty2 = self.game_canvas.coords(self.target)

        player_center_x = (px1 + px2) / 2
        player_center_y = (py1 + py2) / 2
        target_center_x = (tx1 + tx2) / 2
        target_center_y = (ty1 + ty2) / 2

        dx = round(target_center_x - player_center_x, 2)
        dy = round(target_center_y - player_center_y, 2)
        player_row, player_col = self._cell_from_center(player_center_x, player_center_y)
        target_row, target_col = self._cell_from_center(target_center_x, target_center_y)
        distance_steps = self._distance_between_cells((player_row, player_col), (target_row, target_col))
        proximity_ratio = max(0.0, 1.0 - (distance_steps / max(1, (self.grid_cells * 2 - 2))))
        if self.last_manhattan_distance == 0:
            temperature = "unknown"
        elif distance_steps < self.last_manhattan_distance:
            temperature = "hotter"
        elif distance_steps > self.last_manhattan_distance:
            temperature = "colder"
        else:
            temperature = "same"
        self.last_manhattan_distance = distance_steps
        efficiency = 0.0
        if self.episode_steps > 0:
            efficiency = min(1.0, self.episode_optimal_steps / self.episode_steps)

        # Update live positions immediately from canvas sampling so perception,
        # memory snapshots, and planner context remain frame-consistent.
        self.current_player_cell = (player_row, player_col)
        self.current_target_cell = (target_row, target_col)

        mode = self._normalized_layout_mode()
        if mode == "maze":
            self._update_maze_known_map(player_row, player_col, radius=1, facing=self.player_facing)
            self._resolve_visible_predictions()
            self._queue_frontier_predictions()
            if self.endocrine_enabled:
                endocrine_before = self.endocrine.state()
                self.endocrine.tick(self.memory_step_index)
                signature_text = self._current_pattern_signature((player_row, player_col))
                if signature_text:
                    try:
                        self.endocrine.update_from_signature(json.loads(signature_text), self.memory_step_index)
                    except Exception:  # noqa: BLE001
                        pass
                endocrine_after = self.endocrine.state()
                endocrine_delta = self._endocrine_delta_text(endocrine_before, endocrine_after)
                if endocrine_delta and self._last_endocrine_trace_step != self.memory_step_index:
                    self._last_endocrine_trace_step = self.memory_step_index
                    self._append_endocrine_event(
                        "signature",
                        (
                            f"delta=[{endocrine_delta}] cell={player_row},{player_col} "
                            f"facing={self.player_facing}"
                        ),
                    )
            self.mental_sweep_cells = self._build_mental_sweep(player_row, player_col)
            self._draw_fov_overlay(player_row, player_col)
            self._draw_mental_sweep_overlay(player_row, player_col)
            self._working_memory_snapshot(current_cell=(player_row, player_col))
            self._store_current_maze_memory_snapshot()
            personality = self.maze_personality or {}
            perception_block = (
                f"Directional FOV status (facing={self.player_facing}, depth={self.maze_fov_depth}, "
                f"peripheral={self.maze_fov_peripheral}, cone_deg={round(self.maze_fov_cone_degrees, 1)}, "
                f"falloff={round(self.maze_fov_distance_falloff, 3)}, "
                f"corner_graze={round(self.maze_fov_corner_graze_factor, 3)}, "
                f"wedge_dist_scale={round(self.maze_fov_wedge_distance_scale, 3)}, "
                f"full>={round(self.maze_fov_full_threshold, 3)}, half>={round(self.maze_fov_half_threshold, 3)}, "
                f"behind=hidden):\n"
                f"{self._build_local_status_snapshot(player_row, player_col, radius=1, include_render_details=True)}\n"
                "Legend: P=player, E=visible exit, O=full-visible open, H=half-visible open (cone boundary), "
                "B=visible blocker/wall frame, ?=not visible, arrows (^ > v <)=single opening-edge marker side.\n\n"
                "Renderable FOV (model-friendly, same visibility source as canvas):\n"
                f"{self._build_interpretable_fov_snapshot(player_row, player_col)}\n\n"
                f"Maze personality: {self.maze_personality_name} "
                f"(dead_end_allowance={int(personality.get('dead_end_allowance', self.dead_end_learning_allowance_base))}, "
                f"dead_end_learned={self.episode_dead_end_learn_events}, "
                f"novelty_scale={round(float(personality.get('novelty_reward_scale', 1.0)), 2)}, "
                f"dead_end_scale={round(float(personality.get('dead_end_penalty_scale', 1.0)), 2)}).\n\n"
                "Boundary rule: outside the grid is a hard wall (WALL), never unknown/open.\n"
                f"Immediate move walls/open: {self._boundary_blocked_summary((player_row, player_col))}\n\n"
                f"Mental directional edge scan (look-around before move):\n"
                f"{self._mental_edge_scan_summary(player_row, player_col)}"
            )
            target_metrics_line = "Target signal hidden. Distance/proximity feedback disabled in maze mode."
            episode_objective_line = "Episode optimal steps hidden in maze mode."
        else:
            self._clear_fov_overlay()
            self._clear_mental_sweep_overlay()
            self.mental_sweep_cells = {}
            perception_block = (
                "Grid snapshot:\n"
                f"{self._build_grid_snapshot(player_center_x, player_center_y, target_center_x, target_center_y)}"
            )
            target_metrics_line = (
                f"Current shortest-path distance: {distance_steps} steps. "
                f"Proximity ratio: {round(proximity_ratio, 3)}. "
                f"Hotter/colder signal: {temperature}."
            )
            episode_objective_line = f"Episode optimal steps at spawn: {self.episode_optimal_steps}."

        self._draw_pseudo3d_view(player_row, player_col)

        snapshot = (
            f"Canvas: {self.canvas_width}x{self.canvas_height}. "
            f"Mode: {mode}. "
            f"Maze difficulty: {self._normalized_maze_difficulty()}. "
            f"Maze algorithm: {self.current_maze_algorithm or 'n/a'}. "
            f"Player center: ({round(player_center_x, 2)}, {round(player_center_y, 2)}). "
            f"Target center hidden. Vector target-player hidden.\n"
            f"Player cell(row,col): ({player_row}, {player_col}). "
            f"Target cell hidden. "
            f"Blocked cells: {len(self.blocked_cells)}. "
            f"{target_metrics_line}\n"
            f"{episode_objective_line} "
            f"Episode steps taken: {self.episode_steps}. "
            f"Maze attempt count (current): {self.episode_maze_attempt_count}. "
            f"Last maze solved attempts: {self.last_maze_solve_attempts}. "
            f"Episode revisit steps: {self.episode_revisit_steps}. "
            f"Episode backtracks: {self.episode_backtracks}. "
            f"Current efficiency: {round(efficiency, 3)}. "
            f"Total reward: {round(self.total_reward, 2)}. "
            f"Prediction score (maze): {round(self.prediction_score_current_maze, 2)} "
            f"(lifetime={round(self.prediction_score_total, 2)}, "
            f"occ_acc={round(self._prediction_accuracy(), 3)}, "
            f"shape_acc={round(self._prediction_shape_accuracy(), 3)}, "
            f"full_acc={round(self._prediction_full_accuracy(), 3)}, "
            f"occ_brier={round(self._prediction_avg_occupancy_brier(), 3)}, "
            f"shape_brier={round(self._prediction_avg_shape_brier(), 3)}, "
            f"pending={len(self.prediction_memory_active)}, expired={self.prediction_expired_count}).\n"
            f"{perception_block}"
        )

        with self.game_state_lock:
            self.current_player_cell = (player_row, player_col)
            self.current_target_cell = (target_row, target_col)
            self.latest_game_state = snapshot

    def _get_game_state_snapshot(self) -> str:
        with self.game_state_lock:
            snapshot = self.latest_game_state
        memory_reference = self._maze_memory_context()
        if memory_reference:
            return f"{snapshot}\n\nMaze memory reference:\n{memory_reference}"
        return snapshot

    def _build_grid_snapshot(
        self,
        player_center_x: float,
        player_center_y: float,
        target_center_x: float,
        target_center_y: float,
        cells: int | None = None,
    ) -> str:
        if cells is None:
            cells = self.grid_cells
        grid = [["." for _ in range(cells)] for _ in range(cells)]

        for row, col in self.blocked_cells:
            if 0 <= row < cells and 0 <= col < cells:
                grid[row][col] = "#"

        p_col = min(cells - 1, max(0, int((player_center_x / self.canvas_width) * cells)))
        p_row = min(cells - 1, max(0, int((player_center_y / self.canvas_height) * cells)))
        t_col = min(cells - 1, max(0, int((target_center_x / self.canvas_width) * cells)))
        t_row = min(cells - 1, max(0, int((target_center_y / self.canvas_height) * cells)))

        grid[p_row][p_col] = "P"
        if grid[t_row][t_col] == "P":
            grid[t_row][t_col] = "X"
        else:
            grid[t_row][t_col] = "T"

        return "\n".join(" ".join(row) for row in grid)

    def _with_ascii_boundary(self, rows: list[str], boundary_token: str = "B") -> str:
        if not rows:
            return ""
        tokenized_rows: list[list[str]] = []
        width = 0
        for row in rows:
            tokens = row.split()
            if not tokens:
                continue
            tokenized_rows.append(tokens)
            width = max(width, len(tokens))
        if width <= 0 or not tokenized_rows:
            return "\n".join(rows)

        top_bottom = " ".join([boundary_token] * (width + 2))
        framed: list[str] = [top_bottom]
        for tokens in tokenized_rows:
            if len(tokens) < width:
                tokens = tokens + (["?"] * (width - len(tokens)))
            framed.append(" ".join([boundary_token] + tokens + [boundary_token]))
        framed.append(top_bottom)
        return "\n".join(framed)

    def _edge_context_probe_cells(
        self,
        origin_row: int,
        origin_col: int,
        facing: str | None = None,
    ) -> set[tuple[int, int]]:
        """
        Return nearby side-context cells around the forward beam for ASCII views.

        This augments strict cone visibility by exposing immediate side occupancy
        (blocked vs open) around the currently looked corridor.
        """
        fv_r, fv_c = self._facing_vector_for(facing)
        facing_value = (facing or self.player_facing or "UP").strip().upper()
        if facing_value in {"UP", "DOWN"}:
            side_vectors = [(0, -1), (0, 1)]
        else:
            side_vectors = [(-1, 0), (1, 0)]

        cells: set[tuple[int, int]] = set()

        for step in range(0, self.grid_cells + 1):
            beam_row = origin_row + (fv_r * step)
            beam_col = origin_col + (fv_c * step)
            if beam_row < 0 or beam_row >= self.grid_cells or beam_col < 0 or beam_col >= self.grid_cells:
                break

            if step > 0 and not self._is_local_cell_visible(origin_row, origin_col, beam_row, beam_col, facing=facing):
                break

            for sv_r, sv_c in side_vectors:
                side_row = beam_row + sv_r
                side_col = beam_col + sv_c
                if 0 <= side_row < self.grid_cells and 0 <= side_col < self.grid_cells:
                    cells.add((side_row, side_col))

                # Also include one-ahead side cells so corridor mouths are visible.
                ahead_side_row = beam_row + fv_r + sv_r
                ahead_side_col = beam_col + fv_c + sv_c
                if 0 <= ahead_side_row < self.grid_cells and 0 <= ahead_side_col < self.grid_cells:
                    cells.add((ahead_side_row, ahead_side_col))

            if self._is_blocked_cell((beam_row, beam_col)):
                break

        cells.discard((origin_row, origin_col))
        return cells

    def _build_local_status_snapshot(
        self,
        player_row: int,
        player_col: int,
        radius: int = 1,
        include_render_details: bool = False,
        facing: str | None = None,
    ) -> str:
        facing_for_view = (facing or self.player_facing)
        edge_markers: dict[tuple[int, int], str] = {}
        edge_context_cells = self._edge_context_probe_cells(player_row, player_col, facing_for_view)
        if include_render_details:
            edge_list = self._visible_edge_opening_cells(player_row, player_col, facing_for_view)
            for row, col, side in edge_list:
                edge_markers[(row, col)] = {
                    "UP": "^",
                    "RIGHT": ">",
                    "DOWN": "v",
                    "LEFT": "<",
                }.get(side, "*")

        grid_rows: list[str] = []
        for row in range(self.grid_cells):
            tokens: list[str] = []
            for col in range(self.grid_cells):
                vis_kind = self._local_visibility_kind(player_row, player_col, row, col, facing=facing_for_view)
                if row == player_row and col == player_col:
                    token = "P"
                elif vis_kind == "none":
                    if (row, col) in edge_context_cells:
                        token = "B" if (row, col) in self.blocked_cells else "O"
                    else:
                        token = "?"
                elif (row, col) == self.current_target_cell:
                    token = "E"
                elif (row, col) in self.blocked_cells:
                    token = "B"
                elif vis_kind == "half":
                    token = "H"
                else:
                    token = "O"

                if include_render_details and (row, col) in edge_markers and token in {"O", "H"}:
                    token = f"{token}{edge_markers[(row, col)]}"

                tokens.append(token)
            grid_rows.append(" ".join(tokens))

        rows: list[str] = [self._with_ascii_boundary(grid_rows)]

        if include_render_details:
            if edge_markers:
                details = ", ".join(
                    f"({row},{col}) side={side}"
                    for row, col, side in self._visible_edge_opening_cells(player_row, player_col, facing_for_view)
                )
            else:
                details = "none"
            rows.append(f"Beam side edge marker(s): {details}")

        return "\n".join(rows)

    def _build_interpretable_fov_snapshot(self, player_row: int, player_col: int) -> str:
        edge_markers: dict[tuple[int, int], str] = {}
        edge_context_cells = self._edge_context_probe_cells(player_row, player_col, self.player_facing)
        for row, col, side in self._visible_edge_opening_cells(player_row, player_col, self.player_facing):
            edge_markers[(row, col)] = {
                "UP": "^",
                "RIGHT": ">",
                "DOWN": "v",
                "LEFT": "<",
            }.get(side, "*")

        grid_rows: list[str] = []
        corner_graze_cells: list[str] = []
        for row in range(self.grid_cells):
            tokens: list[str] = []
            for col in range(self.grid_cells):
                if row == player_row and col == player_col:
                    tokens.append("P")
                    continue

                vis_kind = self._local_visibility_kind(player_row, player_col, row, col)
                if vis_kind == "none":
                    if (row, col) in edge_context_cells:
                        tokens.append("B" if (row, col) in self.blocked_cells else "O")
                    else:
                        tokens.append("?")
                    continue

                strength = self._visibility_strength(
                    player_row,
                    player_col,
                    row,
                    col,
                    facing=self.player_facing,
                )
                strength_bin = int(round(max(0.0, min(1.0, strength)) * 9.0))
                _los_clear, corner_graze_steps = self._line_of_sight_metrics(
                    player_row,
                    player_col,
                    row,
                    col,
                )
                if corner_graze_steps > 0:
                    corner_graze_cells.append(f"({row},{col},g={corner_graze_steps})")

                if (row, col) == self.current_target_cell:
                    token = f"E{strength_bin}"
                elif (row, col) in self.blocked_cells:
                    token = f"B{strength_bin}"
                elif vis_kind == "half":
                    token = f"H{strength_bin}"
                else:
                    token = f"O{strength_bin}"

                marker = edge_markers.get((row, col), "")
                if marker and token.startswith(("O", "H")):
                    token = f"{token}{marker}"

                tokens.append(token)

            grid_rows.append(" ".join(tokens))

        rows: list[str] = [self._with_ascii_boundary(grid_rows)]

        rows.append("Legend2: O#/H#/B#/E# use visibility strength bins 0..9 (higher=clearer/brighter).")
        if corner_graze_cells:
            rows.append(f"Corner-graze cells: {', '.join(corner_graze_cells)}")
        else:
            rows.append("Corner-graze cells: none")
        return "\n".join(rows)

    def _build_mental_sweep(self, player_row: int, player_col: int) -> dict[tuple[int, int], str]:
        """Temporary look-around map from all facings before selecting a move."""
        seen: dict[tuple[int, int], str] = {(player_row, player_col): "P"}
        for facing in ["UP", "RIGHT", "DOWN", "LEFT"]:
            for row in range(self.grid_cells):
                for col in range(self.grid_cells):
                    if not self._is_local_cell_visible(player_row, player_col, row, col, facing=facing):
                        continue
                    cell = (row, col)
                    if cell == self.current_target_cell:
                        seen[cell] = "E"
                    elif cell in self.blocked_cells:
                        seen[cell] = "B"
                    else:
                        seen[cell] = "O"
        return seen

    def _directional_edge_scan(self, player_row: int, player_col: int, facing: str) -> dict[str, int | bool | str]:
        """Edge scan in one direction to identify corridor extent and decision points."""
        fv_r, fv_c = self._facing_vector_for(facing)
        clear_run = 0
        blocked_ahead = False
        frontier_visible = False
        junction_visible = False
        exit_visible = False
        boxed_side_steps = 0
        edge_type = "open"
        side_open_steps = 0
        side_blocked_steps = 0
        side_open_contacts = 0
        side_blocked_contacts = 0
        side_unknown_contacts = 0
        inferred_side_open_steps = 0
        inferred_side_open_contacts = 0
        inferred_diagonal_open_contacts = 0

        if facing in {"UP", "DOWN"}:
            side_vectors = [(0, -1), (0, 1)]
        else:
            side_vectors = [(-1, 0), (1, 0)]

        def is_wall(cell_row: int, cell_col: int) -> bool:
            return (cell_row, cell_col) in self.blocked_cells

        def in_bounds(cell_row: int, cell_col: int) -> bool:
            return 0 <= cell_row < self.grid_cells and 0 <= cell_col < self.grid_cells

        def is_open_geometry(cell_row: int, cell_col: int) -> bool:
            return in_bounds(cell_row, cell_col) and (not is_wall(cell_row, cell_col))

        max_probe = max(2, self.grid_cells)
        for step in range(1, max_probe + 1):
            row = player_row + (fv_r * step)
            col = player_col + (fv_c * step)

            if not in_bounds(row, col):
                edge_type = "bounds"
                break

            visibility = self._local_visibility_kind(player_row, player_col, row, col, facing=facing)
            if visibility == "none":
                edge_type = "occluded"
                break

            if (row, col) in self.blocked_cells:
                blocked_ahead = True
                edge_type = "blocked"
                break

            clear_run += 1
            if (row, col) == self.current_target_cell:
                exit_visible = True
                edge_type = "exit"
                break

            side_a = (row + side_vectors[0][0], col + side_vectors[0][1])
            side_b = (row + side_vectors[1][0], col + side_vectors[1][1])
            side_cells = [side_a, side_b]

            side_statuses: list[str] = []
            inferred_side_flags = [False, False]
            for idx, (side_row, side_col) in enumerate(side_cells):
                if is_wall(side_row, side_col):
                    side_statuses.append("blocked")
                    side_blocked_contacts += 1
                elif self._is_local_cell_visible(player_row, player_col, side_row, side_col, facing=facing):
                    side_statuses.append("open")
                    side_open_contacts += 1
                else:
                    side_statuses.append("unknown")
                    side_unknown_contacts += 1

                    # Geometry inference: treat some non-visible non-wall side cells as likely branch openings.
                    # This catches wall gaps / side-corridor mouths that are implied by visible structure.
                    inferred_open = False
                    opposite_idx = 1 - idx
                    opposite_row, opposite_col = side_cells[opposite_idx]
                    opposite_is_wall = is_wall(opposite_row, opposite_col)

                    side_forward_row = side_row + fv_r
                    side_forward_col = side_col + fv_c
                    if is_open_geometry(side_forward_row, side_forward_col):
                        inferred_open = True

                    # If one side is wall and the other is non-wall but occluded, infer a wall-gap opening.
                    if opposite_is_wall:
                        inferred_open = True

                    # Diagonal around-corner inference: blocked side but diagonal ahead open implies a side gap.
                    diagonal_row = row + fv_r + side_vectors[idx][0]
                    diagonal_col = col + fv_c + side_vectors[idx][1]
                    if is_open_geometry(diagonal_row, diagonal_col):
                        inferred_open = True
                        inferred_diagonal_open_contacts += 1

                    inferred_side_flags[idx] = inferred_open
                    if inferred_open:
                        inferred_side_open_contacts += 1

            if "blocked" in side_statuses:
                side_blocked_steps += 1
            if "open" in side_statuses:
                side_open_steps += 1
                # A visible lateral opening along the beam is a decision point.
                junction_visible = True

            if any(inferred_side_flags):
                inferred_side_open_steps += 1
                # Treat inferred side geometry as branch evidence so scorer can avoid false terminals.
                junction_visible = True
                frontier_visible = True

            if side_statuses[0] == "blocked" and side_statuses[1] == "blocked":
                boxed_side_steps += 1

            degree = len(self._traversable_neighbors((row, col)))
            if degree >= 3:
                junction_visible = True
            if self._unknown_neighbor_count((row, col)) > 0:
                frontier_visible = True

        if edge_type == "open" and (frontier_visible or junction_visible):
            edge_type = "decision"

        boxed_corridor_without_exit = (
            clear_run >= 1
            and boxed_side_steps >= clear_run
            and edge_type in {"blocked", "bounds", "occluded"}
            and (not frontier_visible)
            and (not junction_visible)
            and (not exit_visible)
        )

        return {
            "clear_run": clear_run,
            "blocked_ahead": blocked_ahead,
            "frontier_visible": frontier_visible,
            "junction_visible": junction_visible,
            "exit_visible": exit_visible,
            "boxed_side_steps": boxed_side_steps,
            "side_open_steps": side_open_steps,
            "side_blocked_steps": side_blocked_steps,
            "side_open_contacts": side_open_contacts,
            "side_blocked_contacts": side_blocked_contacts,
            "side_unknown_contacts": side_unknown_contacts,
            "inferred_side_open_steps": inferred_side_open_steps,
            "inferred_side_open_contacts": inferred_side_open_contacts,
            "inferred_diagonal_open_contacts": inferred_diagonal_open_contacts,
            "boxed_corridor_without_exit": boxed_corridor_without_exit,
            "edge_type": edge_type,
            "edge_detected": edge_type in {"blocked", "bounds", "occluded", "decision", "exit"},
        }

    def _is_move_visibly_terminal_dead_end(self, origin: tuple[int, int], move: str) -> bool:
        if move not in {"UP", "DOWN", "LEFT", "RIGHT"}:
            return False
        if not self._is_valid_traversal_move(move):
            return False

        scan = self._directional_edge_scan(origin[0], origin[1], move)
        if scan["exit_visible"]:
            return False
        if scan["frontier_visible"] or scan["junction_visible"]:
            return False
        if scan["edge_type"] not in {"blocked", "bounds"}:
            return False
        # clear_run>=1 means there is at least one traversable step before the
        # visible terminal cap, i.e., a short corridor that likely dead-ends.
        return int(scan["clear_run"]) >= 1

    def _is_move_visibly_boxed_corridor_without_exit(self, origin: tuple[int, int], move: str) -> bool:
        if move not in {"UP", "DOWN", "LEFT", "RIGHT"}:
            return False
        if not self._is_valid_traversal_move(move):
            return False
        scan = self._directional_edge_scan(origin[0], origin[1], move)
        return bool(scan["boxed_corridor_without_exit"])

    def _mental_edge_scan_summary(self, player_row: int, player_col: int) -> str:
        lines: list[str] = []
        for facing in ["UP", "RIGHT", "DOWN", "LEFT"]:
            scan = self._directional_edge_scan(player_row, player_col, facing)
            lines.append(
                (
                    f"{facing}: clear_run={scan['clear_run']} edge={scan['edge_type']} "
                    f"frontier_visible={scan['frontier_visible']} junction_visible={scan['junction_visible']} "
                    f"side_open_steps={scan.get('side_open_steps', 0)} "
                    f"side_blocked_steps={scan.get('side_blocked_steps', 0)} "
                    f"inferred_side_open_steps={scan.get('inferred_side_open_steps', 0)}"
                )
            )
        return "\n".join(lines)

    def _sanitize_cell(self, cell: tuple[int, int]) -> tuple[int, int]:
        row, col = cell
        row = min(self.grid_cells - 1, max(0, row))
        col = min(self.grid_cells - 1, max(0, col))
        return (row, col)

    def _maze_profile(self) -> tuple[int, float]:
        difficulty = self._normalized_maze_difficulty()
        if difficulty == "easy":
            return (8, 0.003)
        if difficulty == "hard":
            return (12, 0.001)
        return (10, 0.002)

    def _open_region_connected(self, blocked: set[tuple[int, int]]) -> bool:
        total_cells = self.grid_cells * self.grid_cells
        open_count = total_cells - len(blocked)
        if open_count <= 1:
            return True

        start: tuple[int, int] | None = None
        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                if (row, col) not in blocked:
                    start = (row, col)
                    break
            if start is not None:
                break
        if start is None:
            return True

        seen = {start}
        queue: deque[tuple[int, int]] = deque([start])
        while queue:
            row, col = queue.popleft()
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                rr = row + dr
                cc = col + dc
                if rr < 0 or rr >= self.grid_cells or cc < 0 or cc >= self.grid_cells:
                    continue
                nxt = (rr, cc)
                if nxt in blocked or nxt in seen:
                    continue
                seen.add(nxt)
                queue.append(nxt)
        return len(seen) == open_count

    def _narrow_wide_openings(
        self,
        difficulty: str,
        protected_cell: tuple[int, int] | None,
        rng: random.Random,
    ) -> None:
        tightening_map = {
            "easy": (5, 24),
            "medium": (4, 18),
            "hard": (1, 6),
        }
        passes, max_fills = tightening_map.get(difficulty, (2, 10))
        protected = protected_cell
        filled = 0

        for _ in range(max(1, passes)):
            changed = False
            for row in range(self.grid_cells - 1):
                for col in range(self.grid_cells - 1):
                    block = [(row, col), (row + 1, col), (row, col + 1), (row + 1, col + 1)]
                    if any(cell in self.blocked_cells for cell in block):
                        continue

                    # Prefer blocking the most "room-like" cell in this 2x2 patch.
                    ranked: list[tuple[int, tuple[int, int]]] = []
                    for cell in block:
                        if protected is not None and cell == protected:
                            continue
                        degree = 0
                        rr, cc = cell
                        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nbr = (rr + dr, cc + dc)
                            if nbr in self.blocked_cells:
                                continue
                            if 0 <= nbr[0] < self.grid_cells and 0 <= nbr[1] < self.grid_cells:
                                degree += 1
                        ranked.append((degree, cell))
                    if not ranked:
                        continue

                    ranked.sort(key=lambda item: item[0], reverse=True)
                    top_degree = ranked[0][0]
                    top_cells = [cell for deg, cell in ranked if deg == top_degree]
                    rng.shuffle(top_cells)

                    placed = False
                    for candidate in top_cells:
                        trial = set(self.blocked_cells)
                        trial.add(candidate)
                        if not self._open_region_connected(trial):
                            continue
                        self.blocked_cells = trial
                        filled += 1
                        changed = True
                        placed = True
                        break

                    if placed and filled >= max_fills:
                        return
            if not changed:
                break

    def _target_distance_band(self, max_distance: int) -> tuple[int, int]:
        if max_distance <= 0:
            return (0, 0)

        min_ratio = max(0.0, min(1.0, self.target_distance_min_ratio))
        max_ratio = max(min_ratio, min(1.0, self.target_distance_max_ratio))
        min_distance = max(1, int(round(max_distance * min_ratio)))
        max_distance_allowed = max(min_distance, int(round(max_distance * max_ratio)))
        max_distance_allowed = min(max_distance, max_distance_allowed)
        return (min_distance, max_distance_allowed)

    def _distance_map_from_cell(self, start: tuple[int, int]) -> dict[tuple[int, int], int]:
        if self._is_blocked_cell(start):
            return {}
        distances: dict[tuple[int, int], int] = {start: 0}
        queue: deque[tuple[int, int]] = deque([start])
        while queue:
            cell = queue.popleft()
            base = distances[cell]
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                nxt = self._neighbor_for_move(cell, move)
                if nxt == cell or self._is_blocked_cell(nxt) or nxt in distances:
                    continue
                distances[nxt] = base + 1
                queue.append(nxt)
        return distances

    def _deterministic_maze_target_cell(
        self,
        player_cell: tuple[int, int],
        reachable_from_player: list[tuple[int, int]],
    ) -> tuple[int, int] | None:
        if self._normalized_layout_mode() != "maze" or not reachable_from_player:
            return None

        map_id = int(self.current_maze_episode_id)
        if map_id < 0:
            return None

        difficulty = self._normalized_maze_difficulty()
        start_anchor = self._maze_start_anchor_cell(map_id, difficulty)
        open_cells = self._open_cells()
        if not open_cells:
            return None

        if self._is_blocked_cell(start_anchor):
            ranked_open = sorted(
                open_cells,
                key=lambda cell: (
                    abs(cell[0] - start_anchor[0]) + abs(cell[1] - start_anchor[1]),
                    cell[0],
                    cell[1],
                ),
            )
            if not ranked_open:
                return None
            start_anchor = ranked_open[0]

        anchor_distances = self._distance_map_from_cell(start_anchor)
        if not anchor_distances:
            return None

        reachable_set = set(reachable_from_player)
        eligible = [
            cell
            for cell in reachable_set
            if cell != player_cell and cell in anchor_distances
        ]
        if not eligible:
            eligible = [cell for cell in reachable_set if cell != player_cell]
            if not eligible:
                return None

        max_distance = max(anchor_distances.get(cell, 0) for cell in eligible)
        farthest = [cell for cell in eligible if anchor_distances.get(cell, 0) == max_distance]
        farthest.sort()
        if not farthest:
            return None

        diff_offset = {"easy": 10, "medium": 20, "hard": 30}.get(difficulty, 20)
        algo_offset = sum(ord(ch) for ch in self.current_maze_algorithm)
        seed = self.maze_seed_base + 300_000 + (map_id * 97) + diff_offset + algo_offset + int(self.grid_cells)
        rng = random.Random(seed)
        return farthest[rng.randrange(len(farthest))]

    def _maze_algorithm_for_difficulty(self, difficulty: str, rng: random.Random) -> str:
        # Calibrated by grid size and typical algorithm difficulty.
        # easy (8x8): branchier texture is usually easier to read.
        # medium (10x10): longer DFS corridors/dead-ends raise complexity.
        # hard (12x12): rotate the two hardest structural styles.
        if difficulty == "easy":
            return "prim_kruskal"
        if difficulty == "medium":
            return "dfs_backtracker"
        return "recursive_division" if rng.random() < 0.5 else "aldous_broder"

    def _maze_node_cells(self) -> list[tuple[int, int]]:
        nodes = [
            (row, col)
            for row in range(1, self.grid_cells, 2)
            for col in range(1, self.grid_cells, 2)
        ]
        if not nodes:
            nodes = [(0, 0)]
        return nodes

    def _maze_node_neighbors(
        self,
        node: tuple[int, int],
        node_set: set[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        row, col = node
        candidates = [
            (row - 2, col),
            (row + 2, col),
            (row, col - 2),
            (row, col + 2),
        ]
        return [nbr for nbr in candidates if nbr in node_set]

    def _maze_edges_dfs_backtracker(
        self,
        nodes: list[tuple[int, int]],
        rng: random.Random,
    ) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        node_set = set(nodes)
        start = rng.choice(nodes)
        stack = [start]
        visited = {start}
        edges: list[tuple[tuple[int, int], tuple[int, int]]] = []

        while stack:
            current = stack[-1]
            unvisited = [nbr for nbr in self._maze_node_neighbors(current, node_set) if nbr not in visited]
            if not unvisited:
                stack.pop()
                continue
            nxt = rng.choice(unvisited)
            visited.add(nxt)
            edges.append((current, nxt))
            stack.append(nxt)
        return edges

    def _maze_edges_prim_kruskal_variant(
        self,
        nodes: list[tuple[int, int]],
        rng: random.Random,
    ) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        # Prim-like frontier growth with Kruskal union checks for branchier mazes.
        node_set = set(nodes)
        parents: dict[tuple[int, int], tuple[int, int]] = {node: node for node in nodes}

        def find(node: tuple[int, int]) -> tuple[int, int]:
            while parents[node] != node:
                parents[node] = parents[parents[node]]
                node = parents[node]
            return node

        def union(a: tuple[int, int], b: tuple[int, int]) -> bool:
            ra = find(a)
            rb = find(b)
            if ra == rb:
                return False
            parents[rb] = ra
            return True

        start = rng.choice(nodes)
        visited = {start}
        frontier: list[tuple[tuple[int, int], tuple[int, int]]] = [
            (start, nbr) for nbr in self._maze_node_neighbors(start, node_set)
        ]
        edges: list[tuple[tuple[int, int], tuple[int, int]]] = []

        while frontier and len(visited) < len(nodes):
            idx = rng.randrange(len(frontier))
            a, b = frontier.pop(idx)
            if b in visited and find(a) == find(b):
                continue
            if union(a, b):
                edges.append((a, b))
            if b in visited:
                continue
            visited.add(b)
            for nbr in self._maze_node_neighbors(b, node_set):
                frontier.append((b, nbr))

        candidate_edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for node in nodes:
            row, col = node
            for nbr in [(row + 2, col), (row, col + 2)]:
                if nbr in node_set:
                    candidate_edges.append((node, nbr))
        rng.shuffle(candidate_edges)
        for a, b in candidate_edges:
            if union(a, b):
                edges.append((a, b))

        return edges

    def _maze_edges_aldous_broder(
        self,
        nodes: list[tuple[int, int]],
        rng: random.Random,
    ) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        node_set = set(nodes)
        current = rng.choice(nodes)
        visited = {current}
        edges: list[tuple[tuple[int, int], tuple[int, int]]] = []

        while len(visited) < len(nodes):
            neighbors = self._maze_node_neighbors(current, node_set)
            if not neighbors:
                break
            nxt = rng.choice(neighbors)
            if nxt not in visited:
                edges.append((current, nxt))
                visited.add(nxt)
            current = nxt
        return edges

    def _recursive_division_blockers(
        self,
        protected_cell: tuple[int, int] | None,
        rng: random.Random,
    ) -> set[tuple[int, int]]:
        blocked: set[tuple[int, int]] = set()

        def choose_orientation(width: int, height: int) -> str:
            if width < height:
                return "H"
            if height < width:
                return "V"
            return "H" if rng.random() < 0.5 else "V"

        def divide(left: int, top: int, right: int, bottom: int) -> None:
            width = right - left + 1
            height = bottom - top + 1
            if width < 3 or height < 3:
                return

            orientation = choose_orientation(width, height)
            if orientation == "H":
                wall_candidates = [r for r in range(top + 1, bottom) if r % 2 == 0]
                if not wall_candidates:
                    return
                wall_row = rng.choice(wall_candidates)
                passage_col = rng.randrange(left, right + 1)
                for col in range(left, right + 1):
                    cell = (wall_row, col)
                    if col == passage_col or cell == protected_cell:
                        continue
                    blocked.add(cell)
                divide(left, top, right, wall_row - 1)
                divide(left, wall_row + 1, right, bottom)
            else:
                wall_candidates = [c for c in range(left + 1, right) if c % 2 == 0]
                if not wall_candidates:
                    return
                wall_col = rng.choice(wall_candidates)
                passage_row = rng.randrange(top, bottom + 1)
                for row in range(top, bottom + 1):
                    cell = (row, wall_col)
                    if row == passage_row or cell == protected_cell:
                        continue
                    blocked.add(cell)
                divide(left, top, wall_col - 1, bottom)
                divide(wall_col + 1, top, right, bottom)

        divide(0, 0, self.grid_cells - 1, self.grid_cells - 1)
        if protected_cell is not None:
            blocked.discard(protected_cell)
        return blocked

    def _apply_grid_profile(self) -> None:
        mode = self._normalized_layout_mode()
        desired_grid = 8
        if mode == "maze":
            desired_grid, _ = self._maze_profile()

        if desired_grid == self.grid_cells:
            return

        old_cell = self.current_player_cell
        if hasattr(self, "player"):
            try:
                old_cell = self._player_cell()
            except Exception:  # noqa: BLE001
                old_cell = self.current_player_cell

        self.grid_cells = desired_grid
        self.cell_size = self.canvas_width // self.grid_cells
        self.player_speed = self.cell_size
        self.player_size = max(16, int(self.cell_size * 0.62))
        self.target_radius = max(7, int(self.cell_size * 0.30))
        self.player_x = (self.cell_size - self.player_size) // 2
        self.player_y = (self.cell_size - self.player_size) // 2

        self._draw_chessboard()

        if hasattr(self, "player"):
            snapped = self._sanitize_cell(old_cell)
            self._place_player_at_cell(snapped)
            self.current_player_cell = snapped
            self._update_start_end_markers()

    def _cell_from_center(self, center_x: float, center_y: float) -> tuple[int, int]:
        col = min(self.grid_cells - 1, max(0, int(center_x / self.cell_size)))
        row = min(self.grid_cells - 1, max(0, int(center_y / self.cell_size)))
        return row, col

    def _player_cell(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.game_canvas.coords(self.player)
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        return self._cell_from_center(center_x, center_y)

    def _update_score_label(self) -> None:
        self.score_var.set(
            f"Targets reached: {self.targets_reached} | Reward: {round(self.total_reward, 1)} "
            f"| Last maze attempts: {self.last_maze_solve_attempts}"
        )

    def _score_context(self) -> str:
        completed, remaining = self._goal_session_progress()
        step_remaining = max(0, self.episode_step_limit - self.episode_steps)
        return (
            f"targets_reached_total={self.targets_reached}\n"
            f"total_reward={round(self.total_reward, 2)}\n"
            f"episode_revisit_steps={self.episode_revisit_steps}\n"
            f"episode_backtracks={self.episode_backtracks}\n"
            f"episode_step_limit={self.episode_step_limit}\n"
            f"episode_steps_remaining={step_remaining}\n"
            f"maze_attempt_count_current={self.episode_maze_attempt_count}\n"
            f"maze_last_solve_attempts={self.last_maze_solve_attempts}\n"
            f"dead_end_entrances_tracked={len(self.episode_dead_end_entrances)}\n"
            f"goal_session_active={self.goal_session_active}\n"
            f"goal_session_target_hits={self.goal_session_target_hits}\n"
            f"goal_session_hits_completed={completed}\n"
            f"goal_session_hits_remaining={remaining}"
        )

    def _dead_end_difficulty_scale(self) -> float:
        difficulty = self._normalized_maze_difficulty()
        if difficulty == "easy":
            return max(0.1, self.easy_dead_end_scale)
        if difficulty == "hard":
            return max(0.1, self.hard_dead_end_scale)
        return max(0.1, self.medium_dead_end_scale)

    def _attempt_dead_end_scale(self) -> float:
        # Escalate dead-end suppression after repeated timeout resets in same maze.
        growth = max(0.0, self.attempt_dead_end_escalation)
        attempts_over_one = max(0, self.episode_maze_attempt_count - 1)
        return min(3.0, 1.0 + (attempts_over_one * growth))

    def _goal_session_progress(self) -> tuple[int, int]:
        if not self.goal_session_active:
            return (0, 0)
        completed = max(0, self.targets_reached - self.goal_session_start_hits)
        remaining = max(0, self.goal_session_target_hits - completed)
        return (completed, remaining)

    def _end_auto_goal_session(self) -> None:
        self.goal_session_active = False
        self.goal_session_start_hits = 0
        self.goal_session_target_hits = 0
        self.auto_goal_hits_remaining = 0

    def _reset_score(self) -> None:
        self.targets_reached = 0
        self.total_reward = 0.0
        self.episode_steps = 0
        self.episode_optimal_steps = 0
        self.episode_step_limit = 0
        self._clear_sticky_objective_path()
        self.episode_revisit_steps = 0
        self.episode_backtracks = 0
        self.episode_maze_attempt_count = 1
        self.last_maze_solve_attempts = 0
        self.episode_visited_cells = {}
        self._end_auto_goal_session()
        self._update_score_label()
        self._refresh_game_state()
        self.status_var.set("Score reset")

    def _extract_moves(self, agent_output: str) -> list[str]:
        json_moves = self._extract_moves_from_json_blocks(agent_output)
        if json_moves:
            return json_moves
        return self._extract_moves_from_text(agent_output)

    def _extract_moves_from_json_blocks(self, text: str) -> list[str]:
        blocks = re.findall(r"\{[\s\S]*?\}", text)
        for block in blocks:
            try:
                payload = json.loads(block)
                raw_moves = payload.get("moves", [])
                if isinstance(raw_moves, list):
                    moves = self._normalize_moves(raw_moves)
                    if moves:
                        return moves
            except Exception:  # noqa: BLE001
                continue

        try:
            payload = self._parse_json_payload(text)
            raw_moves = payload.get("moves", [])
            if isinstance(raw_moves, list):
                return self._normalize_moves(raw_moves)
        except Exception:  # noqa: BLE001
            pass
        return []

    def _extract_moves_from_text(self, text: str) -> list[str]:
        words = re.findall(r"\b(up|down|left|right)\b", text, flags=re.IGNORECASE)
        return self._normalize_moves(words)

    def _normalize_moves(self, moves: list) -> list[str]:
        normalized_moves: list[str] = []
        for move in moves:
            if isinstance(move, str):
                direction = move.strip().upper()
                if direction in {"UP", "DOWN", "LEFT", "RIGHT"}:
                    normalized_moves.append(direction)
        return normalized_moves[:60]

    def _is_game_navigation_request(self, prompt: str, plan: dict) -> bool:
        if plan.get("is_repeat_goal", False):
            return True

        text = (
            f"{prompt} {plan.get('intent_summary', '')} "
            f"{plan.get('agent_task', '')} {plan.get('normalized_goal', '')}"
        ).lower()
        hints = [
            "move",
            "capture",
            "goal",
            "square",
            "circle",
            "target",
            "grid",
            "path",
            "reach",
            "go to",
            "navigate",
            "ball",
            "maze",
            "exit",
            "up",
            "down",
            "left",
            "right",
        ]
        return any(token in text for token in hints)

    def _is_local_navigation_request(self, prompt: str) -> bool:
        text = (prompt or "").strip().lower()
        if not text:
            return False
        direct_patterns = [
            r"\bnext move\b",
            # Match "solve maze", "solve the maze", "solve 15 mazes", "solve individual mazes", etc.
            r"\bsolve\b.*\bmazes?\b",
            r"\b(?:complete|finish|do|run|play)\b.*\bmazes?\b",
            r"\bfind (the )?(exit|goal|target|ball)\b",
            r"\bnavigate to\b",
            r"\bgo to\b",
            r"\breach\b",
            r"\bcapture\b",
            r"\bmove\b",
            r"\bup\b|\bdown\b|\bleft\b|\bright\b",
        ]
        if any(re.search(pattern, text) for pattern in direct_patterns):
            return True
        synthetic_plan = {
            "intent_summary": text,
            "agent_task": text,
            "normalized_goal": text,
            "is_repeat_goal": False,
        }
        return self._is_game_navigation_request(text, synthetic_plan)

    def _extract_execution_count(self, plan: dict) -> int:
        try:
            raw_count = int(plan.get("execution_count", 1) or 1)
        except Exception:  # noqa: BLE001
            raw_count = 1

        if not plan.get("is_repeat_goal", False):
            return 1

        return min(max(1, raw_count), self.max_repeat_executions)

    def _extract_local_execution_count(self, prompt: str) -> int:
        text = (prompt or "").strip().lower()
        # Prevent step-budget numbers from being mistaken as repeat-goal counts.
        text = re.sub(
            r"\b(?:max(?:imum)?\s+)?(?:steps?|moves?|turns?|iterations?)\s*(?:limit)?\s*(?:=|:|to|of)?\s*\d+\b",
            " ",
            text,
        )
        text = re.sub(
            r"\b(?:step|move|turn|iteration)\s*limit\s*(?:=|:|to|of)?\s*\d+\b",
            " ",
            text,
        )

        count_units = r"times?|hits?|goals?|targets?|mazes?|runs?|episodes?"
        digit_match = re.search(rf"\b(?:x|repeat|repeats?)\s*(\d+)\b", text)
        if digit_match:
            return max(1, min(self.max_repeat_executions, int(digit_match.group(1))))

        # Handles forms like:
        # - "10 mazes"
        # - "10 individual mazes"
        # - "10 separate maze runs"
        trailing_digit_match = re.search(
            rf"\b(\d+)\s+(?:\w+\s+)?(?:\w+\s+)?(?:{count_units})\b",
            text,
        )
        if trailing_digit_match:
            return max(1, min(self.max_repeat_executions, int(trailing_digit_match.group(1))))

        leading_digit_match = re.search(
            rf"\b(?:{count_units})\s*(\d+)\b",
            text,
        )
        if leading_digit_match:
            return max(1, min(self.max_repeat_executions, int(leading_digit_match.group(1))))

        word_counts = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        for word, count in word_counts.items():
            if re.search(
                rf"\b{word}\s+(?:\w+\s+)?(?:\w+\s+)?(?:{count_units})\b",
                text,
            ):
                return count
        return 1

    def _build_local_navigation_plan(self, prompt: str) -> dict:
        execution_count = self._extract_local_execution_count(prompt)
        objective = "maze navigation" if self._normalized_layout_mode() == "maze" else "grid navigation"
        return {
            "delegate": True,
            "intent_summary": f"Local kernel navigation request: {objective}.",
            "agent_task": "Use the internal navigation kernel to move toward the current objective efficiently.",
            "direct_response": "",
            "success_criteria": (
                f"Reach the current objective {execution_count} time(s) using the local navigation kernel only."
            ),
            "confidence": 1.0,
            "normalized_goal": objective,
            "is_repeat_goal": execution_count > 1,
            "execution_count": execution_count,
        }

    def _execute_local_navigation_request(self, prompt: str, assistant_instructions: str) -> dict:
        plan = self._build_local_navigation_plan(prompt)
        self.last_normalized_goal = plan["normalized_goal"]
        self.root.after(0, lambda: self.status_var.set("Local kernel: executing navigation..."))
        step_session = self._run_stepwise_goal_session(
            prompt,
            plan,
            assistant_instructions,
            local_kernel_only=True,
        )
        game_state = self._get_game_state_snapshot()
        completed, remaining = self._goal_session_progress()
        target_cell_debug = (
            "(hidden in maze mode)" if self._normalized_layout_mode() == "maze" else str(self.current_target_cell)
        )
        agent_output = "Local navigation kernel active: no external API calls were used for planning or step evaluation."
        mode_label = "maze" if self._normalized_layout_mode() == "maze" else "grid"
        completion_label = "maze runs" if mode_label == "maze" else "target hits"
        if step_session["success"]:
            answer = (
                f"Executed locally using the {mode_label} kernel. "
                f"Completed {step_session['completed']}/{plan['execution_count']} {completion_label} in "
                f"{step_session['iterations']} step iterations without external API calls."
            )
        else:
            answer = (
                f"Executed locally using the {mode_label} kernel. "
                f"Completed {step_session['completed']}/{plan['execution_count']} {completion_label} in "
                f"{step_session['iterations']} step iterations; {step_session['remaining']} remain."
            )

        return {
            "plan": plan,
            "step_session": step_session,
            "game_state": game_state,
            "completed": completed,
            "remaining": remaining,
            "target_cell_debug": target_cell_debug,
            "agent_output": agent_output,
            "mode_label": mode_label,
            "answer": answer,
        }

    def _format_local_navigation_debug(self, result: dict, header: str = "[LOCAL KERNEL PLAN]") -> str:
        plan = result["plan"]
        step_session = result["step_session"]
        return (
            f"{header}\n"
            f"delegate: {plan['delegate']}\n"
            f"intent_summary: {plan['intent_summary']}\n"
            f"agent_task: {plan['agent_task']}\n"
            f"success_criteria: {plan['success_criteria']}\n"
            f"confidence: {plan['confidence']}\n"
            f"normalized_goal: {plan['normalized_goal']}\n"
            f"repeat_goal: {plan['is_repeat_goal']}\n"
            f"execution_count: {plan['execution_count']}\n"
            f"external_api_calls: 0\n"
            f"local_navigation_kernel: {self.local_navigation_kernel}\n"
            f"local_navigation_api_fallback: {self.local_navigation_api_fallback}\n"
            f"step_mode_success: {step_session['success']}\n"
            f"step_mode_iterations: {step_session['iterations']}\n"
            f"step_mode_completed_hits: {step_session['completed']}\n"
            f"step_mode_remaining_hits: {step_session['remaining']}\n"
            f"target_cell: {result['target_cell_debug']}\n"
            f"goal_session_active: {self.goal_session_active}\n"
            f"goal_session_target_hits: {self.goal_session_target_hits}\n"
            f"goal_session_hits_completed: {result['completed']}\n"
            f"goal_session_hits_remaining: {result['remaining']}\n"
            f"auto_goal_hits_remaining: {self.auto_goal_hits_remaining}\n"
            f"game_state:\n{result['game_state']}\n"
            "\n[STEP LOG]\n"
            f"{step_session['step_log'] or '(none)'}\n"
            "\n[AGENT OUTPUT]\n"
            f"{result['agent_output']}"
        )

    def _present_local_navigation_result(self, result: dict, header: str = "[LOCAL KERNEL PLAN]") -> None:
        debug_text = self._format_local_navigation_debug(result, header=header)
        self.root.after(0, self._set_debug_text, debug_text)
        self.root.after(0, self._set_response, str(result["answer"]))

    def _handle_local_navigation_request(self, prompt: str, assistant_instructions: str) -> None:
        result = self._execute_local_navigation_request(prompt, assistant_instructions)
        self._present_local_navigation_result(result)

    def _shortest_path_moves_to_target(self) -> list[str]:
        return self._shortest_path_moves_between_cells(self.current_player_cell, self.current_target_cell)

    def _neighbor_for_move(self, cell: tuple[int, int], move: str) -> tuple[int, int]:
        row, col = cell
        if move == "UP":
            row = max(0, row - 1)
        elif move == "DOWN":
            row = min(self.grid_cells - 1, row + 1)
        elif move == "LEFT":
            col = max(0, col - 1)
        elif move == "RIGHT":
            col = min(self.grid_cells - 1, col + 1)
        return (row, col)

    def _is_blocked_cell(self, cell: tuple[int, int]) -> bool:
        return cell in self.blocked_cells

    def _shortest_path_moves_between_cells(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
    ) -> list[str]:
        if start == target:
            return []
        if self._is_blocked_cell(start) or self._is_blocked_cell(target):
            return []

        queue: deque[tuple[tuple[int, int], list[str]]] = deque()
        queue.append((start, []))
        seen = {start}

        while queue:
            cell, path = queue.popleft()
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                nxt = self._neighbor_for_move(cell, move)
                if nxt == cell or nxt in seen or self._is_blocked_cell(nxt):
                    continue
                new_path = path + [move]
                if nxt == target:
                    return new_path
                seen.add(nxt)
                queue.append((nxt, new_path))
        return []

    def _clear_sticky_objective_path(self) -> None:
        self._sticky_objective_target = None
        self._sticky_objective_path = []

    def _prime_sticky_objective_path(self, path: list[str]) -> None:
        if not path or self.current_target_cell == self.current_player_cell:
            self._clear_sticky_objective_path()
            return
        if not self._moves_reach_current_target(path):
            self._clear_sticky_objective_path()
            return
        self._sticky_objective_target = self.current_target_cell
        self._sticky_objective_path = list(path)

    def _sticky_objective_move(self) -> str:
        if self._sticky_objective_target != self.current_target_cell:
            self._clear_sticky_objective_path()
            return ""
        if not self._sticky_objective_path:
            return ""
        if not self._moves_reach_current_target(self._sticky_objective_path):
            self._clear_sticky_objective_path()
            return ""
        move = self._sticky_objective_path[0]
        if not self._is_valid_traversal_move(move):
            self._clear_sticky_objective_path()
            return ""
        return move

    def _distance_between_cells(self, start: tuple[int, int], target: tuple[int, int]) -> int:
        if start == target:
            return 0
        path = self._shortest_path_moves_between_cells(start, target)
        if not path:
            return self.grid_cells * self.grid_cells
        return len(path)

    def _simulate_end_cell(self, moves: list[str]) -> tuple[int, int]:
        row, col = self.current_player_cell
        for move in moves:
            candidate = self._neighbor_for_move((row, col), move)
            if not self._is_blocked_cell(candidate):
                row, col = candidate
        return (row, col)

    def _moves_reach_current_target(self, moves: list[str]) -> bool:
        if not moves:
            return False
        return self._simulate_end_cell(moves) == self.current_target_cell

    def _distance_from_target_for_cell(self, cell: tuple[int, int]) -> int:
        return self._distance_between_cells(cell, self.current_target_cell)

    def _distance_after_single_move(self, move: str) -> int:
        candidate = self._neighbor_for_move(self.current_player_cell, move)
        if self._is_blocked_cell(candidate):
            candidate = self.current_player_cell
        return self._distance_from_target_for_cell(candidate)

    def _maze_episode_fully_mapped(self) -> bool:
        """Return True when exploration no longer has value in the current maze."""
        summary = self._episodic_memory_summary()
        known_open_raw = summary.get("known_open", 0)
        unknown_raw = summary.get("unknown", 1)
        frontier_raw = summary.get("frontier", 1)
        known_open_cells = int(0 if known_open_raw is None else known_open_raw)
        unknown_cells = int(1 if unknown_raw is None else unknown_raw)
        frontier_cells = int(1 if frontier_raw is None else frontier_raw)
        # Require full convergence, not just a transient frontier=0 snapshot.
        return known_open_cells > 0 and unknown_cells <= 0 and frontier_cells <= 0

    def _frontier_cells_current_episode(self) -> list[tuple[int, int]]:
        frontier_cells: list[tuple[int, int]] = []
        for cell, token in self.maze_known_cells.items():
            if token not in {".", "P", "E"}:
                continue
            if self._unknown_neighbor_count(cell) > 0:
                frontier_cells.append(cell)
        return frontier_cells

    def _active_same_maze_retry_count(self) -> int:
        attempt_retries = max(0, int(self.episode_maze_attempt_count) - 1)
        return max(int(self.step_limit_reset_count), int(self.same_maze_retry_count), attempt_retries)

    def _recent_move_direction_entropy(self, window: int | None = None) -> float:
        sample_window = max(4, int(window or self.loop_entropy_window))
        recent_transitions = list(self.maze_recent_transitions)[-sample_window:]
        if len(recent_transitions) < 4:
            return 2.0

        direction_counts = {"UP": 0, "DOWN": 0, "LEFT": 0, "RIGHT": 0}
        total = 0
        for frm, to in recent_transitions:
            delta = (to[0] - frm[0], to[1] - frm[1])
            move = ""
            if delta == (-1, 0):
                move = "UP"
            elif delta == (1, 0):
                move = "DOWN"
            elif delta == (0, -1):
                move = "LEFT"
            elif delta == (0, 1):
                move = "RIGHT"
            if not move:
                continue
            direction_counts[move] += 1
            total += 1

        if total < 4:
            return 2.0

        entropy = 0.0
        for count in direction_counts.values():
            if count <= 0:
                continue
            probability = count / total
            entropy -= probability * math.log2(probability)
        return round(entropy, 3)

    def _frontier_lock_active(self, unknown_cells: int | None = None, frontier_cells: int | None = None) -> bool:
        if unknown_cells is None or frontier_cells is None:
            summary = self._episodic_memory_summary()
            unknown_cells = int(summary.get("unknown", 0) or 0)
            frontier_cells = int(summary.get("frontier", 0) or 0)

        unresolved_frontier = (unknown_cells > 0) or (frontier_cells > 0)
        if not unresolved_frontier:
            return False

        frontier_target = self._select_persistent_frontier_target()
        if frontier_target is None:
            return False

        late_frontier = (
            unknown_cells <= self.frontier_lock_unknown_threshold
            or frontier_cells <= self.frontier_lock_frontier_threshold
        )
        retry_lock = self._active_same_maze_retry_count() > 0
        entropy_collapse = (
            len(self.maze_recent_transitions) >= max(4, self.loop_entropy_window - 1)
            and self._recent_move_direction_entropy() <= self.loop_entropy_threshold
        )
        return bool(late_frontier or retry_lock or entropy_collapse)

    def _frontier_lock_step(self) -> str:
        if not self._frontier_lock_active():
            return ""

        frontier_target = self._select_persistent_frontier_target()
        if frontier_target is None:
            return ""

        path = self._path_to_frontier_target(frontier_target)
        if not path:
            return ""

        return path[0]

    def _retry_continuity_active(self) -> bool:
        if self._active_same_maze_retry_count() <= 0:
            return False
        if self._maze_episode_fully_mapped():
            return False
        return self._select_persistent_frontier_target() is not None

    def _is_post_reset_exhausted_region_cell(self, cell: tuple[int, int]) -> bool:
        if self._active_same_maze_retry_count() <= 0:
            return False
        if cell not in self._post_reset_exhausted_cells:
            return False
        if self._unknown_neighbor_count(cell) > 0:
            return False
        return self._cell_visit_reset_epoch.get(cell, -1) < self.reset_epoch

    def _shortest_path_moves_between_cells_with_avoidance(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        *,
        avoid_cells: set[tuple[int, int]] | None = None,
        avoid_transitions: set[tuple[tuple[int, int], tuple[int, int]]] | None = None,
    ) -> list[str]:
        if start == target:
            return []
        if self._is_blocked_cell(start) or self._is_blocked_cell(target):
            return []

        blocked_cells = set(avoid_cells or set())
        blocked_cells.discard(start)
        blocked_cells.discard(target)
        blocked_transitions = set(avoid_transitions or set())

        queue: deque[tuple[tuple[int, int], list[str]]] = deque([(start, [])])
        seen = {start}

        while queue:
            cell, path = queue.popleft()
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                nxt = self._neighbor_for_move(cell, move)
                if nxt == cell or nxt in seen or self._is_blocked_cell(nxt):
                    continue
                if nxt in blocked_cells:
                    continue
                if (cell, nxt) in blocked_transitions and nxt != target:
                    continue
                new_path = path + [move]
                if nxt == target:
                    return new_path
                seen.add(nxt)
                queue.append((nxt, new_path))
        return []

    def _path_exhaustion_counts(
        self,
        start: tuple[int, int],
        moves: list[str],
    ) -> tuple[int, int]:
        exhausted_cells = 0
        exhausted_transitions = 0
        current = start
        for move in moves:
            nxt = self._neighbor_for_move(current, move)
            if self._is_post_reset_exhausted_region_cell(nxt):
                exhausted_cells += 1
            if (current, nxt) in self._post_reset_exhausted_transitions:
                exhausted_transitions += 1
            current = nxt
        return exhausted_cells, exhausted_transitions

    def _path_to_frontier_target(self, target: tuple[int, int]) -> list[str]:
        avoid_cells = {
            cell
            for cell in self._post_reset_exhausted_cells
            if self._is_post_reset_exhausted_region_cell(cell)
        }
        avoid_transitions = set(self._post_reset_exhausted_transitions)
        constrained_path = self._shortest_path_moves_between_cells_with_avoidance(
            self.current_player_cell,
            target,
            avoid_cells=avoid_cells,
            avoid_transitions=avoid_transitions,
        )
        if constrained_path or (self.current_player_cell == target):
            return constrained_path
        return self._shortest_path_moves_between_cells(self.current_player_cell, target)

    def _select_persistent_frontier_target(self, force_refresh: bool = False) -> tuple[int, int] | None:
        frontier_cells = self._frontier_cells_current_episode()
        if not frontier_cells:
            self._persistent_frontier_target = None
            self._same_maze_retry_frontier_target = None
            return None

        current_target = self._same_maze_retry_frontier_target or self._persistent_frontier_target
        if (not force_refresh) and current_target in frontier_cells:
            if current_target == self.current_player_cell:
                self._persistent_frontier_target = current_target
                return current_target
            current_path = self._path_to_frontier_target(current_target)
            if current_path:
                self._persistent_frontier_target = current_target
                if self._active_same_maze_retry_count() > 0:
                    self._same_maze_retry_frontier_target = current_target
                return current_target

        best_target: tuple[int, int] | None = None
        best_key: tuple[int, int, int, int, int] | None = None
        for frontier_cell in frontier_cells:
            path = self._path_to_frontier_target(frontier_cell)
            if frontier_cell != self.current_player_cell and not path:
                continue
            exhausted_cells, exhausted_transitions = self._path_exhaustion_counts(
                self.current_player_cell,
                path,
            )
            continuity_bonus = 2 if frontier_cell == current_target else 0
            selection_key = (
                exhausted_cells,
                exhausted_transitions,
                max(0, len(path) - continuity_bonus),
                self.episode_visited_cells.get(frontier_cell, 0),
                -self._unknown_neighbor_count(frontier_cell),
            )
            if best_key is None or selection_key < best_key:
                best_key = selection_key
                best_target = frontier_cell

        self._persistent_frontier_target = best_target
        if self._active_same_maze_retry_count() > 0:
            self._same_maze_retry_frontier_target = best_target
        return best_target

    def _persistent_frontier_step(self) -> str:
        frontier_target = self._select_persistent_frontier_target()
        if frontier_target is None:
            return ""
        if frontier_target == self.current_player_cell:
            if self._unknown_neighbor_count(self.current_player_cell) > 0:
                return ""
            frontier_target = self._select_persistent_frontier_target(force_refresh=True)
            if frontier_target is None or frontier_target == self.current_player_cell:
                return ""

        path = self._path_to_frontier_target(frontier_target)
        if not path:
            self._persistent_frontier_target = None
            return ""
        return path[0]

    def _reset_organism_control_state(self) -> None:
        self.organism_memory_state = OrganismMemoryState()
        self.organism_endocrine_state = OrganismEndocrineState()
        self.organism_control_state = OrganismControlState()
        self.organism_last_step_debug = ""
        self.maze_agent = self._build_maze_agent()

    def _build_maze_agent(self) -> MazeAgent:
        return MazeAgent(
            grid_size=self.grid_cells,
            cycle_taboo_duration=self.maze_agent_cycle_taboo_duration,
            corridor_step_escape_threshold=self.maze_agent_corridor_escape_threshold,
            escape_timeout=self.maze_agent_escape_timeout,
            escape_exit_pressure=self.maze_agent_escape_exit_pressure,
            corridor_overuse_threshold=self.maze_agent_corridor_overuse_threshold,
            novelty_weight=self.maze_agent_novelty_weight,
            frontier_weight=self.maze_agent_frontier_weight,
            junction_bonus=self.maze_agent_junction_bonus,
            corridor_overuse_penalty=self.maze_agent_corridor_overuse_penalty,
            dead_end_penalty=self.maze_agent_dead_end_penalty,
            motif_weight=self.maze_agent_motif_weight,
            loop_risk_weight=self.maze_agent_loop_risk_weight,
            corridor_forward_bias=self.maze_agent_corridor_forward_bias,
            side_open_bias=self.maze_agent_side_open_bias,
        )

    def _organism_signature_from_current(self) -> OrganismSignature | None:
        signature_text = self._current_pattern_signature(self.current_player_cell)
        if not signature_text:
            return None
        try:
            payload = json.loads(signature_text)
        except Exception:  # noqa: BLE001
            return None
        try:
            return OrganismSignature(
                boundary_bucket=int(payload.get("boundary_bucket", 0) or 0),
                branch_profile=str(payload.get("branch_profile", "") or ""),
                dead_end_risk=int(payload.get("dead_end_risk", 0) or 0),
                dead_end_risk_depth=int(payload.get("dead_end_risk_depth", 0) or 0),
                frontier_distance=int(payload.get("frontier_distance", 0) or 0),
                known_degree=int(payload.get("known_degree", 0) or 0),
                unknown_neighbors=int(payload.get("unknown_neighbors", 0) or 0),
                visit_bucket=int(payload.get("visit_bucket", 0) or 0),
                recent_backtrack=int(payload.get("recent_backtrack", 0) or 0),
                transition_pressure_bucket=int(payload.get("transition_pressure_bucket", 0) or 0),
                facing=str(payload.get("facing", "UP") or "UP"),
                difficulty=str(payload.get("difficulty", self._normalized_maze_difficulty()) or "medium"),
            )
        except Exception:  # noqa: BLE001
            return None

    def _organism_event_from_current(self, signature: OrganismSignature) -> OrganismEvent:
        tags: set[str] = set()
        reward = 0.0
        penalty = 0.0

        if signature.unknown_neighbors > 0:
            tags.add("novelty_reward")
            reward += min(0.35, 0.08 * signature.unknown_neighbors)
        if signature.frontier_distance <= 1:
            tags.add("frontier_visible")
            reward += 0.12
        if signature.recent_backtrack > 0:
            tags.add("cycle_pair")
            penalty += 0.18
        if signature.transition_pressure_bucket >= 2:
            tags.add("transition_repeat")
            penalty += 0.14 * signature.transition_pressure_bucket
        if signature.dead_end_risk >= 2:
            tags.add("visible_terminal")
            penalty += 0.10 * signature.dead_end_risk
        if signature.dead_end_risk_depth >= 2 and signature.unknown_neighbors == 0:
            tags.add("boxed_corridor")
            penalty += 0.12

        last_action = self.organism_control_state.last_action or "UP"
        return OrganismEvent(
            step=int(self.memory_step_index),
            action=last_action,
            reward=round(max(0.0, reward), 4),
            penalty=round(max(0.0, penalty), 4),
            tags=tags,
        )

    def _organism_candidate_projections(
        self,
        candidates: list[tuple[str, tuple[int, int]]],
    ) -> list[CandidateProjection]:
        projections: list[CandidateProjection] = []
        origin_frontier = min(6, self._frontier_distance(self.current_player_cell, max_depth=6))
        for move, next_cell in candidates:
            breakdown = self._exploration_move_breakdown(move)
            if bool(breakdown.get("blocked", False)):
                continue

            raw_loop_pressure = (
                float(breakdown.get("transition_repeat_penalty", 0) or 0)
                + float(breakdown.get("cycle_pair_penalty", 0) or 0)
                + float(breakdown.get("loop_commitment_penalty", 0) or 0)
                + float(breakdown.get("immediate_backtrack_hard_penalty", 0) or 0)
                + float(breakdown.get("terminal_hard_veto_penalty", 0) or 0)
                + float(breakdown.get("dead_end_end_slap_penalty", 0) or 0)
                + float(breakdown.get("dead_end_tip_revisit_slap_penalty", 0) or 0)
            )
            estimated_loop_risk = max(0.0, min(1.0, raw_loop_pressure / 260.0))

            unknown_neighbors = int(breakdown.get("unknown_neighbors", 0) or 0)
            known = int(breakdown.get("known", 0) or 0)
            visits = int(breakdown.get("visits", 0) or 0)
            edge_frontier = 1 if bool(breakdown.get("edge_frontier", False)) else 0
            edge_junction = 1 if bool(breakdown.get("edge_junction", False)) else 0
            estimated_novelty = (
                (0.20 * unknown_neighbors)
                + (0.16 * edge_frontier)
                + (0.10 * edge_junction)
                + (0.12 * (0 if known else 1))
            )
            estimated_novelty = max(0.0, min(1.0, estimated_novelty))

            frontier_distance = int(breakdown.get("frontier_distance", origin_frontier) or origin_frontier)
            dead_end_risk_depth = int(breakdown.get("dead_end_risk_depth", 0) or 0)
            cycle_pair_recent = float(breakdown.get("cycle_pair_penalty", 0) or 0) > 0
            visible_terminal = (
                int(breakdown.get("visible_terminal_end_penalty", 0) or 0) > 0
                or int(breakdown.get("terminal_hard_veto_penalty", 0) or 0) > 0
            )
            boxed_corridor = (
                int(breakdown.get("boxed_corridor_no_exit", 0) or 0) > 0
                or int(breakdown.get("boxed_corridor_penalty", 0) or 0) > 0
            )
            catastrophic_trap = bool(cycle_pair_recent and visible_terminal and boxed_corridor)
            frontier_delta = origin_frontier - frontier_distance
            estimated_frontier_gain = max(0.0, min(1.0, (frontier_delta + 2.0) / 4.0))

            projections.append(
                CandidateProjection(
                    action=move,
                    next_pos=next_cell,
                    estimated_loop_risk=round(estimated_loop_risk, 4),
                    estimated_novelty=round(estimated_novelty, 4),
                    estimated_unknown_neighbors=unknown_neighbors,
                    estimated_frontier_gain=round(estimated_frontier_gain, 4),
                    visit_count=visits,
                    frontier_distance=frontier_distance,
                    dead_end_risk_depth=dead_end_risk_depth,
                    cycle_pair_recent=cycle_pair_recent,
                    visible_terminal=visible_terminal,
                    boxed_corridor=boxed_corridor,
                    catastrophic_trap=catastrophic_trap,
                )
            )
        return projections

    def _maze_agent_exploration_move(
        self,
        candidates: list[tuple[str, tuple[int, int]]],
        terminal_filtered: bool,
    ) -> str:
        """
        New-architecture exploration hook using the maze/ package.

        Falls back gracefully to an empty string (causing _best_exploration_move
        to continue to the organism_control or score-based fallback).
        """
        if not candidates:
            return ""

        candidate_inputs: list[CandidateInput] = []
        for move, next_cell in candidates:
            bd = self._exploration_move_breakdown(move)
            if bool(bd.get("blocked", False)):
                continue
            raw_loop_pressure = (
                float(bd.get("transition_repeat_penalty", 0) or 0)
                + float(bd.get("cycle_pair_penalty", 0) or 0)
                + float(bd.get("loop_commitment_penalty", 0) or 0)
                + float(bd.get("immediate_backtrack_hard_penalty", 0) or 0)
                + float(bd.get("terminal_hard_veto_penalty", 0) or 0)
                + float(bd.get("dead_end_end_slap_penalty", 0) or 0)
                + float(bd.get("dead_end_tip_revisit_slap_penalty", 0) or 0)
            )
            estimated_loop_risk = max(0.0, min(1.0, raw_loop_pressure / 260.0))
            unknown_neighbors = int(bd.get("unknown_neighbors", 0) or 0)
            edge_frontier = 1 if bool(bd.get("edge_frontier", False)) else 0
            edge_junction = 1 if bool(bd.get("edge_junction", False)) else 0
            known = int(bd.get("known", 0) or 0)
            estimated_novelty = max(0.0, min(1.0,
                (0.20 * unknown_neighbors)
                + (0.16 * edge_frontier)
                + (0.10 * edge_junction)
                + (0.12 * (0 if known else 1))
            ))
            origin_frontier = self._frontier_distance(self.current_player_cell, max_depth=6)
            frontier_distance = int(bd.get("frontier_distance", origin_frontier) or origin_frontier)
            frontier_delta = origin_frontier - frontier_distance
            estimated_frontier_gain = max(0.0, min(1.0, (frontier_delta + 2.0) / 4.0))
            candidate_inputs.append(
                CandidateInput(
                    action=move,
                    next_pos=next_cell,
                    visit_count=int(bd.get("visits", 0) or 0),
                    estimated_loop_risk=round(estimated_loop_risk, 4),
                    estimated_novelty=round(estimated_novelty, 4),
                    estimated_frontier_gain=round(estimated_frontier_gain, 4),
                    dead_end_risk_depth=int(bd.get("dead_end_risk_depth", 0) or 0),
                )
            )

        if not candidate_inputs:
            return ""

        # Keep local-map authority: expose goal coordinates only when the exit
        # is currently visible (not just historically seen), or once episodic
        # mapping has fully converged.
        target_row, target_col = self.current_target_cell
        target_visible_now = (
            self.maze_known_cells.get(self.current_target_cell, "") == "E"
            and self._is_local_cell_visible(
                self.current_player_cell[0],
                self.current_player_cell[1],
                target_row,
                target_col,
                facing=self.player_facing,
            )
        )
        goal_known_current_maze = target_visible_now or self._maze_episode_fully_mapped()
        goal_pos_for_agent = self.current_target_cell if goal_known_current_maze else None

        try:
            out: MazeStepOutput = self.maze_agent.step(
                player_pos=self.current_player_cell,
                facing=self.player_facing,
                step=self.memory_step_index,
                known_cells=set(self.maze_known_cells.keys()),
                wall_cells=self.blocked_cells,
                visit_counts=self.episode_visited_cells,
                candidates=candidate_inputs,
                goal_pos=goal_pos_for_agent,
            )
        except Exception:  # noqa: BLE001
            return ""

        chosen_move = out.action
        valid_moves = {move for move, _ in candidates}
        if chosen_move not in valid_moves:
            return ""

        guard_notes: list[str] = []
        if str(getattr(out.mode, "name", "")) == "GOAL_DIRECTED":
            guarded_move, guarded_note = self._objective_move_with_risk_guard(chosen_move)
            if guarded_note:
                guard_notes.append(guarded_note)
            if guarded_move and guarded_move in valid_moves:
                chosen_move = guarded_move

            cycle_vetoed_moves = {
                v.action
                for v in out.veto_log
                if v.vetoed and str(getattr(v.reason, "name", "")) == "CYCLE_DETECTED"
            }
            escape_move, escape_note = self._goal_directed_cycle_escape_move(
                chosen_move,
                valid_moves,
                cycle_vetoed_moves,
            )
            if escape_note:
                guard_notes.append(escape_note)
            if escape_move and escape_move in valid_moves:
                chosen_move = escape_move

        veto_summary = ",".join(
            f"{v.action}:{v.reason.name if v.reason else 'ok'}"
            for v in out.veto_log
            if v.vetoed
        )
        guard_suffix = f" {' '.join(guard_notes)}" if guard_notes else ""
        self._last_planner_choice_debug = (
            f"source=maze_agent mode={out.mode.name} action={chosen_move} "
            f"rationale={out.rationale} "
            f"goal_known={1 if goal_known_current_maze else 0} "
            f"vetoed=[{veto_summary}] "
            f"terminal_filtered={terminal_filtered}{guard_suffix}"
        )
        return chosen_move

    def _organism_live_exploration_move(
        self,
        candidates: list[tuple[str, tuple[int, int]]],
        terminal_filtered: bool,
    ) -> str:
        signature = self._organism_signature_from_current()
        if signature is None:
            return ""

        visible_ascii = [
            line.split()
            for line in self._build_local_status_snapshot(
                self.current_player_cell[0],
                self.current_player_cell[1],
                radius=1,
                include_render_details=False,
            ).splitlines()
            if " " in line
        ]
        grid_state = OrganismGridState(
            player_pos=self.current_player_cell,
            facing=self.player_facing,
            visible_ascii=visible_ascii,
            step_index=self.memory_step_index,
        )
        event = self._organism_event_from_current(signature)
        projections = self._organism_candidate_projections(candidates)
        if not projections:
            return ""

        non_catastrophic = [p for p in projections if not organism_is_catastrophic_trap(p)]
        veto_count = len(projections) - len(non_catastrophic)
        if non_catastrophic:
            projections = non_catastrophic
        else:
            # If all candidates are catastrophic, choose escape by least-visited, then lowest loop risk.
            fallback = min(
                projections,
                key=lambda p: (p.visit_count, p.estimated_loop_risk, -p.estimated_novelty),
            )
            self.organism_last_step_debug = (
                f"policy=ESCAPE_LOOP_FALLBACK action={fallback.action} "
                f"all_catastrophic=1 veto_count={veto_count} "
                f"terminal_filtered={terminal_filtered}"
            )
            self._last_planner_choice_debug = f"source=organism_control {self.organism_last_step_debug}"
            return fallback.action

        try:
            step_result = organism_step_agent(
                grid=grid_state,
                signature=signature,
                event=event,
                candidate_moves=projections,
                memory=self.organism_memory_state,
                endocrine=self.organism_endocrine_state,
                control=self.organism_control_state,
            )
        except Exception:  # noqa: BLE001
            return ""

        self.organism_memory_state = step_result.memory
        self.organism_endocrine_state = step_result.endocrine
        self.organism_control_state = step_result.control

        chosen_move = step_result.action
        valid_moves = {move for move, _ in candidates}
        if chosen_move not in valid_moves:
            return ""

        self.organism_last_step_debug = (
            f"policy={step_result.policy} action={chosen_move} "
            f"loop_risk={round(step_result.loop_risk, 3)} "
            f"frontier_strength={round(step_result.frontier_strength, 3)} "
            f"veto_count={veto_count} "
            f"terminal_filtered={terminal_filtered} "
            f"loop_suspected={self.organism_control_state.loop_suspected}"
        )
        self._last_planner_choice_debug = f"source=organism_control {self.organism_last_step_debug}"
        return chosen_move

    def _best_progress_move(self) -> str:
        current_distance = self._distance_from_target_for_cell(self.current_player_cell)
        best_move = ""
        best_distance = current_distance
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            candidate = self._neighbor_for_move(self.current_player_cell, move)
            if self._is_blocked_cell(candidate):
                continue
            d = self._distance_after_single_move(move)
            if best_move == "" or d < best_distance:
                best_move = move
                best_distance = d
        return best_move

    def _best_exploration_move(self) -> str:
        current = self.current_player_cell
        candidates: list[tuple[str, tuple[int, int]]] = []
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            nxt = self._neighbor_for_move(current, move)
            if nxt == current or self._is_blocked_cell(nxt):
                continue
            candidates.append((move, nxt))

        if not candidates:
            return ""

        force_score_fallback = self._maze_reexplore_cooldown_remaining > 0
        persistent_frontier_move = self._persistent_frontier_step()
        persistent_frontier_target = self._persistent_frontier_target
        continuity_override_active = self._retry_continuity_active()
        frontier_lock_active = self._frontier_lock_active()
        frontier_lock_move = self._frontier_lock_step() if frontier_lock_active else ""

        if frontier_lock_active and frontier_lock_move and persistent_frontier_target is not None:
            target_distance = self._distance_between_cells(self.current_player_cell, persistent_frontier_target)
            exhausted_cells, exhausted_transitions = self._path_exhaustion_counts(
                self.current_player_cell,
                self._path_to_frontier_target(persistent_frontier_target),
            )
            next_cell = self._neighbor_for_move(self.current_player_cell, frontier_lock_move)
            current_frontier_distance = self._frontier_distance(self.current_player_cell, max_depth=12)
            next_frontier_distance = self._frontier_distance(next_cell, max_depth=12)
            self._last_planner_choice_debug = (
                f"source=frontier_lock selected={frontier_lock_move} target={persistent_frontier_target} "
                f"target_distance={target_distance} frontier_distance={current_frontier_distance}->{next_frontier_distance} "
                f"exhausted_cells={exhausted_cells} exhausted_transitions={exhausted_transitions} "
                f"retries={self._active_same_maze_retry_count()} entropy={self._recent_move_direction_entropy()} "
                f"force_score_fallback={1 if force_score_fallback else 0}"
            )
            return frontier_lock_move

        if (continuity_override_active or (not force_score_fallback)) and persistent_frontier_move and persistent_frontier_target is not None:
            target_distance = self._distance_between_cells(self.current_player_cell, persistent_frontier_target)
            exhausted_cells, exhausted_transitions = self._path_exhaustion_counts(
                self.current_player_cell,
                self._path_to_frontier_target(persistent_frontier_target),
            )
            self._last_planner_choice_debug = (
                f"source=persistent_frontier selected={persistent_frontier_move} target={persistent_frontier_target} "
                f"target_distance={target_distance} exhausted_cells={exhausted_cells} "
                f"exhausted_transitions={exhausted_transitions} retries={self._active_same_maze_retry_count()} "
                f"force_score_fallback={1 if force_score_fallback else 0}"
            )
            return persistent_frontier_move

        terminal_filtered = False
        if self.terminal_end_hard_avoid:
            non_terminal_candidates = [
                (move, nxt)
                for move, nxt in candidates
                if (
                    (not self._is_move_visibly_terminal_dead_end(current, move))
                    and (not self._is_move_visibly_boxed_corridor_without_exit(current, move))
                )
            ]
            if non_terminal_candidates and len(non_terminal_candidates) < len(candidates):
                candidates = non_terminal_candidates
                terminal_filtered = True

        if self.maze_agent_enable and (not force_score_fallback):
            maze_move = self._maze_agent_exploration_move(candidates, terminal_filtered)
            if maze_move:
                return maze_move

        if self.organism_control_enable and (not force_score_fallback):
            organism_move = self._organism_live_exploration_move(candidates, terminal_filtered)
            if organism_move:
                return organism_move

        tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
        scored: list[tuple[str, int]] = []
        for move, _cell in candidates:
            scored.append((move, self._exploration_move_score(move)))
        scored.sort(key=lambda item: (item[1], tie_order.get(item[0], 9)))
        best_score = scored[0][1]

        frontier_move = self._frontier_first_step()
        if (not force_score_fallback) and frontier_move and any(move == frontier_move for move, _score in scored):
            frontier_breakdown = self._exploration_move_breakdown(frontier_move)
            frontier_score = int(frontier_breakdown["score"])
            margin = max(0, self.frontier_override_score_margin)
            if frontier_score <= best_score + margin:
                self._last_planner_choice_debug = (
                    f"source=frontier_first selected={frontier_move} frontier_score={frontier_score} "
                    f"best_local_score={best_score} margin={margin} "
                    f"terminal_filtered={terminal_filtered} "
                    f"randomize_ties={self.exploration_randomize_ties} tie_band={self.exploration_tie_band}"
                )
                return frontier_move
            self._last_planner_choice_debug = (
                f"source=frontier_first_rejected selected={frontier_move} frontier_score={frontier_score} "
                f"best_local_score={best_score} margin={margin} -> fallback=score"
            )

        tie_band = max(0, self.exploration_tie_band)
        near_best = [item for item in scored if item[1] <= best_score + tie_band]
        near_best_moves = [move for move, _score in near_best]
        near_best_breakdowns = {move: self._exploration_move_breakdown(move) for move in near_best_moves}

        selected_move = scored[0][0]
        picked_random_tie = False
        stuck_softmax_used = False
        if force_score_fallback and len(scored) > 1:
            # Under stuck re-explore fallback, sample from a wider near-best set
            # instead of deterministic argmin to break local attractor cycles.
            stuck_band = tie_band + 6 + min(10, self._maze_stuck_trigger_count)
            stuck_pool = [item for item in scored if item[1] <= best_score + stuck_band]
            if len(stuck_pool) > 1:
                temp = max(1.5, 4.0 - min(2.0, 0.25 * self._maze_stuck_trigger_count))
                weights: list[float] = []
                for _move, _score in stuck_pool:
                    delta = float(_score - best_score)
                    weights.append(math.exp(-delta / temp))
                sampled = self._planner_rng.choices(stuck_pool, weights=weights, k=1)[0]
                selected_move = sampled[0]
                picked_random_tie = True
                stuck_softmax_used = True

        if self.exploration_randomize_ties and len(near_best) > 1:
            candidate_pool = near_best_moves
            if self.tie_random_requires_novel:
                novelty_pool = [
                    move
                    for move in near_best_moves
                    if (
                        int(near_best_breakdowns[move].get("unknown_neighbors", 0)) > 0
                        or int(near_best_breakdowns[move].get("visits", 0)) == 0
                    )
                ]
                if novelty_pool:
                    candidate_pool = novelty_pool

            low_info_pool = [
                move
                for move in candidate_pool
                if (
                    int(near_best_breakdowns[move].get("unknown_neighbors", 0)) == 0
                    and int(near_best_breakdowns[move].get("visits", 0)) > 0
                    and int(near_best_breakdowns[move].get("recent_transition_count", 0)) > 0
                )
            ]
            if low_info_pool and len(low_info_pool) == len(candidate_pool):
                picked_random_tie = False
            else:
                selected_move = self._planner_rng.choice(candidate_pool)
                picked_random_tie = True
        elif len(near_best) > 1 and self.exploration_tie_noise > 0:
            # Add tiny jitter in score-near-equivalent sets to avoid deterministic replay.
            noisy_pool: list[tuple[str, float]] = []
            for move, score in near_best:
                jitter = self._planner_rng.uniform(-self.exploration_tie_noise, self.exploration_tie_noise)
                noisy_pool.append((move, float(score) + jitter))
            noisy_pool.sort(key=lambda item: (item[1], tie_order.get(item[0], 9)))
            selected_move = noisy_pool[0][0]
            picked_random_tie = True

        near_best_compact = ",".join([f"{move}:{score}" for move, score in near_best])
        self._last_planner_choice_debug = (
            f"source=score selected={selected_move} best={best_score} tie_band={tie_band} "
            f"force_score_fallback={1 if force_score_fallback else 0} "
            f"stuck_softmax={1 if stuck_softmax_used else 0} "
            f"terminal_filtered={terminal_filtered} "
            f"randomize_ties={self.exploration_randomize_ties} picked_random_tie={picked_random_tie} "
            f"near_best=[{near_best_compact}]"
        )
        return selected_move

    def _best_maze_objective_move(self) -> str:
        # Capture immediately if a single step can reach the target.
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            nxt = self._neighbor_for_move(self.current_player_cell, move)
            if nxt == self.current_target_cell and not self._is_blocked_cell(nxt):
                return move

        # Shift from exploration to objective-seeking once the exit is
        # currently visible, or once episodic mapping has fully converged.
        target_row, target_col = self.current_target_cell
        target_known_visible = (
            self.maze_known_cells.get(self.current_target_cell, "") == "E"
            and self._is_local_cell_visible(
                self.current_player_cell[0],
                self.current_player_cell[1],
                target_row,
                target_col,
                facing=self.player_facing,
            )
        )
        if (not target_known_visible) and (not self._maze_episode_fully_mapped()):
            return ""
        if (not target_known_visible) and (not self._maze_objective_override_safe()):
            return ""

        current_distance = self._distance_between_cells(self.current_player_cell, self.current_target_cell)
        if current_distance <= 0 or current_distance >= self.grid_cells * self.grid_cells:
            return ""

        # Prefer shortest-path moves that keep immediate geometric progress
        # toward the seen exit (instead of oscillating on tie-equivalent moves).
        target_row, target_col = self.current_target_cell
        player_row, player_col = self.current_player_cell
        toward_target_order: list[str] = []
        if target_row < player_row:
            toward_target_order.append("UP")
        elif target_row > player_row:
            toward_target_order.append("DOWN")
        if target_col < player_col:
            toward_target_order.append("LEFT")
        elif target_col > player_col:
            toward_target_order.append("RIGHT")
        if self.player_facing in {"UP", "DOWN", "LEFT", "RIGHT"} and self.player_facing not in toward_target_order:
            toward_target_order.append(self.player_facing)
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if move not in toward_target_order:
                toward_target_order.append(move)

        for move in toward_target_order:
            nxt = self._neighbor_for_move(self.current_player_cell, move)
            if nxt == self.current_player_cell or self._is_blocked_cell(nxt):
                continue
            nxt_distance = self._distance_between_cells(nxt, self.current_target_cell)
            if nxt_distance == current_distance - 1:
                return move

        path = self._shortest_path_moves_between_cells(self.current_player_cell, self.current_target_cell)
        if path:
            return path[0]
        return ""

    def _objective_move_risk_score(self, move: str) -> float:
        if not move:
            return float("inf")
        if not self._is_valid_traversal_move(move):
            return float("inf")

        breakdown = self._exploration_move_breakdown(move)
        risk_score = 0.0
        risk_score += float(breakdown.get("terminal_hard_veto_penalty", 0) or 0)
        risk_score += float(breakdown.get("dead_end_end_slap_penalty", 0) or 0)
        risk_score += float(breakdown.get("dead_end_tip_revisit_slap_penalty", 0) or 0)
        risk_score += float(breakdown.get("revisit_dead_end_entrance_penalty", 0) or 0)
        risk_score += float(breakdown.get("boxed_corridor_penalty", 0) or 0) * float(
            breakdown.get("boxed_corridor_no_exit", 0) or 0
        )
        risk_score += float(breakdown.get("visible_terminal_end_penalty", 0) or 0) * float(
            breakdown.get("dead_end_risk_depth", 0) or 0
        )
        risk_score += float(breakdown.get("cycle_pair_penalty", 0) or 0)
        risk_score += float(breakdown.get("transition_repeat_penalty", 0) or 0)
        risk_score += float(breakdown.get("immediate_backtrack_hard_penalty", 0) or 0)
        risk_score += float(breakdown.get("cause_effect_memory_penalty", 0) or 0)
        risk_score -= float(breakdown.get("cause_effect_memory_reward", 0) or 0)
        return float(risk_score)

    def _objective_move_with_risk_guard(self, preferred_move: str) -> tuple[str, str]:
        if not preferred_move:
            return ("", "")
        if not self._is_valid_traversal_move(preferred_move):
            return ("", "")

        current_distance = self._distance_between_cells(self.current_player_cell, self.current_target_cell)
        if current_distance <= 0 or current_distance >= self.grid_cells * self.grid_cells:
            return (preferred_move, "")

        preferred_risk = self._objective_move_risk_score(preferred_move)
        severe_risk_threshold = 120.0
        if preferred_risk < severe_risk_threshold:
            return (preferred_move, "")

        best_move = preferred_move
        best_risk = preferred_risk
        detour_tolerance = 1
        progress_candidates: list[tuple[float, int, str]] = []
        detour_candidates: list[tuple[float, int, str]] = []
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if move == preferred_move:
                continue
            if not self._is_valid_traversal_move(move):
                continue

            nxt = self._neighbor_for_move(self.current_player_cell, move)
            next_distance = self._distance_between_cells(nxt, self.current_target_cell)
            if next_distance >= self.grid_cells * self.grid_cells:
                continue
            # Allow tiny objective detours to escape known trap transitions.
            if next_distance > (current_distance + detour_tolerance):
                continue

            alt_risk = self._objective_move_risk_score(move)
            candidate = (alt_risk, next_distance, move)
            if next_distance < current_distance:
                progress_candidates.append(candidate)
            else:
                detour_candidates.append(candidate)

        candidate_pool = progress_candidates if progress_candidates else detour_candidates
        if candidate_pool:
            candidate_pool.sort(key=lambda item: (item[0], item[1], item[2]))
            best_risk, _, best_move = candidate_pool[0]

        if best_move != preferred_move and (best_risk + 25.0) < preferred_risk:
            note = (
                "[OBJECTIVE-RISK-GUARD: "
                f"{preferred_move}->{best_move} risk={int(round(preferred_risk))}->{int(round(best_risk))}]"
            )
            return (best_move, note)
        return (preferred_move, "")

    def _objective_progress_guard(
        self,
        selected_move: str,
        shortest_path_move: str,
        enforce_strict_progress: bool,
    ) -> tuple[str, str]:
        if (not enforce_strict_progress) or (not selected_move) or (not shortest_path_move):
            return (selected_move, "")
        if (not self._is_valid_traversal_move(selected_move)) or (not self._is_valid_traversal_move(shortest_path_move)):
            return (selected_move, "")

        current_distance = self._distance_between_cells(self.current_player_cell, self.current_target_cell)
        selected_next = self._neighbor_for_move(self.current_player_cell, selected_move)
        shortest_next = self._neighbor_for_move(self.current_player_cell, shortest_path_move)
        selected_distance = self._distance_between_cells(selected_next, self.current_target_cell)
        shortest_distance = self._distance_between_cells(shortest_next, self.current_target_cell)
        # Strict progress means objective distance must monotonically decrease.
        # Do not require the steepest local drop if a safer alternative still progresses.
        if selected_distance < current_distance:
            return (selected_move, "")

        note = (
            "[OBJECTIVE-PROGRESS-GUARD: "
            f"{selected_move}->{shortest_path_move} dist={current_distance}->{selected_distance}->{shortest_distance}]"
        )
        return (shortest_path_move, note)

    def _goal_directed_cycle_escape_move(
        self,
        preferred_move: str,
        candidate_moves: set[str],
        cycle_vetoed_moves: set[str],
    ) -> tuple[str, str]:
        if not preferred_move:
            return ("", "")
        if preferred_move not in cycle_vetoed_moves:
            return (preferred_move, "")

        current_distance = self._distance_between_cells(self.current_player_cell, self.current_target_cell)
        if current_distance <= 0 or current_distance >= self.grid_cells * self.grid_cells:
            return (preferred_move, "")

        preferred_risk = self._objective_move_risk_score(preferred_move)
        alternatives: list[tuple[float, int, str]] = []
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            if move == preferred_move or move not in candidate_moves:
                continue
            if move in cycle_vetoed_moves:
                continue
            if not self._is_valid_traversal_move(move):
                continue

            nxt = self._neighbor_for_move(self.current_player_cell, move)
            next_distance = self._distance_between_cells(nxt, self.current_target_cell)
            if next_distance >= self.grid_cells * self.grid_cells:
                continue
            # Allow a one-step detour to break objective loops.
            if next_distance > (current_distance + 1):
                continue

            risk = self._objective_move_risk_score(move)
            alternatives.append((risk, next_distance, move))

        if not alternatives:
            return (preferred_move, "")

        alternatives.sort(key=lambda item: (item[0], item[1], item[2]))
        best_risk, best_distance, best_move = alternatives[0]
        note = (
            "[GOAL-CYCLE-GUARD: "
            f"{preferred_move}->{best_move} risk={int(round(preferred_risk))}->{int(round(best_risk))} "
            f"dist={current_distance}->{best_distance}]"
        )
        return (best_move, note)

    def _frontier_first_step(self) -> str:
        persistent_move = self._persistent_frontier_step()
        if persistent_move:
            return persistent_move

        def bfs_to_frontier(avoid_dead_end_entrances: bool, avoid_immediate_backtrack: bool) -> str:
            start = self.current_player_cell
            if self._unknown_neighbor_count(start) > 0:
                # Already on a frontier cell; use local scoring for immediate move.
                return ""

            # Anti-ping-pong guard: when multiple legal exits exist from the
            # current cell, avoid immediately returning to the previous-previous
            # cell on frontier routing.
            backtrack_cell = self.prev_prev_player_cell
            legal_first_moves: list[tuple[str, tuple[int, int]]] = []
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                nxt = self._neighbor_for_move(start, move)
                if nxt == start or self._is_blocked_cell(nxt):
                    continue
                legal_first_moves.append((move, nxt))
            has_non_backtrack_first_option = any(nxt != backtrack_cell for _move, nxt in legal_first_moves)
            has_non_terminal_first_option = any(
                (
                    (not self._is_move_visibly_terminal_dead_end(start, move))
                    and (not self._is_move_visibly_boxed_corridor_without_exit(start, move))
                )
                for move, _nxt in legal_first_moves
            )

            queue: deque[tuple[tuple[int, int], list[str]]] = deque([(start, [])])
            seen = {start}
            while queue:
                cell, path = queue.popleft()
                if path and self._unknown_neighbor_count(cell) > 0:
                    return path[0]

                moves = ["UP", "DOWN", "LEFT", "RIGHT"]
                if self.exploration_randomize_ties:
                    self._planner_rng.shuffle(moves)
                for move in moves:
                    nxt = self._neighbor_for_move(cell, move)
                    if nxt == cell or nxt in seen or self._is_blocked_cell(nxt):
                        continue
                    if (
                        avoid_immediate_backtrack
                        and not path
                        and has_non_backtrack_first_option
                        and nxt == backtrack_cell
                    ):
                        continue
                    if (
                        not path
                        and has_non_terminal_first_option
                        and (
                            self._is_move_visibly_terminal_dead_end(start, move)
                            or self._is_move_visibly_boxed_corridor_without_exit(start, move)
                        )
                    ):
                        continue
                    if avoid_dead_end_entrances and nxt in self.episode_dead_end_entrances:
                        continue
                    seen.add(nxt)
                    queue.append((nxt, path + [move]))
            return ""

        # Prefer frontiers that do not route through known dead-end entrances.
        first_pass = bfs_to_frontier(avoid_dead_end_entrances=True, avoid_immediate_backtrack=True)
        if first_pass:
            return first_pass
        second_pass = bfs_to_frontier(avoid_dead_end_entrances=False, avoid_immediate_backtrack=True)
        if second_pass:
            return second_pass
        return bfs_to_frontier(avoid_dead_end_entrances=False, avoid_immediate_backtrack=False)

    def _is_valid_traversal_move(self, move: str) -> bool:
        if move not in {"UP", "DOWN", "LEFT", "RIGHT"}:
            return False
        nxt = self._neighbor_for_move(self.current_player_cell, move)
        return nxt != self.current_player_cell and not self._is_blocked_cell(nxt)

    def _is_transition_taboo(self, from_cell: tuple[int, int], to_cell: tuple[int, int]) -> bool:
        key = (from_cell, to_cell)
        expiry = self.taboo_transitions.get(key)
        if expiry is None:
            return False
        if int(self.memory_step_index) <= int(expiry):
            return True
        self.taboo_transitions.pop(key, None)
        return False

    def _register_transition_trap_event(
        self,
        from_cell: tuple[int, int] | None,
        to_cell: tuple[int, int] | None,
        reason_tags: list[str],
        outcome_score: float,
    ) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        if from_cell is None or to_cell is None or from_cell == to_cell:
            return
        if outcome_score >= -0.01:
            return
        tag_set = {str(tag).strip() for tag in reason_tags if str(tag).strip()}
        required_tags = {"cycle_pair", "visible_terminal", "boxed_corridor"}
        if not required_tags.issubset(tag_set):
            return

        step_idx = int(self.memory_step_index)
        self.recent_trap_transition_events.append((step_idx, from_cell, to_cell))
        window_start = step_idx - max(6, self.recent_cycle_window)
        same_edge_count = 0
        reverse_edge_count = 0
        for event_step, event_from, event_to in self.recent_trap_transition_events:
            if event_step < window_start:
                continue
            if event_from == from_cell and event_to == to_cell:
                same_edge_count += 1
            elif event_from == to_cell and event_to == from_cell:
                reverse_edge_count += 1

        if same_edge_count >= self.cycle_taboo_threshold:
            self.taboo_transitions[(from_cell, to_cell)] = step_idx + self.cycle_taboo_duration_steps
        if (same_edge_count + reverse_edge_count) >= self.cycle_taboo_threshold:
            # Escalate ping-pong loops by tabooing both directions.
            expiry = step_idx + self.cycle_taboo_duration_steps
            self.taboo_transitions[(from_cell, to_cell)] = expiry
            self.taboo_transitions[(to_cell, from_cell)] = expiry

    def _traversable_neighbors(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        neighbors: list[tuple[int, int]] = []
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            nxt = self._neighbor_for_move(cell, move)
            if nxt != cell and not self._is_blocked_cell(nxt):
                neighbors.append(nxt)
        return neighbors

    def _boundary_blocked_summary(self, cell: tuple[int, int]) -> str:
        parts: list[str] = []
        for move in ["UP", "RIGHT", "DOWN", "LEFT"]:
            nxt = self._neighbor_for_move(cell, move)
            if nxt == cell:
                parts.append(f"{move}=bounds_wall")
            elif self._is_blocked_cell(nxt):
                parts.append(f"{move}=blocker_wall")
            else:
                parts.append(f"{move}=open")
        return ", ".join(parts)

    def _unknown_neighbor_count(self, cell: tuple[int, int]) -> int:
        count = 0
        row, col = cell
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr = row + dr
            nc = col + dc
            if nr < 0 or nr >= self.grid_cells or nc < 0 or nc >= self.grid_cells:
                continue
            if (nr, nc) not in self.maze_known_cells:
                count += 1
        return count

    def _is_fully_known_current_maze_cell(self, cell: tuple[int, int]) -> bool:
        if cell not in self.maze_known_cells:
            return False
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            nxt = self._neighbor_for_move(cell, move)
            if nxt == cell:
                continue
            if nxt not in self.maze_known_cells:
                return False
        return True

    def _episodic_memory_summary(self) -> dict[str, int]:
        summary = self._build_structural_summary()
        fully_known_open_cells = 0
        for cell, token in self.maze_known_cells.items():
            if token in {".", "P", "E"} and self._is_fully_known_current_maze_cell(cell):
                fully_known_open_cells += 1
        return {
            "known_open": int(summary.get("open_cells", 0) or 0),
            "known_blocked": int(summary.get("blocked_cells", 0) or 0),
            "unknown": int(summary.get("unknown_cells", 0) or 0),
            "frontier": int(summary.get("frontier_cells", 0) or 0),
            "junctions": int(summary.get("junction_cells", 0) or 0),
            "corridors": int(summary.get("corridor_cells", 0) or 0),
            "dead_ends": int(summary.get("dead_end_cells", 0) or 0),
            "fully_known_open": fully_known_open_cells,
            "visited_cells": len(self.episode_visited_cells),
        }

    def _is_corridor_cell(self, cell: tuple[int, int]) -> bool:
        neighbors = self._traversable_neighbors(cell)
        if len(neighbors) != 2:
            return False
        dr1 = neighbors[0][0] - cell[0]
        dc1 = neighbors[0][1] - cell[1]
        dr2 = neighbors[1][0] - cell[0]
        dc2 = neighbors[1][1] - cell[1]
        return dr1 == -dr2 and dc1 == -dc2

    def _potential_opening_count(self, cell: tuple[int, int]) -> int:
        """Count unknown neighbor cells that are adjacent to known open geometry."""
        count = 0
        row, col = cell
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr = row + dr
            nc = col + dc
            if nr < 0 or nr >= self.grid_cells or nc < 0 or nc >= self.grid_cells:
                continue
            unknown_cell = (nr, nc)
            if unknown_cell in self.blocked_cells or unknown_cell in self.maze_known_cells:
                continue

            has_known_open_neighbor = False
            for adr, adc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ar = nr + adr
                ac = nc + adc
                if ar < 0 or ar >= self.grid_cells or ac < 0 or ac >= self.grid_cells:
                    continue
                adjacent = (ar, ac)
                if adjacent in self.blocked_cells:
                    continue
                if adjacent in self.maze_known_cells:
                    has_known_open_neighbor = True
                    break

            if has_known_open_neighbor:
                count += 1
        return count

    def _biological_navigation_signals(
        self,
        origin: tuple[int, int],
        move: str,
        candidate: tuple[int, int],
        edge_scan: dict[str, int | bool | str],
        unknown_neighbors: int,
        dead_end_risk_depth: int,
        visits: int,
        frontier_distance: int,
        transition_pressure_bucket: int,
        backtrack: int,
    ) -> dict[str, int]:
        if not self.bio_nav_enable:
            return {
                "bio_opening_bonus": 0,
                "bio_dead_end_escape_bonus": 0,
                "bio_novelty_bonus": 0,
                "bio_corridor_flow_bonus": 0,
                "bio_dead_end_predictive_penalty": 0,
                "bio_loop_risk_penalty": 0,
                "bio_opening_evidence": 0,
            }

        origin_unknown = self._unknown_neighbor_count(origin)
        origin_frontier_distance = self._frontier_distance(origin)
        opening_evidence = 0
        if bool(edge_scan.get("junction_visible", False)):
            opening_evidence += 1
        if bool(edge_scan.get("frontier_visible", False)):
            opening_evidence += 1
        if int(edge_scan.get("side_open_steps", 0) or 0) > 0:
            opening_evidence += 1
        if int(edge_scan.get("inferred_side_open_steps", 0) or 0) > 0:
            opening_evidence += 1
        if int(edge_scan.get("inferred_diagonal_open_contacts", 0) or 0) > 0:
            opening_evidence += 1
        opening_evidence += min(2, self._potential_opening_count(candidate))

        bio_opening_bonus = 0
        if opening_evidence > 0:
            bio_opening_bonus = int(round(self.bio_nav_opening_weight * min(1.0, opening_evidence / 3.0)))

        novelty_gain = max(0, unknown_neighbors - origin_unknown)
        bio_novelty_bonus = int(round(novelty_gain * self.bio_nav_novelty_scale))

        bio_corridor_flow_bonus = 0
        if self._is_corridor_cell(origin) and move == self.player_facing and backtrack == 0:
            bio_corridor_flow_bonus = int(self.bio_nav_corridor_flow_weight)

        origin_open_degree = len(self._traversable_neighbors(origin))
        in_tight_origin = (origin_open_degree <= 2 and origin_unknown == 0) or transition_pressure_bucket >= 2
        bio_dead_end_escape_bonus = 0
        if in_tight_origin:
            escaping = (
                unknown_neighbors > origin_unknown
                or frontier_distance < origin_frontier_distance
                or bool(edge_scan.get("junction_visible", False))
                or bool(edge_scan.get("frontier_visible", False))
            )
            if escaping:
                bio_dead_end_escape_bonus = int(self.bio_nav_dead_end_escape_weight)

        bio_dead_end_predictive_penalty = 0
        if dead_end_risk_depth >= 2 and unknown_neighbors == 0:
            depth_units = max(1, min(3, dead_end_risk_depth - 1))
            bio_dead_end_predictive_penalty = int(self.bio_nav_dead_end_predictive_penalty) * depth_units
            if visits > 0:
                bio_dead_end_predictive_penalty += int(round(self.bio_nav_dead_end_predictive_penalty * 0.5))

        bio_loop_risk_penalty = 0
        if candidate in self.maze_recent_cells and unknown_neighbors == 0 and opening_evidence == 0:
            bio_loop_risk_penalty = int(self.bio_nav_loop_risk_penalty)

        return {
            "bio_opening_bonus": bio_opening_bonus,
            "bio_dead_end_escape_bonus": bio_dead_end_escape_bonus,
            "bio_novelty_bonus": bio_novelty_bonus,
            "bio_corridor_flow_bonus": bio_corridor_flow_bonus,
            "bio_dead_end_predictive_penalty": bio_dead_end_predictive_penalty,
            "bio_loop_risk_penalty": bio_loop_risk_penalty,
            "bio_opening_evidence": opening_evidence,
        }

    def _frontier_distance(self, start: tuple[int, int], max_depth: int = 10) -> int:
        if self._unknown_neighbor_count(start) > 0:
            return 0

        queue: deque[tuple[tuple[int, int], int]] = deque([(start, 0)])
        seen = {start}
        while queue:
            cell, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for nxt in self._traversable_neighbors(cell):
                if nxt in seen:
                    continue
                nd = depth + 1
                if self._unknown_neighbor_count(nxt) > 0:
                    return nd
                seen.add(nxt)
                queue.append((nxt, nd))
        return max_depth + 1

    def _recent_transition_counts(self, origin: tuple[int, int], candidate: tuple[int, int]) -> tuple[int, int]:
        """Return counts of forward and reverse transitions in the recent cycle window."""
        if not self.maze_recent_transitions:
            return (0, 0)

        window = list(self.maze_recent_transitions)[-self.recent_cycle_window :]
        forward = 0
        reverse = 0
        for frm, to in window:
            if frm == origin and to == candidate:
                forward += 1
            elif frm == candidate and to == origin:
                reverse += 1
        return (forward, reverse)

    def _local_map_authority_scale(
        self,
        *,
        is_known: int,
        visits: int,
        backtrack: int,
        recent_penalty: int,
        unknown_neighbors: int,
        frontier_distance: int,
        episodic_dead_end_known: bool,
        candidate_is_target: bool,
    ) -> tuple[float, bool, bool]:
        """Return (authority_scale, episodic_constraint_active, cross_maze_influence_allowed)."""
        episodic_constraint_active = (
            (is_known == 1) or (visits > 0) or episodic_dead_end_known
        ) and (not candidate_is_target)

        cross_maze_influence_allowed = (
            (unknown_neighbors > 0)
            and (frontier_distance > 0)
            and (backtrack == 0)
            and (visits == 0)
            and (not episodic_dead_end_known)
            and (not candidate_is_target)
        )

        if self.local_map_authority_mode == "strict":
            scale = 1.0 if (episodic_constraint_active and (not cross_maze_influence_allowed)) else 0.0
            return (scale, episodic_constraint_active, cross_maze_influence_allowed)

        # Soft mode: continuous confidence-weighted blending (Bayesian-style).
        evidence = 0.0
        if is_known:
            evidence += 0.45
        evidence += min(0.30, visits * 0.12)
        if episodic_dead_end_known:
            evidence += 0.40
        if unknown_neighbors == 0:
            evidence += 0.20
        if frontier_distance >= 3:
            evidence += 0.10
        if backtrack:
            evidence += 0.12
        if recent_penalty:
            evidence += 0.08

        if unknown_neighbors > 0:
            evidence -= 0.28
        if frontier_distance <= 1:
            evidence -= 0.18
        if visits == 0 and backtrack == 0:
            evidence -= 0.08

        normalized = max(0.0, min(1.0, evidence))
        scale = max(0.0, min(1.0, self.local_map_authority_soft_scale)) * normalized
        if episodic_constraint_active and (not cross_maze_influence_allowed):
            scale = max(scale, min(1.0, self.local_map_authority_soft_scale * 0.65))
        return (scale, episodic_constraint_active, cross_maze_influence_allowed)

    def _exploration_move_score(self, move: str) -> int:
        return self._exploration_move_breakdown(move)["score"]

    def _decision_noise_term(self, move: str) -> int:
        """Small per-decision noise to break deterministic corridor ordering."""
        if self.decision_noise_weight <= 0:
            return 0
        key = (self.memory_step_index, self.current_player_cell, move)
        cached = self._decision_noise_cache.get(key)
        if cached is not None:
            return cached

        term = int(round(self._decision_noise_rng.uniform(-self.decision_noise_weight, self.decision_noise_weight)))
        self._decision_noise_cache[key] = term
        if len(self._decision_noise_cache) > 512:
            self._decision_noise_cache.clear()
        return term

    def _exploration_move_breakdown(self, move: str) -> dict:
        if not move:
            return {
                "score": 10_000,
                "blocked": True,
                "visits": 0,
                "backtrack": 0,
                "known": 1,
                "known_dead_area": 1,
                "frontier_distance": 99,
                "unknown_neighbors": 0,
                "open_degree": 0,
            }
        origin = self.current_player_cell
        candidate = self._neighbor_for_move(origin, move)
        if candidate == origin or self._is_blocked_cell(candidate):
            return {
                "score": 10_000,
                "blocked": True,
                "visits": 0,
                "backtrack": 0,
                "known": 1,
                "known_dead_area": 1,
                "frontier_distance": 99,
                "unknown_neighbors": 0,
                "open_degree": 0,
            }

        visits = self.episode_visited_cells.get(candidate, 0)
        personality = self.maze_personality or {}
        dead_end_penalty_scale = float(personality.get("dead_end_penalty_scale", 1.0))
        novelty_reward_scale = float(personality.get("novelty_reward_scale", 1.0))
        branch_diversity_scale = float(personality.get("branch_diversity_scale", 1.0))
        corridor_penalty_scale = float(personality.get("corridor_penalty_scale", 1.0))
        direction_bias = personality.get("direction_bias", {}) if isinstance(personality.get("direction_bias", {}), dict) else {}
        move_personality_bias = int(direction_bias.get(move, 0)) if isinstance(direction_bias, dict) else 0
        dead_end_allowance = int(personality.get("dead_end_allowance", self.dead_end_learning_allowance_base))
        dead_end_allowance_remaining = max(0, dead_end_allowance - self.episode_dead_end_learn_events)
        difficulty_dead_end_scale = self._dead_end_difficulty_scale()
        attempt_dead_end_scale = self._attempt_dead_end_scale()
        is_known = 1 if candidate in self.maze_known_cells else 0
        backtrack = 1 if candidate == self.prev_prev_player_cell else 0
        recent_penalty = 1 if candidate in self.maze_recent_cells else 0
        recent_recency_penalty = 0
        if self.maze_recent_cells:
            recent_cells_list = list(self.maze_recent_cells)
            if candidate in recent_cells_list:
                # Penalize very recent revisits more heavily to reduce local oscillation.
                distance_from_tail = len(recent_cells_list) - recent_cells_list[::-1].index(candidate)
                recency_rank = max(1, len(recent_cells_list) - distance_from_tail + 1)
                recent_recency_penalty = max(0, 14 - recency_rank)
        open_degree = len(self._traversable_neighbors(candidate))
        unknown_neighbors = self._unknown_neighbor_count(candidate)
        origin_frontier_distance = self._frontier_distance(origin)
        frontier_distance = self._frontier_distance(candidate)
        episodic_summary = self._episodic_memory_summary()
        episodic_known_open = int(episodic_summary.get("known_open", 0) or 0)
        episodic_unknown_cells = int(episodic_summary.get("unknown", 0) or 0)
        episodic_frontier_cells = int(episodic_summary.get("frontier", 0) or 0)
        frontier_lock_active = self._frontier_lock_active(episodic_unknown_cells, episodic_frontier_cells)
        move_entropy = self._recent_move_direction_entropy()
        candidate_fully_known_current_maze = self._is_fully_known_current_maze_cell(candidate)
        episodic_dead_end_known = (
            candidate in self.episode_dead_end_tip_cells
            or candidate in self.episode_dead_end_entrances
        )
        known_dead_area = 1 if (is_known and unknown_neighbors == 0 and open_degree <= 1) else 0
        if known_dead_area == 1:
            episodic_dead_end_known = True
        local_map_authority_scale, episodic_constraint_active, cross_maze_influence_allowed = self._local_map_authority_scale(
            is_known=is_known,
            visits=visits,
            backtrack=backtrack,
            recent_penalty=recent_penalty,
            unknown_neighbors=unknown_neighbors,
            frontier_distance=frontier_distance,
            episodic_dead_end_known=episodic_dead_end_known,
            candidate_is_target=(candidate == self.current_target_cell),
        )
        episodic_exploration_locked = local_map_authority_scale >= 0.999
        # --- Prediction memory bias (unknown cells only) ---
        # When the candidate is unknown but has an active shape prediction,
        # bias scoring toward predicted junctions and away from predicted dead-ends.
        prediction_junction_bonus = 0
        prediction_dead_end_penalty = 0
        prediction_used = False
        prediction_context_trust = 0.0
        prediction_effective_conf = 0.0
        if not is_known:
            (
                prediction_junction_bonus,
                prediction_dead_end_penalty,
                prediction_context_trust,
                prediction_effective_conf,
            ) = self._prediction_candidate_bias(candidate)
            prediction_used = (prediction_junction_bonus > 0) or (prediction_dead_end_penalty > 0)
        corridor_commit = self._known_corridor_commitment(origin, move)
        dead_end_risk_depth = self._dead_end_risk_depth(origin, move)
        dead_end_exp_penalty = 0
        short_dead_end_penalty = 0
        revisit_dead_end_entrance_penalty = 0
        narrow_corridor_additive_penalty = 0
        dead_end_learning_grace = 0
        if dead_end_risk_depth > 0:
            # Keep this penalty intentionally mild: discourage repeated dead-end
            # commitment without fully suppressing cautious probing.
            capped_depth = min(7, dead_end_risk_depth)
            dead_end_exp_penalty = int(
                round(
                    ((2 ** capped_depth - 1) * 2)
                    * dead_end_penalty_scale
                    * difficulty_dead_end_scale
                    * attempt_dead_end_scale
                )
            )
            # Strongly discourage low-information short dead-end probes (1-2 cells deep).
            if dead_end_risk_depth <= 2:
                frontier_weight = 1.0 + (min(6, frontier_distance) * max(0.0, self.dead_end_frontier_distance_scale))
                short_dead_end_penalty = int(
                    round(
                        (3 - dead_end_risk_depth)
                        * self.shallow_dead_end_penalty_base
                        * dead_end_penalty_scale
                        * difficulty_dead_end_scale
                        * attempt_dead_end_scale
                        * frontier_weight
                    )
                )
            if dead_end_allowance_remaining > 0 and visits == 0 and dead_end_risk_depth >= 3:
                # Allow one (or configured few) exploratory dead-end probes as learning samples.
                dead_end_learning_grace = 1
                dead_end_exp_penalty = min(dead_end_exp_penalty, 2)

        if candidate in self.episode_dead_end_entrances:
            revisit_dead_end_entrance_penalty = int(
                round(
                    self.revisit_dead_end_entrance_penalty
                    * difficulty_dead_end_scale
                    * attempt_dead_end_scale
                )
            )
        # Penalize committing into narrow single-exit corridors unless frontier evidence is strong.
        if open_degree <= 1 and unknown_neighbors == 0:
            narrow_corridor_additive_penalty = int(
                round(
                    self.narrow_corridor_penalty
                    * difficulty_dead_end_scale
                    * attempt_dead_end_scale
                )
            )
        edge_scan = self._directional_edge_scan(origin[0], origin[1], move)
        straight_tunnel = 1 if (edge_scan["clear_run"] >= 3 and not edge_scan["edge_detected"]) else 0
        visible_open_decision = (
            1
            if (
                edge_scan["frontier_visible"] or edge_scan["junction_visible"]
            )
            else 0
        )
        visible_closed_structure = (
            1
            if (
                edge_scan["edge_type"] in {"blocked", "bounds", "occluded"}
                and (not edge_scan["frontier_visible"])
                and (not edge_scan["junction_visible"])
            )
            else 0
        )
        row, col = candidate
        at_boundary = row in {0, self.grid_cells - 1} or col in {0, self.grid_cells - 1}
        boundary_hug = (
            1
            if (
                at_boundary
                and unknown_neighbors == 0
                and (not edge_scan["frontier_visible"])
                and (not edge_scan["junction_visible"])
            )
            else 0
        )
        terminal_corridor = (
            1
            if (
                edge_scan["clear_run"] >= 1
                and edge_scan["edge_type"] in {"bounds", "blocked"}
                and (not edge_scan["frontier_visible"])
                and (not edge_scan["junction_visible"])
                and (not edge_scan["exit_visible"])
            )
            else 0
        )
        boxed_corridor_no_exit = 1 if edge_scan["boxed_corridor_without_exit"] else 0
        visible_exit_corridor = 1 if edge_scan["exit_visible"] else 0
        pre_tip_dead_end_commit = (
            open_degree <= 1
            and unknown_neighbors <= 1
            and candidate != self.current_target_cell
        )
        visible_terminal_dead_end_commit = (
            candidate != self.current_target_cell
            and (
                (terminal_corridor == 1)
                or (boxed_corridor_no_exit == 1)
            )
        )
        dead_end_end_slap_penalty = 0
        if pre_tip_dead_end_commit or visible_terminal_dead_end_commit:
            # Slap immediately when a branch is visibly terminal/no-exit, even if
            # mapping state has not fully collapsed to a known tip yet.
            if visible_terminal_dead_end_commit:
                slap_scale = 1.0
            else:
                slap_scale = 1.0 if unknown_neighbors == 0 else 0.72
            dead_end_end_slap_penalty = int(
                round(
                    self.dead_end_end_slap_penalty
                    * slap_scale
                    * difficulty_dead_end_scale
                    * attempt_dead_end_scale
                )
            )
        dead_end_tip_revisit_slap_penalty = 0
        if (
            candidate != self.current_target_cell
            and (
                candidate in self.episode_dead_end_tip_cells
                or ((pre_tip_dead_end_commit or visible_terminal_dead_end_commit) and visits > 0)
            )
        ):
            dead_end_tip_revisit_slap_penalty = int(
                round(
                    self.dead_end_tip_revisit_slap_penalty
                    * difficulty_dead_end_scale
                    * attempt_dead_end_scale
                )
            )
        branch_diversity_penalty = 0
        origin_open_neighbors = self._traversable_neighbors(origin)
        forced_single_exit = len(origin_open_neighbors) <= 1
        if len(origin_open_neighbors) >= 2:
            sibling_visits = [self.episode_visited_cells.get(cell, 0) for cell in origin_open_neighbors]
            min_sibling_visits = min(sibling_visits) if sibling_visits else 0
            # Prefer less-visited sibling branches at decision points to avoid
            # over-committing to the first explored branch/dead-end.
            branch_diversity_penalty = max(0, visits - min_sibling_visits) * 7
        branch_diversity_penalty = int(round(branch_diversity_penalty * branch_diversity_scale))
        seen_corridor_continue_penalty = 0
        if is_known and unknown_neighbors == 0 and open_degree <= 2:
            # Mildly discourage over-clearing already-seen corridor segments.
            # This keeps exploration active but reduces "sweep every tile" behavior.
            seen_corridor_continue_penalty = min(5, max(0, int(edge_scan["clear_run"]) - 1)) * 2
        seen_corridor_continue_penalty = int(round(seen_corridor_continue_penalty * corridor_penalty_scale))
        episodic_relevance_penalty = 0
        if episodic_constraint_active and frontier_distance >= origin_frontier_distance:
            base_episodic_penalty = 10 + (visits * 5) + (recent_penalty * 6)
            episodic_relevance_penalty = int(round(base_episodic_penalty * local_map_authority_scale))
        corridor_suppression_active = (
            unknown_neighbors == 0
            and open_degree <= 2
            and (not bool(edge_scan["frontier_visible"]))
            and (not bool(edge_scan["junction_visible"]))
            and visible_exit_corridor == 0
        )
        corridor_suppression_penalty = 0
        if corridor_suppression_active:
            corridor_suppression_penalty = 8 + (visits * 4) + (backtrack * 6)
        recent_transition_count, recent_reverse_transition_count = self._recent_transition_counts(origin, candidate)
        transition_repeat_penalty = int(round(recent_transition_count * self.cycle_transition_penalty_weight))
        cycle_pair_penalty = int(round(recent_reverse_transition_count * self.cycle_pair_penalty_weight))
        stuck_transition_taboo_boost = 0
        if self._maze_reexplore_cooldown_remaining > 0:
            # Stuck-only short taboo pressure: keep normal behavior unchanged outside
            # re-explore mode, but strongly suppress repeated directed transitions
            # and ping-pong pairs while cooldown is active.
            stuck_transition_taboo_boost = int(
                round(
                    (recent_transition_count * self.maze_stuck_transition_repeat_boost)
                    + (recent_reverse_transition_count * self.maze_stuck_transition_reverse_boost)
                )
            )
        no_progress_repeat_penalty = 0
        if (
            visits > 0
            and unknown_neighbors == 0
            and frontier_distance >= origin_frontier_distance
        ):
            no_progress_repeat_penalty = max(0, int(self.no_progress_repeat_penalty))
        loop_commitment_penalty = 0
        if recent_reverse_transition_count > 0 and visits > 0 and unknown_neighbors == 0:
            loop_commitment_penalty = max(0, int(self.loop_commitment_penalty))
        immediate_backtrack_hard_penalty = 0
        if backtrack and unknown_neighbors == 0:
            has_non_backtrack_alternative = False
            for alt_move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                if alt_move == move:
                    continue
                alt_cell = self._neighbor_for_move(origin, alt_move)
                if alt_cell == origin or self._is_blocked_cell(alt_cell):
                    continue
                if alt_cell == self.prev_prev_player_cell:
                    continue
                has_non_backtrack_alternative = True
                break
            if has_non_backtrack_alternative:
                immediate_backtrack_hard_penalty = max(0, int(self.immediate_backtrack_hard_penalty))
        transition_pressure_repeat_penalty = 0
        if visits > 0 and unknown_neighbors == 0 and (recent_transition_count + recent_reverse_transition_count) > 0:
            pressure_units = min(3, recent_transition_count + recent_reverse_transition_count)
            transition_pressure_repeat_penalty = (
                pressure_units * max(0, int(self.transition_pressure_repeat_penalty_weight))
            )

        post_reset_exhaustion_penalty = 0
        reset_failure_transition_penalty = 0
        reset_failure_cell_penalty = 0
        reset_success_transition_bonus = 0
        frontier_lock_progress_bonus = 0
        frontier_lock_loop_penalty = 0
        solved_region_penalty = 0
        transition_key = (origin, candidate)
        if self._active_same_maze_retry_count() > 0:
            if (
                candidate in self._post_reset_exhausted_cells
                and unknown_neighbors == 0
                and self._cell_visit_reset_epoch.get(candidate, -1) < self.reset_epoch
            ):
                post_reset_exhaustion_penalty = max(0, int(self.post_reset_exhaustion_penalty))
            if transition_key in self._post_reset_exhausted_transitions and unknown_neighbors == 0:
                post_reset_exhaustion_penalty += max(0, int(self.post_reset_exhaustion_penalty // 2))

            fail_t_count = int(self._post_reset_transition_failure_counts.get(transition_key, 0) or 0)
            fail_c_count = int(self._post_reset_cell_failure_counts.get(candidate, 0) or 0)
            success_t_count = int(self._post_reset_transition_success_counts.get(transition_key, 0) or 0)

            reset_failure_transition_penalty = min(
                220,
                fail_t_count * max(0, int(self.reset_failure_transition_penalty)),
            )
            reset_failure_cell_penalty = min(
                180,
                fail_c_count * max(0, int(self.reset_failure_cell_penalty)),
            )
            reset_success_transition_bonus = min(
                90,
                success_t_count * max(0, int(self.reset_success_transition_bonus)),
            )

        if frontier_lock_active:
            active_retries = max(1, self._active_same_maze_retry_count())
            frontier_target = self._select_persistent_frontier_target()
            preferred_move = ""
            if frontier_target is not None:
                path_to_frontier = self._path_to_frontier_target(frontier_target)
                if path_to_frontier:
                    preferred_move = path_to_frontier[0]
            if move == preferred_move:
                frontier_lock_progress_bonus = max(0, int(self.frontier_lock_retry_bonus)) * active_retries
            elif (
                unknown_neighbors == 0
                and candidate_fully_known_current_maze
                and frontier_distance >= origin_frontier_distance
            ):
                frontier_lock_loop_penalty = max(0, int(self.frontier_lock_loop_penalty)) * active_retries

        if (
            episodic_known_open >= 20
            and episodic_frontier_cells > 0
            and unknown_neighbors == 0
            and candidate_fully_known_current_maze
            and frontier_distance >= origin_frontier_distance
        ):
            solved_region_penalty = max(0, int(self.solved_region_penalty))

        transition_pressure_bucket = min(3, recent_transition_count + recent_reverse_transition_count)
        recent_forced_cells = set(self.recent_forced_corridor_cells)
        forced_corridor_reentry_penalty = 0
        if candidate in recent_forced_cells:
            forced_corridor_reentry_penalty = max(0, int(self.forced_corridor_reentry_penalty))

        endocrine_stress_penalty = 0
        endocrine_fatigue_penalty = 0
        endocrine_curiosity_bonus = 0
        endocrine_confidence_bonus = 0
        endocrine_momentum_bonus = 0
        endocrine_exploration_drive = 0.0
        endocrine_risk_aversion = 0.0
        endocrine_momentum = 0.0
        if self.endocrine_enabled:
            hormone = self.endocrine.state()
            neural = self.endocrine.neural_state()
            stress = float(hormone.get("stress", 0.0))
            curiosity = float(hormone.get("curiosity", 0.0))
            confidence = float(hormone.get("confidence", 0.0))
            fatigue = float(hormone.get("fatigue", 0.0))
            endocrine_exploration_drive = float(neural.get("exploration_drive", 0.0))
            endocrine_risk_aversion = float(neural.get("risk_aversion", 0.0))
            endocrine_momentum = float(neural.get("momentum", 0.0))

            if dead_end_risk_depth > 0 or terminal_corridor or boxed_corridor_no_exit:
                endocrine_stress_penalty = int(
                    round(stress * self.endocrine_stress_danger_weight * max(1, dead_end_risk_depth))
                )
            if visits > 0 or recent_penalty > 0:
                endocrine_fatigue_penalty = int(
                    round(fatigue * self.endocrine_fatigue_repeat_weight * (1 + recent_penalty + backtrack))
                )
            if unknown_neighbors > 0 or bool(edge_scan["frontier_visible"]) or bool(edge_scan["junction_visible"]):
                endocrine_curiosity_bonus = int(
                    round(curiosity * self.endocrine_curiosity_novelty_weight * max(1, unknown_neighbors))
                )
            if dead_end_risk_depth <= 1 and visits == 0:
                endocrine_confidence_bonus = int(round(confidence * self.endocrine_confidence_risk_bonus))
            endocrine_momentum_bonus = int(round(max(0.0, endocrine_momentum) * self.endocrine_momentum_bonus_weight))

        bio_nav = self._biological_navigation_signals(
            origin,
            move,
            candidate,
            edge_scan,
            unknown_neighbors,
            dead_end_risk_depth,
            visits,
            frontier_distance,
            transition_pressure_bucket,
            backtrack,
        )

        visit_bucket = 0
        if visits >= 4:
            visit_bucket = 3
        elif visits >= 2:
            visit_bucket = 2
        elif visits >= 1:
            visit_bucket = 1

        unknown_tightening_term = max(0, 1 - unknown_neighbors)
        frontier_tightening_term = 0
        if frontier_distance >= 3:
            frontier_tightening_term = 2
        elif frontier_distance >= 1:
            frontier_tightening_term = 1
        branch_tightening_score = (
            max(0, dead_end_risk_depth)
            + unknown_tightening_term
            + frontier_tightening_term
            + visit_bucket
            + max(0, transition_pressure_bucket - 1)
        )

        recent_frontier_seen = False
        recent_cells = list(self.maze_recent_cells)[-max(1, int(self.branch_recent_frontier_window)):]
        for seen_cell in recent_cells:
            if seen_cell == origin:
                continue
            manhattan = abs(seen_cell[0] - origin[0]) + abs(seen_cell[1] - origin[1])
            if manhattan > max(1, int(self.branch_recent_frontier_max_distance)):
                continue
            seen_unknown = self._unknown_neighbor_count(seen_cell)
            seen_frontier_dist = self._frontier_distance(seen_cell)
            if seen_unknown >= 2 or seen_frontier_dist <= 1:
                recent_frontier_seen = True
                break

        taboo_transition_penalty = 0
        if self._is_transition_taboo(origin, candidate):
            has_non_taboo_alternative = False
            for alt_move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                if alt_move == move:
                    continue
                alt_cell = self._neighbor_for_move(origin, alt_move)
                if alt_cell == origin or self._is_blocked_cell(alt_cell):
                    continue
                if not self._is_transition_taboo(origin, alt_cell):
                    has_non_taboo_alternative = True
                    break
            if has_non_taboo_alternative:
                taboo_transition_penalty = 2000

        if forced_single_exit:
            # Keep cycle/terminal penalties strong even in forced corridors.
            # Only soften generic no-progress commitment terms slightly.
            no_progress_repeat_penalty = int(round(no_progress_repeat_penalty * 0.25))
            loop_commitment_penalty = int(round(loop_commitment_penalty * 0.25))

        terminal_hard_veto_penalty = 0
        if terminal_corridor or boxed_corridor_no_exit:
            has_non_terminal_alternative = False
            for alt_move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                if alt_move == move:
                    continue
                alt_cell = self._neighbor_for_move(origin, alt_move)
                if alt_cell == origin or self._is_blocked_cell(alt_cell):
                    continue
                if (
                    (not self._is_move_visibly_terminal_dead_end(origin, alt_move))
                    and (not self._is_move_visibly_boxed_corridor_without_exit(origin, alt_move))
                ):
                    has_non_terminal_alternative = True
                    break
            if has_non_terminal_alternative and (dead_end_risk_depth >= 1 or visits > 0):
                terminal_hard_veto_penalty = max(0, int(self.terminal_corridor_hard_veto_penalty))

        branch_tightening_abort_penalty = 0
        branch_tightening_escape_bonus = 0
        branch_tightening_mode_active = False
        if branch_tightening_score >= int(self.branch_tightening_abort_threshold):
            has_escape_alternative = False
            candidate_is_escape = (
                unknown_neighbors >= 2
                or bool(edge_scan["frontier_visible"])
                or bool(edge_scan["junction_visible"])
            ) and (not terminal_corridor) and (not boxed_corridor_no_exit)
            for alt_move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                alt_cell = self._neighbor_for_move(origin, alt_move)
                if alt_cell == origin or self._is_blocked_cell(alt_cell):
                    continue
                if self._is_transition_taboo(origin, alt_cell):
                    continue
                alt_unknown = self._unknown_neighbor_count(alt_cell)
                alt_frontier = self._frontier_distance(alt_cell)
                alt_edge = self._directional_edge_scan(origin[0], origin[1], alt_move)
                alt_terminal = self._is_move_visibly_terminal_dead_end(origin, alt_move)
                alt_boxed = self._is_move_visibly_boxed_corridor_without_exit(origin, alt_move)
                alt_is_escape = (
                    alt_unknown > unknown_neighbors
                    or alt_frontier < frontier_distance
                    or bool(alt_edge.get("frontier_visible", False))
                    or bool(alt_edge.get("junction_visible", False))
                ) and (not alt_terminal) and (not alt_boxed)
                if alt_is_escape:
                    has_escape_alternative = True
                    break

            if has_escape_alternative and recent_frontier_seen:
                branch_tightening_mode_active = True
                if candidate_is_escape:
                    branch_tightening_escape_bonus = max(0, int(self.branch_tightening_escape_bonus))
                else:
                    branch_tightening_abort_penalty = max(0, int(self.branch_tightening_abort_penalty))

        cause_effect_reason_tags: list[str] = []
        if dead_end_end_slap_penalty > 0:
            cause_effect_reason_tags.append("dead_end_slap")
        if dead_end_tip_revisit_slap_penalty > 0:
            cause_effect_reason_tags.append("dead_end_tip_revisit")
        if revisit_dead_end_entrance_penalty > 0:
            cause_effect_reason_tags.append("dead_end_entrance_revisit")
        if terminal_corridor > 0:
            cause_effect_reason_tags.append("visible_terminal")
        if boxed_corridor_no_exit > 0:
            cause_effect_reason_tags.append("boxed_corridor")
        if cycle_pair_penalty > 0:
            cause_effect_reason_tags.append("cycle_pair")
        if transition_repeat_penalty > 0:
            cause_effect_reason_tags.append("transition_repeat")
        if immediate_backtrack_hard_penalty > 0:
            cause_effect_reason_tags.append("immediate_backtrack")
        if visible_open_decision > 0:
            cause_effect_reason_tags.append("visible_open_decision")

        cause_effect_penalty_signal, cause_effect_reward_signal, retrieved_cause_tags = self._cause_effect_retrieval_signal(
            move,
            cause_effect_reason_tags,
            {
                "unknown_neighbors": unknown_neighbors,
                "open_degree": open_degree,
                "frontier_distance": frontier_distance,
                "edge_type": str(edge_scan["edge_type"]),
            },
        )
        cross_maze_influence_factor = max(0.0, 1.0 - local_map_authority_scale)
        strict_risk_memory_floor_applied = 0
        strict_risk_context = 0
        if self.local_map_authority_mode == "strict":
            risk_tags = {
                "dead_end_slap",
                "dead_end_tip_revisit",
                "dead_end_entrance_revisit",
                "visible_terminal",
                "boxed_corridor",
                "cycle_pair",
                "transition_repeat",
                "immediate_backtrack",
            }
            strict_risk_context = 1 if any(tag in risk_tags for tag in cause_effect_reason_tags) else 0
            has_memory_signal = (cause_effect_penalty_signal > 0.0) or (cause_effect_reward_signal > 0.0)
            if strict_risk_context and has_memory_signal:
                risk_floor = max(0.0, min(1.0, self.strict_authority_risk_memory_min_scale))
                if risk_floor > cross_maze_influence_factor:
                    cross_maze_influence_factor = risk_floor
                    strict_risk_memory_floor_applied = 1
        cause_effect_memory_penalty = int(round(cause_effect_penalty_signal * cross_maze_influence_factor))
        cause_effect_memory_reward = int(round(cause_effect_reward_signal * cross_maze_influence_factor))
        if terminal_corridor or boxed_corridor_no_exit:
            cause_effect_memory_penalty = int(
                round(cause_effect_memory_penalty * max(1.0, self.trap_context_cause_effect_penalty_scale))
            )
        decision_noise = self._decision_noise_term(move)

        novelty_multiplier = max(0.0, 1.0 - local_map_authority_scale)
        effective_visible_open_decision = int(round(visible_open_decision * novelty_multiplier))
        effective_edge_frontier = bool(edge_scan["frontier_visible"]) and (novelty_multiplier > 0.0)
        effective_edge_junction = bool(edge_scan["junction_visible"]) and (novelty_multiplier > 0.0)
        effective_endocrine_curiosity_bonus = int(round(endocrine_curiosity_bonus * novelty_multiplier))
        effective_bio_opening_bonus = int(round(int(bio_nav["bio_opening_bonus"]) * novelty_multiplier))
        effective_bio_novelty_bonus = int(round(int(bio_nav["bio_novelty_bonus"]) * novelty_multiplier))
        effective_bio_corridor_flow_bonus = int(round(int(bio_nav["bio_corridor_flow_bonus"]) * novelty_multiplier))

        # Lower is better: heavily penalize repeated/dead-area moves, reward frontier expansion.
        score = 0
        score += visits * 9
        score += backtrack * 16
        score += recent_penalty * 14
        score += recent_recency_penalty
        score += is_known * 3
        score += int(round(known_dead_area * 20 * attempt_dead_end_scale))
        score += frontier_distance * 3
        score += corridor_commit * 4
        score += dead_end_exp_penalty
        score += short_dead_end_penalty
        score += revisit_dead_end_entrance_penalty
        score += dead_end_end_slap_penalty
        score += dead_end_tip_revisit_slap_penalty
        score += narrow_corridor_additive_penalty
        score += straight_tunnel * 10
        score += visible_closed_structure * 6
        score += boundary_hug * 12
        visible_terminal_end_penalty = max(0, int(self.visible_terminal_end_penalty))
        score += terminal_corridor * visible_terminal_end_penalty
        boxed_corridor_penalty = max(0, int(self.boxed_corridor_no_exit_penalty))
        score += boxed_corridor_no_exit * boxed_corridor_penalty
        score += branch_diversity_penalty
        score += seen_corridor_continue_penalty
        score += episodic_relevance_penalty
        score += corridor_suppression_penalty
        score += transition_repeat_penalty
        score += cycle_pair_penalty
        score += stuck_transition_taboo_boost
        score += no_progress_repeat_penalty
        score += loop_commitment_penalty
        score += immediate_backtrack_hard_penalty
        score += transition_pressure_repeat_penalty
        score += post_reset_exhaustion_penalty
        score += reset_failure_transition_penalty
        score += reset_failure_cell_penalty
        score += frontier_lock_loop_penalty
        score += solved_region_penalty
        score += forced_corridor_reentry_penalty
        score += taboo_transition_penalty
        score += terminal_hard_veto_penalty
        score += branch_tightening_abort_penalty
        score += int(bio_nav["bio_dead_end_predictive_penalty"])
        score += int(bio_nav["bio_loop_risk_penalty"])
        score += endocrine_stress_penalty
        score += endocrine_fatigue_penalty
        score += cause_effect_memory_penalty
        score += move_personality_bias
        score += decision_noise
        # Keep raw exploration reward intentionally weak. Strong preference comes
        # from seeing an unblocked decision/frontier ahead rather than blind probing.
        novelty_reward = int(round(unknown_neighbors * 2 * novelty_reward_scale))
        if dead_end_risk_depth > 0 or corridor_suppression_active:
            novelty_reward = 0
        elif local_map_authority_scale > 0.0:
            novelty_reward = int(round(novelty_reward * novelty_multiplier))
        score -= novelty_reward
        score -= max(0, open_degree - 2) * 1
        score -= effective_visible_open_decision * 22
        score -= cause_effect_memory_reward
        score -= branch_tightening_escape_bonus
        score -= effective_bio_opening_bonus
        score -= int(bio_nav["bio_dead_end_escape_bonus"])
        score -= effective_bio_novelty_bonus
        score -= effective_bio_corridor_flow_bonus
        score -= effective_endocrine_curiosity_bonus
        score -= endocrine_confidence_bonus
        score -= endocrine_momentum_bonus
        score -= reset_success_transition_bonus
        score -= frontier_lock_progress_bonus
        visible_exit_reward = max(0, int(self.visible_exit_corridor_reward))
        score -= visible_exit_corridor * visible_exit_reward
        if effective_edge_frontier:
            score -= 12
        if effective_edge_junction:
            score -= 10

        high_risk_frontier_override_bonus = 0
        if dead_end_risk_depth >= 2 and visits >= 2:
            has_frontier_escape_option = False
            for alt_move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                alt_cell = self._neighbor_for_move(origin, alt_move)
                if alt_cell == origin or self._is_blocked_cell(alt_cell):
                    continue
                alt_unknown = self._unknown_neighbor_count(alt_cell)
                alt_edge = self._directional_edge_scan(origin[0], origin[1], alt_move)
                if (
                    alt_unknown > unknown_neighbors
                    or bool(alt_edge.get("frontier_visible", False))
                    or bool(alt_edge.get("junction_visible", False))
                ):
                    has_frontier_escape_option = True
                    break
            if has_frontier_escape_option and (
                unknown_neighbors > 0
                or bool(edge_scan["frontier_visible"])
                or bool(edge_scan["junction_visible"])
            ):
                high_risk_frontier_override_bonus = max(0, int(self.high_risk_frontier_override_bonus))
                score -= high_risk_frontier_override_bonus

        # When transition pressure is high, reward moves that leave recent trap cells
        # and expose branching/frontier information.
        escape_bias_bonus = 0
        if transition_pressure_bucket >= 2:
            recent_window = set(list(self.maze_recent_cells)[-6:])
            is_recent_reentry = candidate in recent_window
            is_escape_move = (not is_recent_reentry) and (
                unknown_neighbors > 0
                or open_degree >= 3
                or bool(edge_scan["frontier_visible"])
                or bool(edge_scan["junction_visible"])
            )
            if is_escape_move:
                escape_bias_bonus = max(0, int(self.escape_bias_bonus)) + ((transition_pressure_bucket - 2) * 4)
                score -= escape_bias_bonus
        raw_prediction_junction_bonus = prediction_junction_bonus
        raw_prediction_dead_end_penalty = prediction_dead_end_penalty
        local_contradiction_debt = self._prediction_local_contradiction_debt(candidate)
        prediction_contradiction_scale = 1.0
        if prediction_used and local_contradiction_debt > 0.0:
            # Reduce prediction influence in regions with repeated prediction failures.
            suppression = min(0.85, local_contradiction_debt * 0.28)
            prediction_contradiction_scale = max(0.15, 1.0 - suppression)
            prediction_junction_bonus = int(round(prediction_junction_bonus * prediction_contradiction_scale))
            prediction_dead_end_penalty = int(round(prediction_dead_end_penalty * prediction_contradiction_scale))

        score -= prediction_junction_bonus
        score += prediction_dead_end_penalty
        prediction_lookahead_bonus = self._prediction_two_step_lookahead_bonus(origin, candidate)
        if prediction_used and prediction_contradiction_scale < 1.0:
            prediction_lookahead_bonus = int(round(prediction_lookahead_bonus * prediction_contradiction_scale))
        score -= prediction_lookahead_bonus
        contradiction_probe_bonus = 0
        if local_contradiction_debt > 0.0 and (unknown_neighbors > 0 or frontier_distance <= 1):
            contradiction_probe_bonus = min(18, int(round(local_contradiction_debt * 6.0)))
            score -= contradiction_probe_bonus
        # Stuck re-explore phase: amplify frontier-seeking and increase stochasticity
        # so the agent can break deterministic loop attractors.
        stuck_frontier_seek_bonus = 0
        stuck_uncertainty_probe_bonus = 0
        stuck_dead_end_penalty_relief = 0
        stuck_extra_noise = 0
        if self._maze_reexplore_cooldown_remaining > 0:
            if frontier_distance < origin_frontier_distance and frontier_distance >= 0:
                _stuck_depth = min(5, self._maze_stuck_trigger_count)
                stuck_frontier_seek_bonus = 28 + (_stuck_depth * 4)
                score -= stuck_frontier_seek_bonus
            if unknown_neighbors > 0 or frontier_distance <= 1:
                # Encourage direct verification of nearby ambiguous branches.
                stuck_uncertainty_probe_bonus = 14 + min(12, self._maze_stuck_trigger_count * 2)
                score -= stuck_uncertainty_probe_bonus
                # Temporarily relax part of dead-end revisit suppression while stuck,
                # but do not fully remove it.
                stuck_dead_end_penalty_relief = min(
                    revisit_dead_end_entrance_penalty + dead_end_tip_revisit_slap_penalty,
                    28,
                )
                score -= stuck_dead_end_penalty_relief
            stuck_extra_noise = decision_noise * 2
            score += stuck_extra_noise

        base_score_without_noise = score - decision_noise - stuck_extra_noise
        return {
            "score": score,
            "base_score_without_noise": base_score_without_noise,
            "blocked": False,
            "visits": visits,
            "backtrack": backtrack,
            "recent": recent_penalty,
            "recent_recency_penalty": recent_recency_penalty,
            "known": is_known,
            "known_dead_area": known_dead_area,
            "frontier_distance": frontier_distance,
            "corridor_commit": corridor_commit,
            "dead_end_risk_depth": dead_end_risk_depth,
            "dead_end_exp_penalty": dead_end_exp_penalty,
            "short_dead_end_penalty": short_dead_end_penalty,
            "revisit_dead_end_entrance_penalty": revisit_dead_end_entrance_penalty,
            "dead_end_end_slap_penalty": dead_end_end_slap_penalty,
            "dead_end_tip_revisit_slap_penalty": dead_end_tip_revisit_slap_penalty,
            "narrow_corridor_additive_penalty": narrow_corridor_additive_penalty,
            "dead_end_learning_grace": dead_end_learning_grace,
            "dead_end_allowance_remaining": dead_end_allowance_remaining,
            "attempt_dead_end_scale": round(attempt_dead_end_scale, 2),
            "edge_clear_run": int(edge_scan["clear_run"]),
            "edge_type": str(edge_scan["edge_type"]),
            "edge_frontier": effective_edge_frontier,
            "edge_junction": effective_edge_junction,
            "edge_exit_visible": bool(edge_scan["exit_visible"]),
            "edge_side_open_steps": int(edge_scan.get("side_open_steps", 0) or 0),
            "edge_side_blocked_steps": int(edge_scan.get("side_blocked_steps", 0) or 0),
            "visible_open_decision": effective_visible_open_decision,
            "visible_closed_structure": visible_closed_structure,
            "boundary_hug": boundary_hug,
            "visible_terminal_end_penalty": visible_terminal_end_penalty,
            "boxed_corridor_no_exit": boxed_corridor_no_exit,
            "boxed_corridor_penalty": boxed_corridor_penalty,
            "visible_exit_corridor": visible_exit_corridor,
            "visible_exit_reward": visible_exit_reward,
            "branch_diversity_penalty": branch_diversity_penalty,
            "seen_corridor_continue_penalty": seen_corridor_continue_penalty,
            "candidate_fully_known_current_maze": 1 if candidate_fully_known_current_maze else 0,
            "episodic_constraint_active": 1 if episodic_constraint_active else 0,
            "cross_maze_influence_allowed": 1 if cross_maze_influence_allowed else 0,
            "cross_maze_influence_factor": round(cross_maze_influence_factor, 3),
            "strict_risk_context": strict_risk_context,
            "strict_risk_memory_floor_applied": strict_risk_memory_floor_applied,
            "local_map_authority_mode": self.local_map_authority_mode,
            "local_map_authority_scale": round(local_map_authority_scale, 3),
            "episodic_exploration_locked": 1 if episodic_exploration_locked else 0,
            "episodic_relevance_penalty": episodic_relevance_penalty,
            "corridor_suppression_active": 1 if corridor_suppression_active else 0,
            "corridor_suppression_penalty": corridor_suppression_penalty,
            "recent_transition_count": recent_transition_count,
            "recent_reverse_transition_count": recent_reverse_transition_count,
            "transition_repeat_penalty": transition_repeat_penalty,
            "cycle_pair_penalty": cycle_pair_penalty,
            "stuck_transition_taboo_boost": stuck_transition_taboo_boost,
            "no_progress_repeat_penalty": no_progress_repeat_penalty,
            "loop_commitment_penalty": loop_commitment_penalty,
            "immediate_backtrack_hard_penalty": immediate_backtrack_hard_penalty,
            "transition_pressure_repeat_penalty": transition_pressure_repeat_penalty,
            "post_reset_exhaustion_penalty": post_reset_exhaustion_penalty,
            "reset_failure_transition_penalty": reset_failure_transition_penalty,
            "reset_failure_cell_penalty": reset_failure_cell_penalty,
            "reset_success_transition_bonus": reset_success_transition_bonus,
            "frontier_lock_active": 1 if frontier_lock_active else 0,
            "frontier_lock_progress_bonus": frontier_lock_progress_bonus,
            "frontier_lock_loop_penalty": frontier_lock_loop_penalty,
            "solved_region_penalty": solved_region_penalty,
            "move_entropy": move_entropy,
            "transition_pressure_bucket": transition_pressure_bucket,
            "forced_corridor_reentry_penalty": forced_corridor_reentry_penalty,
            "taboo_transition_penalty": taboo_transition_penalty,
            "terminal_hard_veto_penalty": terminal_hard_veto_penalty,
            "branch_tightening_score": branch_tightening_score,
            "branch_tightening_mode_active": 1 if branch_tightening_mode_active else 0,
            "branch_tightening_abort_penalty": branch_tightening_abort_penalty,
            "branch_tightening_escape_bonus": branch_tightening_escape_bonus,
            "recent_frontier_seen": 1 if recent_frontier_seen else 0,
            "high_risk_frontier_override_bonus": high_risk_frontier_override_bonus,
            "escape_bias_bonus": escape_bias_bonus,
            "bio_opening_bonus": effective_bio_opening_bonus,
            "bio_dead_end_escape_bonus": int(bio_nav["bio_dead_end_escape_bonus"]),
            "bio_novelty_bonus": effective_bio_novelty_bonus,
            "bio_corridor_flow_bonus": effective_bio_corridor_flow_bonus,
            "bio_dead_end_predictive_penalty": int(bio_nav["bio_dead_end_predictive_penalty"]),
            "bio_loop_risk_penalty": int(bio_nav["bio_loop_risk_penalty"]),
            "bio_opening_evidence": int(bio_nav["bio_opening_evidence"]),
            "endocrine_stress_penalty": endocrine_stress_penalty,
            "endocrine_fatigue_penalty": endocrine_fatigue_penalty,
            "endocrine_curiosity_bonus": effective_endocrine_curiosity_bonus,
            "endocrine_confidence_bonus": endocrine_confidence_bonus,
            "endocrine_momentum_bonus": endocrine_momentum_bonus,
            "endocrine_exploration_drive": round(endocrine_exploration_drive, 3),
            "endocrine_risk_aversion": round(endocrine_risk_aversion, 3),
            "endocrine_momentum": round(endocrine_momentum, 3),
            "cause_effect_memory_penalty": cause_effect_memory_penalty,
            "cause_effect_memory_reward": cause_effect_memory_reward,
            "cause_effect_retrieved_tags": ",".join(retrieved_cause_tags),
            "move_personality_bias": move_personality_bias,
            "decision_noise": decision_noise,
            "novelty_reward": novelty_reward,
            "unknown_neighbors": unknown_neighbors,
            "open_degree": open_degree,
            "forced_single_exit": 1 if forced_single_exit else 0,
            "prediction_junction_bonus": prediction_junction_bonus,
            "prediction_dead_end_penalty": prediction_dead_end_penalty,
            "prediction_junction_bonus_raw": raw_prediction_junction_bonus,
            "prediction_dead_end_penalty_raw": raw_prediction_dead_end_penalty,
            "prediction_contradiction_scale": round(prediction_contradiction_scale, 3),
            "prediction_context_trust": round(prediction_context_trust, 3),
            "prediction_effective_conf": round(prediction_effective_conf, 3),
            "prediction_lookahead_bonus": prediction_lookahead_bonus,
            "local_contradiction_debt": round(local_contradiction_debt, 3),
            "contradiction_probe_bonus": contradiction_probe_bonus,
            "stuck_frontier_seek_bonus": stuck_frontier_seek_bonus,
            "stuck_uncertainty_probe_bonus": stuck_uncertainty_probe_bonus,
            "stuck_dead_end_penalty_relief": stuck_dead_end_penalty_relief,
            "stuck_extra_noise": stuck_extra_noise,
            "prediction_used": 1 if prediction_used else 0,
        }

    def _known_corridor_commitment(self, origin: tuple[int, int], first_move: str) -> int:
        """Estimate how deep this move commits into a known straight corridor."""
        if first_move not in {"UP", "DOWN", "LEFT", "RIGHT"}:
            return 0
        max_probe = max(2, self.maze_fov_depth)
        prev = origin
        current = self._neighbor_for_move(origin, first_move)
        if current == origin or self._is_blocked_cell(current):
            return 0

        commitment = 0
        for _ in range(max_probe):
            if current not in self.maze_known_cells:
                break
            if self._unknown_neighbor_count(current) > 0:
                break

            neighbors = [n for n in self._traversable_neighbors(current) if n != prev]
            if len(neighbors) != 1:
                break

            nxt = neighbors[0]
            in_vec = (current[0] - prev[0], current[1] - prev[1])
            out_vec = (nxt[0] - current[0], nxt[1] - current[1])
            if in_vec != out_vec:
                break

            commitment += 1
            prev, current = current, nxt

        return commitment

    def _dead_end_risk_depth(self, origin: tuple[int, int], first_move: str) -> int:
        """Estimate deterministic commitment depth if the move funnels toward a known dead end."""
        if first_move not in {"UP", "DOWN", "LEFT", "RIGHT"}:
            return 0

        prev = origin
        current = self._neighbor_for_move(origin, first_move)
        if current == origin or self._is_blocked_cell(current):
            return 0

        depth = 0
        max_probe = max(4, self.maze_fov_depth + 3)
        for _ in range(max_probe):
            depth += 1
            if current not in self.maze_known_cells:
                # Unknown ahead means this is not a deterministic dead-end commitment.
                return 0
            if self._unknown_neighbor_count(current) > 0:
                return 0

            neighbors = [n for n in self._traversable_neighbors(current) if n != prev]
            if not neighbors:
                # Reached terminal known dead end.
                return depth
            if len(neighbors) > 1:
                # Junction means escape routes exist; risk not deterministic.
                return 0

            prev, current = current, neighbors[0]

        return 0

    def _format_exploration_candidates(self) -> str:
        lines: list[str] = []
        tie_order = {"UP": 0, "RIGHT": 1, "DOWN": 2, "LEFT": 3}
        breakdowns: dict[str, dict] = {}
        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            breakdowns[move] = self._exploration_move_breakdown(move)

        valid_ranked = [
            (move, b)
            for move, b in breakdowns.items()
            if not b["blocked"]
        ]
        valid_ranked.sort(key=lambda item: (item[1]["score"], tie_order.get(item[0], 9)))

        lines.append(
            (
                f"decision_context: step_idx={self.memory_step_index} player={self.current_player_cell} "
                f"facing={self.player_facing} noise_weight={self.decision_noise_weight} "
                f"tie_break=UP>RIGHT>DOWN>LEFT tie_random={self.exploration_randomize_ties} "
                f"tie_band={self.exploration_tie_band} "
                f"stuck_reexplore_cooldown={self._maze_reexplore_cooldown_remaining} "
                f"stuck_reexplore_triggers={self._maze_stuck_trigger_count} "
                f"model_assist_reliance={round(self.maze_model_assist_reliance, 3)} "
                f"model_assist_calls={self._maze_model_assist_calls_used}/{self.maze_model_assist_max_calls_per_episode} "
                f"model_assist_cooldown={self._maze_model_assist_cooldown_remaining} "
                f"reset_epoch={self.reset_epoch} resets={self.step_limit_reset_count} "
                f"same_maze_retries={self.same_maze_retry_count} active_retries={self._active_same_maze_retry_count()} "
                f"steps_since_reset={max(0, self.memory_step_index - self._last_step_reset_memory_step)} "
                f"stm_relax={self._post_reset_stm_relax_remaining} "
                f"frontier_target={self._persistent_frontier_target} "
                f"frontier_lock={1 if self._frontier_lock_active() else 0} "
                f"move_entropy={self._recent_move_direction_entropy()} "
                f"local_map_authority_mode={self.local_map_authority_mode} "
                f"blend={'continuous' if self.local_map_authority_mode == 'soft' else 'hard'} "
                f"soft_scale={round(self.local_map_authority_soft_scale, 3)}"
            )
        )
        if self.endocrine_enabled:
            hormone = self.endocrine.state()
            neural = self.endocrine.neural_state()
            lines.append(
                (
                    "endocrine: "
                    f"stress={hormone.get('stress', 0.0)} "
                    f"curiosity={hormone.get('curiosity', 0.0)} "
                    f"confidence={hormone.get('confidence', 0.0)} "
                    f"fatigue={hormone.get('fatigue', 0.0)} "
                    f"reward={hormone.get('reward', 0.0)} "
                    f"exploration_drive={neural.get('exploration_drive', 0.0)} "
                    f"risk_aversion={neural.get('risk_aversion', 0.0)} "
                    f"momentum={neural.get('momentum', 0.0)}"
                )
            )
            if self.endocrine_event_log:
                lines.append(f"endocrine_event_last: {self.endocrine_event_log[-1]}")
        if self.organism_control_enable:
            endocrine = self.organism_endocrine_state
            lines.append(
                (
                    "organism_control: "
                    f"policy={self.organism_control_state.current_policy} "
                    f"loop_suspected={self.organism_control_state.loop_suspected} "
                    f"dopamine={round(endocrine.dopamine, 3)} "
                    f"cortisol={round(endocrine.cortisol, 3)} "
                    f"serotonin={round(endocrine.serotonin, 3)} "
                    f"acetylcholine={round(endocrine.acetylcholine, 3)} "
                    f"norepinephrine={round(endocrine.norepinephrine, 3)} "
                    f"boredom={round(endocrine.boredom, 3)}"
                )
            )
            if self.organism_last_step_debug:
                lines.append(f"organism_last_step: {self.organism_last_step_debug}")
        personality = self.maze_personality or {}
        lines.append(
            (
                f"personality: {self.maze_personality_name} "
                f"dead_end_allowance={int(personality.get('dead_end_allowance', self.dead_end_learning_allowance_base))} "
                f"dead_end_learned={self.episode_dead_end_learn_events} "
                f"attempt={self.episode_maze_attempt_count} "
                f"attempt_dead_end_scale={round(self._attempt_dead_end_scale(), 2)} "
                f"novelty_scale={round(float(personality.get('novelty_reward_scale', 1.0)), 2)} "
                f"dead_end_scale={round(float(personality.get('dead_end_penalty_scale', 1.0)), 2)}"
            )
        )
        if valid_ranked:
            best_score = int(valid_ranked[0][1]["score"])
            tie_band = max(0, self.exploration_tie_band)
            near_best_live = [
                (move, int(b["score"]))
                for move, b in valid_ranked
                if int(b["score"]) <= best_score + tie_band
            ]
            near_best_live_compact = ",".join([f"{move}:{score}" for move, score in near_best_live])
            lines.append(
                (
                    f"planner_choice_live_scores: best={best_score} tie_band={tie_band} "
                    f"near_best=[{near_best_live_compact}]"
                )
            )
            if self._last_planner_choice_debug:
                lines.append(f"planner_choice_last_selection: {self._last_planner_choice_debug}")
            ranked_compact = ", ".join(
                [
                    (
                        f"{move}:{b['score']}"
                        f"(base={b.get('base_score_without_noise', b['score'])},noise={b.get('decision_noise', 0)})"
                    )
                    for move, b in valid_ranked
                ]
            )
            lines.append(f"ranked_moves: {ranked_compact}")
            if len(valid_ranked) >= 2:
                best_score = int(valid_ranked[0][1]["score"])
                second_score = int(valid_ranked[1][1]["score"])
                lines.append(f"best_margin_vs_second: {second_score - best_score}")

        for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
            b = breakdowns[move]
            if b["blocked"]:
                lines.append(f"{move}: blocked score=10000")
            else:
                lines.append(
                    (
                        f"{move}: score={b['score']} base_score={b.get('base_score_without_noise', b['score'])} "
                        f"visits={b['visits']} known={b['known']} "
                        f"backtrack={b['backtrack']} recent={b['recent']} dead_area={b['known_dead_area']} "
                        f"unknown_neighbors={b['unknown_neighbors']} frontier_dist={b['frontier_distance']} "
                        f"corridor_commit={b.get('corridor_commit', 0)} "
                        f"dead_end_depth={b.get('dead_end_risk_depth', 0)} "
                        f"dead_end_exp_penalty={b.get('dead_end_exp_penalty', 0)} "
                        f"short_dead_end_penalty={b.get('short_dead_end_penalty', 0)} "
                        f"revisit_dead_end_entrance_penalty={b.get('revisit_dead_end_entrance_penalty', 0)} "
                        f"dead_end_end_slap_penalty={b.get('dead_end_end_slap_penalty', 0)} "
                        f"dead_end_tip_revisit_slap_penalty={b.get('dead_end_tip_revisit_slap_penalty', 0)} "
                        f"narrow_corridor_additive_penalty={b.get('narrow_corridor_additive_penalty', 0)} "
                        f"dead_end_learning_grace={b.get('dead_end_learning_grace', 0)} "
                        f"dead_end_allowance_remaining={b.get('dead_end_allowance_remaining', 0)} "
                        f"attempt_dead_end_scale={b.get('attempt_dead_end_scale', 1.0)} "
                        f"edge={b.get('edge_type', 'n/a')} edge_run={b.get('edge_clear_run', 0)} "
                        f"edge_side_open_steps={b.get('edge_side_open_steps', 0)} "
                        f"edge_side_blocked_steps={b.get('edge_side_blocked_steps', 0)} "
                        f"visible_open_decision={b.get('visible_open_decision', 0)} "
                        f"visible_closed_structure={b.get('visible_closed_structure', 0)} "
                        f"candidate_fully_known_current_maze={b.get('candidate_fully_known_current_maze', 0)} "
                        f"episodic_constraint_active={b.get('episodic_constraint_active', 0)} "
                        f"cross_maze_influence_allowed={b.get('cross_maze_influence_allowed', 0)} "
                        f"cross_maze_influence_factor={b.get('cross_maze_influence_factor', 0.0)} "
                        f"local_map_authority_mode={b.get('local_map_authority_mode', 'strict')} "
                        f"local_map_authority_scale={b.get('local_map_authority_scale', 0.0)} "
                        f"episodic_exploration_locked={b.get('episodic_exploration_locked', 0)} "
                        f"episodic_relevance_penalty={b.get('episodic_relevance_penalty', 0)} "
                        f"branch_diversity_penalty={b.get('branch_diversity_penalty', 0)} "
                        f"seen_corridor_continue_penalty={b.get('seen_corridor_continue_penalty', 0)} "
                        f"visible_terminal_end_penalty={b.get('visible_terminal_end_penalty', 0)} "
                        f"transition_repeat_penalty={b.get('transition_repeat_penalty', 0)} "
                        f"cycle_pair_penalty={b.get('cycle_pair_penalty', 0)} "
                        f"no_progress_repeat_penalty={b.get('no_progress_repeat_penalty', 0)} "
                        f"loop_commitment_penalty={b.get('loop_commitment_penalty', 0)} "
                        f"immediate_backtrack_hard_penalty={b.get('immediate_backtrack_hard_penalty', 0)} "
                        f"transition_pressure_repeat_penalty={b.get('transition_pressure_repeat_penalty', 0)} "
                        f"frontier_lock_active={b.get('frontier_lock_active', 0)} "
                        f"frontier_lock_progress_bonus={b.get('frontier_lock_progress_bonus', 0)} "
                        f"frontier_lock_loop_penalty={b.get('frontier_lock_loop_penalty', 0)} "
                        f"solved_region_penalty={b.get('solved_region_penalty', 0)} "
                        f"move_entropy={b.get('move_entropy', 0.0)} "
                        f"endocrine_stress_penalty={b.get('endocrine_stress_penalty', 0)} "
                        f"endocrine_fatigue_penalty={b.get('endocrine_fatigue_penalty', 0)} "
                        f"endocrine_curiosity_bonus={b.get('endocrine_curiosity_bonus', 0)} "
                        f"endocrine_confidence_bonus={b.get('endocrine_confidence_bonus', 0)} "
                        f"endocrine_momentum_bonus={b.get('endocrine_momentum_bonus', 0)} "
                        f"endocrine_exploration_drive={b.get('endocrine_exploration_drive', 0.0)} "
                        f"endocrine_risk_aversion={b.get('endocrine_risk_aversion', 0.0)} "
                        f"endocrine_momentum={b.get('endocrine_momentum', 0.0)} "
                        f"cause_effect_memory_penalty={b.get('cause_effect_memory_penalty', 0)} "
                        f"cause_effect_memory_reward={b.get('cause_effect_memory_reward', 0)} "
                        f"cause_effect_retrieved_tags={b.get('cause_effect_retrieved_tags', '') or '(none)'} "
                        f"transition_count={b.get('recent_transition_count', 0)} "
                        f"reverse_transition_count={b.get('recent_reverse_transition_count', 0)} "
                        f"move_personality_bias={b.get('move_personality_bias', 0)} "
                        f"novelty_reward={b.get('novelty_reward', 0)} "
                        f"decision_noise={b.get('decision_noise', 0)} "
                        f"boundary_hug={b.get('boundary_hug', 0)} "
                        f"degree={b['open_degree']}"
                    )
                )
        return "\n".join(lines)

    def _start_auto_goal_session(self, total_hits: int, first_moves: list[str]) -> None:
        self.goal_session_active = True
        self.goal_session_start_hits = self.targets_reached
        self.goal_session_target_hits = max(1, total_hits)
        self.auto_goal_hits_remaining = self.goal_session_target_hits
        if first_moves:
            self._apply_agent_moves(first_moves)
        else:
            fallback_moves = self._shortest_path_moves_to_target()
            if fallback_moves:
                self._apply_agent_moves(fallback_moves)

    def _continue_auto_goal_session_if_needed(self) -> None:
        completed, remaining = self._goal_session_progress()
        self.auto_goal_hits_remaining = remaining
        if not self.goal_session_active or remaining <= 0:
            return
        next_moves = self._shortest_path_moves_to_target()
        if next_moves:
            self._apply_agent_moves(next_moves)

    def _apply_agent_moves(self, moves: list[str]) -> None:
        self.pending_agent_moves.extend(moves)
        if not self.agent_move_animation_active and self.pending_agent_moves:
            self.agent_move_animation_active = True
            self._animate_next_agent_move()

    def _animate_next_agent_move(self) -> None:
        if not self.pending_agent_moves:
            self.agent_move_animation_active = False
            return

        move = self.pending_agent_moves.pop(0)
        vectors = {
            "UP": (0, -self.player_speed),
            "DOWN": (0, self.player_speed),
            "LEFT": (-self.player_speed, 0),
            "RIGHT": (self.player_speed, 0),
        }
        dx, dy = vectors[move]
        self._move_player(dx, dy)
        self.root.after(self.move_delay_ms, self._animate_next_agent_move)

    def _init_game(self) -> None:
        self._draw_chessboard()
        self._generate_layout()
        self._draw_blockers()

        self.player = self.game_canvas.create_rectangle(
            self.player_x,
            self.player_y,
            self.player_x + self.player_size,
            self.player_y + self.player_size,
            fill="#1e1e1e",
            outline="",
        )
        if self._normalized_layout_mode() == "maze":
            self._place_player_at_cell(self.current_player_cell)
        self.target = self.game_canvas.create_oval(0, 0, 0, 0, fill="#227dff", outline="")
        self.start_marker = self.game_canvas.create_rectangle(0, 0, 0, 0, outline="#23a55a", width=3)
        self.start_label = self.game_canvas.create_text(0, 0, text="S", fill="#23a55a", font=("Helvetica", 10, "bold"))
        self.end_label = self.game_canvas.create_text(0, 0, text="E", fill="#ffffff", font=("Helvetica", 10, "bold"))
        self._spawn_target()
        self._refresh_game_state()

        self.game_canvas.bind("<Button-1>", lambda _event: self.game_canvas.focus_set())
        self.game_canvas.bind("<Up>", lambda _event: self._move_player(0, -self.player_speed))
        self.game_canvas.bind("<Down>", lambda _event: self._move_player(0, self.player_speed))
        self.game_canvas.bind("<Left>", lambda _event: self._move_player(-self.player_speed, 0))
        self.game_canvas.bind("<Right>", lambda _event: self._move_player(self.player_speed, 0))
        self.game_canvas.bind("<w>", lambda _event: self._move_player(0, -self.player_speed))
        self.game_canvas.bind("<s>", lambda _event: self._move_player(0, self.player_speed))
        self.game_canvas.bind("<a>", lambda _event: self._move_player(-self.player_speed, 0))
        self.game_canvas.bind("<d>", lambda _event: self._move_player(self.player_speed, 0))
        self.game_canvas.focus_set()

    def _cell_center(self, cell: tuple[int, int]) -> tuple[float, float]:
        row, col = cell
        center_x = col * self.cell_size + (self.cell_size / 2)
        center_y = row * self.cell_size + (self.cell_size / 2)
        return center_x, center_y

    def _update_start_end_markers(self) -> None:
        if not hasattr(self, "start_marker"):
            return

        start_row, start_col = self.episode_start_player_cell
        start_x1 = start_col * self.cell_size + 2
        start_y1 = start_row * self.cell_size + 2
        start_x2 = (start_col + 1) * self.cell_size - 2
        start_y2 = (start_row + 1) * self.cell_size - 2
        self.game_canvas.coords(self.start_marker, start_x1, start_y1, start_x2, start_y2)

        sx, sy = self._cell_center(self.episode_start_player_cell)
        self.game_canvas.coords(self.start_label, sx - (self.cell_size * 0.28), sy - (self.cell_size * 0.28))

        ex, ey = self._cell_center(self.current_target_cell)
        self.game_canvas.coords(self.end_label, ex, ey)
        self.game_canvas.tag_raise(self.target)
        self.game_canvas.tag_raise(self.end_label)
        self.game_canvas.tag_raise(self.player)

    def _draw_chessboard(self) -> None:
        self.game_canvas.delete("board")
        self.game_canvas.delete("fov")
        self.game_canvas.delete("sweep")
        light = "#f0f4ff"
        dark = "#dbe4ff"
        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                x1 = col * self.cell_size
                y1 = row * self.cell_size
                x2 = x1 + self.cell_size
                y2 = y1 + self.cell_size
                color = light if (row + col) % 2 == 0 else dark
                self.game_canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=color,
                    outline="#b6bfd3",
                    width=1,
                    tags="board",
                )

    def _clear_fov_overlay(self) -> None:
        self.game_canvas.delete("fov")

    def _clear_mental_sweep_overlay(self) -> None:
        self.game_canvas.delete("sweep")

    def _draw_mental_sweep_overlay(self, player_row: int, player_col: int) -> None:
        self._clear_mental_sweep_overlay()
        # Mental sweep remains for internal planning/debug only; visual overlay is
        # handled by _draw_fov_overlay to avoid painting non-visible cells.
        _ = (player_row, player_col)

    def _set_player_facing_from_move(self, move: str) -> None:
        if move == "UP":
            self.player_facing = "UP"
        elif move == "DOWN":
            self.player_facing = "DOWN"
        elif move == "LEFT":
            self.player_facing = "LEFT"
        elif move == "RIGHT":
            self.player_facing = "RIGHT"

    def _available_look_directions(self) -> list[str]:
        origin = self.current_player_cell
        directions: list[str] = []
        for move in ["UP", "RIGHT", "DOWN", "LEFT"]:
            nxt = self._neighbor_for_move(origin, move)
            if nxt != origin and not self._is_blocked_cell(nxt):
                directions.append(move)
        if not directions:
            if self.player_facing in {"UP", "RIGHT", "DOWN", "LEFT"}:
                return [self.player_facing]
            return ["UP"]
        return directions

    def _preview_look_directions_blocking(self, directions: list[str]) -> None:
        if self._normalized_layout_mode() != "maze":
            return
        if self.look_preview_delay_ms <= 0:
            return
        if not directions:
            return

        original_facing = self.player_facing
        self._clear_working_memory_look_sweep(keep_recent=False)
        self.working_memory_look_sweep_step = self.memory_step_index
        done = threading.Event()
        delay_ms = max(20, self.look_preview_delay_ms)

        def run_preview(index: int) -> None:
            if index >= len(directions):
                self.player_facing = original_facing
                self._refresh_game_state()
                done.set()
                return

            self.player_facing = directions[index]
            # Build a plain directional WM snapshot for this look angle.
            look_row, look_col = self.current_player_cell
            look_signature = self._current_pattern_signature(current_cell=(look_row, look_col))
            look_ascii = self._build_local_status_snapshot(
                look_row,
                look_col,
                radius=1,
                facing=self.player_facing,
            )
            self.working_memory_active = {
                "signature": look_signature,
                "ascii": look_ascii,
                "player_cell": str((look_row, look_col)),
            }
            self._capture_working_memory_look_snapshot(self.player_facing)
            self._refresh_game_state()
            self.root.after(delay_ms, lambda: run_preview(index + 1))

        self.root.after(0, lambda: run_preview(0))
        timeout_s = max(1.0, (len(directions) * delay_ms) / 1000.0 + 0.5)
        done.wait(timeout=timeout_s)

    def _draw_fov_overlay(self, player_row: int, player_col: int) -> None:
        self._clear_fov_overlay()
        if self._normalized_layout_mode() != "maze":
            return

        # Fill all currently visible cells in the active facing cone. Color
        # intensity reflects ray strength so around-corner grazes appear dimmer.
        inset = 1
        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                vis_kind = self._local_visibility_kind(
                    player_row,
                    player_col,
                    row,
                    col,
                    facing=self.player_facing,
                )
                if vis_kind == "none":
                    continue

                strength = self._visibility_strength(
                    player_row,
                    player_col,
                    row,
                    col,
                    facing=self.player_facing,
                )
                _los_clear, corner_graze_steps = self._line_of_sight_metrics(
                    player_row,
                    player_col,
                    row,
                    col,
                )
                fill_color = self._fov_fill_color(strength, vis_kind, corner_graze_steps)

                x1 = col * self.cell_size + inset
                y1 = row * self.cell_size + inset
                x2 = (col + 1) * self.cell_size - inset
                y2 = (row + 1) * self.cell_size - inset

                if vis_kind == "half" and row != player_row and col != player_col:
                    points = self._half_visible_triangle_points(
                        player_row,
                        player_col,
                        x1,
                        y1,
                        x2,
                        y2,
                        row,
                        col,
                        strength=strength,
                    )
                    self.game_canvas.create_polygon(
                        points,
                        fill=fill_color,
                        outline="",
                        tags="fov",
                    )
                else:
                    self.game_canvas.create_rectangle(
                        x1,
                        y1,
                        x2,
                        y2,
                        fill=fill_color,
                        outline="",
                        tags="fov",
                    )

        # Mark visible side edges along the projected beam corridor.
        for row, col, edge_move in self._visible_edge_opening_cells(player_row, player_col, self.player_facing):
            x1 = col * self.cell_size + inset
            y1 = row * self.cell_size + inset
            x2 = (col + 1) * self.cell_size - inset
            y2 = (row + 1) * self.cell_size - inset
            if edge_move == "UP":
                line = (x1, y1, x2, y1)
            elif edge_move == "DOWN":
                line = (x1, y2, x2, y2)
            elif edge_move == "LEFT":
                line = (x1, y1, x1, y2)
            else:
                line = (x2, y1, x2, y2)
            self.game_canvas.create_line(
                *line,
                fill="#23a55a",
                width=3,
                capstyle=tk.ROUND,
                tags="fov",
            )

        # Keep gameplay elements above overlay.
        self.game_canvas.tag_raise("blocker")
        if hasattr(self, "start_marker"):
            self.game_canvas.tag_raise(self.start_marker)
        if hasattr(self, "start_label"):
            self.game_canvas.tag_raise(self.start_label)
        if hasattr(self, "target"):
            self.game_canvas.tag_raise(self.target)
        if hasattr(self, "end_label"):
            self.game_canvas.tag_raise(self.end_label)
        if hasattr(self, "player"):
            self.game_canvas.tag_raise(self.player)

    def _fov_fill_color(self, strength: float, vis_kind: str, corner_graze_steps: int) -> str:
        # Strength-based palette gives a user-visible cue for light/vision attenuation.
        full_palette = ["#b9eec7", "#9fe5b1", "#86dd9b", "#6ed586"]
        half_palette = ["#d1f3db", "#c3efd2", "#b5ebc9", "#a7e7c0"]
        palette = half_palette if vis_kind == "half" else full_palette

        clamped = max(0.0, min(1.0, strength))
        idx = int(round(clamped * (len(palette) - 1)))
        # Corner-graze rays should appear dimmer than direct line-of-sight rays.
        idx = max(0, idx - max(0, corner_graze_steps))
        return palette[idx]

    def _draw_pseudo3d_view(self, player_row: int, player_col: int) -> None:
        if not hasattr(self, "pseudo3d_canvas"):
            return

        canvas = self.pseudo3d_canvas
        canvas.delete("all")
        w = float(self.pseudo3d_width)
        h = float(self.pseudo3d_height)
        horizon = h * 0.42

        # Sky and floor slabs establish the retro first-person atmosphere.
        canvas.create_rectangle(0, 0, w, horizon, fill="#1a223c", outline="")
        canvas.create_rectangle(0, horizon, w, h, fill="#201c14", outline="")

        max_depth = max(2, min(self.grid_cells, int(self.pseudo3d_max_depth)))
        fv_r, fv_c = self._facing_vector_for(self.player_facing)
        # Use screen-consistent side mapping so map-right appears on the right
        # side of POV for all facings (less ego-mirrored, more grid-consistent).
        left_wall_vec, right_wall_vec = self._pseudo3d_screen_side_vectors(self.player_facing)

        near_x = 12.0
        far_x = w * 0.45
        near_y = 10.0
        far_y = h * 0.41

        def frame_at(depth_idx: int) -> tuple[float, float, float, float]:
            t = max(0.0, min(1.0, depth_idx / float(max_depth)))
            # Non-linear interpolation gives stronger perspective compression at distance.
            ease = t ** 1.18
            inset_x = near_x + ((far_x - near_x) * ease)
            inset_y = near_y + ((far_y - near_y) * ease)
            return (inset_x, inset_y, w - inset_x, h - inset_y)

        frames = [frame_at(i) for i in range(max_depth + 1)]
        terminated = False
        debug_line = ""

        ceiling_palette = ["#32456f", "#2c3d63", "#263556", "#202c49", "#1b263e", "#172136"]
        floor_palette = ["#3a311f", "#332b1b", "#2c2518", "#261f15", "#201a12", "#1b160f"]
        wall_palette = ["#6f7791", "#656d87", "#5b627b", "#51586f", "#474e63", "#3f4558"]
        outline_palette = ["#8b95b2", "#8089a4", "#757f97", "#6a748a", "#5f697e", "#555f72"]

        # Perspective floor rails and center guide line reinforce motion/depth.
        vanishing_x = w / 2
        floor_y = h - 1
        far = frames[-1]
        canvas.create_line(vanishing_x, horizon + 4, vanishing_x, h, fill="#4b5267", width=1)
        canvas.create_line(vanishing_x, floor_y, far[0], far[3], fill="#4b3f2b", width=1)
        canvas.create_line(vanishing_x, floor_y, far[2], far[3], fill="#4b3f2b", width=1)

        for depth in range(1, max_depth + 1):
            near = frames[depth - 1]
            far = frames[depth]
            row = player_row + (fv_r * depth)
            col = player_col + (fv_c * depth)
            palette_idx = min(len(ceiling_palette) - 1, depth - 1)

            blocked_front = not self._pseudo3d_cell_traversable(row, col)
            left_cap_units = 0
            right_cap_units = 0
            if blocked_front:
                # Count contiguous open cells on the cap plane around the
                # blocked center cell. This drives cap opening widths.
                left_cap_units = self._pseudo3d_lateral_open_run(
                    row,
                    col,
                    left_wall_vec,
                    origin_row=player_row,
                    origin_col=player_col,
                    facing=self.player_facing,
                )
                right_cap_units = self._pseudo3d_lateral_open_run(
                    row,
                    col,
                    right_wall_vec,
                    origin_row=player_row,
                    origin_col=player_col,
                    facing=self.player_facing,
                )

            if blocked_front:
                left_open = left_cap_units > 0
                right_open = right_cap_units > 0
            else:
                left_row = row + left_wall_vec[0]
                left_col = col + left_wall_vec[1]
                right_row = row + right_wall_vec[0]
                right_col = col + right_wall_vec[1]
                left_open = self._pseudo3d_cell_traversable(left_row, left_col) and self._is_local_cell_visible(
                    player_row,
                    player_col,
                    left_row,
                    left_col,
                    facing=self.player_facing,
                )
                right_open = self._pseudo3d_cell_traversable(right_row, right_col) and self._is_local_cell_visible(
                    player_row,
                    player_col,
                    right_row,
                    right_col,
                    facing=self.player_facing,
                )
            left_closed = not left_open
            right_closed = not right_open
            debug_line = (
                f"d={depth} front_blocked={int(blocked_front)} "
                f"left_open={int(left_open)} right_open={int(right_open)} "
                f"capL={left_cap_units} capR={right_cap_units}"
            )

            # Ceiling and floor slices.
            canvas.create_polygon(
                near[0], near[1],
                near[2], near[1],
                far[2], far[1],
                far[0], far[1],
                fill=ceiling_palette[palette_idx],
                outline="",
            )
            canvas.create_polygon(
                near[0], near[3],
                near[2], near[3],
                far[2], far[3],
                far[0], far[3],
                fill=floor_palette[palette_idx],
                outline="",
            )

            if left_closed:
                canvas.create_polygon(
                    near[0], near[1],
                    near[0], near[3],
                    far[0], far[3],
                    far[0], far[1],
                    fill=wall_palette[palette_idx],
                    outline=outline_palette[palette_idx],
                    width=1,
                )
                # Subtle vertical groove lines for retro wall texture.
                span = max(8.0, near[3] - near[1])
                groove_step = max(7.0, span / 5.0)
                y = near[1] + groove_step
                while y < near[3]:
                    t = (y - near[1]) / max(1.0, (near[3] - near[1]))
                    x_near = near[0]
                    x_far = far[0]
                    y_far = far[1] + ((far[3] - far[1]) * t)
                    canvas.create_line(x_near, y, x_far, y_far, fill="#3a4155", width=1)
                    y += groove_step
            else:
                # Side opening portal hint (like old dungeon side passage peeks).
                canvas.create_polygon(
                    near[0], near[1],
                    near[0], near[3],
                    far[0], far[3],
                    far[0], far[1],
                    fill="#141a2b",
                    outline="#4d5a82",
                    width=1,
                )

            if right_closed:
                canvas.create_polygon(
                    near[2], near[1],
                    near[2], near[3],
                    far[2], far[3],
                    far[2], far[1],
                    fill=wall_palette[palette_idx],
                    outline=outline_palette[palette_idx],
                    width=1,
                )
                span = max(8.0, near[3] - near[1])
                groove_step = max(7.0, span / 5.0)
                y = near[1] + groove_step
                while y < near[3]:
                    t = (y - near[1]) / max(1.0, (near[3] - near[1]))
                    x_near = near[2]
                    x_far = far[2]
                    y_far = far[1] + ((far[3] - far[1]) * t)
                    canvas.create_line(x_near, y, x_far, y_far, fill="#3a4155", width=1)
                    y += groove_step
            else:
                canvas.create_polygon(
                    near[2], near[1],
                    near[2], near[3],
                    far[2], far[3],
                    far[2], far[1],
                    fill="#141a2b",
                    outline="#4d5a82",
                    width=1,
                )

            if (row, col) == self.current_target_cell and not blocked_front:
                cx = (far[0] + far[2]) / 2
                cy = (far[1] + far[3]) / 2
                radius = max(4.0, (far[2] - far[0]) * 0.13)
                canvas.create_oval(
                    cx - radius,
                    cy - radius,
                    cx + radius,
                    cy + radius,
                    fill="#34a4ff",
                    outline="#d6f0ff",
                    width=1,
                )
                canvas.create_line(
                    cx - (radius * 1.3),
                    cy,
                    cx + (radius * 1.3),
                    cy,
                    fill="#d6f0ff",
                    width=1,
                )
                canvas.create_line(
                    cx,
                    cy - (radius * 1.3),
                    cx,
                    cy + (radius * 1.3),
                    fill="#d6f0ff",
                    width=1,
                )

            if blocked_front:
                front_color = wall_palette[palette_idx]
                front_outline = outline_palette[palette_idx]

                wall_segments: list[tuple[float, float]] = []
                span = max(1.0, far[2] - far[0])
                if left_cap_units > 0 or right_cap_units > 0:
                    # Cap split is directly proportional to real open-cell
                    # counts on the blocked depth plane.
                    total_units = left_cap_units + 1 + right_cap_units
                    unit_width = span / float(max(1, total_units))
                    seg_left = far[0] + (left_cap_units * unit_width)
                    seg_right = seg_left + unit_width
                    wall_segments.append((seg_left, seg_right))
                else:
                    # No openings on this cap plane: full front wall.
                    wall_segments.append((far[0], far[2]))

                for seg_left, seg_right in wall_segments:
                    if seg_right - seg_left < 8.0:
                        # Avoid micro wall slivers that create visual artifacts.
                        continue
                    canvas.create_rectangle(
                        seg_left,
                        far[1],
                        seg_right,
                        far[3],
                        fill=front_color,
                        outline=front_outline,
                        width=2,
                    )
                    # Brick-like horizontal seams for the cap wall.
                    wall_h = max(1.0, far[3] - far[1])
                    seam_count = max(1, min(5, int(wall_h // 14)))
                    for seam in range(1, seam_count + 1):
                        y = far[1] + ((wall_h * seam) / (seam_count + 1))
                        canvas.create_line(seg_left + 3, y, seg_right - 3, y, fill="#4a5167", width=1)

                terminated = True
                break

            # Corridor frame lines at each depth ring for readable old-school layering.
            canvas.create_rectangle(
                far[0],
                far[1],
                far[2],
                far[3],
                outline="#556085",
                width=1,
            )

        if not terminated:
            far = frames[-1]
            canvas.create_rectangle(
                far[0],
                far[1],
                far[2],
                far[3],
                fill="#1f2230",
                outline="#3e4868",
                width=1,
            )

        canvas.create_text(
            8,
            8,
            anchor=tk.NW,
            fill="#b9c6ef",
            font=("Helvetica", 9, "bold"),
            text=f"Facing {self.player_facing} | depth {max_depth}",
        )
        if debug_line:
            canvas.create_text(
                8,
                24,
                anchor=tk.NW,
                fill="#8fa2d6",
                font=("Helvetica", 8),
                text=debug_line,
            )

    def _pseudo3d_cell_traversable(self, row: int, col: int) -> bool:
        if row < 0 or row >= self.grid_cells or col < 0 or col >= self.grid_cells:
            return False
        return (row, col) not in self.blocked_cells

    def _pseudo3d_screen_side_vectors(self, facing: str) -> tuple[tuple[int, int], tuple[int, int]]:
        facing_upper = (facing or "UP").strip().upper()
        if facing_upper in {"UP", "DOWN"}:
            return (0, -1), (0, 1)
        if facing_upper == "RIGHT":
            return (-1, 0), (1, 0)
        return (1, 0), (-1, 0)

    def _pseudo3d_lateral_open_run(
        self,
        row: int,
        col: int,
        vec: tuple[int, int],
        origin_row: int,
        origin_col: int,
        facing: str,
    ) -> int:
        count = 0
        max_scan = self.grid_cells
        for step in range(1, max_scan + 1):
            rr = row + (vec[0] * step)
            cc = col + (vec[1] * step)
            if not self._pseudo3d_cell_traversable(rr, cc):
                break
            if not self._is_local_cell_visible(origin_row, origin_col, rr, cc, facing=facing):
                break
            count += 1
        return count

    def _visible_edge_opening_cells(
        self,
        player_row: int,
        player_col: int,
        facing: str,
    ) -> list[tuple[int, int, str]]:
        fv_r, fv_c = self._facing_vector_for(facing)
        if facing in {"UP", "DOWN"}:
            side_specs = [((0, -1), "LEFT"), ((0, 1), "RIGHT")]
        else:
            side_specs = [((-1, 0), "UP"), ((1, 0), "DOWN")]

        edges: list[tuple[int, int, str]] = []
        seen_edges: set[tuple[int, int, str]] = set()

        for step in range(1, self.grid_cells + 1):
            row = player_row + (fv_r * step)
            col = player_col + (fv_c * step)
            if row < 0 or row >= self.grid_cells or col < 0 or col >= self.grid_cells:
                break
            if not self._is_local_cell_visible(player_row, player_col, row, col, facing=facing):
                break
            if self._is_blocked_cell((row, col)):
                break

            for (sv_r, sv_c), side_name in side_specs:
                side_row = row + sv_r
                side_col = col + sv_c
                side_in_bounds = 0 <= side_row < self.grid_cells and 0 <= side_col < self.grid_cells
                side_visible = (
                    side_in_bounds
                    and self._is_local_cell_visible(player_row, player_col, side_row, side_col, facing=facing)
                )
                side_blocked = (not side_in_bounds) or self._is_blocked_cell((side_row, side_col))
                # Record both visible lateral openings and blocked lateral boundaries.
                if side_visible or side_blocked:
                    edge = (row, col, side_name)
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        edges.append(edge)

        return edges

    def _half_visible_triangle_points(
        self,
        player_row: int,
        player_col: int,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        row: int,
        col: int,
        strength: float = 0.0,
    ) -> list[int]:
        dr = row - player_row
        dc = col - player_col
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        # 2D projection-style boundary slice: not fixed 45deg. Stronger cells get
        # a wider visible slice, weaker peripheral cells get a thinner slice.
        base_ratio = 0.34 + (0.36 * max(0.0, min(1.0, strength)))
        distance = math.hypot(dr, dc)
        depth_norm = min(1.0, max(0.0, (distance - 1.0) / max(1.0, float(self.maze_fov_depth))))
        distance_taper = 1.0 - (max(0.0, self.maze_fov_wedge_distance_scale) * depth_norm)
        cut_ratio = max(0.2, min(0.82, base_ratio * distance_taper))
        cut_px_x = max(1, min(width - 1, int(round(width * cut_ratio))))
        cut_px_y = max(1, min(height - 1, int(round(height * cut_ratio))))

        if dr < 0 and dc > 0:  # up-right
            return [x1, y2, x1, y1 + cut_px_y, x1 + cut_px_x, y2]
        if dr < 0 and dc < 0:  # up-left
            return [x2, y2, x2, y1 + cut_px_y, x2 - cut_px_x, y2]
        if dr > 0 and dc > 0:  # down-right
            return [x1, y1, x1 + cut_px_x, y1, x1, y1 + cut_px_y]
        # down-left (default)
        return [x2, y1, x2 - cut_px_x, y1, x2, y1 + cut_px_y]

    def _normalized_layout_mode(self) -> str:
        mode = (self.layout_mode.get() or "grid").strip().lower()
        if mode not in {"grid", "maze"}:
            mode = "grid"
            self.layout_mode.set(mode)
        return mode

    def _normalized_maze_difficulty(self) -> str:
        difficulty = (self.maze_difficulty.get() or "medium").strip().lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
            self.maze_difficulty.set(difficulty)
        return difficulty

    def _maze_map_id_for_generation(self, advance: bool) -> int:
        if advance:
            return max(0, int(self.layout_generation_index))
        # When advance is disabled, regenerate the active map id, not the next one.
        return max(0, int(self.layout_generation_index) - 1)

    def _maze_start_anchor_cell(self, map_id: int, difficulty: str) -> tuple[int, int]:
        diff_offset = {"easy": 10, "medium": 20, "hard": 30}.get(difficulty, 20)
        seed = self.maze_seed_base + 700_000 + (int(map_id) * 37) + diff_offset
        rng = random.Random(seed)
        return (rng.randrange(self.grid_cells), rng.randrange(self.grid_cells))

    def _maze_layout_rng(self, advance: bool = True) -> random.Random:
        mode_offset = 1000 if self._normalized_layout_mode() == "maze" else 0
        diff = self._normalized_maze_difficulty()
        diff_offset = {"easy": 10, "medium": 20, "hard": 30}.get(diff, 20)
        map_id = self._maze_map_id_for_generation(advance)
        seed = self.maze_seed_base + map_id + mode_offset + diff_offset
        if advance:
            self.layout_generation_index = map_id + 1
        return random.Random(seed)

    def _event_rng(self) -> random.Random:
        mode_offset = 1000 if self._normalized_layout_mode() == "maze" else 0
        diff = self._normalized_maze_difficulty()
        diff_offset = {"easy": 10, "medium": 20, "hard": 30}.get(diff, 20)
        seed = self.maze_seed_base + 100_000 + self.layout_event_index + mode_offset + diff_offset
        self.layout_event_index += 1
        return random.Random(seed)

    def _current_maze_map_id(self) -> int:
        # layout_generation_index advances immediately after generation.
        return max(0, self.layout_generation_index - 1)

    def _sync_maze_start_number_to_current(self) -> None:
        self.maze_map_start_var.set(str(self._current_maze_map_id()))

    def _open_cells(self) -> list[tuple[int, int]]:
        return [
            (row, col)
            for row in range(self.grid_cells)
            for col in range(self.grid_cells)
            if (row, col) not in self.blocked_cells
        ]

    def _random_open_cell(
        self,
        rng: random.Random,
        exclude: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        open_cells = [cell for cell in self._open_cells() if cell != exclude]
        if not open_cells:
            if exclude is not None:
                return exclude
            return (0, 0)
        return rng.choice(open_cells)

    def _generate_blockers(self, protected_cell: tuple[int, int] | None = None) -> None:
        self.blocked_cells = set()
        density = min(0.42, max(0.08, self.blocker_density))
        if protected_cell is None:
            protected_cell = self.current_player_cell if self.current_player_cell else (0, 0)
        for row in range(self.grid_cells):
            for col in range(self.grid_cells):
                if (row, col) == protected_cell:
                    continue
                if random.random() < density:
                    self.blocked_cells.add((row, col))

    def _generate_maze_blockers(
        self,
        protected_cell: tuple[int, int] | None,
        difficulty: str,
        rng: random.Random,
    ) -> None:
        algorithm = self._maze_algorithm_for_difficulty(difficulty, rng)
        self.current_maze_algorithm = algorithm

        if algorithm == "recursive_division":
            self.blocked_cells = self._recursive_division_blockers(protected_cell, rng)
            return

        all_cells = {
            (row, col)
            for row in range(self.grid_cells)
            for col in range(self.grid_cells)
        }
        self.blocked_cells = set(all_cells)

        nodes = self._maze_node_cells()
        for node in nodes:
            self.blocked_cells.discard(node)

        if algorithm == "prim_kruskal":
            edges = self._maze_edges_prim_kruskal_variant(nodes, rng)
        elif algorithm == "aldous_broder":
            edges = self._maze_edges_aldous_broder(nodes, rng)
        else:
            edges = self._maze_edges_dfs_backtracker(nodes, rng)

        for a, b in edges:
            mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
            self.blocked_cells.discard(mid)

        # Controlled loop carving keeps mazes traversable while preserving each algorithm style.
        _, loop_chance = self._maze_profile()
        for row in range(1, self.grid_cells - 1):
            for col in range(1, self.grid_cells - 1):
                if (row, col) in self.blocked_cells and rng.random() < loop_chance:
                    self.blocked_cells.discard((row, col))

        # Collapse wide-open pockets into tighter single-cell corridors.
        self._narrow_wide_openings(difficulty, protected_cell, rng)

        if protected_cell is not None:
            self.blocked_cells.discard(protected_cell)

    def _generate_layout(
        self,
        protected_cell: tuple[int, int] | None = None,
        advance_maze_sequence: bool = True,
    ) -> None:
        self._apply_grid_profile()
        mode = self._normalized_layout_mode()
        self._reset_maze_known_map()
        if mode != "maze":
            self.current_maze_algorithm = ""
            self._clear_working_memory()
        if mode == "maze":
            difficulty = self._normalized_maze_difficulty()
            map_id = self._maze_map_id_for_generation(advance_maze_sequence)
            start_anchor = self._maze_start_anchor_cell(map_id, difficulty)
            self._generate_maze_blockers(
                start_anchor,
                difficulty,
                self._maze_layout_rng(advance=advance_maze_sequence),
            )
            # Episode id should identify the current maze layout, not target respawns.
            self.current_maze_episode_id = self._current_maze_map_id()
            self.current_player_cell = start_anchor
            self._load_layout_cell_memory_snapshot()
            if hasattr(self, "player"):
                self._place_player_at_cell(start_anchor)
            return
        if protected_cell is not None:
            protected_cell = self._sanitize_cell(protected_cell)
        elif self.current_player_cell:
            protected_cell = self._sanitize_cell(self.current_player_cell)
        self._generate_blockers(protected_cell=protected_cell)

    def _carve_path_between_cells(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        rng: random.Random | None = None,
    ) -> None:
        if rng is None:
            rng = random.Random()
        if start == target:
            self.blocked_cells.discard(start)
            return

        row, col = start
        target_row, target_col = target
        self.blocked_cells.discard((row, col))
        self.blocked_cells.discard((target_row, target_col))

        while (row, col) != (target_row, target_col):
            row_delta = target_row - row
            col_delta = target_col - col

            take_row = row_delta != 0 and (col_delta == 0 or rng.random() < 0.55)
            if take_row:
                row += 1 if row_delta > 0 else -1
            else:
                col += 1 if col_delta > 0 else -1

            row = min(self.grid_cells - 1, max(0, row))
            col = min(self.grid_cells - 1, max(0, col))
            self.blocked_cells.discard((row, col))

    def _draw_blockers(self) -> None:
        self.game_canvas.delete("blocker")
        inset = max(3, int(self.cell_size * 0.14))
        for row, col in self.blocked_cells:
            x1 = col * self.cell_size + inset
            y1 = row * self.cell_size + inset
            x2 = (col + 1) * self.cell_size - inset
            y2 = (row + 1) * self.cell_size - inset
            self.game_canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                fill="#7b879f",
                outline="#5f6980",
                width=1,
                tags="blocker",
            )

    def _reachable_cells_from_player(self) -> set[tuple[int, int]]:
        start = self.current_player_cell if self.current_player_cell else self._player_cell()
        if self._is_blocked_cell(start):
            return set()
        seen = {start}
        queue: deque[tuple[int, int]] = deque([start])
        while queue:
            cell = queue.popleft()
            for move in ["UP", "DOWN", "LEFT", "RIGHT"]:
                nxt = self._neighbor_for_move(cell, move)
                if nxt == cell or nxt in seen or self._is_blocked_cell(nxt):
                    continue
                seen.add(nxt)
                queue.append(nxt)
        return seen

    def _place_player_at_cell(self, cell: tuple[int, int]) -> None:
        row, col = cell
        offset = (self.cell_size - self.player_size) / 2
        x1 = col * self.cell_size + offset
        y1 = row * self.cell_size + offset
        self.game_canvas.coords(
            self.player,
            x1,
            y1,
            x1 + self.player_size,
            y1 + self.player_size,
        )

    def _random_cell(self) -> tuple[int, int]:
        rng = self._event_rng()
        return (
            rng.randint(0, self.grid_cells - 1),
            rng.randint(0, self.grid_cells - 1),
        )

    def _regenerate_blockers(self) -> None:
        self._generate_layout(protected_cell=self._player_cell())
        self._draw_blockers()
        self.pending_agent_moves = []
        self.agent_move_animation_active = False
        self._spawn_target()
        mode = self._normalized_layout_mode()
        if mode == "maze":
            self._sync_maze_start_number_to_current()
            self.status_var.set(
                "Generated new deterministic maze "
                f"(map_id={self._current_maze_map_id()}, "
                f"{self._normalized_maze_difficulty()}, algo={self.current_maze_algorithm})"
            )
        else:
            self.status_var.set("Generated new low-noise blockers")

    def _next_maze_layout(self) -> None:
        if self._normalized_layout_mode() != "maze":
            self.status_var.set("Next Maze is available in maze mode only")
            return

        self.pending_agent_moves = []
        self.agent_move_animation_active = False
        self._generate_layout(protected_cell=self._player_cell())
        self._draw_blockers()
        self._spawn_target()
        self._refresh_memory_viewer()
        self._sync_maze_start_number_to_current()
        self.status_var.set(
            "Loaded next deterministic maze "
            f"(map_id={self._current_maze_map_id()}, "
            f"{self._normalized_maze_difficulty()}, algo={self.current_maze_algorithm})"
        )

    def _set_maze_start_number(self) -> None:
        if self._normalized_layout_mode() != "maze":
            self.status_var.set("Set Start is available in maze mode only")
            return

        raw_value = (self.maze_map_start_var.get() or "").strip()
        try:
            absolute_index = int(raw_value)
        except ValueError:
            self.status_var.set("Start # must be a whole number >= 0")
            return
        if absolute_index < 0:
            self.status_var.set("Start # must be >= 0")
            return

        self.layout_generation_index = absolute_index
        self.pending_agent_moves = []
        self.agent_move_animation_active = False
        self._generate_layout(protected_cell=self._player_cell())
        self._draw_blockers()
        self._spawn_target()
        self._refresh_memory_viewer()
        self._sync_maze_start_number_to_current()
        self.status_var.set(
            "Set deterministic maze start "
            f"(map_id={self._current_maze_map_id()}, "
            f"{self._normalized_maze_difficulty()}, algo={self.current_maze_algorithm})"
        )

    def _on_layout_settings_changed(self, _value: str | None = None) -> None:
        self.pending_agent_moves = []
        self.agent_move_animation_active = False
        mode = self._normalized_layout_mode()
        difficulty = self._normalized_maze_difficulty()
        self._generate_layout(protected_cell=self._player_cell())
        self.game_canvas.config(width=self.canvas_width, height=self.canvas_height)
        self._draw_blockers()
        self._spawn_target()
        self._refresh_memory_viewer()
        self._save_window_geometry()
        if mode == "maze":
            self._sync_maze_start_number_to_current()
            self.status_var.set(
                f"Mode set to maze ({difficulty}, {self.grid_cells}x{self.grid_cells}, algo={self.current_maze_algorithm})"
            )
        else:
            self.status_var.set(f"Mode set to grid ({self.grid_cells}x{self.grid_cells})")

    def _spawn_target(self) -> None:
        self._clear_sticky_objective_path()
        px1, py1, px2, py2 = self.game_canvas.coords(self.player)
        player_col = min(self.grid_cells - 1, max(0, int(((px1 + px2) / 2) / self.cell_size)))
        player_row = min(self.grid_cells - 1, max(0, int(((py1 + py2) / 2) / self.cell_size)))
        rng = self._event_rng()

        self.current_player_cell = (player_row, player_col)
        reachable = self._reachable_cells_from_player()
        available = [cell for cell in reachable if cell != (player_row, player_col)]
        if not available:
            # Ensure target always spawns on a reachable, non-blocked cell.
            for _ in range(8):
                self._generate_layout(
                    protected_cell=(player_row, player_col),
                    advance_maze_sequence=False,
                )
                self._draw_blockers()
                reachable = self._reachable_cells_from_player()
                available = [cell for cell in reachable if cell != (player_row, player_col)]
                if available:
                    break
        if not available:
            all_cells = [
                (row, col)
                for row in range(self.grid_cells)
                for col in range(self.grid_cells)
                if not (row == player_row and col == player_col)
            ]
            forced_target = rng.choice(all_cells)
            self._carve_path_between_cells((player_row, player_col), forced_target, rng=rng)
            self._draw_blockers()
            reachable = self._reachable_cells_from_player()
            available = [cell for cell in reachable if cell != (player_row, player_col)]
            if not available:
                self.blocked_cells = set()
                self._draw_blockers()
                available = all_cells

        target_cell: tuple[int, int] | None = None
        if self._normalized_layout_mode() == "maze":
            target_cell = self._deterministic_maze_target_cell((player_row, player_col), available)

        if target_cell is None:
            distance_map = self._distance_map_from_cell((player_row, player_col))
            max_distance = max((distance_map.get(cell, 0) for cell in available), default=0)
            min_distance, max_distance_allowed = self._target_distance_band(max_distance)
            eligible = [
                cell
                for cell in available
                if min_distance <= distance_map.get(cell, 0) <= max_distance_allowed
            ]
            if eligible:
                spawn_pool = eligible
            else:
                # Graceful fallback: pick among the farthest reachable cells.
                if distance_map:
                    max_distance = max(distance_map.get(cell, 0) for cell in available)
                    spawn_pool = [cell for cell in available if distance_map.get(cell, 0) == max_distance]
                else:
                    spawn_pool = available
            target_cell = rng.choice(spawn_pool)

        target_row, target_col = target_cell
        self.current_target_cell = (target_row, target_col)
        self.episode_start_player_cell = (player_row, player_col)
        self.episode_optimal_steps = self._distance_between_cells((player_row, player_col), (target_row, target_col))
        safety_margin = self._maze_safety_margin() if self._normalized_layout_mode() == "maze" else 8
        self.episode_step_limit = self.episode_optimal_steps + safety_margin
        self.episode_steps = 0
        self.episode_revisit_steps = 0
        self.episode_backtracks = 0
        self.episode_dead_end_learn_events = 0
        self.episode_dead_end_samples = set()
        self.episode_dead_end_entrances = set()
        self.episode_dead_end_tip_cells = set()
        self.episode_maze_attempt_count = 1
        if self._normalized_layout_mode() == "maze":
            self._reset_organism_control_state()
        if self._normalized_layout_mode() == "maze":
            self._roll_maze_personality()
        self.maze_recent_transitions.clear()
        self.recent_forced_corridor_cells.clear()
        self.episode_visited_cells = {(player_row, player_col): 1}
        self.prev_player_cell = (player_row, player_col)
        self.prev_prev_player_cell = (player_row, player_col)
        x = target_col * self.cell_size + (self.cell_size / 2)
        y = target_row * self.cell_size + (self.cell_size / 2)
        self.game_canvas.coords(
            self.target,
            x - self.target_radius,
            y - self.target_radius,
            x + self.target_radius,
            y + self.target_radius,
        )
        self._store_structural_memory_snapshot()
        self._update_start_end_markers()
        # Immediately refresh state so models always receive latest coordinates after every target move.
        self._refresh_game_state()

    def _move_player(self, dx: int, dy: int) -> None:
        x1, y1, x2, y2 = self.game_canvas.coords(self.player)
        old_cell = self.current_player_cell
        move_dir = ""
        if dy < 0:
            move_dir = "UP"
        elif dy > 0:
            move_dir = "DOWN"
        elif dx < 0:
            move_dir = "LEFT"
        elif dx > 0:
            move_dir = "RIGHT"
        new_x1 = min(max(0, x1 + dx), self.canvas_width - self.player_size)
        new_y1 = min(max(0, y1 + dy), self.canvas_height - self.player_size)

        new_center_x = new_x1 + (self.player_size / 2)
        new_center_y = new_y1 + (self.player_size / 2)
        new_cell = self._cell_from_center(new_center_x, new_center_y)

        if self._is_blocked_cell(new_cell):
            self._record_action_outcome_memory(
                action_taken=f"MOVE_{move_dir or 'UNKNOWN'}",
                outcome_value=-8.0,
                reward_signal=0.0,
                penalty_signal=8.0,
                reason_tags=["blocked_cell"],
                details={"reason": "blocked_cell", "from_cell": old_cell, "to_cell": new_cell},
                player_cell=old_cell,
            )
            self._refresh_game_state()
            return

        if new_x1 != x1 or new_y1 != y1:
            self.episode_steps += 1
            self.memory_step_index += 1
            if dy < 0:
                self._set_player_facing_from_move("UP")
            elif dy > 0:
                self._set_player_facing_from_move("DOWN")
            elif dx < 0:
                self._set_player_facing_from_move("LEFT")
            elif dx > 0:
                self._set_player_facing_from_move("RIGHT")

        if new_cell != old_cell:
            if self._sticky_objective_path:
                if move_dir and self._sticky_objective_path[0] == move_dir:
                    self._sticky_objective_path = self._sticky_objective_path[1:]
                    if not self._sticky_objective_path:
                        self._clear_sticky_objective_path()
                else:
                    self._clear_sticky_objective_path()
            if self._normalized_layout_mode() == "maze":
                self.maze_recent_cells.append(new_cell)
                self.maze_recent_transitions.append((old_cell, new_cell))
                if move_dir:
                    sampled_depth = self._dead_end_risk_depth(old_cell, move_dir)
                    if sampled_depth > 0 and new_cell not in self.episode_dead_end_samples:
                        self.episode_dead_end_entrances.add(old_cell)
                        self.episode_dead_end_samples.add(new_cell)
                        self.episode_dead_end_learn_events += 1
                    else:
                        # Also learn from visible terminal/boxed corridors even when
                        # the full branch is not yet map-known.
                        visibly_risky = (
                            self._is_move_visibly_terminal_dead_end(old_cell, move_dir)
                            or self._is_move_visibly_boxed_corridor_without_exit(old_cell, move_dir)
                        )
                        if visibly_risky:
                            if old_cell not in self.episode_dead_end_entrances:
                                self.episode_dead_end_entrances.add(old_cell)
                            if new_cell not in self.episode_dead_end_tip_cells:
                                self.episode_dead_end_tip_cells.add(new_cell)
                                self.episode_dead_end_learn_events += 1
                # Hard dead-end learning: if we step into a narrow end-corridor
                # (tip or pre-tip), tag it so revisits are strongly suppressed.
                if new_cell != self.current_target_cell:
                    new_unknown_neighbors = self._unknown_neighbor_count(new_cell)
                    new_open_degree = len(self._traversable_neighbors(new_cell))
                    if new_unknown_neighbors <= 1 and new_open_degree <= 1:
                        if new_cell not in self.episode_dead_end_tip_cells:
                            self.episode_dead_end_tip_cells.add(new_cell)
                            self.episode_dead_end_learn_events += 1
                        self.episode_dead_end_entrances.add(old_cell)
            visits = self.episode_visited_cells.get(new_cell, 0)
            if visits > 0:
                self.episode_revisit_steps += 1
            if new_cell == self.prev_prev_player_cell:
                self.episode_backtracks += 1
            self.episode_visited_cells[new_cell] = visits + 1
            self._cell_visit_reset_epoch[new_cell] = int(self.reset_epoch)
            self.prev_prev_player_cell = self.prev_player_cell
            self.prev_player_cell = new_cell

        self.game_canvas.coords(
            self.player,
            new_x1,
            new_y1,
            new_x1 + self.player_size,
            new_y1 + self.player_size,
        )
        self._refresh_game_state()
        captured = self._check_collision()
        if captured:
            return

        if (
            self._normalized_layout_mode() == "maze"
            and self.maze_step_limit_reset_enable
            and self.episode_step_limit > 0
        ):
            if self.episode_steps >= self.episode_step_limit:
                self.pending_agent_moves = []
                self.agent_move_animation_active = False
                self._clear_sticky_objective_path()
                self._capture_post_reset_learning()
                self.step_limit_reset_count += 1
                self.same_maze_retry_count += 1
                self.reset_epoch += 1
                self._last_step_reset_memory_step = int(self.memory_step_index)
                self._same_maze_retry_last_step = int(self.memory_step_index)
                self._same_maze_retry_frontier_target = self._select_persistent_frontier_target()
                self._post_reset_stm_relax_remaining = int(self.post_reset_stm_relax_steps)
                self.episode_maze_attempt_count += 1
                preserve_retry_memory = not self.reset_maze_knowledge_on_step_limit
                if self.reset_maze_knowledge_on_step_limit:
                    # Treat step-limit timeout as a fresh exploration episode.
                    self._clear_working_memory()
                    self._reset_maze_known_map()
                    self._reset_organism_control_state()
                self._place_player_at_cell(self.episode_start_player_cell)
                self.current_player_cell = self.episode_start_player_cell
                self.prev_player_cell = self.episode_start_player_cell
                self.prev_prev_player_cell = self.episode_start_player_cell
                if preserve_retry_memory and self._same_maze_retry_frontier_target is not None:
                    self._persistent_frontier_target = self._same_maze_retry_frontier_target
                if not preserve_retry_memory:
                    self.maze_recent_transitions.clear()
                    self.recent_forced_corridor_cells.clear()
                self.episode_steps = 0
                self.episode_revisit_steps = 0
                self.episode_backtracks = 0
                # Keep learned dead-end entrances within the same maze so retries
                # do not repeatedly commit to the exact same shallow traps.
                self._roll_maze_personality()
                if preserve_retry_memory:
                    start_visits = self.episode_visited_cells.get(self.episode_start_player_cell, 0)
                    self.episode_visited_cells[self.episode_start_player_cell] = start_visits + 1
                else:
                    self.episode_visited_cells = {self.episode_start_player_cell: 1}
                self._cell_visit_reset_epoch[self.episode_start_player_cell] = int(self.reset_epoch)
                self._record_action_outcome_memory(
                    action_taken="STEP_LIMIT_RESET",
                    outcome_value=-25.0,
                    reward_signal=0.0,
                    penalty_signal=25.0,
                    reason_tags=["step_limit", "timeout_reset"],
                    details={
                        "episode_step_limit": self.episode_step_limit,
                        "attempt": self.episode_maze_attempt_count,
                        "knowledge_reset": bool(self.reset_maze_knowledge_on_step_limit),
                    },
                    player_cell=self.episode_start_player_cell,
                )
                self._maze_timeout_reset_pulse = True
                self._refresh_game_state()
                if self.reset_maze_knowledge_on_step_limit:
                    self.status_var.set(
                        "Step limit reached: returned to start "
                        f"(attempt {self.episode_maze_attempt_count}, knowledge reset)"
                    )
                else:
                    self.status_var.set(
                        f"Step limit reached: returned to start (attempt {self.episode_maze_attempt_count})"
                    )

    def _check_collision(self) -> bool:
        player_coords = self.game_canvas.coords(self.player)
        target_coords = self.game_canvas.coords(self.target)
        overlap = not (
            player_coords[2] < target_coords[0]
            or player_coords[0] > target_coords[2]
            or player_coords[3] < target_coords[1]
            or player_coords[1] > target_coords[3]
        )
        if overlap:
            self.targets_reached += 1
            self.last_maze_solve_attempts = self.episode_maze_attempt_count
            if self._normalized_layout_mode() == "maze":
                # Persist complete deterministic layout at solve time so exact-map
                # revisits can hydrate a full known map immediately.
                self._store_complete_layout_cell_memory_snapshot()
            if self.episode_steps > 0:
                efficiency = min(1.0, self.episode_optimal_steps / self.episode_steps)
            else:
                efficiency = 1.0
            base_reward = 100.0 * efficiency
            repeat_penalty = (
                self.episode_revisit_steps * self.revisit_penalty_weight
                + self.episode_backtracks * self.backtrack_penalty_weight
            )
            reward = round(max(0.0, base_reward - repeat_penalty), 2)
            self.total_reward += reward
            self._record_action_outcome_memory(
                action_taken="CAPTURE_TARGET",
                outcome_value=float(reward),
                reward_signal=float(reward),
                penalty_signal=0.0,
                reason_tags=["target_capture", "efficiency_reward"],
                details={
                    "reward": reward,
                    "base_reward": round(base_reward, 2),
                    "repeat_penalty": round(repeat_penalty, 2),
                    "episode_steps": self.episode_steps,
                    "episode_optimal_steps": self.episode_optimal_steps,
                },
                player_cell=self.current_player_cell,
            )
            self._update_score_label()

            rng = self._event_rng()
            self.pending_agent_moves = []
            self.agent_move_animation_active = False
            self._generate_layout(protected_cell=self.current_player_cell)
            self._draw_blockers()
            new_player_cell = self._random_open_cell(rng)
            self._place_player_at_cell(new_player_cell)
            self.current_player_cell = new_player_cell
            self._spawn_target()

            completed, remaining = self._goal_session_progress()
            self.auto_goal_hits_remaining = remaining

            if self.goal_session_active and remaining > 0:
                self.status_var.set(
                    "Auto-run: "
                    f"{remaining} target hits remaining "
                    f"(completed {completed}/{self.goal_session_target_hits}, "
                    f"last maze attempts={self.last_maze_solve_attempts})"
                )
            elif self.goal_session_active and remaining == 0:
                self.status_var.set(
                    f"Auto-run complete (last maze attempts={self.last_maze_solve_attempts})"
                )
            else:
                self.status_var.set(
                    f"Maze solved in {self.last_maze_solve_attempts} attempt(s)"
                )
            return True
        return False

    def _on_cmd_enter(self, _event: tk.Event) -> str:
        self.on_send()
        return "break"

    def clear_text(self) -> None:
        self.prompt_input.delete("1.0", tk.END)
        self.response_output.config(state=tk.NORMAL)
        self.response_output.delete("1.0", tk.END)
        self.response_output.config(state=tk.DISABLED)
        self._end_auto_goal_session()
        self._set_debug_text("")
        self.status_var.set("Ready")

    def on_send(self) -> None:
        prompt = self.prompt_input.get("1.0", tk.END).strip()
        if not prompt:
            self.status_var.set("Please enter some text before sending")
            return

        navigation_request = self.local_navigation_kernel and self._is_local_navigation_request(prompt)

        if not self.client and not navigation_request:
            self.status_var.set("Missing OPENAI_API_KEY in .env or .env.secret")
            return

        assistant_instructions = self.instructions_input.get("1.0", tk.END).strip()

        self.send_btn.config(state=tk.DISABLED, text="Sending...")
        self.status_var.set("Waiting for model response...")

        thread = threading.Thread(target=self._request_response, args=(prompt, assistant_instructions), daemon=True)
        thread.start()

    def _request_response(self, prompt: str, assistant_instructions: str) -> None:
        try:
            local_navigation_request = self.local_navigation_kernel and self._is_local_navigation_request(prompt)
            local_navigation_result: dict | None = None
            local_navigation_debug = ""
            local_navigation_remaining = 0

            if local_navigation_request:
                local_navigation_result = self._execute_local_navigation_request(prompt, assistant_instructions)
                local_navigation_remaining = int(local_navigation_result["remaining"])
                if (
                    local_navigation_result["step_session"]["success"]
                    or not self.client
                    or not self.local_navigation_api_fallback
                ):
                    self._present_local_navigation_result(local_navigation_result)
                    return

                local_navigation_debug = self._format_local_navigation_debug(
                    local_navigation_result,
                    header="[LOCAL KERNEL PREFLIGHT]",
                )
                self.root.after(0, lambda: self.status_var.set("Local kernel stalled; using OpenAI fallback..."))

            if not self.client:
                raise RuntimeError("Missing OPENAI_API_KEY in .env or .env.secret")

            self.root.after(0, lambda: self.status_var.set("Logic model: interpreting request..."))
            plan = self._build_logic_plan(prompt, assistant_instructions)
            if plan["normalized_goal"]:
                self.last_normalized_goal = plan["normalized_goal"]

            repetition = {
                "is_repeat_goal": bool(plan.get("is_repeat_goal", False)),
                "execution_count": max(1, min(self.max_repeat_executions, int(plan.get("execution_count", 1) or 1))),
                "confidence": 0.0,
                "reason": "Repetition resolver disabled; using planner repetition fields.",
            }
            if self.enable_logic_repetition_resolver:
                repetition = self._logic_resolve_repetition(prompt, plan, assistant_instructions)
            if repetition["confidence"] >= self.repeat_confidence_threshold:
                plan["is_repeat_goal"] = repetition["is_repeat_goal"]
                plan["execution_count"] = repetition["execution_count"]

            if local_navigation_request and local_navigation_result is not None:
                plan["delegate"] = True
                plan["is_repeat_goal"] = local_navigation_remaining > 1
                plan["execution_count"] = max(1, local_navigation_remaining)
                plan["success_criteria"] = (
                    f"Reach the current objective {plan['execution_count']} more time(s) after local-kernel progress."
                )
                if local_navigation_result["step_session"]["completed"] > 0:
                    plan["intent_summary"] = (
                        f"{plan['intent_summary']} Continue from local-kernel progress; "
                        f"{local_navigation_result['step_session']['completed']} hit(s) already completed."
                    ).strip()

            game_navigation_request = self._is_game_navigation_request(prompt, plan)
            low_confidence = plan["confidence"] < self.logic_confidence_threshold
            requested_count = self._extract_execution_count(plan)

            if not plan["delegate"]:
                answer = plan["direct_response"] or "No direct response returned."
                fallback_used = False
                fallback_moves: list[str] = []
                if self.enable_path_fallback and game_navigation_request and low_confidence:
                    fallback_moves = self._shortest_path_moves_to_target()
                    if fallback_moves:
                        fallback_used = True
                        self.root.after(0, self._apply_agent_moves, fallback_moves)

                game_state = self._get_game_state_snapshot()
                local_prefight_section = f"{local_navigation_debug}\n\n" if local_navigation_debug else ""
                debug_text = (
                    f"{local_prefight_section}"
                    "[LOGIC PLAN]\n"
                    f"delegate: {plan['delegate']}\n"
                    f"intent_summary: {plan['intent_summary']}\n"
                    f"agent_task: {plan['agent_task']}\n"
                    f"success_criteria: {plan['success_criteria']}\n"
                    f"confidence: {plan['confidence']}\n"
                    f"normalized_goal: {plan['normalized_goal']}\n"
                    f"repeat_goal: {plan['is_repeat_goal']}\n"
                    f"execution_count: {requested_count}\n"
                    f"repetition_confidence: {repetition['confidence']}\n"
                    f"repetition_reason: {repetition['reason']}\n"
                    f"local_navigation_prefight: {bool(local_navigation_debug)}\n"
                    f"game_navigation_request: {game_navigation_request}\n"
                    f"fallback_used: {fallback_used}\n"
                    f"fallback_moves: {fallback_moves}\n"
                    f"game_state:\n{game_state}\n"
                    "\n[AGENT OUTPUT]\nNot used (delegate=false)."
                )
                self.root.after(0, self._set_debug_text, debug_text)
                self.root.after(0, self._set_response, answer)
                return

            self.root.after(0, lambda: self.status_var.set("Agent model: executing task..."))
            step_session = {
                "requested_count": requested_count,
                "iterations": 0,
                "completed": 0,
                "remaining": 0,
                "success": False,
                "step_log": "",
            }
            agent_output = "Stepwise mode active: single-move proposals + logic move evaluation per step."
            if game_navigation_request:
                step_session = self._run_stepwise_goal_session(prompt, plan, assistant_instructions)

            game_state = self._get_game_state_snapshot()
            completed, remaining = self._goal_session_progress()
            target_cell_debug = (
                "(hidden in maze mode)" if self._normalized_layout_mode() == "maze" else str(self.current_target_cell)
            )

            local_prefight_section = f"{local_navigation_debug}\n\n" if local_navigation_debug else ""
            debug_text = (
                f"{local_prefight_section}"
                "[LOGIC PLAN]\n"
                f"delegate: {plan['delegate']}\n"
                f"intent_summary: {plan['intent_summary']}\n"
                f"agent_task: {plan['agent_task']}\n"
                f"success_criteria: {plan['success_criteria']}\n"
                f"confidence: {plan['confidence']}\n"
                f"normalized_goal: {plan['normalized_goal']}\n"
                f"repeat_goal: {plan['is_repeat_goal']}\n"
                f"execution_count: {requested_count}\n"
                f"repetition_confidence: {repetition['confidence']}\n"
                f"repetition_reason: {repetition['reason']}\n"
                f"local_navigation_prefight: {bool(local_navigation_debug)}\n"
                f"game_navigation_request: {game_navigation_request}\n"
                f"step_mode_success: {step_session['success']}\n"
                f"step_mode_iterations: {step_session['iterations']}\n"
                f"step_mode_completed_hits: {step_session['completed']}\n"
                f"step_mode_remaining_hits: {step_session['remaining']}\n"
                f"target_cell: {target_cell_debug}\n"
                f"goal_session_active: {self.goal_session_active}\n"
                f"goal_session_target_hits: {self.goal_session_target_hits}\n"
                f"goal_session_hits_completed: {completed}\n"
                f"goal_session_hits_remaining: {remaining}\n"
                f"auto_goal_hits_remaining: {self.auto_goal_hits_remaining}\n"
                f"game_state:\n{game_state}\n"
                "\n[STEP LOG]\n"
                f"{step_session['step_log'] or '(none)'}\n"
                "\n[AGENT OUTPUT]\n"
                f"{agent_output}"
            )
            self.root.after(0, self._set_debug_text, debug_text)

            self.root.after(0, lambda: self.status_var.set("Preparing final response..."))
            if game_navigation_request and not self.enable_logic_finalizer_for_navigation:
                completion_label = "maze runs" if self._normalized_layout_mode() == "maze" else "target hits"
                if step_session["success"]:
                    answer = (
                        f"Navigation run complete. Completed {step_session['completed']}/{requested_count} {completion_label} "
                        f"in {step_session['iterations']} step iterations."
                    )
                else:
                    answer = (
                        f"Navigation progress: completed {step_session['completed']}/{requested_count} {completion_label} "
                        f"in {step_session['iterations']} step iterations; {step_session['remaining']} remaining."
                    )
            else:
                answer = self._logic_finalize(prompt, plan, agent_output, assistant_instructions)
            self.root.after(0, self._set_response, answer)
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, self._set_error, redact_secrets(f"Request failed: {exc}"))

    def _set_response(self, text: str) -> None:
        safe_text = redact_secrets(text)
        self.response_output.config(state=tk.NORMAL)
        self.response_output.delete("1.0", tk.END)
        self.response_output.insert(tk.END, safe_text)
        self.response_output.config(state=tk.DISABLED)

        self.send_btn.config(state=tk.NORMAL, text="Send")
        self.status_var.set("Done")

    def _set_error(self, message: str) -> None:
        safe_message = redact_secrets(message)
        self.response_output.config(state=tk.NORMAL)
        self.response_output.delete("1.0", tk.END)
        self.response_output.insert(tk.END, safe_message)
        self.response_output.config(state=tk.DISABLED)

        self.send_btn.config(state=tk.NORMAL, text="Send")
        self.status_var.set("Error")


if __name__ == "__main__":
    root_window = tk.Tk()
    app = AIAssistantApp(root_window)
    root_window.mainloop()
