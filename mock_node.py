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


class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int
    temperature: float
    stream: bool = False


@app.get("/metrics")
async def metrics():
    return {
        "node_name": NODE_NAME,
        "kv_used_mb": random.randint(256, min(6144, KV_CAPACITY_MB)),
        "kv_capacity_mb": KV_CAPACITY_MB,
        "active_requests": random.randint(0, 12),
    }


@app.post("/generate")
async def generate(req: GenerateRequest):
    if random.random() < FAILURE_RATE:
        raise HTTPException(
            status_code=503,
            detail=f"simulated failure from {NODE_NAME}",
        )

    time.sleep(random.uniform(0.05, 0.2))
    return {
        "node": NODE_NAME,
        "text": f"Mock response from {NODE_NAME} for prompt: {req.prompt[:80]}",
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "stream": req.stream,
    }