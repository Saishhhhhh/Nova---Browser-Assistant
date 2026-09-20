"""
Live website benchmark for nodriver: Google Search & YouTube.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add project roots to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

import nodriver as uc


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


async def run_live_benchmark(headed: bool = False):
    exe = find_chrome_executable()
    print(f"\n[nodriver Live] Launching browser (headed={headed})...")
    browser = await uc.start(
        headless=not headed,
        browser_executable_path=exe,
        browser_args=["--window-size=1280,800"]
    )

    results = {
        "contender": "nodriver",
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
        print("\n[nodriver Live] Task 1: Google Search Pipeline...")
        t0_g = time.perf_counter_ns()
        tab = await browser.get("https://www.google.com")
        nav_g_ms = (time.perf_counter_ns() - t0_g) / 1_000_000.0

        # Dismiss cookies banner
        await tab.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const acceptBtn = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('I agree'));
                if (acceptBtn) acceptBtn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        # Locate search box
        search_box = await tab.select("textarea[name='q'], input[name='q']")
        t0_type = time.perf_counter_ns()
        await search_box.send_keys("browser automation speed benchmark\n")
        type_g_ms = (time.perf_counter_ns() - t0_type) / 1_000_000.0

        # Wait for results
        t0_wait = time.perf_counter_ns()
        organic_results = []
        for _ in range(60):
            items = await tab.evaluate("""
                (() => {
                    const nodes = Array.from(document.querySelectorAll('#search h3, #rso h3')).slice(0, 5);
                    return nodes.map(h => ({
                        title: h.textContent,
                        link: h.closest('a') ? h.closest('a').href : ''
                    }));
                })()
            """)
            if items and len(items) > 0:
                organic_results = items
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
            "success": len(organic_results) > 0,
            "top_result": organic_results[0]["title"] if organic_results else None
        }
        print(f"  Google Search completed in {total_g_ms:.1f}ms. Top result: {results['google_search']['top_result']}")

        # ==============================================================
        # Task 2: YouTube Search & Video Interaction
        # ==============================================================
        print("\n[nodriver Live] Task 2: YouTube Search & Video Interaction...")
        t0_y = time.perf_counter_ns()
        tab_yt = await browser.get("https://www.youtube.com")
        nav_y_ms = (time.perf_counter_ns() - t0_y) / 1_000_000.0

        await tab_yt.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const consent = btns.find(b => b.textContent.includes('Accept all') || b.textContent.includes('Reject all'));
                if (consent) consent.click();
            })()
        """)
        await asyncio.sleep(1.0)

        # Search box
        yt_input = await tab_yt.select("input#search, input[name='search_query']")
        t0_y_type = time.perf_counter_ns()
        await yt_input.send_keys("lofi coding music\n")
        type_y_ms = (time.perf_counter_ns() - t0_y_type) / 1_000_000.0

        # Wait for video result
        t0_y_results = time.perf_counter_ns()
        video_clicked = False
        first_video_title = None

        for _ in range(60):
            video_info = await tab_yt.evaluate("""
                (() => {
                    const v = document.querySelector('ytd-video-renderer #video-title');
                    if (v) return { title: v.textContent.trim() };
                    return null;
                })()
            """)
            if video_info:
                first_video_title = video_info.get("title")
                v_el = await tab_yt.select("ytd-video-renderer #video-title")
                if v_el:
                    await v_el.click()
                    video_clicked = True
                    break
            await asyncio.sleep(0.1)

        wait_y_results_ms = (time.perf_counter_ns() - t0_y_results) / 1_000_000.0

        # Wait for video player
        player_ready = False
        t0_player = time.perf_counter_ns()
        for _ in range(50):
            state = await tab_yt.evaluate("""
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
        browser.stop()

        out_dir = PROJECT_ROOT / "results" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "nodriver_live.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n[nodriver Live] Saved live benchmark results to {out_file}")
        return results

    except Exception:
        browser.stop()
        raise


def main():
    parser = argparse.ArgumentParser(description="nodriver Live Sites Benchmark")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser window")
    args = parser.parse_args()

    uc.loop().run_until_complete(run_live_benchmark(headed=args.headed))


if __name__ == "__main__":
    main()
