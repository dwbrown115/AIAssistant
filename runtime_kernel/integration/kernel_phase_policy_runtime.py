from __future__ import annotations

import os

from kernel_contracts import DevelopmentStage, ReasoningBudgetContract, ReasoningProfile


def _parse_reasoning_profile(value: object, *, fallback: ReasoningProfile) -> ReasoningProfile:
    try:
        token = str(value or "").strip().upper()
        if token:
            return ReasoningProfile(token)
    except Exception:
        pass
    return fallback


def _parse_development_stage(value: object, *, fallback: DevelopmentStage) -> DevelopmentStage:
    try:
        token = str(value or "").strip()
        if token:
            return DevelopmentStage(token)
    except Exception:
        pass
    return fallback


def _scaled_budget(
    base_budget: ReasoningBudgetContract,
    *,
    branches_scale: object = 1.0,
    depth_delta: object = 0,
    time_budget_scale: object = 1.0,
    token_budget_scale: object = 1.0,
) -> ReasoningBudgetContract:
    try:
        branches_scale_value = float(branches_scale)
    except Exception:
        branches_scale_value = 1.0
    try:
        depth_delta_value = int(depth_delta)
    except Exception:
        depth_delta_value = 0
    try:
        time_budget_scale_value = float(time_budget_scale)
    except Exception:
        time_budget_scale_value = 1.0
    try:
        token_budget_scale_value = float(token_budget_scale)
    except Exception:
        token_budget_scale_value = 1.0
    return ReasoningBudgetContract(
        max_branches=max(1, min(32, int(round(float(base_budget.max_branches) * max(0.05, branches_scale_value))))),
        max_depth=max(1, min(8, int(base_budget.max_depth + depth_delta_value))),
        time_budget_ms=max(8, min(1200, int(round(float(base_budget.time_budget_ms) * max(0.05, time_budget_scale_value))))),
        token_budget=max(64, min(20000, int(round(float(base_budget.token_budget) * max(0.05, token_budget_scale_value))))),
    )


