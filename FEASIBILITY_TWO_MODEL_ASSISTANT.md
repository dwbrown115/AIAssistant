# Feasibility Document: Dual-Model Customized GPT Assistant

**Date:** February 2026  
**Project Goal:** Build a customized GPT-based assistant with two separate but integrated models:
1. **Conversation Model** optimized for natural chat, intent interpretation, and user assistance (Copilot-like conversational UX).
2. **Agent Model** optimized for tool use, code/task execution, planning, and autonomous multi-step actions (GitHub Copilot/agent-like behavior).

**Design Principle:** The Conversation Model is the **primary user interface** and mediator. Users interact with it first; it coordinates with the Agent Model for execution and then returns results in a consistent conversational experience.

**Context Placement Principle:** Shared context memory/index is **local-first on the device**, with optional encrypted sync for multi-device continuity.

**Interaction Scope Principle:** v1 is **text-only** to lower cost and reduce implementation complexity.

---

## 1) Executive Summary

Building a dual-model assistant is **feasible** with current LLM infrastructure and model APIs. The architecture should use:
- A **conversation-first orchestrator** where the Conversation Model is the front door for every user turn.
- A **smart router** that decides when to invoke the Agent Model behind the scenes.
- A **shared local memory index** used by both models for continuity, personalization, and task context.
- A **unified policy/safety layer** and **telemetry loop** to optimize quality over time.

A realistic path is:
- **MVP (8–12 weeks):** API-based models + on-device retrieval memory + basic routing + guardrails (text-only UX).
- **Production v1 (4–6 months):** stronger orchestration, learned routing, evaluation harness, cost controls, and selective fine-tuning.
- **Advanced (6–12+ months):** memory hierarchy, domain fine-tunes, long-horizon planning improvements, and automated quality governance.

---

## 2) Problem Statement and Product Intent

You want one assistant experience that feels coherent, but internally uses two specialized reasoning modes:

- **Mode A: Conversational Interpretation**
  - High empathy, concise explanations, ambiguity handling, policy-safe response style.
  - Strong at summarization, intent extraction, and user education.

- **Mode B: Agentic Execution**
  - High reliability for decomposition, planning, tool calls, coding, data operations, and iterative task completion.
  - Strong at "do the work" operations, not just explain.

The challenge is to combine these into one product while preserving:
- Fast response times,
- Context continuity,
- Safety/compliance,
- Cost efficiency,
- Predictable behavior.

Additional requirement for product coherence:
- The user should primarily communicate with the Conversation Model, while Agent Model actions are requested, explained, and confirmed through that same conversational layer.

Scope decision for v1:
- Text-only interaction (no voice/image/video), with multimodal support treated as a later-phase expansion.

---

## 3) Feasibility Assessment

### Overall Feasibility: **High**

Why it is feasible now:
- Mature hosted model APIs support role-specialized prompting and tool-calling.
- Vector/knowledge indexing stacks are production-ready.
- Existing orchestration frameworks reduce implementation complexity.
- Evaluation methodologies for assistants are much better than 2 years ago.

Primary constraints:
- Multi-model orchestration complexity.
- Memory quality (retrieval precision, stale context, privacy handling).
- Tool execution safety and deterministic behavior.
- Cost/performance balancing under real usage.

Conclusion: Technically and operationally feasible with staged rollout and strong observability.

---

## 4) Target Architecture

## 4.1 Core Components

1. **Client Layer**
   - Text UI channels (web/app/IDE chat)
   - Session identity + auth
   - Streaming responses

2. **Orchestrator Layer**
   - Conversation-first request intake
   - Agent invocation router (decides if/when Agent Model is called)
   - Workflow state machine

3. **Model Layer**
   - **Model C (Conversation):** tuned for language quality, intent understanding, and explanation.
   - **Model A (Agent):** tuned for planning, tools, code/task execution, iterative loops.

4. **Shared Memory Index**
   - User profile memory (preferences, style, constraints)
   - Session/task memory (active objective, plans, artifacts)
   - Knowledge memory (documents, repos, notes)
   - Zettelkasten note graph as the primary long-term context memory
   - Local-first storage on device with optional encrypted cloud sync

