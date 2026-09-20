"""
Live website benchmark for Playwright: Google Search & YouTube.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add project roots to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright


async def run_live_benchmark(headed: bool = False):
    print(f"\n[Playwright Live] Launching Chrome (channel='chrome', headed={headed})...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        channel="chrome",
        headless=not headed,
        args=["--window-size=1280,800"]
    )
    context = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()

    results = {
        "contender": "playwright",
        "environment": "live",
        "headed": headed,
        "google_search": {},
        "youtube": {},
        "success": False
    }

    try:
        # ==============================================================
        # Task 1: Google Search
        # ==============================================================
        print("\n[Playwright Live] Task 1: Google Search Pipeline...")
        t0_g = time.perf_counter_ns()
        await page.goto("https://www.google.com", wait_until="domcontentloaded")
        nav_g_ms = (time.perf_counter_ns() - t0_g) / 1_000_000.0

        # Dismiss cookies banner
        try:
            accept_btn = page.locator("button:has-text('Accept all'), button:has-text('I agree'), button:has-text('Tout accepter')")
            if await accept_btn.count() > 0:
                await accept_btn.first.click(timeout=1000)
        except Exception:
            pass

        # Locate search box
        search_box = page.locator("textarea[name='q'], input[name='q']")
        t0_type = time.perf_counter_ns()
        await search_box.press_sequentially("browser automation speed benchmark", delay=0)
        await search_box.press("Enter")
        type_g_ms = (time.perf_counter_ns() - t0_type) / 1_000_000.0

        # Wait for results
        t0_wait = time.perf_counter_ns()
        results_container = page.locator("#search h3, #rso h3")
        await results_container.first.wait_for(state="visible", timeout=10000)
        wait_g_ms = (time.perf_counter_ns() - t0_wait) / 1_000_000.0

        # Extract top 5
        items = await results_container.all()
        organic_results = []
        for el in items[:5]:
            title = await el.text_content()
            organic_results.append({"title": (title or "").strip()})

        total_g_ms = (time.perf_counter_ns() - t0_g) / 1_000_000.0

        results["google_search"] = {
            "nav_ms": round(nav_g_ms, 2),
            "type_ms": round(type_g_ms, 2),
            "wait_results_ms": round(wait_g_ms, 2),
            "total_ms": round(total_g_ms, 2),
            "results_count": len(organic_results),
            "success": len(organic_results) > 0,
            "top_result": organic_results[0]["title"] if organic_results else None
        }
        print(f"  Google Search completed in {total_g_ms:.1f}ms. Top result: {results['google_search']['top_result']}")

        # ==============================================================
        # Task 2: YouTube Search & Video Interaction
        # ==============================================================
        print("\n[Playwright Live] Task 2: YouTube Search & Video Interaction...")
        t0_y = time.perf_counter_ns()
        await page.goto("https://www.youtube.com", wait_until="domcontentloaded")
        nav_y_ms = (time.perf_counter_ns() - t0_y) / 1_000_000.0

        # Dismiss consent popup
        try:
            consent_btn = page.locator("button:has-text('Accept all'), button:has-text('Reject all')")
            if await consent_btn.count() > 0:
                await consent_btn.first.click(timeout=1500)
        except Exception:
            pass

        # Search box
        yt_input = page.locator("input#search, input[name='search_query']").first
        await yt_input.wait_for(state="visible", timeout=10000)
        t0_y_type = time.perf_counter_ns()
        await yt_input.press_sequentially("lofi coding music", delay=0)
        await yt_input.press("Enter")
        type_y_ms = (time.perf_counter_ns() - t0_y_type) / 1_000_000.0

        # Wait for video result
        t0_y_results = time.perf_counter_ns()
        video_title_el = page.locator("ytd-video-renderer #video-title").first
        await video_title_el.wait_for(state="visible", timeout=15000)
        wait_y_results_ms = (time.perf_counter_ns() - t0_y_results) / 1_000_000.0
        first_video_title = (await video_title_el.text_content() or "").strip()

        # Click video
        await video_title_el.click()

        # Wait for video player
        t0_player = time.perf_counter_ns()
        video_player = page.locator("video.html5-main-video")
        await video_player.wait_for(state="attached", timeout=15000)
        await page.wait_for_function("() => { const v = document.querySelector('video.html5-main-video'); return v && v.readyState >= 1; }")
        player_wait_ms = (time.perf_counter_ns() - t0_player) / 1_000_000.0
        total_y_ms = (time.perf_counter_ns() - t0_y) / 1_000_000.0

        results["youtube"] = {
            "nav_ms": round(nav_y_ms, 2),
            "type_ms": round(type_y_ms, 2),
            "wait_results_ms": round(wait_y_results_ms, 2),
            "player_ready_ms": round(player_wait_ms, 2),
            "total_ms": round(total_y_ms, 2),
            "first_video": first_video_title,
            "success": True
        }
        print(f"  YouTube completed in {total_y_ms:.1f}ms. Video: {first_video_title}")

        results["success"] = results["google_search"]["success"] and results["youtube"]["success"]
        await browser.close()
        await pw.stop()

        out_dir = PROJECT_ROOT / "results" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "playwright_live.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[Playwright Live] Saved live benchmark results to {out_file}")
        return results

    except Exception:
        await browser.close()
        await pw.stop()
        raise


def main():
    parser = argparse.ArgumentParser(description="Playwright Live Sites Benchmark")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    args = parser.parse_args()

    asyncio.run(run_live_benchmark(headed=args.headed))


if __name__ == "__main__":
    main()
