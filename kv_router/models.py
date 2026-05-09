from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class GenerateRequest(BaseModel):
    """Incoming generation request for the router."""

    prompt: str = Field(..., min_length=1)
    max_tokens: int = Field(..., gt=0, le=8192)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    stream: bool = Field(False)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("prompt must not be empty or whitespace only")
        return stripped


class NodeMetrics(BaseModel):
    kv_used_mb: int = 0
    kv_capacity_mb: int = 0
    active_requests: int = 0


class NodeInfo(BaseModel):
    url: str
    metrics: NodeMetrics
    last_updated_ts: Optional[float] = None
    last_error: Optional[str] = None
    healthy: bool = False
    stale: bool = True


class RoutingWeights(BaseModel):
    alpha: float = 1.0
    beta: float = 0.2
    gamma: float = 0.8
    delta: float = 2.0


class RoutingBreakdown(BaseModel):
    node_url: str
    free_kv_ratio: float
    cache_pressure: float
    load_ratio: float
    uncertainty: float
    stale_penalty: float
    score: float
    healthy: bool
    stale: bool


class GenerateResponse(BaseModel):
    request_id: str
    selected_node: str
    tried_nodes: List[str]
    uncertainty: float
    routing_scores: List[RoutingBreakdown]
    router_metrics: Dict[str, Any]
    upstream_response: Dict[str, Any]