from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Literal, Optional, Sequence, Set, Tuple

Direction = Literal["UP", "RIGHT", "DOWN", "LEFT"]
ActionType = Direction
PolicyId = Literal["EXPLORE_FRONTIER", "ESCAPE_LOOP", "SAFE_PROGRESS", "RISK_PUSH"]
Tag = str
Position = Tuple[int, int]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class GridState:
    player_pos: Position
    facing: Direction
    visible_ascii: Sequence[Sequence[str]]
    step_index: int


@dataclass(frozen=True)
class Event:
    step: int
    action: ActionType
    reward: float
    penalty: float
    tags: Set[Tag]


@dataclass(frozen=True)
class Signature:
    boundary_bucket: int
    branch_profile: str
    dead_end_risk: int
    dead_end_risk_depth: int
    frontier_distance: int
    known_degree: int
    unknown_neighbors: int
    visit_bucket: int
    recent_backtrack: int
    transition_pressure_bucket: int
    facing: Direction
    difficulty: str


@dataclass(frozen=True)
class LookSnapshot:
    step: int
    facing: Direction
    ascii_snapshot: str


@dataclass(frozen=True)
class EpisodeStep:
    step: int
    signature: Signature
    event: Event
    player_pos: Position


@dataclass(frozen=True)
class LoopSignature:
    reason: str
    confidence: float
    repeated_positions: Tuple[Position, ...] = ()
    repeated_profiles: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EpisodeSummary:
    step_count: int
    penalty_sum: float
    reward_sum: float
    unique_positions: int
    loop_detected: bool


@dataclass(frozen=True)
class FrontierRecord:
    step: int
    branch_profile: str
    frontier_distance: int
    unknown_neighbors: int
    strength: float


@dataclass
class WorkingMemory:
    current_grid: Optional[GridState] = None
    current_signature: Optional[Signature] = None
    recent_events: Deque[Event] = field(default_factory=lambda: deque(maxlen=40))
    recent_looks: Deque[LookSnapshot] = field(default_factory=lambda: deque(maxlen=24))

    def update_working_memory(
        self,
        grid: GridState,
        signature: Signature,
        events: Iterable[Event] = (),
        looks: Iterable[LookSnapshot] = (),
    ) -> None:
        self.current_grid = grid
        self.current_signature = signature
        for event in events:
            self.recent_events.append(event)
        for look in looks:
            self.recent_looks.append(look)

    def get_recent_events(self, n: int) -> list[Event]:
        if n <= 0:
            return []
        return list(self.recent_events)[-n:]


