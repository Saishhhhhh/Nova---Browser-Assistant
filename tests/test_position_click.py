"""End to end through the fast path: the click really happens (no model calls).

  python -m tests.test_position_click
"""
import asyncio

from browser_use import Browser
from mycroft.dom_fastpath import FastPath

async def main():
    b = Browser(headless=True, keep_alive=True, window_size={"width": 1280, "height": 800}, viewport={"width": 1280, "height": 800})
    await b.start()
    fp = FastPath(b, picker=None)
    fails = 0
    async def check(cmd, expect, start="https://books.toscrape.com"):
        nonlocal fails
        r = await fp.run(f"go to {start}")
        await asyncio.sleep(1.5)
        r = await fp.run(cmd)
        await asyncio.sleep(1.5)
        url = await b.get_current_page_url()
        ok = r.handled and not r.error and expect in url
        fails += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {cmd!r:42} -> {url[-48:]}   ({r.detail[:70]})")
    await check("click the second book", "tipping-the-velvet")
    await check("click the last book", "sharp-objects")
    await check("click the link at the top right", "/login", start="https://quotes.toscrape.com")
    await check("click the third link", "/tag/love", start="https://quotes.toscrape.com")
    await b.kill()
    print("ALL PASSED" if not fails else f"{fails} FAILED")
asyncio.run(main())
