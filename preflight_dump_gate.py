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
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


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

    telemetry_channel_re = re.compile(r"telemetry_channel=([a-z_]+)")
    telemetry_intervention_re = re.compile(r"telemetry_intervention=(\d+)")
    telemetry_progress_re = re.compile(r"telemetry_progress_delta=(-?\d+)")
    telemetry_penalty_re = re.compile(r"telemetry_penalty_signal=(-?\d+(?:\.\d+)?)")
    telemetry_reward_re = re.compile(r"telemetry_reward_signal=(-?\d+(?:\.\d+)?)")
    telemetry_score_re = re.compile(r"telemetry_decision_score=(-?\d+(?:\.\d+)?)")

    telemetry_present_flags: list[bool] = []
    telemetry_channels: list[str] = []
    telemetry_interventions: list[int] = []
    telemetry_progress_values: list[float] = []
    telemetry_penalty_values: list[float] = []
    telemetry_reward_values: list[float] = []
    telemetry_score_values: list[float] = []
    telemetry_rows = 0
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
