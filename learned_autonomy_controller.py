from __future__ import annotations

from kernel_contracts import AutonomyState, AutonomyTransitionEvent


class LearnedAutonomyController:
    """Runtime learner that attenuates hard override reliance from telemetry."""

    def __init__(
        self,
        *,
        enabled: bool,
        ema_decay: float,
        warmup_steps: int,
        phase1_score: float,
        phase2_score: float,
        unresolved_target: float,
    ) -> None:
        self.enabled = bool(enabled)
        self.ema_decay = max(0.5, min(0.999, float(ema_decay)))
        self.warmup_steps = max(1, int(warmup_steps))
        self.phase1_score = max(0.0, min(1.0, float(phase1_score)))
        self.phase2_score = max(self.phase1_score, min(1.0, float(phase2_score)))
        self.unresolved_target = max(0.0, min(1.0, float(unresolved_target)))

        self.step_count = 0
        self.score_ema = 0.5
        self.learned_only_ema = 0.5
        self.hardcoded_only_ema = 0.5
        self.intervention_ema = 0.5
        self.utility_ema = 0.5
        self.unresolved_override_ema = 0.0
        self._hard_phase_bonus = 0
        self._objective_phase_bonus = 0
        self._soft_influence_scale = 1.0
        self.autonomy_state = AutonomyState.ASSISTED
        self.autonomy_level = 0.42
        self.allowed_action_classes = ("safe_progress", "frontier_explore")
        self.veto_flags: tuple[str, ...] = ()

    def set_external_override(self, state: AutonomyState, reason: str, actor: str = "external") -> AutonomyTransitionEvent:
        prev = self.autonomy_state
        self.autonomy_state = state
        self.autonomy_level = self._state_level(state)
        self._refresh_action_class_controls()
        return AutonomyTransitionEvent(
            from_state=prev,
            to_state=self.autonomy_state,
            trigger="external_override",
            justification=str(reason or "external override"),
            external_override=True,
            actor=str(actor or "external"),
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

    def observe_step(
        self,
        *,
        telemetry_channel: str,
        intervention_applied: bool,
        utility_anchor: float,
        unresolved_objective_override: bool,
    ) -> AutonomyTransitionEvent | None:
        if not self.enabled:
            return None

        self.step_count += 1
        keep = self.ema_decay
        blend = 1.0 - keep

        learned_sample = 1.0 if str(telemetry_channel) == "learned_only" else 0.0
        hardcoded_sample = 1.0 if str(telemetry_channel) == "hardcoded_only" else 0.0
        intervention_sample = 1.0 if intervention_applied else 0.0
        unresolved_sample = 1.0 if unresolved_objective_override else 0.0
        utility_sample = self._clamp(float(utility_anchor), 0.0, 1.0)

        self.learned_only_ema = (self.learned_only_ema * keep) + (learned_sample * blend)
        self.hardcoded_only_ema = (self.hardcoded_only_ema * keep) + (hardcoded_sample * blend)
        self.intervention_ema = (self.intervention_ema * keep) + (intervention_sample * blend)
        self.utility_ema = (self.utility_ema * keep) + (utility_sample * blend)
        self.unresolved_override_ema = (self.unresolved_override_ema * keep) + (unresolved_sample * blend)

        learned_mix_balance = self._clamp(
            0.5 + ((self.learned_only_ema - self.hardcoded_only_ema) * 0.5),
            0.0,
            1.0,
        )
        intervention_relief = self._clamp(1.0 - self.intervention_ema, 0.0, 1.0)
        unresolved_relief = self._clamp(1.0 - self.unresolved_override_ema, 0.0, 1.0)

        score_target = self._clamp(
            (0.4 * learned_mix_balance)
            + (0.3 * self.utility_ema)
            + (0.2 * intervention_relief)
            + (0.1 * unresolved_relief),
            0.0,
            1.0,
        )
        self.score_ema = (self.score_ema * keep) + (score_target * blend)

        self._recompute_outputs()
        return self._refresh_autonomy_state(
            telemetry_channel=str(telemetry_channel or "unknown"),
            intervention_applied=bool(intervention_applied),
        )

    def _state_level(self, state: AutonomyState) -> float:
        levels = {
            AutonomyState.MANUAL: 0.0,
            AutonomyState.ASSISTED: 0.35,
            AutonomyState.CONSTRAINED_AUTONOMY: 0.58,
            AutonomyState.SUPERVISED_AUTONOMY: 0.78,
            AutonomyState.SUSPENDED: 0.12,
        }
        return float(levels.get(state, 0.35))

    def _refresh_action_class_controls(self) -> None:
        if self.autonomy_state == AutonomyState.MANUAL:
            self.allowed_action_classes = ("manual_only",)
            self.veto_flags = ("kernel_autonomy_disabled",)
            return
        if self.autonomy_state == AutonomyState.SUSPENDED:
            self.allowed_action_classes = ("safe_progress",)
            self.veto_flags = ("safety_hold",)
            return
        if self.autonomy_state == AutonomyState.ASSISTED:
            self.allowed_action_classes = ("safe_progress", "frontier_explore")
            self.veto_flags = ()
            return
        if self.autonomy_state == AutonomyState.CONSTRAINED_AUTONOMY:
            self.allowed_action_classes = ("safe_progress", "frontier_explore", "verification")
            self.veto_flags = ()
            return
        self.allowed_action_classes = (
            "safe_progress",
            "frontier_explore",
            "verification",
            "risk_push",
        )
        self.veto_flags = ()

    def _refresh_autonomy_state(
        self,
        *,
        telemetry_channel: str,
        intervention_applied: bool,
    ) -> AutonomyTransitionEvent | None:
        previous = self.autonomy_state

        if self.step_count < self.warmup_steps:
            candidate = AutonomyState.ASSISTED
            trigger = "warmup"
        else:
            high_distress = self.unresolved_override_ema >= max(self.unresolved_target + 0.18, 0.25)
            low_utility = self.utility_ema <= 0.35
            high_intervention = self.intervention_ema >= 0.72
            if high_distress and (low_utility or high_intervention):
                candidate = AutonomyState.SUSPENDED
                trigger = "risk_guard"
            elif self.score_ema >= self.phase2_score and self.hardcoded_only_ema <= 0.42:
                candidate = AutonomyState.SUPERVISED_AUTONOMY
                trigger = "performance"
            elif self.score_ema >= self.phase1_score:
                candidate = AutonomyState.CONSTRAINED_AUTONOMY
                trigger = "performance"
            elif intervention_applied:
                candidate = AutonomyState.ASSISTED
                trigger = "intervention"
            else:
                candidate = AutonomyState.ASSISTED
                trigger = "stability"

        self.autonomy_state = candidate
        self.autonomy_level = self._state_level(candidate)
        self._refresh_action_class_controls()
        if previous == candidate:
            return None

        justification = (
            f"score_ema={round(float(self.score_ema),4)} utility_ema={round(float(self.utility_ema),4)} "
            f"intervention_ema={round(float(self.intervention_ema),4)} "
            f"unresolved_override_ema={round(float(self.unresolved_override_ema),4)} "
            f"channel={telemetry_channel}"
        )
        return AutonomyTransitionEvent(
            from_state=previous,
            to_state=candidate,
            trigger=trigger,
            justification=justification,
            external_override=False,
            actor="learned_autonomy_controller",
        )

    def _recompute_outputs(self) -> None:
        if (not self.enabled) or self.step_count < self.warmup_steps:
            self._hard_phase_bonus = 0
            self._objective_phase_bonus = 0
            self._soft_influence_scale = 1.0
            return

        hard_bonus = 0
        if self.score_ema >= self.phase2_score:
            hard_bonus = 2
        elif self.score_ema >= self.phase1_score:
            hard_bonus = 1

        unresolved_pressure = self._clamp(
            self.unresolved_override_ema - self.unresolved_target,
            0.0,
            1.0,
        )
        unresolved_bonus = 0
        if unresolved_pressure >= 0.20:
            unresolved_bonus = 2
        elif unresolved_pressure >= 0.08:
            unresolved_bonus = 1

        objective_bonus = max(hard_bonus, unresolved_bonus)
        soft_influence_scale = self._clamp(1.0 - (0.55 * self.score_ema), 0.35, 1.0)

        self._hard_phase_bonus = int(max(0, min(2, hard_bonus)))
        self._objective_phase_bonus = int(max(0, min(2, objective_bonus)))
        self._soft_influence_scale = float(soft_influence_scale)

    def hard_phase_bonus(self) -> int:
        return int(self._hard_phase_bonus)

    def objective_phase_bonus(self) -> int:
        return int(self._objective_phase_bonus)

    def soft_influence_scale(self) -> float:
        return float(self._soft_influence_scale)

    def snapshot(self) -> dict[str, float | int]:
        return {
            "enabled": 1 if self.enabled else 0,
            "step_count": int(self.step_count),
            "score_ema": round(float(self.score_ema), 4),
            "learned_only_ema": round(float(self.learned_only_ema), 4),
            "hardcoded_only_ema": round(float(self.hardcoded_only_ema), 4),
            "intervention_ema": round(float(self.intervention_ema), 4),
            "utility_ema": round(float(self.utility_ema), 4),
            "unresolved_override_ema": round(float(self.unresolved_override_ema), 4),
            "hard_phase_bonus": int(self._hard_phase_bonus),
            "objective_phase_bonus": int(self._objective_phase_bonus),
            "soft_influence_scale": round(float(self._soft_influence_scale), 4),
            "autonomy_state": str(self.autonomy_state.value),
            "autonomy_level": round(float(self.autonomy_level), 4),
            "allowed_action_classes": ",".join(self.allowed_action_classes),
            "veto_flags": ",".join(self.veto_flags),
        }
