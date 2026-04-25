from __future__ import annotations


def build_phase4_outline_definition() -> dict[str, object]:
    """Return the retired phase-4 deprecation outline for archival reference."""
    return {
        "name": "Objective Force Channels",
        "priority": "high",
        "groups": [
            "OBJECTIVE_OVERRIDE_PHASE_LEVEL unresolved-force channels",
            "objective unresolved score/repeat forced-margin hardcoded gates",
        ],
        "micro_steps": [
            {
                "label": "4.0 Moderate objective override suppression",
                "description": "Reduce unresolved objective forcing while preserving fallback safety.",
                "overrides": {"objective_override_phase_level": 2},
            },
            {
                "label": "4.1 Strong objective override suppression",
                "description": "Shift objective preference to learned/soft channels first.",
                "overrides": {"objective_override_phase_level": 3},
            },
            {
                "label": "4.2 Full unresolved objective suppression",
                "description": "Disable final hard unresolved objective forcing path.",
                "overrides": {"objective_override_phase_level": 4},
            },
        ],
    }