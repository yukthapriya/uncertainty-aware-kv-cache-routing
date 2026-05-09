from __future__ import annotations

import collections
import json
import statistics
import time

import httpx

ROUTER_URL = "http://localhost:8000/generate"
NUM_REQUESTS = 30

PROMPTS = [
    "Explain uncertainty-aware KV-cache routing in vLLM.",
    "Summarize how KV-cache pressure affects distributed inference latency.",
    "Describe a Kubernetes-native inference gateway for vLLM.",
    "Compare round-robin routing with cache-aware routing for LLM serving.",
    "Explain how repeated system prefixes can improve cache locality in distributed inference.",
]

STRATEGIES = ["kv_aware", "least_loaded", "round_robin"]


def run_strategy(strategy: str) -> None:
    selected_counts: collections.Counter[str] = collections.Counter()
    failures = 0
    latencies_ms = []
    fallback_events = 0

    print(f"\n=== Running strategy={strategy} ===")

    with httpx.Client(timeout=30.0) as client:
        for i in range(NUM_REQUESTS):
            payload = {
                "prompt": PROMPTS[i % len(PROMPTS)],
                "max_tokens": 64,
                "temperature": 0.3 + (i % 4) * 0.2,
                "routing_strategy": strategy,
                "session_id": f"session-{i % 3}",
            }

            started = time.perf_counter()
            try:
                response = client.post(ROUTER_URL, json=payload)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                latencies_ms.append(elapsed_ms)

                if response.status_code != 200:
                    failures += 1
                    print(f"[{i}] failed status={response.status_code} body={response.text}")
                    continue

                data = response.json()
                tried_nodes = data.get("tried_nodes", [])
                if len(tried_nodes) > 1:
                    fallback_events += 1

                selected_node = data["selected_node"]
                selected_counts[selected_node] += 1

                print(
                    json.dumps(
                        {
                            "request_index": i,
                            "strategy": strategy,
                            "selected_node": selected_node,
                            "tried_nodes": tried_nodes,
                            "uncertainty": data.get("uncertainty"),
                            "router_latency_ms": data.get("router_metrics", {}).get("avg_router_latency_ms"),
                        }
                    )
                )
            except Exception as exc:
                failures += 1
                print(f"[{i}] exception={exc}")

    avg_latency = statistics.mean(latencies_ms) if latencies_ms else 0.0
    p95_latency = (
        statistics.quantiles(latencies_ms, n=20)[18]
        if len(latencies_ms) >= 20
        else max(latencies_ms, default=0.0)
    )

    print(f"\n=== Summary strategy={strategy} ===")
    print(f"requests_sent: {NUM_REQUESTS}")
    print(f"failures: {failures}")
    print(f"fallback_events_seen: {fallback_events}")
    print(f"avg_latency_ms: {avg_latency:.2f}")
    print(f"p95_latency_ms: {p95_latency:.2f}")
    print("selected_counts:")
    for node, count in selected_counts.items():
        print(f"  {node}: {count}")


def main() -> None:
    for strategy in STRATEGIES:
        run_strategy(strategy)

    with httpx.Client(timeout=10.0) as client:
        response = client.get("http://localhost:8000/metrics/router")
        print("\n=== Router Metrics Snapshot ===")
        print(response.text)


if __name__ == "__main__":
    main()