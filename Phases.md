Phase 0 Baseline Lock	Freeze today’s behavior so we can measure improvements	Keep current logic in place, run 3 to 5 baseline batches, archive dumps and snapshots	Stable completion baseline and loop-tag baseline established

Phase 1 Instrument Only	Add learning telemetry without changing decisions	In app.py, log per-step decision_source as hardcoded, learned, mixed; log intervention type and delayed outcome window. In preflight_dump_gate.py, add phase metrics for intervention utility	Metrics visible in dumps and preflight, no behavior regression
Phase 2 Soften Hard Overrides	Convert hard channels to weighted score influences	In app.py, replace direct force paths with score deltas multiplied by channel weights. Keep only emergency safety clamps as hard	Completion stays near baseline while hardcoded_only_rate drops
Phase 3 Learned Channel Weights	Let model learn how much each rule should matter by context	In adaptive_controller.py, add small head predicting channel weights from current context. In app.py, apply learned weights to rule deltas	learned_only_rate and mixed_rate trend up, loop density trends down
Phase 4 Adaptive-First Arbitration	Make learner the primary chooser, rules become guardrails	Switch arbitration order so adaptive policy chooses first, heuristic channels act as safety shaping and veto only for catastrophic states	Full-run completion remains high with fewer hard overrides
Phase 5 Auto-Anneal Hardcoded Influence	Automatically reduce legacy influence when performance is stable	Add annealing logic based on rolling completion, loop tags, and catastrophic penalties; fall back up if regressions appear	Long runs stable with low hardcoded dependency
Phase 6 Legacy Prune	Remove obsolete hardcoded branches	Delete dead override paths and keep compact emergency safety core	Cleaner code path with equivalent or better performance

Phase 3 Readiness Evaluation (2026-04-07)
Decision	Conditional hold (pilot allowed, full rollout not yet)
Why	Current runs show major hardcoded-rate improvement, but loop severity and manual rescue events are still present	Proceed with guarded Phase 3 scaffolding only

Evidence (Baseline vs Current)
- Baseline full runs (20260407_103529/103741): guard_override_rate=0.7629, learned_only_rate=0.1985, hardcoded_only_rate=0.1048, mixed_rate=0.6581, max_no_progress=51, max_penalty=1000.
- Current full runs:
	- 20260407_111255: completed=15/15, guard_override_rate=0.1064, learned_only_rate=0.8204, hardcoded_only_rate=0.0155, mixed_rate=0.0909, max_no_progress=37, max_penalty=1641.
	- 20260407_112128: completed=15/15, guard_override_rate=0.1084, learned_only_rate=0.7422, hardcoded_only_rate=0.0115, mixed_rate=0.0969, max_no_progress=54, max_penalty=1699.
- Manual assist observed in latest run set (keyboard_input events around steps 808-830), indicating unresolved trap pocket behavior.

Architecture Gap for Phase 3
- Adaptive controller currently predicts a single scalar adjustment, not per-channel rule weights.
- app.py currently applies adaptive score adjustment globally, not as context-conditioned channel multipliers.

Phase 3 Entry Criteria (for full rollout)
1) Two consecutive 15-maze full runs with no manual keyboard intervention.
2) hardcoded_only_rate <= 0.02 and mixed_rate <= 0.15 on both runs.
3) max_no_progress <= 40 and max_penalty <= 1400 on both runs.
4) Implement channel-weight head and keep it behind a feature flag with fallback to current Phase 2 behavior.
