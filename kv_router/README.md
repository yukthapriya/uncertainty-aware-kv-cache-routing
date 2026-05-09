# Uncertainty-Aware KV-Cache Routing for vLLM

A prototype router for distributed vLLM-style inference that routes requests using:

- per-request uncertainty estimation
- KV-cache utilization
- active request load
- stale-metrics penalties
- fallback routing on failure
- optional strategy comparison benchmarking
- optional Rust scoring microservice

## Features

- multi-node request routing
- pluggable uncertainty estimator
- node-sensitive scoring
- strategy comparison:
  - `kv_aware`
  - `least_loaded`
  - `round_robin`
- health-aware node selection
- fallback to next-best node on upstream failure
- structured JSON logging
- router health and metrics endpoints
- mock nodes for local testing
- benchmark script for repeated request simulation
- Rust scoring microservice for performance-sensitive score computation

## Architecture

```text
Client
  |
  v
Router (FastAPI)
  |- uncertainty estimator
  |- node registry
  |- scoring engine
  |- fallback logic
  |- router metrics
  |
  +--> Node 1 (/metrics, /generate)
  +--> Node 2 (/metrics, /generate)
  +--> Node 3 (/metrics, /generate)

Optional:
Router -> Rust scorer (/score)
```

## Scoring

### KV-aware scoring
```text
score(node, req) =
    0.5 * prefix_affinity
  + α * free_kv_ratio
  - β * load_ratio
  - γ * uncertainty * cache_pressure
  - δ * stale_penalty
```

Where:

- `prefix_affinity` is a lightweight affinity heuristic using prompt/session hashing
- `free_kv_ratio = (capacity - used) / capacity`
- `load_ratio = active_requests / max_active_requests`
- `cache_pressure = used / capacity`
- `stale_penalty = 1 if metrics are stale else 0`

### Other strategies
- `least_loaded`
- `round_robin`

## Project structure

```text
uncertainty-aware-kv-cache-routing/
├── benchmark.py
├── mock_node.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── rust_scorer/
│   ├── Cargo.toml
│   └── src/main.rs
└── kv_router/
    ├── __init__.py
    ├── router.py
    ├── node_registry.py
    ├── uncertainty.py
    ├── scoring.py
    ├── models.py
    ├── metrics.py
    ├── logging_utils.py
    ├── config.yaml
    └── README.md
```

## API

### `POST /generate`

Example request:
```json
{
  "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
  "max_tokens": 64,
  "temperature": 0.8,
  "stream": false,
  "session_id": "session-1",
  "routing_strategy": "kv_aware"
}
```

The response includes:
- `request_id`
- `selected_node`
- `tried_nodes`
- `uncertainty`
- `routing_scores`
- `router_metrics`
- `upstream_response`

### `GET /health`
Returns:
- router status
- node counts
- healthy node counts
- routing weights
- router metrics
- last known node metrics

### `GET /metrics/router`
Returns in-memory router metrics, including:
- total requests
- failed requests
- fallback count
- per-node selection counts
- average uncertainty
- average latencies

## Local config

Edit `kv_router/config.yaml`.

### Local node addresses
```yaml
nodes:
  - "http://localhost:8101"
  - "http://localhost:8102"
  - "http://localhost:8103"
```

### Docker Compose node addresses
```yaml
nodes:
  - "http://mock-node-1:8101"
  - "http://mock-node-2:8102"
  - "http://mock-node-3:8103"
```

## Run locally

### 1. Create environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start mock nodes

Terminal 1:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node1 FAILURE_RATE=0.0 KV_USED_MB_BASE=1200 ACTIVE_REQUESTS_BASE=2 uvicorn mock_node:app --host 0.0.0.0 --port 8101
```

Terminal 2:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node2 FAILURE_RATE=0.3 KV_USED_MB_BASE=2200 ACTIVE_REQUESTS_BASE=4 uvicorn mock_node:app --host 0.0.0.0 --port 8102
```

Terminal 3:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node3 FAILURE_RATE=0.0 KV_USED_MB_BASE=3200 ACTIVE_REQUESTS_BASE=1 uvicorn mock_node:app --host 0.0.0.0 --port 8103
```

### 3. Start router

Terminal 4:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
uvicorn kv_router.router:app --host 0.0.0.0 --port 8000
```

### 4. Test
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8,
    "routing_strategy": "kv_aware"
  }'
```

Health:
```bash
curl "http://localhost:8000/health"
```

Router metrics:
```bash
curl "http://localhost:8000/metrics/router"
```

## Benchmark

Run:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
python benchmark.py
```

This runs:
- `kv_aware`
- `least_loaded`
- `round_robin`

and prints:
- selected node
- tried nodes
- uncertainty
- average latency
- p95 latency
- fallback events
- node distribution

## Rust scorer

Run:
```bash
cd ~/uncertainty-aware-kv-cache-routing/rust_scorer
cargo run
```

Test:
```bash
curl -X POST "http://localhost:9000/score" \
  -H "Content-Type: application/json" \
  -d '{
    "uncertainty": 0.2,
    "max_active_requests": 16,
    "weights": {
      "alpha": 1.0,
      "beta": 0.25,
      "gamma": 1.0,
      "delta": 2.0
    },
    "nodes": [
      {
        "node_url": "http://localhost:8101",
        "kv_used_mb": 1000,
        "kv_capacity_mb": 8192,
        "active_requests": 4,
        "healthy": true,
        "stale": false
      }
    ]
  }'
```

## Docker

Build and run:
```bash
docker compose up --build
```

## Limitations

- uses mock worker nodes
- no streaming response forwarding yet
- no persistent metrics storage
- no GPU telemetry integration
- mock metrics are randomized
- Rust scorer is optional and not wired into router by default

## Next steps

- wire Rust scorer into router
- add Prometheus metrics export
- support OpenAI-compatible endpoints
- add Kubernetes manifests
- improve prefix-affinity model
- add TTFT and throughput-oriented measurements