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

    def current_baseline_target(self) -> tuple[str, str] | None:
        """Return the terminal/baseline stage when no active stage remains.

        This keeps runtime stage-gated controls anchored to the integrated end
        state (phase 9 / WB8) after all micro stages are completed.
        """
        for phase_id in reversed(self.phase_order):
            state = self.phase_state[phase_id]
            if not state.enabled:
                continue
            phase_spec = self.phase_spec_by_id[phase_id]
            if not phase_spec.micro_stages:
                continue
            stage_index = max(0, min(state.micro_index, len(phase_spec.micro_stages) - 1))
            return (phase_id, phase_spec.micro_stages[stage_index].stage_id)
        return None

    def current_or_baseline_target(self) -> tuple[str, str] | None:
        active_target = self.current_active_target()
        if active_target is not None:
            return active_target
        return self.current_baseline_target()

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
        self._align_weights_to_objectives_under_deficit(state=state, stage=stage)
        state.score_ema = self._composite_score(state)
        self._adapt_target(state)

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
    ) -> None:
        # Score floor is intentionally fixed to the base target. Dynamic goalpost
        # movement is disabled so promotion quality is evaluated against a stable bar.
        state.promotion_target = _clamp(
            self.base_promotion_target,
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

    def _align_weights_to_objectives_under_deficit(
        self,
        *,
        state: AdaptivePhaseRuntime,
        stage: MicroStageSpec,
    ) -> None:
        """Nudge adaptive weights toward stage objectives when score lags target.

        Entry-time rebasing can drift over long windows; this bounded correction
        keeps late-stage phases from stalling in transfer-heavy equilibria.
        """
        if not self.weight_rebase_enable:
            return
        deficit = max(0.0, float(state.promotion_target) - float(state.score_ema))
        if deficit <= 0.0:
            return
        target = self._rebase_weight_target(tuple(stage.objective_signals or ()))
        mode_token = str(getattr(stage, "mode", "") or "").strip().lower()
        align_rate = 0.03 + min(0.16, deficit * 0.90)
        if "control" in mode_token:
            align_rate *= 1.2
        align_rate = _clamp(align_rate, 0.02, 0.22)
        for key in tuple(self.adaptive_weights.keys()):
            current = float(self.adaptive_weights.get(key, 0.0))
            desired = float(target.get(key, current))
            self.adaptive_weights[key] = _clamp(
                ((1.0 - align_rate) * current) + (align_rate * desired),
                0.02,
                0.60,
            )
        norm = sum(self.adaptive_weights.values())
        if norm > 0.0:
            for key in tuple(self.adaptive_weights.keys()):
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
            "baseline_target": self.current_baseline_target(),
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

    def _snapshot_phase_rows(self, payload: object) -> dict[str, dict[str, object]]:
        if not isinstance(payload, dict):
            return {}
        phases = payload.get("phases")
        if not isinstance(phases, list):
            return {}
        rows: dict[str, dict[str, object]] = {}
        for row in phases:
            if not isinstance(row, dict):
                continue
            phase_id = str(row.get("phase_id", "") or "").strip()
            if phase_id:
                rows[phase_id] = row
        return rows

    def snapshot_is_compatible(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        payload_signature = str(payload.get("phase_set_signature", "") or "").strip()
        if payload_signature and payload_signature == str(self.phase_set_signature):
            return True
        rows = self._snapshot_phase_rows(payload)
        if not rows:
            phases = payload.get("phases")
            return isinstance(phases, list) and any((isinstance(row, dict) for row in phases))
        for phase_id in rows.keys():
            if phase_id in self.phase_state:
                return True
        # Allow cross-plan restore by progress-ratio mapping when IDs no longer match.
        return True

    def restore_snapshot(self, payload: dict[str, object]) -> bool:
        if not isinstance(payload, dict):
            return False
        phases = payload.get("phases")
        if not isinstance(phases, list):
            return False
        if not self.snapshot_is_compatible(payload):
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

        def _restore_state_from_row(
            *,
            state: AdaptivePhaseRuntime,
            spec: AdaptivePhaseSpec,
            row: dict[str, object],
        ) -> None:
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
            # Keep restored score floor pinned to base; do not carry forward any
            # previously raised promotion target from older snapshots.
            state.promotion_target = _clamp(
                self.base_promotion_target,
                self.base_promotion_target,
                self.promotion_target_hard_max,
            )

        snapshot_rows = self._snapshot_phase_rows(payload)
        phase_rows: dict[str, dict[str, object]] = {
            phase_id: row
            for phase_id, row in snapshot_rows.items()
            if phase_id in self.phase_state
        }

        if not phase_rows:
            payload_rows = [row for row in phases if isinstance(row, dict)]
            if not payload_rows:
                return False

            source_completed_micro_total = max(
                0,
                _as_int(payload.get("completed_micro_total", 0), 0),
            )
            source_total_micro = 0
            for row in payload_rows:
                src_micro_index = max(0, _as_int(row.get("micro_index", 0), 0))
                src_completed = _as_bool(row.get("completed", False), False)
                source_total_micro += src_micro_index + (1 if src_completed else 0)
            source_total_micro = max(1, int(source_total_micro))

            if source_completed_micro_total > 0:
                progress_ratio = _clamp(
                    float(source_completed_micro_total) / float(source_total_micro),
                    0.0,
                    1.0,
                )
            else:
                source_completed_phase_count = max(
                    0,
                    _as_int(payload.get("completed_phase_count", 0), 0),
                )
                source_phase_count = max(1, len(payload_rows))
                progress_ratio = _clamp(
                    float(source_completed_phase_count) / float(source_phase_count),
                    0.0,
                    1.0,
                )

            destination_total_micro = sum(
                max(1, len(spec.micro_stages)) for spec in self.phase_specs
            )
            remaining_completed_micro = max(
                0,
                int(round(progress_ratio * float(max(1, destination_total_micro)))),
            )

            source_last_index = max(0, len(payload_rows) - 1)
            destination_last_index = max(0, len(self.phase_order) - 1)

            for destination_index, phase_id in enumerate(self.phase_order):
                state = self.phase_state[phase_id]
                spec = self.phase_spec_by_id[phase_id]
                if destination_last_index > 0:
                    mapped_index = int(
                        round(
                            (float(destination_index) / float(destination_last_index))
                            * float(source_last_index)
                        )
                    )
                else:
                    mapped_index = 0
                mapped_index = max(0, min(source_last_index, mapped_index))
                mapped_row = payload_rows[mapped_index]
                _restore_state_from_row(state=state, spec=spec, row=mapped_row)

                stage_count = max(1, len(spec.micro_stages))
                if remaining_completed_micro >= stage_count:
                    state.completed = True
                    state.micro_index = max(0, stage_count - 1)
                    remaining_completed_micro -= stage_count
                else:
                    state.completed = False
                    state.micro_index = max(0, min(remaining_completed_micro, stage_count - 1))
                    remaining_completed_micro = 0

                state.promotion_target = _clamp(
                    self.base_promotion_target,
                    self.base_promotion_target,
                    self.promotion_target_hard_max,
                )

        else:
            for phase_id in self.phase_order:
                state = self.phase_state[phase_id]
                row = phase_rows.get(phase_id)
                if row is None:
                    continue
                spec = self.phase_spec_by_id[phase_id]
                _restore_state_from_row(state=state, spec=spec, row=row)

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


def build_mv_input_transition_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
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

    wb0_baseline_targets = (
        "adaptive_controller",
        "parallel_reasoning_engine",
        "governance_orchestrator",
        "learned_autonomy_controller",
    )
    wb1_stabilization_targets = (
        "learned_autonomy_controller",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
    )
    wb2_gate_targets = (
        "parallel_reasoning_engine",
        "learned_autonomy_controller",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
        "governance_orchestrator",
    )
    wb3_localization_targets = (
        "learned_autonomy_controller",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "organism_control",
        "maze_agent",
        "causal_counterfactual_planner",
        "governance_orchestrator",
    )
    wb4_influence_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "causal_counterfactual_planner",
        "organism_control",
        "maze_agent",
    )
    wb5_experiment_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "organism_control",
        "maze_agent",
    )
    wb6_attenuation_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "causal_counterfactual_planner",
        "organism_control",
        "maze_agent",
    )
    wb7_shadow_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "causal_counterfactual_planner",
        "organism_control",
        "maze_agent",
    )
    wb8_cutover_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "causal_counterfactual_planner",
        "organism_control",
        "maze_agent",
    )

    return (
        AdaptivePhaseSpec(
            phase_id="phase_wb0_baseline_lock_and_measurement_hygiene",
            label="Phase WB0 - Baseline Lock and Measurement Hygiene",
            capability="lock measurement hygiene and instrumentation consistency before policy-ladder progression",
            module_id="wb0_baseline_lock_and_measurement_hygiene",
            micro_stages=(
                _stage(
                    "wb0.m1_run_recipe_lock",
                    "WB0.1 Run recipe lock",
                    mode="integrate",
                    module_targets=wb0_baseline_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=72,
                ),
                _stage(
                    "wb0.m2_preflight_coverage_discipline",
                    "WB0.2 Preflight coverage discipline",
                    mode="control_integrate",
                    module_targets=wb0_baseline_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=84,
                ),
                _stage(
                    "wb0.m3_dump_integrity_watch",
                    "WB0.3 Dump integrity watch",
                    mode="control_integrate",
                    module_targets=wb0_baseline_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=96,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb1_beam_anchored_mv_objective_equivalence_stabilization",
            label="Phase WB1 - Beam-Anchored MV Objective Equivalence Stabilization",
            capability="stabilize woven MV objective equivalence so activation always requires beam anchor readiness",
            module_id="wb1_beam_anchored_mv_objective_equivalence_stabilization",
            micro_stages=(
                _stage(
                    "wb1.m1_woven_anchor_activation",
                    "WB1.1 Woven anchor activation",
                    mode="integrate",
                    module_targets=wb1_stabilization_targets,
                    objective_signals=("integration_quality", "transfer", "stability"),
                    min_observations=96,
                ),
                _stage(
                    "wb1.m2_anchor_reason_audit",
                    "WB1.2 Anchor reason audit",
                    mode="integrate",
                    module_targets=wb1_stabilization_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=108,
                ),
                _stage(
                    "wb1.m3_objective_force_suppression_guard",
                    "WB1.3 Objective force suppression guard",
                    mode="control_integrate",
                    module_targets=wb1_stabilization_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=120,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb2_dual_evidence_objective_gate_hardening",
            label="Phase WB2 - Dual-Evidence Objective Gate Hardening",
            capability="enforce dual evidence with anchored beam context plus MV gate acceptance and bounded probes",
            module_id="wb2_dual_evidence_objective_gate_hardening",
            micro_stages=(
                _stage(
                    "wb2.m1_dual_evidence_strict_gate",
                    "WB2.1 Dual-evidence strict gate",
                    mode="control_integrate",
                    module_targets=wb2_gate_targets,
                    objective_signals=("integration_quality", "transfer", "introspection_gain"),
                    min_observations=112,
                ),
                _stage(
                    "wb2.m2_probe_budget_bounds",
                    "WB2.2 Probe budget bounds",
                    mode="control_integrate",
                    module_targets=wb2_gate_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=124,
                ),
                _stage(
                    "wb2.m3_override_pressure_reduction",
                    "WB2.3 Override pressure reduction",
                    mode="control_integrate",
                    module_targets=wb2_gate_targets,
                    objective_signals=("integration_quality", "transfer", "stability"),
                    min_observations=136,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb3_localization_reliability_recovery_before_authority_lift",
            label="Phase WB3 - Localization Reliability Recovery Before Authority Lift",
            capability="recover localization reliability floors before any additional MV authority lift",
            module_id="wb3_localization_reliability_recovery_before_authority_lift",
            micro_stages=(
                _stage(
                    "wb3.m1_preplan_truth_reacquire_strict",
                    "WB3.1 Preplan truth reacquire strict",
                    mode="integrate",
                    module_targets=wb3_localization_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=128,
                ),
                _stage(
                    "wb3.m2_player_exit_accuracy_floor_guard",
                    "WB3.2 Player/exit accuracy floor guard",
                    mode="integrate",
                    module_targets=wb3_localization_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=144,
                ),
                _stage(
                    "wb3.m3_contradiction_debt_reduction",
                    "WB3.3 Contradiction debt reduction",
                    mode="control_integrate",
                    module_targets=wb3_localization_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=160,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb4_controlled_mv_influence_lift",
            label="Phase WB4 - Controlled MV Influence Lift",
            capability="lift MV influence via calibration and tie-break quality without bypassing beam guard channels",
            module_id="wb4_controlled_mv_influence_lift",
            micro_stages=(
                _stage(
                    "wb4.m1_score_influence_calibration",
                    "WB4.1 Score influence calibration",
                    mode="integrate",
                    module_targets=wb4_influence_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=136,
                ),
                _stage(
                    "wb4.m2_tie_break_quality_lift",
                    "WB4.2 Tie-break quality lift",
                    mode="integrate",
                    module_targets=wb4_influence_targets,
                    objective_signals=("integration_quality", "transfer", "safety"),
                    min_observations=152,
                ),
                _stage(
                    "wb4.m3_guard_channel_stability_verification",
                    "WB4.3 Guard channel stability verification",
                    mode="control_integrate",
                    module_targets=wb4_influence_targets,
                    objective_signals=("integration_quality", "stability", "safety", "transfer", "introspection_gain"),
                    min_observations=168,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb5_stage_gated_advanced_experiments",
            label="Phase WB5 - Stage-Gated Advanced Experiments",
            capability="run bounded perturbation and contradiction stress experiments on isolated windows after stability gates",
            module_id="wb5_stage_gated_advanced_experiments",
            micro_stages=(
                _stage(
                    "wb5.m1_beam_perturbation_readiness_check",
                    "WB5.1 Beam perturbation readiness check",
                    mode="control_integrate",
                    module_targets=wb5_experiment_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=156,
                ),
                _stage(
                    "wb5.m2_beam_blackout_burst_and_recovery",
                    "WB5.2 Beam blackout burst and recovery",
                    mode="control_integrate",
                    module_targets=wb5_experiment_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=172,
                ),
                _stage(
                    "wb5.m3_contradiction_injection_and_recovery",
                    "WB5.3 Contradiction injection and recovery",
                    mode="control_integrate",
                    module_targets=wb5_experiment_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=188,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb6_beam_decoupling_start_guard_attenuation_ladder",
            label="Phase WB6 - Beam Decoupling Start (Guard Attenuation Ladder)",
            capability="start beam decoupling through guard attenuation ladder while preserving objective and truth contracts",
            module_id="wb6_beam_decoupling_start_guard_attenuation_ladder",
            micro_stages=(
                _stage(
                    "wb6.m1_beam_guard_attenuation_step_a",
                    "WB6.1 Beam guard attenuation step A",
                    mode="control_integrate",
                    module_targets=wb6_attenuation_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=168,
                ),
                _stage(
                    "wb6.m2_beam_guard_attenuation_step_b",
                    "WB6.2 Beam guard attenuation step B",
                    mode="control_integrate",
                    module_targets=wb6_attenuation_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=184,
                ),
                _stage(
                    "wb6.m3_beam_shadow_policy_near_zero",
                    "WB6.3 Beam shadow policy near-zero",
                    mode="control_integrate",
                    module_targets=wb6_attenuation_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=200,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb7_mv_primary_with_beam_shadow_decoupling_verification",
            label="Phase WB7 - MV-Primary with Beam Shadow (Decoupling Verification)",
            capability="verify MV-primary operation while beam runs shadow-only disagreement audits",
            module_id="wb7_mv_primary_with_beam_shadow_decoupling_verification",
            micro_stages=(
                _stage(
                    "wb7.m1_shadow_disagreement_audit",
                    "WB7.1 Shadow disagreement audit",
                    mode="control_integrate",
                    module_targets=wb7_shadow_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=176,
                ),
                _stage(
                    "wb7.m2_disagreement_failure_prediction_gate",
                    "WB7.2 Disagreement failure-prediction gate",
                    mode="control_integrate",
                    module_targets=wb7_shadow_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=192,
                ),
                _stage(
                    "wb7.m3_shadow_emergency_rollback_drill",
                    "WB7.3 Shadow emergency rollback drill",
                    mode="control_integrate",
                    module_targets=wb7_shadow_targets,
                    objective_signals=("integration_quality", "stability", "safety", "transfer"),
                    min_observations=208,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_wb8_full_beam_decoupling_operational_cutover",
            label="Phase WB8 - Full Beam Decoupling (Operational Cutover)",
            capability="cut over to MV-only operational path with emergency rollback to WB7 on stability breach",
            module_id="wb8_full_beam_decoupling_operational_cutover",
            micro_stages=(
                _stage(
                    "wb8.m1_mv_only_operational_cutover",
                    "WB8.1 MV-only operational cutover",
                    mode="control_integrate",
                    module_targets=wb8_cutover_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=188,
                ),
                _stage(
                    "wb8.m2_mixed_window_stability_hold",
                    "WB8.2 Mixed-window stability hold",
                    mode="control_integrate",
                    module_targets=wb8_cutover_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer", "introspection_gain"),
                    min_observations=204,
                ),
                _stage(
                    "wb8.m3_operational_cutover_freeze",
                    "WB8.3 Operational cutover freeze",
                    mode="control_integrate",
                    module_targets=wb8_cutover_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer", "introspection_gain"),
                    min_observations=220,
                ),
            ),
        ),
    )


def build_exit_goal_capability_and_ouch_readiness_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Compatibility alias retained for callers still importing the legacy builder name."""
    return build_mv_input_transition_phase_specs()


def build_mv_localization_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Compatibility alias retained for migrated callers."""
    return build_mv_input_transition_phase_specs()


def build_trust_lift_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Compatibility alias retained for runtime callers migrated from older plans."""
    return build_mv_input_transition_phase_specs()


def build_tuning_and_consolidation_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Program phases aligned to phase_plans/TUNING_AND_CONSOLIDATION_PHASE_MICRO_PLAN.md."""

    def _stage(
        stage_id: str,
        label: str,
        *,
        mode: str,
        module_targets: tuple[str, ...],
        objective_signals: tuple[str, ...],
        min_observations: int,
    ) -> MicroStageSpec:
        return MicroStageSpec(
            stage_id=str(stage_id),
            label=str(label),
            mode=str(mode),
            module_targets=tuple(module_targets),
            objective_signals=tuple(objective_signals),
            min_observations=max(16, int(min_observations)),
        )

    shared_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "organism_control",
        "maze_agent",
    )
    retune_targets = shared_targets + ("causal_counterfactual_planner",)

    return (
        AdaptivePhaseSpec(
            phase_id="phase_tr0_baseline_parity_recovery",
            label="Phase TR0 - Baseline Parity Recovery",
            capability="recover prior stable override/intervention parity before entering consolidation",
            module_id="tr0_baseline_parity_recovery",
            micro_stages=(
                _stage(
                    "tr0.m1_cohort_anchor_lock",
                    "TR0.1 Cohort anchor lock",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety", "introspection_gain"),
                    min_observations=84,
                ),
                _stage(
                    "tr0.m2_override_pressure_clamp",
                    "TR0.2 Override pressure clamp",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=96,
                ),
                _stage(
                    "tr0.m3_parity_confirmation",
                    "TR0.3 Parity confirmation",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "transfer", "safety"),
                    min_observations=108,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc0_baseline_signal_reacquisition",
            label="Phase TC0 - Baseline Signal Reacquisition",
            capability="reacquire stable baseline signal quality before formal lock-in",
            module_id="tc0_baseline_signal_reacquisition",
            micro_stages=(
                _stage(
                    "tc0.m1_baseline_anchor_refresh",
                    "TC0.1 Baseline anchor refresh",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=88,
                ),
                _stage(
                    "tc0.m2_stability_floor_rebuild",
                    "TC0.2 Stability floor rebuild",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=128,
                ),
                _stage(
                    "tc0.m3_transfer_floor_recheck",
                    "TC0.3 Transfer floor recheck",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=136,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc1_baseline_safety_rebalance",
            label="Phase TC1 - Baseline Safety Rebalance",
            capability="rebalance override pressure and safety gating back to baseline",
            module_id="tc1_baseline_safety_rebalance",
            micro_stages=(
                _stage(
                    "tc1.m1_override_budget_normalize",
                    "TC1.1 Override budget normalize",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=144,
                ),
                _stage(
                    "tc1.m2_unresolved_objective_quieting",
                    "TC1.2 Unresolved objective quieting",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=152,
                ),
                _stage(
                    "tc1.m3_intervention_rate_reduction",
                    "TC1.3 Intervention rate reduction",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=160,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc2_baseline_parity_certification",
            label="Phase TC2 - Baseline Parity Certification",
            capability="certify parity hold before entering consolidation lock workflows",
            module_id="tc2_baseline_parity_certification",
            micro_stages=(
                _stage(
                    "tc2.m1_parity_gate_probe",
                    "TC2.1 Parity gate probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=156,
                ),
                _stage(
                    "tc2.m2_parity_hold_verification",
                    "TC2.2 Parity hold verification",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=168,
                ),
                _stage(
                    "tc2.m3_baseline_certification",
                    "TC2.3 Baseline certification",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "introspection_gain"),
                    min_observations=180,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc3_baseline_lock",
            label="Phase TC3 - Baseline Lock",
            capability="lock baseline manifest, gate definitions, and seed protocol for comparability",
            module_id="tc3_baseline_lock",
            micro_stages=(
                _stage(
                    "tc3.m1_baseline_manifest",
                    "TC3.1 Baseline manifest",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=80,
                ),
                _stage(
                    "tc3.m2_metric_gate_lock",
                    "TC3.2 Metric gate lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=92,
                ),
                _stage(
                    "tc3.m3_seed_protocol_lock",
                    "TC3.3 Seed protocol lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "transfer", "introspection_gain"),
                    min_observations=104,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc4_stabilization_sweep",
            label="Phase TC4 - Stabilization Sweep",
            capability="verify repeatability while monitoring pressure drift and triaging regressions",
            module_id="tc4_stabilization_sweep",
            micro_stages=(
                _stage(
                    "tc4.m1_repeatability_check",
                    "TC4.1 Repeatability check",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=112,
                ),
                _stage(
                    "tc4.m2_pressure_watch",
                    "TC4.2 Pressure watch",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=124,
                ),
                _stage(
                    "tc4.m3_regression_triage",
                    "TC4.3 Regression triage",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "introspection_gain", "safety"),
                    min_observations=136,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc5_narrow_retuning",
            label="Phase TC5 - Narrow Retuning",
            capability="retune one constrained knob family at a time under matched comparisons",
            module_id="tc5_narrow_retuning",
            micro_stages=(
                _stage(
                    "tc5.m1_objective_pressure_retune",
                    "TC5.1 Objective pressure retune",
                    mode="control_integrate",
                    module_targets=retune_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=128,
                ),
                _stage(
                    "tc5.m2_verification_margin_retune",
                    "TC5.2 Verification margin retune",
                    mode="control_integrate",
                    module_targets=retune_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=140,
                ),
                _stage(
                    "tc5.m3_guard_margin_retune",
                    "TC5.3 Guard margin retune",
                    mode="control_integrate",
                    module_targets=retune_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=152,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc6_consolidation_hardening",
            label="Phase TC6 - Consolidation Hardening",
            capability="confirm multi-batch stability and keep rollback readiness hot",
            module_id="tc6_consolidation_hardening",
            micro_stages=(
                _stage(
                    "tc6.m1_multi_batch_confirmation",
                    "TC6.1 Multi-batch confirmation",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=144,
                ),
                _stage(
                    "tc6.m2_report_unification",
                    "TC6.2 Report unification",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "introspection_gain", "transfer"),
                    min_observations=156,
                ),
                _stage(
                    "tc6.m3_rollback_readiness",
                    "TC6.3 Rollback readiness",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=168,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_tc7_promotion_readiness",
            label="Phase TC7 - Promotion Readiness",
            capability="final signoff and stable baseline tagging for next-phase handoff",
            module_id="tc7_promotion_readiness",
            micro_stages=(
                _stage(
                    "tc7.m1_final_signoff",
                    "TC7.1 Final signoff",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=160,
                ),
                _stage(
                    "tc7.m2_default_profile_tag",
                    "TC7.2 Default profile tag",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "introspection_gain", "stability"),
                    min_observations=172,
                ),
                _stage(
                    "tc7.m3_next_phase_handoff",
                    "TC7.3 Next-phase handoff",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "transfer", "introspection_gain"),
                    min_observations=184,
                ),
            ),
        ),
    )


def build_wb_endstate_stabilization_recovery_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Program phases aligned to phase_plans/WB_ENDSTATE_STABILIZATION_RECOVERY_PLAN_V1.md."""

    def _stage(
        stage_id: str,
        label: str,
        *,
        mode: str,
        module_targets: tuple[str, ...],
        objective_signals: tuple[str, ...],
        min_observations: int,
    ) -> MicroStageSpec:
        return MicroStageSpec(
            stage_id=str(stage_id),
            label=str(label),
            mode=str(mode),
            module_targets=tuple(module_targets),
            objective_signals=tuple(objective_signals),
            min_observations=max(16, int(min_observations)),
        )

    shared_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "organism_control",
        "maze_agent",
    )

    return (
        AdaptivePhaseSpec(
            phase_id="phase_rs0_recovery_lock_and_evidence_freeze",
            label="Phase RS0 - Recovery Lock and Evidence Freeze",
            capability="freeze run recipe and metrics contract before stabilization actions",
            module_id="rs0_recovery_lock_and_evidence_freeze",
            micro_stages=(
                _stage(
                    "rs0.m1_recipe_lock",
                    "RS0.1 Recipe lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "introspection_gain"),
                    min_observations=64,
                ),
                _stage(
                    "rs0.m2_metric_contract_lock",
                    "RS0.2 Metric contract lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability"),
                    min_observations=72,
                ),
                _stage(
                    "rs0.m3_baseline_snapshot_lock",
                    "RS0.3 Baseline snapshot lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=80,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs1_unresolved_wait_pressure_stabilization",
            label="Phase RS1 - Unresolved Wait Pressure Stabilization",
            capability="reduce unresolved verification waiting pressure to recovery-safe levels",
            module_id="rs1_unresolved_wait_pressure_stabilization",
            micro_stages=(
                _stage(
                    "rs1.m1_wait_source_bucketing",
                    "RS1.1 Wait source bucketing",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=88,
                ),
                _stage(
                    "rs1.m2_objective_wait_suppression",
                    "RS1.2 Objective wait suppression",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=96,
                ),
                _stage(
                    "rs1.m3_wait_recheck_hold",
                    "RS1.3 Wait recheck hold",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=104,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs2_guard_override_normalization",
            label="Phase RS2 - Guard Override Normalization",
            capability="normalize override pressure while preserving non-bypassable safety veto pathways",
            module_id="rs2_guard_override_normalization",
            micro_stages=(
                _stage(
                    "rs2.m1_override_reason_partition",
                    "RS2.1 Override reason partition",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "introspection_gain"),
                    min_observations=104,
                ),
                _stage(
                    "rs2.m2_override_budget_rebalance",
                    "RS2.2 Override budget rebalance",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=112,
                ),
                _stage(
                    "rs2.m3_override_floor_recheck",
                    "RS2.3 Override floor recheck",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=120,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs3_beam_anchor_and_objective_gate_coherence",
            label="Phase RS3 - Beam Anchor and Objective Gate Coherence",
            capability="restore anchor and objective-gate coherence before cutover rehearsal",
            module_id="rs3_beam_anchor_and_objective_gate_coherence",
            micro_stages=(
                _stage(
                    "rs3.m1_anchor_reason_audit",
                    "RS3.1 Anchor reason audit",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "introspection_gain"),
                    min_observations=112,
                ),
                _stage(
                    "rs3.m2_not_recent_suppression_control",
                    "RS3.2 Not-recent suppression control",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=120,
                ),
                _stage(
                    "rs3.m3_gate_reason_normalization",
                    "RS3.3 Gate reason normalization",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=128,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs4_stability_hold_and_variance_compression",
            label="Phase RS4 - Stability Hold and Variance Compression",
            capability="hold stabilized settings and compress variance before WB6-WB8 rehearsal",
            module_id="rs4_stability_hold_and_variance_compression",
            micro_stages=(
                _stage(
                    "rs4.m1_consecutive_pass_hold",
                    "RS4.1 Consecutive pass hold",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "safety"),
                    min_observations=120,
                ),
                _stage(
                    "rs4.m2_variance_band_check",
                    "RS4.2 Variance band check",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=128,
                ),
                _stage(
                    "rs4.m3_regression_tripwire_check",
                    "RS4.3 Regression tripwire check",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "introspection_gain"),
                    min_observations=136,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs5_wb6_wb8_readiness_rehearsal",
            label="Phase RS5 - WB6-WB8 Readiness Rehearsal",
            capability="rehearse attenuation, shadow disagreement, and cutover guards before endstate recertification",
            module_id="rs5_wb6_wb8_readiness_rehearsal",
            micro_stages=(
                _stage(
                    "rs5.m1_attenuation_readiness_probe",
                    "RS5.1 Attenuation readiness probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=128,
                ),
                _stage(
                    "rs5.m2_shadow_disagreement_probe",
                    "RS5.2 Shadow disagreement probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=136,
                ),
                _stage(
                    "rs5.m3_cutover_guard_probe",
                    "RS5.3 Cutover guard probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=144,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs6_endstate_recertification_and_handoff",
            label="Phase RS6 - Endstate Recertification and Handoff",
            capability="recertify U08 contract surfaces and publish exact WB resume decision",
            module_id="rs6_endstate_recertification_and_handoff",
            micro_stages=(
                _stage(
                    "rs6.m1_u08_contract_recheck",
                    "RS6.1 U08 contract recheck",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=136,
                ),
                _stage(
                    "rs6.m2_resume_point_confirm",
                    "RS6.2 Resume point confirm",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "transfer", "introspection_gain"),
                    min_observations=144,
                ),
                _stage(
                    "rs6.m3_handoff_publish",
                    "RS6.3 Handoff publish",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "introspection_gain"),
                    min_observations=152,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs7_full_beam_decoupled_cutover_confirmation",
            label="Phase RS7 - Full Beam-Decoupled Cutover Confirmation",
            capability="confirm stable MV-only cutover with beam fully decoupled from routine live policy authority",
            module_id="rs7_full_beam_decoupled_cutover_confirmation",
            micro_stages=(
                _stage(
                    "rs7.m1_decoupled_profile_apply",
                    "RS7.1 Decoupled profile apply",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=148,
                ),
                _stage(
                    "rs7.m2_decoupled_window_validation",
                    "RS7.2 Decoupled window validation",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=156,
                ),
                _stage(
                    "rs7.m3_decoupled_handoff_freeze",
                    "RS7.3 Decoupled handoff freeze",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer", "introspection_gain"),
                    min_observations=164,
                ),
            ),
        ),
    )


def build_rs_post_recovery_stability_lock_mini_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Expanded post-recovery lock progression aligned with RS_POST_RECOVERY_STABILITY_LOCK_MINI_PHASE_PLAN_V1."""

    def _stage(
        stage_id: str,
        label: str,
        *,
        mode: str,
        module_targets: tuple[str, ...],
        objective_signals: tuple[str, ...],
        min_observations: int,
    ) -> MicroStageSpec:
        return MicroStageSpec(
            stage_id=str(stage_id),
            label=str(label),
            mode=str(mode),
            module_targets=tuple(module_targets),
            objective_signals=tuple(objective_signals),
            min_observations=max(16, int(min_observations)),
        )

    shared_targets = (
        "governance_orchestrator",
        "parallel_reasoning_engine",
        "adaptive_controller",
        "learned_autonomy_controller",
        "organism_control",
        "maze_agent",
    )

    # Keep the terminal end-state phase/stages unchanged for cutover continuity.
    endstate_phase = build_wb_endstate_stabilization_recovery_phase_specs()[-1]

    return (
        AdaptivePhaseSpec(
            phase_id="phase_rs0_recovery_lock_and_evidence_freeze",
            label="Phase RS0 - Recovery Lock and Evidence Freeze",
            capability="freeze recipe and metrics before short stabilization lock windows",
            module_id="rs0_recovery_lock_and_evidence_freeze",
            micro_stages=(
                _stage(
                    "rs0.m1_recipe_lock",
                    "RS0.1 Recipe lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "introspection_gain"),
                    min_observations=64,
                ),
                _stage(
                    "rs0.m2_metric_contract_lock",
                    "RS0.2 Metric contract lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability"),
                    min_observations=72,
                ),
                _stage(
                    "rs0.m3_baseline_snapshot_lock",
                    "RS0.3 Baseline snapshot lock",
                    mode="integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=80,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs1_guard_override_stability_lock",
            label="Phase RS1 - Guard Override Stability Lock",
            capability="stabilize guard override pressure and cap volatility spikes",
            module_id="rs1_guard_override_stability_lock",
            micro_stages=(
                _stage(
                    "rs1.m1_guard_budget_normalization",
                    "RS1.1 Guard budget normalization",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=88,
                ),
                _stage(
                    "rs1.m2_guard_spike_cap_enforcement",
                    "RS1.2 Guard spike-cap enforcement",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=96,
                ),
                _stage(
                    "rs1.m3_guard_window_hold",
                    "RS1.3 Guard window hold",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=104,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs2_unresolved_objective_stability_lock",
            label="Phase RS2 - Unresolved Objective Stability Lock",
            capability="suppress unresolved objective overrides while preserving safety gates",
            module_id="rs2_unresolved_objective_stability_lock",
            micro_stages=(
                _stage(
                    "rs2.m1_unresolved_objective_suppression",
                    "RS2.1 Unresolved objective suppression",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=96,
                ),
                _stage(
                    "rs2.m2_unresolved_override_floor_recheck",
                    "RS2.2 Unresolved override floor recheck",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=104,
                ),
                _stage(
                    "rs2.m3_unresolved_window_hold",
                    "RS2.3 Unresolved window hold",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=112,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs3_warning_free_hard_window_lock",
            label="Phase RS3 - Warning-Free Hard-Window Lock",
            capability="require three consecutive warning-free hard windows before handoff",
            module_id="rs3_warning_free_hard_window_lock",
            micro_stages=(
                _stage(
                    "rs3.m1_warning_free_window_1",
                    "RS3.1 Warning-free hard window 1",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=112,
                ),
                _stage(
                    "rs3.m2_warning_free_window_2",
                    "RS3.2 Warning-free hard window 2",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=120,
                ),
                _stage(
                    "rs3.m3_warning_free_window_3",
                    "RS3.3 Warning-free hard window 3",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer", "introspection_gain"),
                    min_observations=128,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs4_stability_hold_and_variance_compression",
            label="Phase RS4 - Stability Hold and Variance Compression",
            capability="hold warning-free behavior and compress variance before readiness rehearsal",
            module_id="rs4_stability_hold_and_variance_compression",
            micro_stages=(
                _stage(
                    "rs4.m1_consecutive_pass_hold",
                    "RS4.1 Consecutive pass hold",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=120,
                ),
                _stage(
                    "rs4.m2_variance_band_check",
                    "RS4.2 Variance band check",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "stability", "transfer"),
                    min_observations=128,
                ),
                _stage(
                    "rs4.m3_regression_tripwire_check",
                    "RS4.3 Regression tripwire check",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "introspection_gain"),
                    min_observations=136,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs5_wb6_wb8_readiness_rehearsal",
            label="Phase RS5 - WB6-WB8 Readiness Rehearsal",
            capability="rehearse attenuation and cutover guard behavior before recertification",
            module_id="rs5_wb6_wb8_readiness_rehearsal",
            micro_stages=(
                _stage(
                    "rs5.m1_attenuation_readiness_probe",
                    "RS5.1 Attenuation readiness probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=128,
                ),
                _stage(
                    "rs5.m2_shadow_disagreement_probe",
                    "RS5.2 Shadow disagreement probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "transfer"),
                    min_observations=136,
                ),
                _stage(
                    "rs5.m3_cutover_guard_probe",
                    "RS5.3 Cutover guard probe",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "transfer"),
                    min_observations=144,
                ),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_rs6_endstate_recertification_and_handoff",
            label="Phase RS6 - Endstate Recertification and Handoff",
            capability="recertify lock outcomes and publish RS7 handoff decision",
            module_id="rs6_endstate_recertification_and_handoff",
            micro_stages=(
                _stage(
                    "rs6.m1_u08_contract_recheck",
                    "RS6.1 U08 contract recheck",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability"),
                    min_observations=136,
                ),
                _stage(
                    "rs6.m2_resume_point_confirm",
                    "RS6.2 Resume point confirm",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "transfer", "introspection_gain"),
                    min_observations=144,
                ),
                _stage(
                    "rs6.m3_handoff_publish",
                    "RS6.3 Handoff publish",
                    mode="control_integrate",
                    module_targets=shared_targets,
                    objective_signals=("integration_quality", "safety", "stability", "introspection_gain"),
                    min_observations=152,
                ),
            ),
        ),
        endstate_phase,
    )


def build_default_kernel_phase_specs() -> tuple[AdaptivePhaseSpec, ...]:
    """Default runtime progression for expanded RS post-recovery lock with RS7 end-state continuity."""
    return build_rs_post_recovery_stability_lock_mini_phase_specs()
