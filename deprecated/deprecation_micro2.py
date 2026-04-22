from __future__ import annotations


def build_micro2_phase_definition() -> dict[str, object]:
    """Return the phase-2 deprecation micro plan without applying any runtime deprecation."""
    return {
        "name": "Legacy Endocrine Controls",
        "priority": "medium-low",
        "groups": [
            "HORMONE_LEGACY_* blend/batch controls",
            "deprecated ENDOCRINE_* bridge scoring knobs",
        ],
        "micro_steps": [
            {
                "label": "2.0 Legacy batch gate 2",
                "description": "Disable legacy confidence/momentum + repeat-pressure channel groups.",
                "overrides": {
                    "hormone_legacy_batch_level": 2,
                    "hormone_legacy_weight_blend": 0.2,
                },
            },
            {
                "label": "2.1 Legacy batch gate 3",
                "description": "Disable legacy curiosity/exploration channel group.",
                "overrides": {
                    "hormone_legacy_batch_level": 3,
                    "hormone_legacy_weight_blend": 0.15,
                },
            },
            {
                "label": "2.2 Legacy batch gate 4",
                "description": "Full hormone-native mode for caution/risk blend path.",
                "overrides": {
                    "hormone_legacy_batch_level": 4,
                    "hormone_legacy_weight_blend": 0.1,
                    "adaptive_guard_legacy_strength": 0.5,
                },
            },
        ],
    }