5. **Tooling Layer**
   - APIs, databases, file systems, code workspaces, enterprise connectors
   - Sandboxed execution environment

6. **Governance Layer**
   - Policy filters, PII controls, redaction, consent gates
   - Audit logs and event tracing

## 4.2 Interaction Pattern

1. User sends prompt.
2. Conversation Model (Model C) interprets intent, ambiguity, and constraints.
3. API queries Zettelkasten context index (notes + links + tags + embeddings) and attaches retrieved memory.
4. Orchestrator decides whether Agent Model (Model A) is needed for execution.
5. If needed, Model C creates a structured task packet and dispatches to Model A.
6. Model A executes plan/tool actions and returns artifacts + execution state.
7. Model C translates results back to the user, asks clarifying questions, and requests approvals when needed.
8. Memory updater writes confirmed outcomes back into Zettelkasten notes/links with TTL and confidence tags.

---

## 5) Shared Memory Index Design

A shared memory index is central to integration quality.

In this architecture, the **index is the context engine** for both models. Retrieval quality directly controls reasoning quality, so indexing strategy should be treated as a first-class ML subsystem.

The **primary memory medium is Zettelkasten-style notes**: atomic notes, explicit links, and topic tags. The API queries this store every turn so the assistant can "remember" relevant prior knowledge through retrieval.

## 5.1 Memory Types

- **Episodic Memory:** what happened in recent sessions/tasks.
- **Semantic Memory:** durable facts (user/team/project knowledge).
- **Procedural Memory:** preferred workflows, templates, coding conventions.

## 5.2 Storage Strategy

Use a hybrid approach:
- **Local Zettelkasten note store** as canonical memory representation.
- **Local vector index** for semantic retrieval over note content.
- **Local relational/document DB** for metadata/state indexes.
- **Object store** for larger artifacts.
- **Zettelkasten-style link graph** for topic-neighbor traversal and keyword-connected notes.

Default deployment profile:
- Keep memory/index on-device for privacy and lower recurring cloud index cost.
- Sync only selected memory scopes using end-to-end encryption when multi-device use is required.

Each memory entry should include:
- `scope` (user/team/project/session),
- `sensitivity` (public/internal/restricted),
- `freshness` / TTL,
- `confidence score`,
- `provenance` (source + timestamp),
- `embedding version`,
- `keywords` (normalized tags),
- `topic_cluster_id`,
- `note_links` (related-note references),
- `usage_stats` (views, successful retrieval count, last_used_at).

Suggested Zettelkasten note structure:
- `note_id`, `title`, `body`
- `tags` (keywords)
- `links_to` / `linked_from`
- `source_ref` and `created_at` / `updated_at`
- `confidence` and `ttl`

## 5.3 Retrieval and Ranking Algorithm

Use a hybrid ranker that combines semantic relevance, recency, and utility:

$$
Score = w_s \cdot SemanticSim + w_r \cdot Recency + w_u \cdot UsageUtility + w_g \cdot GraphProximity + w_k \cdot KeywordMatch
$$

Where:
- `UsageUtility` increases weight for context that historically contributed to successful task completion.
- `GraphProximity` uses Zettelkasten links/topic graph distance to pull related context not captured by embedding similarity alone.
- `KeywordMatch` improves precision for explicit user terms.

ML enhancement options:
- Start with fixed weights (MVP), then train a lightweight learning-to-rank model on retrieval outcomes.
- Add per-user/per-domain personalization weights over time.
- Use online feedback signals (accepted answer, successful execution, fewer clarifications) to re-rank frequently useful items.

## 5.4 Read/Write Policies

- **Write:** only commit memory from high-confidence outputs or explicit user confirmations.
- **Read:** enforce tenant isolation + security labels.
- **Update:** periodic compaction and contradiction resolution (new facts supersede stale facts).
- **Delete:** user-visible controls for memory purge/export.
- **Re-index:** scheduled keyword/topic clustering refresh and link maintenance for Zettelkasten graph integrity.
- **Local Security:** encrypt memory at rest using OS keychain-backed keys.
- **Sync Policy:** explicit opt-in sync with per-scope controls and auditability.

