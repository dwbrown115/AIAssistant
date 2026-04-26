from __future__ import annotations

from dataclasses import dataclass, field


def _clamp(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


@dataclass(frozen=True)
class MicroStageSpec:
    stage_id: str
    label: str
    mode: str
    module_targets: tuple[str, ...]
    objective_signals: tuple[str, ...]
    min_observations: int = 64


@dataclass(frozen=True)
class AdaptivePhaseSpec:
    phase_id: str
    label: str
    capability: str
    module_id: str
    micro_stages: tuple[MicroStageSpec, ...]


@dataclass
class AdaptivePhaseRuntime:
    phase_id: str
    enabled: bool = True
    micro_index: int = 0
    completed: bool = False
    observations: int = 0
    score_ema: float = 0.0
    train_ema: float = 0.0
    integrate_ema: float = 0.0
    stability_ema: float = 0.0
    transfer_ema: float = 0.0
    safety_ema: float = 0.0
    introspection_ema: float = 0.0
    promotion_target: float = 0.62
    last_effective_min_observations: int = 0
    last_safety_floor: float = 0.42
    last_stability_floor: float = 0.40
    last_transfer_floor: float = 0.18
    last_autostep_enabled: bool = True
    last_blocked_reason: str = "init"


@dataclass
class AdaptivePhaseTransition:
    phase_id: str
    from_micro: int
    to_micro: int
    completed_phase: bool
    reason: str


class AdaptiveKernelPhaseProgram:
    """Adaptive phase/micro progression with optional per-phase pause.

    Phase progression is preserved when a phase is disabled: disabling pauses the
    phase state in place, and active selection simply skips it.
    """

    def __init__(
        self,
        *,
        phase_specs: tuple[AdaptivePhaseSpec, ...],
        ema_decay: float = 0.92,
        base_promotion_target: float = 0.62,
        target_adapt_enable: bool = False,
        target_adapt_rate: float = 0.08,
        weight_adapt_rate: float = 0.06,
        promotion_target_hard_max: float = 0.90,
        early_target_cap_enable: bool = False,
        early_target_cap: float = 0.58,
        early_target_cap_phase_count: int = 1,
        early_target_cap_micro_max: int = 3,
        weight_rebase_enable: bool = True,
        weight_rebase_alpha: float = 0.68,
        weight_rebase_objective_boost: float = 0.30,
        warmup_target_dampener_enable: bool = True,
        warmup_target_dampener_observations: int = 96,
        warmup_target_dampener_max_reduction: float = 0.14,
        target_raise_only_when_score_ready: bool = True,
        target_freeze_after_observation_gate: bool = True,
        target_deficit_relief_rate: float = 0.0,
        target_deficit_margin: float = 0.015,
    ) -> None:
        if not phase_specs:
            raise ValueError("phase_specs must not be empty")
        self.phase_specs = phase_specs
        self.ema_decay = _clamp(float(ema_decay), 0.5, 0.999)
        self.target_adapt_enable = bool(target_adapt_enable)
        self.target_adapt_rate = _clamp(float(target_adapt_rate), 0.001, 0.25)
        self.weight_adapt_rate = _clamp(float(weight_adapt_rate), 0.001, 0.25)
        self.promotion_target_hard_max = _clamp(float(promotion_target_hard_max), 0.45, 0.90)
        self.base_promotion_target = _clamp(
            float(base_promotion_target),
            0.45,
            self.promotion_target_hard_max,
        )
        self.phase_order = tuple(spec.phase_id for spec in phase_specs)
        self.phase_index_by_id = {
            phase_id: idx for idx, phase_id in enumerate(self.phase_order)
        }
        self.phase_spec_by_id = {spec.phase_id: spec for spec in phase_specs}
        self.early_target_cap_enable = bool(early_target_cap_enable)
        self.early_target_cap = _clamp(float(early_target_cap), 0.45, 0.90)
        self.early_target_cap_phase_count = max(0, int(early_target_cap_phase_count))
        self.early_target_cap_micro_max = max(0, int(early_target_cap_micro_max))
        self.weight_rebase_enable = bool(weight_rebase_enable)
        self.weight_rebase_alpha = _clamp(float(weight_rebase_alpha), 0.05, 0.95)
        self.weight_rebase_objective_boost = _clamp(
            float(weight_rebase_objective_boost), 0.0, 0.75
        )
        self.warmup_target_dampener_enable = bool(warmup_target_dampener_enable)
        self.warmup_target_dampener_observations = max(
            8, int(warmup_target_dampener_observations)
        )
        self.warmup_target_dampener_max_reduction = _clamp(
            float(warmup_target_dampener_max_reduction), 0.0, 0.40
        )
        self.target_raise_only_when_score_ready = bool(target_raise_only_when_score_ready)
        self.target_freeze_after_observation_gate = bool(target_freeze_after_observation_gate)
        self.target_deficit_relief_rate = _clamp(float(target_deficit_relief_rate), 0.0, 0.75)
        self.target_deficit_margin = _clamp(float(target_deficit_margin), 0.0, 0.12)
        self.phase_state: dict[str, AdaptivePhaseRuntime] = {
            spec.phase_id: AdaptivePhaseRuntime(
                phase_id=spec.phase_id,
                enabled=True,
                promotion_target=float(self.base_promotion_target),
            )
            for spec in phase_specs
        }
        self.adaptive_weights: dict[str, float] = {
            "train": 0.22,
            "integrate": 0.22,
            "stability": 0.20,
            "transfer": 0.20,
            "safety": 0.12,
            "introspection": 0.04,
        }
        self.completed_micro_total = 0

    def _resolve_manual_phase_id(self, phase_id: str | None=None) -> str | None:
        if phase_id is not None:
            key = str(phase_id).strip()
            if key in self.phase_state:
                return key
        active = self.current_active_target()
        if active is not None:
            return str(active[0])
        for candidate in self.phase_order:
            if not self.phase_state[candidate].completed:
                return candidate
        if self.phase_order:
            return self.phase_order[-1]
        return None

    def _recompute_completed_micro_total(self) -> None:
        total = 0
        for phase_id in self.phase_order:
            spec = self.phase_spec_by_id[phase_id]
            state = self.phase_state[phase_id]
            if state.completed:
                total += len(spec.micro_stages)
            else:
                total += max(0, min(int(state.micro_index), len(spec.micro_stages)))
        self.completed_micro_total = max(0, int(total))

    def manual_advance_micro(self, phase_id: str | None=None) -> AdaptivePhaseTransition | None:
        resolved_phase_id = self._resolve_manual_phase_id(phase_id)
        if resolved_phase_id is None:
            return None
        spec = self.phase_spec_by_id[resolved_phase_id]
        state = self.phase_state[resolved_phase_id]
        max_index = len(spec.micro_stages) - 1
        if state.completed:
            return None
        from_micro = int(state.micro_index)
        if state.micro_index < max_index:
            state.micro_index += 1
            state.observations = 0
            self._recompute_completed_micro_total()
            return AdaptivePhaseTransition(
                phase_id=resolved_phase_id,
                from_micro=from_micro,
                to_micro=int(state.micro_index),
                completed_phase=False,
                reason='manual_advance_micro',
            )
        state.completed = True
        state.observations = 0
        self._recompute_completed_micro_total()
        return AdaptivePhaseTransition(
            phase_id=resolved_phase_id,
            from_micro=from_micro,
            to_micro=int(state.micro_index),
            completed_phase=True,
            reason='manual_complete_phase_from_micro',
        )

    def manual_regress_micro(self, phase_id: str | None=None) -> AdaptivePhaseTransition | None:
        resolved_phase_id = self._resolve_manual_phase_id(phase_id)
        if resolved_phase_id is None:
            return None
        spec = self.phase_spec_by_id[resolved_phase_id]
        state = self.phase_state[resolved_phase_id]
        max_index = len(spec.micro_stages) - 1
        from_micro = int(state.micro_index)
        if state.completed:
            state.completed = False
            state.micro_index = max_index
            state.observations = 0
            self._recompute_completed_micro_total()
            return AdaptivePhaseTransition(
                phase_id=resolved_phase_id,
                from_micro=from_micro,
                to_micro=int(state.micro_index),
                completed_phase=False,
                reason='manual_reopen_phase',
            )
        if state.micro_index <= 0:
            return None
        state.micro_index -= 1
        state.observations = 0
        self._recompute_completed_micro_total()
        return AdaptivePhaseTransition(
            phase_id=resolved_phase_id,
            from_micro=from_micro,
            to_micro=int(state.micro_index),
            completed_phase=False,
            reason='manual_regress_micro',
        )

    def manual_advance_phase(self, phase_id: str | None=None) -> AdaptivePhaseTransition | None:
        resolved_phase_id = self._resolve_manual_phase_id(phase_id)
        if resolved_phase_id is None:
            return None
        spec = self.phase_spec_by_id[resolved_phase_id]
        state = self.phase_state[resolved_phase_id]
        if state.completed:
            return None
        from_micro = int(state.micro_index)
        state.micro_index = len(spec.micro_stages) - 1
        state.completed = True
        state.observations = 0
        self._recompute_completed_micro_total()
        return AdaptivePhaseTransition(
            phase_id=resolved_phase_id,
            from_micro=from_micro,
            to_micro=int(state.micro_index),
            completed_phase=True,
            reason='manual_advance_phase',
        )

    def manual_regress_phase(self, phase_id: str | None=None) -> AdaptivePhaseTransition | None:
        resolved_phase_id = self._resolve_manual_phase_id(phase_id)
        if resolved_phase_id is None:
            return None
        try:
            current_index = self.phase_order.index(resolved_phase_id)
        except ValueError:
            return None
        if current_index <= 0:
            return None
        target_phase_id = self.phase_order[current_index - 1]
        target_state = self.phase_state[target_phase_id]
        from_micro = int(target_state.micro_index)
        target_state.enabled = True
        target_state.completed = False
        target_state.micro_index = 0
        target_state.observations = 0
        self._recompute_completed_micro_total()
        return AdaptivePhaseTransition(
            phase_id=target_phase_id,
            from_micro=from_micro,
            to_micro=0,
            completed_phase=False,
            reason='manual_regress_phase',
        )

    def set_phase_enabled(self, phase_id: str, enabled: bool) -> None:
        if phase_id not in self.phase_state:
            raise KeyError(f"unknown phase_id: {phase_id}")
        self.phase_state[phase_id].enabled = bool(enabled)

    def set_disabled_phase_ids(self, phase_ids: tuple[str, ...]) -> None:
        disabled = set(phase_ids)
        for phase_id, state in self.phase_state.items():
            state.enabled = phase_id not in disabled

    def current_active_target(self) -> tuple[str, str] | None:
        for phase_id in self.phase_order:
            state = self.phase_state[phase_id]
            if (not state.enabled) or state.completed:
                continue
            phase_spec = self.phase_spec_by_id[phase_id]
            stage_index = max(0, min(state.micro_index, len(phase_spec.micro_stages) - 1))
            return (phase_id, phase_spec.micro_stages[stage_index].stage_id)
        return None

    def observe_micro_metrics(
        self,
        phase_id: str,
        *,
        train_quality: float,
        integration_quality: float,
        stability: float,
        transfer: float,
        safety: float,
        introspection_gain: float,
        autostep_enabled: bool = True,
        observation_floor: int | None = None,
    ) -> AdaptivePhaseTransition | None:
        if phase_id not in self.phase_state:
            raise KeyError(f"unknown phase_id: {phase_id}")
        phase_spec = self.phase_spec_by_id[phase_id]
        state = self.phase_state[phase_id]
        if state.completed:
            state.last_blocked_reason = "phase_completed"
            return None
        stage = phase_spec.micro_stages[state.micro_index]

        keep = self.ema_decay
        blend = 1.0 - keep

        train_quality = _clamp(float(train_quality), 0.0, 1.0)
        integration_quality = _clamp(float(integration_quality), 0.0, 1.0)
        stability = _clamp(float(stability), 0.0, 1.0)
        transfer = _clamp(float(transfer), 0.0, 1.0)
        safety = _clamp(float(safety), 0.0, 1.0)
        introspection_gain = _clamp(float(introspection_gain), 0.0, 1.0)

        state.train_ema = (state.train_ema * keep) + (train_quality * blend)
        state.integrate_ema = (state.integrate_ema * keep) + (integration_quality * blend)
        state.stability_ema = (state.stability_ema * keep) + (stability * blend)
        state.transfer_ema = (state.transfer_ema * keep) + (transfer * blend)
        state.safety_ema = (state.safety_ema * keep) + (safety * blend)
        state.introspection_ema = (state.introspection_ema * keep) + (
            introspection_gain * blend
        )
        state.observations += 1

        effective_min_observations = int(stage.min_observations)
        if isinstance(observation_floor, int) and observation_floor >= 0:
            effective_min_observations = max(effective_min_observations, int(observation_floor))

        if state.observations == 1:
            self._maybe_rebase_weights_for_stage_entry(stage)
        self._adapt_weights(state)
        state.score_ema = self._composite_score(state)
        allow_target_raise = True
        if self.target_raise_only_when_score_ready and state.observations >= effective_min_observations:
            allow_target_raise = bool(state.score_ema >= state.promotion_target)
        self._adapt_target(
            state,
            phase_id=phase_id,
            effective_min_observations=effective_min_observations,
            allow_raise=allow_target_raise,
            gate_eligible=bool(state.observations >= effective_min_observations),
        )

        state.last_autostep_enabled = bool(autostep_enabled)
        state.last_effective_min_observations = int(effective_min_observations)

        safety_floor = max(0.42, state.promotion_target - 0.14)
        stability_floor = max(0.40, state.promotion_target - 0.16)
        transfer_floor = max(0.18, state.promotion_target - 0.34)
        state.last_safety_floor = float(safety_floor)
        state.last_stability_floor = float(stability_floor)
        state.last_transfer_floor = float(transfer_floor)

        if not state.enabled:
            state.last_blocked_reason = "phase_disabled"
            return None
        if state.observations < effective_min_observations:
            state.last_blocked_reason = (
                f"observations_below_min({int(state.observations)}<{int(effective_min_observations)})"
            )
            return None
        if not bool(autostep_enabled):
            state.last_blocked_reason = "autostep_disabled"
            return None

        score_ok = state.score_ema >= state.promotion_target
        safety_ok = state.safety_ema >= safety_floor
        stability_ok = state.stability_ema >= stability_floor
        transfer_ok = state.transfer_ema >= transfer_floor
        promote = bool(score_ok and safety_ok and stability_ok and transfer_ok)
        if not promote:
            if not score_ok:
                state.last_blocked_reason = (
                    f"score_below_target({state.score_ema:.4f}<{state.promotion_target:.4f})"
                )
            elif not safety_ok:
                state.last_blocked_reason = (
                    f"safety_below_floor({state.safety_ema:.4f}<{safety_floor:.4f})"
                )
            elif not transfer_ok:
                state.last_blocked_reason = (
                    f"transfer_below_floor({state.transfer_ema:.4f}<{transfer_floor:.4f})"
                )
            else:
                state.last_blocked_reason = (
                    f"stability_below_floor({state.stability_ema:.4f}<{stability_floor:.4f})"
                )
            return None
        state.last_blocked_reason = "promotion_ready"

        prior_micro = state.micro_index
        if state.micro_index + 1 < len(phase_spec.micro_stages):
            state.micro_index += 1
            state.observations = 0
            self.completed_micro_total += 1
            return AdaptivePhaseTransition(
                phase_id=phase_id,
                from_micro=prior_micro,
                to_micro=state.micro_index,
                completed_phase=False,
                reason=(
                    f"promoted stage={stage.stage_id} score={round(state.score_ema, 4)} "
                    f"target={round(state.promotion_target, 4)}"
                ),
            )

        state.completed = True
        self.completed_micro_total += 1
        return AdaptivePhaseTransition(
            phase_id=phase_id,
            from_micro=prior_micro,
            to_micro=prior_micro,
            completed_phase=True,
            reason=(
                f"completed phase score={round(state.score_ema, 4)} "
                f"target={round(state.promotion_target, 4)}"
            ),
        )

    def _composite_score(self, state: AdaptivePhaseRuntime) -> float:
        score = (
            (state.train_ema * self.adaptive_weights["train"])
            + (state.integrate_ema * self.adaptive_weights["integrate"])
            + (state.stability_ema * self.adaptive_weights["stability"])
            + (state.transfer_ema * self.adaptive_weights["transfer"])
            + (state.safety_ema * self.adaptive_weights["safety"])
            + (state.introspection_ema * self.adaptive_weights["introspection"])
        )
        return _clamp(score, 0.0, 1.0)

    def _early_target_cap_applies(self, *, phase_id: str, micro_index: int) -> bool:
        if not self.early_target_cap_enable:
            return False
        if self.early_target_cap_phase_count <= 0:
            return False
        phase_index = self.phase_index_by_id.get(phase_id)
        if phase_index is None:
            return False
        if int(phase_index) >= int(self.early_target_cap_phase_count):
            return False
        return int(micro_index) <= int(self.early_target_cap_micro_max)

    def _adapt_target(
        self,
        state: AdaptivePhaseRuntime,
        *,
        phase_id: str,
        effective_min_observations: int,
        allow_raise: bool,
        gate_eligible: bool,
    ) -> None:
        prior_target = float(state.promotion_target)

        # Hard disable for adaptive goalpost movement when requested.
        if not self.target_adapt_enable:
            state.promotion_target = _clamp(
                prior_target,
                self.base_promotion_target,
                self.promotion_target_hard_max,
            )
            return

        # Once a stage has enough observations, keep the quality bar stable by
        # default so promotion can be decided on score quality, not target drift.
        if gate_eligible and self.target_freeze_after_observation_gate:
            state.promotion_target = _clamp(
                prior_target,
                self.base_promotion_target,
                self.promotion_target_hard_max,
            )
            return

        robustness = (
            (state.stability_ema * 0.35)
            + (state.transfer_ema * 0.35)
            + (state.safety_ema * 0.20)
            + (state.introspection_ema * 0.10)
        )
        adaptive_target = _clamp(0.50 + (robustness * 0.38), 0.45, 0.90)
        target_candidate = _clamp(
            ((1.0 - self.target_adapt_rate) * state.promotion_target)
            + (self.target_adapt_rate * adaptive_target),
            self.base_promotion_target,
            self.promotion_target_hard_max,
        )

        if not bool(allow_raise):
            target_candidate = min(target_candidate, prior_target)

        if (
            int(state.observations) >= int(max(0, effective_min_observations))
            and float(state.score_ema) < prior_target
            and self.target_deficit_relief_rate > 0.0
        ):
            relief_anchor = _clamp(
                float(state.score_ema) + float(self.target_deficit_margin),
                self.base_promotion_target,
                self.promotion_target_hard_max,
            )
            target_candidate = (
                ((1.0 - self.target_deficit_relief_rate) * target_candidate)
                + (self.target_deficit_relief_rate * relief_anchor)
            )
            target_candidate = min(target_candidate, prior_target)

        state.promotion_target = _clamp(
            float(target_candidate),
            self.base_promotion_target,
            self.promotion_target_hard_max,
        )

        if self._early_target_cap_applies(
            phase_id=phase_id, micro_index=int(state.micro_index)
        ):
            state.promotion_target = min(
                state.promotion_target,
                min(
                    max(self.early_target_cap, self.base_promotion_target),
                    self.promotion_target_hard_max,
                ),
            )

        if self.warmup_target_dampener_enable:
            warmup_ratio = _clamp(
                float(state.observations)
                / float(max(1, self.warmup_target_dampener_observations)),
                0.0,
                1.0,
            )
            damp_delta = (1.0 - warmup_ratio) * self.warmup_target_dampener_max_reduction
            if damp_delta > 0.0 and int(state.observations) < int(max(0, effective_min_observations)):
                state.promotion_target = _clamp(
                    state.promotion_target - damp_delta,
                    self.base_promotion_target,
                    self.promotion_target_hard_max,
                )

    def _objective_weight_key(self, signal: str) -> str | None:
        token = str(signal or "").strip().lower()
        mapping = {
            "train_quality": "train",
            "integration_quality": "integrate",
            "stability": "stability",
            "transfer": "transfer",
            "safety": "safety",
            "introspection_gain": "introspection",
        }
        return mapping.get(token)

    def _rebase_weight_target(self, objective_signals: tuple[str, ...]) -> dict[str, float]:
        target = {
            "train": 0.18,
            "integrate": 0.18,
            "stability": 0.18,
            "transfer": 0.18,
            "safety": 0.18,
            "introspection": 0.10,
        }
        objective_keys: list[str] = []
        for signal in objective_signals:
            key = self._objective_weight_key(signal)
            if key and key not in objective_keys:
                objective_keys.append(key)
        if objective_keys:
            boost = self.weight_rebase_objective_boost / float(len(objective_keys))
            for key in objective_keys:
                target[key] = target.get(key, 0.0) + boost
        norm = sum(target.values())
        if norm <= 0.0:
            return dict(self.adaptive_weights)
        return {key: value / norm for key, value in target.items()}

    def _maybe_rebase_weights_for_stage_entry(self, stage: MicroStageSpec) -> None:
        if not self.weight_rebase_enable:
            return
        target = self._rebase_weight_target(tuple(stage.objective_signals or ()))
        alpha = self.weight_rebase_alpha
        for key in tuple(self.adaptive_weights.keys()):
            current = float(self.adaptive_weights.get(key, 0.0))
            desired = float(target.get(key, current))
            self.adaptive_weights[key] = _clamp(
                ((1.0 - alpha) * current) + (alpha * desired),
                0.02,
                0.60,
            )
        norm = sum(self.adaptive_weights.values())
        if norm > 0.0:
            for key in tuple(self.adaptive_weights.keys()):
                self.adaptive_weights[key] = self.adaptive_weights[key] / norm

    def _adapt_weights(self, state: AdaptivePhaseRuntime) -> None:
        transfer_signal = state.transfer_ema
        contributions = {
            "train": state.train_ema,
            "integrate": state.integrate_ema,
            "stability": state.stability_ema,
            "transfer": state.transfer_ema,
            "safety": state.safety_ema,
            "introspection": state.introspection_ema,
        }
        for key, value in contributions.items():
            centered = value - 0.5
            error = transfer_signal - state.score_ema
            updated = self.adaptive_weights[key] + (self.weight_adapt_rate * error * centered)
            self.adaptive_weights[key] = _clamp(updated, 0.02, 0.60)

        norm = sum(self.adaptive_weights.values())
        if norm <= 0.0:
            return
        for key in list(self.adaptive_weights.keys()):
            self.adaptive_weights[key] = self.adaptive_weights[key] / norm

    def snapshot(self) -> dict[str, object]:
        phases: list[dict[str, object]] = []
        completed_phase_count = 0
        for phase_id in self.phase_order:
            spec = self.phase_spec_by_id[phase_id]
            state = self.phase_state[phase_id]
            if state.completed:
                completed_phase_count += 1
            stage = spec.micro_stages[min(state.micro_index, len(spec.micro_stages) - 1)]
            early_target_cap_applied = int(
                self._early_target_cap_applies(
                    phase_id=phase_id, micro_index=int(state.micro_index)
                )
            )
            effective_min_observations = int(
                state.last_effective_min_observations
                if state.last_effective_min_observations > 0
                else int(stage.min_observations)
            )
            safety_floor = float(state.last_safety_floor)
            if safety_floor <= 0.0:
                safety_floor = float(max(0.42, state.promotion_target - 0.14))
            stability_floor = float(state.last_stability_floor)
            if stability_floor <= 0.0:
                stability_floor = float(max(0.40, state.promotion_target - 0.16))
            transfer_floor = float(state.last_transfer_floor)
            if transfer_floor <= 0.0:
                transfer_floor = float(max(0.18, state.promotion_target - 0.34))
            promotion_gate_ready = int(int(state.observations) >= int(effective_min_observations))
            promotion_gate_met = int(
                (state.score_ema >= state.promotion_target)
                and (state.safety_ema >= safety_floor)
                and (state.stability_ema >= stability_floor)
                and (state.transfer_ema >= transfer_floor)
            )
            phases.append(
                {
                    "phase_id": phase_id,
                    "label": spec.label,
                    "enabled": int(state.enabled),
                    "completed": int(state.completed),
                    "micro_index": int(state.micro_index),
                    "current_stage_id": stage.stage_id,
                    "observations": int(state.observations),
                    "score_ema": round(state.score_ema, 4),
                    "promotion_target": round(state.promotion_target, 4),
                    "early_target_cap_applied": int(early_target_cap_applied),
                    "effective_min_observations": int(effective_min_observations),
                    "safety_floor": round(float(safety_floor), 4),
                    "stability_floor": round(float(stability_floor), 4),
                    "transfer_floor": round(float(transfer_floor), 4),
                    "promotion_blocked_reason": str(state.last_blocked_reason or ""),
                    "last_autostep_enabled": int(bool(state.last_autostep_enabled)),
                    "promotion_gate_ready": int(promotion_gate_ready),
                    "promotion_gate_met": int(promotion_gate_met),
                    "train_ema": round(state.train_ema, 4),
                    "integrate_ema": round(state.integrate_ema, 4),
                    "stability_ema": round(state.stability_ema, 4),
                    "transfer_ema": round(state.transfer_ema, 4),
                    "safety_ema": round(state.safety_ema, 4),
                    "introspection_ema": round(state.introspection_ema, 4),
                }
            )
        return {
            "completed_micro_total": int(self.completed_micro_total),
            "completed_phase_count": int(completed_phase_count),
            "active_target": self.current_active_target(),
            "base_promotion_target": round(float(self.base_promotion_target), 4),
            "target_adapt_enable": int(bool(self.target_adapt_enable)),
            "target_adapt_rate": round(float(self.target_adapt_rate), 4),
            "promotion_target_hard_max": round(float(self.promotion_target_hard_max), 4),
            "early_target_cap_enable": int(bool(self.early_target_cap_enable)),
            "early_target_cap": round(float(self.early_target_cap), 4),
            "early_target_cap_phase_count": int(self.early_target_cap_phase_count),
            "early_target_cap_micro_max": int(self.early_target_cap_micro_max),
            "weight_rebase_enable": int(bool(self.weight_rebase_enable)),
            "weight_rebase_alpha": round(float(self.weight_rebase_alpha), 4),
            "weight_rebase_objective_boost": round(float(self.weight_rebase_objective_boost), 4),
            "warmup_target_dampener_enable": int(bool(self.warmup_target_dampener_enable)),
            "warmup_target_dampener_observations": int(self.warmup_target_dampener_observations),
            "warmup_target_dampener_max_reduction": round(float(self.warmup_target_dampener_max_reduction), 4),
            "target_raise_only_when_score_ready": int(bool(self.target_raise_only_when_score_ready)),
            "target_freeze_after_observation_gate": int(bool(self.target_freeze_after_observation_gate)),
            "target_deficit_relief_rate": round(float(self.target_deficit_relief_rate), 4),
            "target_deficit_margin": round(float(self.target_deficit_margin), 4),
            "adaptive_weights": {
                key: round(value, 4) for key, value in self.adaptive_weights.items()
            },
            "phases": phases,
        }

    def restore_snapshot(self, payload: dict[str, object]) -> bool:
        if not isinstance(payload, dict):
            return False
        phases = payload.get("phases")
        if not isinstance(phases, list):
            return False

        def _as_bool(value: object, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(int(value))
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
            return default

        def _as_int(value: object, default: int) -> int:
            try:
                return int(value)  # type: ignore[arg-type]
            except Exception:
                return int(default)

        def _as_float(value: object, default: float) -> float:
            try:
                return float(value)  # type: ignore[arg-type]
            except Exception:
                return float(default)

        phase_rows: dict[str, dict[str, object]] = {}
        for row in phases:
            if not isinstance(row, dict):
                continue
            phase_id = str(row.get("phase_id", "")).strip()
            if phase_id in self.phase_state:
                phase_rows[phase_id] = row

        if not phase_rows:
            return False

        for phase_id in self.phase_order:
            state = self.phase_state[phase_id]
            row = phase_rows.get(phase_id)
            if row is None:
                continue
            spec = self.phase_spec_by_id[phase_id]
            max_index = max(0, len(spec.micro_stages) - 1)

            restored_micro = _as_int(row.get("micro_index", state.micro_index), state.micro_index)
            state.micro_index = max(0, min(restored_micro, max_index))
            state.completed = _as_bool(row.get("completed", state.completed), state.completed)
            if state.completed:
                state.micro_index = max_index
            state.observations = max(0, _as_int(row.get("observations", state.observations), state.observations))
            state.score_ema = _clamp(_as_float(row.get("score_ema", state.score_ema), state.score_ema), 0.0, 1.0)
            state.train_ema = _clamp(_as_float(row.get("train_ema", state.train_ema), state.train_ema), 0.0, 1.0)
            state.integrate_ema = _clamp(_as_float(row.get("integrate_ema", state.integrate_ema), state.integrate_ema), 0.0, 1.0)
            state.stability_ema = _clamp(_as_float(row.get("stability_ema", state.stability_ema), state.stability_ema), 0.0, 1.0)
            state.transfer_ema = _clamp(_as_float(row.get("transfer_ema", state.transfer_ema), state.transfer_ema), 0.0, 1.0)
            state.safety_ema = _clamp(_as_float(row.get("safety_ema", state.safety_ema), state.safety_ema), 0.0, 1.0)
            state.introspection_ema = _clamp(_as_float(row.get("introspection_ema", state.introspection_ema), state.introspection_ema), 0.0, 1.0)
            state.promotion_target = _clamp(
                _as_float(row.get("promotion_target", state.promotion_target), state.promotion_target),
                self.base_promotion_target,
                self.promotion_target_hard_max,
            )

        adaptive_weights = payload.get("adaptive_weights")
        if isinstance(adaptive_weights, dict):
            for key in tuple(self.adaptive_weights.keys()):
                if key not in adaptive_weights:
                    continue
                self.adaptive_weights[key] = _clamp(
                    _as_float(adaptive_weights.get(key), self.adaptive_weights[key]),
                    0.02,
                    0.60,
                )
            norm = sum(self.adaptive_weights.values())
            if norm > 0.0:
                for key in tuple(self.adaptive_weights.keys()):
                    self.adaptive_weights[key] = self.adaptive_weights[key] / norm

        self._recompute_completed_micro_total()
        return True


def build_default_kernel_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    def _micro(
        stage_prefix: str,
        module_id: str,
        *,
        stage_labels: tuple[str, str, str, str],
        stage_modes: tuple[str, str, str, str],
        module_targets: tuple[str, ...],
        objective_signals: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
        min_observations: tuple[int, int, int, int] = (64, 80, 96, 112),
    ) -> tuple[MicroStageSpec, ...]:
        return (
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m1_shadow_train",
                label=stage_labels[0],
                mode=stage_modes[0],
                module_targets=module_targets,
                objective_signals=objective_signals[0],
                min_observations=max(16, int(min_observations[0])),
            ),
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m2_counterfactual_train",
                label=stage_labels[1],
                mode=stage_modes[1],
                module_targets=module_targets,
                objective_signals=objective_signals[1],
                min_observations=max(16, int(min_observations[1])),
            ),
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m3_advisory_integrate",
                label=stage_labels[2],
                mode=stage_modes[2],
                module_targets=module_targets,
                objective_signals=objective_signals[2],
                min_observations=max(16, int(min_observations[2])),
            ),
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m4_control_integrate",
                label=stage_labels[3],
                mode=stage_modes[3],
                module_targets=module_targets,
                objective_signals=objective_signals[3],
                min_observations=max(16, int(min_observations[3])),
            ),
        )

    return (
        AdaptivePhaseSpec(
            phase_id="phase_1_guess_ledger",
            label="Guess Ledger",
            capability="assumption provenance and uncertainty lineage",
            module_id="guess_ledger",
            micro_stages=_micro(
                "p1",
                "guess_ledger",
                stage_labels=(
                    "Assumption ledger shadow capture",
                    "Counterfactual assumption replay",
                    "Uncertainty advisory integration",
                    "Bounded assumption control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "guess_ledger",
                    "learned_autonomy_controller",
                    "governance_orchestrator",
                ),
                objective_signals=(
                    ("train_quality", "stability", "introspection_gain"),
                    ("train_quality", "transfer", "introspection_gain"),
                    ("integration_quality", "safety", "stability"),
                    ("integration_quality", "transfer", "safety"),
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_2_contradiction_accounting",
            label="Contradiction Accounting",
            capability="contradiction debt and assumption blame",
            module_id="contradiction_accounting",
            micro_stages=_micro(
                "p2",
                "contradiction_accounting",
                stage_labels=(
                    "Contradiction debt shadow trace",
                    "Counterfactual contradiction replay",
                    "Contradiction advisory integration",
                    "Bounded contradiction control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "contradiction_accounting",
                    "parallel_reasoning_engine",
                    "governance_orchestrator",
                ),
                objective_signals=(
                    ("train_quality", "introspection_gain", "stability"),
                    ("train_quality", "safety", "stability"),
                    ("integration_quality", "transfer", "safety"),
                    ("integration_quality", "transfer", "stability"),
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_3_falsification_planner",
            label="Falsification Planner",
            capability="information-gain-driven falsification moves",
            module_id="falsification_planner",
            micro_stages=_micro(
                "p3",
                "falsification_planner",
                stage_labels=(
                    "Falsification shadow planning",
                    "Counterfactual falsification replay",
                    "Falsification advisory integration",
                    "Bounded falsification control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "falsification_planner",
                    "parallel_reasoning_engine",
                    "adaptive_controller",
                    "learned_autonomy_controller",
                ),
                objective_signals=(
                    ("train_quality", "transfer", "introspection_gain"),
                    ("train_quality", "stability", "safety"),
                    ("integration_quality", "transfer", "stability"),
                    ("integration_quality", "transfer", "safety"),
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_4_metric_decoupler",
            label="Metric Decoupler",
            capability="separate optimization signals from evaluation signals",
            module_id="metric_decoupler",
            micro_stages=_micro(
                "p4",
                "metric_decoupler",
                stage_labels=(
                    "Metric decoupling shadow audit",
                    "Counterfactual metric replay",
                    "Metric advisory integration",
                    "Bounded metric control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "metric_decoupler",
                    "governance_orchestrator",
                    "parallel_reasoning_engine",
                    "learned_autonomy_controller",
                ),
                objective_signals=(
                    ("train_quality", "safety", "introspection_gain"),
                    ("train_quality", "stability", "safety"),
                    ("integration_quality", "safety", "stability"),
                    ("integration_quality", "safety", "transfer"),
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_5_abstraction_memory",
            label="Abstraction Memory",
            capability="reusable motifs, compositional transfer, schema reuse",
            module_id="abstraction_memory",
            micro_stages=_micro(
                "p5",
                "abstraction_memory",
                stage_labels=(
                    "Abstraction motif shadow capture",
                    "Counterfactual schema replay",
                    "Abstraction advisory integration",
                    "Bounded abstraction control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "abstraction_memory",
                    "adaptive_controller",
                    "organism_control",
                    "maze_agent",
                ),
                objective_signals=(
                    ("train_quality", "stability", "safety"),
                    ("train_quality", "transfer", "safety"),
                    ("integration_quality", "stability", "transfer"),
                    ("integration_quality", "safety", "transfer"),
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_6_causal_counterfactual_planner",
            label="Causal Counterfactual Planner",
            capability="bounded causal what-if planning before irreversible actions",
            module_id="causal_counterfactual_planner",
            micro_stages=_micro(
                "p6",
                "causal_counterfactual_planner",
                stage_labels=(
                    "Causal what-if shadow trace",
                    "Counterfactual consequence replay",
                    "Causal advisory integration",
                    "Bounded causal control",
                ),
                stage_modes=("train", "train", "integrate", "control_integrate"),
                module_targets=(
                    "causal_counterfactual_planner",
                    "parallel_reasoning_engine",
                    "maze_agent",
                    "governance_orchestrator",
                ),
                objective_signals=(
                    ("train_quality", "introspection_gain", "stability"),
                    ("train_quality", "transfer", "safety"),
                    ("integration_quality", "transfer", "stability"),
                    ("integration_quality", "transfer", "safety"),
                ),
            ),
        ),
    )
