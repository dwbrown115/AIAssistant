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
        target_adapt_rate: float = 0.08,
        weight_adapt_rate: float = 0.06,
    ) -> None:
        if not phase_specs:
            raise ValueError("phase_specs must not be empty")
        self.phase_specs = phase_specs
        self.ema_decay = _clamp(float(ema_decay), 0.5, 0.999)
        self.target_adapt_rate = _clamp(float(target_adapt_rate), 0.001, 0.25)
        self.weight_adapt_rate = _clamp(float(weight_adapt_rate), 0.001, 0.25)
        self.phase_order = tuple(spec.phase_id for spec in phase_specs)
        self.phase_spec_by_id = {spec.phase_id: spec for spec in phase_specs}
        self.phase_state: dict[str, AdaptivePhaseRuntime] = {
            spec.phase_id: AdaptivePhaseRuntime(
                phase_id=spec.phase_id,
                enabled=True,
                promotion_target=_clamp(float(base_promotion_target), 0.45, 0.9),
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
    ) -> AdaptivePhaseTransition | None:
        if phase_id not in self.phase_state:
            raise KeyError(f"unknown phase_id: {phase_id}")
        phase_spec = self.phase_spec_by_id[phase_id]
        state = self.phase_state[phase_id]
        if state.completed:
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

        self._adapt_weights(state)
        state.score_ema = self._composite_score(state)
        self._adapt_target(state)

        if not state.enabled:
            return None
        if state.observations < int(stage.min_observations):
            return None

        safety_floor = max(0.42, state.promotion_target - 0.14)
        stability_floor = max(0.40, state.promotion_target - 0.16)
        promote = (
            state.score_ema >= state.promotion_target
            and state.safety_ema >= safety_floor
            and state.stability_ema >= stability_floor
        )
        if not promote:
            return None

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

    def _adapt_target(self, state: AdaptivePhaseRuntime) -> None:
        robustness = (
            (state.stability_ema * 0.35)
            + (state.transfer_ema * 0.35)
            + (state.safety_ema * 0.20)
            + (state.introspection_ema * 0.10)
        )
        adaptive_target = _clamp(0.50 + (robustness * 0.38), 0.45, 0.90)
        state.promotion_target = _clamp(
            ((1.0 - self.target_adapt_rate) * state.promotion_target)
            + (self.target_adapt_rate * adaptive_target),
            0.45,
            0.90,
        )

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
        for phase_id in self.phase_order:
            spec = self.phase_spec_by_id[phase_id]
            state = self.phase_state[phase_id]
            stage = spec.micro_stages[min(state.micro_index, len(spec.micro_stages) - 1)]
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
            "active_target": self.current_active_target(),
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
            state.promotion_target = _clamp(_as_float(row.get("promotion_target", state.promotion_target), state.promotion_target), 0.45, 0.90)

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
        stage_labels: tuple[str, str, str],
        stage_modes: tuple[str, str, str],
    ) -> tuple[MicroStageSpec, ...]:
        return (
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m1",
                label=stage_labels[0],
                mode=stage_modes[0],
                module_targets=(module_id,),
                objective_signals=(
                    "train_quality",
                    "stability",
                    "introspection_gain",
                ),
            ),
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m2",
                label=stage_labels[1],
                mode=stage_modes[1],
                module_targets=(module_id,),
                objective_signals=(
                    "integration_quality",
                    "transfer",
                    "safety",
                ),
            ),
            MicroStageSpec(
                stage_id=f"{stage_prefix}.m3",
                label=stage_labels[2],
                mode=stage_modes[2],
                module_targets=(module_id,),
                objective_signals=(
                    "integration_quality",
                    "stability",
                    "transfer",
                ),
            ),
        )

    return (
        AdaptivePhaseSpec(
            phase_id="phase_1_envelope_shadow",
            label="Envelope + Shadow",
            capability="freeze behavior envelope and run advisory channels in shadow mode",
            module_id="behavior_envelope",
            micro_stages=_micro(
                "p1",
                "behavior_envelope",
                stage_labels=(
                    "Baseline envelope lock",
                    "Shadow advisory telemetry",
                    "Counterfactual utility scoring",
                ),
                stage_modes=("train", "train", "train"),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_2_low_influence_blend",
            label="Low-Influence Blend",
            capability="enable advisory blend with trust scaling and strict intervention budgets",
            module_id="advisory_blend_controller",
            micro_stages=_micro(
                "p2",
                "advisory_blend_controller",
                stage_labels=(
                    "Low-influence advisory ramp",
                    "Intervention budget enforcement",
                    "Guarded assist arbitration",
                ),
                stage_modes=("integrate", "integrate", "integrate"),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_3_hybrid_arbitration",
            label="Hybrid Arbitration",
            capability="run adaptive-first arbitration while preserving hard safety guardrails",
            module_id="hybrid_arbiter",
            micro_stages=_micro(
                "p3",
                "hybrid_arbiter",
                stage_labels=(
                    "Hybrid policy arbitration",
                    "Adaptive-primary with safety clamps",
                    "Stability hold under mixed traffic",
                ),
                stage_modes=("integrate", "integrate", "integrate"),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_4_auto_anneal_rollback",
            label="Auto-Anneal + Rollback",
            capability="automatically reduce hardcoded influence with guardrail-triggered rollback",
            module_id="anneal_rollback_controller",
            micro_stages=_micro(
                "p4",
                "anneal_rollback_controller",
                stage_labels=(
                    "Auto-anneal hardcoded influence",
                    "Regression-trigger rollback tuning",
                    "Guardrail steady-state verification",
                ),
                stage_modes=("integrate", "integrate", "integrate"),
            ),
        ),
        AdaptivePhaseSpec(
            phase_id="phase_5_legacy_prune",
            label="Legacy Prune",
            capability="retire obsolete hardcoded branches while preserving emergency safety core",
            module_id="legacy_prune_controller",
            micro_stages=_micro(
                "p5",
                "legacy_prune_controller",
                stage_labels=(
                    "Candidate legacy-path deprecation",
                    "Safety-core parity validation",
                    "Post-prune release hold",
                ),
                stage_modes=("integrate", "integrate", "integrate"),
            ),
        ),
    )
