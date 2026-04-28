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
    impact_rank: int = 0
    impact_label: str = ""
    env_type_group: str = ""
    env_key_count: int = 0
    ownership_action: str = ""
    execution_system: str = ""
    env_prefixes: tuple[str, ...] = ()


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
        self.phase_set_signature = self._build_phase_set_signature()
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

    def _build_phase_set_signature(self) -> str:
        chunks: list[str] = []
        for spec in self.phase_specs:
            stage_ids = ",".join((str(stage.stage_id) for stage in spec.micro_stages))
            chunks.append(f"{spec.phase_id}[{stage_ids}]")
        return "||".join(chunks)

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
            # Once the observation gate is met, pin threshold to the base target
            # so promotion is decided on score quality and not a raised goalpost.
            state.promotion_target = _clamp(
                self.base_promotion_target,
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
                    "current_stage_label": str(stage.label),
                    "current_stage_impact_rank": int(getattr(stage, "impact_rank", 0) or 0),
                    "current_stage_impact_label": str(getattr(stage, "impact_label", "") or ""),
                    "current_stage_env_type_group": str(getattr(stage, "env_type_group", "") or ""),
                    "current_stage_env_key_count": int(getattr(stage, "env_key_count", 0) or 0),
                    "current_stage_ownership_action": str(getattr(stage, "ownership_action", "") or ""),
                    "current_stage_execution_system": str(getattr(stage, "execution_system", "") or ""),
                    "current_stage_env_prefixes": list(tuple(getattr(stage, "env_prefixes", ()) or ())),
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
            "phase_set_signature": str(self.phase_set_signature),
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
        payload_signature = str(payload.get("phase_set_signature", "") or "").strip()
        if payload_signature != str(self.phase_set_signature):
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
            # Normalize restored targets so a previously raised threshold cannot
            # persist past the observation gate boundary.
            stage = spec.micro_stages[max(0, min(state.micro_index, max_index))]
            if self.target_freeze_after_observation_gate and state.observations >= int(stage.min_observations):
                state.promotion_target = _clamp(
                    self.base_promotion_target,
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


def build_mv_localization_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    def _stage(
        stage_id: str,
        label: str,
        *,
        mode: str,
        module_targets: tuple[str, ...],
        objective_signals: tuple[str, ...],
        min_observations: int,
        impact_rank: int = 0,
        impact_label: str = "",
        env_type_group: str = "",
        env_key_count: int = 0,
        ownership_action: str = "",
        execution_system: str = "",
        env_prefixes: tuple[str, ...] = (),
    ) -> MicroStageSpec:
        return MicroStageSpec(
            stage_id=str(stage_id),
            label=str(label),
            mode=str(mode),
            module_targets=tuple(module_targets),
            objective_signals=tuple(objective_signals),
            min_observations=max(16, int(min_observations)),
            impact_rank=max(0, int(impact_rank)),
            impact_label=str(impact_label),
            env_type_group=str(env_type_group),
            env_key_count=max(0, int(env_key_count)),
            ownership_action=str(ownership_action),
            execution_system=str(execution_system),
            env_prefixes=tuple((str(prefix).strip() for prefix in tuple(env_prefixes) if str(prefix).strip())),
        )

    mvt0_instrumentation_targets = (
        "adaptive_controller",
        "parallel_reasoning_engine",
        "governance_orchestrator",
        "causal_counterfactual_planner",
    )
    mvt1_routing_targets = (
        "learned_autonomy_controller",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
    )
    mvt2_intervention_targets = (
        "parallel_reasoning_engine",
        "learned_autonomy_controller",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
        "governance_orchestrator",
    )
    mvt3_memory_targets = (
        "learned_autonomy_controller",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
        "causal_counterfactual_planner",
    )
    mvt4_override_targets = (
        "parallel_reasoning_engine",
        "learned_autonomy_controller",
        "adaptive_controller",
        "governance_orchestrator",
    )
    mvt5_validation_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "causal_counterfactual_planner",
    )

    return (
        AdaptivePhaseSpec(
            phase_id="phase_mvt0_instrumentation_and_gate_reliability",
            label="Phase MVT0 - Instrumentation and Gate Reliability",
            capability="stabilize parser/gate telemetry and intervention taxonomy before behavior tuning",
            module_id="mvt0_instrumentation_and_gate_reliability",
            micro_stages=(
                _stage(
                    "mvt0.m1_preflight_parser_hardening",
                    "MVT0.1 Preflight parser hardening",
                    mode="integrate",
                    module_targets=mvt0_instrumentation_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=56,
                ),
                _stage(
                    "mvt0.m2_intervention_taxonomy_lock",
                    "MVT0.2 Intervention taxonomy lock",
                    mode="control_integrate",
                    module_targets=mvt0_instrumentation_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=72,
                ),
                _stage(
                    "mvt0.m3_reasoning_conf_signal_enable",
                    "MVT0.3 Reasoning confidence signal enable",
                    mode="control_integrate",
                    module_targets=mvt0_instrumentation_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=84,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_mvt1_mv_to_learned_routing_bias_lift",
            label="Phase MVT1 - MV to Learned Routing Bias Lift",
            capability="raise learned-path MV routing share while reducing unknown and mixed routing leakage",
            module_id="mvt1_mv_to_learned_routing_bias_lift",
            micro_stages=(
                _stage(
                    "mvt1.m1_mv_prior_weight_rebalance",
                    "MVT1.1 MV prior weight rebalance",
                    mode="integrate",
                    module_targets=mvt1_routing_targets,
                    objective_signals=("integration_quality", "transfer", "stability"),
                    min_observations=76,
                ),
                _stage(
                    "mvt1.m2_mv_disagreement_dynamic_relief",
                    "MVT1.2 MV disagreement dynamic relief",
                    mode="integrate",
                    module_targets=mvt1_routing_targets,
                    objective_signals=("integration_quality", "transfer", "safety"),
                    min_observations=88,
                ),
                _stage(
                    "mvt1.m3_objective_evidence_quality_gate",
                    "MVT1.3 Objective evidence quality gate",
                    mode="control_integrate",
                    module_targets=mvt1_routing_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=100,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_mvt2_intervention_rate_compression_soft_first",
            label="Phase MVT2 - Intervention Rate Compression (Soft-First)",
            capability="decrease intervention and objective overrides by exhausting learned soft substitutions first",
            module_id="mvt2_intervention_rate_compression_soft_first",
            micro_stages=(
                _stage(
                    "mvt2.m1_soft_substitution_before_override",
                    "MVT2.1 Soft substitution before override",
                    mode="control_integrate",
                    module_targets=mvt2_intervention_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=92,
                ),
                _stage(
                    "mvt2.m2_override_budget_strictness_tuning",
                    "MVT2.2 Override budget strictness tuning",
                    mode="control_integrate",
                    module_targets=mvt2_intervention_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=104,
                ),
                _stage(
                    "mvt2.m3_unresolved_context_override_guard",
                    "MVT2.3 Unresolved-context override guard",
                    mode="control_integrate",
                    module_targets=mvt2_intervention_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=116,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_mvt3_memory_driven_learned_selection_lift",
            label="Phase MVT3 - Memory-Driven Learned Selection Lift",
            capability="increase learned-only selection through stronger memory quality and uncertainty feedback integration",
            module_id="mvt3_memory_driven_learned_selection_lift",
            micro_stages=(
                _stage(
                    "mvt3.m1_cause_effect_priority_lift",
                    "MVT3.1 Cause-effect priority lift",
                    mode="integrate",
                    module_targets=mvt3_memory_targets,
                    objective_signals=("integration_quality", "transfer", "stability"),
                    min_observations=100,
                ),
                _stage(
                    "mvt3.m2_stm_to_semantic_promotion_quality_tuning",
                    "MVT3.2 STM to semantic promotion quality tuning",
                    mode="integrate",
                    module_targets=mvt3_memory_targets,
                    objective_signals=("integration_quality", "transfer", "safety"),
                    min_observations=112,
                ),
                _stage(
                    "mvt3.m3_pattern_uncertainty_feedback_loop",
                    "MVT3.3 Pattern uncertainty feedback loop",
                    mode="control_integrate",
                    module_targets=mvt3_memory_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=124,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_mvt4_objective_override_near_invisibility",
            label="Phase MVT4 - Objective Override Near-Invisibility",
            capability="push objective override behavior toward rare edge cases while preserving safety certainty",
            module_id="mvt4_objective_override_near_invisibility",
            micro_stages=(
                _stage(
                    "mvt4.m1_objective_excitement_soft_capture_refine",
                    "MVT4.1 Objective excitement soft-capture refine",
                    mode="control_integrate",
                    module_targets=mvt4_override_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=110,
                ),
                _stage(
                    "mvt4.m2_terminal_and_frontier_guard_coherence",
                    "MVT4.2 Terminal and frontier guard coherence",
                    mode="control_integrate",
                    module_targets=mvt4_override_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=122,
                ),
                _stage(
                    "mvt4.m3_phase_policy_cap_for_hardcoded_channel",
                    "MVT4.3 Phase policy cap for hardcoded channel",
                    mode="control_integrate",
                    module_targets=mvt4_override_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=134,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_mvt5_validation_rollout_and_freeze",
            label="Phase MVT5 - Validation, Rollout, and Freeze",
            capability="validate targets across hard windows, publish gates, and freeze guarded runtime defaults",
            module_id="mvt5_validation_rollout_and_freeze",
            micro_stages=(
                _stage(
                    "mvt5.m1_batch_validation_matrix",
                    "MVT5.1 Batch validation matrix",
                    mode="control_integrate",
                    module_targets=mvt5_validation_targets,
                    objective_signals=("integration_quality", "transfer", "safety"),
                    min_observations=120,
                ),
                _stage(
                    "mvt5.m2_canonical_report_and_gate_update",
                    "MVT5.2 Canonical report and gate update",
                    mode="control_integrate",
                    module_targets=mvt5_validation_targets,
                    objective_signals=("integration_quality", "transfer", "stability"),
                    min_observations=136,
                ),
                _stage(
                    "mvt5.m3_freeze_and_regression_guard",
                    "MVT5.3 Freeze and regression guard",
                    mode="control_integrate",
                    module_targets=mvt5_validation_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=152,
                ),
            ),
        ),
    )


def build_trust_lift_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Compatibility alias retained for runtime callers migrated from older plans."""
    return build_mv_localization_phase_specs()


def build_default_kernel_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Compatibility alias kept for existing callers in the runtime bootstrap path."""
    return build_mv_localization_phase_specs()
