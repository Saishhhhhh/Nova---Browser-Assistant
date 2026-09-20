"""
Benchmark runner: Raw CDP against local test server fixtures.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

# Add project roots to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from cdp_client import ChromeProcess, CDPClient, get_page_ws_url
from benchmark_harness.server.app import start_server


def calc_stats(times: list[float]) -> dict:
    if not times:
        return {"p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
    sorted_t = sorted(times)
    p50 = statistics.median(sorted_t)
    p95_idx = int(len(sorted_t) * 0.95)
    p95 = sorted_t[min(p95_idx, len(sorted_t) - 1)]
    return {
        "p50": round(p50, 2),
        "p95": round(p95, 2),
        "min": round(sorted_t[0], 2),
        "max": round(sorted_t[-1], 2),
        "mean": round(statistics.mean(sorted_t), 2),
    }


async def run_benchmark(headed: bool = False, iterations: int = 5, server_port: int = 8765):
    base_url = f"http://127.0.0.1:{server_port}"
    chrome = ChromeProcess(port=9222, headless=not headed)
    
    print(f"\n[Raw CDP] Launching Chrome (headed={headed})...")
    t_start = time.perf_counter()
    chrome.start()
    t_launch = (time.perf_counter() - t_start) * 1000.0
    print(f"[Raw CDP] Chrome launched in {t_launch:.1f} ms")

    try:
        ws_url = await get_page_ws_url(9222)
        client = CDPClient(ws_url)
        await client.connect()
        print("[Raw CDP] Connected to Page target via WebSocket.")

        # Metric stores
        nav_times = []
        click_times = []
        type_times = []
        scroll_times = []
        dom_query_times = []
        axtree_times = []
        axtree_node_counts = []
        spa_filter_times = []

        print(f"\n[Raw CDP] Running {iterations} iteration(s)...")

        for it in range(1, iterations + 1):
            # 1. Navigation to Actions fixture
            nav_ms = await client.navigate(f"{base_url}/actions.html")
            nav_times.append(nav_ms)

            # Wait for actions readiness beacon
            for _ in range(50):
                ready = await client.evaluate("window.location.pathname.endsWith('actions.html') && window.__fixture_ready === true")
                if ready:
                    break
                await asyncio.sleep(0.05)

            # 2. Click Benchmark
            c_ms = await client.click("#btn-click-target")
            click_times.append(c_ms)
            click_text = await client.evaluate("document.getElementById('click-status').textContent")
            assert "SUCCESS" in (click_text or ""), f"Click verification failed: {click_text}"

            # 3. Typing Benchmark (50 chars)
            test_phrase = "Raw CDP benchmark keystroke latency test 12345"
            t_ms = await client.type_text("#input-text-target", test_phrase)
            type_times.append(t_ms)
            val = await client.evaluate("document.getElementById('input-text-target').value")
            assert test_phrase in (val or ""), f"Typing verification failed: {val}"

            # 4. Scroll Benchmark
            s_ms = await client.scroll(0, 1400)
            scroll_times.append(s_ms)

            # 5. Heavy DOM Benchmark (10k nodes)
            await client.navigate(f"{base_url}/dom_heavy.html")
            for _ in range(100):
                ready = await client.evaluate("window.location.pathname.endsWith('dom_heavy.html') && window.__total_nodes === 10000")
                if ready:
                    break
                await asyncio.sleep(0.05)

            # Query deeply nested element
            t0 = time.perf_counter_ns()
            coords = await client.get_element_center("#needle-btn")
            dom_query_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            dom_query_times.append(dom_query_ms)
            assert coords is not None, "Failed to query #needle-btn"

            # Accessibility Tree Extraction
            ax_res, ax_ms = await client.get_accessibility_tree()
            axtree_times.append(ax_ms)
            nodes = ax_res.get("nodes", [])
            axtree_node_counts.append(len(nodes))

            # 6. Dynamic SPA Hydration & Filter
            await client.navigate(f"{base_url}/dynamic_spa.html")
            for _ in range(50):
                ready = await client.evaluate("window.location.pathname.endsWith('dynamic_spa.html') && window.__fixture_ready === true")
                if ready:
                    break
                await asyncio.sleep(0.05)

            # Wait for delayed hydration button
            for _ in range(30):
                hydrated = await client.evaluate("document.getElementById('hydrated-action-btn') !== null")
                if hydrated:
                    break
                await asyncio.sleep(0.05)

            # Filter products
            t0 = time.perf_counter_ns()
            await client.type_text("#spa-search-input", "Laptop")
            filter_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            spa_filter_times.append(filter_ms)

            print(f"  Iteration {it}/{iterations} done: click={c_ms:.1f}ms, type={t_ms:.1f}ms, 10k-query={dom_query_ms:.1f}ms, axTree={ax_ms:.1f}ms")

        await client.close()

        # Compile results
        results = {
            "contender": "raw_cdp",
            "environment": "local",
            "headed": headed,
            "iterations": iterations,
            "cold_launch_ms": round(t_launch, 2),
            "navigation_ms": calc_stats(nav_times),
            "click_latency_ms": calc_stats(click_times),
            "type_50_chars_ms": calc_stats(type_times),
            "scroll_dispatch_ms": calc_stats(scroll_times),
            "dom_10k_query_ms": calc_stats(dom_query_times),
            "axtree_extraction_ms": calc_stats(axtree_times),
            "avg_axtree_nodes": int(statistics.mean(axtree_node_counts)) if axtree_node_counts else 0,
            "spa_filter_ms": calc_stats(spa_filter_times),
            "success": True,
        }

        # Save to results/raw/
        out_dir = PROJECT_ROOT / "results" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "raw_cdp_local.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[Raw CDP] Local benchmark complete! Saved results to {out_file}")
        print("--------------------------------------------------")
        print(f"  Cold Launch:       {results['cold_launch_ms']} ms")
        print(f"  Click (p50/p95):   {results['click_latency_ms']['p50']} / {results['click_latency_ms']['p95']} ms")
        print(f"  Type 50c (p50):    {results['type_50_chars_ms']['p50']} ms")
        print(f"  10k Query (p50):   {results['dom_10k_query_ms']['p50']} ms")
        print(f"  AXTree Dump (p50): {results['axtree_extraction_ms']['p50']} ms ({results['avg_axtree_nodes']} nodes)")
        print("--------------------------------------------------")
        return results

    finally:
        chrome.stop()


def main():
    parser = argparse.ArgumentParser(description="Raw CDP Local Benchmark Runner")
    parser.add_argument("--headed", action="store_true", help="Launch headed Chrome window")
    parser.add_argument("--smoke", action="store_true", help="Run 1 iteration sanity check")
    parser.add_argument("--iterations", type=int, default=5, help="Number of benchmark iterations")
    parser.add_argument("--port", type=int, default=8765, help="Local test server port")
    args = parser.parse_args()

    # Start local test server
    server, _ = start_server(args.port)
    try:
        iters = 1 if args.smoke else args.iterations
        asyncio.run(run_benchmark(headed=args.headed, iterations=iters, server_port=args.port))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
