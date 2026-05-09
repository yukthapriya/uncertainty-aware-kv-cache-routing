from __future__ import annotations

import time

from kv_router.models import RouterMetricsSnapshot


class RouterMetrics:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.requests_total = 0
        self.requests_failed = 0
        self.fallbacks_total = 0
        self.selected_per_node: dict[str, int] = {}
        self._uncertainty_sum = 0.0
        self._router_latency_sum_ms = 0.0
        self._upstream_latency_sum_ms = 0.0

    def record_request(self, uncertainty: float, router_latency_ms: float, upstream_latency_ms: float) -> None:
        self.requests_total += 1
        self._uncertainty_sum += uncertainty
        self._router_latency_sum_ms += router_latency_ms
        self._upstream_latency_sum_ms += upstream_latency_ms

    def record_failed_request(self) -> None:
        self.requests_failed += 1

    def record_fallback(self) -> None:
        self.fallbacks_total += 1

    def record_selection(self, node_url: str) -> None:
        self.selected_per_node[node_url] = self.selected_per_node.get(node_url, 0) + 1

    def snapshot(self) -> RouterMetricsSnapshot:
        requests = self.requests_total if self.requests_total > 0 else 1
        return RouterMetricsSnapshot(
            uptime_seconds=round(time.time() - self.started_at, 3),
            requests_total=self.requests_total,
            requests_failed=self.requests_failed,
            fallbacks_total=self.fallbacks_total,
            selected_per_node=self.selected_per_node,
            avg_uncertainty=round(self._uncertainty_sum / requests, 6) if self.requests_total else 0.0,
            avg_router_latency_ms=round(self._router_latency_sum_ms / requests, 3) if self.requests_total else 0.0,
            avg_upstream_latency_ms=round(self._upstream_latency_sum_ms / requests, 3) if self.requests_total else 0.0,
        )