"""
llm-d Traffic Distribution Test

Tests intelligent routing across vLLM replicas via the llm-d scheduler.
After running, queries vLLM pod metrics to show per-node traffic distribution.

Tests:
  1. Concurrent load    - parallel requests to verify distribution across pods
  2. Prefix cache       - repeated prompts to verify cache-aware routing
  3. Sustained throughput - steady-state performance over a duration

Requirements:
  pip install aiohttp   (or: uv run --with aiohttp python test_distribution.py ...)

Usage:
  python test_distribution.py --url <LLMD_URL> --model <MODEL_NAME>

  # Example:
  python test_distribution.py \\
    --url http://my-gateway.example.com/redhat-ods-applications/my-model-llmd/v1 \\
    --model openai/gpt-oss-20b

  # With custom settings:
  python test_distribution.py \\
    --url http://my-gateway.example.com/redhat-ods-applications/my-model-llmd/v1 \\
    --model openai/gpt-oss-20b \\
    --namespace my-namespace \\
    --concurrency 4 \\
    --duration 60

Arguments:
  --url          llm-d gateway URL ending with /v1 (required)
  --model        Model name as registered in vLLM (required)
  --namespace    Kubernetes namespace where vLLM pods run (default: redhat-ods-applications)
  --service-name LLMInferenceService name for pod label lookup (derived from URL path by default)
  --concurrency  Number of concurrent requests (default: 6)
  --duration     Duration in seconds for sustained throughput test (default: 30)

Environment variables (alternative to CLI args):
  LLMD_URL       - Same as --url
  LLMD_MODEL     - Same as --model
  LLMD_NAMESPACE - Same as --namespace
"""

import argparse
import asyncio
import os
import re
import subprocess
import sys
import time
from collections import defaultdict

try:
    import aiohttp
except ImportError:
    print("Error: aiohttp is required. Install with:")
    print("  pip install aiohttp")
    print("  # or run with: uv run --with aiohttp python test_distribution.py ...")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test llm-d traffic distribution across vLLM replicas"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("LLMD_URL"),
        help="llm-d gateway URL ending with /v1 (or set LLMD_URL env var)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("LLMD_MODEL"),
        help="Model name as registered in vLLM (or set LLMD_MODEL env var)",
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get("LLMD_NAMESPACE", "redhat-ods-applications"),
        help="Kubernetes namespace (default: redhat-ods-applications)",
    )
    parser.add_argument(
        "--service-name",
        default=None,
        help="LLMInferenceService name for pod label lookup (derived from URL if omitted)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Number of concurrent requests (default: 6)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration in seconds for sustained throughput test (default: 30)",
    )
    args = parser.parse_args()

    if not args.url:
        parser.error("--url is required (or set LLMD_URL env var)")
    if not args.model:
        parser.error("--model is required (or set LLMD_MODEL env var)")

    if not args.service_name:
        parts = args.url.rstrip("/").split("/")
        for i, p in enumerate(parts):
            if p == "v1" and i > 0:
                args.service_name = parts[i - 1]
                break
        if not args.service_name:
            args.service_name = parts[-1] if parts[-1] != "v1" else parts[-2]

    return args


