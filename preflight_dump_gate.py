#!/usr/bin/env python3
"""Preflight gate for maze log dumps.

Usage:
  python preflight_dump_gate.py "Log Dump/15_mazes_medium_20260403_093348.txt"
  python preflight_dump_gate.py "Log Dump/15_mazes_medium_20260403_093348.txt" --strict --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


OVERRIDE_MARKERS: dict[str, str] = {
    "objective_override": "Objective override:",
    "stuck_reexplore_override": "Stuck re-explore override:",
    "map_doubt_override": "Map-doubt override:",
    "targeted_model_override": "Targeted-model override:",
    "anti_oscillation_override": "Anti-oscillation override:",
    "cycle_avoid_override": "Cycle-avoid override:",
    "terminal_corridor_override": "Terminal/boxed-corridor override:",
    "plan_hold_override": "Plan-hold override:",
    "memory_risk_replay_guard": "[MEMORY-RISK-REPLAY-GUARD:",
    "objective_relax_guard": "[OBJECTIVE-RELAX-GUARD:",
    "objective_verify_gate": "[OBJECTIVE-VERIFY-GATE:",
    "objective_progress_guard": "[OBJECTIVE-PROGRESS-GUARD:",
}

PROFILE_THRESHOLDS: dict[str, dict[str, float]] = {
    "batch4": {
        "max_guard_override_rate": 0.45,
        "max_intervention_rate": 0.45,
        "max_stuck_reexplore_override": 60,
        "max_anti_oscillation_override": 220,
        "max_targeted_model_override": 80,
        "min_learned_only_rate": 0.45,
        "max_hardcoded_only_rate": 0.35,
        "max_unresolved_objective_override_rate": 0.03,
        "min_phase1_telemetry_coverage": 0.85,
        "min_projection_telemetry_coverage_when_enabled": 0.80,
        "min_projection_scored_coverage_when_active": 0.02,
        "min_projection_beneficial_rate": 0.25,
        "max_projection_non_beneficial_rate_when_active": 0.85,
        "max_projection_clip_rate": 0.35,
    },
    "relaxed": {
        "max_guard_override_rate": 0.65,
        "max_intervention_rate": 0.65,
        "max_stuck_reexplore_override": 140,
        "max_anti_oscillation_override": 360,
        "max_targeted_model_override": 160,
        "min_learned_only_rate": 0.30,
        "max_hardcoded_only_rate": 0.50,
        "max_unresolved_objective_override_rate": 0.06,
        "min_phase1_telemetry_coverage": 0.65,
        "min_projection_telemetry_coverage_when_enabled": 0.45,
        "min_projection_scored_coverage_when_active": 0.01,
        "min_projection_beneficial_rate": 0.12,
        "max_projection_non_beneficial_rate_when_active": 0.95,
        "max_projection_clip_rate": 0.60,
    },
}


def _to_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if cleaned in {"true", "1", "yes"}:
        return True
    if cleaned in {"false", "0", "no"}:
        return False
    return None


def _parse_scalar(value: str) -> int | float | str:
    value = value.strip().rstrip(",")
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", value):
        return float(value)
    return value


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return int(default)
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return int(default)


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return float(default)
    try:
        return float(text)
    except ValueError:
        return float(default)


def _parse_key_values(span: str) -> dict[str, int | float | str]:
    payload: dict[str, int | float | str] = {}
    for token in span.strip().split():
        if "=" not in token:
            continue
        key, raw = token.split("=", 1)
        payload[key.strip()] = _parse_scalar(raw)
    return payload


def parse_dump(text: str, profile: str) -> dict[str, object]:
    planner_lines = [
        line
        for line in text.splitlines()
        if line.startswith("step=") and "proposal_source=" in line
    ]
    planner_steps = len(planner_lines)

    step_indices = []
    for line in planner_lines:
        match = re.match(r"^step=(\d+)", line)
        if match:
            step_indices.append(int(match.group(1)))

    override_lines = [line for line in planner_lines if "guard_override=True" in line]
    override_count = len(override_lines)
    override_rate = (override_count / planner_steps) if planner_steps else 0.0

    marker_counts: dict[str, int] = {}
    for key, marker in OVERRIDE_MARKERS.items():
        marker_counts[key] = sum(1 for line in planner_lines if marker in line)
    marker_indices_map: dict[str, list[int]] = {
        key: [idx for idx, line in enumerate(planner_lines) if marker in line]
        for key, marker in OVERRIDE_MARKERS.items()
    }

    telemetry_channel_re = re.compile(r"telemetry_channel=([a-z_]+)")
    telemetry_intervention_re = re.compile(r"telemetry_intervention=(\d+)")
    telemetry_progress_re = re.compile(r"telemetry_progress_delta=(-?\d+)")
    telemetry_penalty_re = re.compile(r"telemetry_penalty_signal=(-?\d+(?:\.\d+)?)")
    telemetry_reward_re = re.compile(r"telemetry_reward_signal=(-?\d+(?:\.\d+)?)")
    telemetry_score_re = re.compile(r"telemetry_decision_score=(-?\d+(?:\.\d+)?)")
    projection_delta_re = re.compile(r"projection_score_delta=(-?\d+)")
    projection_scaled_re = re.compile(r"projection_score_delta_scaled=(-?\d+(?:\.\d+)?)")
    projection_clipped_re = re.compile(r"projection_score_delta_clipped=(\d+)")
    projection_forward_re = re.compile(r"projection_forward_bonus=(-?\d+)")
    projection_back_penalty_re = re.compile(r"projection_backward_penalty=(-?\d+)")
    projection_back_escape_re = re.compile(r"projection_backward_escape_bonus=(-?\d+)")
    projection_scale_re = re.compile(r"projection_score_(?:influence_)?scale=(-?\d+(?:\.\d+)?)")

    telemetry_present_flags: list[bool] = []
    telemetry_channels: list[str] = []
    telemetry_interventions: list[int] = []
    telemetry_progress_values: list[float] = []
    telemetry_penalty_values: list[float] = []
    telemetry_reward_values: list[float] = []
    telemetry_score_values: list[float] = []
    telemetry_rows = 0
    projection_present_flags: list[bool] = []
    projection_delta_values: list[float] = []
    projection_scaled_values: list[float] = []
    projection_clipped_values: list[int] = []
    projection_forward_values: list[float] = []
    projection_back_penalty_values: list[float] = []
    projection_back_escape_values: list[float] = []
    projection_scale_values: list[float] = []
    projection_rows = 0
    for line in planner_lines:
        channel_match = telemetry_channel_re.search(line)
        has_telemetry = channel_match is not None
        telemetry_present_flags.append(has_telemetry)
        if has_telemetry:
            telemetry_rows += 1
            telemetry_channels.append(str(channel_match.group(1)).strip().lower())
        else:
            telemetry_channels.append("unknown")

        intervention_match = telemetry_intervention_re.search(line)
        telemetry_interventions.append(int(intervention_match.group(1)) if intervention_match else 0)

        progress_match = telemetry_progress_re.search(line)
        telemetry_progress_values.append(float(progress_match.group(1)) if progress_match else 0.0)

        penalty_match = telemetry_penalty_re.search(line)
        telemetry_penalty_values.append(float(penalty_match.group(1)) if penalty_match else 0.0)

        reward_match = telemetry_reward_re.search(line)
        telemetry_reward_values.append(float(reward_match.group(1)) if reward_match else 0.0)

        score_match = telemetry_score_re.search(line)
        telemetry_score_values.append(float(score_match.group(1)) if score_match else 0.0)

        projection_delta_match = projection_delta_re.search(line)
        has_projection = projection_delta_match is not None
        projection_present_flags.append(has_projection)
        if has_projection:
            projection_rows += 1
        projection_delta_value = float(projection_delta_match.group(1)) if projection_delta_match else 0.0
        projection_delta_values.append(projection_delta_value)

        projection_scaled_match = projection_scaled_re.search(line)
        projection_scaled_values.append(float(projection_scaled_match.group(1)) if projection_scaled_match else 0.0)

        projection_clipped_match = projection_clipped_re.search(line)
        projection_clipped_values.append(int(projection_clipped_match.group(1)) if projection_clipped_match else 0)

        projection_forward_match = projection_forward_re.search(line)
        projection_forward_values.append(float(projection_forward_match.group(1)) if projection_forward_match else 0.0)

        projection_back_penalty_match = projection_back_penalty_re.search(line)
        projection_back_penalty_values.append(
            float(projection_back_penalty_match.group(1)) if projection_back_penalty_match else 0.0
        )

        projection_back_escape_match = projection_back_escape_re.search(line)
        projection_back_escape_values.append(
            float(projection_back_escape_match.group(1)) if projection_back_escape_match else 0.0
        )

        projection_scale_match = projection_scale_re.search(line)
        projection_scale_values.append(float(projection_scale_match.group(1)) if projection_scale_match else 0.0)

    intervention_markers = list(OVERRIDE_MARKERS.values())
    routing_markers = [
        "Objective routing:",
        "MV route mode routing:",
        "Fully-mapped routing:",
    ]

    learned_memory_re = re.compile(r"memory_event=(semantic:reinforced|stm:reinforced|novel->stm|familiar->pruned)")
    heuristic_learned_rows = {
        idx
        for idx, line in enumerate(planner_lines)
        if learned_memory_re.search(line)
    }
    heuristic_intervention_rows = {
        idx
        for idx, line in enumerate(planner_lines)
        if ("guard_override=True" in line)
        or any(marker in line for marker in intervention_markers)
    }
    intervention_rows: set[int] = set()
    learned_rows: set[int] = set()
    hardcoded_rows: set[int] = set()
    for idx in range(planner_steps):
        if telemetry_present_flags[idx]:
            channel = telemetry_channels[idx]
            intervention_flag = telemetry_interventions[idx] > 0
            if intervention_flag:
                intervention_rows.add(idx)
            if channel == "learned_only":
                learned_rows.add(idx)
            elif channel == "hardcoded_only":
                hardcoded_rows.add(idx)
            elif channel == "mixed":
                learned_rows.add(idx)
                hardcoded_rows.add(idx)
        else:
            if idx in heuristic_intervention_rows:
                intervention_rows.add(idx)
                hardcoded_rows.add(idx)
            if idx in heuristic_learned_rows:
                learned_rows.add(idx)

    hardcoded_rows = hardcoded_rows.union(intervention_rows)
    routing_rows = {
        idx
        for idx, line in enumerate(planner_lines)
        if any(marker in line for marker in routing_markers)
    }
    learned_only_rows = learned_rows - hardcoded_rows
    hardcoded_only_rows = hardcoded_rows - learned_rows
    mixed_rows = learned_rows.intersection(hardcoded_rows)
    unknown_rows = set(range(planner_steps)) - learned_rows.union(hardcoded_rows)

    def _rate(count: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return float(count) / float(total)

    def _mean(values: list[float], indices: list[int]) -> float:
        if not indices:
            return 0.0
        return float(sum(values[idx] for idx in indices)) / float(len(indices))

    def _window_mean(values: list[float], indices: list[int], window: int) -> float:
        if not indices:
            return 0.0
        total = 0.0
        for idx in indices:
            upper = min(len(values), idx + max(1, window))
            total += float(sum(values[idx:upper]))
        return total / float(len(indices))

    objective_unknown_frontier_re = re.compile(r"unknown=(\d+)\s+frontier=(\d+)")
    unresolved_objective_override_rows = 0
    for line in planner_lines:
        if "Objective override:" not in line:
            continue
        match = objective_unknown_frontier_re.search(line)
        if not match:
            continue
        unknown_now = int(match.group(1))
        frontier_now = int(match.group(2))
        if unknown_now > 0 or frontier_now > 0:
            unresolved_objective_override_rows += 1
    unresolved_objective_override_rate = _rate(unresolved_objective_override_rows, planner_steps)
    intervention_rate = _rate(len(intervention_rows), planner_steps)
    routing_rate = _rate(len(routing_rows), planner_steps)
    telemetry_coverage = _rate(telemetry_rows, planner_steps)

    telemetry_indices = [idx for idx, present in enumerate(telemetry_present_flags) if present]
    projection_indices = [idx for idx, present in enumerate(projection_present_flags) if present]
    telemetry_intervention_indices = [idx for idx in telemetry_indices if telemetry_interventions[idx] > 0]
    telemetry_non_intervention_indices = [idx for idx in telemetry_indices if telemetry_interventions[idx] <= 0]
    phase1_window = 3
    phase1_intervention_progress_avg = _mean(telemetry_progress_values, telemetry_intervention_indices)
    phase1_non_intervention_progress_avg = _mean(telemetry_progress_values, telemetry_non_intervention_indices)
    phase1_intervention_penalty_avg = _mean(telemetry_penalty_values, telemetry_intervention_indices)
    phase1_non_intervention_penalty_avg = _mean(telemetry_penalty_values, telemetry_non_intervention_indices)
    phase1_intervention_progress_win_avg = _window_mean(
        telemetry_progress_values,
        telemetry_intervention_indices,
        phase1_window,
    )
    phase1_non_intervention_progress_win_avg = _window_mean(
        telemetry_progress_values,
        telemetry_non_intervention_indices,
        phase1_window,
    )
    phase1_intervention_penalty_win_avg = _window_mean(
        telemetry_penalty_values,
        telemetry_intervention_indices,
        phase1_window,
    )
    phase1_non_intervention_penalty_win_avg = _window_mean(
        telemetry_penalty_values,
        telemetry_non_intervention_indices,
        phase1_window,
    )
    phase1_intervention_utility_win = (
        phase1_intervention_progress_win_avg - phase1_non_intervention_progress_win_avg
    )
    phase1_penalty_delta_win = (
        phase1_non_intervention_penalty_win_avg - phase1_intervention_penalty_win_avg
    )

    projection_coverage = _rate(projection_rows, planner_steps)
    projection_beneficial_rows = [idx for idx in projection_indices if projection_delta_values[idx] < 0.0]
    projection_adverse_rows = [idx for idx in projection_indices if projection_delta_values[idx] > 0.0]
    projection_neutral_rows = [idx for idx in projection_indices if projection_delta_values[idx] == 0.0]
    projection_clipped_rows = [idx for idx in projection_indices if projection_clipped_values[idx] > 0]
    projection_beneficial_rate = _rate(len(projection_beneficial_rows), len(projection_indices))
    projection_adverse_rate = _rate(len(projection_adverse_rows), len(projection_indices))
    projection_non_beneficial_rate = 1.0 - projection_beneficial_rate if projection_indices else 1.0
    projection_clip_rate = _rate(len(projection_clipped_rows), len(projection_indices))
    projection_delta_avg = _mean(projection_delta_values, projection_indices)
    projection_delta_scaled_avg = _mean(projection_scaled_values, projection_indices)
    projection_forward_avg = _mean(projection_forward_values, projection_indices)
    projection_back_penalty_avg = _mean(projection_back_penalty_values, projection_indices)
    projection_back_escape_avg = _mean(projection_back_escape_values, projection_indices)
    projection_influence_scale_avg = _mean(projection_scale_values, projection_indices)
    projection_effectiveness_score = projection_beneficial_rate - projection_adverse_rate
    projection_abs_delta_avg = (
        float(sum(abs(projection_delta_values[idx]) for idx in projection_indices)) / float(len(projection_indices))
        if projection_indices
        else 0.0
    )
    total_tag_lines = len(re.findall(r"tags=[^\n]*", text))
    projection_guidance_tag_rows = len(
        re.findall(r"tags=[^\n]*\bprojection_guidance_reward\b", text)
    )
    projection_guidance_tag_rate = _rate(projection_guidance_tag_rows, total_tag_lines)
    projection_usage_detected = bool(projection_indices) or (projection_guidance_tag_rows > 0)
    projection_enabled = (
        "projection_module=1" in text
        or "MAZE_PROJECTION_MODULE_ENABLE=1" in text
        or "projection_score_delta=" in text
        or (projection_guidance_tag_rows > 0)
    )

    mv_player_enabled = 0
    mv_player_training = 0
    mv_player_samples = 0
    mv_player_exact_hits = 0
    mv_player_accuracy = 0.0
    mv_player_mae = 0.0
    mv_exit_enabled = 0
    mv_exit_training = 0
    mv_exit_samples = 0
    mv_exit_exact_hits = 0
    mv_exit_accuracy = 0.0
    mv_exit_mae = 0.0
    mv_cellmap_ready = 0
    mv_cellmap_accuracy = 0.0
    mv_cellmap_confident_accuracy = 0.0
    mv_cellmap_refine_passes = 0
    mv_cellmap_confident = 0
    mv_cellmap_total = 0

    mv_player_match = None
    for match in re.finditer(r"machine_vision_player_localization:\s*\n([^\n]+)", text, flags=re.IGNORECASE):
        mv_player_match = match
    if mv_player_match is not None:
        player_payload = _parse_key_values(mv_player_match.group(1))
        mv_player_enabled = _coerce_int(player_payload.get("enabled", 0))
        mv_player_training = _coerce_int(player_payload.get("training", 0))
        mv_player_samples = _coerce_int(player_payload.get("samples", 0))
        mv_player_exact_hits = _coerce_int(player_payload.get("exact_hits", 0))
        mv_player_accuracy = _coerce_float(player_payload.get("accuracy", 0.0))
        mv_player_mae = _coerce_float(player_payload.get("mae", 0.0))

    mv_exit_match = None
    for match in re.finditer(r"machine_vision_exit_localization:\s*\n([^\n]+)", text, flags=re.IGNORECASE):
        mv_exit_match = match
    if mv_exit_match is not None:
        exit_payload = _parse_key_values(mv_exit_match.group(1))
        mv_exit_enabled = _coerce_int(exit_payload.get("enabled", 0))
        mv_exit_training = _coerce_int(exit_payload.get("training", 0))
        mv_exit_samples = _coerce_int(exit_payload.get("samples", 0))
        mv_exit_exact_hits = _coerce_int(exit_payload.get("exact_hits", 0))
        mv_exit_accuracy = _coerce_float(exit_payload.get("accuracy", 0.0))
        mv_exit_mae = _coerce_float(exit_payload.get("mae", 0.0))

    mv_cellmap_match = None
    for match in re.finditer(r"machine_vision_cellmap_bootstrap:\s*\n([^\n]+)", text, flags=re.IGNORECASE):
        mv_cellmap_match = match
    if mv_cellmap_match is not None:
        cellmap_line = str(mv_cellmap_match.group(1) or "").strip()
        cellmap_payload = _parse_key_values(cellmap_line)
        mv_cellmap_ready = _coerce_int(cellmap_payload.get("ready", 0))
        mv_cellmap_accuracy = _coerce_float(cellmap_payload.get("acc", 0.0))
        mv_cellmap_confident_accuracy = _coerce_float(cellmap_payload.get("conf_acc", 0.0))
        mv_cellmap_refine_passes = _coerce_int(cellmap_payload.get("refine_passes", 0))
        confident_match = re.search(r"confident=(\d+)/(\d+)", cellmap_line)
        if confident_match:
            mv_cellmap_confident = int(confident_match.group(1))
            mv_cellmap_total = int(confident_match.group(2))

    mv_enabled_matches = [int(raw) for raw in re.findall(r"\bmv_enabled=(\d+)\b", text)]
    mv_enabled_last = int(mv_enabled_matches[-1]) if mv_enabled_matches else int((mv_player_enabled > 0) or (mv_exit_enabled > 0))
    mv_route_mode_matches = [int(raw) for raw in re.findall(r"\bmv_route_mode=(\d+)\b", text)]
    legacy_mv_route_mode_active = int(any(value > 0 for value in mv_route_mode_matches))

    mvl0_contract_lock = int(legacy_mv_route_mode_active == 0)
    mvl1_estimator_signal_present = int((mv_player_samples > 0) and (mv_exit_samples > 0))

    marker_diagnostics: dict[str, dict[str, int | float]] = {}
    active_marker_keys: list[str] = []
    for marker_key, marker_indices in marker_indices_map.items():
        marker_count = len(marker_indices)
        marker_index_set = set(marker_indices)
        marker_telemetry_indices = [idx for idx in marker_indices if idx in telemetry_indices]
        non_marker_telemetry_indices = [idx for idx in telemetry_indices if idx not in marker_index_set]
        marker_intervention_indices = [
            idx for idx in marker_telemetry_indices if telemetry_interventions[idx] > 0
        ]

        marker_progress_avg = _mean(telemetry_progress_values, marker_telemetry_indices)
        marker_penalty_avg = _mean(telemetry_penalty_values, marker_telemetry_indices)
        marker_progress_win_avg = _window_mean(
            telemetry_progress_values,
            marker_telemetry_indices,
            phase1_window,
        )
        marker_penalty_win_avg = _window_mean(
            telemetry_penalty_values,
            marker_telemetry_indices,
            phase1_window,
        )
        non_marker_progress_win_avg = _window_mean(
            telemetry_progress_values,
            non_marker_telemetry_indices,
            phase1_window,
        )
        non_marker_penalty_win_avg = _window_mean(
            telemetry_penalty_values,
            non_marker_telemetry_indices,
            phase1_window,
        )

        utility_vs_non_marker_win = marker_progress_win_avg - non_marker_progress_win_avg
        penalty_delta_vs_non_marker_win = non_marker_penalty_win_avg - marker_penalty_win_avg

        marker_diagnostics[marker_key] = {
            "rows": marker_count,
            "row_rate": round(_rate(marker_count, planner_steps), 4),
            "telemetry_rows": len(marker_telemetry_indices),
            "telemetry_coverage": round(_rate(len(marker_telemetry_indices), marker_count), 4),
            "intervention_rows": len(marker_intervention_indices),
            "intervention_overlap_rate": round(
                _rate(len(marker_intervention_indices), len(marker_telemetry_indices)),
                4,
            ),
            "progress_avg": round(marker_progress_avg, 4),
            "penalty_avg": round(marker_penalty_avg, 4),
            "progress_win3_avg": round(marker_progress_win_avg, 4),
            "penalty_win3_avg": round(marker_penalty_win_avg, 4),
            "utility_vs_non_marker_win3": round(utility_vs_non_marker_win, 4),
            "penalty_delta_vs_non_marker_win3": round(penalty_delta_vs_non_marker_win, 4),
        }
        if marker_count > 0:
            active_marker_keys.append(marker_key)

    active_marker_keys_sorted = sorted(
        active_marker_keys,
        key=lambda key: (
            float(marker_diagnostics[key]["utility_vs_non_marker_win3"]),
            float(marker_diagnostics[key]["penalty_delta_vs_non_marker_win3"]),
        ),
    )
    top_harmful_markers = active_marker_keys_sorted[:3]
    top_helpful_markers = list(reversed(active_marker_keys_sorted[-3:]))

    pipeline_metrics: dict[str, object] = {}
    for key in [
        "execution_count",
        "step_mode_success",
        "step_mode_iterations",
        "step_mode_completed_hits",
        "step_mode_remaining_hits",
    ]:
        match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, flags=re.MULTILINE)
        if not match:
            continue
        raw = match.group(1).strip()
        if key == "step_mode_success":
            pipeline_metrics[key] = _to_bool(raw)
        else:
            pipeline_metrics[key] = _parse_scalar(raw)

    regression_matches = re.findall(r"memory_regression_check=([^\n]+)", text)
    regression_data = _parse_key_values(regression_matches[-1]) if regression_matches else {}

    sleep_cycle_entries = []
    for match in re.finditer(r"\[SLEEP-CYCLE:\s*([^\]]+)\]", text):
        payload = _parse_key_values(match.group(1))
        sleep_cycle_entries.append(payload)

    post_run_sleep_entries = [
        row for row in sleep_cycle_entries if str(row.get("trigger", "")).strip() == "post-run-set"
    ]

    thresholds = PROFILE_THRESHOLDS.get(profile, PROFILE_THRESHOLDS["batch4"])

    failures: list[str] = []
    warnings: list[str] = []

    success_flag = pipeline_metrics.get("step_mode_success")
    if success_flag is False:
        failures.append("step_mode_success is False")

    execution_count = pipeline_metrics.get("execution_count")
    completed_hits = pipeline_metrics.get("step_mode_completed_hits")
    remaining_hits = pipeline_metrics.get("step_mode_remaining_hits")

    if isinstance(execution_count, int) and isinstance(completed_hits, int) and completed_hits < execution_count:
        failures.append(
            f"completed hits lower than requested ({completed_hits}/{execution_count})"
        )

    if isinstance(remaining_hits, int) and remaining_hits > 0:
        failures.append(f"step_mode_remaining_hits is non-zero ({remaining_hits})")

    shortest_route_integrity = str(regression_data.get("shortest_route_integrity", "")).strip().lower()
    if shortest_route_integrity and shortest_route_integrity != "pass":
        failures.append(
            f"shortest_route_integrity is '{regression_data.get('shortest_route_integrity')}'"
        )

    if not post_run_sleep_entries:
        failures.append("missing post-run-set sleep cycle marker")

    max_guard_override_rate = float(thresholds["max_guard_override_rate"])
    if override_rate > max_guard_override_rate:
        warnings.append(
            f"guard override rate {override_rate:.3f} exceeds profile threshold {max_guard_override_rate:.3f}"
        )

    max_intervention_rate = float(thresholds["max_intervention_rate"])
    if intervention_rate > max_intervention_rate:
        warnings.append(
            f"intervention rate {intervention_rate:.3f} exceeds profile threshold {max_intervention_rate:.3f}"
        )

    max_stuck = int(thresholds["max_stuck_reexplore_override"])
    if marker_counts["stuck_reexplore_override"] > max_stuck:
        warnings.append(
            "stuck re-explore overrides "
            f"{marker_counts['stuck_reexplore_override']} exceed threshold {max_stuck}"
        )

    max_anti = int(thresholds["max_anti_oscillation_override"])
    if marker_counts["anti_oscillation_override"] > max_anti:
        warnings.append(
            "anti-oscillation overrides "
            f"{marker_counts['anti_oscillation_override']} exceed threshold {max_anti}"
        )

    max_targeted = int(thresholds["max_targeted_model_override"])
    if marker_counts["targeted_model_override"] > max_targeted:
        warnings.append(
            "targeted-model overrides "
            f"{marker_counts['targeted_model_override']} exceed threshold {max_targeted}"
        )

    learned_only_rate = _rate(len(learned_only_rows), planner_steps)
    hardcoded_only_rate = _rate(len(hardcoded_only_rows), planner_steps)
    min_learned_only_rate = float(thresholds["min_learned_only_rate"])
    if learned_only_rate < min_learned_only_rate:
        warnings.append(
            f"learned-only decision rate {learned_only_rate:.3f} is below threshold {min_learned_only_rate:.3f}"
        )

    max_hardcoded_only_rate = float(thresholds["max_hardcoded_only_rate"])
    if hardcoded_only_rate > max_hardcoded_only_rate:
        warnings.append(
            f"hardcoded-only decision rate {hardcoded_only_rate:.3f} exceeds threshold {max_hardcoded_only_rate:.3f}"
        )

    max_unresolved_objective_override_rate = float(thresholds["max_unresolved_objective_override_rate"])
    if unresolved_objective_override_rate > max_unresolved_objective_override_rate:
        warnings.append(
            "unresolved objective-override rate "
            f"{unresolved_objective_override_rate:.3f} exceeds threshold {max_unresolved_objective_override_rate:.3f}"
        )

    min_phase1_telemetry_coverage = float(thresholds.get("min_phase1_telemetry_coverage", 0.0))
    if telemetry_coverage < min_phase1_telemetry_coverage:
        warnings.append(
            "phase-1 telemetry coverage "
            f"{telemetry_coverage:.3f} is below threshold {min_phase1_telemetry_coverage:.3f}"
        )

    min_projection_telemetry_coverage = float(thresholds.get("min_projection_telemetry_coverage_when_enabled", 0.0))
    if (
        projection_enabled
        and projection_usage_detected
        and projection_coverage < min_projection_telemetry_coverage
    ):
        warnings.append(
            "projection telemetry coverage "
            f"{projection_coverage:.3f} is below threshold {min_projection_telemetry_coverage:.3f}"
        )

    min_projection_scored_coverage = float(thresholds.get("min_projection_scored_coverage_when_active", 0.0))
    if (
        projection_enabled
        and projection_usage_detected
        and projection_coverage < min_projection_scored_coverage
    ):
        warnings.append(
            "projection scored-coverage "
            f"{projection_coverage:.3f} is below threshold {min_projection_scored_coverage:.3f}"
        )

    min_projection_beneficial_rate = float(thresholds.get("min_projection_beneficial_rate", 0.0))
    if projection_enabled and projection_usage_detected:
        if projection_indices:
            if projection_beneficial_rate < min_projection_beneficial_rate:
                warnings.append(
                    "projection beneficial-rate "
                    f"{projection_beneficial_rate:.3f} is below threshold {min_projection_beneficial_rate:.3f}"
                )
        else:
            warnings.append(
                "projection active but produced zero scored rows; "
                "non-beneficial-rate treated as 1.000"
            )

    max_projection_non_beneficial_rate = float(
        thresholds.get("max_projection_non_beneficial_rate_when_active", 1.0)
    )
    if (
        projection_enabled
        and projection_usage_detected
        and projection_non_beneficial_rate > max_projection_non_beneficial_rate
    ):
        warnings.append(
            "projection non-beneficial-rate "
            f"{projection_non_beneficial_rate:.3f} exceeds threshold {max_projection_non_beneficial_rate:.3f}"
        )

    max_projection_clip_rate = float(thresholds.get("max_projection_clip_rate", 1.0))
    if projection_indices and projection_clip_rate > max_projection_clip_rate:
        warnings.append(
            "projection clip-rate "
            f"{projection_clip_rate:.3f} exceeds threshold {max_projection_clip_rate:.3f}"
        )

    status = "pass"
    if failures:
        status = "fail"
    elif warnings:
        status = "warn"

    report: dict[str, object] = {
        "status": status,
        "profile": profile,
        "failures": failures,
        "warnings": warnings,
        "metrics": {
            "planner_step_rows": planner_steps,
            "planner_max_step_index": max(step_indices) if step_indices else 0,
            "guard_override_rows": override_count,
            "guard_override_rate": round(override_rate, 4),
            "intervention_rows": len(intervention_rows),
            "intervention_rate": round(intervention_rate, 4),
            "objective_routing_rows": len(routing_rows),
            "objective_routing_rate": round(routing_rate, 4),
            "behavior_screen": {
                "learned_rows": len(learned_rows),
                "hardcoded_rows": len(hardcoded_rows),
                "learned_only_rows": len(learned_only_rows),
                "hardcoded_only_rows": len(hardcoded_only_rows),
                "mixed_rows": len(mixed_rows),
                "unknown_rows": len(unknown_rows),
                "learned_only_rate": round(learned_only_rate, 4),
                "hardcoded_only_rate": round(hardcoded_only_rate, 4),
                "mixed_rate": round(_rate(len(mixed_rows), planner_steps), 4),
                "unresolved_objective_override_rows": unresolved_objective_override_rows,
                "unresolved_objective_override_rate": round(unresolved_objective_override_rate, 4),
                "phase1_telemetry_rows": telemetry_rows,
                "phase1_telemetry_coverage": round(telemetry_coverage, 4),
                "phase1_intervention_rows": len(telemetry_intervention_indices),
                "phase1_intervention_progress_avg": round(phase1_intervention_progress_avg, 4),
                "phase1_non_intervention_progress_avg": round(phase1_non_intervention_progress_avg, 4),
                "phase1_intervention_penalty_avg": round(phase1_intervention_penalty_avg, 4),
                "phase1_non_intervention_penalty_avg": round(phase1_non_intervention_penalty_avg, 4),
                "phase1_intervention_progress_win3_avg": round(phase1_intervention_progress_win_avg, 4),
                "phase1_non_intervention_progress_win3_avg": round(phase1_non_intervention_progress_win_avg, 4),
                "phase1_intervention_penalty_win3_avg": round(phase1_intervention_penalty_win_avg, 4),
                "phase1_non_intervention_penalty_win3_avg": round(phase1_non_intervention_penalty_win_avg, 4),
                "phase1_intervention_utility_win3": round(phase1_intervention_utility_win, 4),
                "phase1_penalty_delta_win3": round(phase1_penalty_delta_win, 4),
                "phase1_window": phase1_window,
            },
            "projection_screen": {
                "projection_enabled": int(bool(projection_enabled)),
                "projection_usage_detected": int(bool(projection_usage_detected)),
                "projection_rows": projection_rows,
                "projection_coverage": round(projection_coverage, 4),
                "projection_guidance_tag_rows": projection_guidance_tag_rows,
                "tag_lines": total_tag_lines,
                "projection_guidance_tag_rate": round(projection_guidance_tag_rate, 4),
                "projection_beneficial_rows": len(projection_beneficial_rows),
                "projection_adverse_rows": len(projection_adverse_rows),
                "projection_neutral_rows": len(projection_neutral_rows),
                "projection_beneficial_rate": round(projection_beneficial_rate, 4),
                "projection_adverse_rate": round(projection_adverse_rate, 4),
                "projection_non_beneficial_rate": round(projection_non_beneficial_rate, 4),
                "projection_clipped_rows": len(projection_clipped_rows),
                "projection_clip_rate": round(projection_clip_rate, 4),
                "projection_score_delta_avg": round(projection_delta_avg, 4),
                "projection_score_delta_abs_avg": round(projection_abs_delta_avg, 4),
                "projection_score_delta_scaled_avg": round(projection_delta_scaled_avg, 4),
                "projection_effectiveness_score": round(projection_effectiveness_score, 4),
                "projection_forward_bonus_avg": round(projection_forward_avg, 4),
                "projection_backward_penalty_avg": round(projection_back_penalty_avg, 4),
                "projection_backward_escape_bonus_avg": round(projection_back_escape_avg, 4),
                "projection_influence_scale_avg": round(projection_influence_scale_avg, 4),
            },
            "mv_localization_screen": {
                "player_enabled": int(mv_player_enabled),
                "player_training": int(mv_player_training),
                "player_samples": int(mv_player_samples),
                "player_exact_hits": int(mv_player_exact_hits),
                "player_accuracy": round(float(mv_player_accuracy), 4),
                "player_mae": round(float(mv_player_mae), 4),
                "exit_enabled": int(mv_exit_enabled),
                "exit_training": int(mv_exit_training),
                "exit_samples": int(mv_exit_samples),
                "exit_exact_hits": int(mv_exit_exact_hits),
                "exit_accuracy": round(float(mv_exit_accuracy), 4),
                "exit_mae": round(float(mv_exit_mae), 4),
                "cellmap_ready": int(mv_cellmap_ready),
                "cellmap_confident": int(mv_cellmap_confident),
                "cellmap_total": int(mv_cellmap_total),
                "cellmap_accuracy": round(float(mv_cellmap_accuracy), 4),
                "cellmap_confident_accuracy": round(float(mv_cellmap_confident_accuracy), 4),
                "cellmap_refine_passes": int(mv_cellmap_refine_passes),
                "mv_enabled_last": int(mv_enabled_last),
                "legacy_mv_route_mode_active": int(legacy_mv_route_mode_active),
                "mvl0_contract_lock": int(mvl0_contract_lock),
                "mvl1_estimator_signal_present": int(mvl1_estimator_signal_present),
            },
            "intervention_diagnostics": {
                "markers": marker_diagnostics,
                "top_harmful_markers": top_harmful_markers,
                "top_helpful_markers": top_helpful_markers,
            },
            "override_markers": marker_counts,
            "pipeline": pipeline_metrics,
            "memory_regression_check": regression_data,
            "sleep_cycle_entries": sleep_cycle_entries,
            "post_run_set_sleep_cycle_count": len(post_run_sleep_entries),
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight gate parser for maze memory dump files")
    parser.add_argument("dump_file", help="Path to a dump file in Log Dump/")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_THRESHOLDS.keys()),
        default="batch4",
        help="Threshold profile used for warning gates.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures for CI-style gating.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit only JSON report output.",
    )
    args = parser.parse_args()

    dump_path = Path(args.dump_file)
    if not dump_path.exists() or not dump_path.is_file():
        print(f"error: dump file not found: {dump_path}", file=sys.stderr)
        return 2

    text = dump_path.read_text(encoding="utf-8", errors="replace")
    report = parse_dump(text, profile=args.profile)

    status = str(report.get("status", "fail"))
    failures = list(report.get("failures", []))
    warnings = list(report.get("warnings", []))

    if args.strict and (status == "warn"):
        status = "fail"
        failures = ["strict mode enabled and warnings were present", *warnings]
        report["status"] = "fail"
        report["failures"] = failures

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"preflight_status={report['status']} profile={report['profile']}")
        print(f"dump_file={dump_path}")
        metrics = report.get("metrics", {})
        if isinstance(metrics, dict):
            print(
                "planner_steps="
                f"{metrics.get('planner_step_rows', 0)} "
                "guard_override_rows="
                f"{metrics.get('guard_override_rows', 0)} "
                "guard_override_rate="
                f"{metrics.get('guard_override_rate', 0.0)}"
            )
            behavior_screen = metrics.get("behavior_screen", {})
            if isinstance(behavior_screen, dict) and behavior_screen:
                print(
                    "behavior_screen="
                    f"learned_only_rate={behavior_screen.get('learned_only_rate', 0.0)} "
                    f"hardcoded_only_rate={behavior_screen.get('hardcoded_only_rate', 0.0)} "
                    f"mixed_rate={behavior_screen.get('mixed_rate', 0.0)} "
                    "unresolved_objective_override_rate="
                    f"{behavior_screen.get('unresolved_objective_override_rate', 0.0)} "
                    f"phase1_telemetry_coverage={behavior_screen.get('phase1_telemetry_coverage', 0.0)} "
                    f"phase1_intervention_utility_win3={behavior_screen.get('phase1_intervention_utility_win3', 0.0)} "
                    f"phase1_penalty_delta_win3={behavior_screen.get('phase1_penalty_delta_win3', 0.0)}"
                )
            projection_screen = metrics.get("projection_screen", {})
            if isinstance(projection_screen, dict) and projection_screen:
                print(
                    "projection_screen="
                    f"enabled={projection_screen.get('projection_enabled', 0)} "
                    f"usage_detected={projection_screen.get('projection_usage_detected', 0)} "
                    f"coverage={projection_screen.get('projection_coverage', 0.0)} "
                    f"tag_rate={projection_screen.get('projection_guidance_tag_rate', 0.0)} "
                    f"beneficial_rate={projection_screen.get('projection_beneficial_rate', 0.0)} "
                    f"non_beneficial_rate={projection_screen.get('projection_non_beneficial_rate', 0.0)} "
                    f"clip_rate={projection_screen.get('projection_clip_rate', 0.0)} "
                    f"delta_avg={projection_screen.get('projection_score_delta_avg', 0.0)} "
                    f"delta_scaled_avg={projection_screen.get('projection_score_delta_scaled_avg', 0.0)} "
                    f"effectiveness_score={projection_screen.get('projection_effectiveness_score', 0.0)}"
                )
            mv_localization_screen = metrics.get("mv_localization_screen", {})
            if isinstance(mv_localization_screen, dict) and mv_localization_screen:
                print(
                    "mv_localization_screen="
                    f"player_acc={mv_localization_screen.get('player_accuracy', 0.0)} "
                    f"exit_acc={mv_localization_screen.get('exit_accuracy', 0.0)} "
                    f"cellmap_ready={mv_localization_screen.get('cellmap_ready', 0)} "
                    f"contract_lock={mv_localization_screen.get('mvl0_contract_lock', 0)} "
                    f"estimator_signal={mv_localization_screen.get('mvl1_estimator_signal_present', 0)} "
                    f"legacy_route_mode={mv_localization_screen.get('legacy_mv_route_mode_active', 0)}"
                )
            intervention_diag = metrics.get("intervention_diagnostics", {})
            if isinstance(intervention_diag, dict):
                markers = intervention_diag.get("markers", {})
                harmful = intervention_diag.get("top_harmful_markers", [])
                helpful = intervention_diag.get("top_helpful_markers", [])
                if isinstance(markers, dict) and markers and isinstance(harmful, list) and isinstance(helpful, list):
                    harmful_parts: list[str] = []
                    for key in harmful[:2]:
                        payload = markers.get(key)
                        if not isinstance(payload, dict):
                            continue
                        harmful_parts.append(
                            f"{key}:rows={payload.get('rows', 0)} util={payload.get('utility_vs_non_marker_win3', 0.0)} pen_delta={payload.get('penalty_delta_vs_non_marker_win3', 0.0)}"
                        )
                    helpful_parts: list[str] = []
                    for key in helpful[:2]:
                        payload = markers.get(key)
                        if not isinstance(payload, dict):
                            continue
                        helpful_parts.append(
                            f"{key}:rows={payload.get('rows', 0)} util={payload.get('utility_vs_non_marker_win3', 0.0)} pen_delta={payload.get('penalty_delta_vs_non_marker_win3', 0.0)}"
                        )
                    if harmful_parts or helpful_parts:
                        print(
                            "intervention_diagnostics="
                            f"harmful=[{' | '.join(harmful_parts)}] "
                            f"helpful=[{' | '.join(helpful_parts)}]"
                        )
            pipeline = metrics.get("pipeline", {})
            if isinstance(pipeline, dict):
                print(
                    "pipeline="
                    f"execution_count={pipeline.get('execution_count', 'n/a')} "
                    f"completed={pipeline.get('step_mode_completed_hits', 'n/a')} "
                    f"remaining={pipeline.get('step_mode_remaining_hits', 'n/a')} "
                    f"success={pipeline.get('step_mode_success', 'n/a')}"
                )
            regression = metrics.get("memory_regression_check", {})
            if isinstance(regression, dict) and regression:
                print(
                    "memory_regression_check="
                    f"shortest_route_integrity={regression.get('shortest_route_integrity', 'n/a')} "
                    f"objective_steps={regression.get('objective_steps', 'n/a')}"
                )
            print(f"post_run_set_sleep_cycles={metrics.get('post_run_set_sleep_cycle_count', 0)}")

        if failures:
            print("failures:")
            for item in failures:
                print(f"- {item}")
        if warnings:
            print("warnings:")
            for item in warnings:
                print(f"- {item}")

    return 2 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
