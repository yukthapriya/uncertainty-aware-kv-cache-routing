# Uncertainty-Aware KV-Cache Routing for vLLM

## Overview

This project implements a production-style prototype router for distributed vLLM-style inference. It routes generation requests across multiple worker nodes using:

- per-request uncertainty estimation
- KV-cache utilization
- active request load
- stale-metrics penalties
- fallback routing on failure

The goal is to explore how request-level uncertainty and node-level KV-cache state can be combined to make better routing decisions than simple round-robin or least-connections policies.

This prototype is designed to be:
- modular
- easy to run locally
- easy to extend toward real vLLM deployments

---

## Why this project

In distributed LLM inference systems, not all requests are equal and not all nodes are equally capable at every moment.

A router that only balances by request count may ignore:
- KV-cache pressure
- prompt complexity or uncertainty
- stale metrics
- degraded nodes
- transient upstream failures

This project explores a more inference-aware approach:
- estimate how uncertain or potentially expensive a request is
- combine that with live node KV/load metrics
- route to the best node
- recover gracefully if the chosen node fails

This is especially relevant for multi-node vLLM serving, where KV-cache availability and runtime load can significantly affect latency and throughput.

---

## Features

### Routing
- multi-node request routing
- node ranking based on live metrics
- node-sensitive uncertainty-aware scoring
- configurable routing weights

### Uncertainty estimation
- pluggable uncertainty estimator interface
- heuristic uncertainty estimator
- lightweight logistic-regression-style estimator support

### Reliability
- health-aware node selection
- stale-metrics penalty
- fallback to next-best node on upstream failure
- temporary node degradation after failed forwarding

### Observability
- structured JSON logging
- router health endpoint
- router metrics endpoint
- request-level routing metadata
- per-node selection counters
- average latency and uncertainty tracking

### Local development
- mock worker nodes
- benchmark script
- requirements file
- Dockerfile
- docker-compose support

---

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

### File summary

#### Project root
- `benchmark.py`  
  Sends repeated requests to the router and summarizes node selection and latency behavior.

- `mock_node.py`  
  Simulates a worker node exposing:
  - `GET /metrics`
  - `POST /generate`

- `requirements.txt`  
  Python dependencies for local execution.

- `Dockerfile`  
  Container image for router and local testing.

- `docker-compose.yml`  
  Runs router plus multiple mock nodes in a local multi-service setup.

#### `kv_router/`
- `router.py`  
  Main FastAPI service implementing generation routing and health/metrics endpoints.

- `node_registry.py`  
  Polls node `/metrics` endpoints, caches latest state, and tracks degradation/staleness.

- `uncertainty.py`  
  Request uncertainty estimation logic and estimator factory.

- `scoring.py`  
  Routing score calculation and score breakdown generation.

- `models.py`  
  Pydantic models for requests, responses, node info, and score breakdowns.

- `metrics.py`  
  In-memory router metrics collection.

- `logging_utils.py`  
  Structured JSON logging configuration.

- `config.yaml`  
  Node URLs and tunable routing configuration.

- `README.md`  
  Project documentation.

---

## Architecture

```text
                  +----------------------+
                  |        Client        |
                  +----------+-----------+
                             |
                             v
                  +----------------------+
                  |   Router (FastAPI)   |
                  |----------------------|
                  | - uncertainty model  |
                  | - node registry      |
                  | - scoring engine     |
                  | - fallback logic     |
                  | - router metrics     |
                  +----------+-----------+
                             |
                +------------+------------+
                |            |            |
                v            v            v
         +-----------+ +-----------+ +-----------+
         |  Node 1   | |  Node 2   | |  Node 3   |
         | /metrics  | | /metrics  | | /metrics  |
         | /generate | | /generate | | /generate |
         +-----------+ +-----------+ +-----------+
```

---

## Request flow

For `POST /generate`:

