from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import httpx

from kv_router.models import NodeMetrics, NodeState

logger = logging.getLogger(__name__)


class NodeRegistry:
    def __init__(self, nodes: list[str], interval_s: int, stale_after_s: int, degrade_duration_s: int, timeout_s: float) -> None:
        self.nodes = nodes
        self.interval_s = interval_s
        self.stale_after_s = stale_after_s
        self.degrade_duration_s = degrade_duration_s
        self.timeout_s = timeout_s

        self._state: dict[str, NodeState] = {url: NodeState(url=url) for url in nodes}
        self._degraded_until: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("NodeRegistry polling started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("NodeRegistry polling stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            await self.refresh_all()
            await asyncio.sleep(self.interval_s)

    async def refresh_all(self) -> None:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            await asyncio.gather(*(self._refresh_one(client, url) for url in self.nodes))

    async def _refresh_one(self, client: httpx.AsyncClient, url: str) -> None:
        try:
            response = await client.get(f"{url}/metrics")
            response.raise_for_status()
            data = response.json()

            state = self._state[url]
            state.metrics = NodeMetrics(
                kv_used_mb=data["kv_used_mb"],
                kv_capacity_mb=data["kv_capacity_mb"],
                active_requests=data["active_requests"],
            )
            state.last_updated_ts = time.time()
            state.last_error = None
            state.healthy = time.time() >= self._degraded_until.get(url, 0.0)
            state.stale = False
        except Exception as exc:
            state = self._state[url]
            state.last_error = str(exc)
            state.healthy = False
            state.stale = True
            logger.warning("Failed to refresh metrics for node %s: %s", url, exc)

    def mark_degraded(self, url: str) -> None:
        self._degraded_until[url] = time.time() + self.degrade_duration_s
        state = self._state[url]
        state.healthy = False
        state.last_error = "temporarily degraded after upstream failure"

    def get_states(self) -> list[NodeState]:
        now = time.time()
        states: list[NodeState] = []

        for url, state in self._state.items():
            degraded = now < self._degraded_until.get(url, 0.0)
            stale = not state.last_updated_ts or (now - state.last_updated_ts > self.stale_after_s)

            state.stale = stale
            state.healthy = (not degraded) and state.metrics is not None and not stale and state.last_error is None
            states.append(state)

        return states