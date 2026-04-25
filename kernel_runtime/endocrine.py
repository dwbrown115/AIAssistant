import os


class Hormone:
    def __init__(
        self,
        value: float = 0.0,
        decay: float = 0.95,
        min_val: float = 0.0,
        max_val: float = 1.0,
    ) -> None:
        self.value = float(value)
        self.decay = float(decay)
        self.min_val = float(min_val)
        self.max_val = float(max_val)

    def update(self, delta: float) -> None:
        self.value = max(self.min_val, min(self.max_val, self.value + float(delta)))

    def tick(self) -> None:
        self.value = max(self.min_val, min(self.max_val, self.value * self.decay))


class EndocrineSystem:
    """Slow global modulators that bias move selection and memory behavior."""

    def __init__(self) -> None:
        self.H_curiosity = Hormone(
            value=0.36,
            decay=float(os.getenv("H_CURIOSITY_DECAY", "0.97")),
        )
        self.H_caution = Hormone(
            value=0.24,
            decay=float(os.getenv("H_CAUTION_DECAY", "0.93")),
        )
        self.H_persistence = Hormone(
            value=0.32,
            decay=float(os.getenv("H_PERSISTENCE_DECAY", "0.965")),
        )
        self.H_mv_trust = Hormone(
            value=0.28, decay=float(os.getenv("H_MV_TRUST_DECAY", "0.96"))
        )
        self.H_boredom = Hormone(
            value=0.16,
            decay=float(os.getenv("H_BOREDOM_DECAY", "0.985")),
        )
        self.H_confidence = Hormone(
            value=0.30,
            decay=float(os.getenv("H_CONFIDENCE_DECAY", "0.96")),
        )
        self._homeostasis_targets = {
            "H_curiosity": 0.36,
            "H_caution": 0.24,
            "H_persistence": 0.32,
            "H_mv_trust": 0.28,
            "H_boredom": 0.16,
            "H_confidence": 0.30,
        }
        self._saturation_high_start = max(
            0.7,
            min(0.99, float(os.getenv("HORMONE_SATURATION_HIGH_START", "0.86"))),
        )
        self._saturation_low_end = max(
            0.01,
            min(0.3, float(os.getenv("HORMONE_SATURATION_LOW_END", "0.14"))),
        )
        self._saturation_min_scale = max(
            0.05,
            min(1.0, float(os.getenv("HORMONE_SATURATION_MIN_SCALE", "0.30"))),
        )
        self._distress_recovery_enable = (
            os.getenv("HORMONE_DISTRESS_RECOVERY_ENABLE", "1") == "1"
        )
        self._distress_recovery_threshold = max(
            0.75,
            min(0.99, float(os.getenv("HORMONE_DISTRESS_RECOVERY_THRESHOLD", "0.86"))),
        )
        self._distress_recovery_step = max(
            0.001,
            min(0.05, float(os.getenv("HORMONE_DISTRESS_RECOVERY_STEP", "0.016"))),
        )
        self._distress_drive_threshold = min(
            -0.2,
            max(
                -2.0,
                float(
                    os.getenv("HORMONE_DISTRESS_EXPLORATION_DRIVE_THRESHOLD", "-0.82")
                ),
            ),
        )
        self._distress_drive_recovery_scale = max(
            1.0,
            min(3.0, float(os.getenv("HORMONE_DISTRESS_DRIVE_RECOVERY_SCALE", "1.55"))),
        )
        self._outcome_penalty_clip = max(
            30.0,
            float(os.getenv("HORMONE_OUTCOME_PENALTY_CLIP", "260.0")),
        )
        self._dead_end_penalty_scale = max(
            0.05,
            min(1.0, float(os.getenv("HORMONE_DEAD_END_PENALTY_SCALE", "0.30"))),
        )
        self._terminal_boxed_penalty_scale = max(
            0.05,
            min(1.0, float(os.getenv("HORMONE_TERMINAL_BOXED_PENALTY_SCALE", "0.45"))),
        )
        self._repeat_loop_penalty_scale = max(
            0.05,
            min(1.0, float(os.getenv("HORMONE_REPEAT_LOOP_PENALTY_SCALE", "0.55"))),
        )
        self._distress_persistence_cap = max(
            0.05,
            min(0.95, float(os.getenv("HORMONE_DISTRESS_PERSISTENCE_CAP", "0.42"))),
        )
        self._distress_persistence_relief_step = max(
            0.002,
            min(
                0.08,
                float(os.getenv("HORMONE_DISTRESS_PERSISTENCE_RELIEF_STEP", "0.024")),
            ),
        )
        self._last_decay_step = -1
        self._last_signature_step = -1

    def _edge_damped_delta(self, hormone: Hormone, delta: float) -> float:
        value = float(hormone.value)
        d = float(delta)
        if d > 0.0 and value >= self._saturation_high_start:
            span = max(1e-6, 1.0 - self._saturation_high_start)
            proximity = max(0.0, min(1.0, (value - self._saturation_high_start) / span))
            scale = max(self._saturation_min_scale, 1.0 - proximity)
            d *= scale
        elif d < 0.0 and value <= self._saturation_low_end:
            span = max(1e-6, self._saturation_low_end)
            proximity = max(0.0, min(1.0, (self._saturation_low_end - value) / span))
            scale = max(self._saturation_min_scale, 1.0 - proximity)
            d *= scale
        return d

    def _update_hormone(self, hormone: Hormone, delta: float) -> None:
        hormone.update(self._edge_damped_delta(hormone, delta))

    def _exploration_drive(self) -> float:
        return (
            self.H_curiosity.value
            + (0.45 * self.H_confidence.value)
            + (0.40 * self.H_persistence.value)
            + (0.35 * self.H_mv_trust.value)
            - (0.60 * self.H_caution.value)
            - (0.70 * self.H_boredom.value)
        )

    def _apply_distress_recovery(self) -> None:
        if not self._distress_recovery_enable:
            return
        exploration_drive = self._exploration_drive()
        high_distress = (
            self.H_caution.value >= self._distress_recovery_threshold
            and self.H_boredom.value >= self._distress_recovery_threshold
        )
        drive_locked = (
            exploration_drive <= self._distress_drive_threshold
            and self.H_caution.value >= (self._distress_recovery_threshold - 0.08)
        )
        if not (high_distress or drive_locked):
            return

        step = float(self._distress_recovery_step)
        if drive_locked:
            step *= float(self._distress_drive_recovery_scale)
        self._update_hormone(self.H_caution, -step)
        self._update_hormone(self.H_boredom, -step)
        self._update_hormone(self.H_curiosity, step)
        self._update_hormone(self.H_confidence, step * 0.8)
        self._update_hormone(self.H_mv_trust, step * 0.7)
        self._update_hormone(self.H_persistence, step * 0.55)

        if (
            exploration_drive <= self._distress_drive_threshold
            and self.H_persistence.value > self._distress_persistence_cap
        ):
            relief = min(
                self._distress_persistence_relief_step,
                self.H_persistence.value - self._distress_persistence_cap,
            )
            if relief > 0.0:
                self._update_hormone(self.H_persistence, -relief)

    def tick(self, step_index: int) -> None:
        if int(step_index) == self._last_decay_step:
            return
        self._last_decay_step = int(step_index)
        for hormone in [
            self.H_curiosity,
            self.H_caution,
            self.H_persistence,
            self.H_mv_trust,
            self.H_boredom,
            self.H_confidence,
        ]:
            hormone.tick()
        self._apply_distress_recovery()

    def update_from_signature(self, signature: dict, step_index: int) -> None:
        if int(step_index) == self._last_signature_step:
            return
        self._last_signature_step = int(step_index)

        dead_end_risk = int(signature.get("dead_end_risk", 0) or 0)
        dead_end_depth = int(signature.get("dead_end_risk_depth", 0) or 0)
        unknown_neighbors = int(signature.get("unknown_neighbors", 0) or 0)
        frontier_distance = int(signature.get("frontier_distance", 0) or 0)
        visit_bucket = int(signature.get("visit_bucket", 0) or 0)
        recent_backtrack = int(signature.get("recent_backtrack", 0) or 0)
        transition_pressure = int(signature.get("transition_pressure_bucket", 0) or 0)
        risky_branches = int(signature.get("visible_risky_branches", 0) or 0)

        caution_delta = (
            (dead_end_risk * 0.035)
            + (min(6, dead_end_depth) * 0.015)
            + (transition_pressure * 0.03)
            + (recent_backtrack * 0.03)
            + (risky_branches * 0.02)
        )
        if unknown_neighbors == 0:
            caution_delta += 0.02
        if frontier_distance >= 3:
            caution_delta += 0.02
        if unknown_neighbors >= 2 and dead_end_risk == 0:
            caution_delta -= 0.015
        self._update_hormone(self.H_caution, caution_delta)

        curiosity_delta = unknown_neighbors * 0.05
        if frontier_distance <= 1:
            curiosity_delta += 0.04
        if dead_end_risk >= 2:
            curiosity_delta -= 0.03
        if risky_branches == 0 and unknown_neighbors == 0:
            curiosity_delta -= 0.02
        self._update_hormone(self.H_curiosity, curiosity_delta)

        boredom_delta = (
            (visit_bucket * 0.03)
            + (transition_pressure * 0.02)
            + (recent_backtrack * 0.03)
        )
        if unknown_neighbors == 0:
            boredom_delta += 0.03
        if unknown_neighbors >= 2 or frontier_distance <= 1:
            boredom_delta -= 0.03
        self._update_hormone(self.H_boredom, boredom_delta)

        persistence_delta = (transition_pressure * 0.022) + (visit_bucket * 0.01)
        if unknown_neighbors > 0 and frontier_distance <= 2:
            persistence_delta += 0.018
        if recent_backtrack > 0 and unknown_neighbors == 0:
            persistence_delta -= 0.014
        if dead_end_risk >= 2:
            persistence_delta -= 0.01
        self._update_hormone(self.H_persistence, persistence_delta)

        confidence_delta = 0.0
        if dead_end_risk == 0 and unknown_neighbors > 0 and visit_bucket <= 1:
            confidence_delta += 0.03
        if dead_end_risk >= 2 or recent_backtrack > 0:
            confidence_delta -= 0.03
        if risky_branches >= 2:
            confidence_delta -= 0.02
        self._update_hormone(self.H_confidence, confidence_delta)

        mv_trust_delta = 0.0
        if unknown_neighbors > 0 and frontier_distance <= 2 and dead_end_risk <= 1:
            mv_trust_delta += 0.02
        if risky_branches == 0 and dead_end_risk == 0:
            mv_trust_delta += 0.015
        if recent_backtrack > 0 or dead_end_risk >= 2:
            mv_trust_delta -= 0.025
        if transition_pressure >= 2:
            mv_trust_delta -= 0.015
        self._update_hormone(self.H_mv_trust, mv_trust_delta)

    def update_from_outcome(
        self,
        outcome_value: float,
        reward_signal: float,
        penalty_signal: float,
        tags: list[str],
    ) -> None:
        outcome = float(outcome_value)
        reward = max(0.0, float(reward_signal))
        penalty = max(0.0, float(penalty_signal))
        tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
        has_terminal_or_boxed = bool({"visible_terminal", "boxed_corridor"} & tag_set)
        has_repeat_loop = bool(
            {"cycle_pair", "transition_repeat", "immediate_backtrack"} & tag_set
        )
        has_dead_end_slap = bool(
            {"dead_end_slap", "dead_end_tip_revisit", "dead_end_entrance_revisit"}
            & tag_set
        )

        if penalty > 0.0 and has_dead_end_slap:
            scale = float(self._dead_end_penalty_scale)
            penalty *= scale
            if outcome < 0.0:
                outcome *= scale

        if penalty > 0.0 and has_terminal_or_boxed:
            scale = float(self._terminal_boxed_penalty_scale)
            penalty *= scale
            if outcome < 0.0:
                outcome *= scale

        if penalty > 0.0 and has_repeat_loop:
            scale = float(self._repeat_loop_penalty_scale)
            penalty *= scale
            if outcome < 0.0:
                outcome *= scale

        trap_churn = bool({"visible_terminal", "boxed_corridor"} & tag_set) and bool(
            {"cycle_pair", "transition_repeat", "immediate_backtrack"} & tag_set
        )
        if trap_churn and penalty > 0.0:
            churn_scale = max(
                0.1,
                min(1.0, float(os.getenv("HORMONE_TRAP_CHURN_PENALTY_SCALE", "0.35"))),
            )
            penalty *= churn_scale
            if outcome < 0.0:
                outcome *= churn_scale

        if penalty > self._outcome_penalty_clip:
            clip = float(self._outcome_penalty_clip)
            scale = clip / max(1e-6, penalty)
            penalty = clip
            if outcome < 0.0:
                outcome *= scale

        if reward > 0.0 or outcome > 0.0:
            gain = max(reward, max(0.0, outcome))
            self._update_hormone(self.H_confidence, 0.04 + min(0.12, gain / 380.0))
            self._update_hormone(self.H_persistence, 0.03 + min(0.10, gain / 460.0))
            self._update_hormone(self.H_caution, -0.05)
            self._update_hormone(self.H_boredom, -0.04)
            self._update_hormone(self.H_mv_trust, 0.02 + min(0.08, gain / 520.0))
            if "novelty_reward" in tag_set or "frontier_visible" in tag_set:
                self._update_hormone(self.H_curiosity, 0.035)
        elif penalty > 0.0 or outcome < 0.0:
            self._update_hormone(self.H_caution, 0.06 + min(0.24, penalty / 260.0))
            self._update_hormone(self.H_boredom, 0.05 + min(0.18, penalty / 300.0))
            self._update_hormone(
                self.H_confidence, -(0.05 + min(0.15, penalty / 320.0))
            )
            self._update_hormone(self.H_mv_trust, -(0.04 + min(0.13, penalty / 360.0)))
            if "cycle_pair" in tag_set or "transition_repeat" in tag_set:
                self._update_hormone(self.H_curiosity, -0.02)
                drive_locked = (
                    self._exploration_drive() <= self._distress_drive_threshold
                )
                high_distress = self.H_caution.value >= (
                    self._distress_recovery_threshold - 0.04
                ) and self.H_boredom.value >= (self._distress_recovery_threshold - 0.04)
                if drive_locked or high_distress:
                    self._update_hormone(self.H_persistence, -0.03)
                else:
                    self._update_hormone(self.H_persistence, 0.01)
            elif penalty > 120.0:
                self._update_hormone(self.H_persistence, -0.02)
        self._apply_distress_recovery()

    def sleep_cycle_prune(
        self,
        *,
        decay_passes: int = 2,
        pull_strength: float = 0.08,
        extreme_threshold: float = 0.95,
    ) -> dict[str, int]:
        passes = max(1, int(decay_passes))
        pull = max(0.0, min(1.0, float(pull_strength)))
        extreme = max(0.5, min(0.999, float(extreme_threshold)))

        hormones: list[tuple[str, Hormone]] = [
            ("H_curiosity", self.H_curiosity),
            ("H_caution", self.H_caution),
            ("H_persistence", self.H_persistence),
            ("H_mv_trust", self.H_mv_trust),
            ("H_boredom", self.H_boredom),
            ("H_confidence", self.H_confidence),
        ]

        def _is_extreme(value: float) -> bool:
            return value >= extreme or value <= (1.0 - extreme)

        saturated_before = sum(
            1 for _name, hormone in hormones if _is_extreme(float(hormone.value))
        )

        for _ in range(passes):
            for _name, hormone in hormones:
                hormone.tick()

        if pull > 0.0:
            for name, hormone in hormones:
                target = float(self._homeostasis_targets.get(name, hormone.value))
                hormone.update((target - float(hormone.value)) * pull)

        saturated_after = sum(
            1 for _name, hormone in hormones if _is_extreme(float(hormone.value))
        )
        return {
            "applied": 1,
            "passes": int(passes),
            "saturated_before": int(saturated_before),
            "saturated_after": int(saturated_after),
        }

    def state(self) -> dict[str, float]:
        return {
            "H_curiosity": round(self.H_curiosity.value, 4),
            "H_caution": round(self.H_caution.value, 4),
            "H_persistence": round(self.H_persistence.value, 4),
            "H_mv_trust": round(self.H_mv_trust.value, 4),
            "H_boredom": round(self.H_boredom.value, 4),
            "H_confidence": round(self.H_confidence.value, 4),
        }

    def neural_state(self) -> dict[str, float]:
        exploration_drive = self._exploration_drive()
        risk_aversion = (
            self.H_caution.value
            - (0.55 * self.H_confidence.value)
            + (0.22 * self.H_boredom.value)
        )
        momentum = (
            self.H_persistence.value
            + (0.45 * self.H_confidence.value)
            - (0.35 * self.H_boredom.value)
        )
        mv_reliance = (
            self.H_mv_trust.value
            - (0.40 * self.H_caution.value)
            + (0.20 * self.H_confidence.value)
        )
        return {
            "exploration_drive": round(exploration_drive, 4),
            "risk_aversion": round(risk_aversion, 4),
            "momentum": round(momentum, 4),
            "mv_reliance": round(mv_reliance, 4),
        }
