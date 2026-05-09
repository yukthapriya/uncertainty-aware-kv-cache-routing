from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

from kv_router.models import NodeInfo, NodeMetrics

logger = logging.getLogger(__name__)


@dataclass
class NodeState:
    url: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    last_updated_ts: Optional[float] = None
    last_error: Optional[str] = None
    healthy: bool = False
    degraded_until_ts: float = 0.0

    def is_degraded(self) -> bool:
        return time.time() < self.degraded_until_ts

    def to_model(self, stale_after_s: float) -> NodeInfo:
        now = time.time()
        stale = (
            self.last_updated_ts is None
            or (now - self.last_updated_ts) > stale_after_s
        )

        return NodeInfo(
            url=self.url,
            metrics=NodeMetrics(
                kv_used_mb=int(self.metrics.get("kv_used_mb", 0)),
                kv_capacity_mb=int(self.metrics.get("kv_capacity_mb", 0)),
                active_requests=int(self.metrics.get("active_requests", 0)),
            ),
            last_updated_ts=self.last_updated_ts,
            last_error=self.last_error,
            healthy=self.healthy and not self.is_degraded(),
            stale=stale,
        )


class NodeRegistry:
    def __init__(
        self,
        *,
        config_path: str | Path,
        request_timeout_s: float = 2.0,
    ) -> None:
        self.config_path = Path(config_path)
        self.request_timeout_s = request_timeout_s

        self._config: Dict[str, Any] = {}
        self._nodes: Dict[str, NodeState] = {}
        self._poll_interval_s: float = 5.0
        self._stale_after_s: float = 10.0
        self._degrade_duration_s: float = 15.0
        self._polling_task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

        self._load_config()

    def _load_config(self) -> None:
        with self.config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        node_urls = config.get("nodes", []) or []
        polling = config.get("polling", {}) or {}

        if not isinstance(node_urls, list) or not node_urls:
            raise ValueError("config.yaml must define a non-empty 'nodes' list")

        self._config = config
        self._poll_interval_s = float(polling.get("interval_s", 5.0))
        self._stale_after_s = float(polling.get("stale_after_s", 10.0))
        self._degrade_duration_s = float(polling.get("degrade_duration_s", 15.0))

        self._nodes = {str(url): NodeState(url=str(url)) for url in node_urls}

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    @property
    def stale_after_s(self) -> float:
        return self._stale_after_s

    async def start(self) -> None:
        if self._polling_task is not None and not self._polling_task.done():
            return
        self._stop_event.clear()
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("NodeRegistry polling started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._polling_task is not None:
            await self._polling_task
        logger.info("NodeRegistry polling stopped")

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.refresh_all()
            except Exception:
                logger.exception("Unexpected error while refreshing node metrics")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_s,
                )
            except asyncio.TimeoutError:
                pass

    async def refresh_all(self) -> None:
        async with httpx.AsyncClient(timeout=self.request_timeout_s) as client:
            tasks = [
                self._refresh_single_node(client=client, node_url=node_url)
                for node_url in self._nodes.keys()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _refresh_single_node(
        self,
        *,
        client: httpx.AsyncClient,
        node_url: str,
    ) -> None:
        endpoint = f"{node_url.rstrip('/')}/metrics"
        now = time.time()

        try:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = response.json()

            metrics = {
                "kv_used_mb": int(payload.get("kv_used_mb", 0)),
                "kv_capacity_mb": int(payload.get("kv_capacity_mb", 0)),
                "active_requests": int(payload.get("active_requests", 0)),
            }

            async with self._lock:
                state = self._nodes[node_url]
                state.metrics = metrics
                state.last_updated_ts = now
                state.last_error = None
                if not state.is_degraded():
                    state.healthy = True

        except Exception as exc:
            async with self._lock:
                state = self._nodes[node_url]
                state.last_updated_ts = now
                state.last_error = str(exc)
                state.healthy = False

            logger.warning("Failed to refresh metrics for node %s: %s", node_url, exc)

    async def mark_node_degraded(self, node_url: str) -> None:
        async with self._lock:
            if node_url in self._nodes:
                self._nodes[node_url].healthy = False
                self._nodes[node_url].degraded_until_ts = (
                    time.time() + self._degrade_duration_s
                )

    async def get_nodes(self) -> List[NodeInfo]:
        async with self._lock:
            return [
                state.to_model(self._stale_after_s)
                for state in self._nodes.values()
            ]

    async def get_routable_nodes(self) -> List[NodeInfo]:
        nodes = await self.get_nodes()
        return [node for node in nodes if node.healthy]