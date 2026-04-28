#!/usr/bin/env python3
"""Canonical ID vs OOD comparison using preflight JSON as status source-of-truth."""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RX_AUTO = re.compile(r"telemetry_autonomy_score=([0-9.+-]+)")
RX_TRUST = re.compile(r"telemetry_reasoning_trust_deliberative=([0-9.+-]+)")
RX_GUARD = re.compile(r"telemetry_guard_utility_ema=([0-9.+-]+)")

RX_PROMO_JSON = re.compile(r'"promotion_target"\s*:\s*([0-9.+-]+)')
RX_PROMO_KV = re.compile(r"(?:^|\s)promotion_target[:= ]+([0-9.+-]+)")
RX_BASE_PROMO_JSON = re.compile(r'"base_promotion_target"\s*:\s*([0-9.+-]+)')
RX_BASE_PROMO_KV = re.compile(r"(?:^|\s)base_promotion_target[:= ]+([0-9.+-]+)")

RX_PHASE_JSON = re.compile(r'"completed_phase_count"\s*:\s*([0-9]+)')
RX_PHASE_KV = re.compile(r"completed_phase_count[:= ]+([0-9]+)")
RX_MICRO_JSON = re.compile(r'"completed_micro_total"\s*:\s*([0-9]+)')
RX_MICRO_KV = re.compile(r"completed_micro_total[:= ]+([0-9]+)")


