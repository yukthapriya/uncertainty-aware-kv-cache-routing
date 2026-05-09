from __future__ import annotations

import os
import random
import socket
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

NODE_NAME = os.getenv("NODE_NAME", socket.gethostname())
KV_CAPACITY_MB = int(os.getenv("KV_CAPACITY_MB", "8192"))
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
ACTIVE_REQUESTS_BASE = int(os.getenv("ACTIVE_REQUESTS_BASE", "0"))
KV_USED_MB_BASE = int(os.getenv("KV_USED_MB_BASE", "1024"))


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int
    temperature: float
    stream: bool = False
    session_id: str | None = None


@app.get("/metrics")
async def metrics():
    kv_used_mb = min(KV_CAPACITY_MB, max(0, KV_USED_MB_BASE + random.randint(-512, 512)))
    active_requests = max(0, ACTIVE_REQUESTS_BASE + random.randint(0, 6))
    return {
        "node_name": NODE_NAME,
        "kv_used_mb": kv_used_mb,
        "kv_capacity_mb": KV_CAPACITY_MB,
        "active_requests": active_requests,
    }


@app.post("/generate")
async def generate(req: GenerateRequest):
    if random.random() < FAILURE_RATE:
        raise HTTPException(status_code=503, detail=f"simulated failure from {NODE_NAME}")

    time.sleep(random.uniform(0.05, 0.2))
    return {
        "node": NODE_NAME,
        "text": f"Mock response from {NODE_NAME} for prompt: {req.prompt[:80]}",
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "stream": req.stream,
        "session_id": req.session_id,
    }