1. client sends a generation request to the router
2. router computes a scalar uncertainty score in `[0, 1]`
3. router refreshes and reads the latest node metrics from `NodeRegistry`
4. router computes a routing score for each node
5. router ranks nodes by score
6. router forwards the request to the highest-ranked healthy node
7. if that upstream request fails, router temporarily degrades the node and retries the next-best candidate
8. router returns:
   - selected node
   - tried nodes
   - uncertainty score
   - routing score breakdown
   - router metrics snapshot
   - upstream response payload

---

## Scoring logic

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

### Interpretation

- higher free KV-cache is better
- higher load is worse
- higher uncertainty penalizes cache-heavy nodes more strongly
- stale metrics reduce trust in that node’s score

This is more useful than a request-global uncertainty penalty, because it makes uncertainty interact with node-specific runtime state.

---

## Uncertainty estimation

The router includes a pluggable uncertainty estimator.

### Supported estimators

#### 1. Heuristic estimator
Uses lightweight signals such as:
- prompt length
- temperature
- rare-token-like ratio
- punctuation ratio
- long-token ratio

This is simple, fast, and dependency-free.

#### 2. Logistic-regression-style estimator
Uses the same features with configurable coefficients:

```text
p = sigmoid(bias + Σ wi * xi)
```

This allows future tuning from offline data.

### Output
Both estimators return a scalar uncertainty score in `[0, 1]`.

---

## Node registry

`NodeRegistry` is responsible for:

- loading node URLs from `config.yaml`
- polling `/metrics` periodically
- caching the latest metrics
- detecting stale metrics
- tracking node health
- temporarily degrading failed nodes after routing failures

The registry returns per-node state including:
- URL
- latest metrics
- last update time
- last error
- healthy/unhealthy status
- stale/not-stale status

---

## Reliability behavior

The router includes several resilience-oriented behaviors:

### Health-aware routing
Only healthy nodes are considered routable.

### Stale-metrics penalty
Nodes with stale metrics are penalized in the scoring function.

### Fallback routing
If the selected node fails during forwarding, the router:
1. marks that node degraded
2. tries the next-best candidate
3. records a fallback event in router metrics

### Temporary degradation
A failed node is excluded temporarily, then can recover after the degradation interval.

---

## API

## `POST /generate`

### Request body
```json
{
  "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
  "max_tokens": 64,
  "temperature": 0.8,
  "stream": false
}
```

### Example response
```json
{
  "request_id": "d86d9bb8-173b-4c0a-ba57-4abf04d1d58e",
  "selected_node": "http://localhost:8101",
  "tried_nodes": ["http://localhost:8101"],
  "uncertainty": 0.199375,
  "routing_scores": [
    {
      "node_url": "http://localhost:8101",
      "free_kv_ratio": 0.9505615234375,
      "cache_pressure": 0.0494384765625,
      "load_ratio": 0.6875,
      "uncertainty": 0.199375,
      "stale_penalty": 0.0,
      "score": 0.7688297271728516,
      "healthy": true,
      "stale": false
    }
  ],
  "router_metrics": {
    "uptime_seconds": 20.688,
    "requests_total": 1,
    "requests_failed": 0,
    "fallbacks_total": 0,
    "selected_per_node": {
      "http://localhost:8101": 1
    },
    "avg_uncertainty": 0.199375,
    "avg_router_latency_ms": 96.199,
    "avg_upstream_latency_ms": 84.869
  },
  "upstream_response": {
    "node": "node1",
    "text": "Mock response from node1 for prompt: Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8,
    "stream": false
  }
}
```

---

## `GET /health`

Returns:
- router status
- node counts
- healthy node counts
- routing weights
- router metrics snapshot
- last known node metrics