def init_kernel_phase_policy_runtime(app: object) -> None:
    app.kernel_phase_module_base_enable = {
        "learned_autonomy_controller": bool(getattr(app, "learned_autonomy_subphase_enable", False)),
        "parallel_reasoning_engine": bool(getattr(app, "parallel_reasoning_enable", False)),
        "adaptive_controller": bool(getattr(app, "adaptive_controller_enable", False)),
        "organism_control": bool(getattr(app, "organism_control_enable", False)),
        "maze_agent": bool(getattr(app, "maze_agent_enable", False)),
        "governance_orchestrator": bool(getattr(getattr(app, "governance_orchestrator", None), "enabled", False)),
    }
    app.kernel_phase_policy_base = {
        "parallel_reasoning_profile": str(getattr(getattr(app, "parallel_reasoning_profile", ReasoningProfile.BALANCED), "value", "BALANCED")),
        "parallel_reasoning_budget": {
            "max_branches": int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_branches", 8)),
            "max_depth": int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_depth", 3)),
            "time_budget_ms": int(getattr(getattr(app, "parallel_reasoning_budget", None), "time_budget_ms", 90)),
            "token_budget": int(getattr(getattr(app, "parallel_reasoning_budget", None), "token_budget", 620)),
        },
        "development_stage": str(getattr(getattr(getattr(app, "governance_orchestrator", None), "development_stage", DevelopmentStage.JUVENILE_KERNEL), "value", "JUVENILE_KERNEL")),
    }
    app.kernel_phase_mode_policy_map = {
        "train": {
            "reasoning_profile": str(os.getenv("KERNEL_PHASE_POLICY_TRAIN_PROFILE", "FAST_APPROX")).strip().upper(),
            "branches_scale": max(0.25, min(2.0, float(os.getenv("KERNEL_PHASE_POLICY_TRAIN_BRANCHES_SCALE", "0.75")))),
            "depth_delta": max(-4, min(4, int(float(os.getenv("KERNEL_PHASE_POLICY_TRAIN_DEPTH_DELTA", "-1"))))),
            "time_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_TRAIN_TIME_BUDGET_SCALE", "0.7")))),
            "token_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_TRAIN_TOKEN_BUDGET_SCALE", "0.75")))),
            "development_stage": str(os.getenv("KERNEL_PHASE_POLICY_TRAIN_STAGE", "JUVENILE_KERNEL")).strip(),
        },
        "integrate": {
            "reasoning_profile": str(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_PROFILE", "BALANCED")).strip().upper(),
            "branches_scale": max(0.25, min(2.0, float(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_BRANCHES_SCALE", "1.0")))),
            "depth_delta": max(-4, min(4, int(float(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_DEPTH_DELTA", "0"))))),
            "time_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_TIME_BUDGET_SCALE", "1.0")))),
            "token_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_TOKEN_BUDGET_SCALE", "1.0")))),
            "development_stage": str(os.getenv("KERNEL_PHASE_POLICY_INTEGRATE_STAGE", "MATURE_KERNEL")).strip(),
        },
        "control_integrate": {
            "reasoning_profile": str(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_PROFILE", "BALANCED")).strip().upper(),
            "reasoning_profile_if_safety": str(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_SAFETY_PROFILE", "DEEP_AUDIT")).strip().upper(),
            "branches_scale": max(0.25, min(2.0, float(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_BRANCHES_SCALE", "1.25")))),
            "depth_delta": max(-4, min(4, int(float(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_DEPTH_DELTA", "1"))))),
            "time_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_TIME_BUDGET_SCALE", "1.4")))),
            "token_budget_scale": max(0.25, min(2.5, float(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_TOKEN_BUDGET_SCALE", "1.3")))),
            "development_stage": str(os.getenv("KERNEL_PHASE_POLICY_CONTROL_INTEGRATE_STAGE", "MATURE_KERNEL")).strip(),
        },
    }
    app.kernel_phase_safety_profile_floor = str(os.getenv("KERNEL_PHASE_POLICY_SAFETY_PROFILE_FLOOR", "BALANCED")).strip().upper()
    app.kernel_phase_runtime_module_signature = None


def kernel_phase_active_specs(app: object, *, phase_id: str, stage_id: str) -> tuple[object | None, object | None]:
    phase_token = str(phase_id or "").strip()
    stage_token = str(stage_id or "").strip()
    active_phase_spec = None
    active_micro_spec = None
    for spec in tuple(getattr(app, "kernel_phase_specs", ()) or ()):
        if str(getattr(spec, "phase_id", "")).strip() != phase_token:
            continue
        active_phase_spec = spec
        for micro_spec in tuple(getattr(spec, "micro_stages", ()) or ()):
            if str(getattr(micro_spec, "stage_id", "")).strip() == stage_token:
                active_micro_spec = micro_spec
                break
        break
    return (active_phase_spec, active_micro_spec)


def kernel_phase_active_module_targets(app: object) -> tuple[str, ...]:
    if (not getattr(app, "kernel_phase_program_enable", False)) or getattr(app, "kernel_phase_program", None) is None:
        return ()
    active_target = app.kernel_phase_program.current_active_target()
    if active_target is None:
        return ()
    phase_id, stage_id = active_target
    _, active_micro_spec = kernel_phase_active_specs(app, phase_id=phase_id, stage_id=stage_id)
    if active_micro_spec is None:
        return ()
    tokens: list[str] = []
    for module_name in tuple(getattr(active_micro_spec, "module_targets", ()) or ()):
        token = str(module_name or "").strip().lower()
        if token:
            tokens.append(token)
    return tuple(dict.fromkeys(tokens))


def kernel_phase_runtime_module_enabled(app: object, module_id: str, *, base_enabled: bool, active_targets: tuple[str, ...]) -> bool:
    if not bool(base_enabled):
        return False
    if (not getattr(app, "kernel_phase_program_enable", False)) or getattr(app, "kernel_phase_program", None) is None:
        return True
    if not active_targets:
        return True
    token = str(module_id or "").strip().lower()
    if not token:
        return True
    if token == "governance_orchestrator":
        return True
    if bool(getattr(app, "kernel_phase_force_safety_core_enable", True)) and token in {"organism_control", "maze_agent"}:
        return True
    return token in set(active_targets)


def apply_kernel_phase_runtime_integration(app: object) -> None:
    base_map = dict(getattr(app, "kernel_phase_module_base_enable", {}) or {})
    if not base_map:
        base_map = {
            "learned_autonomy_controller": bool(getattr(app, "learned_autonomy_subphase_enable", False)),
            "parallel_reasoning_engine": bool(getattr(app, "parallel_reasoning_enable", False)),
            "adaptive_controller": bool(getattr(app, "adaptive_controller_enable", False)),
            "organism_control": bool(getattr(app, "organism_control_enable", False)),
            "maze_agent": bool(getattr(app, "maze_agent_enable", False)),
            "governance_orchestrator": bool(getattr(getattr(app, "governance_orchestrator", None), "enabled", False)),
        }
        app.kernel_phase_module_base_enable = dict(base_map)

    base_policy = dict(getattr(app, "kernel_phase_policy_base", {}) or {})
    if not base_policy:
        base_policy = {
            "parallel_reasoning_profile": str(getattr(getattr(app, "parallel_reasoning_profile", ReasoningProfile.BALANCED), "value", "BALANCED")),
            "parallel_reasoning_budget": {
                "max_branches": int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_branches", 8)),
                "max_depth": int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_depth", 3)),
                "time_budget_ms": int(getattr(getattr(app, "parallel_reasoning_budget", None), "time_budget_ms", 90)),
                "token_budget": int(getattr(getattr(app, "parallel_reasoning_budget", None), "token_budget", 620)),
            },
            "development_stage": str(getattr(getattr(getattr(app, "governance_orchestrator", None), "development_stage", DevelopmentStage.JUVENILE_KERNEL), "value", "JUVENILE_KERNEL")),
        }
        app.kernel_phase_policy_base = dict(base_policy)

    base_budget_payload = dict(base_policy.get("parallel_reasoning_budget", {}) or {})
    base_budget = ReasoningBudgetContract(
        max_branches=max(1, min(32, int(base_budget_payload.get("max_branches", 8) or 8))),
        max_depth=max(1, min(8, int(base_budget_payload.get("max_depth", 3) or 3))),
        time_budget_ms=max(8, min(1200, int(base_budget_payload.get("time_budget_ms", 90) or 90))),
        token_budget=max(64, min(20000, int(base_budget_payload.get("token_budget", 620) or 620))),
    )

    try:
        desired_profile = ReasoningProfile(str(base_policy.get("parallel_reasoning_profile", "BALANCED")).strip().upper())
    except Exception:
        desired_profile = ReasoningProfile.BALANCED
    try:
        desired_stage = DevelopmentStage(str(base_policy.get("development_stage", "JUVENILE_KERNEL")).strip())
    except Exception:
        desired_stage = DevelopmentStage.JUVENILE_KERNEL
    desired_budget = base_budget

    active_targets = kernel_phase_active_module_targets(app)
    active_target = app.kernel_phase_program.current_active_target() if ((app.kernel_phase_program_enable) and (app.kernel_phase_program is not None)) else None
    target_label = f"{active_target[0]}::{active_target[1]}" if active_target else ("complete" if app.kernel_phase_program_enable else "disabled")
    active_micro_mode = ""
    objective_signals: tuple[str, ...] = ()
    mode_policy_payload: dict[str, object] = {}
    safety_signal_active = False
    if active_target is not None:
        _, active_micro_spec = kernel_phase_active_specs(app, phase_id=str(active_target[0]), stage_id=str(active_target[1]))
        if active_micro_spec is not None:
            active_micro_mode = str(getattr(active_micro_spec, "mode", "") or "").strip().lower()
            objective_signals = tuple(
                signal
                for signal in (
                    str(token or "").strip().lower()
                    for token in tuple(getattr(active_micro_spec, "objective_signals", ()) or ())
                )
                if signal
            )
            safety_signal_active = bool("safety" in set(objective_signals))
            mode_map = dict(getattr(app, "kernel_phase_mode_policy_map", {}) or {})
            mode_policy_payload = dict(mode_map.get(active_micro_mode, {}) or {})
            if mode_policy_payload:
                desired_profile = _parse_reasoning_profile(mode_policy_payload.get("reasoning_profile"), fallback=desired_profile)
                if safety_signal_active and mode_policy_payload.get("reasoning_profile_if_safety"):
                    desired_profile = _parse_reasoning_profile(mode_policy_payload.get("reasoning_profile_if_safety"), fallback=desired_profile)
                desired_budget = _scaled_budget(
                    base_budget,
                    branches_scale=mode_policy_payload.get("branches_scale", 1.0),
                    depth_delta=mode_policy_payload.get("depth_delta", 0),
                    time_budget_scale=mode_policy_payload.get("time_budget_scale", 1.0),
                    token_budget_scale=mode_policy_payload.get("token_budget_scale", 1.0),
                )
                desired_stage = _parse_development_stage(mode_policy_payload.get("development_stage"), fallback=desired_stage)

    if safety_signal_active and desired_profile == ReasoningProfile.FAST_APPROX:
        desired_profile = _parse_reasoning_profile(getattr(app, "kernel_phase_safety_profile_floor", "BALANCED"), fallback=ReasoningProfile.BALANCED)

    desired_states = {
        "learned_autonomy_controller": kernel_phase_runtime_module_enabled(app, "learned_autonomy_controller", base_enabled=bool(base_map.get("learned_autonomy_controller", False)), active_targets=active_targets),
        "parallel_reasoning_engine": kernel_phase_runtime_module_enabled(app, "parallel_reasoning_engine", base_enabled=bool(base_map.get("parallel_reasoning_engine", False)), active_targets=active_targets),
        "adaptive_controller": kernel_phase_runtime_module_enabled(app, "adaptive_controller", base_enabled=bool(base_map.get("adaptive_controller", False)), active_targets=active_targets),
        "organism_control": kernel_phase_runtime_module_enabled(app, "organism_control", base_enabled=bool(base_map.get("organism_control", False)), active_targets=active_targets),
        "maze_agent": kernel_phase_runtime_module_enabled(app, "maze_agent", base_enabled=bool(base_map.get("maze_agent", False)), active_targets=active_targets),
        "governance_orchestrator": kernel_phase_runtime_module_enabled(app, "governance_orchestrator", base_enabled=bool(base_map.get("governance_orchestrator", False)), active_targets=active_targets),
    }

    signature = (
        str(target_label),
        int(desired_states["learned_autonomy_controller"]),
        int(desired_states["parallel_reasoning_engine"]),
        int(desired_states["adaptive_controller"]),
        int(desired_states["organism_control"]),
        int(desired_states["maze_agent"]),
        int(desired_states["governance_orchestrator"]),
        str(desired_profile.value),
        int(desired_budget.max_branches),
        int(desired_budget.max_depth),
        int(desired_budget.time_budget_ms),
        int(desired_budget.token_budget),
        str(desired_stage.value),
    )
    if signature == getattr(app, "kernel_phase_runtime_module_signature", None):
        return

    previous_states = {
        "learned_autonomy_controller": bool(getattr(app, "learned_autonomy_subphase_enable", False)),
        "parallel_reasoning_engine": bool(getattr(app, "parallel_reasoning_enable", False)),
        "adaptive_controller": bool(getattr(app, "adaptive_controller_enable", False)),
        "organism_control": bool(getattr(app, "organism_control_enable", False)),
        "maze_agent": bool(getattr(app, "maze_agent_enable", False)),
        "governance_orchestrator": bool(getattr(getattr(app, "governance_orchestrator", None), "enabled", False)),
    }
    previous_profile = str(getattr(getattr(app, "parallel_reasoning_profile", ReasoningProfile.BALANCED), "value", "BALANCED"))
    previous_budget = ReasoningBudgetContract(
        max_branches=max(1, int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_branches", base_budget.max_branches))),
        max_depth=max(1, int(getattr(getattr(app, "parallel_reasoning_budget", None), "max_depth", base_budget.max_depth))),
        time_budget_ms=max(8, int(getattr(getattr(app, "parallel_reasoning_budget", None), "time_budget_ms", base_budget.time_budget_ms))),
        token_budget=max(64, int(getattr(getattr(app, "parallel_reasoning_budget", None), "token_budget", base_budget.token_budget))),
    )
    previous_stage = str(getattr(getattr(getattr(app, "governance_orchestrator", None), "development_stage", DevelopmentStage.JUVENILE_KERNEL), "value", "JUVENILE_KERNEL"))

    app.learned_autonomy_subphase_enable = bool(desired_states["learned_autonomy_controller"])
    if getattr(app, "learned_autonomy_controller", None) is not None:
        app.learned_autonomy_controller.enabled = bool(desired_states["learned_autonomy_controller"])
    app.parallel_reasoning_enable = bool(desired_states["parallel_reasoning_engine"])
    if getattr(app, "parallel_reasoning_engine", None) is not None:
        app.parallel_reasoning_engine.enabled = bool(desired_states["parallel_reasoning_engine"])
    app.parallel_reasoning_profile = desired_profile
    app.parallel_reasoning_budget = desired_budget
    app.adaptive_controller_enable = bool(desired_states["adaptive_controller"])
    app.organism_control_enable = bool(desired_states["organism_control"])
    app.maze_agent_enable = bool(desired_states["maze_agent"])
    if getattr(app, "governance_orchestrator", None) is not None:
        app.governance_orchestrator.enabled = bool(desired_states["governance_orchestrator"])
        app.governance_orchestrator.development_stage = desired_stage

    app._refresh_learned_autonomy_subphase_state()
    app.kernel_phase_runtime_module_signature = signature

    if getattr(app, "governance_orchestrator", None) is not None and app.governance_orchestrator.enabled:
        module_changed = any((desired_states[key] != previous_states.get(key, False) for key in desired_states.keys()))
        policy_changed = bool(
            (str(desired_profile.value) != str(previous_profile))
            or (int(desired_budget.max_branches) != int(previous_budget.max_branches))
            or (int(desired_budget.max_depth) != int(previous_budget.max_depth))
            or (int(desired_budget.time_budget_ms) != int(previous_budget.time_budget_ms))
            or (int(desired_budget.token_budget) != int(previous_budget.token_budget))
            or (str(desired_stage.value) != str(previous_stage))
        )
        changed = bool(module_changed or policy_changed)
        if changed:
            app.governance_orchestrator.record_runtime_event(
                kind="adaptive_phase_module_activation",
                payload={
                    "target": str(target_label),
                    "micro_mode": str(active_micro_mode or "--"),
                    "objective_signals": list(objective_signals),
                    "module_targets": list(active_targets),
                    "module_states": {key: int(value) for key, value in desired_states.items()},
                    "reasoning_profile": str(desired_profile.value),
                    "reasoning_budget": {
                        "max_branches": int(desired_budget.max_branches),
                        "max_depth": int(desired_budget.max_depth),
                        "time_budget_ms": int(desired_budget.time_budget_ms),
                        "token_budget": int(desired_budget.token_budget),
                    },
                    "development_stage": str(desired_stage.value),
                    "mode_policy": dict(mode_policy_payload),
                },
            )


def kernel_phase_module_metrics(app: object, *, module_targets: tuple[str, ...], telemetry_channel: str) -> dict[str, float]:
    def _clip(value: object, lower: float = 0.0, upper: float = 1.0) -> float:
        try:
            numeric = float(value)
        except Exception:
            numeric = lower
        if numeric < lower:
            return lower
        if numeric > upper:
            return upper
        return numeric

    def _add(metrics: list[dict[str, float]], *, train: float, integrate: float, stability: float, transfer: float, safety: float, introspection: float) -> None:
        metrics.append(
            {
                "train_quality": _clip(train),
                "integration_quality": _clip(integrate),
                "stability": _clip(stability),
                "transfer": _clip(transfer),
                "safety": _clip(safety),
                "introspection_gain": _clip(introspection),
            }
        )

    contributions: list[dict[str, float]] = []
    for module_name in tuple(module_targets or ()):
        token = str(module_name or "").strip().lower()

        if token == "learned_autonomy_controller":
            autonomy = app.learned_autonomy_controller.snapshot() if getattr(app, "learned_autonomy_subphase_enable", False) else {}
            score = _clip(autonomy.get("score_ema", 0.5))
            learned_only = _clip(autonomy.get("learned_only_ema", score))
            intervention_ema = _clip(autonomy.get("intervention_ema", 0.5))
            unresolved_ema = _clip(autonomy.get("unresolved_override_ema", 0.0))
            autonomy_level = _clip(autonomy.get("autonomy_level", 0.5))
            _add(
                contributions,
                train=score,
                integrate=(1.0 - intervention_ema),
                stability=(1.0 - unresolved_ema),
                transfer=learned_only,
                safety=(1.0 - unresolved_ema),
                introspection=autonomy_level,
            )
            continue

        if token == "parallel_reasoning_engine":
            reasoning = app._parallel_reasoning_snapshot() if getattr(app, "parallel_reasoning_enable", False) else {}
            confidence = _clip(reasoning.get("last_confidence", 0.0))
            confidence_ema = _clip(reasoning.get("confidence_ema", confidence))
            utility_ema = _clip(reasoning.get("utility_ema", 0.5))
            trust_local = _clip(reasoning.get("plan_trust_local", 0.5))
            trust_adaptive = _clip(reasoning.get("plan_trust_adaptive", 0.5))
            trust_deliberative = _clip(reasoning.get("plan_trust_deliberative", 0.5))
            trust_mean = _clip((trust_local + trust_adaptive + trust_deliberative) / 3.0)
            conf_margin = _clip(0.5 + (0.5 * float(reasoning.get("last_confidence_margin", 0.0) or 0.0)))
            _add(
                contributions,
                train=confidence_ema,
                integrate=utility_ema,
                stability=trust_mean,
                transfer=confidence,
                safety=((0.55 * trust_mean) + (0.45 * conf_margin)),
                introspection=conf_margin,
            )
            continue

        if token == "adaptive_controller":
            if getattr(app, "adaptive_controller_enable", False) and getattr(app, "adaptive_controller", None) is not None:
                stats = app.adaptive_controller.stats()
                steps = max(0, int(stats.get("steps", 0) or 0))
                hidden = max(1, int(stats.get("hidden_units", 1) or 1))
                error_ema = _clip(stats.get("error_ema", 1.0))
                step_floor = max(24, int(getattr(app, "adaptive_policy_min_steps", 120) or 120))
                step_ratio = _clip(float(steps) / float(max(step_floor, 120)))
                error_relief = _clip(1.0 - error_ema)
                hidden_ratio = _clip(float(hidden) / 96.0)
                policy_signal = 0.62
                if str(getattr(app, "adaptive_policy_mode", "hybrid")) == "adaptive_first":
                    policy_signal = 1.0 if steps >= step_floor else 0.72
                elif steps >= step_floor:
                    policy_signal = 0.84
                _add(
                    contributions,
                    train=((0.6 * error_relief) + (0.4 * step_ratio)),
                    integrate=((0.55 * step_ratio) + (0.45 * policy_signal)),
                    stability=error_relief,
                    transfer=step_ratio,
                    safety=((0.65 * error_relief) + (0.35 * policy_signal)),
                    introspection=((0.4 * hidden_ratio) + (0.6 * step_ratio)),
                )
            else:
                _add(contributions, train=0.35, integrate=0.35, stability=0.45, transfer=0.35, safety=0.5, introspection=0.35)
            continue

        if token == "governance_orchestrator":
            enabled = bool(getattr(getattr(app, "governance_orchestrator", None), "enabled", False))
            capabilities = getattr(getattr(app, "governance_orchestrator", None), "capabilities", {})
            audit_log = list(getattr(getattr(app, "governance_orchestrator", None), "audit_log", []))
            recent = audit_log[-240:]
            recent_total = max(1, len(recent))
            event_density = _clip(float(len(recent)) / 120.0)
            capability_density = _clip(float(len(capabilities)) / 8.0)
            error_count = 0
            runtime_count = 0
            for row in recent:
                kind = str((row or {}).get("kind", "")).strip().lower() if isinstance(row, dict) else ""
                if kind == "error":
                    error_count += 1
                if kind.startswith("adaptive_phase_") or kind in {"runtime_event", "action_outcome", "autonomy_transition"}:
                    runtime_count += 1
            error_rate = _clip(float(error_count) / float(recent_total))
            runtime_rate = _clip(float(runtime_count) / float(recent_total))
            enabled_scale = 1.0 if enabled else 0.35
            _add(
                contributions,
                train=enabled_scale * ((0.55 * capability_density) + (0.45 * event_density)),
                integrate=enabled_scale * ((0.6 * capability_density) + (0.4 * runtime_rate)),
                stability=enabled_scale * (1.0 - error_rate),
                transfer=enabled_scale * event_density,
                safety=enabled_scale * (1.0 - min(1.0, error_rate * 1.35)),
                introspection=enabled_scale * ((0.5 * runtime_rate) + (0.5 * event_density)),
            )
            continue

        if token == "organism_control":
            enabled = bool(getattr(app, "organism_control_enable", False))
            loop_suspected = bool(getattr(getattr(app, "organism_control_state", None), "loop_suspected", False))
            serotonin = _clip(getattr(getattr(app, "organism_endocrine_state", None), "serotonin", 0.5))
            cortisol = _clip(getattr(getattr(app, "organism_endocrine_state", None), "cortisol", 0.5))
            dopamine = _clip(getattr(getattr(app, "organism_endocrine_state", None), "dopamine", 0.5))
            policy_token = str(getattr(getattr(app, "organism_control_state", None), "current_policy", "") or "").strip().lower()
            policy_signal = 0.75 if policy_token else 0.45
            stability_signal = 0.42 if loop_suspected else 0.82
            _add(
                contributions,
                train=(0.7 if enabled else 0.3),
                integrate=((0.6 if enabled else 0.35) + (0.4 * policy_signal)),
                stability=stability_signal,
                transfer=((0.45 * serotonin) + (0.35 * dopamine) + (0.2 * policy_signal)),
                safety=((0.62 if enabled else 0.4) + (0.38 * (1.0 - cortisol))),
                introspection=((0.55 * policy_signal) + (0.45 * (1.0 - _clip(cortisol - dopamine, 0.0, 1.0)))),
            )
            continue

        if token in {"maze_agent", "maze_agent_controller"}:
            enabled = bool(getattr(app, "maze_agent_enable", False)) and (getattr(app, "maze_agent", None) is not None)
            controller_state = getattr(getattr(app, "maze_agent", None), "controller_state", None)
            mode_token = str(getattr(controller_state, "mode", "") or "").upper()
            escape_pressure = 1.0 if "ESCAPE" in mode_token else 0.0
            step_pressure = _clip(float(getattr(app, "episode_steps", 0) or 0) / 240.0)
            _add(
                contributions,
                train=(0.68 if enabled else 0.3),
                integrate=((0.72 if enabled else 0.35) - (0.2 * escape_pressure)),
                stability=((0.78 if enabled else 0.42) - (0.35 * escape_pressure)),
                transfer=((0.65 if enabled else 0.35) + (0.2 * (1.0 - step_pressure))),
                safety=((0.74 if enabled else 0.45) - (0.2 * escape_pressure)),
                introspection=(0.78 if mode_token else 0.45),
            )
            continue

    channel_baseline = {"learned_only": 0.72, "mixed": 0.58, "hardcoded_only": 0.42}.get(str(telemetry_channel or "unknown"), 0.5)
    if not contributions:
        return {
            "train_quality": channel_baseline,
            "integration_quality": channel_baseline,
            "stability": channel_baseline,
            "transfer": channel_baseline,
            "safety": max(0.45, channel_baseline),
            "introspection_gain": channel_baseline,
        }

    averaged: dict[str, float] = {
        "train_quality": 0.0,
        "integration_quality": 0.0,
        "stability": 0.0,
        "transfer": 0.0,
        "safety": 0.0,
        "introspection_gain": 0.0,
    }
    for row in contributions:
        for key in tuple(averaged.keys()):
            averaged[key] += _clip(row.get(key, channel_baseline))
    norm = float(len(contributions))
    for key in tuple(averaged.keys()):
        averaged[key] = _clip(averaged[key] / norm)
    return averaged


def kernel_phase_blend_metrics(*, base_metrics: dict[str, float], module_metrics: dict[str, float], micro_mode: str, objective_signals: tuple[str, ...]) -> dict[str, float]:
    def _clip(value: object, lower: float = 0.0, upper: float = 1.0) -> float:
        try:
            numeric = float(value)
        except Exception:
            numeric = lower
        if numeric < lower:
            return lower
        if numeric > upper:
            return upper
        return numeric

    mode = str(micro_mode or "").strip().lower()
    if "control" in mode:
        base_weight = 0.40
        module_weight = 0.60
    elif "integrate" in mode:
        base_weight = 0.48
        module_weight = 0.52
    elif "train" in mode:
        base_weight = 0.62
        module_weight = 0.38
    else:
        base_weight = 0.55
        module_weight = 0.45

    objective_set = {str(signal or "").strip() for signal in tuple(objective_signals or ()) if str(signal or "").strip()}
    supported_keys = ("train_quality", "integration_quality", "stability", "transfer", "safety", "introspection_gain")
    objective_values = [_clip(base_metrics.get(key, 0.5)) for key in objective_set if key in supported_keys]
    objective_alignment = _clip(sum(objective_values) / float(len(objective_values))) if objective_values else 0.5

    blended: dict[str, float] = {}
    for key in supported_keys:
        base_value = _clip(base_metrics.get(key, 0.5))
        module_value = _clip(module_metrics.get(key, base_value))
        value = _clip((base_weight * base_value) + (module_weight * module_value))
        if key in objective_set:
            value = _clip((0.82 * value) + (0.18 * objective_alignment))
        if ("train" in mode) and key in {"train_quality", "introspection_gain"}:
            value = _clip((0.78 * value) + (0.22 * module_value))
        if ("integrate" in mode) and key in {"integration_quality", "transfer"}:
            value = _clip((0.76 * value) + (0.24 * module_value))
        blended[key] = value
    return blended


def observe_kernel_phase_program_step(
    app: object,
    *,
    telemetry_channel: str,
    intervention_types: list[str],
    unresolved_objective_override: bool,
    progress_delta: int,
    reward_signal: float,
    penalty_signal: float,
) -> None:
    if not getattr(app, "kernel_phase_program_enable", False):
        return
    if getattr(app, "kernel_phase_program", None) is None:
        return
    active_target = app.kernel_phase_program.current_active_target()
    if active_target is None:
        return
    phase_id, stage_id = active_target
    _, active_micro_spec = kernel_phase_active_specs(app, phase_id=phase_id, stage_id=stage_id)
    micro_mode = str(getattr(active_micro_spec, "mode", "integrate") or "integrate")
    module_targets = tuple(getattr(active_micro_spec, "module_targets", ()) or ())
    objective_signals = tuple(getattr(active_micro_spec, "objective_signals", ()) or ())
    autonomy_snapshot = app.learned_autonomy_controller.snapshot() if getattr(app, "learned_autonomy_subphase_enable", False) else {}
    reasoning_snapshot = app._parallel_reasoning_snapshot() if getattr(app, "parallel_reasoning_enable", False) else {}
    utility_anchor = max(0.0, min(1.0, float(getattr(app, "guard_utility_ema", 0.5) or 0.5)))
    intervention_ema = max(0.0, min(1.0, float(getattr(app, "guard_intervention_ema", 0.0) or 0.0)))
    learned_score = max(0.0, min(1.0, float(autonomy_snapshot.get("score_ema", utility_anchor))))
    learned_only = max(0.0, min(1.0, float(autonomy_snapshot.get("learned_only_ema", learned_score))))
    channel_signal = {"learned_only": 1.0, "mixed": 0.66, "hardcoded_only": 0.34}.get(str(telemetry_channel or "unknown"), 0.5)
    progress_norm = max(-1.0, min(1.0, float(progress_delta)))
    progress_signal = max(0.0, min(1.0, 0.5 + (0.5 * progress_norm)))
    reward_norm = max(0.0, min(1.0, float(reward_signal) / 200.0))
    penalty_norm = max(0.0, min(1.0, float(penalty_signal) / 260.0))
    unresolved_signal = 1.0 if unresolved_objective_override else 0.0
    intervention_flag = 1.0 if intervention_types else 0.0
    reasoning_conf = max(0.0, min(1.0, float(reasoning_snapshot.get("last_confidence", 0.0))))
    reasoning_margin = max(0.0, min(1.0, 0.5 + (0.5 * float(reasoning_snapshot.get("last_confidence_margin", 0.0)))))

    base_metrics = {
        "train_quality": max(0.0, min(1.0, (0.55 * learned_score) + (0.25 * learned_only) + (0.20 * progress_signal))),
        "integration_quality": max(0.0, min(1.0, (0.60 * utility_anchor) + (0.25 * (1.0 - intervention_ema)) + (0.15 * channel_signal))),
        "stability": max(0.0, min(1.0, (0.55 * utility_anchor) + (0.30 * (1.0 - penalty_norm)) + (0.15 * (1.0 - unresolved_signal)))),
        "transfer": max(0.0, min(1.0, (0.55 * progress_signal) + (0.25 * reward_norm) + (0.20 * channel_signal))),
        "safety": max(0.0, min(1.0, (0.65 * (1.0 - penalty_norm)) + (0.20 * (1.0 - unresolved_signal)) + (0.15 * (1.0 - intervention_flag)))),
        "introspection_gain": max(0.0, min(1.0, (0.65 * reasoning_conf) + (0.35 * reasoning_margin))),
    }
    module_metrics = kernel_phase_module_metrics(app, module_targets=module_targets, telemetry_channel=telemetry_channel)
    blended_metrics = kernel_phase_blend_metrics(
        base_metrics=base_metrics,
        module_metrics=module_metrics,
        micro_mode=micro_mode,
        objective_signals=objective_signals,
    )

    train_quality = float(blended_metrics.get("train_quality", base_metrics["train_quality"]))
    integration_quality = float(blended_metrics.get("integration_quality", base_metrics["integration_quality"]))
    stability = float(blended_metrics.get("stability", base_metrics["stability"]))
    transfer = float(blended_metrics.get("transfer", base_metrics["transfer"]))
    safety = float(blended_metrics.get("safety", base_metrics["safety"]))
    introspection_gain = float(blended_metrics.get("introspection_gain", base_metrics["introspection_gain"]))

    transition = app.kernel_phase_program.observe_micro_metrics(
        phase_id,
        train_quality=train_quality,
        integration_quality=integration_quality,
        stability=stability,
        transfer=transfer,
        safety=safety,
        introspection_gain=introspection_gain,
    )
    current_target = app.kernel_phase_program.current_active_target()
    target_label = f"{current_target[0]}::{current_target[1]}" if current_target else "complete"
    apply_kernel_phase_runtime_integration(app)
    if target_label != getattr(app, "kernel_phase_last_target", None):
        app.governance_orchestrator.record_runtime_event(
            kind="adaptive_phase_target",
            payload={
                "target": target_label,
                "phase_id": phase_id,
                "stage_id": stage_id,
                "stage_mode": micro_mode,
                "module_targets": list(module_targets),
                "objective_signals": list(objective_signals),
                "disabled_phases": list(getattr(app, "kernel_phase_disable_list", ())),
                "completed_micro_total": int(app.kernel_phase_program.snapshot().get("completed_micro_total", 0)),
            },
        )
        app.kernel_phase_last_target = target_label
        app._schedule_kernel_phase_controls_refresh()
        app._schedule_micro_progress_header_update(announce_transition=False)
    if transition is not None:
        app.governance_orchestrator.record_runtime_event(
            kind="adaptive_phase_transition",
            payload={
                "phase_id": transition.phase_id,
                "from_micro": int(transition.from_micro),
                "to_micro": int(transition.to_micro),
                "completed_phase": int(transition.completed_phase),
                "reason": transition.reason,
                "stage_mode": micro_mode,
                "module_targets": list(module_targets),
                "objective_signals": list(objective_signals),
                "blended_metrics": {key: round(float(value), 4) for key, value in blended_metrics.items()},
            },
        )
        app._schedule_kernel_phase_controls_refresh()
        app._schedule_micro_progress_header_update(announce_transition=True)
        app._save_window_geometry()


def kernel_phase_runtime_policy_snapshot(app: object) -> dict[str, object]:
    active_target = app.kernel_phase_program.current_active_target() if ((app.kernel_phase_program_enable) and (app.kernel_phase_program is not None)) else None
    target_label = f"{active_target[0]}::{active_target[1]}" if active_target else ("complete" if app.kernel_phase_program_enable else "disabled")
    active_micro_mode = "--"
    objective_signals: tuple[str, ...] = ()
    if active_target is not None:
        _, active_micro_spec = kernel_phase_active_specs(app, phase_id=str(active_target[0]), stage_id=str(active_target[1]))
        if active_micro_spec is not None:
            active_micro_mode = str(getattr(active_micro_spec, "mode", "--") or "--").strip().lower()
            objective_signals = tuple(
                signal
                for signal in (
                    str(token or "").strip().lower()
                    for token in tuple(getattr(active_micro_spec, "objective_signals", ()) or ())
                )
                if signal
            )

    active_targets = kernel_phase_active_module_targets(app)
    mode_policy_payload = dict((dict(getattr(app, "kernel_phase_mode_policy_map", {}) or {})).get(str(active_micro_mode or "").strip().lower(), {}) or {})
    budget = getattr(app, "parallel_reasoning_budget", None)
    policy_snapshot: dict[str, object] = {
        "enabled": int(bool(app.kernel_phase_program_enable and app.kernel_phase_program is not None)),
        "target": str(target_label),
        "micro_mode": str(active_micro_mode or "--"),
        "objective_signals": list(objective_signals),
        "module_targets": list(active_targets),
        "module_states": {
            "learned_autonomy_controller": int(bool(getattr(app, "learned_autonomy_subphase_enable", False))),
            "parallel_reasoning_engine": int(bool(getattr(app, "parallel_reasoning_enable", False))),
            "adaptive_controller": int(bool(getattr(app, "adaptive_controller_enable", False))),
            "organism_control": int(bool(getattr(app, "organism_control_enable", False))),
            "maze_agent": int(bool(getattr(app, "maze_agent_enable", False))),
            "governance_orchestrator": int(bool(getattr(getattr(app, "governance_orchestrator", None), "enabled", False))),
        },
        "reasoning_profile": str(getattr(getattr(app, "parallel_reasoning_profile", None), "value", "--")),
        "reasoning_budget": {
            "max_branches": int(getattr(budget, "max_branches", 0) or 0),
            "max_depth": int(getattr(budget, "max_depth", 0) or 0),
            "time_budget_ms": int(getattr(budget, "time_budget_ms", 0) or 0),
            "token_budget": int(getattr(budget, "token_budget", 0) or 0),
        },
        "development_stage": str(getattr(getattr(getattr(app, "governance_orchestrator", None), "development_stage", None), "value", "--")),
        "mode_policy": mode_policy_payload,
        "safety_profile_floor": str(getattr(app, "kernel_phase_safety_profile_floor", "BALANCED")),
        "disabled_phases": list(getattr(app, "kernel_phase_disable_list", ())),
    }
    if app.kernel_phase_program is not None:
        snapshot = app.kernel_phase_program.snapshot()
        policy_snapshot["completed_micro_total"] = int(snapshot.get("completed_micro_total", 0) or 0)
        policy_snapshot["completed_phase_count"] = int(snapshot.get("completed_phase_count", 0) or 0)
    return policy_snapshot
