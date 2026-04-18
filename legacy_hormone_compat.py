"""Deprecated legacy hormone blending helpers.

This module isolates transition-era legacy blend behavior so the core app
logic can move toward hormone-native control without carrying compatibility
implementation details in the main app file.
"""

from __future__ import annotations


class LegacyHormoneCompatMixin:
    """Compatibility helpers for legacy endocrine blend migration."""

    def _hormone_blended_weight(
        self,
        modern_value: float,
        legacy_value: float,
        legacy_blend_override: float | None = None,
    ) -> float:
        if legacy_blend_override is None:
            legacy_blend = max(0.0, min(1.0, float(self.hormone_legacy_weight_blend)))
        else:
            legacy_blend = max(0.0, min(1.0, float(legacy_blend_override)))
        return ((1.0 - legacy_blend) * float(modern_value)) + (legacy_blend * float(legacy_value))

    def _legacy_batch_1_low_impact_disabled(self) -> bool:
        # Least impact: remove legacy confidence/momentum shaping first.
        return int(self.hormone_legacy_batch_level) >= 1

    def _legacy_batch_2_repeat_pressure_disabled(self) -> bool:
        # Next: remove legacy repeat/fatigue pressure coupling.
        return int(self.hormone_legacy_batch_level) >= 2

    def _legacy_batch_3_exploration_bias_disabled(self) -> bool:
        # Then: remove legacy curiosity-novelty exploration weighting.
        return int(self.hormone_legacy_batch_level) >= 3

    def _legacy_batch_4_risk_guard_disabled(self) -> bool:
        # Highest impact: remove legacy caution/risk weighting.
        return int(self.hormone_legacy_batch_level) >= 4

    def _legacy_weight_disabled_for_channel(self, channel: str) -> bool:
        key = (channel or "").strip().lower()
        if key in {"confidence", "momentum"}:
            return self._legacy_batch_1_low_impact_disabled()
        if key in {"boredom", "repeat_pressure", "fatigue"}:
            return self._legacy_batch_2_repeat_pressure_disabled()
        if key in {"curiosity", "exploration"}:
            return self._legacy_batch_3_exploration_bias_disabled()
        if key in {"caution", "risk"}:
            return self._legacy_batch_4_risk_guard_disabled()
        return False

    def _hormone_loop_adaptation_signal(self) -> float:
        if not self.endocrine_enabled:
            return 0.0
        if not hasattr(self, "endocrine"):
            return 0.0
        try:
            hormone = self.endocrine.state()
        except Exception:  # noqa: BLE001
            return 0.0

        H_caution = float(hormone.get("H_caution", 0.0) or 0.0)
        H_boredom = float(hormone.get("H_boredom", 0.0) or 0.0)
        H_confidence = float(hormone.get("H_confidence", 0.0) or 0.0)
        H_persistence = float(hormone.get("H_persistence", 0.0) or 0.0)

        raw_pressure = (
            (0.75 * H_caution)
            + (0.70 * H_boredom)
            - (0.55 * H_confidence)
            - (0.45 * H_persistence)
        )
        centered = raw_pressure - float(self.hormone_dynamic_legacy_loop_center)
        scaled = centered * float(self.hormone_dynamic_legacy_loop_gain)
        return max(0.0, min(1.0, scaled))

    def _dynamic_legacy_blend_for_channel(self, channel: str, base_blend: float) -> float:
        blend = max(0.0, min(1.0, float(base_blend)))
        if blend <= 0.0:
            return 0.0
        if not self.hormone_dynamic_legacy_enable:
            return blend

        key = (channel or "").strip().lower()
        if key not in {"confidence", "momentum", "boredom", "repeat_pressure", "fatigue"}:
            return blend

        loop_signal = self._hormone_loop_adaptation_signal()
        if loop_signal <= 0.0:
            return blend

        max_suppression = float(self.hormone_dynamic_legacy_batch12_suppression_max)
        suppression = max(0.0, min(max_suppression, loop_signal * max_suppression))
        return blend * (1.0 - suppression)

    def _hormone_weight_for_channel(self, channel: str, modern_value: float, legacy_value: float) -> float:
        if self._legacy_weight_disabled_for_channel(channel):
            return float(modern_value)
        base_blend = max(0.0, min(1.0, float(self.hormone_legacy_weight_blend)))
        effective_blend = self._dynamic_legacy_blend_for_channel(channel, base_blend)
        return self._hormone_blended_weight(
            modern_value,
            legacy_value,
            legacy_blend_override=effective_blend,
        )
