from __future__ import annotations

import collections
import json
import time

import httpx

ROUTER_URL = "http://localhost:8000/generate"
NUM_REQUESTS = 20

PROMPTS = [
    "Explain uncertainty-aware KV-cache routing in vLLM.",
    "Summarize how KV-cache pressure affects distributed inference latency.",
    "Describe a Kubernetes-native inference gateway for vLLM.",
    "Compare round-robin routing with cache-aware routing for LLM serving.",
]


def main() -> None:
    selected_counts: collections.Counter[str] = collections.Counter()
    failures = 0
    latencies_ms = []

    with httpx.Client(timeout=30.0) as client:
        for i in range(NUM_REQUESTS):
            payload = {
                "prompt": PROMPTS[i % len(PROMPTS)],
                "max_tokens": 64,
                "temperature": 0.3 + (i % 4) * 0.2,
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
                selected_node = data["selected_node"]
                selected_counts[selected_node] += 1

                print(
                    json.dumps(
                        {
                            "request_index": i,
                            "selected_node": selected_node,
                            "tried_nodes": data.get("tried_nodes", []),
                            "uncertainty": data.get("uncertainty"),
                            "router_latency_ms": data.get("router_metrics", {}).get("avg_router_latency_ms"),
                        }
                    )
                )
            except Exception as exc:
                failures += 1
                print(f"[{i}] exception={exc}")

    avg_latency = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

    print("\n=== Benchmark Summary ===")
    print(f"requests_sent: {NUM_REQUESTS}")
    print(f"failures: {failures}")
    print(f"avg_latency_ms: {avg_latency:.2f}")
    print("selected_counts:")
    for node, count in selected_counts.items():
        print(f"  {node}: {count}")


if __name__ == "__main__":
    main()