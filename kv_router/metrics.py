from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict


class RouterMetrics:
    """In-memory router metrics for observability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._requests_total = 0
        self._requests_failed = 0
        self._fallbacks_total = 0
        self._selected_per_node: Dict[str, int] = defaultdict(int)
        self._avg_uncertainty_sum = 0.0
        self._router_latency_ms_sum = 0.0
        self._upstream_latency_ms_sum = 0.0

    def record_success(
        self,
        *,
        node_url: str,
        uncertainty: float,
        router_latency_ms: float,
        upstream_latency_ms: float,
        used_fallback: bool,
    ) -> None:
        with self._lock:
            self._requests_total += 1
            self._selected_per_node[node_url] += 1
            self._avg_uncertainty_sum += uncertainty
            self._router_latency_ms_sum += router_latency_ms
            self._upstream_latency_ms_sum += upstream_latency_ms
            if used_fallback:
                self._fallbacks_total += 1

    def record_failure(self) -> None:
        with self._lock:
            self._requests_total += 1
            self._requests_failed += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            successful = max(1, self._requests_total - self._requests_failed)
            avg_uncertainty = self._avg_uncertainty_sum / successful
            avg_router_latency_ms = self._router_latency_ms_sum / successful
            avg_upstream_latency_ms = self._upstream_latency_ms_sum / successful

            return {
                "uptime_seconds": round(time.time() - self._started_at, 3),
                "requests_total": self._requests_total,
                "requests_failed": self._requests_failed,
                "fallbacks_total": self._fallbacks_total,
                "selected_per_node": dict(self._selected_per_node),
                "avg_uncertainty": round(avg_uncertainty, 6),
                "avg_router_latency_ms": round(avg_router_latency_ms, 3),
                "avg_upstream_latency_ms": round(avg_upstream_latency_ms, 3),
            }