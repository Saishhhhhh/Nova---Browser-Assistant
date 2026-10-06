"""Verifies the model-free fast path against real sites. Makes no LLM/API calls.

Each scenario runs spoken-style commands through FastPath, then checks the OUTCOME in the
browser (URL / page text / scroll position), not whether the code claims it clicked.
A final group checks that vague commands are refused (handled=False) instead of guessed.

  python test_fastpath.py            # headless
  python test_fastpath.py --headed   # visible window on the primary monitor
"""
import argparse
import asyncio
import os
import sys

from browser_use import Browser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dom_fastpath import FastPath, parse_command  # noqa: E402


async def wait_until(predicate, timeout=10.0, interval=0.4) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            if await predicate():
                return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


def url_contains(browser, text):
    async def check():
        return text.lower() in (await browser.get_current_page_url()).lower()
    return check


def url_lacks(browser, text):
    async def check():
        return text.lower() not in (await browser.get_current_page_url()).lower()
    return check


def body_contains(browser, text):
    async def check():
        page = await browser.get_current_page()
        body = await page.evaluate("() => document.body.innerText")
        return text.lower() in (body or "").lower()
    return check


def scrolled(browser):
    async def check():
        page = await browser.get_current_page()
        return float(await page.evaluate("() => window.scrollY") or 0) > 0
    return check


def scenarios(b):
    """(name, [(command, outcome_check_or_None)])"""
    return [
        ("login form (type + click)", [
            ("go to the-internet.herokuapp.com/login", url_contains(b, "/login")),
            ("type tomsmith into username", None),
            ("type SuperSecretPassword! into password", None),
            ("click login", body_contains(b, "You logged into a secure area")),
        ]),
        ("shop (click by visible text)", [
            ("go to books.toscrape.com", url_contains(b, "books.toscrape.com")),
            ("click travel", url_contains(b, "/travel_")),
            ("click It's Only the Himalayas", url_contains(b, "its-only-the-himalayas")),
        ]),
        ("wikipedia (search)", [
            ("go to en.wikipedia.org", url_contains(b, "wikipedia.org")),
            ("search for Alan Turing", url_contains(b, "Alan_Turing")),
        ]),
        ("youtube (search, scroll, back)", [
            ("go to youtube.com", url_contains(b, "youtube.com")),
            ("search for lofi music", url_contains(b, "search_query=lofi")),
            ("scroll down", scrolled(b)),
            ("go back", url_lacks(b, "results")),
        ]),
        ("github (click a tab)", [
            ("go to github.com/microsoft/playwright", url_contains(b, "microsoft/playwright")),
            ("click issues", url_contains(b, "/issues")),
        ]),
    ]


# Must be refused, not guessed at: (command, why a rule can't safely do it)
MUST_ESCALATE = [
    ("go to books.toscrape.com", None),
    ("click the blue one", "visual reference"),
    ("click the thing that looks like a basket", "vague description"),
    ("play the first video", "no rule for this verb"),
    ("what is on this page", "question, not an action"),
]


async def main(headed: bool) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # browser-use error text contains emoji
    kwargs = dict(headless=not headed, no_viewport=True)
    if headed:
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    browser = Browser(**kwargs)
    await browser.start()
    fast = FastPath(browser)

    rows, total, passed, times = [], 0, 0, []
    for name, steps in scenarios(browser):
        print(f"\n== {name}")
        for command, check in steps:
            res = await fast.run(command)
            times.append(res.total_ms)
            if not res.handled or res.error:
                verdict = "NOT HANDLED" if not res.handled else "ACTION ERROR"
                ok = False
            elif check is None:
                verdict, ok = "ran", True
            else:
                ok = await wait_until(check)
                verdict = "PASS" if ok else "FAIL (outcome not reached)"
            if check is not None or not res.handled or res.error:
                total += 1
                passed += int(ok)
            print(f"  [{verdict:>26}] {res.total_ms:7.0f} ms (settle {res.settle_ms:4.0f}, read {res.read_ms:4.0f}) | {command}")
            print(f"      {res.error or res.detail}")
            if not ok:
                break  # later steps depend on this one

    print("\n== refusal checks (must NOT be handled)")
    refusal_total = refusal_ok = 0
    for command, why in MUST_ESCALATE:
        res = await fast.run(command)
        if why is None:
            continue  # setup step
        refusal_total += 1
        ok = not res.handled
        refusal_ok += int(ok)
        print(f"  [{'PASS' if ok else 'FAIL (guessed)':>26}] {command!r:<48} {res.detail}")

    await browser.stop()

    print("\n== intent parsing (offline)")
    for c in ["Go to github.com", "search 'red shoes'", "type hello into the search box", "scroll up 2", "go back", "click on the Sign in button"]:
        print(f"  {c!r:<42} -> {parse_command(c)}")

    print(f"\nOutcome checks passed: {passed}/{total}")
    print(f"Refusals correct:      {refusal_ok}/{refusal_total}")
    if times:
        print(f"Per-command time: avg {sum(times)/len(times):.0f} ms, max {max(times):.0f} ms over {len(times)} commands")
    return 0 if passed == total and refusal_ok == refusal_total else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().headed)))
