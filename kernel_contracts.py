from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GlobalErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"


class ErrorHandlingHint(str, Enum):
    RETRY = "retry"
    DEGRADE = "degrade"
    ESCALATE = "escalate"
    HALT = "halt"


class AutonomyState(str, Enum):
    MANUAL = "MANUAL"
    ASSISTED = "ASSISTED"
    CONSTRAINED_AUTONOMY = "CONSTRAINED_AUTONOMY"
    SUPERVISED_AUTONOMY = "SUPERVISED_AUTONOMY"
    SUSPENDED = "SUSPENDED"


class DevelopmentStage(str, Enum):
    INFANT_KERNEL = "INFANT_KERNEL"
    JUVENILE_KERNEL = "JUVENILE_KERNEL"
    MATURE_KERNEL = "MATURE_KERNEL"
    RESEARCH_MODE = "RESEARCH_MODE"


class ReasoningProfile(str, Enum):
    FAST_APPROX = "FAST_APPROX"
    BALANCED = "BALANCED"
    DEEP_AUDIT = "DEEP_AUDIT"


@dataclass(frozen=True)
class ModuleCapabilityDescriptor:
    module_id: str
    module_version: str
    supported_features: tuple[str, ...]
    known_limitations: tuple[str, ...] = ()
    safety_guarantees: tuple[str, ...] = ()


@dataclass(frozen=True)
class KernelAutonomyInput:
    current_goal: str
    context_summary: str
    risk_profile: dict[str, float]


@dataclass(frozen=True)
class KernelAutonomyOutput:
    autonomy_state: AutonomyState
    autonomy_level: float
    allowed_action_classes: tuple[str, ...]
    veto_flags: tuple[str, ...]


@dataclass(frozen=True)
class KernelOrganismInput:
    action_type: str
    parameters: dict[str, Any]
    safety_constraints: dict[str, Any]


@dataclass(frozen=True)
class KernelOrganismOutput:
    success: bool
    sensor_feedback: dict[str, Any]
    safety_override_triggers: tuple[str, ...]


@dataclass(frozen=True)
class ReasoningBudgetContract:
    max_branches: int
    max_depth: int
    time_budget_ms: int
    token_budget: int


@dataclass(frozen=True)
class KernelReasoningInput:
    problem_spec: str
    constraints: dict[str, Any]
    evaluation_metric: str
    profile: ReasoningProfile
    budget: ReasoningBudgetContract


@dataclass(frozen=True)
class KernelReasoningOutput:
    ranked_hypotheses: tuple[dict[str, Any], ...]
    confidence_scores: tuple[float, ...]
    reasoning_traces: tuple[str, ...]


@dataclass(frozen=True)
class GlobalErrorEvent:
    module: str
    category: GlobalErrorCategory
    code: str
    message: str
    handling_hint: ErrorHandlingHint
    retryable: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionOutcomeEvent:
    action_id: str
    action_type: str
    parameters: dict[str, Any]
    context: dict[str, Any]
    outcome: str
    safety_flags: tuple[str, ...]
    anomalies: tuple[str, ...]


@dataclass(frozen=True)
class AutonomyTransitionEvent:
    from_state: AutonomyState
    to_state: AutonomyState
    trigger: str
    justification: str
    external_override: bool
    actor: str
