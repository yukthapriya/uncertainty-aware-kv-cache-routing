# Uncertainty-Aware KV-Cache Routing for vLLM

A prototype distributed router for LLM inference that selects among multiple vLLM-style nodes using:
- KV-cache awareness
- live node load metrics
- uncertainty-aware request scoring
- fallback on node failure
- optional Rust-backed scoring for the KV-aware path

This project is designed as a systems prototype that separates:
- **control plane in Python**: health polling, request forwarding, fallback, observability
- **scoring path in Rust**: low-overhead candidate ranking for KV-aware routing

---

## Features

- **Multiple routing strategies**
  - `kv_aware`
  - `least_loaded`
  - `round_robin`

- **Live node polling**
  - KV usage
  - KV capacity
  - active requests
  - healthy/stale state tracking

- **Fallback routing**
  - If the top-ranked node fails, the router retries the next candidate

- **Router metrics**
  - total requests
  - failed requests
  - fallback count
  - per-node selection counts
  - average uncertainty
  - average router latency
  - average upstream latency

- **Rust scorer integration**
  - Python router can delegate KV-aware score computation to a Rust service

---

## Architecture

### Components

1. **Mock inference nodes**
   - Simulate vLLM-style inference servers
   - Expose `/metrics`
   - Accept `/generate`

2. **Python router**
   - Polls node metrics
   - Computes uncertainty
   - Selects/ranks candidates
   - Forwards requests
   - Handles fallback and metrics

3. **Rust scorer**
   - Accepts node state and uncertainty inputs
   - Computes KV-aware ranking
   - Returns ordered candidate scores

### Request flow

1. Client sends request to router `/generate`
2. Router estimates request uncertainty
3. Router gets latest node states
4. Router ranks nodes:
   - in Python for `least_loaded` and `round_robin`
   - via Rust service for `kv_aware` when enabled
5. Router forwards request to best candidate
6. On failure, router retries the next ranked node
7. Router returns response with routing metadata and metrics snapshot

---

## Repository Structure

```text
.
├── benchmark.py
├── mock_node.py
├── kv_router/
│   ├── config.yaml
│   ├── logging_utils.py
│   ├── metrics.py
│   ├── models.py
│   ├── node_registry.py
│   ├── router.py
│   ├── scoring.py
│   └── uncertainty.py
└── rust_scorer/
    ├── Cargo.toml
    └── src/main.rs
```

---

## Requirements

- Python 3.11+
- Rust (optional, for Rust scorer)
- macOS/Linux shell environment

---

## Setup

### 1. Create Python environment

```bash
cd ~/uncertainty-aware-kv-cache-routing
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Optional: install Rust
If Rust is not installed:

```bash
brew install rust
```

or install through `rustup`.

---

## Running the System

You need 4-5 terminals.

### Terminal 1: mock node 1
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node1 FAILURE_RATE=0.0 KV_USED_MB_BASE=1200 ACTIVE_REQUESTS_BASE=2 uvicorn mock_node:app --host 0.0.0.0 --port 8101
```

### Terminal 2: mock node 2
This node is configured with higher failure probability to exercise fallback.

```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node2 FAILURE_RATE=0.9 KV_USED_MB_BASE=800 ACTIVE_REQUESTS_BASE=1 uvicorn mock_node:app --host 0.0.0.0 --port 8102
```

### Terminal 3: mock node 3
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
NODE_NAME=node3 FAILURE_RATE=0.0 KV_USED_MB_BASE=3200 ACTIVE_REQUESTS_BASE=1 uvicorn mock_node:app --host 0.0.0.0 --port 8103
```

### Terminal 4: Rust scorer
```bash
cd ~/uncertainty-aware-kv-cache-routing/rust_scorer
cargo run
```

Expected output:
```text
Rust scorer listening on 0.0.0.0:9000
```

### Terminal 5: router
```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
uvicorn kv_router.router:app --host 0.0.0.0 --port 8000
```

---

## Verify the System

### Health check
```bash
curl http://localhost:8000/health
```

Expected fields include:
- `status: ok`
- `healthy_node_count`
- `rust_scorer.enabled: true`

### Example generation request
```bash
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Explain uncertainty-aware KV-cache routing in vLLM",
    "max_tokens": 64,
    "temperature": 0.8,
    "routing_strategy": "kv_aware",
    "session_id": "session-1"
  }'
