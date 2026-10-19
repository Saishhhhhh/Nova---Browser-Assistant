"""Tests for the optional small-model step of FastPath.

  python -m ash.tests.test_model_step          # offline parser tests + real browser with a STAND-IN model. No API calls.
  python -m ash.tests.test_model_step --live   # also runs ~6 commands against the REAL model (a few cents at most)

The default run proves the plumbing: the model is only called when the rules refuse, a valid
pick is executed in the real browser, and every bad answer (none, unknown index, exception)
is refused without clicking anything. Only --live shows whether a real model picks well.
"""
import argparse
import asyncio
import os
import sys

from browser_use import Browser

from ash.dom_fastpath import ElementInfo, FastPath, Pick, format_elements, make_picker_from_env, parse_pick
from ash.tests.test_fastpath import url_contains, wait_until

failures = []


def browser_kwargs(headed: bool) -> dict:
    kwargs = dict(headless=not headed, no_viewport=True)
    if headed:  # pin to the primary monitor (a dual-monitor setup splits the window otherwise)
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    return kwargs


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL':>4}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def offline_tests() -> None:
    print("== reply parser (offline)")
    p = parse_pick('{"action": "click", "index": 13}')
    check("plain click reply", (p.action, p.index) == ("click", 13))
    p = parse_pick('Sure! {"action": "type", "index": 8, "text": "hello"} Hope that helps.')
    check("JSON wrapped in prose", (p.action, p.index, p.text) == ("type", 8, "hello"))
    p = parse_pick('{"action": "click", "index": "21"}')
    check("index given as string", p.index == 21)
    check("index written like [21]", parse_pick('{"action": "click", "index": "[21]"}').index == 21)
    check("index text without a number -> none", parse_pick('{"action": "click", "index": "the first"}').action == "none")
    check("index null -> none", parse_pick('{"action": "click", "index": null}').action == "none")
    check("action none -> none", parse_pick('{"action": "none", "index": null}').action == "none")
    check("type without text -> none", parse_pick('{"action": "type", "index": 4}').action == "none")
    check("unknown action -> none", parse_pick('{"action": "delete", "index": 4}').action == "none")
    check("garbage -> none", parse_pick("I think you should click the button").action == "none")
    check("empty -> none", parse_pick("").action == "none")

    print("== defaults (offline, nothing is sent)")
    saved = {k: os.environ.pop(k, None) for k in ("FASTPATH_PROVIDER", "FASTPATH_MODEL", "FASTPATH_TIMEOUT")}
    try:
        picker = make_picker_from_env()
        check("default provider is deepinfra", picker.provider == "deepinfra", picker.provider)
        check("default model is Gemma 4 31B turbo", picker.model == "google/gemma-4-31B-it-turbo", picker.model)
        check("default timeout is 10 seconds", picker.timeout == 10.0, str(picker.timeout))
        os.environ["FASTPATH_TIMEOUT"] = "9"
        check("timeout comes from FASTPATH_TIMEOUT", make_picker_from_env().timeout == 9.0)
    except RuntimeError as e:
        print(f"  [skip] {e}")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    print("== element list for the model (offline)")
    els = [
        ElementInfo(1, "a", "", "", {}, labels=["sign in"]),
        ElementInfo(2, "div", "", "", {}, labels=[]),                       # no label, not an input: skipped
        ElementInfo(3, "input", "", "text", {}, labels=[], weak_labels=["q"]),
        ElementInfo(4, "button", "", "", {}, labels=["x" * 200]),           # long label is cut
    ]
    lines = format_elements(els).splitlines()
    check("skips unlabelled non-inputs", len(lines) == 3 and lines[0].startswith("[1]") and lines[1].startswith("[3]"))
    check("labels are cut to 80 chars", len(lines[2]) < 120)
    check("limit respected", len(format_elements(els * 200, limit=10).splitlines()) == 10)


class FakePicker:
    """Stands in for the model: answers from a fixed plan, records every call."""

    def __init__(self, plan):
        self.plan, self.calls = plan, []

    async def pick(self, command, elements):
        self.calls.append(command)
        step = self.plan.get(command)
        if isinstance(step, Exception):
            raise step
        if step is None:
            return Pick(note="fake model has no plan for this")
        action, label, text = step
        if label is None:  # an index that is not on the page
            return Pick(action=action, index=999999, text=text)
        for e in elements:
            if label in e.labels:
                return Pick(action=action, index=e.index, text=text, prompt_tokens=100, completion_tokens=10)
        return Pick(note="fake model could not find that label")


