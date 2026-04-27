from __future__ import annotations

import math

from runtime_kernel.kernel_contracts import ReasoningBudgetContract, ReasoningProfile


class ParallelReasoningEngine:
    """Parallel candidate evaluator that blends local, adaptive, and deliberative plans.

    The engine is intentionally lightweight: it evaluates all candidate moves each step,
    estimates per-plan preference scores, and combines them with learned plan-trust EMAs.
    """

    _CHANNELS = ("local", "adaptive", "deliberative")
    _CONTEXT_BUCKETS = ("neutral", "unknown", "frontier", "loop", "hazard")

    def __init__(
        self,
        *,
        enabled: bool,
        ema_decay: float,
        warmup_steps: int,
        min_confidence: float,
        local_weight: float,
        adaptive_weight: float,
        deliberative_weight: float,
        deliberative_unknown_weight: float,
        deliberative_frontier_weight: float,
        deliberative_lookahead_weight: float,
        deliberative_loop_penalty_weight: float,
        deliberative_hazard_penalty_weight: float,
        deliberative_contradiction_penalty_weight: float,
    ) -> None:
        self.enabled = bool(enabled)
        self.ema_decay = self._clamp(float(ema_decay), 0.5, 0.999)
        self.warmup_steps = max(1, int(warmup_steps))
        self.min_confidence = self._clamp(float(min_confidence), 0.05, 0.99)

        self.local_weight = max(0.0, float(local_weight))
        self.adaptive_weight = max(0.0, float(adaptive_weight))
        self.deliberative_weight = max(0.0, float(deliberative_weight))

        self.deliberative_unknown_weight = max(0.0, float(deliberative_unknown_weight))
        self.deliberative_frontier_weight = max(0.0, float(deliberative_frontier_weight))
        self.deliberative_lookahead_weight = max(0.0, float(deliberative_lookahead_weight))
        self.deliberative_loop_penalty_weight = max(0.0, float(deliberative_loop_penalty_weight))
        self.deliberative_hazard_penalty_weight = max(0.0, float(deliberative_hazard_penalty_weight))
        self.deliberative_contradiction_penalty_weight = max(0.0, float(deliberative_contradiction_penalty_weight))

        self.step_count = 0
        self.plan_trust_local = 0.5
        self.plan_trust_adaptive = 0.5
        self.plan_trust_deliberative = 0.5
        self.confidence_ema = 0.5
        self.utility_ema = 0.5
        self.outcome_quality_ema = 0.5
        self.intervention_helpfulness_ema = 0.5
        self.context_trust_blend_weight = 0.38
        self.plan_trust_context: dict[str, dict[str, float]] = {
            channel: {bucket: 0.5 for bucket in self._CONTEXT_BUCKETS}
            for channel in self._CHANNELS
        }
        self.context_bucket_counts: dict[str, int] = {
            bucket: 0 for bucket in self._CONTEXT_BUCKETS
        }
        self.last_strategy = "bootstrap"
        self.strategy_switch_stability_count = 0
        self.last_result: dict[str, object] = {}

    def _profile_default_budget(self, profile: ReasoningProfile) -> ReasoningBudgetContract:
        if profile == ReasoningProfile.FAST_APPROX:
            return ReasoningBudgetContract(max_branches=4, max_depth=2, time_budget_ms=40, token_budget=220)
        if profile == ReasoningProfile.DEEP_AUDIT:
            return ReasoningBudgetContract(max_branches=12, max_depth=5, time_budget_ms=180, token_budget=1200)
        return ReasoningBudgetContract(max_branches=8, max_depth=3, time_budget_ms=90, token_budget=620)

    def _resolve_budget(
        self,
        profile: ReasoningProfile,
        budget: ReasoningBudgetContract | None,
    ) -> ReasoningBudgetContract:
        base = self._profile_default_budget(profile)
        if budget is None:
            return base
        return ReasoningBudgetContract(
            max_branches=max(1, min(32, int(budget.max_branches))),
            max_depth=max(1, min(8, int(budget.max_depth))),
            time_budget_ms=max(8, min(1200, int(budget.time_budget_ms))),
            token_budget=max(64, min(20000, int(budget.token_budget))),
        )

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

    @staticmethod
    def _normalize(value: float, minimum: float, maximum: float) -> float:
        span = float(maximum - minimum)
        if span <= 1e-9:
            return 0.5
        return max(0.0, min(1.0, (float(value) - float(minimum)) / span))

    @staticmethod
    def _sigmoid(value: float) -> float:
        clipped = max(-8.0, min(8.0, float(value)))
        return 1.0 / (1.0 + math.exp(-clipped))

    def _context_bucket(self, candidate: dict[str, float]) -> str:
        unknown = self._clamp(float(candidate.get("unknown_neighbors", 0.0)) / 4.0, 0.0, 1.0)
        frontier = self._clamp(float(candidate.get("frontier_gain", 0.0)), 0.0, 1.0)
        loop_pressure = self._clamp(float(candidate.get("loop_pressure_norm", 0.0)), 0.0, 1.0)
        hazard_pressure = self._clamp(float(candidate.get("hazard_pressure_norm", 0.0)), 0.0, 1.0)

        if hazard_pressure >= 0.62:
            return "hazard"
        if loop_pressure >= 0.58:
            return "loop"
        if frontier >= 0.56:
            return "frontier"
        if unknown >= 0.35:
            return "unknown"
        return "neutral"

    def _context_trust(self, channel: str, bucket: str) -> float:
        channel_map = self.plan_trust_context.get(channel, {})
        return self._clamp(float(channel_map.get(bucket, 0.5) or 0.5), 0.0, 1.0)

    def _effective_channel_trust(self, channel: str, *, global_trust: float, bucket: str) -> float:
        context_trust = self._context_trust(channel, bucket)
        alpha = self._clamp(self.context_trust_blend_weight, 0.0, 0.8)
        return self._clamp(((1.0 - alpha) * global_trust) + (alpha * context_trust), 0.0, 1.0)

    def _outcome_label(
        self,
        *,
        progress_delta: int,
        reward_signal: float,
        penalty_signal: float,
        intervention_applied: bool,
        unresolved_override: bool,
    ) -> tuple[float, float]:
        progress_quality = 1.0 if int(progress_delta) > 0 else (0.45 if int(progress_delta) == 0 else 0.0)
        reward_minus_penalty = (float(reward_signal) - float(penalty_signal)) / 90.0
        reward_quality = self._sigmoid(reward_minus_penalty)
        penalty_relief = self._clamp(1.0 - (float(penalty_signal) / 24.0), 0.0, 1.0)
        outcome_quality = self._clamp(
            (0.46 * progress_quality) + (0.34 * reward_quality) + (0.20 * penalty_relief),
            0.0,
            1.0,
        )
        if bool(unresolved_override):
            outcome_quality = self._clamp(outcome_quality * 0.82, 0.0, 1.0)

        intervention_helpful = 0.5
        if intervention_applied:
            intervention_helpful = 1.0 if (progress_delta > 0 and reward_signal >= penalty_signal) else 0.0
            outcome_quality = self._clamp(
                (0.82 * outcome_quality) + (0.18 * intervention_helpful),
                0.0,
                1.0,
            )
        return (outcome_quality, intervention_helpful)

    def _smooth_strategy(self, candidate_strategy: str) -> str:
        token = str(candidate_strategy or "parallel_ensemble")
        if token == self.last_strategy:
            self.strategy_switch_stability_count = 0
            return token
        if self.step_count <= self.warmup_steps:
            self.last_strategy = token
            self.strategy_switch_stability_count = 0
            return token
        # Require two consecutive switch opportunities to prevent oscillation.
        self.strategy_switch_stability_count += 1
        if self.strategy_switch_stability_count < 2:
            return self.last_strategy
        self.last_strategy = token
        self.strategy_switch_stability_count = 0
        return token

    def _deliberative_score(self, candidate: dict[str, float]) -> float:
        unknown_pref = self._clamp(float(candidate.get("unknown_neighbors", 0.0)) / 4.0, 0.0, 1.0)
        frontier_gain_pref = self._clamp(float(candidate.get("frontier_gain", 0.0)), 0.0, 1.0)
        lookahead_pref = self._clamp(float(candidate.get("lookahead_norm", 0.0)), 0.0, 1.0)

        loop_penalty = self._clamp(float(candidate.get("loop_pressure_norm", 0.0)), 0.0, 1.0)
        hazard_penalty = self._clamp(float(candidate.get("hazard_pressure_norm", 0.0)), 0.0, 1.0)
        contradiction_penalty = self._clamp(float(candidate.get("contradiction_norm", 0.0)), 0.0, 1.0)

        score = (
            (self.deliberative_unknown_weight * unknown_pref)
            + (self.deliberative_frontier_weight * frontier_gain_pref)
            + (self.deliberative_lookahead_weight * lookahead_pref)
            - (self.deliberative_loop_penalty_weight * loop_penalty)
            - (self.deliberative_hazard_penalty_weight * hazard_penalty)
            - (self.deliberative_contradiction_penalty_weight * contradiction_penalty)
        )

        # Keep deliberative output in [0,1] while preserving ranking shape.
        return self._clamp(0.5 + (0.5 * score), 0.0, 1.0)

    def evaluate_candidates(
        self,
        candidates: list[dict[str, float | int | str]],
        *,
        profile: str | ReasoningProfile = ReasoningProfile.BALANCED,
        budget: ReasoningBudgetContract | None = None,
    ) -> dict[str, object]:
        if (not self.enabled) or (not candidates):
            self.last_result = {
                "enabled": 0,
                "selected_move": "",
                "strategy": "disabled",
                "confidence": 0.0,
                "confidence_margin": 0.0,
                "ranked": [],
                "pruned": {"reason": "engine_disabled_or_no_candidates", "discarded": 0},
            }
            return self.last_result

        try:
            profile_enum = ReasoningProfile(str(profile))
        except Exception:
            profile_enum = ReasoningProfile.BALANCED
        resolved_budget = self._resolve_budget(profile_enum, budget)

        pruned_summary: dict[str, object] = {"reason": "none", "discarded": 0, "discarded_moves": []}
        if len(candidates) > resolved_budget.max_branches:
            candidates_sorted = sorted(
                candidates,
                key=lambda row: float(row.get("local_score", 0.0) or 0.0),
            )
            discarded = candidates_sorted[resolved_budget.max_branches :]
            candidates = candidates_sorted[: resolved_budget.max_branches]
            pruned_summary = {
                "reason": "max_branches",
                "discarded": len(discarded),
                "discarded_moves": [str(row.get("move", "") or "") for row in discarded[:8]],
            }

        local_scores = [float(c.get("local_score", 0.0) or 0.0) for c in candidates]
        adaptive_scores = [float(c.get("adaptive_prediction", 0.0) or 0.0) for c in candidates]
        lookahead_scores = [float(c.get("prediction_lookahead_bonus", 0.0) or 0.0) for c in candidates]

        local_min = min(local_scores)
        local_max = max(local_scores)
        adaptive_min = min(adaptive_scores)
        adaptive_max = max(adaptive_scores)
        lookahead_min = min(lookahead_scores)
        lookahead_max = max(lookahead_scores)

        ranked: list[dict[str, float | str]] = []
        previous_margin = self._clamp(
            float(self.last_result.get("confidence_margin", 0.0) if self.last_result else 0.0),
            0.0,
            1.0,
        )
        trust_flatten = 1.0 - self._clamp(previous_margin / 0.18, 0.0, 1.0)

        for row in candidates:
            move = str(row.get("move", "") or "")
            local_score = float(row.get("local_score", 0.0) or 0.0)
            adaptive_prediction = float(row.get("adaptive_prediction", 0.0) or 0.0)
            lookahead_bonus = float(row.get("prediction_lookahead_bonus", 0.0) or 0.0)

            local_pref = 1.0 - self._normalize(local_score, local_min, local_max)
            adaptive_pref = self._normalize(adaptive_prediction, adaptive_min, adaptive_max)

            row_for_deliberation = {
                "unknown_neighbors": float(row.get("unknown_neighbors", 0.0) or 0.0),
                "frontier_gain": float(row.get("frontier_gain", 0.0) or 0.0),
                "lookahead_norm": self._normalize(lookahead_bonus, lookahead_min, lookahead_max),
                "loop_pressure_norm": float(row.get("loop_pressure_norm", 0.0) or 0.0),
                "hazard_pressure_norm": float(row.get("hazard_pressure_norm", 0.0) or 0.0),
                "contradiction_norm": float(row.get("contradiction_norm", 0.0) or 0.0),
            }
            deliberative_pref = self._deliberative_score(row_for_deliberation)
            context_bucket = self._context_bucket(row_for_deliberation)

            trust_local = self._effective_channel_trust(
                "local",
                global_trust=self.plan_trust_local,
                bucket=context_bucket,
            )
            trust_adaptive = self._effective_channel_trust(
                "adaptive",
                global_trust=self.plan_trust_adaptive,
                bucket=context_bucket,
            )
            trust_deliberative = self._effective_channel_trust(
                "deliberative",
                global_trust=self.plan_trust_deliberative,
                bucket=context_bucket,
            )
            trust_mean = (trust_local + trust_adaptive + trust_deliberative) / 3.0
            trust_local = self._clamp((trust_local * (1.0 - (0.45 * trust_flatten))) + (trust_mean * (0.45 * trust_flatten)), 0.0, 1.0)
            trust_adaptive = self._clamp((trust_adaptive * (1.0 - (0.45 * trust_flatten))) + (trust_mean * (0.45 * trust_flatten)), 0.0, 1.0)
            trust_deliberative = self._clamp((trust_deliberative * (1.0 - (0.45 * trust_flatten))) + (trust_mean * (0.45 * trust_flatten)), 0.0, 1.0)

            weight_local = self.local_weight * trust_local
            weight_adaptive = self.adaptive_weight * trust_adaptive
            weight_deliberative = self.deliberative_weight * trust_deliberative
            total_weight = weight_local + weight_adaptive + weight_deliberative
            if total_weight <= 1e-9:
                combined = local_pref
            else:
                combined = (
                    (local_pref * weight_local)
                    + (adaptive_pref * weight_adaptive)
                    + (deliberative_pref * weight_deliberative)
                ) / total_weight

            ranked.append(
                {
                    "move": move,
                    "local_score": local_score,
                    "local_pref": round(local_pref, 6),
                    "adaptive_pref": round(adaptive_pref, 6),
                    "deliberative_pref": round(deliberative_pref, 6),
                    "combined_pref": round(float(combined), 6),
                    "context_bucket": context_bucket,
                    "trust_local_effective": round(float(trust_local), 6),
                    "trust_adaptive_effective": round(float(trust_adaptive), 6),
                    "trust_deliberative_effective": round(float(trust_deliberative), 6),
                }
            )

        ranked.sort(
            key=lambda item: (
                -float(item.get("combined_pref", 0.0) or 0.0),
                float(item.get("local_score", 0.0) or 0.0),
                str(item.get("move", "") or ""),
            )
        )

        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else ranked[0]
        confidence_margin = max(
            0.0,
            float(best.get("combined_pref", 0.0) or 0.0) - float(second.get("combined_pref", 0.0) or 0.0),
        )
        confidence = self._clamp(
            (0.65 * float(best.get("combined_pref", 0.0) or 0.0)) + (0.35 * confidence_margin),
            0.0,
            1.0,
        )

        decay = self.ema_decay
        self.confidence_ema = (decay * self.confidence_ema) + ((1.0 - decay) * confidence)

        # Warmup: preserve baseline local policy while collecting learning signals.
        if self.step_count < self.warmup_steps:
            selected = min(ranked, key=lambda item: float(item.get("local_score", 0.0) or 0.0))
            strategy = "warmup_local"
        elif confidence < self.min_confidence:
            # Low-confidence arbitration: bias toward information gain, but keep local cost in the loop.
            selected = max(
                ranked,
                key=lambda item: (
                    (0.6 * float(item.get("deliberative_pref", 0.0) or 0.0))
                    + (0.4 * float(item.get("local_pref", 0.0) or 0.0))
                ),
            )
            strategy = "low_confidence_probe"
        else:
            selected = best
            strategy = "parallel_ensemble"

        strategy = self._smooth_strategy(strategy)
        if strategy == "parallel_ensemble":
            selected = best
        elif strategy == "low_confidence_probe":
            selected = max(
                ranked,
                key=lambda item: (
                    (0.6 * float(item.get("deliberative_pref", 0.0) or 0.0))
                    + (0.4 * float(item.get("local_pref", 0.0) or 0.0))
                ),
            )
        elif strategy == "warmup_local":
            selected = min(ranked, key=lambda item: float(item.get("local_score", 0.0) or 0.0))

        self.last_result = {
            "enabled": 1,
            "selected_move": str(selected.get("move", "") or ""),
            "strategy": strategy,
            "confidence": round(confidence, 6),
            "confidence_margin": round(confidence_margin, 6),
            "ranked": ranked[:4],
            "plan_trust_local": round(self.plan_trust_local, 6),
            "plan_trust_adaptive": round(self.plan_trust_adaptive, 6),
            "plan_trust_deliberative": round(self.plan_trust_deliberative, 6),
            "confidence_ema": round(self.confidence_ema, 6),
            "context_bucket": str(selected.get("context_bucket", "neutral") or "neutral"),
            "context_trust_blend_weight": round(float(self.context_trust_blend_weight), 4),
            "step_count": int(self.step_count),
            "reasoning_profile": profile_enum.value,
            "budget": {
                "max_branches": int(resolved_budget.max_branches),
                "max_depth": int(resolved_budget.max_depth),
                "time_budget_ms": int(resolved_budget.time_budget_ms),
                "token_budget": int(resolved_budget.token_budget),
            },
            "pruned": pruned_summary,
        }
        return self.last_result

    def observe_feedback(
        self,
        *,
        selected_move: str,
        progress_delta: int,
        reward_signal: float,
        penalty_signal: float,
        intervention_applied: bool = False,
        unresolved_override: bool = False,
        context_bucket_hint: str = "",
    ) -> None:
        if (not self.enabled) or (not self.last_result):
            return

        ranked = self.last_result.get("ranked", [])
        if not isinstance(ranked, list) or not ranked:
            return

        chosen = None
        for row in ranked:
            if str(row.get("move", "") or "") == str(selected_move or ""):
                chosen = row
                break
        if chosen is None:
            return

        self.step_count += 1
        decay = self.ema_decay

        outcome_quality, intervention_helpful = self._outcome_label(
            progress_delta=int(progress_delta),
            reward_signal=float(reward_signal),
            penalty_signal=float(penalty_signal),
            intervention_applied=bool(intervention_applied),
            unresolved_override=bool(unresolved_override),
        )
        self.utility_ema = (decay * self.utility_ema) + ((1.0 - decay) * outcome_quality)
        self.outcome_quality_ema = (decay * self.outcome_quality_ema) + ((1.0 - decay) * outcome_quality)
        self.intervention_helpfulness_ema = (decay * self.intervention_helpfulness_ema) + ((1.0 - decay) * intervention_helpful)

        local_pred = float(chosen.get("local_pref", 0.0) or 0.0)
        adaptive_pred = float(chosen.get("adaptive_pref", 0.0) or 0.0)
        deliberative_pred = float(chosen.get("deliberative_pref", 0.0) or 0.0)

        # Brier-style calibration scoring drives trust updates.
        local_accuracy = self._clamp(1.0 - ((outcome_quality - local_pred) ** 2), 0.0, 1.0)
        adaptive_accuracy = self._clamp(1.0 - ((outcome_quality - adaptive_pred) ** 2), 0.0, 1.0)
        deliberative_accuracy = self._clamp(1.0 - ((outcome_quality - deliberative_pred) ** 2), 0.0, 1.0)

        self.plan_trust_local = (decay * self.plan_trust_local) + ((1.0 - decay) * local_accuracy)
        self.plan_trust_adaptive = (decay * self.plan_trust_adaptive) + ((1.0 - decay) * adaptive_accuracy)
        self.plan_trust_deliberative = (decay * self.plan_trust_deliberative) + ((1.0 - decay) * deliberative_accuracy)

        bucket = str(context_bucket_hint or chosen.get("context_bucket", "neutral") or "neutral").strip().lower()
        if bucket not in self._CONTEXT_BUCKETS:
            bucket = "neutral"
        self.context_bucket_counts[bucket] = int(self.context_bucket_counts.get(bucket, 0) or 0) + 1
        self.plan_trust_context["local"][bucket] = (decay * self._context_trust("local", bucket)) + ((1.0 - decay) * local_accuracy)
        self.plan_trust_context["adaptive"][bucket] = (decay * self._context_trust("adaptive", bucket)) + ((1.0 - decay) * adaptive_accuracy)
        self.plan_trust_context["deliberative"][bucket] = (decay * self._context_trust("deliberative", bucket)) + ((1.0 - decay) * deliberative_accuracy)

    def snapshot(self) -> dict[str, object]:
        context_bucket_mean_trust: dict[str, float] = {}
        for bucket in self._CONTEXT_BUCKETS:
            mean_trust = (
                self._context_trust("local", bucket)
                + self._context_trust("adaptive", bucket)
                + self._context_trust("deliberative", bucket)
            ) / 3.0
            context_bucket_mean_trust[bucket] = round(float(mean_trust), 4)

        return {
            "enabled": 1 if self.enabled else 0,
            "step_count": int(self.step_count),
            "plan_trust_local": round(float(self.plan_trust_local), 4),
            "plan_trust_adaptive": round(float(self.plan_trust_adaptive), 4),
            "plan_trust_deliberative": round(float(self.plan_trust_deliberative), 4),
            "confidence_ema": round(float(self.confidence_ema), 4),
            "utility_ema": round(float(self.utility_ema), 4),
            "outcome_quality_ema": round(float(self.outcome_quality_ema), 4),
            "intervention_helpfulness_ema": round(float(self.intervention_helpfulness_ema), 4),
            "context_trust_blend_weight": round(float(self.context_trust_blend_weight), 4),
            "context_bucket_trust": context_bucket_mean_trust,
            "context_bucket_counts": dict(self.context_bucket_counts),
            "last_confidence": round(float(self.last_result.get("confidence", 0.0) if self.last_result else 0.0), 4),
            "last_confidence_margin": round(
                float(self.last_result.get("confidence_margin", 0.0) if self.last_result else 0.0),
                4,
            ),
        }
