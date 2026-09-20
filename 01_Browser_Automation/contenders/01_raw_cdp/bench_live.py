"""
Live website benchmark for Raw CDP: Google Search & YouTube.
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

from cdp_client import ChromeProcess, CDPClient, get_page_ws_url


async def run_live_benchmark(headed: bool = False):
    chrome = ChromeProcess(port=9222, headless=not headed)
    print(f"\n[Raw CDP Live] Launching Chrome (headed={headed})...")
    chrome.start()

    results = {
        "contender": "raw_cdp",
        "environment": "live",
        "headed": headed,
        "google_search": {},
        "youtube": {},
        "success": False
    }

    try:
        ws_url = await get_page_ws_url(9222)
        client = CDPClient(ws_url)
        await client.connect()
        print("[Raw CDP Live] Connected to Chrome Page target.")

        # ==============================================================
        # Task 1: Google Search
        # ==============================================================
        print("\n[Raw CDP Live] Task 1: Google Search Pipeline...")
        t0_g = time.perf_counter_ns()
        nav_g_ms = await client.navigate("https://www.google.com", timeout=15.0)

        # Handle cookie consent banner if present
        await client.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const acceptBtn = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('I agree') || b.textContent.includes('Tout accepter'));
                if (acceptBtn) acceptBtn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        # Type query
        search_selector = "textarea[name='q'], input[name='q']"
        t0_type = time.perf_counter_ns()
        await client.type_text(search_selector, "browser automation speed benchmark")
        type_g_ms = (time.perf_counter_ns() - t0_type) / 1_000_000.0

        # Press Enter
        await client.press_key("Enter", "Enter", 13)

        # Wait for search results container
        t0_wait = time.perf_counter_ns()
        results_found = False
        organic_results = []
        for _ in range(60):
            res = await client.evaluate("""
                (() => {
                    const items = Array.from(document.querySelectorAll('#search h3, #rso h3')).slice(0, 5);
                    return items.map(h => ({
                        title: h.textContent,
                        link: h.closest('a') ? h.closest('a').href : ''
                    }));
                })()
            """)
            if res and len(res) > 0:
                organic_results = res
                results_found = True
                break
            await asyncio.sleep(0.1)

        wait_g_ms = (time.perf_counter_ns() - t0_wait) / 1_000_000.0
        total_g_ms = (time.perf_counter_ns() - t0_g) / 1_000_000.0

        results["google_search"] = {
            "nav_ms": round(nav_g_ms, 2),
            "type_ms": round(type_g_ms, 2),
            "wait_results_ms": round(wait_g_ms, 2),
            "total_ms": round(total_g_ms, 2),
            "results_count": len(organic_results),
            "success": results_found,
            "top_result": organic_results[0]["title"] if organic_results else None
        }
        print(f"  Google Search completed in {total_g_ms:.1f}ms. Top result: {results['google_search']['top_result']}")

        # ==============================================================
        # Task 2: YouTube Search & Video Interaction
        # ==============================================================
        print("\n[Raw CDP Live] Task 2: YouTube Search & Video Interaction...")
        t0_y = time.perf_counter_ns()
        nav_y_ms = await client.navigate("https://www.youtube.com", timeout=20.0)

        # Handle YouTube consent popup if present
        await client.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button, ytd-button-renderer'));
                const consent = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('Reject all') || b.textContent.includes('I agree'));
                if (consent) consent.click();
            })()
        """)
        await asyncio.sleep(1.0)

        # Search box
        yt_input_sel = "input#search, input[name='search_query']"
        # Wait for search box to appear
        for _ in range(40):
            has_input = await client.evaluate(f"document.querySelector(\"{yt_input_sel}\") !== null")
            if has_input:
                break
            await asyncio.sleep(0.1)

        t0_y_type = time.perf_counter_ns()
        await client.type_text(yt_input_sel, "lofi coding music")
        type_y_ms = (time.perf_counter_ns() - t0_y_type) / 1_000_000.0

        # Press Enter
        await client.press_key("Enter", "Enter", 13)

        # Wait for video results
        t0_y_results = time.perf_counter_ns()
        video_clicked = False
        first_video_title = None
        for _ in range(60):
            video_info = await client.evaluate("""
                (() => {
                    const v = document.querySelector('ytd-video-renderer #video-title');
                    if (v) return { title: v.textContent.trim(), text: v.innerText };
                    return null;
                })()
            """)
            if video_info:
                first_video_title = video_info.get("title")
                # Click first video
                await client.click("ytd-video-renderer #video-title")
                video_clicked = True
                break
            await asyncio.sleep(0.1)

        wait_y_results_ms = (time.perf_counter_ns() - t0_y_results) / 1_000_000.0

        # Wait for video element player ready
        player_ready = False
        t0_player = time.perf_counter_ns()
        for _ in range(50):
            state = await client.evaluate("""
                (() => {
                    const video = document.querySelector('video.html5-main-video');
                    if (video && video.readyState >= 1) return true;
                    return false;
                })()
            """)
            if state:
                player_ready = True
                break
            await asyncio.sleep(0.1)
        player_wait_ms = (time.perf_counter_ns() - t0_player) / 1_000_000.0
        total_y_ms = (time.perf_counter_ns() - t0_y) / 1_000_000.0

        results["youtube"] = {
            "nav_ms": round(nav_y_ms, 2),
            "type_ms": round(type_y_ms, 2),
            "wait_results_ms": round(wait_y_results_ms, 2),
            "player_ready_ms": round(player_wait_ms, 2),
            "total_ms": round(total_y_ms, 2),
            "first_video": first_video_title,
            "success": video_clicked and player_ready
        }
        print(f"  YouTube completed in {total_y_ms:.1f}ms. Video: {first_video_title}")

        results["success"] = results["google_search"]["success"] and results["youtube"]["success"]
        await client.close()

        # Save results
        out_dir = PROJECT_ROOT / "results" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "raw_cdp_live.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[Raw CDP Live] Saved live benchmark results to {out_file}")
        return results

    finally:
        chrome.stop()


def main():
    parser = argparse.ArgumentParser(description="Raw CDP Live Sites Benchmark")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    args = parser.parse_args()

    asyncio.run(run_live_benchmark(headed=args.headed))


if __name__ == "__main__":
    main()
