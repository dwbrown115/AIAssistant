from __future__ import annotations


def set_hormone_panel_text(app: object, text: str) -> None:
    if not hasattr(app, "hormone_panel_output"):
        return
    safe_text = app._redact_text(text)
    app.hormone_panel_output.config(state="normal")
    app.hormone_panel_output.delete("1.0", "end")
    app.hormone_panel_output.insert("end", safe_text)
    app.hormone_panel_output.config(state="disabled")


def hormone_monitor_text(app: object) -> str:
    lines: list[str] = []
    if not app.endocrine_enabled:
        lines.append("endocrine: disabled")
    else:
        state = app.endocrine.state()
        neural = app.endocrine.neural_state()
        lines.append(
            (
                "hormones: "
                f"H_curiosity={state.get('H_curiosity', 0.0)} "
                f"H_caution={state.get('H_caution', 0.0)} "
                f"H_persistence={state.get('H_persistence', 0.0)} "
                f"H_mv_trust={state.get('H_mv_trust', 0.0)} "
                f"H_boredom={state.get('H_boredom', 0.0)} "
                f"H_confidence={state.get('H_confidence', 0.0)}"
            )
        )
        lines.append(
            (
                "derived: "
                f"exploration_drive={neural.get('exploration_drive', 0.0)} "
                f"risk_aversion={neural.get('risk_aversion', 0.0)} "
                f"momentum={neural.get('momentum', 0.0)} "
                f"mv_reliance={neural.get('mv_reliance', 0.0)}"
            )
        )
        lines.append(
            (
                "override_phases: "
                f"objective_override_phase={app._effective_objective_override_phase_level()} "
                f"base_objective_phase={int(app.objective_override_phase_level)} "
                "hard_override_retired=1"
            )
        )
        if app.learned_autonomy_subphase_enable:
            autonomy_snapshot = app.learned_autonomy_controller.snapshot()
            lines.append(
                (
                    "learned_autonomy_subphase: "
                    f"score={autonomy_snapshot.get('score_ema', 0.0)} "
                    f"learned_only_ema={autonomy_snapshot.get('learned_only_ema', 0.0)} "
                    f"hardcoded_only_ema={autonomy_snapshot.get('hardcoded_only_ema', 0.0)} "
                    f"intervention_ema={autonomy_snapshot.get('intervention_ema', 0.0)} "
                    f"utility_ema={autonomy_snapshot.get('utility_ema', 0.0)} "
                    f"unresolved_override_ema={autonomy_snapshot.get('unresolved_override_ema', 0.0)} "
                    f"hard_phase_bonus={autonomy_snapshot.get('hard_phase_bonus', 0)} "
                    f"objective_phase_bonus={autonomy_snapshot.get('objective_phase_bonus', 0)} "
                    f"soft_scale={autonomy_snapshot.get('soft_influence_scale', 1.0)}"
                )
            )
        else:
            lines.append("learned_autonomy_subphase: disabled")

        if getattr(app, "kernel_phase_program_enable", False) and getattr(
            app, "kernel_phase_program", None
        ) is not None:
            phase_snapshot = app.kernel_phase_program.snapshot()
            active_target = phase_snapshot.get("active_target")
            completed_micro_total = int(phase_snapshot.get("completed_micro_total", 0) or 0)
            completed_phase_count = int(phase_snapshot.get("completed_phase_count", 0) or 0)
            phase_specs = tuple(getattr(app, "kernel_phase_specs", ()) or ())
            total_phase_count = len(phase_specs)
            total_micro_count = 0
            for spec in phase_specs:
                try:
                    total_micro_count += len(tuple(getattr(spec, "micro_stages", ()) or ()))
                except Exception:
                    continue
            if isinstance(active_target, (tuple, list)) and len(active_target) == 2:
                target_text = f"{active_target[0]}::{active_target[1]}"
            else:
                target_text = "complete"
            active_phase_row = None
            phases_payload = phase_snapshot.get("phases", [])
            if isinstance(active_target, (tuple, list)) and len(active_target) >= 1 and isinstance(phases_payload, list):
                active_phase_id = str(active_target[0] or "").strip()
                for row in phases_payload:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("phase_id", "") or "").strip() == active_phase_id:
                        active_phase_row = row
                        break
            if isinstance(active_phase_row, dict):
                observations = int(active_phase_row.get("observations", 0) or 0)
                effective_min_observations = int(active_phase_row.get("effective_min_observations", 0) or 0)
                score_ema = float(active_phase_row.get("score_ema", 0.0) or 0.0)
                promotion_target = float(active_phase_row.get("promotion_target", 0.0) or 0.0)
                blocked_reason = str(active_phase_row.get("promotion_blocked_reason", "") or "none")
                safety_ema = float(active_phase_row.get("safety_ema", 0.0) or 0.0)
                safety_floor = float(active_phase_row.get("safety_floor", 0.0) or 0.0)
                stability_ema = float(active_phase_row.get("stability_ema", 0.0) or 0.0)
                stability_floor = float(active_phase_row.get("stability_floor", 0.0) or 0.0)
                micro_index = int(active_phase_row.get("micro_index", 0) or 0)
                gate_ready = int(active_phase_row.get("promotion_gate_ready", 0) or 0)
                gate_met = int(active_phase_row.get("promotion_gate_met", 0) or 0)
                score_gap = max(0.0, promotion_target - score_ema)
                obs_gap = max(0, effective_min_observations - observations)
                early_cap_applied = int(active_phase_row.get("early_target_cap_applied", 0) or 0)
                lines.append(
                    (
                        "promotion_tracker: "
                        f"phase={completed_phase_count}/{max(0, total_phase_count)} "
                        f"micro={completed_micro_total}/{max(0, total_micro_count)} "
                        f"active_micro={micro_index + 1}/4 "
                        f"gate_ready={gate_ready} "
                        f"gate_met={gate_met} "
                        f"obs_gap={obs_gap} "
                        f"score_gap={round(score_gap, 4)} "
                        f"early_cap_applied={early_cap_applied}"
                    )
                )
                lines.append(
                    (
                        "adaptive_phase_program: "
                        f"target={target_text} "
                        f"completed_micro_total={completed_micro_total} "
                        f"obs={observations}/{effective_min_observations} "
                        f"score={round(score_ema, 4)}/{round(promotion_target, 4)} "
                        f"safety={round(safety_ema, 4)}/{round(safety_floor, 4)} "
                        f"stability={round(stability_ema, 4)}/{round(stability_floor, 4)} "
                        f"blocked={blocked_reason} "
                        f"disabled={','.join(getattr(app, 'kernel_phase_disable_list', ()))}"
                    )
                )
            else:
                lines.append(
                    (
                        "promotion_tracker: "
                        f"phase={completed_phase_count}/{max(0, total_phase_count)} "
                        f"micro={completed_micro_total}/{max(0, total_micro_count)} "
                        "active_micro=-- gate_ready=0 gate_met=0 obs_gap=0 score_gap=0.0 early_cap_applied=0"
                    )
                )
                lines.append(
                    (
                        "adaptive_phase_program: "
                        f"target={target_text} "
                        f"completed_micro_total={completed_micro_total} "
                        f"disabled={','.join(getattr(app, 'kernel_phase_disable_list', ()))}"
                    )
                )
        else:
            lines.append("adaptive_phase_program: disabled")

        if app.parallel_reasoning_enable:
            reasoning_snapshot = app._parallel_reasoning_snapshot()
            lines.append(
                (
                    "parallel_reasoning_engine: "
                    f"confidence={reasoning_snapshot.get('last_confidence', 0.0)} "
                    f"confidence_margin={reasoning_snapshot.get('last_confidence_margin', 0.0)} "
                    f"confidence_ema={reasoning_snapshot.get('confidence_ema', 0.0)} "
                    f"utility_ema={reasoning_snapshot.get('utility_ema', 0.0)} "
                    f"trust_local={reasoning_snapshot.get('plan_trust_local', 0.0)} "
                    f"trust_adaptive={reasoning_snapshot.get('plan_trust_adaptive', 0.0)} "
                    f"trust_deliberative={reasoning_snapshot.get('plan_trust_deliberative', 0.0)} "
                    f"steps={reasoning_snapshot.get('step_count', 0)}"
                )
            )
        else:
            lines.append("parallel_reasoning_engine: disabled")

        governance_snapshot = app._unified_introspection_snapshot()
        recent_events = governance_snapshot.get("recent_events", [])
        lines.append(
            (
                "governance_orchestrator: "
                f"enabled={governance_snapshot.get('enabled', 0)} "
                f"policy={governance_snapshot.get('policy_version', 'unknown')} "
                f"stage={governance_snapshot.get('development_stage', 'unknown')} "
                f"registered={len(governance_snapshot.get('registered_modules', []))} "
                f"recent_events={len(recent_events) if isinstance(recent_events, list) else 0}"
            )
        )

    if app.adaptive_progress_report_enable:
        lines.append(
            (
                "adaptive_progress_report: "
                f"inflight={1 if app._adaptive_progress_report_inflight else 0} "
                f"last_sent_step={app._last_adaptive_progress_report_step} "
                f"last_feedback_step={app.adaptive_progress_last_feedback_step}"
            )
        )
        if app.adaptive_progress_last_feedback_summary:
            lines.append(f"report_feedback: {app.adaptive_progress_last_feedback_summary}")
        if app.adaptive_progress_last_autotune_summary:
            lines.append(f"autotune: {app.adaptive_progress_last_autotune_summary}")
        if app.adaptive_progress_last_error:
            lines.append(f"report_error: {app.adaptive_progress_last_error}")
    else:
        lines.append("adaptive_progress_report: disabled")

    return "\n".join(lines)


def refresh_hormone_panel(app: object) -> None:
    if not hasattr(app, "hormone_panel_output"):
        return

    app._set_hormone_panel_text(app._hormone_monitor_text())
