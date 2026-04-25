# Kernel Evaluation and Roadmap

## Executive Summary

Current state: strong adaptive maze controller with excellent introspection, safety scaffolding, and operational tooling.

Comparative maturity: above average for local heuristic-plus-learning navigation systems, but still closer to an advanced "adaptive control stack" than a "primate-like cognitive system."

Bottom line:
- You are beyond toy and baseline agent quality.
- You are not yet at robust abstraction, causal modeling, and transfer depth expected of primate-like cognition.
- The biggest risk is complexity-driven pseudo-adaptivity (many interacting controls that can look adaptive without being truly general).

## Relative Position vs Similar Systems

### What is stronger than most peers
- Very high observability and debug depth.
- Strong guardrail/intervention instrumentation and health gating.
- Broad set of anti-loop and uncertainty recovery mechanisms.
- Good runtime governance discipline and explicit progression framing.
- Rich memory surfaces (working, STM, semantic, cause-effect) with maintenance routines.

### What is weaker than top adaptive architectures
- Learned arbitration still limited by many hand-tuned gates.
- Representation learning depth is moderate, not deep.
- Generalization confidence outside the training regime is unclear.
- Causal counterfactual planning is limited.
- System complexity makes attribution difficult (what learned vs what was forced).

## Honest Interpretation of the "Juvenile Rat Brain" Comparison

That analogy is directionally fair for navigation competency and loop-avoidance behavior, but incomplete.

Fair parts:
- Strong local spatial behavior.
- Effective novelty/reward style modulation.
- Habit-like recovery under repeated pressure.

Incomplete parts:
- Your stack has higher introspection and governance than typical biological analogies imply.
- You already have early multi-system arbitration concepts that go beyond simple reactive behavior.

More accurate framing:
- "Early multi-system adaptive controller with strong safety scaffolding and emerging abstraction, not yet high-level cognitive architecture."

## Key Oversights and Structural Risks

### 1) Control-surface overload
Many knobs can create brittle interactions and hidden couplings.

Risk:
- Hard to know if gains are true learning or compensating heuristics.

### 2) Intervention entanglement
Multiple override channels can mask policy weaknesses.

Risk:
- Learned core gets less pressure to improve where rescue paths are always available.

### 3) Metric circularity
If optimization and evaluation share too many channels, you can overfit health scores.

Risk:
- Passing gates but weak transfer.

### 4) Limited abstraction bottleneck
A large share of behavior still appears tied to engineered feature rules.

Risk:
- Weak compositional transfer to new maze distributions or altered objectives.

### 5) Weak causal world modeling
Planning appears mostly over heuristic score fields and short-horizon signals.

Risk:
- Limited counterfactual reasoning and fragile long-horizon planning.

### 6) OOD testing is not first-class enough
You have strong in-family validation, but less explicit out-of-distribution contracts.

Risk:
- Unknown failure cliffs outside familiar map statistics.

## What to Improve for More "Primate-Like" Capability

### Priority A: Learn arbitration, do not only tune it
- Replace portions of fixed override weighting with a learned meta-controller.
- Inputs: uncertainty, disagreement, recent intervention utility, risk memory, confidence calibration.
- Output: allow/deny/scale interventions, with explicit confidence.

Expected effect:
- Lower manual tuning burden and cleaner ownership boundaries.

### Priority B: Add a compact latent world model
- Learn transition and observation prediction in latent space.
- Run short-horizon model-predictive planning over latent rollouts.
- Keep current heuristics as fallback policy.

Expected effect:
- Better long-horizon coherence and stronger transfer under novelty.

### Priority C: Separate fast, slow, and sleep systems cleanly
- Fast system: reactive action selection.
- Slow system: deliberate planning and arbitration.
- Sleep system: replay, consolidation, and pruning.
- Define strict contracts for what each layer can override.

Expected effect:
- Better interpretability and reduced intervention leakage.

### Priority D: Convert hormone modulation from mostly fixed to partly learned
- Keep hormone channels, but learn update deltas from outcomes and context.
- Constrain with stability priors to avoid volatility.

Expected effect:
- More adaptive behavior-state transitions with less hand-retuning.

### Priority E: Make transfer the top success metric
Add explicit gates for:
- In-distribution performance.
- OOD maze family performance.
- Intervention rate under OOD.
- Degradation under noise/partial observability shifts.
- Recovery speed after distribution shift.

Expected effect:
- Better real adaptivity signal, less score gaming.

## Practical 3-Phase Upgrade Plan

### Phase 1 (2-4 weeks): De-entangle and measure
- Build a mechanism attribution matrix (which module caused each final action).
- Add mandatory ablation runs per major mechanism.
- Track intervention utility by context bucket.

Deliverables:
- Attribution report.
- Intervention utility heatmap.
- "Top 20 knobs" reduction proposal.

### Phase 2 (4-8 weeks): Learned meta-controller pilot
- Introduce a constrained learned arbitration layer.
- Keep hard safety vetoes non-learned.
- Train on intervention utility and outcome quality.

Deliverables:
- Reduced override frequency without quality drop.
- Equal or better OOD stability vs current baseline.

### Phase 3 (8-16 weeks): World-model integration
- Add latent transition model and short-horizon planner.
- Use arbitration to choose between heuristic policy and world-model plan.

Deliverables:
- Improved OOD solve rates.
- Lower dependence on brittle hardcoded penalties.

## Validation Protocol (Non-Negotiable)

For each major change, require:
- Baseline vs change A/B on same seeds.
- In-distribution and OOD test suites.
- Intervention frequency and utility delta.
- Failure-mode histogram, not just aggregate averages.
- Regression checks on unresolved override rate and learned-only rate.

## Criteria for "More Primate-Like" in This Project

Use practical criteria rather than biological labels:
- Can switch strategies under novelty without manual retuning.
- Can preserve performance when task statistics shift.
- Uses learned arbitration more than fixed override stacks.
- Builds reusable latent representations that transfer.
- Demonstrates stable long-horizon planning with fewer forced interventions.

If those metrics improve, you are moving in the right direction regardless of metaphor.

## Final Assessment

You have built a serious adaptive kernel with unusually strong observability and governance for this class of project. The next leap is not adding more knobs, but reducing handcrafted coupling and increasing learned structure in arbitration and planning. That is the shortest path from "clever controller" to "more general cognitive system."