Memory write pattern for reliable recall:
- Write short atomic notes (one durable fact/procedure per note).
- Auto-link new notes to nearest topic neighbors.
- Promote frequently retrieved notes into "hot context" for faster access.

---

## 6) Routing and Model Integration Strategy

Routing policy baseline:
- **User-facing responses are always delivered through Model C.**
- **Model A is an execution specialist invoked by Model C/orchestrator, not the primary user dialogue endpoint.**

## 6.1 Initial Rule-Based Router (MVP)

Use deterministic heuristics first:
- If prompt includes "build", "run", "fix", "implement", "analyze repo" → Model C acknowledges, clarifies requirements, then invokes Model A.
- If prompt includes "explain", "summarize", "what does this mean" → Model C handles directly.
- If confidence low → Model C asks clarifying questions before any agent execution.

## 6.2 Learned Router (Post-MVP)

Train a lightweight classifier on production traces:
- Inputs: intent features, tool need probability, context length, urgency.
- Outputs: model choice + expected token/runtime budget.

## 6.3 Handoff Protocol

To keep behavior coherent:
- Shared intermediate schema: `intent`, `constraints`, `plan`, `artifacts`, `next_action`.
- Require each model to emit short structured state for the other model.
- Require Model A outputs to include `assumptions`, `actions_taken`, and `approval_required` flags for Model C to relay.
- Keep user-facing style consistent via Model C response normalization.

---

## 7) Model Strategy Options

## Option 1: API-First (Recommended)

- Use hosted foundation models for both C and A roles.
- Different system prompts, tool schemas, temperature/profile settings.

**Pros:** fastest launch, lower infra burden, high reliability.  
**Cons:** less control over deep weights and custom internals.

## Option 2: Hybrid Fine-Tune

- Keep one hosted model; fine-tune/open-weight model for one specialized role.

**Pros:** better task specialization, possible lower long-term cost.  
**Cons:** higher MLOps complexity, eval burden, model drift management.

## Option 3: Fully Custom Models

- Train and host both role-optimized models.

**Pros:** maximum control, custom behavior depth.  
**Cons:** highest cost, staffing, risk, and time-to-market.

**Recommendation:** Start with Option 1, move to Option 2 when usage data proves ROI.

---

## 8) Safety, Compliance, and Trust

Key requirements for enterprise readiness:
- Role-based access control for memory retrieval.
- PII/secret detection before memory writes.
- Sandboxed tool execution with allowlists.
- Human confirmation gates for high-impact actions (deletes, external sends, purchases).
- Full trace logging: prompt, retrieved context, tool calls, outputs, model/version.
- Conversation-mediated approvals so high-impact actions are confirmed in natural language with explicit user intent.
- Local encryption key management and secure device-bound memory access controls.

Risk areas:
- Prompt injection through retrieved content.
- Over-persistent memory storing sensitive data.
- Agent overreach (tool misuse without explicit consent).

Mitigations:
- Retrieval-time content sanitization.
- Memory write filters + user consent modes.
- Capability-scoped tool tokens and revocable sessions.

---

## 9) Performance and Cost Feasibility

## 9.1 Latency Targets (Reasonable)

- Conversation turns: 1.5–3.5s first token target.
- Agent turns with tools: 4–20s depending on workflow depth.

## 9.2 Cost Drivers

- Token volume (prompt + retrieval + output).
- Tool execution infrastructure.
- Embedding and re-indexing frequency.
- Long session retention.
- Retrieval ranker complexity (graph traversal + re-ranking passes).
- Device performance variability for local indexing and retrieval latency.
- Optional encrypted sync/backup traffic for multi-device continuity.

Text-only effect:
- Avoids multimodal pipelines and typically lowers total operating cost versus multimodal deployments.

## 9.3 Cost Controls

- Dynamic context truncation + retrieval budget.
- Cache frequent memory retrieval bundles.
- Use smaller model for classification/routing.
- Escalate to larger model only on ambiguity or failures.
- Precompute topic clusters and hot-path note links to reduce query-time graph cost.
- Run local indexing/re-indexing in idle or charging windows.
- Bound on-device index size with hot/warm/cold memory tiers.

