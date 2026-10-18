"""Experiment 9: is Phase 2's memory (scratchpad, conversation history, one re-plan on failure) worth its cost?

  python memory_bench.py          # runs every case with memory ON and OFF, a real browser + real model calls

Each case is a short script of one or more commands, run through the real app (07_End_To_End_Latency/app.py's
AppLoop) exactly as it would run live, with and without `--no-memory`. A fresh ConversationMemory is used per
case (reset between cases, one browser reused per condition for speed); every case has an automatic pass/fail
check on the actual spoken replies, not a guess at what should have happened.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "07_End_To_End_Latency"))
import app  # noqa: E402

# Each case: a list of commands to run in order, and a check(loop) -> (ok: bool, why: str) run after the last one.
# "needs_memory" marks cases where the WITHOUT-memory run is expected to do worse (the point of the experiment);
# the advisory-question case is a control, expected to behave the same either way.


def _last_reply(loop) -> str:
    return loop.records[-1]["reply"] if loop.records else ""


def check_comparison(loop, memory_on):
    r = _last_reply(loop).lower()
    if "attic" in r and ("51.77" in r or "cheaper" in r and "velvet" not in r.split("cheaper")[0][-20:]):
        return True, "named the first (cheaper) book"
    if "51.77" in r and "53.74" in r:
        return True, "gave both prices (comparison at least grounded in real numbers)"
    return False, f"did not clearly say the first book was cheaper: {r[:160]!r}"


def check_followup(loop, memory_on):
    r = _last_reply(loop).lower()
    if "51.77" in r:
        return True, "recalled the first book's price (£51.77) after navigating away"
    return False, f"could not recall the earlier price: {r[:160]!r}"


def check_replan(loop, memory_on):
    """With memory, one replan attempt should be made when a step fails (whether or not it then succeeds).
    Without memory, re-planning is off entirely, so none should be attempted — that is the correct behaviour
    for that condition, not a failure, so the expectation is inverted per condition."""
    rec = loop.records[-1] if loop.records else {}
    replanned = rec.get("replanned", False)
    ok = replanned if memory_on else not replanned
    return ok, f"replanned={replanned} (expected {'True' if memory_on else 'False'}), ok={rec.get('ok')}"


def check_advisory(loop, memory_on):
    r = _last_reply(loop)
    long_enough = len(r.split()) >= 8
    not_refusal = "i can't" not in r.lower() and "i cannot" not in r.lower()[:30]
    return long_enough and not_refusal, f"({len(r.split())} words): {r[:160]!r}"


CASES = [
    {
        "name": "comparison (2 products, needs scratchpad)",
        "needs_memory": True,
        "commands": ["go to books.toscrape.com, tell me the price of the first book, then tell me the price of "
                     "the second book, and tell me which is cheaper"],
        "check": check_comparison,
    },
    {
        "name": "follow-up after navigating away (needs conversation history)",
        "needs_memory": True,
        "commands": ["go to books.toscrape.com", "click the first book", "tell me its price", "go back",
                     "go to quotes.toscrape.com", "what was the first book's price again"],
        "check": check_followup,
    },
    {
        "name": "advisory opinion question (control: should behave the same either way)",
        "needs_memory": False,
        "commands": ["go to books.toscrape.com", "click the first book", "should I buy this book"],
        "check": check_advisory,
    },
    {
        "name": "re-plan once after a step fails (a button that does not exist)",
        "needs_memory": True,
        "commands": ["go to books.toscrape.com, click the nonexistent zorblatt button, and tell me what happened"],
        "check": check_replan,
    },
]


async def run_case(loop, case, memory_on: bool) -> dict:
    loop.memory = app.ConversationMemory()  # fresh per case; browser/router are reused across cases
    loop.records = []
    t0 = time.perf_counter()
    for cmd in case["commands"]:
        app.run_commands(loop, [cmd])
    ms = (time.perf_counter() - t0) * 1000
    ok, why = case["check"](loop, memory_on)
    return {"name": case["name"], "ok": ok, "why": why, "ms": round(ms),
            "replies": [r["reply"] for r in loop.records]}


async def run_condition(memory_on: bool) -> list:
    args = argparse.Namespace(text=True, script=None, no_sound=True, headless=True, input_device=None,
                              output_device=None, hangover=0.5, min_speech=0.25, cue="none", idle=0,
                              hinglish=False, agent_steps=8, agent_timeout=120.0, start_url="", simulate=True,
                              memory=memory_on)
    runner = app.AsyncRunner()
    loop = app.AppLoop(args, runner)
    browser, loop.router = app.make_router(loop, runner, args)
    loop.plan_client = runner.run(app._make_async_client())
    results = []
    for case in CASES:
        print(f"  [{'memory ON ' if memory_on else 'memory OFF'}] {case['name']} ...", flush=True)
        r = await run_case(loop, case, memory_on)
        results.append(r)
        print(f"    {'PASS' if r['ok'] else 'FAIL'} ({r['ms'] / 1000:.1f} s): {r['why']}", flush=True)
    try:
        await loop.plan_client.aclose()
    except Exception:
        pass
    try:
        runner.run(browser.kill(), timeout=15)
    except Exception:
        pass
    return results


async def main() -> int:
    on = await run_condition(True)
    off = await run_condition(False)
    print("\n" + "=" * 100)
    print(f"{'case':<58} {'with memory':<16} {'without memory':<16}")
    for a, b in zip(on, off):
        print(f"{a['name'][:56]:<58} {'PASS' if a['ok'] else 'FAIL':<16} {'PASS' if b['ok'] else 'FAIL':<16}")
    print("=" * 100)
    n_on, n_off = sum(r["ok"] for r in on), sum(r["ok"] for r in off)
    print(f"with memory: {n_on}/{len(on)} passed | without memory: {n_off}/{len(off)} passed")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "memory_bench.json").write_text(
        json.dumps({"with_memory": on, "without_memory": off}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