```

Example response includes:
- `selected_node`
- `tried_nodes`
- `uncertainty`
- `routing_scores`
- `router_metrics`
- `upstream_response`

---

## Benchmark

Run:

```bash
cd ~/uncertainty-aware-kv-cache-routing
source .venv/bin/activate
python benchmark.py
```

The benchmark sends requests using:
- `kv_aware`
- `least_loaded`
- `round_robin`

and prints:
- per-request routing decisions
- fallback behavior
- average latency
- p95 latency
- selection counts

---

## Example Benchmark Results

From one sample run:

| Strategy     | Avg Latency (ms) | P95 Latency (ms) | Fallbacks | Selection Distribution |
|--------------|-----------------:|-----------------:|----------:|------------------------|
| kv_aware     | 141.87           | 213.70           | 1         | node1: 19, node3: 10, node2: 1 |
| least_loaded | 133.48           | 214.55           | 0         | node1: 27, node3: 3 |
| round_robin  | 144.61           | 223.07           | 0         | node1: 20, node3: 10 |

> These results come from a mock-node benchmark with randomized metrics and injected failures, so they should be interpreted as prototype behavior rather than production performance claims.

---

## Rust Scorer Integration

The router can delegate KV-aware ranking to the Rust service.

### Config
`kv_router/config.yaml`:

```yaml
rust_scorer:
  enabled: true
  url: "http://localhost:9000/score"
```

### Behavior
- `kv_aware` uses Rust scoring when enabled and available
- `least_loaded` and `round_robin` stay in Python
- if the Rust scorer is unavailable, the router falls back to Python scoring automatically

This gives the system a hybrid design:
- **Python** for orchestration and control-plane behavior
- **Rust** for performance-oriented scoring logic

---

## Routing Strategies

### `kv_aware`
Ranks nodes using:
- free KV capacity
- cache pressure
- active request load
- request uncertainty
- stale-node penalty

This strategy is the main experimental routing mode.

### `least_loaded`
Selects nodes primarily by active request load.

### `round_robin`
Cycles request preference across nodes and relies on fallback if a selected node fails.

---

## Observability

### Router health
```bash
curl http://localhost:8000/health
```

### Router metrics
```bash
curl http://localhost:8000/metrics/router
```

Metrics include:
- uptime
- request counts
- failed requests
- fallback count
- selected nodes
- average uncertainty
- average router latency
- average upstream latency

### Node metrics
```bash
curl http://localhost:8101/metrics
curl http://localhost:8102/metrics
curl http://localhost:8103/metrics
```

---

## Design Notes

This project is a **prototype**, not a production router.

### Simplifications
- mock nodes instead of real vLLM workers
- heuristic uncertainty estimator
- heuristic KV-affinity scoring
- synthetic benchmark workload
- no real distributed scheduler or autoscaling

### Why it is still useful
It demonstrates:
- systems decomposition
- multi-node routing logic
- failure handling
- control plane / data plane separation
- Python/Rust interoperability
- measurable benchmark outputs

---

## Future Work

- integrate with real vLLM servers
- track real prefix/KV reuse instead of heuristic affinity
- add better workload generation
- export metrics to Prometheus
- add plotting for benchmark output
- support streaming responses
- add request admission control and queueing
- extend Rust scorer with richer scoring signals

---

## Troubleshooting

### Router fails with Python typing errors
Use Python 3.11+.

Check:
```bash
python --version
```

### Router says no healthy nodes
Verify node processes are running:

```bash
curl http://localhost:8101/metrics
curl http://localhost:8102/metrics
curl http://localhost:8103/metrics
```

### Port already in use
Find and kill the old process:

```bash
lsof -i :8000
kill -9 <PID>
```

### Rust scorer unavailable
Check:
```bash
curl http://localhost:9000/score
```

or restart:

```bash
cd rust_scorer
cargo run
```

If Rust is down, the router should still fall back to Python KV-aware scoring.

---

## Summary

This project explores **uncertainty-aware and KV-cache-aware routing for LLM inference** with:
- multi-node health polling
- strategy-based routing
- fallback on failure
- router-level observability
- a hybrid Python + Rust architecture

It is intended as a practical prototype for experimenting with routing policies in distributed LLM serving.
