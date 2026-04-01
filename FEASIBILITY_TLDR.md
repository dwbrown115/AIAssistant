# TL;DR Feasibility Pitch: Conversation-First Dual-Model Assistant

**Date:** February 2026  
**Status:** Feasible, recommended to proceed with staged build

## 1) Problem
Most assistants force a tradeoff:
- Strong chat quality but weak execution, or
- Strong execution but poor user communication.

We need one product that feels like a single assistant while combining both strengths.

## 2) Proposed Solution (Simple)
Build a **conversation-first dual-model system**:
- **Model C (Conversation)** is the primary interface for all user communication.
- **Model A (Agent)** is invoked behind the scenes for planning, tool use, coding, and task execution.
- Both models share one **context index** (memory system) so handoffs preserve intent and continuity.
- Product scope is **text-only in v1** to reduce cost and simplify delivery.

## 3) Why This Works
- Better user trust: one coherent voice (Model C).
- Better task outcomes: execution handled by a specialist (Model A).
- Better context quality: shared memory avoids re-explaining and supports personalization.

## 4) Core Architecture
1. User prompt enters conversation layer.
2. Model C interprets intent, constraints, and ambiguity.
3. Shared index retrieves context.
4. Orchestrator decides whether to invoke Model A.
5. Model A executes and returns artifacts/state.
6. Model C explains results, asks clarifications, and handles approvals.

## 5) Context/Index Strategy (Key Differentiator)
Treat indexing as a first-class ML system.

Use a hybrid index:
- Vector search (semantic similarity)
- Structured memory store (canonical facts)
- Zettelkasten-style link graph (topic-neighbor knowledge)

Rank retrieved context with a weighted score over:
- semantic similarity,
- recency,
- usage utility (what worked before),
- graph proximity,
- keyword match.

Start rule-based in MVP, then move to learning-to-rank using production feedback.

## 6) Business Value / ROI
- Higher completion rate on complex tasks.
- Lower user friction due to better interpretation before execution.
- Reduced wasted tokens via better retrieval and fewer correction turns.
- Clear upgrade path from API-first to selective fine-tuning only where ROI is proven.
- Lower operating overhead by avoiding voice/image/video pipelines in v1.

## 7) Risks and Mitigations
- **Inconsistent model behavior** → strict handoff schema and conversation-mediated responses.
- **Memory staleness/contamination** → TTL, confidence scoring, contradiction resolution.
- **Agent overreach** → scoped tool permissions + explicit user approvals.
- **Cost growth** → model tiering, retrieval budgets, caching, and precomputed topic links.

## 8) Delivery Plan
- **Phase 0 (2–3 weeks):** requirements, governance, stack decisions.
- **Phase 1 (6–9 weeks):** MVP (orchestrator, shared index, core tools, internal alpha).
- **Phase 2 (6–10 weeks):** hardening (eval harness, learned routing, memory quality).
- **Phase 3 (ongoing):** optimization (fine-tuning/distillation, domain packs).

## 9) Success Metrics (First 90 Days)
- Task completion rate
- First-response relevance
- Clarification efficiency
- Conversation-to-agent handoff comprehension
- Retrieval hit quality
- Hallucination/incorrect action rate
- p50/p95 latency
- Cost per successful task

## 10) Go/No-Go Recommendation
**Go.**
Proceed with an API-first, conversation-first MVP and instrument deeply.
Only invest in model fine-tuning after measured gains in task success, quality, and cost efficiency.

## 11) Immediate Next Steps
1. Finalize top 5 workflows and acceptance criteria.
2. Define memory governance policy (retention, sensitivity, deletion).
3. Build thin orchestrator prototype with 10–20 evaluation scenarios.
4. Benchmark against single-model baseline.
5. Decide phase-1 scope based on measured quality/cost delta.