async def plumbing_tests(headed: bool) -> None:
    print("\n== model step plumbing: real browser, stand-in model (no API calls)")
    browser = Browser(**browser_kwargs(headed))
    await browser.start()
    fake = FakePicker({
        "take me to the mystery section": ("click", "mystery", None),
        "head over to romance": ("click", None, None),
        "explode": RuntimeError("boom"),
    })
    fast = FastPath(browser, picker=fake)

    async def url():
        return await browser.get_current_page_url()

    await fast.run("go to books.toscrape.com")
    r = await fast.run("click travel")
    check("rules handle it -> model NOT called", r.handled and not r.used_model and fake.calls == [], r.detail)

    await fast.run("go to books.toscrape.com")
    before = len(fake.calls)
    r = await fast.run("take me to the mystery section")
    check("unknown command -> model called once", r.used_model and len(fake.calls) == before + 1, r.detail)
    check("model's pick was clicked in the real browser", r.handled and await wait_until(url_contains(browser, "mystery_3")), r.detail)
    check("model time and tokens recorded", r.model_ms > 0 and r.prompt_tokens == 100, f"{r.model_ms:.0f} ms")

    await fast.run("go to books.toscrape.com")
    start_url = await url()
    r = await fast.run("show me the poetry books")
    check("model says none -> refused, nothing clicked", not r.handled and r.used_model and await url() == start_url, r.detail)

    r = await fast.run("head over to romance")
    check("model picks a non-existent index -> refused", not r.handled and await url() == start_url, r.detail)

    r = await fast.run("explode")
    check("model raises -> refused, no crash", not r.handled and "model call failed" in r.detail, r.detail)

    class SlowPicker:
        timeout = 0.5  # the limit FastPath should enforce

        async def pick(self, command, elements):
            await asyncio.sleep(4)  # far slower than the limit
            return Pick(action="click", index=elements[0].index)

    t0 = asyncio.get_event_loop().time()
    r = await FastPath(browser, picker=SlowPicker()).run("take me to the mystery section")
    waited = asyncio.get_event_loop().time() - t0
    check("slow model -> gives up at the limit, refused", not r.handled and "timed out" in r.detail and waited < 3.5,
          f"waited {waited:.1f}s: {r.detail}")

    nomodel = FastPath(browser)
    r = await nomodel.run("take me to the mystery section")
    check("no picker configured -> plain refusal, no model", not r.handled and not r.used_model, r.detail)
    await browser.stop()


async def live_tests(headed: bool) -> None:
    picker = make_picker_from_env()
    print(f"\n== LIVE: real model {picker.provider}/{picker.model} (about 6 short calls, real money)")
    browser = Browser(**browser_kwargs(headed))
    await browser.start()
    fast = FastPath(browser, picker=picker)
    plan = [
        ("books.toscrape.com", "take me to the mystery section", "mystery_3", True),
        ("books.toscrape.com", "show me the poetry books", "poetry_23", True),
        ("github.com/microsoft/playwright", "take me to the pull requests", "/pulls", True),
        ("youtube.com/results?search_query=lofi+music", "play the first video", "/watch?v=", True),
        ("books.toscrape.com", "click the blue one", None, False),       # must be refused
        ("books.toscrape.com", "what is on this page", None, False),     # must be refused
    ]
    calls = 0
    for site, command, expect_url, should_act in plan:
        await fast.run(f"go to {site}")
        r = await fast.run(command)
        calls += int(r.used_model)
        if should_act:
            ok = r.handled and await wait_until(url_contains(browser, expect_url))
        else:
            ok = not r.handled
        print(f"  [{'PASS' if ok else 'FAIL':>4}] {command!r:<36} model {r.model_ms:5.0f} ms, "
              f"{r.prompt_tokens} in / {r.completion_tokens} out tokens | {r.detail}")
        if not ok:
            failures.append(command)
        if headed:
            await asyncio.sleep(2.5)  # leave the result on screen long enough to see it
    await browser.stop()
    print(f"  model calls made: {calls}")


async def main(live: bool, headed: bool) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    offline_tests()
    await plumbing_tests(headed)
    if live:
        await live_tests(headed)
    print(f"\n{'ALL PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="also call the real model (costs a few cents)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.live, a.headed)))
