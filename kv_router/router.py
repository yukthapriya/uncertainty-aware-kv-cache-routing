from __future__ import annotations

import contextlib
import logging
import time
import uuid

import httpx
import yaml
from fastapi import FastAPI, HTTPException

from kv_router.logging_utils import configure_logging
from kv_router.metrics import RouterMetrics
from kv_router.models import (
    GenerateRequest,
    GenerateResponse,
    NodeState,
    RoutingWeights,
    RustScorerNodeInput,
    RustScorerRequest,
    RustScorerResponse,
)
from kv_router.node_registry import NodeRegistry
from kv_router.scoring import (
    next_round_robin_index,
    score_kv_aware,
    score_least_loaded,
    score_round_robin,
)
from kv_router.uncertainty import build_uncertainty_estimator

configure_logging()
logger = logging.getLogger(__name__)

with open("kv_router/config.yaml", "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

WEIGHTS = RoutingWeights(**CONFIG.get("scoring", {}))
ROUTER_METRICS = RouterMetrics()
UNCERTAINTY_ESTIMATOR = build_uncertainty_estimator(CONFIG)

NODE_REGISTRY = NodeRegistry(
    nodes=CONFIG["nodes"],
    interval_s=CONFIG["polling"]["interval_s"],
    stale_after_s=CONFIG["polling"]["stale_after_s"],
    degrade_duration_s=CONFIG["polling"]["degrade_duration_s"],
    timeout_s=CONFIG["timeouts"]["metrics_request_timeout_s"],
)

app = FastAPI(title="Uncertainty-Aware KV Router")


@app.on_event("startup")
async def startup() -> None:
    await NODE_REGISTRY.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await NODE_REGISTRY.stop()


async def compute_ranked_scores(request: GenerateRequest, states: list[NodeState]):
    uncertainty = UNCERTAINTY_ESTIMATOR.estimate(request.prompt, request.temperature)

    if request.routing_strategy == "least_loaded":
        ranked = [
            score_least_loaded(
                node=state,
                max_active_requests=CONFIG["router"]["max_active_requests"],
                uncertainty=uncertainty,
            )
            for state in states
        ]
        ranked.sort(key=lambda s: s.score, reverse=True)
        return ranked, uncertainty

    if request.routing_strategy == "round_robin":
        chosen_index = next_round_robin_index(len(states))
        rotated_states = states[chosen_index:] + states[:chosen_index]

        ranked = []
        for i, state in enumerate(rotated_states):
            breakdown = score_round_robin(
                node=state,
                ordered_nodes=rotated_states,
                chosen_index=0,
                uncertainty=uncertainty,
            )
            breakdown.score = float(len(rotated_states) - i)
            ranked.append(breakdown)

        return ranked, uncertainty

    rust_cfg = CONFIG.get("rust_scorer", {})
    rust_enabled = rust_cfg.get("enabled", False)
    rust_url = rust_cfg.get("url")

    if rust_enabled and rust_url:
        try:
            rust_nodes = []
            for state in states:
                if state.metrics is None:
                    rust_nodes.append(
                        RustScorerNodeInput(
                            node_url=state.url,
                            kv_used_mb=0,
                            kv_capacity_mb=1,
                            active_requests=9999,
                            healthy=state.healthy,
                            stale=state.stale,
                        )
                    )
                else:
                    rust_nodes.append(
                        RustScorerNodeInput(
                            node_url=state.url,
                            kv_used_mb=state.metrics.kv_used_mb,
                            kv_capacity_mb=state.metrics.kv_capacity_mb,
                            active_requests=state.metrics.active_requests,
                            healthy=state.healthy,
                            stale=state.stale,
                        )
                    )

            rust_payload = RustScorerRequest(
                uncertainty=uncertainty,
                max_active_requests=CONFIG["router"]["max_active_requests"],
                weights=WEIGHTS,
                nodes=rust_nodes,
            )

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(rust_url, json=rust_payload.model_dump())
                response.raise_for_status()
                rust_response = RustScorerResponse(**response.json())
                return rust_response.ranked_nodes, uncertainty

        except Exception as exc:
            logger.warning("Rust scorer unavailable, falling back to Python scoring: %s", exc)

    ranked = [
        score_kv_aware(
            node=state,
            uncertainty=uncertainty,
            weights=WEIGHTS,
            max_active_requests=CONFIG["router"]["max_active_requests"],
            prompt=request.prompt,
            session_id=request.session_id,
        )
        for state in states
    ]
    ranked.sort(key=lambda s: s.score, reverse=True)
    return ranked, uncertainty


@app.get("/health")
async def health():
    states = NODE_REGISTRY.get_states()
    return {
        "status": "ok",
        "node_count": len(states),
        "healthy_node_count": sum(1 for s in states if s.healthy),
        "weights": WEIGHTS.model_dump(),
        "rust_scorer": CONFIG.get("rust_scorer", {}),
        "router_metrics": ROUTER_METRICS.snapshot().model_dump(),
        "last_known_metrics": [s.model_dump() for s in states],
    }


@app.get("/metrics/router")
async def router_metrics():
    return ROUTER_METRICS.snapshot().model_dump()


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest):
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    states = NODE_REGISTRY.get_states()

    if not any(s.healthy for s in states):
        raise HTTPException(
            status_code=503,
            detail={"message": "No healthy nodes available for routing", "request_id": request_id},
        )

    ranked_scores, uncertainty = await compute_ranked_scores(request, states)
    state_by_url = {s.url: s for s in states}

    tried_nodes: list[str] = []
    upstream_latency_ms = 0.0
    upstream_response = None
    selected_node = None

    async with httpx.AsyncClient(timeout=CONFIG["timeouts"]["forward_request_timeout_s"]) as client:
        for breakdown in ranked_scores:
            candidate = state_by_url[breakdown.node_url]
            if not candidate.healthy:
                continue

            tried_nodes.append(candidate.url)
            try:
                upstream_started = time.perf_counter()
                response = await client.post(
                    f"{candidate.url}{CONFIG['router']['vllm_generate_path']}",
                    json=request.model_dump(),
                )
                response.raise_for_status()
                upstream_latency_ms = (time.perf_counter() - upstream_started) * 1000.0
                upstream_response = response.json()
                selected_node = candidate.url
                break
            except Exception as exc:
                logger.warning("Forwarding failed for node %s: %s", candidate.url, exc)
                NODE_REGISTRY.mark_degraded(candidate.url)
                ROUTER_METRICS.record_fallback()

    if selected_node is None or upstream_response is None:
        ROUTER_METRICS.record_failed_request()
        raise HTTPException(
            status_code=503,
            detail={"message": "All candidate nodes failed during forwarding", "request_id": request_id},
        )

    router_latency_ms = (time.perf_counter() - started) * 1000.0
    ROUTER_METRICS.record_selection(selected_node)
    ROUTER_METRICS.record_request(
        uncertainty=uncertainty,
        router_latency_ms=router_latency_ms,
        upstream_latency_ms=upstream_latency_ms,
    )

    return GenerateResponse(
        request_id=request_id,
        selected_node=selected_node,
        tried_nodes=tried_nodes,
        uncertainty=uncertainty,
        routing_scores=ranked_scores,
        router_metrics=ROUTER_METRICS.snapshot(),
        upstream_response=upstream_response,
    )