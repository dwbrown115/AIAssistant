import os

from . import endocrine as kernel_endocrine
from . import runtime_constants as runtime_const


class KernelBootstrapMixin:
    def _bootstrap_endocrine_kernel_settings(self) -> None:
        self.kernel_no_override_mode = os.getenv("KERNEL_NO_OVERRIDE_MODE", "1") == "1"
        self.endocrine_enabled = os.getenv("ENDOCRINE_ENABLE", "1") == "1"
        self.endocrine = kernel_endocrine.EndocrineSystem()
        # Legacy endocrine bridge knobs are archived under deprecated_code/
        # and intentionally fixed in active runtime.
        self.endocrine_stress_danger_weight = (
            runtime_const.LEGACY_ENDOCRINE_STRESS_DANGER_WEIGHT
        )
        self.endocrine_curiosity_novelty_weight = (
            runtime_const.LEGACY_ENDOCRINE_CURIOSITY_NOVELTY_WEIGHT
        )
        self.endocrine_fatigue_repeat_weight = (
            runtime_const.LEGACY_ENDOCRINE_FATIGUE_REPEAT_WEIGHT
        )
        self.endocrine_confidence_risk_bonus = (
            runtime_const.LEGACY_ENDOCRINE_CONFIDENCE_RISK_BONUS
        )
        self.endocrine_momentum_bonus_weight = (
            runtime_const.LEGACY_ENDOCRINE_MOMENTUM_BONUS_WEIGHT
        )

        # Legacy env-driven blend controls are archived under deprecated_code and no
        # longer wired into active runtime initialization.
        self.hormone_legacy_weight_blend = (
            runtime_const.DEFAULT_HORMONE_LEGACY_WEIGHT_BLEND
        )
        self.hormone_legacy_batch_level = runtime_const.DEFAULT_HORMONE_LEGACY_BATCH_LEVEL

        self.objective_override_phase_level = min(
            runtime_const.MAX_OVERRIDE_PHASE_LEVEL,
            max(
                runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
                int(
                    os.getenv(
                        "OBJECTIVE_OVERRIDE_PHASE_LEVEL",
                        str(self.hormone_legacy_batch_level),
                    )
                ),
            ),
        )
        self.objective_override_enable = (
            os.getenv(
                "OBJECTIVE_OVERRIDE_ENABLE",
                runtime_const.DEFAULT_OBJECTIVE_OVERRIDE_ENABLE,
            )
            == "1"
        )

        # Staged attenuation for hardcoded planner override channels.
        # 0=legacy behavior, 4=maximum suppression of forced override paths.
        self.hard_override_phase_level = min(
            runtime_const.MAX_OVERRIDE_PHASE_LEVEL,
            max(
                runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
                int(
                    os.getenv(
                        "HARD_OVERRIDE_PHASE_LEVEL",
                        runtime_const.DEFAULT_HARD_OVERRIDE_PHASE_LEVEL,
                    )
                ),
            ),
        )
        # Optional: consolidate objective + hard-override phase controls.
        # When set (0..4), this value drives both phase tracks.
        self.consolidated_override_phase_level = max(
            runtime_const.CONSOLIDATED_OVERRIDE_DISABLED,
            min(
                runtime_const.MAX_OVERRIDE_PHASE_LEVEL,
                int(
                    os.getenv(
                        "CONSOLIDATED_OVERRIDE_PHASE_LEVEL",
                        runtime_const.DEFAULT_CONSOLIDATED_OVERRIDE_PHASE_LEVEL,
                    )
                ),
            ),
        )
        if (
            self.consolidated_override_phase_level
            >= runtime_const.MIN_OVERRIDE_PHASE_LEVEL
        ):
            self.objective_override_phase_level = int(
                self.consolidated_override_phase_level
            )
            self.hard_override_phase_level = int(self.consolidated_override_phase_level)
        phase2_soft_default = (
            "1"
            if int(self.hard_override_phase_level)
            >= runtime_const.HARD_OVERRIDE_PHASE2_THRESHOLD
            else "0"
        )
        self.phase2_soft_override_enable = (
            os.getenv("PHASE2_SOFT_OVERRIDE_ENABLE", phase2_soft_default) == "1"
        )
        self.phase2_frontier_lock_influence = max(
            runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
            int(
                os.getenv(
                    "PHASE2_FRONTIER_LOCK_INFLUENCE",
                    runtime_const.DEFAULT_PHASE2_FRONTIER_LOCK_INFLUENCE,
                )
            ),
        )
        self.phase2_persistent_frontier_influence = max(
            runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
            int(
                os.getenv(
                    "PHASE2_PERSISTENT_FRONTIER_INFLUENCE",
                    runtime_const.DEFAULT_PHASE2_PERSISTENT_FRONTIER_INFLUENCE,
                )
            ),
        )
        self.phase2_verification_influence = max(
            runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
            int(
                os.getenv(
                    "PHASE2_VERIFICATION_INFLUENCE",
                    runtime_const.DEFAULT_PHASE2_VERIFICATION_INFLUENCE,
                )
            ),
        )
        self.phase2_plan_hold_influence = max(
            runtime_const.MIN_OVERRIDE_PHASE_LEVEL,
            int(
                os.getenv(
                    "PHASE2_PLAN_HOLD_INFLUENCE",
                    runtime_const.DEFAULT_PHASE2_PLAN_HOLD_INFLUENCE,
                )
            ),
        )
        if self.kernel_no_override_mode:
            self.objective_override_phase_level = runtime_const.MAX_OVERRIDE_PHASE_LEVEL
            self.hard_override_phase_level = runtime_const.MAX_OVERRIDE_PHASE_LEVEL
            self.consolidated_override_phase_level = runtime_const.MAX_OVERRIDE_PHASE_LEVEL
            self.phase2_soft_override_enable = False
