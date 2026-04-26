import json
import math
import os
import random
from typing import Any


class AdaptiveNeuralController:
    """
    Lightweight online learner with semi-biological growth/pruning.

    - Single hidden-layer tanh network
    - Online SGD updates from immediate outcomes
    - Growth when sustained prediction error is high
    - Pruning of weak units to keep the network compact
    - JSON persistence to carry learning across sessions/tasks
    """

    def __init__(
        self,
        *,
        input_dim: int,
        state_path: str,
        seed: int = 1337,
        hidden_min: int = 16,
        hidden_max: int = 128,
        growth_step: int = 4,
        growth_patience: int = 120,
        growth_error_threshold: float = 0.22,
        prune_interval: int = 500,
        prune_importance_threshold: float = 0.008,
        learning_rate: float = 0.018,
        l2: float = 0.0008,
    ) -> None:
        self.input_dim = max(4, int(input_dim))
        self.state_path = str(state_path)
        self.rng = random.Random(int(seed))

        self.hidden_min = max(4, int(hidden_min))
        self.hidden_max = max(self.hidden_min, int(hidden_max))
        self.growth_step = max(1, int(growth_step))
        self.growth_patience = max(20, int(growth_patience))
        self.growth_error_threshold = max(0.02, float(growth_error_threshold))
        self.prune_interval = max(50, int(prune_interval))
        self.prune_importance_threshold = max(0.0, float(prune_importance_threshold))
        self.learning_rate = max(1e-5, float(learning_rate))
        self.l2 = max(0.0, float(l2))

        self.w1: list[list[float]] = []
        self.b1: list[float] = []
        self.w2: list[float] = []
        self.b2: float = 0.0

        self.steps = 0
        self.last_growth_step = 0
        self.last_prune_step = 0
        self.error_ema = 0.0

        self._init_network(self.hidden_min)
        self._load_state_if_present()

    def _rand_weight(self, scale: float = 0.16) -> float:
        return self.rng.uniform(-scale, scale)

    def _init_network(self, hidden_units: int) -> None:
        self.w1 = []
        self.b1 = []
        self.w2 = []
        self.b2 = 0.0
        for _ in range(max(1, int(hidden_units))):
            row = [self._rand_weight(scale=0.12) for _ in range(self.input_dim)]
            self.w1.append(row)
            self.b1.append(self._rand_weight(scale=0.02))
            self.w2.append(self._rand_weight(scale=0.08))

    def _as_feature_vector(self, features: list[float]) -> list[float]:
        vals = [float(v) for v in (features or [])]
        if len(vals) < self.input_dim:
            vals.extend([0.0] * (self.input_dim - len(vals)))
        elif len(vals) > self.input_dim:
            vals = vals[: self.input_dim]
        return vals

    def _forward(self, features: list[float]) -> tuple[list[float], float]:
        x = self._as_feature_vector(features)
        hidden: list[float] = []
        for i, row in enumerate(self.w1):
            z = self.b1[i]
            for j, w in enumerate(row):
                z += w * x[j]
            hidden.append(math.tanh(z))
        y = self.b2
        for i, h in enumerate(hidden):
            y += self.w2[i] * h
        return hidden, y

    def predict(self, features: list[float]) -> float:
        _hidden, y = self._forward(features)
        return math.tanh(y)

    def learn(self, features: list[float], target: float) -> dict[str, Any]:
        x = self._as_feature_vector(features)
        target_val = max(-1.0, min(1.0, float(target)))

        hidden, y = self._forward(x)
        pred = math.tanh(y)
        error = pred - target_val

        dloss_dpred = 2.0 * error
        dpred_dy = 1.0 - (pred * pred)
        delta_out = dloss_dpred * dpred_dy

        lr = self.learning_rate

        for i in range(len(self.w2)):
            grad_w2 = delta_out * hidden[i] + (self.l2 * self.w2[i])
            self.w2[i] -= lr * grad_w2

        self.b2 -= lr * delta_out

        for i in range(len(self.w1)):
            dz_dnet = 1.0 - (hidden[i] * hidden[i])
            hidden_delta = delta_out * self.w2[i] * dz_dnet
            for j in range(self.input_dim):
                grad_w1 = hidden_delta * x[j] + (self.l2 * self.w1[i][j])
                self.w1[i][j] -= lr * grad_w1
            self.b1[i] -= lr * hidden_delta

        abs_error = abs(error)
        self.error_ema = (0.96 * self.error_ema) + (0.04 * abs_error)
        self.steps += 1

        grew = self._maybe_grow(x)
        pruned = self._maybe_prune()

        return {
            "pred": pred,
            "target": target_val,
            "error": error,
            "error_ema": self.error_ema,
            "hidden_units": len(self.w1),
            "grew": grew,
            "pruned": pruned,
        }

    def _maybe_grow(self, features: list[float]) -> bool:
        if len(self.w1) >= self.hidden_max:
            return False
        if self.steps < self.growth_patience:
            return False
        if (self.steps - self.last_growth_step) < (self.growth_patience // 2):
            return False
        if self.error_ema < self.growth_error_threshold:
            return False

        growth = min(self.growth_step, self.hidden_max - len(self.w1))
        if growth <= 0:
            return False

        indexed = [(idx, abs(val)) for idx, val in enumerate(features)]
        indexed.sort(key=lambda item: item[1], reverse=True)
        salient = [idx for idx, _mag in indexed[: min(5, len(indexed))]]

        for _ in range(growth):
            row = [self._rand_weight(scale=0.08) for _ in range(self.input_dim)]
            for idx in salient:
                direction = 1.0 if features[idx] >= 0.0 else -1.0
                row[idx] += direction * self.rng.uniform(0.04, 0.12)
            self.w1.append(row)
            self.b1.append(self._rand_weight(scale=0.03))
            self.w2.append(self._rand_weight(scale=0.1))

        self.last_growth_step = self.steps
        return True

    def _unit_importance(self, idx: int) -> float:
        row = self.w1[idx]
        mean_abs_in = sum(abs(v) for v in row) / max(1, len(row))
        return abs(self.w2[idx]) + (0.18 * mean_abs_in)

    def _maybe_prune(self) -> bool:
        if self.steps < self.prune_interval:
            return False
        if (self.steps - self.last_prune_step) < self.prune_interval:
            return False
        if len(self.w1) <= self.hidden_min:
            return False

        scored = [(i, self._unit_importance(i)) for i in range(len(self.w1))]
        scored.sort(key=lambda item: item[1])

        removable = len(self.w1) - self.hidden_min
        to_remove: list[int] = []
        for i, importance in scored:
            if importance >= self.prune_importance_threshold:
                break
            to_remove.append(i)
            if len(to_remove) >= removable:
                break

        if not to_remove:
            self.last_prune_step = self.steps
            return False

        remove_set = set(to_remove)
        self.w1 = [row for i, row in enumerate(self.w1) if i not in remove_set]
        self.b1 = [val for i, val in enumerate(self.b1) if i not in remove_set]
        self.w2 = [val for i, val in enumerate(self.w2) if i not in remove_set]

        self.last_prune_step = self.steps
        return True

    def stats(self) -> dict[str, Any]:
        return {
            "input_dim": self.input_dim,
            "hidden_units": len(self.w1),
            "steps": self.steps,
            "error_ema": round(self.error_ema, 6),
            "growth_threshold": self.growth_error_threshold,
        }

    def weight_snapshot(self, top_k: int = 6) -> dict[str, Any]:
        if not self.w1 or not self.w2:
            return {
                "hidden_units": 0,
                "mean_abs_w1": 0.0,
                "mean_abs_w2": 0.0,
                "max_abs_w2": 0.0,
                "top_input_importance": [],
                "output_head_sample": [],
            }

        hidden_units = len(self.w1)
        abs_w1_sum = 0.0
        abs_w1_count = 0
        abs_w2_values = [abs(float(v)) for v in self.w2]

        weighted_input_importance = [0.0 for _ in range(self.input_dim)]
        for i, row in enumerate(self.w1):
            out_mag = abs_w2_values[i] if i < len(abs_w2_values) else 0.0
            for j, value in enumerate(row):
                mag = abs(float(value))
                abs_w1_sum += mag
                abs_w1_count += 1
                if j < len(weighted_input_importance):
                    weighted_input_importance[j] += mag * (1.0 + out_mag)

        ranked_inputs = sorted(
            [(idx, score) for idx, score in enumerate(weighted_input_importance)],
            key=lambda item: item[1],
            reverse=True,
        )
        top_input_rows = [
            {"index": int(idx), "importance": round(float(score), 6)}
            for idx, score in ranked_inputs[: max(1, int(top_k))]
        ]

        output_head_sample = [round(float(v), 6) for v in self.w2[: max(1, min(10, int(top_k) + 2))]]
        return {
            "hidden_units": hidden_units,
            "mean_abs_w1": round(abs_w1_sum / max(1, abs_w1_count), 6),
            "mean_abs_w2": round(sum(abs_w2_values) / max(1, len(abs_w2_values)), 6),
            "max_abs_w2": round(max(abs_w2_values), 6),
            "top_input_importance": top_input_rows,
            "output_head_sample": output_head_sample,
        }

    def save_state(self) -> None:
        payload = {
            "version": 1,
            "input_dim": self.input_dim,
            "w1": self.w1,
            "b1": self.b1,
            "w2": self.w2,
            "b2": self.b2,
            "steps": self.steps,
            "last_growth_step": self.last_growth_step,
            "last_prune_step": self.last_prune_step,
            "error_ema": self.error_ema,
            "hidden_min": self.hidden_min,
            "hidden_max": self.hidden_max,
        }
        directory = os.path.dirname(self.state_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _load_state_if_present(self) -> None:
        if not self.state_path or (not os.path.exists(self.state_path)):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if int(payload.get("input_dim", -1)) != self.input_dim:
                return
            w1 = payload.get("w1")
            b1 = payload.get("b1")
            w2 = payload.get("w2")
            b2 = payload.get("b2")
            if not isinstance(w1, list) or not isinstance(b1, list) or not isinstance(w2, list):
                return
            if len(w1) != len(b1) or len(w1) != len(w2) or len(w1) < 1:
                return
            for row in w1:
                if not isinstance(row, list) or len(row) != self.input_dim:
                    return

            self.w1 = [[float(v) for v in row] for row in w1]
            self.b1 = [float(v) for v in b1]
            self.w2 = [float(v) for v in w2]
            self.b2 = float(b2 or 0.0)

            self.steps = int(payload.get("steps", 0) or 0)
            self.last_growth_step = int(payload.get("last_growth_step", 0) or 0)
            self.last_prune_step = int(payload.get("last_prune_step", 0) or 0)
            self.error_ema = float(payload.get("error_ema", 0.0) or 0.0)
        except Exception:
            # Keep default initialized network on any load failure.
            return