@dataclass
class FileSummary:
    file: str
    status: str
    warnings: int
    failures: int
    learned_only_rate: float
    hardcoded_only_rate: float
    mixed_rate: float
    phase1_intervention_utility_win3: float
    projection_effectiveness_score: float
    mvl0_contract_lock: float
    mvl1_estimator_signal_present: float
    mvl_player_accuracy: float
    mvl_exit_accuracy: float
    mvl_cellmap_ready: float
    legacy_mv_route_mode_active: float
    autonomy_mean: float
    trust_delib_mean: float
    trust_delib_floor: float
    guard_utility_mean: float
    phase_count: int
    micro_count: int
    promotion_target_max: float | None
    base_promotion_target_last: float | None
    drift: bool


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _newest_files(pattern: str, count: int) -> list[Path]:
    files = sorted(glob.glob(pattern), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    return [Path(p) for p in files[:count]]


def _extract_last_float(line: str, *patterns: re.Pattern[str]) -> float | None:
    for pat in patterns:
        m = pat.search(line)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _extract_last_int(line: str, *patterns: re.Pattern[str]) -> int | None:
    for pat in patterns:
        m = pat.search(line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _parse_streamed_metrics(path: Path) -> dict[str, Any]:
    auto: list[float] = []
    trust: list[float] = []
    guard: list[float] = []

    max_promo: float | None = None
    base_promo: float | None = None
    phase_count = 0
    micro_count = 0

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            v_auto = _extract_last_float(line, RX_AUTO)
            if v_auto is not None:
                auto.append(v_auto)

            v_trust = _extract_last_float(line, RX_TRUST)
            if v_trust is not None:
                trust.append(v_trust)

            v_guard = _extract_last_float(line, RX_GUARD)
            if v_guard is not None:
                guard.append(v_guard)

            v_promo = _extract_last_float(line, RX_PROMO_JSON, RX_PROMO_KV)
            if v_promo is not None:
                max_promo = v_promo if max_promo is None else max(max_promo, v_promo)

            v_base = _extract_last_float(line, RX_BASE_PROMO_JSON, RX_BASE_PROMO_KV)
            if v_base is not None:
                base_promo = v_base

            v_phase = _extract_last_int(line, RX_PHASE_JSON, RX_PHASE_KV)
            if v_phase is not None:
                phase_count = v_phase

            v_micro = _extract_last_int(line, RX_MICRO_JSON, RX_MICRO_KV)
            if v_micro is not None:
                micro_count = v_micro

    drift = False
    if max_promo is not None and base_promo is not None:
        drift = max_promo > base_promo + 1e-9

    trust_floor = min(trust) if trust else 0.0

    return {
        "autonomy_mean": _mean(auto),
        "trust_delib_mean": _mean(trust),
        "trust_delib_floor": float(trust_floor),
        "guard_utility_mean": _mean(guard),
        "phase_count": phase_count,
        "micro_count": micro_count,
        "promotion_target_max": max_promo,
        "base_promotion_target_last": base_promo,
        "drift": drift,
    }


def _normalize_status(raw: str) -> str:
    upper = (raw or "").strip().upper()
    if upper in {"PASS", "WARN", "FAIL", "ERROR", "TIMEOUT"}:
        return upper
    if upper in {"WARNING", "WARNINGS"}:
        return "WARN"
    return "ERROR"


def _run_preflight(
    file_path: Path,
    python_exe: str,
    preflight_script: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    cmd = [python_exe, preflight_script, str(file_path), "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "warnings": -1,
            "failures": -1,
            "learned_only_rate": 0.0,
            "hardcoded_only_rate": 0.0,
            "mixed_rate": 0.0,
            "phase1_intervention_utility_win3": 0.0,
            "projection_effectiveness_score": 0.0,
            "mvl0_contract_lock": 0.0,
            "mvl1_estimator_signal_present": 0.0,
            "mvl_player_accuracy": 0.0,
            "mvl_exit_accuracy": 0.0,
            "mvl_cellmap_ready": 0.0,
            "legacy_mv_route_mode_active": 0.0,
        }

    if proc.returncode != 0:
        return {
            "status": "ERROR",
            "warnings": -1,
            "failures": -1,
            "learned_only_rate": 0.0,
            "hardcoded_only_rate": 0.0,
            "mixed_rate": 0.0,
            "phase1_intervention_utility_win3": 0.0,
            "projection_effectiveness_score": 0.0,
            "mvl0_contract_lock": 0.0,
            "mvl1_estimator_signal_present": 0.0,
            "mvl_player_accuracy": 0.0,
            "mvl_exit_accuracy": 0.0,
            "mvl_cellmap_ready": 0.0,
            "legacy_mv_route_mode_active": 0.0,
        }

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "status": "ERROR",
            "warnings": -1,
            "failures": -1,
            "learned_only_rate": 0.0,
            "hardcoded_only_rate": 0.0,
            "mixed_rate": 0.0,
            "phase1_intervention_utility_win3": 0.0,
            "projection_effectiveness_score": 0.0,
            "mvl0_contract_lock": 0.0,
            "mvl1_estimator_signal_present": 0.0,
            "mvl_player_accuracy": 0.0,
            "mvl_exit_accuracy": 0.0,
            "mvl_cellmap_ready": 0.0,
            "legacy_mv_route_mode_active": 0.0,
        }

    metrics = payload.get("metrics", {})
    behavior = metrics.get("behavior_screen", {}) if isinstance(metrics, dict) else {}
    projection = metrics.get("projection_screen", {}) if isinstance(metrics, dict) else {}
    mv_localization = metrics.get("mv_localization_screen", {}) if isinstance(metrics, dict) else {}

    return {
        "status": _normalize_status(str(payload.get("status", "ERROR"))),
        "warnings": len(payload.get("warnings", [])),
        "failures": len(payload.get("failures", [])),
        "learned_only_rate": float(behavior.get("learned_only_rate", 0.0) or 0.0),
        "hardcoded_only_rate": float(behavior.get("hardcoded_only_rate", 0.0) or 0.0),
        "mixed_rate": float(behavior.get("mixed_rate", 0.0) or 0.0),
        "phase1_intervention_utility_win3": float(
            behavior.get("phase1_intervention_utility_win3", 0.0) or 0.0
        ),
        "projection_effectiveness_score": float(
            projection.get("projection_effectiveness_score", 0.0) or 0.0
        ),
        "mvl0_contract_lock": float(
            mv_localization.get("mvl0_contract_lock", 0.0) or 0.0
        ),
        "mvl1_estimator_signal_present": float(
            mv_localization.get("mvl1_estimator_signal_present", 0.0) or 0.0
        ),
        "mvl_player_accuracy": float(
            mv_localization.get("player_accuracy", 0.0) or 0.0
        ),
        "mvl_exit_accuracy": float(
            mv_localization.get("exit_accuracy", 0.0) or 0.0
        ),
        "mvl_cellmap_ready": float(
            mv_localization.get("cellmap_ready", 0.0) or 0.0
        ),
        "legacy_mv_route_mode_active": float(
            mv_localization.get("legacy_mv_route_mode_active", 0.0) or 0.0
        ),
    }


def _summarize_group(rows: list[FileSummary]) -> dict[str, Any]:
    if not rows:
        return {
            "autonomy_mean": 0.0,
            "trust_delib_mean": 0.0,
            "trust_delib_floor": 0.0,
            "guard_utility_mean": 0.0,
            "learned_only_rate_mean": 0.0,
            "hardcoded_only_rate_mean": 0.0,
            "mixed_rate_mean": 0.0,
            "phase1_intervention_utility_win3_mean": 0.0,
            "projection_effectiveness_score_mean": 0.0,
            "mvl0_contract_lock_mean": 0.0,
            "mvl1_estimator_signal_present_mean": 0.0,
            "mvl_player_accuracy_mean": 0.0,
            "mvl_exit_accuracy_mean": 0.0,
            "mvl_cellmap_ready_mean": 0.0,
            "legacy_mv_route_mode_active_mean": 0.0,
            "status_counts": {},
            "drift_count": 0,
            "total_warnings": 0,
            "total_failures": 0,
            "mean_phase_count": 0.0,
            "mean_micro_count": 0.0,
        }

    return {
        "autonomy_mean": _mean([r.autonomy_mean for r in rows]),
        "trust_delib_mean": _mean([r.trust_delib_mean for r in rows]),
        "trust_delib_floor": min(float(r.trust_delib_floor) for r in rows),
        "guard_utility_mean": _mean([r.guard_utility_mean for r in rows]),
        "learned_only_rate_mean": _mean([r.learned_only_rate for r in rows]),
        "hardcoded_only_rate_mean": _mean([r.hardcoded_only_rate for r in rows]),
        "mixed_rate_mean": _mean([r.mixed_rate for r in rows]),
        "phase1_intervention_utility_win3_mean": _mean([r.phase1_intervention_utility_win3 for r in rows]),
        "projection_effectiveness_score_mean": _mean([r.projection_effectiveness_score for r in rows]),
        "mvl0_contract_lock_mean": _mean([r.mvl0_contract_lock for r in rows]),
        "mvl1_estimator_signal_present_mean": _mean([r.mvl1_estimator_signal_present for r in rows]),
        "mvl_player_accuracy_mean": _mean([r.mvl_player_accuracy for r in rows]),
        "mvl_exit_accuracy_mean": _mean([r.mvl_exit_accuracy for r in rows]),
        "mvl_cellmap_ready_mean": _mean([r.mvl_cellmap_ready for r in rows]),
        "legacy_mv_route_mode_active_mean": _mean([r.legacy_mv_route_mode_active for r in rows]),
        "status_counts": dict(Counter(r.status for r in rows)),
        "drift_count": sum(1 for r in rows if r.drift),
        "total_warnings": sum(max(0, r.warnings) for r in rows),
        "total_failures": sum(max(0, r.failures) for r in rows),
        "mean_phase_count": _mean([float(r.phase_count) for r in rows]),
        "mean_micro_count": _mean([float(r.micro_count) for r in rows]),
    }


def compare_runs(
    id_pattern: str,
    ood_pattern: str,
    count: int,
    python_exe: str,
    preflight_script: str,
    timeout_seconds: int,
    trust_drop_warn: float,
    trust_mean_min: float,
    trust_floor_min: float,
    trust_id_ood_delta_max: float,
    auto_drop_warn: float,
    guard_drop_warn: float,
) -> dict[str, Any]:
    id_files = _newest_files(id_pattern, count)
    ood_files = _newest_files(ood_pattern, count)

    def collect(files: list[Path]) -> list[FileSummary]:
        rows: list[FileSummary] = []
        for path in files:
            streamed = _parse_streamed_metrics(path)
            preflight = _run_preflight(path, python_exe, preflight_script, timeout_seconds)
            rows.append(
                FileSummary(
                    file=path.name,
                    status=str(preflight["status"]),
                    warnings=int(preflight["warnings"]),
                    failures=int(preflight["failures"]),
                    learned_only_rate=float(preflight["learned_only_rate"]),
                    hardcoded_only_rate=float(preflight["hardcoded_only_rate"]),
                    mixed_rate=float(preflight["mixed_rate"]),
                    phase1_intervention_utility_win3=float(preflight["phase1_intervention_utility_win3"]),
                    projection_effectiveness_score=float(preflight["projection_effectiveness_score"]),
                    mvl0_contract_lock=float(preflight["mvl0_contract_lock"]),
                    mvl1_estimator_signal_present=float(preflight["mvl1_estimator_signal_present"]),
                    mvl_player_accuracy=float(preflight["mvl_player_accuracy"]),
                    mvl_exit_accuracy=float(preflight["mvl_exit_accuracy"]),
                    mvl_cellmap_ready=float(preflight["mvl_cellmap_ready"]),
                    legacy_mv_route_mode_active=float(preflight["legacy_mv_route_mode_active"]),
                    autonomy_mean=float(streamed["autonomy_mean"]),
                    trust_delib_mean=float(streamed["trust_delib_mean"]),
                    trust_delib_floor=float(streamed["trust_delib_floor"]),
                    guard_utility_mean=float(streamed["guard_utility_mean"]),
                    phase_count=int(streamed["phase_count"]),
                    micro_count=int(streamed["micro_count"]),
                    promotion_target_max=streamed["promotion_target_max"],
                    base_promotion_target_last=streamed["base_promotion_target_last"],
                    drift=bool(streamed["drift"]),
                )
            )
        return rows

    id_rows = collect(id_files)
    ood_rows = collect(ood_files)

    id_group = _summarize_group(id_rows)
    ood_group = _summarize_group(ood_rows)

    deltas = {
        "autonomy_mean": id_group["autonomy_mean"] - ood_group["autonomy_mean"],
        "trust_delib_mean": id_group["trust_delib_mean"] - ood_group["trust_delib_mean"],
        "trust_id_ood_delta": id_group["trust_delib_mean"] - ood_group["trust_delib_mean"],
        "guard_utility_mean": id_group["guard_utility_mean"] - ood_group["guard_utility_mean"],
        "learned_only_rate_mean": id_group["learned_only_rate_mean"] - ood_group["learned_only_rate_mean"],
        "hardcoded_only_rate_mean": id_group["hardcoded_only_rate_mean"] - ood_group["hardcoded_only_rate_mean"],
        "mixed_rate_mean": id_group["mixed_rate_mean"] - ood_group["mixed_rate_mean"],
        "phase1_intervention_utility_win3_mean": id_group["phase1_intervention_utility_win3_mean"]
        - ood_group["phase1_intervention_utility_win3_mean"],
        "projection_effectiveness_score_mean": id_group["projection_effectiveness_score_mean"]
        - ood_group["projection_effectiveness_score_mean"],
        "mvl0_contract_lock_mean": id_group["mvl0_contract_lock_mean"]
        - ood_group["mvl0_contract_lock_mean"],
        "mvl1_estimator_signal_present_mean": id_group["mvl1_estimator_signal_present_mean"]
        - ood_group["mvl1_estimator_signal_present_mean"],
        "mvl_player_accuracy_mean": id_group["mvl_player_accuracy_mean"]
        - ood_group["mvl_player_accuracy_mean"],
        "mvl_exit_accuracy_mean": id_group["mvl_exit_accuracy_mean"]
        - ood_group["mvl_exit_accuracy_mean"],
        "mvl_cellmap_ready_mean": id_group["mvl_cellmap_ready_mean"]
        - ood_group["mvl_cellmap_ready_mean"],
        "legacy_mv_route_mode_active_mean": id_group["legacy_mv_route_mode_active_mean"]
        - ood_group["legacy_mv_route_mode_active_mean"],
    }

    regressions = {
        "status_not_all_pass": any(r.status != "PASS" for r in id_rows + ood_rows),
        "drift_detected": (id_group["drift_count"] + ood_group["drift_count"]) > 0,
        "trust_drop_exceeds_threshold": deltas["trust_delib_mean"] > trust_drop_warn,
        "trust_mean_below_target": min(id_group["trust_delib_mean"], ood_group["trust_delib_mean"]) < trust_mean_min,
        "trust_floor_below_target": min(id_group["trust_delib_floor"], ood_group["trust_delib_floor"]) < trust_floor_min,
        "trust_id_ood_delta_exceeds_target": deltas["trust_id_ood_delta"] > trust_id_ood_delta_max,
        "autonomy_drop_exceeds_threshold": deltas["autonomy_mean"] > auto_drop_warn,
        "guard_drop_exceeds_threshold": deltas["guard_utility_mean"] > guard_drop_warn,
        "mvl0_contract_lock_missing": min(id_group["mvl0_contract_lock_mean"], ood_group["mvl0_contract_lock_mean"]) < 1.0,
        "mvl1_estimator_signal_missing": min(id_group["mvl1_estimator_signal_present_mean"], ood_group["mvl1_estimator_signal_present_mean"]) < 1.0,
        "legacy_mv_route_mode_active": max(id_group["legacy_mv_route_mode_active_mean"], ood_group["legacy_mv_route_mode_active_mean"]) > 0.0,
    }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "status_source": "preflight_dump_gate.py --json",
            "id_pattern": id_pattern,
            "ood_pattern": ood_pattern,
            "count": count,
            "timeout_seconds": timeout_seconds,
        },
        "thresholds": {
            "trust_drop_warn": trust_drop_warn,
            "trust_mean_min": trust_mean_min,
            "trust_floor_min": trust_floor_min,
            "trust_id_ood_delta_max": trust_id_ood_delta_max,
            "autonomy_drop_warn": auto_drop_warn,
            "guard_drop_warn": guard_drop_warn,
        },
        "id_files": [p.name for p in id_files],
        "ood_files": [p.name for p in ood_files],
        "id_rows": [asdict(r) for r in id_rows],
        "ood_rows": [asdict(r) for r in ood_rows],
        "id_group": id_group,
        "ood_group": ood_group,
        "deltas_id_minus_ood": deltas,
        "regressions": regressions,
    }


