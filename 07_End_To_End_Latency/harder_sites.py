"""Harder-sites round: 14 commands a person would say, on four heavy public sites, through the real router.

  python harder_sites.py              # visible browser, real model and agent calls (a few cents)
  python harder_sites.py --headless
  python harder_sites.py --only github,youtube

Not a benchmark: a list of what breaks. Each command has an automatic check (the URL it should end on, or for a question
that the answer is not empty and has the expected shape). On a failed check a screenshot and the page title are saved,
so a captcha, a cookie banner or a wrong click is visible. No login is used anywhere.
"""
import argparse
import asyncio
import base64
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for sub in ("02_Reasoning_and_Routing", "01_Browser Automation"):
    sys.path.insert(0, str(ROOT / sub))

from browser_use import Browser  # noqa: E402
from config import EXTRACTION_MODEL, EXTRACTION_PROVIDER, get_browser_use_llm  # noqa: E402
from dom_fastpath import make_picker_from_env  # noqa: E402
from router import CommandRouter  # noqa: E402

# site -> [(command, check)]; a check is a function (url, answer) -> bool
HAS_PRICE = re.compile(r"(₹|rs\.?|inr|\$|£|€)\s?\d|\d[\d,]*\s?(rupees|dollars|pounds)", re.I)
SITES = {
    "amazon": [
        ("go to amazon.in", lambda u, a: "amazon.in" in u),
        ("search for MSI gaming monitor", lambda u, a: "k=" in u and "msi" in u.lower()),
        ("click the second result", lambda u, a: "/dp/" in u or "/gp/" in u),
        ("tell me the price of this product", lambda u, a: bool(HAS_PRICE.search(a))),
    ],
    "youtube": [
        ("go to youtube.com", lambda u, a: "youtube.com" in u),
        ("search for lofi hip hop beats", lambda u, a: "search_query" in u),
        ("click the first video", lambda u, a: "watch?v=" in u),
    ],
    "github": [
        ("go to github.com/microsoft/playwright", lambda u, a: "microsoft/playwright" in u),
        ("click issues", lambda u, a: u.rstrip("/").endswith("/issues") or "/issues?" in u),
        ("click the first issue", lambda u, a: re.search(r"/issues/\d+", u) is not None),
        ("tell me the title of this issue", lambda u, a: len(a.strip()) > 8),
    ],
    "flipkart": [
        ("go to flipkart.com", lambda u, a: "flipkart.com" in u),
        ("search for running shoes", lambda u, a: "search" in u and "running" in u.lower()),
        ("click the second product", lambda u, a: "/p/" in u),
    ],
}


# A fresh set, written before it was run and not tuned afterwards: sites and commands not used while building the fixes.
START = {}
FRESH = {
    "hackernews": [
        ("go to news.ycombinator.com", lambda u, a: "ycombinator.com" in u),
        ("click the first story", lambda u, a: "news.ycombinator.com" not in u or "item?id=" in u),
        ("go back", lambda u, a: "news.ycombinator.com" in u),
        ("click new", lambda u, a: "/newest" in u),
    ],
    "bbc": [
        ("go to bbc.com/news", lambda u, a: "bbc.com" in u or "bbc.co.uk" in u),
        ("click the first article", lambda u, a: ("bbc." in u) and (re.search(r"/(articles|live|videos|news)/[^/]+", u) is not None)
                                                 and not u.rstrip("/").endswith("/news")),
        ("tell me the headline of this article", lambda u, a: len(a.strip()) > 10),
    ],
    "ebay": [
        ("go to ebay.com", lambda u, a: "ebay.com" in u),
        ("search for mechanical keyboard", lambda u, a: "_nkw=" in u or "mechanical" in u.lower()),
        ("click the third result", lambda u, a: "/itm/" in u),
        ("tell me the price", lambda u, a: bool(HAS_PRICE.search(a))),
    ],
    "stackoverflow": [
        ("go to stackoverflow.com/questions", lambda u, a: "stackoverflow.com/questions" in u),
        ("click the first question", lambda u, a: re.search(r"/questions/\d+", u) is not None),
        ("scroll down", lambda u, a: True),
        ("tell me how many answers this question has", lambda u, a: re.search(r"\d", a) is not None),
    ],
}


async def main(only: list, headless: bool, fresh: bool = False) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kwargs = dict(headless=headless, no_viewport=True, keep_alive=True)
    if not headless:
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    browser = Browser(**kwargs)
    await browser.start()
    router = CommandRouter(
        browser, picker=make_picker_from_env(), agent_llm=get_browser_use_llm("cerebras"),
        extraction_llm=get_browser_use_llm(EXTRACTION_PROVIDER, EXTRACTION_MODEL) if EXTRACTION_PROVIDER else None,
        agent_max_steps=8, agent_timeout=90.0)
    shots = HERE / "results" / "harder_sites_screens"
    shots.mkdir(parents=True, exist_ok=True)
    rows = []
    for site, steps in (FRESH if fresh else SITES).items():
        if only and site not in only:
            continue
        print(f"\n=== {site}", flush=True)
        for n, (cmd, check) in enumerate(steps, 1):
            t = time.perf_counter()
            try:
                res = await asyncio.wait_for(router.run_command(cmd), 150)
                tier, handled, answer, detail = res.tier, res.ok, res.reply, res.detail
            except Exception as e:
                tier, handled, answer, detail = "error", False, "", f"{type(e).__name__}: {e}"[:160]
            ms = (time.perf_counter() - t) * 1000
            await asyncio.sleep(1.0)
            try:
                url = await browser.get_current_page_url()
                state = await browser.get_browser_state_summary(include_screenshot=True)
                title = state.title or ""
                shot = state.screenshot
            except Exception:
                url, title, shot = "", "", None
            ok = bool(check(url, answer)) and tier != "error"
            row = {"site": site, "command": cmd, "tier": tier, "router_ok": handled, "check_passed": ok,
                   "ms": round(ms), "url": url[:140], "title": title[:80], "answer": answer[:160], "detail": detail[:200]}
            if not ok and shot:
                path = shots / f"{site}_{n}.png"
                path.write_bytes(base64.b64decode(shot))
                row["screenshot"] = str(path.relative_to(HERE))
            rows.append(row)
            print(f"[{'PASS' if ok else 'FAIL'}] {cmd:<42} {tier:<7} {ms / 1000:5.1f} s  {title[:36]!r}"
                  + ("" if ok else f"\n        -> {url[:90]}\n        -> {detail[:150]}"), flush=True)
    await browser.kill()
    good = sum(r["check_passed"] for r in rows)
    print(f"\n{good} of {len(rows)} commands passed their check")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / ("harder_sites_fresh.json" if fresh else "harder_sites.json")).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="the second set: four sites not used while building the fixes")
    a = ap.parse_args()
    sys.exit(asyncio.run(main([s for s in a.only.split(",") if s], a.headless, a.fresh)))
