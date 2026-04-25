from __future__ import annotations


PHASE5_TRAINING_SYSTEM_PLAN: list[dict[str, object]] = [
    {
        "name": "Extraction-Ready Finalization",
        "priority": "highest",
        "groups": [
            "deprecated runtime constants / bridge-only knobs",
            "legacy compatibility mixin and cleanup candidates",
        ],
        "micro_steps": [
            {
                "label": "5.0 Freeze extraction baseline",
                "description": "Hold active channels at migration-safe minimum state.",
                "overrides": {
                    "objective_override_phase_level": 4,
                },
            },
            {
                "label": "5.1 Guard baseline hardening",
                "description": "Reduce remaining legacy guard strength for extraction dry run.",
                "overrides": {
                    "adaptive_guard_legacy_strength": 0.25,
                },
            },
            {
                "label": "5.2 Extraction ready",
                "description": "Final pre-removal checkpoint before deleting env-bound legacy paths.",
                "overrides": {
                    "adaptive_guard_legacy_strength": 0.25,
                    "adaptive_guard_legacy_strength_init": 0.25,
                },
            },
        ],
    },
]


class DeprecatedPhase5ProgressionMixin:
    """Archived runtime mixin preserving the retired phase-5 progression system."""

    def _build_deprecation_phase_plan(self) -> list[dict[str, object]]:
        return [
            {
                "name": str(phase.get("name", "")),
                "priority": str(phase.get("priority", "")),
                "groups": list(phase.get("groups", [])),
                "micro_steps": list(phase.get("micro_steps", [])),
            }
            for phase in PHASE5_TRAINING_SYSTEM_PLAN
        ]

    def _clamp_deprecation_indices(self, phase_index: int, micro_index: int) -> tuple[int, int]:
        phase_total = max(1, len(self.deprecation_phase_plan))
        phase_idx = max(0, min(int(phase_index), phase_total - 1))
        phase = self.deprecation_phase_plan[phase_idx]
        steps = list(phase.get("micro_steps", []))
        micro_total = max(1, len(steps))
        micro_idx = max(0, min(int(micro_index), micro_total - 1))
        return (phase_idx, micro_idx)

    def _deprecation_step_iter_until_current(self) -> list[dict[str, object]]:
        steps: list[dict[str, object]] = []
        current_phase = int(self.deprecation_phase_index)
        current_micro = int(self.deprecation_micro_index)
        for phase_idx, phase in enumerate(self.deprecation_phase_plan):
            micro_steps = list(phase.get("micro_steps", []))
            for micro_idx, micro_step in enumerate(micro_steps):
                if phase_idx > current_phase:
                    return steps
                if phase_idx == current_phase and micro_idx > current_micro:
                    return steps
                steps.append(micro_step)
        return steps

    def _apply_deprecation_progression_overrides(self) -> None:
        baseline = dict(getattr(self, "_deprecation_manual_baseline", {}))
        if not baseline:
            return
        for attr_name, attr_value in baseline.items():
            setattr(self, attr_name, attr_value)
        for step in self._deprecation_step_iter_until_current():
            overrides = dict(step.get("overrides", {}))
            for attr_name, attr_value in overrides.items():
                if attr_name in baseline:
                    setattr(self, attr_name, attr_value)
        self.objective_override_phase_level = max(0, min(4, int(self.objective_override_phase_level)))
        self.consolidated_override_phase_level = -1
        self.adaptive_guard_legacy_strength = max(float(self.adaptive_guard_legacy_min_strength), min(1.0, float(self.adaptive_guard_legacy_strength)))
        self.adaptive_guard_legacy_strength_init = max(float(self.adaptive_guard_legacy_min_strength), min(1.0, float(self.adaptive_guard_legacy_strength_init)))
        self._refresh_learned_autonomy_subphase_state()

    def _refresh_deprecation_progression_ui(self) -> None:
        phase_idx, micro_idx = self._clamp_deprecation_indices(int(self.deprecation_phase_index), int(self.deprecation_micro_index))
        self.deprecation_phase_index = phase_idx
        self.deprecation_micro_index = micro_idx
        phase = self.deprecation_phase_plan[phase_idx]
        steps = list(phase.get("micro_steps", []))
        step = steps[micro_idx] if steps else {}
        label = str(step.get("label", f"{phase_idx + 1}.{micro_idx}"))
        priority = str(phase.get("priority", "n/a"))
        phase_text = f"{label} | Phase {phase_idx + 1}/{len(self.deprecation_phase_plan)}: {phase.get('name', 'Unnamed')} ({priority})"
        self.deprecation_progress_var.set(phase_text)
        self.deprecation_progress_detail_var.set(str(step.get("description", "")))
        groups = list(phase.get("groups", []))
        if groups:
            self.deprecation_progress_groups_var.set("Extraction groups: " + " | ".join((str(g) for g in groups)))
        else:
            self.deprecation_progress_groups_var.set("Extraction groups: (none)")
        self._schedule_micro_progress_header_update(announce_transition=False)

    def _set_deprecation_progression_state(self, phase_index: int, micro_index: int, *, persist: bool, announce: bool) -> None:
        phase_idx, micro_idx = self._clamp_deprecation_indices(phase_index, micro_index)
        self.deprecation_phase_index = phase_idx
        self.deprecation_micro_index = micro_idx
        self._apply_deprecation_progression_overrides()
        self._refresh_deprecation_progression_ui()
        if announce:
            phase = self.deprecation_phase_plan[phase_idx]
            step = list(phase.get("micro_steps", []))[micro_idx]
            self.status_var.set(f"Deprecation progression -> {step.get('label', f'{phase_idx + 1}.{micro_idx}')}")
        if persist and self.deprecation_progress_persist_enable:
            self._save_window_geometry()

    def _deprecation_progress_prev_phase(self) -> None:
        target_phase = int(self.deprecation_phase_index) - 1
        current_micro = int(self.deprecation_micro_index)
        self._set_deprecation_progression_state(target_phase, current_micro, persist=True, announce=True)

    def _deprecation_progress_next_phase(self) -> None:
        target_phase = int(self.deprecation_phase_index) + 1
        current_micro = int(self.deprecation_micro_index)
        self._set_deprecation_progression_state(target_phase, current_micro, persist=True, announce=True)

    def _deprecation_progress_prev_micro(self) -> None:
        phase_idx = int(self.deprecation_phase_index)
        micro_idx = int(self.deprecation_micro_index) - 1
        if micro_idx < 0:
            phase_idx -= 1
            if phase_idx >= 0:
                prior_steps = list(self.deprecation_phase_plan[phase_idx].get("micro_steps", []))
                micro_idx = max(0, len(prior_steps) - 1)
            else:
                phase_idx = 0
                micro_idx = 0
        self._set_deprecation_progression_state(phase_idx, micro_idx, persist=True, announce=True)

    def _deprecation_progress_next_micro(self) -> None:
        phase_idx = int(self.deprecation_phase_index)
        micro_idx = int(self.deprecation_micro_index) + 1
        current_steps = list(self.deprecation_phase_plan[phase_idx].get("micro_steps", []))
        if micro_idx >= len(current_steps):
            phase_idx += 1
            if phase_idx < len(self.deprecation_phase_plan):
                micro_idx = 0
            else:
                phase_idx = len(self.deprecation_phase_plan) - 1
                last_steps = list(self.deprecation_phase_plan[phase_idx].get("micro_steps", []))
                micro_idx = max(0, len(last_steps) - 1)
        self._set_deprecation_progression_state(phase_idx, micro_idx, persist=True, announce=True)

    def _deprecation_progress_reset(self) -> None:
        self._set_deprecation_progression_state(0, 0, persist=True, announce=True)


