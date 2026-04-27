#!/usr/bin/env python3
"""Progression consistency checks for phase/micro counters in recent log dumps."""

from __future__ import annotations

import argparse
import glob
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RX_PHASE_JSON = re.compile(r'"completed_phase_count"\s*:\s*([0-9]+)')
RX_PHASE_KV = re.compile(r"completed_phase_count[:= ]+([0-9]+)")
RX_MICRO_JSON = re.compile(r'"completed_micro_total"\s*:\s*([0-9]+)')
RX_MICRO_KV = re.compile(r"completed_micro_total[:= ]+([0-9]+)")
RX_TARGET_JSON = re.compile(r'"active_target"\s*:\s*"?([^",\s}]+)')
RX_TARGET_KV = re.compile(r"active_target[:= ]+([^ ,}]+)")
RX_SIG_JSON = re.compile(r'"phase_set_signature"\s*:\s*"?([^",\s}]+)')
RX_SIG_KV = re.compile(r"phase_set_signature[:= ]+([^ ,}]+)")


@dataclass
class ProgressRow:
    file: str
    phase_count: int | None
    micro_count: int | None
    active_target: str | None
    phase_set_signature: str | None
    issues: list[str]


def _newest_files(pattern: str, count: int) -> list[Path]:
    files = sorted(glob.glob(pattern), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    return [Path(p) for p in files[:count]]


def _extract_last(pattern_json: re.Pattern[str], pattern_kv: re.Pattern[str], line: str) -> str | None:
    m = pattern_json.search(line)
    if m:
        return m.group(1)
    m = pattern_kv.search(line)
    if m:
        return m.group(1)
    return None


def _parse_progress(path: Path) -> ProgressRow:
    phase: int | None = None
    micro: int | None = None
    target: str | None = None
    signature: str | None = None

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            v_phase = _extract_last(RX_PHASE_JSON, RX_PHASE_KV, line)
            if v_phase is not None:
                try:
                    phase = int(v_phase)
                except ValueError:
                    pass

            v_micro = _extract_last(RX_MICRO_JSON, RX_MICRO_KV, line)
            if v_micro is not None:
                try:
                    micro = int(v_micro)
                except ValueError:
                    pass

            v_target = _extract_last(RX_TARGET_JSON, RX_TARGET_KV, line)
            if v_target is not None:
                target = v_target

            v_sig = _extract_last(RX_SIG_JSON, RX_SIG_KV, line)
            if v_sig is not None:
                signature = v_sig

    issues: list[str] = []
    if phase is None:
        issues.append("missing_phase_count")
    if micro is None:
        issues.append("missing_micro_count")
    if phase is not None and phase < 0:
        issues.append("negative_phase_count")
    if micro is not None and micro < 0:
        issues.append("negative_micro_count")
    if phase is not None and micro is not None and phase == 0 and micro > 0:
        issues.append("micro_progress_without_phase_progress")

    return ProgressRow(
        file=path.name,
        phase_count=phase,
        micro_count=micro,
        active_target=target,
        phase_set_signature=signature,
        issues=issues,
    )


def check_progression_consistency(pattern: str, count: int) -> dict[str, Any]:
    files = _newest_files(pattern, count)
    rows = [_parse_progress(path) for path in files]

    issues_total = sum(len(r.issues) for r in rows)
    files_with_issues = sum(1 for r in rows if r.issues)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pattern": pattern,
        "count": count,
        "files": [p.name for p in files],
        "rows": [asdict(r) for r in rows],
        "summary": {
            "files_checked": len(rows),
            "files_with_issues": files_with_issues,
            "issues_total": issues_total,
            "status": "PASS" if files_with_issues == 0 else "WARN",
        },
    }


def _print_console(result: dict[str, Any]) -> None:
    print("PROGRESSION CONSISTENCY")
    print("file | phase | micro | active_target | phase_set_signature | issues")
    for row in result["rows"]:
        issues = ",".join(row["issues"]) if row["issues"] else "none"
        print(
            f"{row['file']} | {row['phase_count']} | {row['micro_count']} | "
            f"{row['active_target']} | {row['phase_set_signature']} | {issues}"
        )
    print("SUMMARY", result["summary"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="Log Dump/15_mazes_*.txt")
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--json-out")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = check_progression_consistency(args.pattern, args.count)
    _print_console(result)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
