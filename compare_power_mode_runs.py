#!/usr/bin/env python3
"""Compare two maze dump files for power-mode-like behavior shifts.

This script does not require explicit power-mode markers in logs.
It compares behavioral proxies that usually move when the runtime regime changes.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass, field
from pathlib import Path


STEP_LINE_RE = re.compile(r"^step=(\d+)\s+proposal_source=.*?guard_override=(True|False)")
UNKNOWN_FRONTIER_RE = re.compile(r"unknown=(\d+)\s+frontier=(\d+)")
KV_FLOAT_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*?)=(-?\d+(?:\.\d+)?)")
SLEEP_HORMONE_PRUNE_RE = re.compile(r"hormone_prune=(\d+)")
SLEEP_HORMONE_SAT_RE = re.compile(r"hormone_sat=(\d+)->(\d+)")


@dataclass
class DumpStats:
    path: Path
    label: str
    step_rows: int = 0
    max_step: int = 0
    guard_true: int = 0
    guard_false: int = 0
    phase4_wait: int = 0
    objective_routing: int = 0
    objective_override: int = 0
    mv_bypass: int = 0
    anti_osc_override: int = 0
    terminal_override: int = 0
    risk_guard_tags: int = 0
    progress_guard_tags: int = 0
    unknown_samples: list[int] = field(default_factory=list)
    frontier_samples: list[int] = field(default_factory=list)
    guard_by_step: dict[int, list[int]] = field(default_factory=dict)
    hormones: dict[str, float] = field(default_factory=dict)
    derived: dict[str, float] = field(default_factory=dict)
    sleep_cycles: int = 0
    sleep_hormone_prune_events: int = 0
    sleep_hormone_sat_before_total: int = 0
    sleep_hormone_sat_after_total: int = 0

    @property
    def guard_override_rate(self) -> float:
        total = self.guard_true + self.guard_false
        return (self.guard_true / total) if total else 0.0

    @property
    def unknown_mean(self) -> float:
        return (sum(self.unknown_samples) / len(self.unknown_samples)) if self.unknown_samples else 0.0

    @property
    def frontier_mean(self) -> float:
        return (sum(self.frontier_samples) / len(self.frontier_samples)) if self.frontier_samples else 0.0


def _safe_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def parse_dump(path: Path, label: str) -> DumpStats:
    stats = DumpStats(path=path, label=label)
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()

        step_match = STEP_LINE_RE.search(line)
        if step_match:
            step = int(step_match.group(1))
            guard_val = 1 if step_match.group(2) == "True" else 0
            stats.step_rows += 1
            stats.max_step = max(stats.max_step, step)
            stats.guard_true += guard_val
            stats.guard_false += 1 - guard_val
            stats.guard_by_step.setdefault(step, []).append(guard_val)

            if "Objective phase-4 disable" in line:
                stats.phase4_wait += 1
            if "Objective routing:" in line:
                stats.objective_routing += 1
            if "Objective override:" in line:
                stats.objective_override += 1
            if "MV-PREPLAN: bypass:mv-disabled" in line:
                stats.mv_bypass += 1
            if "Anti-oscillation override" in line:
                stats.anti_osc_override += 1
            if "Terminal/boxed-corridor override" in line:
                stats.terminal_override += 1
            if "[OBJECTIVE-RISK-GUARD:" in line:
                stats.risk_guard_tags += 1
            if "[OBJECTIVE-PROGRESS-GUARD:" in line:
                stats.progress_guard_tags += 1

            uf = UNKNOWN_FRONTIER_RE.search(line)
            if uf:
                stats.unknown_samples.append(int(uf.group(1)))
                stats.frontier_samples.append(int(uf.group(2)))

        if line.startswith("hormones:"):
            stats.hormones = {
                k: _safe_float(v)
                for k, v in KV_FLOAT_RE.findall(line)
            }
        elif line.startswith("derived:"):
            stats.derived = {
                k: _safe_float(v)
                for k, v in KV_FLOAT_RE.findall(line)
            }

        if "[SLEEP-CYCLE:" in line:
            stats.sleep_cycles += 1
            hp = SLEEP_HORMONE_PRUNE_RE.search(line)
            if hp:
                stats.sleep_hormone_prune_events += int(hp.group(1))
            hs = SLEEP_HORMONE_SAT_RE.search(line)
            if hs:
                stats.sleep_hormone_sat_before_total += int(hs.group(1))
                stats.sleep_hormone_sat_after_total += int(hs.group(2))

    return stats


def window_guard_rates(stats: DumpStats, width: int = 100) -> list[tuple[int, int, int, float]]:
    if not stats.guard_by_step:
        return []
    rates: list[tuple[int, int, int, float]] = []
    step_max = stats.max_step
    for start in range(0, step_max + 1, width):
        end = start + width - 1
        vals: list[int] = []
        for step, step_vals in stats.guard_by_step.items():
            if start <= step <= end:
                vals.extend(step_vals)
        if not vals:
            continue
        rate = sum(vals) / len(vals)
        rates.append((start, end, len(vals), rate))
    return rates


def strongest_shift(stats: DumpStats, window: int = 60) -> tuple[int, float, float, float] | None:
    if len(stats.guard_by_step) < (window * 2):
        return None
    series = sorted(
        (step, sum(vals) / len(vals))
        for step, vals in stats.guard_by_step.items()
    )
    best: tuple[int, float, float, float] | None = None
    best_delta = -1.0
    for i in range(window, len(series) - window):
        left = sum(v for _, v in series[i - window : i]) / window
        right = sum(v for _, v in series[i : i + window]) / window
        delta = abs(right - left)
        if delta > best_delta:
            best_delta = delta
            best = (series[i][0], left, right, right - left)
    return best


def _fmt_delta(a: float, b: float) -> str:
    d = b - a
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.4f}"


def _ratio(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def print_summary(a: DumpStats, b: DumpStats) -> None:
    print(f"A: {a.label} ({a.path})")
    print(f"B: {b.label} ({b.path})")
    print()

    print("== Core Behavior ==")
    print(
        "guard_override_rate: "
        f"A={a.guard_override_rate:.4f} B={b.guard_override_rate:.4f} "
        f"delta={_fmt_delta(a.guard_override_rate, b.guard_override_rate)}"
    )
    print(f"step_rows: A={a.step_rows} B={b.step_rows} delta={b.step_rows - a.step_rows:+d}")
    print(f"max_step: A={a.max_step} B={b.max_step} delta={b.max_step - a.max_step:+d}")
    print(
        "phase4_wait_share: "
        f"A={_ratio(a.phase4_wait, a.step_rows):.4f} B={_ratio(b.phase4_wait, b.step_rows):.4f}"
    )
    print(
        "objective_routing_share: "
        f"A={_ratio(a.objective_routing, a.step_rows):.4f} B={_ratio(b.objective_routing, b.step_rows):.4f}"
    )
    print(
        "objective_override_share: "
        f"A={_ratio(a.objective_override, a.step_rows):.4f} B={_ratio(b.objective_override, b.step_rows):.4f}"
    )
    print(
        "mv_bypass_share: "
        f"A={_ratio(a.mv_bypass, a.step_rows):.4f} B={_ratio(b.mv_bypass, b.step_rows):.4f}"
    )
    print(
        "unknown_mean/frontier_mean: "
        f"A={a.unknown_mean:.2f}/{a.frontier_mean:.2f} "
        f"B={b.unknown_mean:.2f}/{b.frontier_mean:.2f}"
    )

    print()
    print("== Hormone Snapshot ==")
    hormone_keys = ["H_curiosity", "H_caution", "H_persistence", "H_mv_trust", "H_boredom", "H_confidence"]
    for key in hormone_keys:
        av = a.hormones.get(key, math.nan)
        bv = b.hormones.get(key, math.nan)
        if math.isnan(av) and math.isnan(bv):
            continue
        print(f"{key}: A={av:.4f} B={bv:.4f} delta={_fmt_delta(av, bv)}")

    derived_keys = ["exploration_drive", "risk_aversion", "momentum", "mv_reliance"]
    for key in derived_keys:
        av = a.derived.get(key, math.nan)
        bv = b.derived.get(key, math.nan)
        if math.isnan(av) and math.isnan(bv):
            continue
        print(f"{key}: A={av:.4f} B={bv:.4f} delta={_fmt_delta(av, bv)}")

    print()
    print("== Sleep Cycle ==")
    print(
        f"sleep_cycles: A={a.sleep_cycles} B={b.sleep_cycles} "
        f"delta={b.sleep_cycles - a.sleep_cycles:+d}"
    )
    print(
        f"hormone_prune_events: A={a.sleep_hormone_prune_events} B={b.sleep_hormone_prune_events} "
        f"delta={b.sleep_hormone_prune_events - a.sleep_hormone_prune_events:+d}"
    )
    print(
        f"hormone_sat_total(before->after): "
        f"A={a.sleep_hormone_sat_before_total}->{a.sleep_hormone_sat_after_total} "
        f"B={b.sleep_hormone_sat_before_total}->{b.sleep_hormone_sat_after_total}"
    )

    print()
    print("== Strongest Guard-Rate Shift ==")
    for stats in [a, b]:
        shift = strongest_shift(stats)
        if not shift:
            print(f"{stats.label}: n/a")
            continue
        step, left, right, delta = shift
        trend = "degradation" if delta > 0 else "improvement"
        print(
            f"{stats.label}: step~{step} left={left:.3f} right={right:.3f} "
            f"delta={delta:.3f} ({trend})"
        )

    print()
    print("== Windowed Guard Rates (B) ==")
    for start, end, rows, rate in window_guard_rates(b):
        print(f"steps {start:03d}-{end:03d}: rows={rows:3d} override_rate={rate:.3f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two dump files for implicit low-power vs regular-mode behavior differences."
    )
    parser.add_argument("dump_a", type=Path, help="First dump file (for example: low-power run)")
    parser.add_argument("dump_b", type=Path, help="Second dump file (for example: regular-power run)")
    parser.add_argument("--label-a", default="A", help="Label for first run")
    parser.add_argument("--label-b", default="B", help="Label for second run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dump_a.exists():
        raise SystemExit(f"Missing file: {args.dump_a}")
    if not args.dump_b.exists():
        raise SystemExit(f"Missing file: {args.dump_b}")

    stats_a = parse_dump(args.dump_a, args.label_a)
    stats_b = parse_dump(args.dump_b, args.label_b)
    print_summary(stats_a, stats_b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
