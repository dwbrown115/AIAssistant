# Costs and Model Selection: Dual-Model Linked Assistant

**Date:** February 2026  
**Scope:** Cost rundown for running two separate but linked models (conversation-first + agent execution), with **context stored on-device**, plus recommended model choices.

## Assumption
- Context memory/index lives on the user device (local-first retrieval).
- Cloud model APIs are still used for model inference unless explicitly replaced with local models.
- Assistant interaction is **text-only** (no voice, image, or video processing in v1).

## Text-Only Impact
Text-only operation lowers complexity and usually lowers cost by removing:
- speech-to-text and text-to-speech pipelines,
- media preprocessing/storage,
- multimodal model routing and larger context payloads.

Practical effect:
- lower infrastructure overhead,
- lower average per-turn token and runtime variance,
- easier QA and policy control in early phases.

## 1) Cost Reality (What changes with two linked models)
A two-model system usually adds:
- orchestration overhead,
- extra context retrieval,
- occasional double-inference turns (chat model mediates + agent model executes).

But it can also reduce waste if routing is good:
- most turns stay on a cheaper chat model,
- expensive agent model runs only when execution is required,
- fewer failed task loops due to better understanding before execution.

## 2) Cost Components
Your monthly run cost is approximately:

$$
C_{total} = C_{chat\_tokens} + C_{agent\_tokens} + C_{embeddings} + C_{local\_index} + C_{tool\_runtime} + C_{observability} + C_{sync}
$$

Where:
- `C_chat_tokens`: conversation model input/output token cost
- `C_agent_tokens`: agent model input/output token cost
- `C_embeddings`: indexing + re-indexing + query embeddings
- `C_local_index`: on-device storage/IO and local retrieval compute
- `C_tool_runtime`: sandbox compute, API calls, filesystem/code execution
- `C_observability`: traces, logs, evaluation pipelines
- `C_sync`: optional encrypted backup/sync bandwidth and storage (if multi-device continuity is needed)

With on-device context, you usually reduce recurring cloud vector DB spend but add client-side compute/storage requirements.
With text-only scope, you also avoid multimodal processing costs and can keep routing simpler.

## 3) Practical Cost Drivers
Highest impact levers:
1. Agent invocation rate (`p_agent`): % of turns that call the agent model.
2. Average context length per turn.
3. Output verbosity (especially long agent traces).
4. Re-indexing frequency and embedding churn.
5. Tool runtime duration (especially code execution and external APIs).
6. Device class variability (desktop vs laptop vs mobile) for local retrieval latency.

## 4) Example Cost Scenarios (Illustrative)
These are planning estimates, not provider-locked price quotes.

### Baseline usage assumption
- 100,000 total turns/month
- 70% chat-only turns, 30% chat + agent turns
- Chat-only turn tokens (avg): 1,200 input / 500 output
- Agent-invoked turn tokens (avg):
  - chat mediation: 800 input / 300 output
  - agent execution: 2,500 input / 1,000 output

### Scenario A: Cost-optimized stack
- Chat model (small/mini tier): low cost
- Agent model (coding/tool mini tier): moderate cost

Estimated monthly:
- Inference subtotal: **~$450–$1,200**
- Memory/index infra (local-first): **~$20–$180**
- Tool runtime + observability: **~$250–$1,000**
- Optional encrypted sync/backup: **~$0–$250**
- **Total:** **~$720–$2,630 / month**

Text-only adjustment guidance:
- compared with a multimodal-capable stack, expect approximately **10–30% lower total run cost** in many workloads.

### Scenario B: Higher-quality default stack
- Chat model (mid/high quality tier)
- Agent model (strong coding/tool tier)

Estimated monthly:
- Inference subtotal: **~$1,600–$4,500**
- Memory/index infra (local-first): **~$40–$260**
- Tool runtime + observability: **~$400–$1,500**
- Optional encrypted sync/backup: **~$0–$450**
- **Total:** **~$2,040–$6,710 / month**

Text-only adjustment guidance:
- compared with multimodal operation, expect approximately **10–25% lower total run cost** if usage is mostly conversational + agentic text tasks.

### Scale reference
At ~1,000,000 turns/month, multiply by roughly **8x–12x** depending on cache hit rate, routing quality, and context controls.

## 5) Per-Turn Cost Heuristic
Use this quick estimator:

$$
C_{turn} \approx C_{chat} + p_{agent} \cdot C_{agent} + C_{retrieval} + C_{tools}
$$

Typical planning ranges:
- Chat-only turn: **~$0.002–$0.02**
- Agent-invoked turn: **~$0.01–$0.12**
- Blended average (`p_agent`=0.3): **~$0.005–$0.05**

On-device context generally shifts turn cost lower on retrieval, but local latency and battery usage can increase if index maintenance is too aggressive.

## 6) Ideal Model Pairing (Recommended)
Given your architecture (conversation model is primary, agent model is execution specialist):

Given text-only scope, prioritize models with strong text reasoning and tool-use efficiency over multimodal capability.

### Primary recommendation
- **Conversation model:** `GPT-5.3-mini` (default), with selective escalation to `GPT-5.3` for complex ambiguity.
- **Agent model:** `GPT-5.3-Codex` for planning, code/tool workflows, and autonomous multi-step execution.

Why this pairing:
- Keeps most user interaction fast and affordable.
- Preserves high execution reliability for agent tasks.
- Supports conversation-first mediation without paying premium model cost on every turn.

### Alternative (quality-first)
- **Conversation model:** `GPT-5.3`
- **Agent model:** `GPT-5.3-Codex`

Use when:
- user base needs very high interpretive quality,
- complex natural-language requirements are frequent,
- budget can support higher default inference spend.

## 7) Suggested Routing Policy for Cost + Quality
- Start every turn on conversation model.
- Invoke agent model only when execution/tool confidence exceeds threshold.
- Auto-escalate conversation model tier only for ambiguous/high-stakes turns.
- Cap retrieval context budget before invoking agent.
- Enforce max agent loop count per task unless user confirms continuation.
- Keep responses concise by default to control output token spend.

## 8) Cost Optimization Checklist
1. Keep `p_agent` low through better chat clarification.
2. Use cached retrieval bundles for repeated tasks.
3. Compress/summarize long context before agent handoff.
4. Limit verbose output modes unless requested.
5. Batch embeddings and schedule re-indexing windows.
6. Track cost per successful task (not just cost per request).
7. Run local indexing jobs during idle/charging windows.
8. Use encrypted local storage and rotate device keys.
9. Keep v1 strictly text-only; defer voice/image/video until ROI justifies added cost.

## 9) On-Device Context Implementation Notes
- Use local hybrid index: SQLite/Postgres-lite + local vector store + keyword/topic graph.
- Encrypt context at rest on device (OS keychain-backed encryption keys).
- Keep hot context in a bounded cache; archive cold context with lower retrieval priority.
- Add conflict-safe sync if user has multiple devices (CRDT or last-write-wins with provenance).
- Preserve explicit user controls: export, delete, and per-scope memory disable.

## 10) What to Decide Next
1. Pick target monthly budget band (e.g., <$3k, $3k–$8k, >$8k).
2. Choose default conversation tier (`GPT-5.3-mini` vs `GPT-5.3`).
3. Set initial `p_agent` target (recommend 20–35%).
4. Decide whether multi-device encrypted sync is required in v1.
5. Define escalation policy for high-stakes actions.
6. Instrument dashboards: blended turn cost, success-adjusted cost, agent invoke rate, and local retrieval latency.
