from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RoutingStrategy = Literal["kv_aware", "least_loaded", "round_robin"]


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 64
    temperature: float = 0.8
    stream: bool = False
    session_id: str | None = None
    routing_strategy: RoutingStrategy = "kv_aware"


class NodeMetrics(BaseModel):
    kv_used_mb: int
    kv_capacity_mb: int
    active_requests: int


class NodeState(BaseModel):
    url: str
    metrics: NodeMetrics | None = None
    last_updated_ts: float | None = None
    last_error: str | None = None
    healthy: bool = False
    stale: bool = True


class RoutingWeights(BaseModel):
    alpha: float = 1.0
    beta: float = 0.25
    gamma: float = 1.0
    delta: float = 2.0


class RoutingScoreBreakdown(BaseModel):
    node_url: str
    free_kv_ratio: float
    cache_pressure: float
    load_ratio: float
    uncertainty: float
    stale_penalty: float
    score: float
    healthy: bool
    stale: bool


class RustScorerNodeInput(BaseModel):
    node_url: str
    kv_used_mb: int
    kv_capacity_mb: int
    active_requests: int
    healthy: bool
    stale: bool


class RustScorerRequest(BaseModel):
    uncertainty: float
    max_active_requests: int
    weights: RoutingWeights
    nodes: list[RustScorerNodeInput]


class RustScorerResponse(BaseModel):
    ranked_nodes: list[RoutingScoreBreakdown]


class RouterMetricsSnapshot(BaseModel):
    uptime_seconds: float
    requests_total: int
    requests_failed: int
    fallbacks_total: int
    selected_per_node: dict[str, int]
    avg_uncertainty: float
    avg_router_latency_ms: float
    avg_upstream_latency_ms: float


class GenerateResponse(BaseModel):
    request_id: str
    selected_node: str
    tried_nodes: list[str]
    uncertainty: float
    routing_scores: list[RoutingScoreBreakdown]
    router_metrics: RouterMetricsSnapshot
    upstream_response: dict[str, Any] = Field(default_factory=dict)