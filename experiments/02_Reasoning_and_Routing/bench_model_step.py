"""Command-set benchmark for the fast path's model step, one model per run.

  python bench_model_step.py --provider ollama --model qwen2.5:3b
  python bench_model_step.py --provider cerebras                      # real API: ~18 short calls
  python bench_model_step.py --provider deepinfra

18 spoken-style commands on real sites. 14 should DO something (outcome is checked in the browser:
URL / field value) and 4 must be REFUSED. Each result is saved to results/bench_<provider>_<model>.json
so models can be compared side by side. A command the rules handle never reaches the model.
"""
import argparse
import asyncio
import json
import os
import re
import statistics
import sys

from browser_use import Browser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dom_fastpath import FastPath, OpenAICompatiblePicker, DEFAULT_MODELS  # noqa: E402
from test_fastpath import url_contains, wait_until  # noqa: E402

BOOKS = "books.toscrape.com"
GITHUB = "github.com/microsoft/playwright"
TURING = "en.wikipedia.org/wiki/Alan_Turing"
WIKI_MAIN = "en.wikipedia.org/wiki/Main_Page"
YT = "youtube.com/results?search_query=lofi+music"

# (start page, command, expectation)  expectation: ("url", text) | ("field", css, value) | ("refuse",)
CASES = [
    (BOOKS, "take me to the mystery section", ("url", "mystery_3")),
    (BOOKS, "show me the poetry books", ("url", "poetry_23")),
    (BOOKS, "I want to see science fiction", ("url", "science-fiction_16")),
    (BOOKS, "go to the next page", ("url", "page-2.html")),
    (BOOKS, "open the first book", ("url", "a-light-in-the-attic")),
    (GITHUB, "take me to the pull requests", ("url", "/pulls")),
    (GITHUB, "show me the issues", ("url", "/issues")),
    (GITHUB, "where are the releases", ("url", "/releases")),
    (TURING, "go to the talk page", ("url", "Talk:Alan_Turing")),
    (TURING, "show me the page history", ("url", "action=history")),
    (TURING, "take me to the main page", ("url", "Main_Page")),
    (WIKI_MAIN, "put quantum computing in the search", ("field", "input[name=search]", "quantum computing")),
    (YT, "play the first video", ("url", "/watch?v=")),
    (GITHUB, "click actions", ("url", "/actions")),  # control: the rules resolve this, the model is not needed
    (BOOKS, "click the blue one", ("refuse",)),
    (BOOKS, "what is on this page", ("refuse",)),
    (BOOKS, "compare the first two books", ("refuse",)),
    (BOOKS, "delete everything", ("refuse",)),
]


def field_is(browser, selector: str, expected: str):
    async def check():
        page = await browser.get_current_page()
        value = await page.evaluate(f"() => (document.querySelector({json.dumps(selector)}) || {{}}).value")
        return (value or "") == expected
    return check


async def run_case(browser, fast: FastPath, start: str, command: str, expect: tuple) -> dict:
    row = {"command": command, "expect": expect[0], "handled": False, "used_model": False, "picked": "",
           "outcome": "", "model_ms": 0, "total_ms": 0, "tokens_in": 0, "tokens_out": 0, "detail": ""}
    try:
        await asyncio.wait_for(fast.run(f"go to {start}"), 90)
        res = await asyncio.wait_for(fast.run(command), 150)
    except Exception as e:
        row.update(outcome="ERROR", detail=f"{type(e).__name__}: {e}"[:150])
        return row
    row.update(handled=res.handled and not res.error, used_model=res.used_model, picked=res.picked,
               model_ms=round(res.model_ms), total_ms=round(res.total_ms),
               tokens_in=res.prompt_tokens, tokens_out=res.completion_tokens, detail=(res.error or res.detail)[:150])
    if expect[0] == "refuse":
        row["outcome"] = "REFUSED_OK" if not res.handled else "WRONG_ACTION"
    elif not res.handled:
        row["outcome"] = "REFUSED"  # safe failure: would escalate to the full agent
    else:
        check = (url_contains(browser, expect[1]) if expect[0] == "url"
                 else field_is(browser, expect[1], expect[2]))
        row["outcome"] = "CORRECT" if await wait_until(check, timeout=8) else "WRONG_ACTION"
    return row


async def main(provider: str, model: str, headed: bool, pause: float) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    picker = OpenAICompatiblePicker(provider, model)
    kwargs = dict(headless=not headed, no_viewport=True)
    if headed:
        kwargs.update(window_position={"width": 0, "height": 0}, window_size={"width": 1536, "height": 864})
    browser = Browser(**kwargs)
    await browser.start()
    fast = FastPath(browser, picker=picker)

    print(f"== {provider}/{model}: {len(CASES)} commands")
    rows = []
    for start, command, expect in CASES:
        row = await run_case(browser, fast, start, command, expect)
        rows.append(row)
        via = "model" if row["used_model"] else "rules"
        failed = "  <-- MODEL CALL FAILED" if "model call failed" in row["detail"] else ""
        print(f"  {row['outcome']:<13} {via:<5} {row['model_ms']:>6} ms  {row['tokens_in']:>5} in  "
              f"{row['command']!r:<40} picked={row['picked']!r}{failed}")
        if pause:
            await asyncio.sleep(pause)  # stay under per-minute token limits (Cerebras)
    await browser.stop()

    act = [r for r in rows if r["expect"] != "refuse"]
    refuse = [r for r in rows if r["expect"] == "refuse"]
    correct = sum(r["outcome"] == "CORRECT" for r in act)
    wrong_act = sum(r["outcome"] == "WRONG_ACTION" for r in act)
    refused_act = sum(r["outcome"] == "REFUSED" for r in act)
    refuse_ok = sum(r["outcome"] == "REFUSED_OK" for r in refuse)
    wrong_refuse = sum(r["outcome"] == "WRONG_ACTION" for r in refuse)
    ms = [r["model_ms"] for r in rows if r["used_model"] and r["model_ms"]]
    failed_calls = sum("model call failed" in r["detail"] for r in rows)
    summary = {
        "provider": provider, "model": model, "commands": len(rows),
        "model_calls_failed": failed_calls,  # if > 0 the refusal counts below are NOT trustworthy
        "act_commands": len(act), "act_correct": correct, "act_wrong_click": wrong_act,
        "act_refused_safely": refused_act, "refuse_commands": len(refuse), "refused_ok": refuse_ok,
        "guessed_when_should_refuse": wrong_refuse,
        "wrong_clicks_total": wrong_act + wrong_refuse,
        "model_calls": len(ms), "model_ms_median": round(statistics.median(ms)) if ms else None,
        "model_ms_max": max(ms) if ms else None,
        "tokens_in_avg": round(statistics.mean(r["tokens_in"] for r in rows if r["used_model"]) or 0) if ms else None,
    }
    print("\n" + json.dumps(summary, indent=2))
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"), exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}_{model}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", f"bench_{safe}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["cerebras", "deepinfra", "ollama"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait between commands (rate limits)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.provider, a.model or DEFAULT_MODELS[a.provider], a.headed, a.pause)))
