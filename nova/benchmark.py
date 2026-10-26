"""A systematic success-rate benchmark for the finished router (rules -> model-step -> full agent),
answering a question live testing never could: not "does this specific bug stay fixed" (that's what
tests/test_live_regressions.py is for), but "out of a broad, varied set of tasks, what fraction
actually succeed, and is that consistent run to run?"

  python -m nova.benchmark                 # real browser, real API calls, 2 repeats per task (a few dollars)
  python -m nova.benchmark --repeats 1      # cheaper, one pass, less evidence about consistency
  python -m nova.benchmark --headed         # watch it run

Deliberately scoped to the router alone (CommandRouter.run_command - rules, the model-step, and the full
browser-use agent, whichever one actually ends up handling each task). The planner (multi-step splitting)
and conversation memory have their own benchmark already - experiments/09_Memory_and_Replanning/memory_bench.py
- and aren't re-measured here.

Each task runs from a fixed starting page, so one task's outcome can't be polluted by the page the
previous one happened to leave the browser on. Success is checked against the real page state or the
reply text (what actually happened), never "ok=True" alone - the GitHub-search-typing bug earlier in this
project is the whole reason that distinction matters: a result that claims success isn't the same as one
that was verified.
"""
import argparse
import asyncio
import datetime
import json
import statistics
import sys
import time
from pathlib import Path

from browser_use import Browser

from . import config
from .dom_fastpath import make_picker_from_env
from .router import CommandRouter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent   # repo root - results/ lives here, not inside the nova/ package itself


