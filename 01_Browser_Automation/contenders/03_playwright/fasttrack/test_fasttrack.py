"""
Interactive Headed Test Runner for Playwright Fast-Track Skills.
Launches a visible Chrome window and demonstrates fast-tracked tasks with visual highlights.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Add project roots
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(PROJECT_ROOT))

# Reconfigure stdout to handle UTF-8 cleanly on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from fasttrack.engine import FastPlaywrightEngine
from fasttrack.skills.youtube import YouTubeSkill
from fasttrack.skills.amazon import AmazonSkill
from fasttrack.skills.google import GoogleSkill
from fasttrack.skills.general import GeneralSkill
from benchmark_harness.server.app import start_server


async def demo_youtube(engine: FastPlaywrightEngine, query: str = "lofi coding beats", delay: float = 2.0):
    yt = YouTubeSkill(engine)
    print("\n" + "="*60)
    print(f">> [DEMO: YOUTUBE FAST-TRACK] Query: '{query}'")
    print("="*60)

    # 1. Direct deep-link search
    t0 = time.perf_counter()
    nav_ms = await yt.search(query)
    print(f"  [1] Direct deep-link navigation: {nav_ms:.1f}ms")
    await asyncio.sleep(delay)

    # 2. Play first video
    res = await yt.play_first_video()
    print(f"  [2] Auto-play first video: '{res['title']}' (click={res['click_ms']:.1f}ms)")
    await asyncio.sleep(delay + 1.0)

    # 3. Media control: Pause
    p_res = await yt.toggle_play_pause()
    print(f"  [3] Instant PAUSE (shortcut 'k'): {p_res['latency_ms']:.1f}ms -> Paused={p_res['state'].get('paused')}")
    await asyncio.sleep(delay)

    # 4. Media control: Seek forward +10s
    s_res = await yt.seek_forward()
    print(f"  [4] Instant SEEK +10s (shortcut 'l'): {s_res['latency_ms']:.1f}ms -> Time={s_res['state'].get('currentTime')}s")
    await asyncio.sleep(delay)

    # 5. Media control: Resume Play
    r_res = await yt.toggle_play_pause()
    print(f"  [5] Instant RESUME (shortcut 'k'): {r_res['latency_ms']:.1f}ms -> Paused={r_res['state'].get('paused')}")
    await asyncio.sleep(delay)

    # 6. Media control: Toggle Mute
    m_res = await yt.toggle_mute()
    print(f"  [6] Instant MUTE (shortcut 'm'): {m_res['latency_ms']:.1f}ms -> Muted={m_res['state'].get('muted')}")
    await asyncio.sleep(delay)


async def demo_amazon(engine: FastPlaywrightEngine, query: str = "mechanical keyboard", delay: float = 2.0):
    amz = AmazonSkill(engine)
    print("\n" + "="*60)
    print(f">> [DEMO: AMAZON FAST-TRACK] Query: '{query}' (Sorted: Price Low to High)")
    print("="*60)

    # 1. Direct search with price sort parameter
    nav_ms = await amz.search_and_sort(query, sort_by="price_low_to_high")
    print(f"  [1] Direct sorted navigation: {nav_ms:.1f}ms")
    await asyncio.sleep(delay)

    # 2. Extract top products in-memory
    t0 = time.perf_counter()
    products = await amz.extract_top_products(limit=3)
    extract_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  [2] Instant in-memory product extraction: {extract_ms:.1f}ms")
    for idx, p in enumerate(products, 1):
        print(f"      #{idx}: {p['title'][:45]}... | {p['price']} | Rating: {p['rating']}")
    await asyncio.sleep(delay)


async def demo_google(engine: FastPlaywrightEngine, query: str = "fastest browser automation", delay: float = 2.0):
    g = GoogleSkill(engine)
    print("\n" + "="*60)
    print(f">> [DEMO: GOOGLE FAST-TRACK] Query: '{query}'")
    print("="*60)

    nav_ms = await g.search(query)
    print(f"  [1] Direct search navigation: {nav_ms:.1f}ms")
    await asyncio.sleep(delay)

    results = await g.extract_results(limit=3)
    print(f"  [2] Organic result extraction (<20ms):")
    for r in results:
        print(f"      #{r['index']}: {r['title'][:40]}... -> {r['link'][:45]}...")
    await asyncio.sleep(delay)


async def demo_general_hybrid(engine: FastPlaywrightEngine, delay: float = 2.0, server_port: int = 8765):
    gen = GeneralSkill(engine)
    print("\n" + "="*60)
    print(">> [DEMO: GENERAL HYBRID SNAPSHOTTER] Local Action Fixture with Visual Badges")
    print("="*60)

    base_url = f"http://127.0.0.1:{server_port}"
    nav_ms = await engine.navigate_direct(f"{base_url}/actions.html")
    print(f"  [1] Navigated to local test fixture: {nav_ms:.1f}ms")
    await asyncio.sleep(1.0)

    # Extract interactive snapshot with visual numbered badges
    t0 = time.perf_counter()
    items = await gen.get_interactive_snapshot()
    snap_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  [2] Injected snapshotter found {len(items)} interactive elements in {snap_ms:.1f}ms:")
    for el in items[:5]:
        print(f"      [{el['index']}] <{el['tag']}> \"{el['text']}\"")
    print("      (Look at the browser: yellow badges [1], [2] are rendered on screen!)")
    await asyncio.sleep(delay + 1.0)

    # Click element [1]
    click_ms = await gen.click_by_index(1)
    print(f"  [3] Clicked element [1] with visual green ripple: {click_ms:.1f}ms")
    await asyncio.sleep(delay)

    # Type into element [2]
    await gen.type_by_index(2, "Hello from Fast-Track Speech Agent!")
    print(f"  [4] Typed into input [2]")
    await asyncio.sleep(delay)


async def main():
    parser = argparse.ArgumentParser(description="Playwright Fast-Track Headed Visual Test Runner")
    parser.add_argument("--skill", choices=["youtube", "amazon", "google", "general", "all"], default="all", help="Skill to test")
    parser.add_argument("--query", type=str, default=None, help="Custom search query")
    parser.add_argument("--delay", type=float, default=1.8, help="Delay (seconds) between steps to allow visual observation")
    parser.add_argument("--port", type=int, default=8765, help="Local test server port")
    parser.add_argument("--no-server", action="store_true", help="Skip starting local test server")
    args = parser.parse_args()

    server = None
    if args.skill in ("general", "all") and not args.no_server:
        server, _ = start_server(args.port)

    # Initialize headed engine
    engine = FastPlaywrightEngine(headed=True, viewport_width=1280, viewport_height=800)
    await engine.start()

    try:
        if args.skill in ("youtube", "all"):
            q = args.query or "3 AM Coding Session Lofi"
            await demo_youtube(engine, query=q, delay=args.delay)

        if args.skill in ("amazon", "all"):
            q = args.query or "wireless gaming mouse"
            await demo_amazon(engine, query=q, delay=args.delay)

        if args.skill in ("google", "all"):
            q = args.query or "playwright fastest browser automation"
            await demo_google(engine, query=q, delay=args.delay)

        if args.skill in ("general", "all"):
            await demo_general_hybrid(engine, delay=args.delay, server_port=args.port)

        print("\n" + "="*60)
        print("✅ [ALL DEMOS COMPLETED] Keeping browser open for 4 seconds...")
        print("="*60)
        await asyncio.sleep(4.0)

    finally:
        await engine.stop()
        if server:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
