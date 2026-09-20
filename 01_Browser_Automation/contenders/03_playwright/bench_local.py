"""
Benchmark runner: Playwright against local test server fixtures.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

# Add project roots to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright
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

    print(f"\n[Playwright] Launching Chrome (channel='chrome', headed={headed})...")
    t_start = time.perf_counter()
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        channel="chrome",
        headless=not headed,
        args=["--window-size=1280,800"]
    )
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    t_launch = (time.perf_counter() - t_start) * 1000.0
    print(f"[Playwright] Browser launched in {t_launch:.1f} ms")

    try:
        nav_times = []
        click_times = []
        type_times = []
        scroll_times = []
        dom_query_times = []
        axtree_times = []
        axtree_node_counts = []
        spa_filter_times = []

        print(f"\n[Playwright] Running {iterations} iteration(s)...")

        for it in range(1, iterations + 1):
            # 1. Navigation
            t0 = time.perf_counter_ns()
            await page.goto(f"{base_url}/actions.html", wait_until="load")
            await page.wait_for_function("() => window.location.pathname.endsWith('actions.html') && window.__fixture_ready === true")
            nav_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            nav_times.append(nav_ms)

            # 2. Click (Playwright locator click with actionability checks)
            t0 = time.perf_counter_ns()
            await page.locator("#btn-click-target").click()
            c_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            click_times.append(c_ms)

            click_text = await page.locator("#click-status").text_content()
            assert "SUCCESS" in (click_text or ""), f"Click verification failed: {click_text}"

            # 3. Typing (50 chars with keystroke emulation)
            test_phrase = "Playwright benchmark keystroke latency test 12345"
            inp = page.locator("#input-text-target")
            t0 = time.perf_counter_ns()
            await inp.press_sequentially(test_phrase, delay=0)
            t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            type_times.append(t_ms)

            val = await inp.input_value()
            assert test_phrase in (val or ""), f"Typing verification failed: {val}"

            # 4. Scroll
            t0 = time.perf_counter_ns()
            await page.mouse.wheel(0, 1400)
            s_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            scroll_times.append(s_ms)

            # 5. Heavy DOM (10k nodes)
            await page.goto(f"{base_url}/dom_heavy.html", wait_until="load")
            await page.wait_for_function("() => window.location.pathname.endsWith('dom_heavy.html') && window.__total_nodes === 10000")

            # Query 10k DOM needle
            needle = page.locator("#needle-btn")
            t0 = time.perf_counter_ns()
            box = await needle.bounding_box()
            dom_query_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            dom_query_times.append(dom_query_ms)
            assert box is not None, "Failed to query #needle-btn bounding box"

            # Accessibility Tree Extraction via CDP Session
            t0 = time.perf_counter_ns()
            cdp = await context.new_cdp_session(page)
            ax_res = await cdp.send("Accessibility.getFullAXTree")
            ax_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            axtree_times.append(ax_ms)
            nodes = ax_res.get("nodes", []) if isinstance(ax_res, dict) else []
            axtree_node_counts.append(len(nodes))
            await cdp.detach()

            # 6. Dynamic SPA Hydration & Filter
            await page.goto(f"{base_url}/dynamic_spa.html", wait_until="load")
            await page.wait_for_function("() => window.location.pathname.endsWith('dynamic_spa.html') && window.__fixture_ready === true")

            # Wait for delayed hydration button
            hydrated_btn = page.locator("#hydrated-action-btn")
            await hydrated_btn.wait_for(state="visible", timeout=5000)

            # Filter products
            search_inp = page.locator("#spa-search-input")
            t0 = time.perf_counter_ns()
            await search_inp.press_sequentially("Laptop", delay=0)
            filter_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            spa_filter_times.append(filter_ms)

            print(f"  Iteration {it}/{iterations} done: click={c_ms:.1f}ms, type={t_ms:.1f}ms, 10k-query={dom_query_ms:.1f}ms, axTree={ax_ms:.1f}ms")

        await browser.close()
        await pw.stop()

        results = {
            "contender": "playwright",
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
        out_file = out_dir / "playwright_local.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[Playwright] Local benchmark complete! Saved results to {out_file}")
        print("--------------------------------------------------")
        print(f"  Cold Launch:       {results['cold_launch_ms']} ms")
        print(f"  Click (p50/p95):   {results['click_latency_ms']['p50']} / {results['click_latency_ms']['p95']} ms")
        print(f"  Type 50c (p50):    {results['type_50_chars_ms']['p50']} ms")
        print(f"  10k Query (p50):   {results['dom_10k_query_ms']['p50']} ms")
        print(f"  AXTree Dump (p50): {results['axtree_extraction_ms']['p50']} ms ({results['avg_axtree_nodes']} nodes)")
        print("--------------------------------------------------")
        return results

    except Exception:
        await browser.close()
        await pw.stop()
        raise


def main():
    parser = argparse.ArgumentParser(description="Playwright Local Benchmark Runner")
    parser.add_argument("--headed", action="store_true", help="Launch headed Chrome window")
    parser.add_argument("--smoke", action="store_true", help="Run 1 iteration sanity check")
    parser.add_argument("--iterations", type=int, default=5, help="Number of benchmark iterations")
    parser.add_argument("--port", type=int, default=8765, help="Local test server port")
    args = parser.parse_args()

    server, _ = start_server(args.port)
    try:
        iters = 1 if args.smoke else args.iterations
        asyncio.run(run_benchmark(headed=args.headed, iterations=iters, server_port=args.port))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
