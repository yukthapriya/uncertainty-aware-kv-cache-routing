from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException

from kv_router.logging_utils import configure_logging
from kv_router.metrics import RouterMetrics
from kv_router.models import (
    GenerateRequest,
    GenerateResponse,
    NodeInfo,
    RoutingBreakdown,
    RoutingWeights,
)
from kv_router.node_registry import NodeRegistry
from kv_router.scoring import build_score_breakdown
from kv_router.uncertainty import UncertaintyEstimator, build_uncertainty_estimator

import logging

configure_logging()
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class RouterState:
    def __init__(
        self,
        *,
        registry: NodeRegistry,
        estimator: UncertaintyEstimator,
        weights: RoutingWeights,
        forward_timeout_s: float,
        vllm_generate_path: str,
        max_active_requests: int,
        router_metrics: RouterMetrics,
    ) -> None:
        self.registry = registry
        self.estimator = estimator
        self.weights = weights
        self.forward_timeout_s = forward_timeout_s
        self.vllm_generate_path = vllm_generate_path
        self.max_active_requests = max_active_requests
        self.router_metrics = router_metrics
        self.last_metrics: List[Dict[str, Any]] = []


def load_router_settings(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_app(config_path: Path = CONFIG_PATH) -> FastAPI:
    config = load_router_settings(config_path)

    registry = NodeRegistry(
        config_path=config_path,
        request_timeout_s=float(
            (config.get("timeouts", {}) or {}).get("metrics_request_timeout_s", 2.0)
        ),
    )

    uncertainty_config = config.get("uncertainty_estimator", {}) or {}
    estimator = build_uncertainty_estimator(uncertainty_config)

    scoring_config = config.get("scoring", {}) or {}
    weights = RoutingWeights(
        alpha=float(scoring_config.get("alpha", 1.0)),
        beta=float(scoring_config.get("beta", 0.2)),
        gamma=float(scoring_config.get("gamma", 0.8)),
        delta=float(scoring_config.get("delta", 2.0)),
    )

    router_config = config.get("router", {}) or {}
    forward_timeout_s = float(
        (config.get("timeouts", {}) or {}).get("forward_request_timeout_s", 60.0)
    )
    vllm_generate_path = str(router_config.get("vllm_generate_path", "/generate"))
    max_active_requests = int(router_config.get("max_active_requests", 16))

    state = RouterState(
        registry=registry,
        estimator=estimator,
        weights=weights,
        forward_timeout_s=forward_timeout_s,
        vllm_generate_path=vllm_generate_path,
        max_active_requests=max_active_requests,
        router_metrics=RouterMetrics(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await state.registry.start()
        await state.registry.refresh_all()
        state.last_metrics = [n.model_dump() for n in await state.registry.get_nodes()]
        try:
            yield
        finally:
            await state.registry.stop()

    app = FastAPI(
        title="Uncertainty-Aware KV-Cache Router",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.router_state = state

    async def rank_nodes(uncertainty: float) -> List[RoutingBreakdown]:
        await state.registry.refresh_all()
        nodes = await state.registry.get_nodes()
        state.last_metrics = [n.model_dump() for n in nodes]

        ranked: List[RoutingBreakdown] = []
        for node in nodes:
            breakdown = build_score_breakdown(
                node_url=node.url,
                metrics=node.metrics.model_dump(),
                uncertainty=uncertainty,
                weights=state.weights,
                max_active_requests=state.max_active_requests,
                stale=node.stale,
                healthy=node.healthy,
            )
            ranked.append(breakdown)

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked

    async def try_forward(
        candidate_nodes: List[RoutingBreakdown],
        payload: Dict[str, Any],
        request_id: str,
    ) -> Tuple[str, Dict[str, Any], List[str], bool, float]:
        tried_nodes: List[str] = []
        used_fallback = False

        async with httpx.AsyncClient(timeout=state.forward_timeout_s) as client:
            for idx, candidate in enumerate(candidate_nodes):
                if not candidate.healthy:
                    continue

                tried_nodes.append(candidate.node_url)
                target_url = (
                    f"{candidate.node_url.rstrip('/')}/"
                    f"{state.vllm_generate_path.lstrip('/')}"
                )

                upstream_started = time.perf_counter()
                try:
                    response = await client.post(
                        target_url,
                        json=payload,
                        headers={"x-request-id": request_id},
                    )
                    response.raise_for_status()
                    upstream_latency_ms = (time.perf_counter() - upstream_started) * 1000.0
                    return (
                        candidate.node_url,
                        response.json(),
                        tried_nodes,
                        idx > 0,
                        upstream_latency_ms,
                    )
                except httpx.HTTPError:
                    await state.registry.mark_node_degraded(candidate.node_url)
                    used_fallback = True
                    logger.warning(
                        "Upstream request failed; trying next node",
                        extra={
                            "extra_fields": {
                                "request_id": request_id,
                                "failed_node": candidate.node_url,
                            }
                        },
                    )

        raise HTTPException(
            status_code=502,
            detail={
                "message": "All candidate nodes failed",
                "request_id": request_id,
                "tried_nodes": tried_nodes,
                "used_fallback": used_fallback,
            },
        )

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        nodes = await state.registry.get_nodes()
        state.last_metrics = [n.model_dump() for n in nodes]
        return {
            "status": "ok",
            "node_count": len(nodes),
            "healthy_node_count": len([n for n in nodes if n.healthy]),
            "weights": state.weights.model_dump(),
            "router_metrics": state.router_metrics.snapshot(),
            "last_known_metrics": state.last_metrics,
        }

    @app.get("/metrics/router")
    async def router_metrics() -> Dict[str, Any]:
        return state.router_metrics.snapshot()

    @app.post("/generate", response_model=GenerateResponse)
    async def generate(request: GenerateRequest) -> GenerateResponse:
        request_id = str(uuid.uuid4())
        router_started = time.perf_counter()

        uncertainty = state.estimator.estimate(
            prompt=request.prompt,
            temperature=request.temperature,
        )

        ranked_nodes = await rank_nodes(uncertainty=uncertainty)
        healthy_candidates = [node for node in ranked_nodes if node.healthy]

        if not healthy_candidates:
            state.router_metrics.record_failure()
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "No healthy nodes available for routing",
                    "request_id": request_id,
                },
            )

        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
        }

        try:
            selected_node, upstream_payload, tried_nodes, used_fallback, upstream_latency_ms = (
                await try_forward(
                    candidate_nodes=healthy_candidates,
                    payload=payload,
                    request_id=request_id,
                )
            )
        except HTTPException:
            state.router_metrics.record_failure()
            raise

        router_latency_ms = (time.perf_counter() - router_started) * 1000.0
        state.router_metrics.record_success(
            node_url=selected_node,
            uncertainty=uncertainty,
            router_latency_ms=router_latency_ms,
            upstream_latency_ms=upstream_latency_ms,
            used_fallback=used_fallback,
        )

        logger.info(
            "Request routed successfully",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "selected_node": selected_node,
                    "tried_nodes": tried_nodes,
                    "uncertainty": round(uncertainty, 6),
                    "router_latency_ms": round(router_latency_ms, 3),
                    "upstream_latency_ms": round(upstream_latency_ms, 3),
                    "used_fallback": used_fallback,
                }
            },
        )

        return GenerateResponse(
            request_id=request_id,
            selected_node=selected_node,
            tried_nodes=tried_nodes,
            uncertainty=uncertainty,
            routing_scores=healthy_candidates,
            router_metrics=state.router_metrics.snapshot(),
            upstream_response=upstream_payload,
        )

    return app


app = build_app()


if __name__ == "__main__":
    uvicorn.run(
        "kv_router.router:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )