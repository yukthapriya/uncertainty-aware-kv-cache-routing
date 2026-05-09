from __future__ import annotations

import hashlib
from itertools import count

from kv_router.models import NodeState, RoutingScoreBreakdown, RoutingWeights

_round_robin_counter = count()


def next_round_robin_index(num_nodes: int) -> int:
    return next(_round_robin_counter) % max(1, num_nodes)


def compute_prefix_affinity(prompt: str, session_id: str | None, node_url: str) -> float:
    key = (session_id or prompt[:32]).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    slot = int(digest[:8], 16) % 3
    node_slot = sum(ord(c) for c in node_url) % 3
    return 1.0 if slot == node_slot else 0.0


def score_kv_aware(
    node: NodeState,
    uncertainty: float,
    weights: RoutingWeights,
    max_active_requests: int,
    prompt: str,
    session_id: str | None,
) -> RoutingScoreBreakdown:
    if not node.metrics:
        return RoutingScoreBreakdown(
            node_url=node.url,
            free_kv_ratio=0.0,
            cache_pressure=1.0,
            load_ratio=1.0,
            uncertainty=uncertainty,
            stale_penalty=1.0,
            score=-9999.0,
            healthy=node.healthy,
            stale=node.stale,
        )

    capacity = max(1, node.metrics.kv_capacity_mb)
    used = max(0, min(node.metrics.kv_used_mb, capacity))

    free_kv_ratio = (capacity - used) / capacity
    cache_pressure = used / capacity
    load_ratio = min(1.0, node.metrics.active_requests / max(1, max_active_requests))
    stale_penalty = 1.0 if node.stale else 0.0
    prefix_affinity = compute_prefix_affinity(prompt, session_id, node.url)

    score = (
        0.5 * prefix_affinity
        + weights.alpha * free_kv_ratio
        - weights.beta * load_ratio
        - weights.gamma * uncertainty * cache_pressure
        - weights.delta * stale_penalty
    )

    return RoutingScoreBreakdown(
        node_url=node.url,
        free_kv_ratio=free_kv_ratio,
        cache_pressure=cache_pressure,
        load_ratio=load_ratio,
        uncertainty=uncertainty,
        stale_penalty=stale_penalty,
        score=score,
        healthy=node.healthy,
        stale=node.stale,
    )


def score_least_loaded(node: NodeState, max_active_requests: int, uncertainty: float) -> RoutingScoreBreakdown:
    if not node.metrics:
        return RoutingScoreBreakdown(
            node_url=node.url,
            free_kv_ratio=0.0,
            cache_pressure=1.0,
            load_ratio=1.0,
            uncertainty=uncertainty,
            stale_penalty=1.0,
            score=-9999.0,
            healthy=node.healthy,
            stale=node.stale,
        )

    capacity = max(1, node.metrics.kv_capacity_mb)
    used = max(0, min(node.metrics.kv_used_mb, capacity))
    free_kv_ratio = (capacity - used) / capacity
    cache_pressure = used / capacity
    load_ratio = min(1.0, node.metrics.active_requests / max(1, max_active_requests))
    stale_penalty = 1.0 if node.stale else 0.0
    score = -load_ratio - stale_penalty

    return RoutingScoreBreakdown(
        node_url=node.url,
        free_kv_ratio=free_kv_ratio,
        cache_pressure=cache_pressure,
        load_ratio=load_ratio,
        uncertainty=uncertainty,
        stale_penalty=stale_penalty,
        score=score,
        healthy=node.healthy,
        stale=node.stale,
    )


def score_round_robin(
    node: NodeState,
    ordered_nodes: list[NodeState],
    chosen_index: int,
    uncertainty: float,
) -> RoutingScoreBreakdown:
    idx = ordered_nodes.index(node)
    base = 1.0 if idx == chosen_index else 0.0

    free_kv_ratio = 0.0
    cache_pressure = 1.0
    load_ratio = 1.0
    stale_penalty = 1.0 if node.stale else 0.0

    if node.metrics:
        capacity = max(1, node.metrics.kv_capacity_mb)
        used = max(0, min(node.metrics.kv_used_mb, capacity))
        free_kv_ratio = (capacity - used) / capacity
        cache_pressure = used / capacity
        load_ratio = node.metrics.active_requests / max(1, node.metrics.active_requests + 1)

    score = base - stale_penalty
    return RoutingScoreBreakdown(
        node_url=node.url,
        free_kv_ratio=free_kv_ratio,
        cache_pressure=cache_pressure,
        load_ratio=load_ratio,
        uncertainty=uncertainty,
        stale_penalty=stale_penalty,
        score=score,
        healthy=node.healthy,
        stale=node.stale,
    )