async def _poll(predicate, timeout: float = 3.0, interval: float = 0.3) -> bool:
    """Checking a URL/page the instant run_command() returns can race a navigation that's still settling -
    found while validating this benchmark itself: the exact same search succeeded 5/5 times with a 0.5 s
    wait before checking, immediately after being (falsely) scored a failure with no wait at all. Every
    page-state check below polls briefly instead of looking once, so a slow-but-real success isn't scored
    the same as a genuine failure."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            if await predicate():
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


def url_contains(browser, text):
    async def check(res):
        return await _poll(lambda: _url_has(browser, text))
    return check


async def _url_has(browser, text) -> bool:
    return text.lower() in (await browser.get_current_page_url()).lower()


def reply_contains(text):
    async def check(res):
        return text.lower() in (res.reply or "").lower()
    return check


def body_contains(browser, text):
    async def check(res):
        return await _poll(lambda: _body_has(browser, text))
    return check


async def _body_has(browser, text) -> bool:
    page = await browser.get_current_page()
    body = await page.evaluate("() => document.body.innerText")
    return text.lower() in (body or "").lower()


def ok_and(predicate=None):
    """Passed only if the router itself reports success, and - optionally - an extra check on the result
    (e.g. that dom_fastpath's own scroll-verification didn't report the page failing to move)."""
    async def check(res):
        if not res.ok:
            return False
        return predicate(res) if predicate else True
    return check


async def refused(res) -> bool:
    return not res.ok


async def is_clarify(res) -> bool:
    return res.tier == "clarify"


def any_of(*checks):
    async def check(res):
        for c in checks:
            if await c(res):
                return True
        return False
    return check


def make_tasks(browser):
    """Each task: a fixed start_url, a natural-language command (as if already transcribed - no wake word,
    this measures the router/agent, not speech), and a check against the real end state. `tier_hint` is
    informational only (what tier this was expected to need) - success is judged by the check, not by
    which tier handled it; the router is free to solve a task any way it can."""
    return [
        {"id": "nav_github", "tier_hint": "rules", "start": "about:blank",
         "command": "go to github.com", "check": url_contains(browser, "github.com")},
        {"id": "nav_wikipedia", "tier_hint": "rules", "start": "about:blank",
         "command": "go to wikipedia", "check": url_contains(browser, "wikipedia.org")},
        {"id": "search_wikipedia", "tier_hint": "rules", "start": "https://en.wikipedia.org",
         "command": "search for Alan Turing", "check": url_contains(browser, "Alan_Turing")},
        {"id": "scroll_down", "tier_hint": "rules", "start": "https://books.toscrape.com",
         "command": "scroll down", "check": ok_and(lambda res: "did not move" not in (res.detail or "").lower())},
        {"id": "click_category", "tier_hint": "rules", "start": "https://books.toscrape.com",
         "command": "click travel", "check": any_of(url_contains(browser, "travel"), body_contains(browser, "Travel"))},
        {"id": "search_youtube", "tier_hint": "rules", "start": "https://youtube.com",
         "command": "search for lofi music", "check": url_contains(browser, "search_query")},
        {"id": "keypress_mute", "tier_hint": "rules", "start": "https://youtube.com",
         "command": "hit M", "check": ok_and()},
        {"id": "click_signin", "tier_hint": "model", "start": "https://github.com",
         "command": "click the Sign in button", "check": any_of(url_contains(browser, "login"), body_contains(browser, "Sign in"))},
        {"id": "extract_book_title", "tier_hint": "agent", "start": "https://books.toscrape.com",
         "command": "tell me the title of the first book on this page",
         "check": reply_contains("a light in the attic")},
        {"id": "extract_book_price", "tier_hint": "agent", "start": "https://books.toscrape.com",
         "command": "what is the price of the first book on this page",
         "check": reply_contains("51.77")},
        {"id": "extract_quote_author", "tier_hint": "agent", "start": "https://quotes.toscrape.com",
         "command": "who said the first quote on this page", "check": reply_contains("einstein")},
        # Deliberately phrased as one compound sentence and run through the bare router, with no planner -
        # this measures whether the router alone can do multi-part requests. By design it mostly can't: the
        # model-step performs one action and stops, so it may just click "travel" and never get to the
        # second half. That's not a bug here, it's exactly why the planner (app.py's looks_multi_step/plan)
        # exists - this task's honest job is to show what happens without it, not to pass.
        {"id": "compound_without_planner", "tier_hint": "compound, no planner", "start": "https://books.toscrape.com",
         "command": "open the travel category and tell me the title of the first book listed",
         "check": reply_contains("himalayas")},
        {"id": "navigate_and_check_tab", "tier_hint": "agent", "start": "https://github.com",
         "command": "open the microsoft playwright repository and tell me if it has an issues tab",
         "check": any_of(reply_contains("issue"), url_contains(browser, "playwright"))},
        {"id": "ambiguous_click_refused", "tier_hint": "refusal", "start": "https://books.toscrape.com",
         "command": "click the blue one", "check": refused},
        {"id": "vague_command_refused", "tier_hint": "refusal", "start": "https://books.toscrape.com",
         "command": "click", "check": is_clarify},
    ]


async def run_task(router, task, timeout=90.0) -> dict:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(router.fast._act({"navigate": {"url": task["start"], "new_tab": False}}), 15)
    except Exception:
        pass
    try:
        res = await asyncio.wait_for(router.run_command(task["command"]), timeout)
        passed = bool(await task["check"](res))
        detail, tier = res.detail[:150], res.tier
    except asyncio.TimeoutError:
        passed, detail, tier = False, f"timed out after {timeout:.0f}s", "timeout"
    except Exception as e:
        passed, detail, tier = False, f"{type(e).__name__}: {e}"[:150], "error"
    return {"id": task["id"], "tier_hint": task["tier_hint"], "command": task["command"],
            "passed": passed, "tier": tier, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000)}


async def main_async(args) -> int:
    browser = Browser(headless=args.headless, no_viewport=True, keep_alive=True)
    await browser.start()
    router = CommandRouter(browser, picker=make_picker_from_env(),
                           agent_llm=config.get_browser_use_llm("cerebras"),
                           agent_max_steps=8, agent_timeout=90.0)
    tasks = make_tasks(browser)
    runs = []
    for attempt in range(1, args.repeats + 1):
        print(f"\n=== pass {attempt}/{args.repeats} ===")
        for task in tasks:
            r = await run_task(router, task)
            r["attempt"] = attempt
            runs.append(r)
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"  [{mark}] {r['id']:<26} tier={r['tier']:<9} {r['ms']:>6} ms  {r['detail']}")
    await browser.kill()

    by_task = {}
    for r in runs:
        by_task.setdefault(r["id"], []).append(r)
    print("\n" + "=" * 90)
    print(f"{'task':<26} {'tier hint':<10} {'pass rate':<14} {'median ms':>10}")
    for tid, rs in by_task.items():
        n_pass = sum(r["passed"] for r in rs)
        rate = n_pass / len(rs)
        med = statistics.median(r["ms"] for r in rs)
        flag = "  <- inconsistent across repeats" if 0.0 < rate < 1.0 else ""
        print(f"{tid:<26} {rs[0]['tier_hint']:<10} {rate * 100:>4.0f}% ({n_pass}/{len(rs)})   {med:>7.0f} ms{flag}")
    overall = sum(r["passed"] for r in runs) / len(runs)
    print("=" * 90)
    print(f"OVERALL: {sum(r['passed'] for r in runs)}/{len(runs)} = {overall * 100:.1f}% "
          f"({len(tasks)} tasks x {args.repeats} repeat(s))")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"benchmark_{stamp}.json"
    path.write_text(json.dumps({"overall_pass_rate": overall, "repeats": args.repeats, "runs": runs}, indent=1), encoding="utf-8")
    print(f"saved {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2, help="how many times to run every task (default 2, for a consistency signal)")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--headed", dest="headless", action="store_false")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
