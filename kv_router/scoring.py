from __future__ import annotations

from typing import Any, Dict

from kv_router.models import RoutingBreakdown, RoutingWeights


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_free_kv_ratio(kv_used_mb: int, kv_capacity_mb: int) -> float:
    if kv_capacity_mb <= 0:
        return 0.0
    used = max(0, min(kv_used_mb, kv_capacity_mb))
    return (kv_capacity_mb - used) / kv_capacity_mb


def compute_cache_pressure(kv_used_mb: int, kv_capacity_mb: int) -> float:
    if kv_capacity_mb <= 0:
        return 1.0
    used = max(0, min(kv_used_mb, kv_capacity_mb))
    return used / kv_capacity_mb


def compute_load_ratio(active_requests: int, max_active_requests: int) -> float:
    if max_active_requests <= 0:
        return float(active_requests)
    return clamp01(active_requests / max_active_requests)


def build_score_breakdown(
    *,
    node_url: str,
    metrics: Dict[str, Any],
    uncertainty: float,
    weights: RoutingWeights,
    max_active_requests: int,
    stale: bool,
    healthy: bool,
) -> RoutingBreakdown:
    kv_used_mb = int(metrics.get("kv_used_mb", 0))
    kv_capacity_mb = int(metrics.get("kv_capacity_mb", 0))
    active_requests = int(metrics.get("active_requests", 0))

    free_kv_ratio = compute_free_kv_ratio(kv_used_mb, kv_capacity_mb)
    cache_pressure = compute_cache_pressure(kv_used_mb, kv_capacity_mb)
    load_ratio = compute_load_ratio(active_requests, max_active_requests)
    stale_penalty = 1.0 if stale else 0.0

    score = (
        weights.alpha * free_kv_ratio
        - weights.beta * load_ratio
        - weights.gamma * uncertainty * cache_pressure
        - weights.delta * stale_penalty
    )

    return RoutingBreakdown(
        node_url=node_url,
        free_kv_ratio=free_kv_ratio,
        cache_pressure=cache_pressure,
        load_ratio=load_ratio,
        uncertainty=float(uncertainty),
        stale_penalty=stale_penalty,
        score=score,
        healthy=healthy,
        stale=stale,
    )