### Example response
```json
{
  "status": "ok",
  "node_count": 3,
  "healthy_node_count": 3,
  "weights": {
    "alpha": 1.0,
    "beta": 0.25,
    "gamma": 1.0,
    "delta": 2.0
  },
  "router_metrics": {
    "uptime_seconds": 28.817,
    "requests_total": 1,
    "requests_failed": 0,
    "fallbacks_total": 0,
    "selected_per_node": {
      "http://localhost:8101": 1
    },
    "avg_uncertainty": 0.199375,
    "avg_router_latency_ms": 96.199,
    "avg_upstream_latency_ms": 84.869
  },
  "last_known_metrics": [
    {
      "url": "http://localhost:8101",
      "metrics": {
        "kv_used_mb": 4966,
        "kv_capacity_mb": 8192,
        "active_requests": 8
      },
      "last_updated_ts": 1778292093.4525619,
      "last_error": null,
      "healthy": true,
      "stale": false
    }
  ]
}
```

---

## `GET /metrics/router`

Returns an in-memory snapshot of router metrics, including:
- uptime
- total requests
- failed requests
- fallback count
- per-node selection counts
- average uncertainty
- average router latency
- average upstream latency

---

## Configuration

Configuration lives in `kv_router/config.yaml`.

### Example local config
```yaml
nodes:
  - "http://localhost:8101"
  - "http://localhost:8102"
  - "http://localhost:8103"

polling:
  interval_s: 5
  stale_after_s: 10
  degrade_duration_s: 15

timeouts:
  metrics_request_timeout_s: 2.0
  forward_request_timeout_s: 30.0

scoring:
  alpha: 1.0
  beta: 0.25
  gamma: 1.0
  delta: 2.0

router:
  vllm_generate_path: "/generate"
  max_active_requests: 16

uncertainty_estimator:
  type: heuristic
  params:
    length_weight: 0.35
    temperature_weight: 0.35
    rare_token_weight: 0.20
    punctuation_weight: 0.05
    long_token_weight: 0.05
```

### Docker note
For Docker Compose, use service names instead of `localhost`:

```yaml
nodes:
  - "http://mock-node-1:8101"
  - "http://mock-node-2:8102"
  - "http://mock-node-3:8103"
```

---

## Local setup

### 1. Create a virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Start mock nodes
Open 3 terminals.

#### Terminal 1
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node1 FAILURE_RATE=0.0 uvicorn mock_node:app --host 0.0.0.0 --port 8101
```

#### Terminal 2
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node2 FAILURE_RATE=0.3 uvicorn mock_node:app --host 0.0.0.0 --port 8102
```

#### Terminal 3
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node3 FAILURE_RATE=0.0 uvicorn mock_node:app --host 0.0.0.0 --port 8103
```

### 4. Start router
Open a 4th terminal:

```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
uvicorn kv_router.router:app --host 0.0.0.0 --port 8000
```

---

## Local testing

### Send a generation request
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8
  }'
```

### Check health
```bash
curl "http://localhost:8000/health"
```

### Check router metrics
```bash
curl "http://localhost:8000/metrics/router"
```

### Check node metrics directly
```bash
curl "http://localhost:8101/metrics"
curl "http://localhost:8102/metrics"
curl "http://localhost:8103/metrics"
```

---

## Benchmarking / demo

A simple benchmark client is included in `benchmark.py`.

### Run benchmark
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
python benchmark.py
```

This script:
- sends repeated requests to the router
- prints the selected node per request
- prints tried nodes
- prints uncertainty values
- summarizes selected node counts
- reports average request latency

### Example use cases
This is useful for demonstrating:
- load-aware routing behavior
- cache-aware node selection
- uncertainty-influenced scheduling
- fallback behavior under injected failures

---

## Validated fallback example

In one validation run, the router first selected a high-scoring node configured with a high failure rate, then retried the next-best node:

```json
{
  "request_index": 1,
  "selected_node": "http://localhost:8103",
  "tried_nodes": ["http://localhost:8102", "http://localhost:8103"]
}
```

Router metrics confirmed fallback activity:

```json
{
  "fallbacks_total": 1
}
```

This demonstrates that the router can recover from upstream node failures while preserving request success.

---

## Docker usage

### Build and run
```bash
docker compose up --build
```

### Test after startup
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8
  }'
```

