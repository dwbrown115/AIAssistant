from __future__ import annotations


def build_micro3_phase_definition() -> dict[str, object]:
    """Return the retired phase-3 deprecation micro plan for archival reference."""
    return {
        "name": "Hard Override Channels",
        "priority": "medium",
        "groups": [
            "HARD_OVERRIDE_PHASE_LEVEL / CONSOLIDATED_OVERRIDE_PHASE_LEVEL",
            "PHASE2_* hardcoded influence channels",
        ],
        "micro_steps": [
            {
                "label": "3.0 Disable frontier-lock forcing",
                "description": "Retire first hard forced-routing channel.",
                "overrides": {
                    "consolidated_override_phase_level": -1,
                    "hard_override_phase_level": 1,
                },
            },
            {
                "label": "3.1 Move to soft-influence routing",
                "description": "Retire persistent-frontier forcing and enforce soft override mode.",
                "overrides": {
                    "consolidated_override_phase_level": -1,
                    "hard_override_phase_level": 2,
                    "phase2_soft_override_enable": True,
                    "phase2_frontier_lock_influence": 18,
                    "phase2_persistent_frontier_influence": 12,
                },
            },
            {
                "label": "3.2 Disable verification/plan-hold forcing",
                "description": "Route through score influence only and lower hardcoded planner pressure.",
                "overrides": {
                    "consolidated_override_phase_level": -1,
                    "hard_override_phase_level": 4,
                    "phase2_soft_override_enable": True,
                    "phase2_verification_influence": 10,
                    "phase2_plan_hold_influence": 8,
                },
            },
        ],
    }
