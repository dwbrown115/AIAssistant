from __future__ import annotations

import json


def refresh_game_state(app: object) -> None:
    px1, py1, px2, py2 = app.game_canvas.coords(app.player)
    tx1, ty1, tx2, ty2 = app.game_canvas.coords(app.target)

    player_center_x = (px1 + px2) / 2
    player_center_y = (py1 + py2) / 2
    target_center_x = (tx1 + tx2) / 2
    target_center_y = (ty1 + ty2) / 2

    dx = round(target_center_x - player_center_x, 2)
    dy = round(target_center_y - player_center_y, 2)
    player_row, player_col = app._cell_from_center(player_center_x, player_center_y)
    target_row, target_col = app._cell_from_center(target_center_x, target_center_y)
    distance_steps = app._distance_between_cells((player_row, player_col), (target_row, target_col))
    proximity_ratio = max(0.0, 1.0 - (distance_steps / max(1, (app.grid_cells * 2 - 2))))
    if app.last_manhattan_distance == 0:
        temperature = "unknown"
    elif distance_steps < app.last_manhattan_distance:
        temperature = "hotter"
    elif distance_steps > app.last_manhattan_distance:
        temperature = "colder"
    else:
        temperature = "same"
    app.last_manhattan_distance = distance_steps
    efficiency = 0.0
    if app.episode_steps > 0:
        efficiency = min(1.0, app.episode_optimal_steps / app.episode_steps)

    # Update live positions immediately from canvas sampling so perception,
    # memory snapshots, and planner context remain frame-consistent.
    app.current_player_cell = (player_row, player_col)
    app.current_target_cell = (target_row, target_col)

    mode = app._normalized_layout_mode()
    if mode == "maze":
        app._ensure_machine_vision_cellmap_for_current_maze()
        app._update_maze_known_map(player_row, player_col, radius=1, facing=app.player_facing)
        app._resolve_visible_predictions()
        app._queue_frontier_predictions()
        if app.endocrine_enabled:
            endocrine_before = app.endocrine.state()
            app.endocrine.tick(app.memory_step_index)
            signature_text = app._current_pattern_signature((player_row, player_col))
            if signature_text:
                try:
                    app.endocrine.update_from_signature(json.loads(signature_text), app.memory_step_index)
                except Exception:  # noqa: BLE001
                    pass
            endocrine_after = app.endocrine.state()
            endocrine_delta = app._endocrine_delta_text(endocrine_before, endocrine_after)
            if endocrine_delta and app._last_endocrine_trace_step != app.memory_step_index:
                app._last_endocrine_trace_step = app.memory_step_index
                app._append_endocrine_event(
                    "signature",
                    (
                        f"delta=[{endocrine_delta}] cell={player_row},{player_col} "
                        f"facing={app.player_facing}"
                    ),
                )
        app.mental_sweep_cells = app._build_mental_sweep(player_row, player_col)
        app._draw_fov_overlay(player_row, player_col)
        app._draw_mental_sweep_overlay(player_row, player_col)
        suppress_wm_preview = bool(getattr(app, "_suppress_wm_snapshot_during_look_preview", False))
        if not suppress_wm_preview:
            app._working_memory_snapshot(current_cell=(player_row, player_col))
            app._store_current_maze_memory_snapshot()
        personality = app.maze_personality or {}
        visibility_legend_line = (
            "Legend: P=player, S=visible episode start, E=visible exit, O=full-visible open, H=half-visible open (cone boundary), "
            "B=visible blocker/wall, ?=not visible, arrows (^ > v <)=single opening-edge marker side, x=marked-off verified-empty side opening.\n\n"
            if not app.maze_ascii_visible_only
            else
            "Legend: P=player, S=visible episode start, E=visible exit, O=full-visible open, H=half-visible open (cone boundary), "
            "B=visible blocker/wall, .=hidden cell omitted/cropped by visibility mode, "
            "arrows (^ > v <)=single opening-edge marker side, x=marked-off verified-empty side opening.\n\n"
        )
        perception_block = (
            f"Directional FOV status (facing={app.player_facing}, depth={app.maze_fov_depth}, "
            f"peripheral={app.maze_fov_peripheral}, cone_deg={round(app.maze_fov_cone_degrees, 1)}, "
            f"lateral_extra_deg={round(app.maze_fov_lateral_extra_degrees, 1)}, "
            f"lateral_near_depth={round(app.maze_fov_lateral_near_depth, 2)}, "
            f"lateral_band={round(app.maze_fov_lateral_band_cells, 2)}, "
            f"lateral_floor+={round(app.maze_fov_lateral_floor_margin, 3)}, "
            f"falloff={round(app.maze_fov_distance_falloff, 3)}, "
            f"corner_graze={round(app.maze_fov_corner_graze_factor, 3)}, "
            f"wedge_dist_scale={round(app.maze_fov_wedge_distance_scale, 3)}, "
            f"full>={round(app.maze_fov_full_threshold, 3)}, half>={round(app.maze_fov_half_threshold, 3)}, "
            f"behind=hidden):\n"
            f"{app._build_local_status_snapshot(player_row, player_col, radius=1, include_render_details=True)}\n"
            f"{visibility_legend_line}"
            "Renderable FOV (model-friendly, same visibility source as canvas):\n"
            f"{app._build_interpretable_fov_snapshot(player_row, player_col)}\n\n"
            f"Maze personality: {app.maze_personality_name} "
            f"(dead_end_allowance={int(personality.get('dead_end_allowance', app.dead_end_learning_allowance_base))}, "
            f"dead_end_learned={app.episode_dead_end_learn_events}, "
            f"novelty_scale={round(float(personality.get('novelty_reward_scale', 1.0)), 2)}, "
            f"dead_end_scale={round(float(personality.get('dead_end_penalty_scale', 1.0)), 2)}).\n\n"
            "Boundary rule: outside the grid is a hard wall (WALL), never unknown/open.\n"
            f"Immediate move walls/open: {app._boundary_blocked_summary((player_row, player_col))}\n\n"
            f"Mental directional edge scan (look-around before move):\n"
            f"{app._mental_edge_scan_summary(player_row, player_col)}"
        )
        target_metrics_line = "Target signal hidden. Distance/proximity feedback disabled in maze mode."
        episode_objective_line = "Episode optimal steps hidden in maze mode."
    else:
        app._clear_fov_overlay()
        app._clear_mental_sweep_overlay()
        app.mental_sweep_cells = {}
        perception_block = (
            "Grid snapshot:\n"
            f"{app._build_grid_snapshot(player_center_x, player_center_y, target_center_x, target_center_y)}"
        )
        target_metrics_line = (
            f"Current shortest-path distance: {distance_steps} steps. "
            f"Proximity ratio: {round(proximity_ratio, 3)}. "
            f"Hotter/colder signal: {temperature}."
        )
        episode_objective_line = f"Episode optimal steps at spawn: {app.episode_optimal_steps}."

    app._update_machine_vision_localization(player_row, player_col)
    app._update_machine_vision_exit_localization(player_row, player_col)
    app._draw_machine_vision_cellmap_overlay()
    app._draw_machine_vision_route_overlay()
    app._draw_machine_vision_prediction_overlay(player_row, player_col)
    app._draw_machine_vision_exit_prediction_overlay(player_row, player_col)
    app._draw_mv_render_debug_overlay(player_row, player_col, target_row, target_col)
    if app._machine_vision_enabled():
        vision_pred_cell = app.machine_vision_last_prediction.get("predicted_cell", (-1, -1))
        vision_conf = float(app.machine_vision_last_prediction.get("confidence", 0.0) or 0.0)
        vision_support = int(app.machine_vision_last_prediction.get("support", 0) or 0)
        vision_error = int(app.machine_vision_last_prediction.get("manhattan_error", 0) or 0)
        machine_vision_line = (
            "Machine vision player localization: "
            f"pred={vision_pred_cell} actual=({player_row}, {player_col}) "
            f"conf={round(vision_conf, 3)} support={vision_support} "
            f"accuracy={round(app._machine_vision_accuracy(), 3)} "
            f"mae={round(app._machine_vision_mae(), 3)} "
            f"last_error={vision_error} samples={app.machine_vision_total_samples}."
        )
        vision_exit_pred_cell = app.machine_vision_exit_last_prediction.get("predicted_cell", (-1, -1))
        vision_exit_conf = float(app.machine_vision_exit_last_prediction.get("confidence", 0.0) or 0.0)
        vision_exit_support = int(app.machine_vision_exit_last_prediction.get("support", 0) or 0)
        vision_exit_error = int(app.machine_vision_exit_last_prediction.get("manhattan_error", 0) or 0)
        machine_vision_exit_line = (
            "Machine vision exit localization: "
            f"pred={vision_exit_pred_cell} actual={app.current_target_cell} "
            f"conf={round(vision_exit_conf, 3)} support={vision_exit_support} "
            f"accuracy={round(app._machine_vision_exit_accuracy(), 3)} "
            f"mae={round(app._machine_vision_exit_mae(), 3)} "
            f"last_error={vision_exit_error} samples={app.machine_vision_exit_total_samples}."
        )
        machine_vision_cellmap_line = app._machine_vision_cellmap_status_line()
        machine_vision_view_line = (
            "Machine vision sees (grid-sized training snapshot):\n"
            f"{app._machine_vision_grid_snapshot(player_row, player_col)}"
        )
        mv_hints = app._machine_vision_kernel_hints()
        mv_self_pred = tuple(mv_hints.get("self_pred_cell", (-1, -1)) or (-1, -1))
        mv_exit_pred = tuple(mv_hints.get("exit_pred_cell", (-1, -1)) or (-1, -1))
        mv_self_err_raw = mv_hints.get("self_error", -1)
        mv_self_err = int(mv_self_err_raw if mv_self_err_raw is not None else -1)
        machine_vision_kernel_hint_line = (
            "Machine vision kernel hint channel: "
            f"enabled={(1 if bool(mv_hints.get('enabled', False)) else 0)} "
            f"exit_usable={(1 if bool(mv_hints.get('exit_usable', False)) else 0)} "
            f"self_pred={mv_self_pred} self_err={mv_self_err} self_conf={round(float(mv_hints.get('self_conf', 0.0) or 0.0), 3)} "
            f"exit_pred={mv_exit_pred} exit_conf={round(float(mv_hints.get('exit_conf', 0.0) or 0.0), 3)} "
            f"hint_strength={round(float(mv_hints.get('exit_hint_strength', 0.0) or 0.0), 3)}."
        )
        last_mv_kernel = dict(getattr(app, "_last_mv_kernel_breakdown", {}) or {})
        machine_vision_kernel_influence_line = (
            "Machine vision kernel scoring (last selected move): "
            f"step={int(getattr(app, '_last_mv_kernel_breakdown_step', -1) or -1)} "
            f"move={str(last_mv_kernel.get('move', '') or '(none)')} "
            f"exit_usable={int(last_mv_kernel.get('mv_exit_usable', 0) or 0)} "
            f"exit_pred={tuple(last_mv_kernel.get('mv_exit_pred_cell', (-1, -1)) or (-1, -1))} "
            f"exit_hint_strength={round(float(last_mv_kernel.get('mv_exit_hint_strength', 0.0) or 0.0), 3)} "
            f"exit_bonus={int(last_mv_kernel.get('mv_exit_alignment_bonus', 0) or 0)} "
            f"exit_penalty={int(last_mv_kernel.get('mv_exit_alignment_penalty', 0) or 0)} "
            f"cellmap_usable={int(last_mv_kernel.get('mv_cellmap_usable', 0) or 0)} "
            f"cellmap_open_bonus={int(last_mv_kernel.get('mv_cellmap_open_alignment_bonus', 0) or 0)} "
            f"cellmap_blocked_penalty={int(last_mv_kernel.get('mv_cellmap_blocked_risk_penalty', 0) or 0)} "
            f"cellmap_neighbor_open_bonus={int(last_mv_kernel.get('mv_cellmap_neighbor_open_bonus', 0) or 0)} "
            f"cellmap_neighbor_blocked_penalty={int(last_mv_kernel.get('mv_cellmap_neighbor_blocked_penalty', 0) or 0)}."
        )
        machine_vision_render_debug_line = app._mv_render_debug_status_line()
    else:
        machine_vision_line = "Machine vision player localization: disabled (master toggle off)."
        machine_vision_exit_line = "Machine vision exit localization: disabled (master toggle off)."
        machine_vision_cellmap_line = "Machine vision cell map: disabled (master toggle off)."
        machine_vision_view_line = "Machine vision sees: disabled (master toggle off)."
        machine_vision_kernel_hint_line = "Machine vision kernel hint channel: disabled (master toggle off)."
        machine_vision_kernel_influence_line = "Machine vision kernel scoring (last selected move): unavailable (master toggle off)."
        machine_vision_render_debug_line = app._mv_render_debug_status_line()

    app._draw_pseudo3d_view(player_row, player_col)

    snapshot = (
        f"Canvas: {app.canvas_width}x{app.canvas_height}. "
        f"Mode: {mode}. "
        f"Maze difficulty: {app._normalized_maze_difficulty()}. "
        f"Maze algorithm: {app.current_maze_algorithm or 'n/a'}. "
        f"Player center: ({round(player_center_x, 2)}, {round(player_center_y, 2)}). "
        f"Target center hidden. Vector target-player hidden.\n"
        f"Player cell(row,col): ({player_row}, {player_col}). "
        f"Target cell hidden. "
        f"Blocked cells: {len(app.blocked_cells)}. "
        f"{target_metrics_line}\n"
        f"{episode_objective_line} "
        f"Episode steps taken: {app.episode_steps}. "
        f"Maze attempt count (current): {app.episode_maze_attempt_count}. "
        f"Last maze solved attempts: {app.last_maze_solve_attempts}. "
        f"Episode revisit steps: {app.episode_revisit_steps}. "
        f"Episode backtracks: {app.episode_backtracks}. "
        f"Current efficiency: {round(efficiency, 3)}. "
        f"Total reward: {round(app.total_reward, 2)}. "
        f"Prediction score (maze): {round(app.prediction_score_current_maze, 2)} "
        f"(lifetime={round(app.prediction_score_total, 2)}, "
        f"occ_acc={round(app._prediction_accuracy(), 3)}, "
        f"shape_acc={round(app._prediction_shape_accuracy(), 3)}, "
        f"full_acc={round(app._prediction_full_accuracy(), 3)}, "
        f"occ_brier={round(app._prediction_avg_occupancy_brier(), 3)}, "
        f"shape_brier={round(app._prediction_avg_shape_brier(), 3)}, "
        f"pending={len(app.prediction_memory_active)}, expired={app.prediction_expired_count}).\n"
        f"{machine_vision_line}\n"
        f"{machine_vision_exit_line}\n"
        f"{machine_vision_cellmap_line}\n"
        f"{machine_vision_kernel_hint_line}\n"
        f"{machine_vision_kernel_influence_line}\n"
        f"{machine_vision_render_debug_line}\n"
        f"{machine_vision_view_line}\n"
        f"{perception_block}"
    )

    with app.game_state_lock:
        app.current_player_cell = (player_row, player_col)
        app.current_target_cell = (target_row, target_col)
        app.latest_game_state = snapshot

    app._refresh_hormone_panel()
