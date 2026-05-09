from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod


class BaseUncertaintyEstimator(ABC):
    @abstractmethod
    def estimate(self, prompt: str, temperature: float) -> float:
        raise NotImplementedError


class HeuristicUncertaintyEstimator(BaseUncertaintyEstimator):
    def __init__(
        self,
        length_weight: float = 0.35,
        temperature_weight: float = 0.35,
        rare_token_weight: float = 0.20,
        punctuation_weight: float = 0.05,
        long_token_weight: float = 0.05,
    ) -> None:
        self.length_weight = length_weight
        self.temperature_weight = temperature_weight
        self.rare_token_weight = rare_token_weight
        self.punctuation_weight = punctuation_weight
        self.long_token_weight = long_token_weight

    def estimate(self, prompt: str, temperature: float) -> float:
        tokens = prompt.split()
        token_count = max(1, len(tokens))
        long_tokens = [t for t in tokens if len(t) >= 10]
        punctuation_count = len(re.findall(r"[,:;!?()\-]", prompt))
        rare_like = [t for t in tokens if any(ch.isdigit() for ch in t) or "/" in t or "_" in t]

        length_feature = min(1.0, token_count / 64.0)
        temperature_feature = min(1.0, max(0.0, temperature))
        rare_feature = min(1.0, len(rare_like) / token_count)
        punctuation_feature = min(1.0, punctuation_count / max(1, len(prompt)))
        long_token_feature = min(1.0, len(long_tokens) / token_count)

        score = (
            self.length_weight * length_feature
            + self.temperature_weight * temperature_feature
            + self.rare_token_weight * rare_feature
            + self.punctuation_weight * punctuation_feature
            + self.long_token_weight * long_token_feature
        )
        return round(max(0.0, min(1.0, score)), 6)


class LogisticUncertaintyEstimator(BaseUncertaintyEstimator):
    def __init__(self, bias: float = -1.0, w_len: float = 1.0, w_temp: float = 1.0, w_rare: float = 0.5) -> None:
        self.bias = bias
        self.w_len = w_len
        self.w_temp = w_temp
        self.w_rare = w_rare

    def estimate(self, prompt: str, temperature: float) -> float:
        tokens = prompt.split()
        token_count = max(1, len(tokens))
        rare_like = [t for t in tokens if any(ch.isdigit() for ch in t) or "/" in t or "_" in t]

        x = (
            self.bias
            + self.w_len * min(1.0, token_count / 64.0)
            + self.w_temp * min(1.0, max(0.0, temperature))
            + self.w_rare * min(1.0, len(rare_like) / token_count)
        )
        p = 1.0 / (1.0 + math.exp(-x))
        return round(max(0.0, min(1.0, p)), 6)


def build_uncertainty_estimator(config: dict) -> BaseUncertaintyEstimator:
    estimator_cfg = config.get("uncertainty_estimator", {})
    estimator_type = estimator_cfg.get("type", "heuristic")
    params = estimator_cfg.get("params", {})

    if estimator_type == "logistic":
        return LogisticUncertaintyEstimator(**params)
    return HeuristicUncertaintyEstimator(**params)