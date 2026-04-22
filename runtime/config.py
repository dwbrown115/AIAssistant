from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRuntimeConfig:
    logic_model: str
    agent_model: str
    local_navigation_kernel: bool
    local_navigation_api_fallback: bool


def load_model_runtime_config() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        logic_model=os.getenv("OPENAI_LOGIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
        agent_model=os.getenv("OPENAI_AGENT_MODEL", "gpt-4o-mini"),
        local_navigation_kernel=os.getenv("LOCAL_NAVIGATION_KERNEL", "1") == "1",
        local_navigation_api_fallback=os.getenv("LOCAL_NAVIGATION_API_FALLBACK", "1") == "1",
    )