### Important note
When using Docker Compose, ensure `kv_router/config.yaml` uses Docker service names:
- `mock-node-1`
- `mock-node-2`
- `mock-node-3`

rather than `localhost`.

---

## Extending uncertainty estimation

The uncertainty estimator is intentionally pluggable.

To add a new estimator:
1. implement a class with:
   ```python
   def estimate(self, prompt: str, temperature: float) -> float:
       ...
   ```
2. return a scalar in `[0, 1]`
3. register it in `build_uncertainty_estimator()`

### Possible future features
- tokenizer-aware prompt statistics
- entropy proxy from a draft model
- retrieval confidence
- prompt classification
- policy-based uncertainty for long-context prompts
- empirical uncertainty learned from serving telemetry

---

## Integrating with real vLLM

This prototype uses mock nodes for local experimentation, but the design maps naturally to real vLLM deployments.

### Possible integration path
- replace mock node URLs with real vLLM-serving pods/services
- change `vllm_generate_path` to the actual inference endpoint
- adapt the request/response format for:
  - `/v1/completions`
  - `/v1/chat/completions`

### Production metrics sources
Instead of polling `/metrics` directly from mock nodes, a production system could gather:
- KV-cache usage
- queue depth
- active requests
- GPU memory utilization
- throughput
- failure rate

from:
- sidecars
- Prometheus
- DCGM exporters
- Kubernetes telemetry pipelines

---

## Kubernetes integration ideas

This project is compatible with a Kubernetes-native mental model.

### Example production architecture
- router as a Deployment + Service
- vLLM workers as separate pods
- metrics collected via sidecars or Prometheus
- request routing integrated with a gateway or inference extension
- autoscaling based on latency, queue depth, or KV pressure

### Natural extensions
- service discovery through Kubernetes APIs
- Gateway API or inference gateway integration
- health-aware routing across pods or node pools
- zone-aware or topology-aware routing
- sticky session support for multi-turn chat
- policy-aware routing by model or adapter

---

## Observability

The router exposes:
- structured JSON logs
- request-level routing metadata
- in-memory router metrics
- node health snapshots

### Current tracked router metrics
- `requests_total`
- `requests_failed`
- `fallbacks_total`
- `selected_per_node`
- `avg_uncertainty`
- `avg_router_latency_ms`
- `avg_upstream_latency_ms`

### Recommended future observability
- Prometheus export format
- latency histograms
- OpenTelemetry traces
- failure categorization
- route-decision audit logs

---

## Limitations

This is still a prototype. Current limitations include:

- mock worker nodes instead of real vLLM workers
- no streaming response forwarding yet
- no OpenAI-compatible request schema yet
- no persistent metrics storage
- no auth, rate limiting, or quota handling
- in-memory state only
- random mock metrics rather than true inference metrics
- no GPU telemetry integration yet

---

## Future work

### Inference / routing improvements
- streaming response forwarding
- OpenAI-compatible `/v1/completions` and `/v1/chat/completions`
- session-aware or sticky routing
- prefill-vs-decode-aware scheduling
- model-aware routing
- LoRA/adaptor-aware routing
- richer uncertainty estimation

### Reliability improvements
- circuit breakers
- retry budgets
- smarter stale-metrics decay
- better health-state transitions
- draining mode for nodes
- bounded concurrency controls

### Observability improvements
- Prometheus metrics export
- OpenTelemetry traces
- latency histograms
- richer decision logs
- dashboarding support

### Platform / deployment improvements
- Kubernetes manifests
- Prometheus integration
- autoscaling hooks
- service mesh integration
- Gateway API integration
- production service discovery

---

## Summary

This project is a practical prototype of an inference-aware request router for multi-node vLLM-style systems.

It combines:
- uncertainty estimation
- KV-cache awareness
- load-aware node ranking
- fallback routing
- health tracking
- local benchmarking

and provides a clear path toward more realistic distributed inference infrastructure in Kubernetes-native environments.