@dataclass
class ShortTermMemory:
    episodes: Deque[list[EpisodeStep]] = field(default_factory=lambda: deque(maxlen=20))
    frontier_records: list[FrontierRecord] = field(default_factory=list)
    recent_steps: Deque[EpisodeStep] = field(default_factory=lambda: deque(maxlen=64))

    def start_episode(self) -> None:
        self.episodes.append([])

    def record_step(self, step: int, signature: Signature, event: Event, player_pos: Position) -> None:
        if not self.episodes:
            self.start_episode()
        item = EpisodeStep(step=step, signature=signature, event=event, player_pos=player_pos)
        self.episodes[-1].append(item)
        self.recent_steps.append(item)

        strength = max(0.0, (signature.unknown_neighbors * 0.6) + max(0, 3 - signature.frontier_distance))
        self.frontier_records.append(
            FrontierRecord(
                step=step,
                branch_profile=signature.branch_profile,
                frontier_distance=signature.frontier_distance,
                unknown_neighbors=signature.unknown_neighbors,
                strength=round(strength, 3),
            )
        )

    def detect_local_loop(self) -> Optional[LoopSignature]:
        if len(self.recent_steps) < 6:
            return None

        window = list(self.recent_steps)[-16:]
        positions = [step.player_pos for step in window]
        pos_counter = Counter(positions)
        repeated_positions = tuple(pos for pos, count in pos_counter.items() if count >= 3)

        profiles = [step.signature.branch_profile for step in window]
        profile_counter = Counter(profiles)
        repeated_profiles = tuple(profile for profile, count in profile_counter.items() if count >= 4)

        cycle_tag_hits = 0
        trap_tag_hits = 0
        for step in window:
            tags = step.event.tags
            if "cycle_pair" in tags or "transition_repeat" in tags:
                cycle_tag_hits += 1
            if "visible_terminal" in tags or "boxed_corridor" in tags:
                trap_tag_hits += 1

        confidence = 0.0
        reasons: list[str] = []
        if repeated_positions:
            confidence += 0.4
            reasons.append("repeated_positions")
        if repeated_profiles:
            confidence += 0.3
            reasons.append("repeated_branch_profile")
        if cycle_tag_hits >= 2:
            confidence += 0.2
            reasons.append("cycle_tags")
        if trap_tag_hits >= 2:
            confidence += 0.1
            reasons.append("trap_tags")

        if confidence < 0.35:
            return None

        return LoopSignature(
            reason="+".join(reasons),
            confidence=round(_clamp(confidence, 0.0, 1.0), 3),
            repeated_positions=repeated_positions,
            repeated_profiles=repeated_profiles,
        )

    def summarize_episode(self) -> EpisodeSummary:
        if not self.episodes:
            return EpisodeSummary(step_count=0, penalty_sum=0.0, reward_sum=0.0, unique_positions=0, loop_detected=False)

        episode = self.episodes[-1]
        penalty_sum = sum(step.event.penalty for step in episode)
        reward_sum = sum(step.event.reward for step in episode)
        unique_positions = len({step.player_pos for step in episode})
        loop_detected = self.detect_local_loop() is not None
        return EpisodeSummary(
            step_count=len(episode),
            penalty_sum=round(penalty_sum, 3),
            reward_sum=round(reward_sum, 3),
            unique_positions=unique_positions,
            loop_detected=loop_detected,
        )

    def get_recent_positions_and_actions(self, n: int) -> list[tuple[Position, ActionType]]:
        if n <= 0:
            return []
        return [(item.player_pos, item.event.action) for item in list(self.recent_steps)[-n:]]


@dataclass
class VisitStats:
    visits: int = 0
    reward_sum: float = 0.0
    penalty_sum: float = 0.0


@dataclass(frozen=True)
class LoopPattern:
    signature_key: str
    confidence: float
    step: int


@dataclass(frozen=True)
class SuccessPattern:
    signature_key: str
    reward: float
    step: int


@dataclass
class LongTermMemory:
    visited_signatures: Dict[str, VisitStats] = field(default_factory=dict)
    loop_patterns: list[LoopPattern] = field(default_factory=list)
    success_patterns: list[SuccessPattern] = field(default_factory=list)

    def _signature_key(self, signature: Signature) -> str:
        return (
            f"bb={signature.boundary_bucket}|bp={signature.branch_profile}|dr={signature.dead_end_risk}|"
            f"fd={signature.frontier_distance}|uk={signature.unknown_neighbors}|tp={signature.transition_pressure_bucket}|"
            f"fc={signature.facing}|df={signature.difficulty}"
        )

    def update_visit(self, signature: Signature, event: Event) -> None:
        key = self._signature_key(signature)
        stats = self.visited_signatures.setdefault(key, VisitStats())
        stats.visits += 1
        stats.reward_sum += event.reward
        stats.penalty_sum += event.penalty

        if event.reward > event.penalty and event.reward > 0:
            self.success_patterns.append(SuccessPattern(signature_key=key, reward=event.reward, step=event.step))

    def record_loop(self, loop_sig: LoopSignature, signature: Signature, step: int) -> None:
        key = self._signature_key(signature)
        self.loop_patterns.append(LoopPattern(signature_key=key, confidence=loop_sig.confidence, step=step))

    def get_loop_risk(self, signature: Signature) -> float:
        key = self._signature_key(signature)
        stats = self.visited_signatures.get(key)
        if not stats:
            return 0.0

        mean_penalty = stats.penalty_sum / max(1, stats.visits)
        mean_reward = stats.reward_sum / max(1, stats.visits)
        structural_risk = 0.12 * stats.visits
        signal_risk = max(0.0, mean_penalty - (0.5 * mean_reward))
        risk = _clamp(structural_risk + signal_risk, 0.0, 1.0)
        return round(risk, 4)

    def get_novelty_score(self, signature: Signature) -> float:
        key = self._signature_key(signature)
        stats = self.visited_signatures.get(key)
        if not stats:
            return 1.0
        novelty = 1.0 / (1.0 + (0.6 * stats.visits))
        return round(_clamp(novelty, 0.0, 1.0), 4)