def _print_console(result: dict[str, Any]) -> None:
    print("ID FILES:")
    for name in result["id_files"]:
        print("-", name)
    print("OOD FILES:")
    for name in result["ood_files"]:
        print("-", name)

    print("\nID PER-FILE:")
    print("file | status | warn | fail | auto | trust | guard | drift | phase/micro | mvl(p/e/cell/r)")
    for row in result["id_rows"]:
        print(
            f"{row['file']} | {row['status']} | {row['warnings']} | {row['failures']} | "
            f"{row['autonomy_mean']:.4f} | {row['trust_delib_mean']:.4f} | {row['guard_utility_mean']:.4f} | "
            f"{'Y' if row['drift'] else 'N'} | {row['phase_count']}/{row['micro_count']} | "
            f"{row['mvl_player_accuracy']:.3f}/{row['mvl_exit_accuracy']:.3f}/{int(round(row['mvl_cellmap_ready']))}/{int(round(row['legacy_mv_route_mode_active']))}"
        )

    print("\nGROUP MEANS:")
    ig = result["id_group"]
    og = result["ood_group"]
    print(
        f"ID auto={ig['autonomy_mean']:.4f} trust={ig['trust_delib_mean']:.4f} "
        f"trust_floor={ig['trust_delib_floor']:.4f} guard={ig['guard_utility_mean']:.4f}"
    )
    print(
        f"OOD auto={og['autonomy_mean']:.4f} trust={og['trust_delib_mean']:.4f} "
        f"trust_floor={og['trust_delib_floor']:.4f} guard={og['guard_utility_mean']:.4f}"
    )
    print(
        f"ID mvl_player_acc={ig['mvl_player_accuracy_mean']:.4f} "
        f"mvl_exit_acc={ig['mvl_exit_accuracy_mean']:.4f} "
        f"mvl_cellmap_ready={ig['mvl_cellmap_ready_mean']:.4f} "
        f"legacy_route_mode={ig['legacy_mv_route_mode_active_mean']:.4f}"
    )
    print(
        f"OOD mvl_player_acc={og['mvl_player_accuracy_mean']:.4f} "
        f"mvl_exit_acc={og['mvl_exit_accuracy_mean']:.4f} "
        f"mvl_cellmap_ready={og['mvl_cellmap_ready_mean']:.4f} "
        f"legacy_route_mode={og['legacy_mv_route_mode_active_mean']:.4f}"
    )

    print("\nDELTA ID-OOD:")
    for key in (
        "autonomy_mean",
        "trust_delib_mean",
        "trust_id_ood_delta",
        "guard_utility_mean",
        "mvl_player_accuracy_mean",
        "mvl_exit_accuracy_mean",
        "mvl_cellmap_ready_mean",
        "legacy_mv_route_mode_active_mean",
    ):
        print(f"{key}={result['deltas_id_minus_ood'][key]:.4f}")

    print("\nSTATUS COUNTS:")
    print("ID", result["id_group"]["status_counts"])
    print("OOD", result["ood_group"]["status_counts"])
    print("DRIFT COUNT", result["id_group"]["drift_count"] + result["ood_group"]["drift_count"])

    print("\nREGRESSION FLAGS:")
    for k, v in result["regressions"].items():
        print(f"- {k}: {v}")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    ig = result["id_group"]
    og = result["ood_group"]
    d = result["deltas_id_minus_ood"]

    lines = [
        "# Canonical ID vs OOD Comparison",
        "",
        f"Generated: {result['generated_at_utc']}",
        "",
        "## Contract",
        f"- Status source: {result['contract']['status_source']}",
        f"- ID pattern: {result['contract']['id_pattern']}",
        f"- OOD pattern: {result['contract']['ood_pattern']}",
        f"- Files per group: {result['contract']['count']}",
        "",
        "## Group Means",
        f"- ID: auto={ig['autonomy_mean']:.4f}, trust={ig['trust_delib_mean']:.4f}, trust_floor={ig['trust_delib_floor']:.4f}, guard={ig['guard_utility_mean']:.4f}",
        f"- OOD: auto={og['autonomy_mean']:.4f}, trust={og['trust_delib_mean']:.4f}, trust_floor={og['trust_delib_floor']:.4f}, guard={og['guard_utility_mean']:.4f}",
        f"- ID MVL: player_acc={ig['mvl_player_accuracy_mean']:.4f}, exit_acc={ig['mvl_exit_accuracy_mean']:.4f}, cellmap_ready={ig['mvl_cellmap_ready_mean']:.4f}, contract_lock={ig['mvl0_contract_lock_mean']:.4f}, estimator_signal={ig['mvl1_estimator_signal_present_mean']:.4f}, legacy_route_mode={ig['legacy_mv_route_mode_active_mean']:.4f}",
        f"- OOD MVL: player_acc={og['mvl_player_accuracy_mean']:.4f}, exit_acc={og['mvl_exit_accuracy_mean']:.4f}, cellmap_ready={og['mvl_cellmap_ready_mean']:.4f}, contract_lock={og['mvl0_contract_lock_mean']:.4f}, estimator_signal={og['mvl1_estimator_signal_present_mean']:.4f}, legacy_route_mode={og['legacy_mv_route_mode_active_mean']:.4f}",
        "",
        "## Delta (ID - OOD)",
        f"- autonomy_mean: {d['autonomy_mean']:.4f}",
        f"- trust_delib_mean: {d['trust_delib_mean']:.4f}",
        f"- trust_id_ood_delta: {d['trust_id_ood_delta']:.4f}",
        f"- guard_utility_mean: {d['guard_utility_mean']:.4f}",
        f"- mvl_player_accuracy_mean: {d['mvl_player_accuracy_mean']:.4f}",
        f"- mvl_exit_accuracy_mean: {d['mvl_exit_accuracy_mean']:.4f}",
        f"- mvl_cellmap_ready_mean: {d['mvl_cellmap_ready_mean']:.4f}",
        f"- mvl0_contract_lock_mean: {d['mvl0_contract_lock_mean']:.4f}",
        f"- mvl1_estimator_signal_present_mean: {d['mvl1_estimator_signal_present_mean']:.4f}",
        f"- legacy_mv_route_mode_active_mean: {d['legacy_mv_route_mode_active_mean']:.4f}",
        "",
        "## Status and Drift",
        f"- ID status counts: {ig['status_counts']}",
        f"- OOD status counts: {og['status_counts']}",
        f"- Total drift count: {ig['drift_count'] + og['drift_count']}",
        "",
        "## Regression Flags",
    ]
    for k, v in result["regressions"].items():
        lines.append(f"- {k}: {v}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-pattern", default="Log Dump/15_mazes_hard_*.txt")
    parser.add_argument("--ood-pattern", default="Log Dump/15_mazes_very_hard_*.txt")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--preflight-script", default="preflight_dump_gate.py")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--trust-drop-warn", type=float, default=0.10)
    parser.add_argument("--trust-mean-min", type=float, default=0.82)
    parser.add_argument("--trust-floor-min", type=float, default=0.72)
    parser.add_argument("--trust-id-ood-delta-max", type=float, default=0.10)
    parser.add_argument("--autonomy-drop-warn", type=float, default=0.05)
    parser.add_argument("--guard-drop-warn", type=float, default=0.03)
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = compare_runs(
        id_pattern=args.id_pattern,
        ood_pattern=args.ood_pattern,
        count=args.count,
        python_exe=args.python_exe,
        preflight_script=args.preflight_script,
        timeout_seconds=args.timeout_seconds,
        trust_drop_warn=args.trust_drop_warn,
        trust_mean_min=args.trust_mean_min,
        trust_floor_min=args.trust_floor_min,
        trust_id_ood_delta_max=args.trust_id_ood_delta_max,
        auto_drop_warn=args.autonomy_drop_warn,
        guard_drop_warn=args.guard_drop_warn,
    )

    _print_console(result)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        _write_markdown(Path(args.markdown_out), result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