def build_phase5_training_system_archive() -> dict[str, object]:
    """Return the retired phase-5 runtime deprecation-training scaffold.

    This archive captures the final extraction-ready progression that used to
    manually push legacy objective/guard channels toward removal.
    """

    return {
        "name": "Extraction-Ready Finalization",
        "priority": "highest",
        "groups": [
            "deprecated runtime constants / bridge-only knobs",
            "legacy compatibility mixin and cleanup candidates",
        ],
        "micro_steps": [
            {
                "label": str(step.get("label", "")),
                "description": str(step.get("description", "")),
                "overrides": dict(step.get("overrides", {})),
            }
            for step in PHASE5_TRAINING_SYSTEM_PLAN[0].get("micro_steps", [])
        ],
        "retired_runtime_methods": [
            "_build_deprecation_phase_plan",
            "_clamp_deprecation_indices",
            "_deprecation_step_iter_until_current",
            "_apply_deprecation_progression_overrides",
            "_refresh_deprecation_progression_ui",
            "_set_deprecation_progression_state",
            "_deprecation_progress_prev_phase",
            "_deprecation_progress_next_phase",
            "_deprecation_progress_prev_micro",
            "_deprecation_progress_next_micro",
            "_deprecation_progress_reset",
        ],
        "retired_ui_panel": "Deprecation Progression",
    }