@dataclass
class MemoryState:
    working_memory: WorkingMemory = field(default_factory=WorkingMemory)
    short_term: ShortTermMemory = field(default_factory=ShortTermMemory)
    long_term: LongTermMemory = field(default_factory=LongTermMemory)


@dataclass
class EndocrineState:
    dopamine: float = 0.30
    cortisol: float = 0.20
    serotonin: float = 0.30
    acetylcholine: float = 0.25
    norepinephrine: float = 0.20
    boredom: float = 0.15

    def clamp(self) -> None:
        self.dopamine = _clamp(self.dopamine, 0.0, 1.0)
        self.cortisol = _clamp(self.cortisol, 0.0, 1.0)
        self.serotonin = _clamp(self.serotonin, 0.0, 1.0)
        self.acetylcholine = _clamp(self.acetylcholine, 0.0, 1.0)
        self.norepinephrine = _clamp(self.norepinephrine, 0.0, 1.0)
        self.boredom = _clamp(self.boredom, 0.0, 1.0)


@dataclass
class ControlState:
    current_policy: PolicyId = "EXPLORE_FRONTIER"
    last_action: Optional[ActionType] = None
    loop_suspected: bool = False
    loop_signature: Optional[LoopSignature] = None


@dataclass
class CandidateProjection:
    action: ActionType
    next_pos: Position
    estimated_loop_risk: float
    estimated_novelty: float
    estimated_unknown_neighbors: int
    estimated_frontier_gain: float
    visit_count: int = 0
    frontier_distance: int = 99
    dead_end_risk_depth: int = 0
    cycle_pair_recent: bool = False
    visible_terminal: bool = False
    boxed_corridor: bool = False
    catastrophic_trap: bool = False


@dataclass
class StepResult:
    action: ActionType
    policy: PolicyId
    loop_risk: float
    frontier_strength: float
    memory: MemoryState
    endocrine: EndocrineState
    control: ControlState


