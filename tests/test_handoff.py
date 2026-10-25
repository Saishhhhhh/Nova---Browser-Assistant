"""Verifies the fast path -> full agent handoff on ONE shared browser.

  python -m tests.test_handoff            # headless
  python -m tests.test_handoff --headed   # watch it (window pinned to the primary monitor)

REAL API CALLS (a few cents): one DeepInfra Gemma call for the model step, then the browser-use
agent on Cerebras for ~3-6 steps. Checks that:
  1. rules handle the first two commands,
  2. a question the fast path can't do goes to the agent,
  3. the agent CONTINUES from the page the fast path left (not from scratch),
  4. the browser is still alive afterwards and the fast path works again.
"""
import argparse
import asyncio
import sys

from browser_use import Browser

from mycroft.config import EXTRACTION_MODEL, EXTRACTION_PROVIDER, get_browser_use_llm
from mycroft.dom_fastpath import make_picker_from_env
from mycroft.router import CommandRouter
from tests.test_fastpath import url_contains, wait_until

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL':>4}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def show(r) -> None:
    print(f"      tier={r.tier} ok={r.ok} total={r.total_ms:.0f} ms (fast path {r.fast_ms:.0f} ms) steps={r.agent_steps}")
    print(f"      reply: {r.reply[:160]!r}")
    print(f"      detail: {r.detail[:230]}")


async def main(headed: bool) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kwargs = dict(headless=not headed, no_viewport=True, keep_alive=True)
    if headed:
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    browser = Browser(**kwargs)
    await browser.start()
    picker = make_picker_from_env()
    router = CommandRouter(
        browser, picker=picker,
        agent_llm=get_browser_use_llm("cerebras"),
        extraction_llm=get_browser_use_llm(EXTRACTION_PROVIDER, EXTRACTION_MODEL) if EXTRACTION_PROVIDER else None,
        agent_max_steps=8, agent_timeout=240.0,
    )
    print(f"fast-path model: {picker.provider}/{picker.model}; agent model: cerebras")

    print("\n== 1. rules handle simple commands")
    r = await router.run_command("go to books.toscrape.com")
    show(r)
    check("go to site -> rules", r.tier == "rules" and r.ok)
    r = await router.run_command("click travel")
    show(r)
    check("click travel -> rules, page changed", r.tier == "rules" and await wait_until(url_contains(browser, "travel_")))

    print("\n== 2. a question goes to the agent, on the page the fast path left")
    r = await router.run_command("tell me the title of the first book on this page")
    show(r)
    check("escalated to the agent", r.tier == "agent", f"tier was {r.tier}")
    check("agent answered with the right book", "himalayas" in r.reply.lower(), r.reply[:80])
    if r.tier == "agent":
        started_on = r.agent_urls[0] if r.agent_urls else ""
        check("agent continued from the fast path's page, not from scratch",
              "travel_" in started_on, f"agent's first page: {started_on}")
        print(f"      agent pages: {r.agent_urls}")

    print("\n== 3. the browser survives the agent and the fast path works again")
    try:
        alive_url = await browser.get_current_page_url()
        check("browser still open after the agent finished", bool(alive_url), alive_url)
    except Exception as e:
        check("browser still open after the agent finished", False, f"{type(e).__name__}: {e}")
    r = await router.run_command("go to books.toscrape.com")
    check("fast path navigates after the agent", r.tier == "rules" and r.ok, r.detail[:100])
    r = await router.run_command("click mystery")
    show(r)
    check("fast path clicks after the agent", r.tier == "rules" and await wait_until(url_contains(browser, "mystery_3")))

    await browser.kill()
    print(f"\n{'ALL PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().headed)))
