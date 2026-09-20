"""
Benchmark runner: nodriver against local test server fixtures.
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

import nodriver as uc
from benchmark_harness.server.app import start_server


def find_chrome_executable() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


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
    exe = find_chrome_executable()

    print(f"\n[nodriver] Launching browser (headed={headed})...")
    t_start = time.perf_counter()
    browser = await uc.start(
        headless=not headed,
        browser_executable_path=exe,
        browser_args=["--window-size=1280,800", "--no-default-browser-check"]
    )
    t_launch = (time.perf_counter() - t_start) * 1000.0
    print(f"[nodriver] Browser launched in {t_launch:.1f} ms")

    try:
        tab = await browser.get(f"{base_url}/actions.html")
        print("[nodriver] Page loaded.")

        nav_times = []
        click_times = []
        type_times = []
        scroll_times = []
        dom_query_times = []
        axtree_times = []
        axtree_node_counts = []
        spa_filter_times = []

        print(f"\n[nodriver] Running {iterations} iteration(s)...")

        for it in range(1, iterations + 1):
            # 1. Navigation
            t0 = time.perf_counter_ns()
            await tab.get(f"{base_url}/actions.html")
            for _ in range(50):
                ready = await tab.evaluate("window.location.pathname.endsWith('actions.html') && window.__fixture_ready === true")
                if ready:
                    break
                await asyncio.sleep(0.05)
            nav_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            nav_times.append(nav_ms)

            # 2. Click
            btn = await tab.select("#btn-click-target")
            t0 = time.perf_counter_ns()
            await btn.click()
            c_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            click_times.append(c_ms)

            click_text = await tab.evaluate("document.getElementById('click-status').textContent")
            assert "SUCCESS" in (click_text or ""), f"Click verification failed: {click_text}"

            # 3. Typing
            test_phrase = "nodriver benchmark keystroke latency test 12345"
            inp = await tab.select("#input-text-target")
            t0 = time.perf_counter_ns()
            await inp.send_keys(test_phrase)
            t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            type_times.append(t_ms)

            val = await tab.evaluate("document.getElementById('input-text-target').value")
            assert test_phrase in (val or ""), f"Typing verification failed: {val}"

            # 4. Scroll
            t0 = time.perf_counter_ns()
            await tab.evaluate("window.scrollTo(0, 1400)")
            s_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            scroll_times.append(s_ms)

            # 5. Heavy DOM (10k nodes)
            await tab.get(f"{base_url}/dom_heavy.html")
            for _ in range(100):
                ready = await tab.evaluate("window.location.pathname.endsWith('dom_heavy.html') && window.__total_nodes === 10000")
                if ready:
                    break
                await asyncio.sleep(0.05)

            # Query 10k DOM needle
            t0 = time.perf_counter_ns()
            needle = await tab.select("#needle-btn")
            dom_query_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            dom_query_times.append(dom_query_ms)
            assert needle is not None, "Failed to query #needle-btn"

            # Accessibility Tree via CDP domain
            t0 = time.perf_counter_ns()
            ax_data = await tab.send(uc.cdp.accessibility.get_full_ax_tree())
            ax_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            axtree_times.append(ax_ms)
            nodes = getattr(ax_data, "nodes", []) if hasattr(ax_data, "nodes") else []
            axtree_node_counts.append(len(nodes))

            # 6. Dynamic SPA Hydration & Filter
            await tab.get(f"{base_url}/dynamic_spa.html")
            for _ in range(50):
                ready = await tab.evaluate("window.location.pathname.endsWith('dynamic_spa.html') && window.__fixture_ready === true")
                if ready:
                    break
                await asyncio.sleep(0.05)

            # Wait for delayed hydration button
            for _ in range(30):
                hydrated = await tab.evaluate("document.getElementById('hydrated-action-btn') !== null")
                if hydrated:
                    break
                await asyncio.sleep(0.05)

            # Filter products
            search_inp = await tab.select("#spa-search-input")
            t0 = time.perf_counter_ns()
            await search_inp.send_keys("Laptop")
            filter_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            spa_filter_times.append(filter_ms)

            print(f"  Iteration {it}/{iterations} done: click={c_ms:.1f}ms, type={t_ms:.1f}ms, 10k-query={dom_query_ms:.1f}ms, axTree={ax_ms:.1f}ms")

        browser.stop()

        results = {
            "contender": "nodriver",
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

        out_dir = PROJECT_ROOT / "results" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "nodriver_local.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[nodriver] Local benchmark complete! Saved results to {out_file}")
        print("--------------------------------------------------")
        print(f"  Cold Launch:       {results['cold_launch_ms']} ms")
        print(f"  Click (p50/p95):   {results['click_latency_ms']['p50']} / {results['click_latency_ms']['p95']} ms")
        print(f"  Type 50c (p50):    {results['type_50_chars_ms']['p50']} ms")
        print(f"  10k Query (p50):   {results['dom_10k_query_ms']['p50']} ms")
        print(f"  AXTree Dump (p50): {results['axtree_extraction_ms']['p50']} ms ({results['avg_axtree_nodes']} nodes)")
        print("--------------------------------------------------")
        return results

    except Exception:
        browser.stop()
        raise


def main():
    parser = argparse.ArgumentParser(description="nodriver Local Benchmark Runner")
    parser.add_argument("--headed", action="store_true", help="Launch headed Chrome window")
    parser.add_argument("--smoke", action="store_true", help="Run 1 iteration sanity check")
    parser.add_argument("--iterations", type=int, default=5, help="Number of benchmark iterations")
    parser.add_argument("--port", type=int, default=8765, help="Local test server port")
    args = parser.parse_args()

    server, _ = start_server(args.port)
    try:
        iters = 1 if args.smoke else args.iterations
        uc.loop().run_until_complete(run_benchmark(headed=args.headed, iterations=iters, server_port=args.port))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