def update_endocrine(
    endocrine: EndocrineState,
    event: Event,
    signature: Signature,
    loop_risk: float,
    frontier_strength: float,
) -> EndocrineState:
    # Dopamine: novelty and success, with mild decay.
    endocrine.dopamine += 0.10 * max(0.0, event.reward)
    if "novelty_reward" in event.tags:
        endocrine.dopamine += 0.06
    endocrine.dopamine *= 0.97

    # Cortisol: penalties, loop pressure, and explicit cycle tags.
    endocrine.cortisol += 0.12 * max(0.0, event.penalty)
    if "cycle_pair" in event.tags or "transition_repeat" in event.tags:
        endocrine.cortisol += 0.07
    if loop_risk > 0.35:
        endocrine.cortisol += 0.20 * loop_risk
    endocrine.cortisol *= 0.95

    # Serotonin: stable progress, but suppressed by high cortisol.
    if event.penalty <= 0.0 and event.reward > 0.0:
        endocrine.serotonin += 0.04
    endocrine.serotonin -= 0.08 * endocrine.cortisol
    endocrine.serotonin *= 0.98

    # Acetylcholine: uncertainty/frontier attention.
    endocrine.acetylcholine += 0.02 * max(0, signature.unknown_neighbors)
    endocrine.acetylcholine += 0.08 * max(0.0, frontier_strength)
    endocrine.acetylcholine *= 0.96

    # Norepinephrine: urgency from pressure/risk/stress.
    endocrine.norepinephrine += 0.04 * max(0, signature.transition_pressure_bucket)
    endocrine.norepinephrine += 0.04 * max(0, signature.dead_end_risk)
    endocrine.norepinephrine += 0.05 * endocrine.cortisol
    endocrine.norepinephrine *= 0.95

    # Boredom: repeated low-novelty states, relieved by novelty events.
    if "cycle_pair" in event.tags:
        endocrine.boredom += 0.08
    if signature.unknown_neighbors == 0 and frontier_strength < 0.15:
        endocrine.boredom += 0.06
    if "novelty_reward" in event.tags:
        endocrine.boredom *= 0.80
    else:
        endocrine.boredom *= 0.99

    endocrine.clamp()
    return endocrine


def select_policy(endocrine: EndocrineState, loop_risk: float, frontier_strength: float) -> PolicyId:
    if loop_risk >= 0.60 or endocrine.boredom >= 0.55 or endocrine.cortisol >= 0.60:
        return "ESCAPE_LOOP"
    if endocrine.acetylcholine >= 0.45 and frontier_strength >= 0.25:
        return "EXPLORE_FRONTIER"
    if endocrine.serotonin >= 0.45 and endocrine.cortisol <= 0.25:
        return "SAFE_PROGRESS"
    return "RISK_PUSH"


def _choose_max_novelty(candidates: Sequence[CandidateProjection]) -> CandidateProjection:
    return max(
        candidates,
        key=lambda c: (c.estimated_novelty, c.estimated_frontier_gain, -c.estimated_loop_risk),
    )


def _choose_min_loop_risk(candidates: Sequence[CandidateProjection]) -> CandidateProjection:
    return min(
        candidates,
        key=lambda c: (c.estimated_loop_risk, -c.estimated_novelty, -c.estimated_frontier_gain),
    )


def _derive_forbidden_moves_from_cycles(recent: Sequence[tuple[Position, ActionType]]) -> Set[ActionType]:
    if not recent:
        return set()

    action_counts = Counter(action for _, action in recent)
    forbidden: Set[ActionType] = {action for action, count in action_counts.items() if count >= 3}

    if len(recent) >= 4:
        tail = [action for _, action in recent[-4:]]
        if tail[0] == tail[2] and tail[1] == tail[3]:
            forbidden.update({tail[0], tail[1]})

    return forbidden


def is_catastrophic_trap(candidate: CandidateProjection) -> bool:
    if candidate.catastrophic_trap:
        return True
    if candidate.cycle_pair_recent and candidate.visible_terminal and candidate.boxed_corridor:
        return True
    if (
        candidate.visit_count >= 1
        and candidate.frontier_distance >= 3
        and candidate.dead_end_risk_depth >= 2
        and candidate.cycle_pair_recent
    ):
        return True
    return False


def _least_visited_low_risk(candidates: Sequence[CandidateProjection]) -> CandidateProjection:
    return min(
        candidates,
        key=lambda c: (c.visit_count, c.estimated_loop_risk, -c.estimated_novelty, -c.estimated_frontier_gain),
    )


def escape_loop_policy(
    memory: MemoryState,
    candidates: Sequence[CandidateProjection],
    recent_window: int = 10,
) -> ActionType:
    if not candidates:
        return "UP"

    non_catastrophic = [c for c in candidates if not is_catastrophic_trap(c)]
    if non_catastrophic:
        candidates = non_catastrophic
    else:
        # Escape fallback when every option is structurally bad.
        return _least_visited_low_risk(candidates).action

    recent = memory.short_term.get_recent_positions_and_actions(recent_window)
    forbidden_moves = _derive_forbidden_moves_from_cycles(recent)

    filtered = [c for c in candidates if c.action not in forbidden_moves]
    if filtered:
        return _choose_max_novelty(filtered).action
    return _choose_min_loop_risk(candidates).action


