from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Protocol, Any


_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def simple_tokenize(text: str) -> List[str]:
    if not text:
        return []
    return _TOKEN_PATTERN.findall(text)


def extract_features(prompt: str, temperature: float) -> Dict[str, float]:
    tokens = simple_tokenize(prompt)
    token_count = len(tokens)

    if token_count == 0:
        rare_token_ratio = 0.0
        punctuation_ratio = 0.0
        long_token_ratio = 0.0
    else:
        rare_like_tokens = [
            t for t in tokens
            if (
                any(ch.isdigit() for ch in t)
                or "_" in t
                or len(t) > 12
                or not t.isascii()
                or any(ch in "{}[]()<>=/*+-_" for ch in t)
            )
        ]
        punctuation_like = [t for t in tokens if len(t) == 1 and not t.isalnum()]
        long_tokens = [t for t in tokens if len(t) >= 10]

        rare_token_ratio = len(rare_like_tokens) / token_count
        punctuation_ratio = len(punctuation_like) / token_count
        long_token_ratio = len(long_tokens) / token_count

    prompt_length_chars = len(prompt)
    normalized_length = min(prompt_length_chars / 4000.0, 1.0)
    normalized_temperature = clamp01(temperature / 2.0)

    return {
        "prompt_length_chars": float(prompt_length_chars),
        "token_count": float(token_count),
        "normalized_length": normalized_length,
        "normalized_temperature": normalized_temperature,
        "rare_token_ratio": rare_token_ratio,
        "punctuation_ratio": punctuation_ratio,
        "long_token_ratio": long_token_ratio,
    }


class UncertaintyEstimator(Protocol):
    def estimate(self, prompt: str, temperature: float) -> float:
        ...


@dataclass
class HeuristicUncertaintyEstimator:
    length_weight: float = 0.35
    temperature_weight: float = 0.35
    rare_token_weight: float = 0.20
    punctuation_weight: float = 0.05
    long_token_weight: float = 0.05

    def estimate(self, prompt: str, temperature: float) -> float:
        features = extract_features(prompt, temperature)
        score = (
            self.length_weight * features["normalized_length"]
            + self.temperature_weight * features["normalized_temperature"]
            + self.rare_token_weight * features["rare_token_ratio"]
            + self.punctuation_weight * features["punctuation_ratio"]
            + self.long_token_weight * features["long_token_ratio"]
        )
        return clamp01(score)


@dataclass
class LogisticRegressionUncertaintyEstimator:
    bias: float
    coefficients: Dict[str, float]

    def estimate(self, prompt: str, temperature: float) -> float:
        features = extract_features(prompt, temperature)
        logit = self.bias
        for feature_name, feature_value in features.items():
            logit += self.coefficients.get(feature_name, 0.0) * feature_value
        probability = 1.0 / (1.0 + math.exp(-logit))
        return clamp01(probability)


def build_uncertainty_estimator(config: Dict[str, Any]) -> UncertaintyEstimator:
    estimator_type = str(config.get("type", "heuristic")).strip().lower()
    params = config.get("params", {}) or {}

    if estimator_type == "heuristic":
        return HeuristicUncertaintyEstimator(
            length_weight=float(params.get("length_weight", 0.35)),
            temperature_weight=float(params.get("temperature_weight", 0.35)),
            rare_token_weight=float(params.get("rare_token_weight", 0.20)),
            punctuation_weight=float(params.get("punctuation_weight", 0.05)),
            long_token_weight=float(params.get("long_token_weight", 0.05)),
        )

    if estimator_type in {"logistic", "logistic_regression"}:
        return LogisticRegressionUncertaintyEstimator(
            bias=float(params.get("bias", -1.0)),
            coefficients={
                str(k): float(v)
                for k, v in (params.get("coefficients", {}) or {}).items()
            },
        )

    raise ValueError(f"Unsupported uncertainty estimator type: {estimator_type!r}")