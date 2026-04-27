#!/usr/bin/env python3
"""Generate the first full-system tuning report artifact from canonical tooling."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from tuning.canonical_compare import compare_runs
from tuning.progression_consistency import check_progression_consistency


def _to_md_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| File | Status | Warn | Fail | Auto | Trust | Guard | Drift | Phase/Micro |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + f"{row['file']} | {row['status']} | {row['warnings']} | {row['failures']} | "
            + f"{row['autonomy_mean']:.4f} | {row['trust_delib_mean']:.4f} | {row['guard_utility_mean']:.4f} | "
            + f"{'Y' if row['drift'] else 'N'} | {row['phase_count']}/{row['micro_count']} |"
        )
    return lines


def _regression_flag_lines(flags: dict[str, bool]) -> list[str]:
    lines = []
    for key, value in flags.items():
        state = "TRIGGERED" if value else "clear"
        lines.append(f"- {key}: {state}")
    return lines


def _recommendations(compare_result: dict[str, Any], progression_result: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    flags = compare_result["regressions"]

    if flags["status_not_all_pass"]:
        recs.append("Normalize failing/timed-out files first before further tuning passes.")
    if flags["drift_detected"]:
        recs.append("Apply promotion-target envelope hardening and re-run drift verification.")
    if flags["trust_drop_exceeds_threshold"]:
        recs.append(
            "Prioritize OOD trust calibration and arbitration retuning before expanding OOD severity."
        )
    if flags.get("trust_mean_below_target", False):
        recs.append("Raise trust mean through calibration-focused updates before advancing trust phases.")
    if flags.get("trust_floor_below_target", False):
        recs.append("Address low-trust floor slices before enabling stricter trust enforcement.")
    if flags.get("trust_id_ood_delta_exceeds_target", False):
        recs.append("Reduce ID-OOD trust gap before promoting OOD curriculum severity.")
    if progression_result["summary"]["files_with_issues"] > 0:
        recs.append("Repair phase/micro logging consistency before adding stricter CI gates.")

    if not recs:
        recs.append("Continue app-surface cleanup with kernel tuning frozen, then re-run this report.")

    return recs


def generate_report(args: argparse.Namespace) -> dict[str, Any]:
    compare_result = compare_runs(
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
    progression_result = check_progression_consistency(
        pattern=args.progress_pattern,
        count=args.progress_count,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    id_group = compare_result["id_group"]
    ood_group = compare_result["ood_group"]
    deltas = compare_result["deltas_id_minus_ood"]

    lines: list[str] = [
        "# Full System Tuning Report",
        "",
        f"Generated: {compare_result['generated_at_utc']}",
        "",
        "## Scope",
        f"- ID pattern: {compare_result['contract']['id_pattern']}",
        f"- OOD pattern: {compare_result['contract']['ood_pattern']}",
        f"- Files per group: {compare_result['contract']['count']}",
        f"- Status source of truth: {compare_result['contract']['status_source']}",
        "",
        "## ID Per-File Results",
    ]
    lines.extend(_to_md_table(compare_result["id_rows"]))

    lines.extend(
        [
            "",
            "## OOD Per-File Results",
        ]
    )
    lines.extend(_to_md_table(compare_result["ood_rows"]))

    lines.extend(
        [
            "",
            "## Group Means",
            f"- ID: auto={id_group['autonomy_mean']:.4f}, trust={id_group['trust_delib_mean']:.4f}, trust_floor={id_group['trust_delib_floor']:.4f}, guard={id_group['guard_utility_mean']:.4f}",
            f"- OOD: auto={ood_group['autonomy_mean']:.4f}, trust={ood_group['trust_delib_mean']:.4f}, trust_floor={ood_group['trust_delib_floor']:.4f}, guard={ood_group['guard_utility_mean']:.4f}",
            "",
            "## Delta (ID - OOD)",
            f"- autonomy_mean: {deltas['autonomy_mean']:.4f}",
            f"- trust_delib_mean: {deltas['trust_delib_mean']:.4f}",
            f"- trust_id_ood_delta: {deltas['trust_id_ood_delta']:.4f}",
            f"- guard_utility_mean: {deltas['guard_utility_mean']:.4f}",
            f"- learned_only_rate_mean: {deltas['learned_only_rate_mean']:.4f}",
            f"- hardcoded_only_rate_mean: {deltas['hardcoded_only_rate_mean']:.4f}",
            f"- mixed_rate_mean: {deltas['mixed_rate_mean']:.4f}",
            f"- phase1_intervention_utility_win3_mean: {deltas['phase1_intervention_utility_win3_mean']:.4f}",
            f"- projection_effectiveness_score_mean: {deltas['projection_effectiveness_score_mean']:.4f}",
            "",
            "## Status and Drift",
            f"- ID status counts: {id_group['status_counts']}",
            f"- OOD status counts: {ood_group['status_counts']}",
            f"- ID drift count: {id_group['drift_count']}",
            f"- OOD drift count: {ood_group['drift_count']}",
            "",
            "## Regression Flags",
        ]
    )
    lines.extend(_regression_flag_lines(compare_result["regressions"]))

    lines.extend(
        [
            "",
            "## Progression Consistency",
            f"- Pattern: {progression_result['pattern']}",
            f"- Files checked: {progression_result['summary']['files_checked']}",
            f"- Files with issues: {progression_result['summary']['files_with_issues']}",
            f"- Total issues: {progression_result['summary']['issues_total']}",
            f"- Status: {progression_result['summary']['status']}",
            "",
            "## Recommendations",
        ]
    )
    for rec in _recommendations(compare_result, progression_result):
        lines.append(f"- {rec}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "report_path": str(output_path),
        "compare": compare_result,
        "progression": progression_result,
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-pattern", default="Log Dump/15_mazes_hard_*.txt")
    parser.add_argument("--ood-pattern", default="Log Dump/15_mazes_very_hard_*.txt")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--python-exe", default="python3")
    parser.add_argument("--preflight-script", default="preflight_dump_gate.py")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--trust-drop-warn", type=float, default=0.10)
    parser.add_argument("--trust-mean-min", type=float, default=0.82)
    parser.add_argument("--trust-floor-min", type=float, default=0.72)
    parser.add_argument("--trust-id-ood-delta-max", type=float, default=0.10)
    parser.add_argument("--autonomy-drop-warn", type=float, default=0.05)
    parser.add_argument("--guard-drop-warn", type=float, default=0.03)
    parser.add_argument("--progress-pattern", default="Log Dump/15_mazes_*.txt")
    parser.add_argument("--progress-count", type=int, default=15)
    parser.add_argument(
        "--output",
        default=f"phase_plans/reports/FULL_SYSTEM_TUNING_REPORT_{date.today().isoformat()}.md",
    )
    parser.add_argument("--json-out")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = generate_report(args)
    print(f"Report written: {payload['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
