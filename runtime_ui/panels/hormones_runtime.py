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
