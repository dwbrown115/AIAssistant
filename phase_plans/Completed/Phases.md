Phase Set (Current Runtime Default)

Phase 1 Envelope + Shadow
Goal	Freeze behavior envelope and evaluate new module guidance without control authority
Execution	Keep baseline chooser authoritative; run advisory channels in shadow mode only; log counterfactual utility and risk deltas
Exit gate	No regression against envelope thresholds for completion, loop severity, no-progress streaks, and unresolved objective overrides

Phase 2 Low-Influence Blend
Goal	Introduce advisory influence gradually while preventing behavior drift
Execution	Blend advisory deltas into score with low trust-scaled weights; enforce intervention budgets per window; keep emergency safety clamps hard
Exit gate	Sustained quality at or above baseline while hardcoded-only channel share trends down and intervention utility remains positive

Phase 3 Hybrid Arbitration
Goal	Promote adaptive arbitration while preserving guardrails
Execution	Run adaptive-first selection in eligible contexts; keep heuristic channels as safety shaping and catastrophic veto only
Exit gate	Stable completion and reduced loop pressure under mixed channel traffic; no increase in unresolved-objective lock behavior

Phase 4 Auto-Anneal + Rollback
Goal	Automate hardcoded influence reduction with safe fallback
Execution	Anneal legacy channel weights when rolling metrics are healthy; auto-rollback up when guardrail metrics regress beyond threshold
Exit gate	Long-window stability with low hardcoded dependency and zero sustained guardrail violations

Phase 5 Legacy Prune
Goal	Retire obsolete hardcoded paths while keeping compact emergency safety core
Execution	Remove deprecated forced branches; keep minimal catastrophic safety handlers and audit hooks
Exit gate	Parity-or-better behavior with simpler control path and unchanged safety outcomes

Guardrails (must remain non-regressing across all phases)
1) Solve/completion consistency
2) Loop pressure and repeat-transition severity
3) Max no-progress streak
4) Unresolved objective override rate
5) Projection beneficial-vs-harmful contribution trend

Rollout policy
1) Shadow first, then low influence, then hybrid arbitration
2) Promotion requires consecutive healthy windows, not single-run spikes
3) Any guardrail breach triggers immediate phase hold and automatic rollback to prior influence profile