def explore_frontier_policy(candidates: Sequence[CandidateProjection]) -> ActionType:
    if not candidates:
        return "UP"
    non_catastrophic = [c for c in candidates if not is_catastrophic_trap(c)]
    if non_catastrophic:
        candidates = non_catastrophic
    best = max(candidates, key=lambda c: (c.estimated_frontier_gain, c.estimated_novelty, -c.estimated_loop_risk))
    return best.action


def safe_progress_policy(candidates: Sequence[CandidateProjection]) -> ActionType:
    if not candidates:
        return "UP"
    non_catastrophic = [c for c in candidates if not is_catastrophic_trap(c)]
    if non_catastrophic:
        candidates = non_catastrophic
    best = min(candidates, key=lambda c: (c.estimated_loop_risk, -c.estimated_frontier_gain, -c.estimated_novelty))
    return best.action


def risk_push_policy(candidates: Sequence[CandidateProjection]) -> ActionType:
    if not candidates:
        return "UP"
    non_catastrophic = [c for c in candidates if not is_catastrophic_trap(c)]
    if non_catastrophic:
        candidates = non_catastrophic
    best = max(candidates, key=lambda c: (c.estimated_frontier_gain + c.estimated_novelty, -c.estimated_loop_risk))
    return best.action


def _compute_frontier_strength(signature: Signature) -> float:
    distance_term = _clamp(1.0 - (signature.frontier_distance / 6.0), 0.0, 1.0)
    unknown_term = _clamp(signature.unknown_neighbors / 4.0, 0.0, 1.0)
    return round((0.45 * distance_term) + (0.55 * unknown_term), 4)


def step_agent(
    grid: GridState,
    signature: Signature,
    event: Event,
    candidate_moves: Sequence[CandidateProjection],
    memory: MemoryState,
    endocrine: EndocrineState,
    control: ControlState,
) -> StepResult:
    memory.working_memory.update_working_memory(grid=grid, signature=signature, events=[event])
    memory.short_term.record_step(step=grid.step_index, signature=signature, event=event, player_pos=grid.player_pos)
    memory.long_term.update_visit(signature=signature, event=event)

    loop_sig = memory.short_term.detect_local_loop()
    if loop_sig is not None:
        memory.long_term.record_loop(loop_sig=loop_sig, signature=signature, step=grid.step_index)

    loop_risk = 1.0 if loop_sig is not None else memory.long_term.get_loop_risk(signature)
    frontier_strength = _compute_frontier_strength(signature)

    endocrine = update_endocrine(
        endocrine=endocrine,
        event=event,
        signature=signature,
        loop_risk=loop_risk,
        frontier_strength=frontier_strength,
    )

    policy = select_policy(endocrine=endocrine, loop_risk=loop_risk, frontier_strength=frontier_strength)

    if policy == "ESCAPE_LOOP":
        action = escape_loop_policy(memory=memory, candidates=candidate_moves)
    elif policy == "EXPLORE_FRONTIER":
        action = explore_frontier_policy(candidate_moves)
    elif policy == "SAFE_PROGRESS":
        action = safe_progress_policy(candidate_moves)
    else:
        action = risk_push_policy(candidate_moves)

    control.current_policy = policy
    control.last_action = action
    control.loop_suspected = loop_sig is not None
    control.loop_signature = loop_sig

    return StepResult(
        action=action,
        policy=policy,
        loop_risk=loop_risk,
        frontier_strength=frontier_strength,
        memory=memory,
        endocrine=endocrine,
        control=control,
    )
