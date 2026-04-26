from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from runtime_kernel.kernel_contracts import (
    ActionOutcomeEvent,
    AutonomyTransitionEvent,
    DevelopmentStage,
    GlobalErrorEvent,
    ModuleCapabilityDescriptor,
)


@dataclass
class GovernanceOrchestrator:
    enabled: bool
    policy_version: str
    development_stage: DevelopmentStage
    capabilities: dict[str, ModuleCapabilityDescriptor] = field(default_factory=dict)
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def register_module(self, descriptor: ModuleCapabilityDescriptor) -> None:
        self.capabilities[descriptor.module_id] = descriptor

    def record_autonomy_transition(self, event: AutonomyTransitionEvent) -> None:
        if not self.enabled:
            return
        self.audit_log.append(
            {
                "ts": time.time(),
                "kind": "autonomy_transition",
                "policy_version": self.policy_version,
                "stage": self.development_stage.value,
                "from": event.from_state.value,
                "to": event.to_state.value,
                "trigger": event.trigger,
                "justification": event.justification,
                "external_override": int(event.external_override),
                "actor": event.actor,
            }
        )

    def record_action_outcome(self, event: ActionOutcomeEvent) -> None:
        if not self.enabled:
            return
        self.audit_log.append(
            {
                "ts": time.time(),
                "kind": "action_outcome",
                "policy_version": self.policy_version,
                "stage": self.development_stage.value,
                "action_id": event.action_id,
                "action_type": event.action_type,
                "outcome": event.outcome,
                "safety_flags": list(event.safety_flags),
                "anomalies": list(event.anomalies),
                "context": dict(event.context),
            }
        )

    def record_error(self, event: GlobalErrorEvent) -> None:
        if not self.enabled:
            return
        self.audit_log.append(
            {
                "ts": time.time(),
                "kind": "error",
                "policy_version": self.policy_version,
                "stage": self.development_stage.value,
                "module": event.module,
                "category": event.category.value,
                "code": event.code,
                "message": event.message,
                "handling_hint": event.handling_hint.value,
                "retryable": int(event.retryable),
                "details": dict(event.details),
            }
        )

    def record_runtime_event(self, *, kind: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        event_kind = str(kind or "runtime_event").strip() or "runtime_event"
        self.audit_log.append(
            {
                "ts": time.time(),
                "kind": event_kind,
                "policy_version": self.policy_version,
                "stage": self.development_stage.value,
                "payload": dict(payload or {}),
            }
        )

    def introspection_snapshot(self, *, autonomy: dict[str, Any], reasoning: dict[str, Any]) -> dict[str, Any]:
        recent = self.audit_log[-20:]
        return {
            "enabled": int(self.enabled),
            "policy_version": self.policy_version,
            "development_stage": self.development_stage.value,
            "registered_modules": sorted(self.capabilities.keys()),
            "autonomy": autonomy,
            "reasoning": reasoning,
            "recent_events": recent,
        }