---

## 10) Implementation Roadmap

## Phase 0 (2–3 weeks): Discovery & Design
- Define use cases and success metrics.
- Finalize memory schema and data governance policy.
- Choose base model providers and tool runtime stack.
- Define local storage encryption, backup, and sync scope policy.
- Lock text-only product scope and response-style constraints.

## Phase 1 (6–9 weeks): MVP Build
- Build orchestrator + rule-based router.
- Implement shared local memory service (write/read APIs + local vector store).
- Add keyword extraction + initial topic clustering for note indexing.
- Add core tools and execution sandbox.
- Ship internal alpha with observability dashboards.
- Exclude voice/image/video pipelines from MVP scope.

## Phase 2 (6–10 weeks): Hardening
- Build eval harness (task success, hallucination rate, tool error rate).
- Add learned router and fallback policies.
- Improve memory quality (ranking, dedupe, contradiction handling).
- Add learning-to-rank and Zettelkasten link graph scoring in retriever.
- Add user-facing memory controls.
- Add optional encrypted multi-device sync conflict-resolution rules.

## Phase 3 (ongoing): Optimization
- Selective fine-tuning/distillation.
- Adaptive planning loops for agent mode.
- Domain packs (code, support, operations, legal/compliance by policy).

---

## 11) Staffing and Capability Requirements

Minimum team for v1:
- 1 Product Lead
- 1–2 Full-stack Engineers
- 1 ML/LLM Engineer
- 1 Platform/Infra Engineer
- 1 Security/Compliance contributor (part-time acceptable early)
- 1 QA/Evaluation specialist (can be shared role initially)

Critical capabilities:
- LLM prompt + evaluation engineering
- Retrieval/memory systems
- Tooling sandbox and secure execution
- Observability and incident response
- Local storage security, key management, and sync architecture

---

## 12) Key Risks and Mitigation Matrix

1. **Inconsistent behavior between models**  
   Mitigation: strict handoff schema + unified style post-processor.

2. **Memory contamination/staleness**  
   Mitigation: confidence scoring, TTL, contradiction resolution jobs.

3. **High operating cost under scale**  
   Mitigation: model tiering, caching, dynamic context limits.

4. **Agent mistakes with real-world impact**  
   Mitigation: approval workflows, scoped tool permissions, rollback logs.

5. **Evaluation blind spots**  
   Mitigation: red-team prompts + scenario replay + regression suites.

---

## 13) Success Metrics (Launch + 90 Days)

- Task completion rate (agent workflows)
- First-response relevance score
- Clarification efficiency (fewer unnecessary follow-ups)
- Conversation-to-agent handoff comprehension score (did agent output match interpreted intent)
- Retrieval hit quality (percent of top-k context used in final successful output)
- Hallucination/incorrect action rate
- Latency percentiles (p50/p95)
- Cost per successful task
- User trust metrics (thumbs up/down + retention)

---

## 14) Final Feasibility Verdict

A two-model integrated assistant with shared memory is **practically achievable** and can provide a strong product advantage:
- Better conversational quality than one-size-fits-all agent systems,
- Better execution reliability than chat-only systems,
- Better personalization and continuity via memory sharing.

With a conversation-first integration pattern, users get a single coherent interface while still benefiting from agent-grade execution depth.

Best path:
1. Launch API-first MVP quickly.
2. Instrument deeply (quality, cost, safety).
3. Iterate routing + memory quality before heavy fine-tuning.
4. Introduce custom model specialization only where data proves clear ROI.

---

## 15) Recommended Next Actions (Immediate)

1. Write a one-page Product Requirements Document with top 5 workflows.
2. Define memory governance policy (what is never stored, retention, deletion rights).
3. Build a thin orchestrator prototype with 10–20 curated eval tasks.
4. Validate whether conversation-first dual-model routing materially outperforms a single-model baseline.
5. Decide go/no-go for phase-1 engineering based on measured delta and cost envelope.
