"""Regression set built from real failing live-voice transcripts (not invented phrasing), each with a concrete
expected end state instead of just "didn't crash". Run this after any router/dom_fastpath change.

  python test_live_regressions.py        # real browser, a few cents of API calls

Every case here is a literal command copied from a pasted live session that did the wrong thing. The point of
this file is that a future change can't silently re-break one of these without the suite catching it.
"""
import asyncio
import sys

from browser_use import Browser
from dom_fastpath import make_picker_from_env
from router import CommandRouter


async def check(name: str, cond: bool, detail: str) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


async def main() -> int:
    b = Browser(headless=True, no_viewport=True, keep_alive=True)
    await b.start()
    router = CommandRouter(b, picker=make_picker_from_env())
    ok = True

    print("== search must actually submit, not just type (GitHub has no visible search box until a button opens it)")
    await router.run_command("go to github.com")
    r = await router.run_command("Search for Google.")
    url = await b.get_current_page_url()
    for _ in range(6):
        if "q=" in url:
            break
        await asyncio.sleep(0.5)
        url = await b.get_current_page_url()
    ok &= await check('"Search for Google." submits and reaches results', "google" in url.lower() and "q=" in url, url)

    print("== a locational preamble in front of a search must not block the rules path")
    r = await router.run_command("go to github.com")
    r = await router.run_command("In the top right search bar, search for size.")
    ok &= await check('"In the top right search bar, search for X." -> tier rules, not model', r.tier == "rules", f"tier={r.tier}")

    print("== spelled-out letters collapse into one word before typing, wherever they end up")
    r = await router.run_command("go to github.com")
    r = await router.run_command("search for S A I S H H H H H H")
    ok &= await check('spelled letters assembled, not typed with spaces', "saishhhhhh" in r.reply.lower(), r.reply)

    print("== 'Stop.' with nothing running must not ask for clarification")
    r = await router.run_command("Stop.")
    ok &= await check('"Stop." (idle) is a quiet no-op, not "Sorry, what should I do?"',
                       r.tier == "chat" and r.ok, f"tier={r.tier} reply={r.reply!r}")

    await b.kill()
    print("\n" + ("ALL PASSED" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
