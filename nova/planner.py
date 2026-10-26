"""Splits a multi-action spoken request into the router's single-action steps.

  steps, ms, err = await plan(client, "go to Amazon, search for MSI monitors, and tell me the cheapest one")
  # steps == ["go to amazon.com", "search for MSI monitors", "ask the cheapest one"]

Used by the app (07_End_To_End_Latency/app.py) for real multi-step commands, and by Experiment 8's
plan_bench.py / plan_execute.py for benchmarking, so both share the exact prompt and model Exp 8 measured.

Only DeepInfra `gemma-4-31B-it-turbo` is wired in: in Exp 8 it was the one model that planned all 18 test
requests exactly right, with no stalls. `gpt-oss-120b` tied on accuracy but had an unpredictable ~25 s stall
on one request every run; `Llama-3.1-8B` invented steps nobody asked for. See
08_Planning_and_Position_Hints/README.md for the numbers.

A single-action command should never reach this module: Exp 8 also found planning is not a speed-up (the
plan call itself costs 1-3 s on top of running the steps), so the caller should only plan a request that
joins more than one action — see `looks_multi_step()`.
"""
import asyncio
import json
import os
import re
import time

import httpx

MODEL_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
MODEL_KEY_ENV = "DEEPINFRA_API_KEY"
MODEL_NAME = "google/gemma-4-31B-it-turbo"

SYSTEM = (
    "You split a spoken request for a voice-controlled web browser into a short list of single-action steps.\n"
    "Allowed steps (use exactly these forms):\n"
    "  go to <website address, e.g. amazon.com, youtube.com, news.ycombinator.com>\n"
    "  search for <text>          (types into the page's search box and presses Enter)\n"
    "  click <what to click>      (a label, or a position such as: the second result, the link at the top left)\n"
    "  type <text> into <field>\n"
    "  scroll down | scroll up | go back\n"
    "  ask <question about what is on the current page>   (reads or reports something)\n"
    "Rules: one action per step; keep the user's own words for click targets; use only the steps the request needs and "
    "never add steps it does not ask for; a request that is already a single action is a single step. An 'ask' step is "
    "normally last. For a request that compares two or more things (\"should I buy the Acer or the MSI\", \"which is "
    "cheaper\"), give each thing its own short 'ask' step naming what to record about it (e.g. \"ask the price of the "
    "Acer\"), then end with one final 'ask' step that states the comparison itself (e.g. \"ask which is cheaper, the "
    "Acer or the MSI\") — that last step is answered from the earlier 'ask' answers, not by reading a page.\n"
    'Reply with JSON only: {"steps": ["step 1", "step 2"]}'
)

# A request is only worth planning if it joins more than one action: "and then", a comma-separated list of
# clauses, "then", or "and" immediately before another step verb. A single command ("scroll down", "click the
# login button") must not match, since planning it would only add a 1-3 s model call for no benefit (Exp 8).
# Checked against Exp 8's 18 test requests: 15/15 multi-step matched, 3/3 single-step did not.
MULTI_STEP = re.compile(
    r"(?:,.*\band\b)|(?:\band\s+(?:then\s+)?(?:go|open|click|search|tell|scroll|type|find|read|play)\b)|\bthen\b", re.I)


def looks_multi_step(text: str) -> bool:
    return bool(MULTI_STEP.search(text))


def parse_step(step: str) -> tuple:
    """-> (kind, argument). kind in go/search/click/type/ask/scroll/back/other."""
    t = step.strip()
    low = t.lower()
    for prefix, kind in (("go to ", "go"), ("open ", "go"), ("navigate to ", "go"), ("search for ", "search"),
                         ("search ", "search"), ("click on ", "click"), ("click ", "click"), ("type ", "type"),
                         ("ask ", "ask"), ("scroll ", "scroll")):
        if low.startswith(prefix):
            return kind, t[len(prefix):].strip(" :")
    if low.startswith("go back") or low == "back":
        return "back", ""
    return "other", t


async def plan(client: httpx.AsyncClient, request: str) -> tuple:
    """-> (steps: list[str] | None, ms: float, error: str). steps is None on failure (error explains why)."""
    body = {"model": MODEL_NAME, "temperature": 0, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": request}],
            "response_format": {"type": "json_object"}}
    t = time.perf_counter()
    r = None
    for attempt in range(3):
        r = await client.post(MODEL_URL, headers={"Authorization": f"Bearer {os.getenv(MODEL_KEY_ENV)}"}, json=body)
        if r.status_code == 429 and attempt < 2:
            await asyncio.sleep(8 * (attempt + 1))
            continue
        break
    ms = (time.perf_counter() - t) * 1000
    if r is None or r.status_code >= 400:
        return None, ms, f"HTTP {r.status_code if r else '?'}: {r.text[:120] if r else 'no response'}"
    text = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, ms, f"no JSON in reply: {text[:100]!r}"
    try:
        steps = json.loads(m.group(0))["steps"]
        assert isinstance(steps, list) and all(isinstance(s, str) for s in steps)
    except Exception:
        return None, ms, f"not valid JSON steps: {text[:100]!r}"
    if not steps:
        return None, ms, "the model said there is nothing more to do"  # a deliberate {"steps": []}, not a parse error
    return steps, ms, ""


async def replan_after_failure(client: httpx.AsyncClient, request: str, done_steps: list, failed_step: str,
                               error: str, remaining_steps: list) -> tuple:
    """A plan step failed: try once for a replacement for whatever was left, given what actually happened.
    -> (steps: list[str] | None, ms: float, error: str). An empty or missing list means "nothing more to try",
    which the caller should treat the same as a plan that cannot continue — this is tried only once, never looped."""
    context = (
        f"I was carrying out this request: \"{request}\"\n"
        f"Steps already done: {done_steps or '(none)'}\n"
        f"This step failed: \"{failed_step}\" — {error}\n"
        f"Steps that were still planned: {remaining_steps or '(none)'}\n"
        "Suggest a replacement for the remaining work, using the same step grammar, that avoids the failure "
        "(for example a different click target, or going back first). If nothing more can usefully be done, "
        'reply with {"steps": []}.'
    )
    return await plan(client, context)
