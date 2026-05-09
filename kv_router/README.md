# Uncertainty-Aware KV-Cache Routing for vLLM

A prototype router for distributed vLLM-style inference that routes requests using:

- per-request uncertainty estimation
- KV-cache utilization
- active request load
- stale-metrics penalties
- fallback routing on failure

## Features

- multi-node request routing
- pluggable uncertainty estimator
- node-sensitive scoring
- health-aware node selection
- fallback to next-best node on upstream failure
- structured JSON logging
- router health and metrics endpoints
- mock nodes for local testing
- benchmark script for repeated request simulation

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
```

## Scoring

The router computes a node-sensitive routing score:

```text
score(node, req) =
    α * free_kv_ratio
  - β * load_ratio
  - γ * uncertainty * cache_pressure
  - δ * stale_penalty
```

Where:

- `free_kv_ratio = (capacity - used) / capacity`
- `load_ratio = active_requests / max_active_requests`
- `cache_pressure = used / capacity`
- `stale_penalty = 1 if metrics are stale else 0`

This makes high-uncertainty requests prefer nodes with more free KV-cache and lower cache pressure.

## Project structure

```text
uncertainty-aware-kv-cache-routing/
├── benchmark.py
├── mock_node.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
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

Request:

```json
{
  "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
  "max_tokens": 64,
  "temperature": 0.8,
  "stream": false
}
```

Response includes:
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

## Configuration

Edit `kv_router/config.yaml`.

### Local config
```yaml
nodes:
  - "http://localhost:8101"
  - "http://localhost:8102"
  - "http://localhost:8103"
```

### Docker Compose config
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
NODE_NAME=node1 FAILURE_RATE=0.0 uvicorn mock_node:app --host 0.0.0.0 --port 8101
```

Terminal 2:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node2 FAILURE_RATE=0.3 uvicorn mock_node:app --host 0.0.0.0 --port 8102
```

Terminal 3:
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node3 FAILURE_RATE=0.0 uvicorn mock_node:app --host 0.0.0.0 --port 8103
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
    "temperature": 0.8
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

This sends repeated requests and prints:
- selected node
- tried nodes
- uncertainty
- summary counts
- average latency

## Validated fallback example

A benchmark run confirmed fallback behavior:

```json
{
  "request_index": 1,
  "selected_node": "http://localhost:8103",
  "tried_nodes": ["http://localhost:8102", "http://localhost:8103"]
}
```

Router metrics showed:

```json
{
  "fallbacks_total": 1
}
```

## Docker

Build and run:

```bash
docker compose up --build
```

Then test:

```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8
  }'
```

## Extending the project

Possible next steps:
- streaming response forwarding
- OpenAI-compatible `/v1/completions` or `/v1/chat/completions`
- Prometheus metrics export
- Kubernetes manifests
- service discovery integration
- richer uncertainty models
- GPU and queue-depth metrics
- session-aware routing

## Limitations

- uses mock worker nodes
- no streaming response forwarding yet
- no persistent metrics storage
- no auth or rate limiting
- no GPU telemetry integration
- mock metrics are randomized

## Summary

This project is a modular prototype for uncertainty-aware, KV-cache-aware request routing in multi-node vLLM-style systems. It combines request uncertainty, node metrics, fallback logic, and observability into a simple framework that can be extended toward real distributed inference deployments.