def get_pod_metrics(namespace, service_name):
    """Fetch vLLM metrics from each pod via oc exec."""
    pod_label = f"app.kubernetes.io/name={service_name},kserve.io/component=workload"
    try:
        result = subprocess.run(
            [
                "oc",
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                pod_label,
                "-o",
                r"jsonpath={range .items[*]}{.metadata.name},{.spec.nodeName}{'\n'}{end}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        pods = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if "," in line:
                name, node = line.split(",", 1)
                short_node = re.sub(
                    r"ip-[\d-]+\..*",
                    lambda m: m.group().split(".")[0].split("-")[-1],
                    node,
                )
                if short_node == node:
                    short_node = node.split(".")[0]
                pods.append((name, short_node))

        pod_stats = []
        for pod_name, short_node in pods:
            try:
                metrics_result = subprocess.run(
                    [
                        "oc",
                        "exec",
                        pod_name,
                        "-n",
                        namespace,
                        "--",
                        "curl",
                        "-sk",
                        "--max-time",
                        "10",
                        "https://localhost:8000/metrics",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                metrics = metrics_result.stdout
            except subprocess.TimeoutExpired:
                print(
                    f"  Warning: Timeout fetching metrics from {short_node} ({pod_name})"
                )
                metrics = ""

            requests = 0
            prompt_tokens = 0
            gen_tokens = 0
            cache_hit = "N/A"

            for line in metrics.split("\n"):
                if line.startswith("vllm:request_success_total"):
                    requests += int(float(line.split()[-1]))
                elif line.startswith("vllm:prompt_tokens_total"):
                    prompt_tokens = int(float(line.split()[-1]))
                elif line.startswith("vllm:generation_tokens_total"):
                    gen_tokens = int(float(line.split()[-1]))
                elif "prefix_cache_hit_rate" in line and not line.startswith("#"):
                    try:
                        cache_hit = f"{float(line.split()[-1]):.1%}"
                    except ValueError:
                        pass

            pod_stats.append(
                {
                    "node": short_node,
                    "pod": pod_name,
                    "requests": requests,
                    "prompt_tokens": prompt_tokens,
                    "gen_tokens": gen_tokens,
                    "cache_hit": cache_hit,
                }
            )

        return pod_stats
    except Exception as e:
        print(f"  Warning: Could not fetch pod metrics: {e}")
        return []


def print_distribution(before, after):
    """Print per-pod traffic distribution showing both delta and cumulative totals."""
    print(f"\n{'=' * 60}")
    print("Pod Traffic Distribution")
    print(f"{'=' * 60}")

    before_map = {s["pod"]: s for s in before}

    print("\n  This run (delta):")
    header = f"  {'Node':<16} {'Requests':>10} {'Prompt Tok':>12} {'Gen Tok':>10} {'Cache Hit':>10}"
    print(header)
    print(f"  {'-' * 16} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 10}")

    total_reqs = 0
    total_prompt = 0
    total_gen = 0
    rows = []

    for s in after:
        b = before_map.get(
            s["pod"], {"requests": 0, "prompt_tokens": 0, "gen_tokens": 0}
        )
        delta_reqs = s["requests"] - b["requests"]
        delta_prompt = s["prompt_tokens"] - b["prompt_tokens"]
        delta_gen = s["gen_tokens"] - b["gen_tokens"]
        rows.append((s["node"], delta_reqs, delta_prompt, delta_gen, s["cache_hit"]))
        total_reqs += delta_reqs
        total_prompt += delta_prompt
        total_gen += delta_gen

    for node, reqs, prompt, gen, cache in sorted(rows, key=lambda r: -r[1]):
        pct = f"({reqs / total_reqs * 100:.0f}%)" if total_reqs > 0 else ""
        bar = "#" * min(reqs // 2, 30) if reqs > 0 else ""
        print(
            f"  {node:<16} {reqs:>6} {pct:>4} {prompt:>12} {gen:>10} {cache:>10}  {bar}"
        )

    print(f"  {'-' * 16} {'-' * 10} {'-' * 12} {'-' * 10} {'-' * 10}")
    print(f"  {'TOTAL':<16} {total_reqs:>10} {total_prompt:>12} {total_gen:>10}")

    print("\n  Cumulative totals (since pod start):")
    header = f"  {'Node':<16} {'Requests':>10} {'Prompt Tok':>12} {'Gen Tok':>10}"
    print(header)
    print(f"  {'-' * 16} {'-' * 10} {'-' * 12} {'-' * 10}")

    cum_total = sum(s["requests"] for s in after)
    cum_rows = []
    for s in after:
        cum_rows.append((s["node"], s["requests"], s["prompt_tokens"], s["gen_tokens"]))

    for node, reqs, prompt, gen in sorted(cum_rows, key=lambda r: -r[1]):
        pct = f"({reqs / cum_total * 100:.0f}%)" if cum_total > 0 else ""
        bar = "#" * min(reqs // 5, 30) if reqs > 0 else ""
        print(f"  {node:<16} {reqs:>6} {pct:>4} {prompt:>12} {gen:>10}  {bar}")

    print(f"  {'-' * 16} {'-' * 10} {'-' * 12} {'-' * 10}")
    cum_prompt = sum(s["prompt_tokens"] for s in after)
    cum_gen = sum(s["gen_tokens"] for s in after)
    print(f"  {'TOTAL':<16} {cum_total:>10} {cum_prompt:>12} {cum_gen:>10}")

    if cum_total > 0 and len(after) > 0:
        expected = cum_total / len(after)
        max_reqs = max(r[1] for r in cum_rows)
        skew = max_reqs / expected if expected > 0 else 0
        print(f"\n  Distribution skew: {skew:.2f}x (1.0 = perfectly even)")
        if skew > 2.0:
            print(
                "  -> Highly skewed: llm-d prefix-cache scorer is routing repeat prompts to same pods"
            )
        elif skew > 1.3:
            print("  -> Moderately skewed: llm-d is favoring pods with cached prefixes")
        else:
            print("  -> Relatively even distribution across pods")


async def send_request(session, url, model, prompt, max_tokens=20, request_id=0):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    start = time.monotonic()
    try:
        async with session.post(
            f"{url}/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            data = await resp.json()
            elapsed = time.monotonic() - start
            usage = data.get("usage", {})
            return {
                "request_id": request_id,
                "status": resp.status,
                "elapsed": elapsed,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "model": data.get("model", ""),
                "error": None,
            }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "request_id": request_id,
            "status": 0,
            "elapsed": elapsed,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model": "",
            "error": str(e),
        }


async def test_concurrent_load(url, model, num_requests=30, concurrency=6):
    print(f"\n{'=' * 60}")
    print("TEST 1: Concurrent Load Distribution")
    print(f"Sending {num_requests} requests with concurrency={concurrency}")
    print(f"{'=' * 60}")

    prompts = [
        "What is machine learning?",
        "Explain quantum computing.",
        "How does photosynthesis work?",
        "What causes earthquakes?",
        "Describe the solar system.",
        "What is artificial intelligence?",
        "How do vaccines work?",
        "Explain the theory of relativity.",
        "What is blockchain technology?",
        "How does the internet work?",
    ]

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_request(session, prompt, req_id):
        async with semaphore:
            return await send_request(
                session, url, model, prompt, max_tokens=20, request_id=req_id
            )

    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        tasks = [
            bounded_request(session, prompts[i % len(prompts)], i)
            for i in range(num_requests)
        ]
        results = await asyncio.gather(*tasks)
    total_time = time.monotonic() - start

    successful = [r for r in results if r["error"] is None and r["status"] == 200]
    failed = [r for r in results if r["error"] is not None or r["status"] != 200]

    print("\nResults:")
    print(f"  Successful: {len(successful)}/{num_requests}")
    print(f"  Failed: {len(failed)}")
    print(f"  Total time: {total_time:.2f}s")
    print(f"  Throughput: {len(successful) / total_time:.2f} req/s")

    if successful:
        latencies = [r["elapsed"] for r in successful]
        latencies.sort()
        total_tokens = sum(r["total_tokens"] for r in successful)
        print("\nLatency (seconds):")
        print(f"  Min:    {min(latencies):.3f}")
        print(f"  Median: {latencies[len(latencies) // 2]:.3f}")
        print(f"  P95:    {latencies[int(len(latencies) * 0.95)]:.3f}")
        print(f"  Max:    {max(latencies):.3f}")
        print(f"  Avg:    {sum(latencies) / len(latencies):.3f}")
        print("\nTokens:")
        print(f"  Total: {total_tokens}")
        print(f"  Tokens/sec: {total_tokens / total_time:.1f}")

    if failed:
        print("\nErrors:")
        for r in failed[:3]:
            err = r["error"] or f"HTTP {r['status']}"
            print(f"  Request {r['request_id']}: {err}")

    return results


async def test_prefix_cache_routing(url, model, num_rounds=3, prompts_per_round=6):
    print(f"\n{'=' * 60}")
    print("TEST 2: Prefix Cache Routing")
    print(f"Sending same prompts {num_rounds} rounds to test cache-aware routing")
    print(f"{'=' * 60}")

    base_prompts = [
        "You are a helpful assistant that explains science concepts. Explain the concept of gravity in detail, including Newton's law of universal gravitation and Einstein's general theory of relativity.",
        "You are a helpful assistant that explains science concepts. Explain the concept of evolution by natural selection, including Darwin's original theory and modern synthesis.",
        "You are a helpful assistant that explains science concepts. Explain the concept of thermodynamics, including the three laws and their practical applications.",
    ]

    round_results = []
    async with aiohttp.ClientSession() as session:
        for round_num in range(num_rounds):
            print(f"\n  Round {round_num + 1}/{num_rounds}...")
            start = time.monotonic()
            tasks = [
                send_request(
                    session,
                    url,
                    model,
                    base_prompts[i % len(base_prompts)],
                    max_tokens=30,
                    request_id=i,
                )
                for i in range(prompts_per_round)
            ]
            results = await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start

            successful = [r for r in results if r["error"] is None]
            avg_latency = (
                sum(r["elapsed"] for r in successful) / len(successful)
                if successful
                else 0
            )

            round_results.append(
                {
                    "round": round_num + 1,
                    "avg_latency": avg_latency,
                    "total_time": elapsed,
                    "successful": len(successful),
                }
            )
            print(
                f"    Avg latency: {avg_latency:.3f}s | Total: {elapsed:.2f}s | Success: {len(successful)}/{prompts_per_round}"
            )

    if len(round_results) >= 2:
        first = round_results[0]["avg_latency"]
        last = round_results[-1]["avg_latency"]
        change_pct = ((last - first) / first) * 100 if first > 0 else 0
        print(
            f"\n  Latency: {first:.3f}s (round 1) -> {last:.3f}s (round {num_rounds}): {change_pct:+.1f}%"
        )
        if change_pct < -10:
            print(
                "  -> Prefix cache routing is effective (latency decreased on repeated prompts)"
            )
        elif change_pct < 0:
            print("  -> Slight latency decrease, prefix caching may be working")
        else:
            print(
                "  -> No latency decrease detected (cache may need more repetitions or longer prompts)"
            )


async def test_sustained_throughput(url, model, duration_seconds=30, concurrency=6):
    print(f"\n{'=' * 60}")
    print(
        f"TEST 3: Sustained Throughput ({duration_seconds}s, concurrency={concurrency})"
    )
    print(f"{'=' * 60}")

    prompts = [
        "Write a short poem about the ocean.",
        "What are the benefits of exercise?",
        "Explain how a computer processor works.",
        "Describe the water cycle.",
        "What is the meaning of life?",
        "How do birds fly?",
    ]

    results = []
    start = time.monotonic()
    request_count = 0

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(concurrency)

        async def worker():
            nonlocal request_count
            while time.monotonic() - start < duration_seconds:
                async with semaphore:
                    req_id = request_count
                    request_count += 1
                    prompt = prompts[req_id % len(prompts)]
                    result = await send_request(
                        session, url, model, prompt, max_tokens=30, request_id=req_id
                    )
                    results.append(result)

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.gather(*workers)

    total_time = time.monotonic() - start
    successful = [r for r in results if r["error"] is None and r["status"] == 200]
    total_tokens = sum(r["total_tokens"] for r in successful)

    print("\nResults:")
    print(f"  Duration: {total_time:.1f}s")
    print(f"  Total requests: {len(results)}")
    print(f"  Successful: {len(successful)}")
    print(f"  Throughput: {len(successful) / total_time:.2f} req/s")
    print(f"  Total tokens: {total_tokens}")
    print(f"  Tokens/sec: {total_tokens / total_time:.1f}")

    if successful:
        latencies = sorted(r["elapsed"] for r in successful)
        print("\nLatency (seconds):")
        print(f"  Min:    {min(latencies):.3f}")
        print(f"  Median: {latencies[len(latencies) // 2]:.3f}")
        print(f"  P95:    {latencies[int(len(latencies) * 0.95)]:.3f}")
        print(f"  Max:    {max(latencies):.3f}")

        bucket_size = 5
        print(f"\n  Requests completed per {bucket_size}s window:")
        time_buckets = defaultdict(int)
        for i, r in enumerate(successful):
            t = (i / len(successful)) * total_time
            bucket = int(t // bucket_size) * bucket_size
            time_buckets[bucket] += 1
        for t in sorted(time_buckets.keys()):
            bar = "#" * time_buckets[t]
            print(f"    {t:3d}-{t + bucket_size:3d}s: {time_buckets[t]:3d} {bar}")


async def main():
    args = parse_args()

    print("llm-d Traffic Distribution Test")
    print(f"Endpoint: {args.url}")
    print(f"Model: {args.model}")
    print(f"Namespace: {args.namespace}")
    print(f"Service: {args.service_name}")
    print(f"Concurrency: {args.concurrency}")

    async with aiohttp.ClientSession() as session:
        result = await send_request(
            session, args.url, args.model, "hello", max_tokens=5
        )
        if result["error"]:
            print(f"\nConnection failed: {result['error']}")
            sys.exit(1)
        print(f"Connection OK (latency: {result['elapsed']:.3f}s)")

    print("\nCollecting baseline pod metrics...")
    before = get_pod_metrics(args.namespace, args.service_name)

    num_requests = args.concurrency * 5
    await test_concurrent_load(
        args.url, args.model, num_requests=num_requests, concurrency=args.concurrency
    )
    await test_prefix_cache_routing(
        args.url, args.model, num_rounds=3, prompts_per_round=args.concurrency
    )
    await test_sustained_throughput(
        args.url,
        args.model,
        duration_seconds=args.duration,
        concurrency=args.concurrency,
    )

    print("\nCollecting final pod metrics...")
    after = get_pod_metrics(args.namespace, args.service_name)

    if before and after:
        print_distribution(before, after)

    print(f"\n{'=' * 60}")
    print("All tests complete.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
