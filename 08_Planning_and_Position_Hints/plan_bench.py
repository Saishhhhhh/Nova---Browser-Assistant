"""Part A of Experiment 8: can a model split a spoken request into the router's one-action commands?

  python plan_bench.py                         # all models, 18 requests (a few cents)
  python plan_bench.py --models gemma          # one model

Each request is sent to a model with a small grammar of allowed steps. The returned plan is compared with a plan
written by hand. Scored per request: the right number of steps, each step of the right kind and about the right
target, nothing invented. Also reported: how many steps the router's rules could run without a model, and the time.
No browser is used here (running the plans is plan_execute.py).
"""
import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
load_dotenv(ROOT / ".env")

MODELS = {
    "gemma": ("https://api.deepinfra.com/v1/openai/chat/completions", "DEEPINFRA_API_KEY", "google/gemma-4-31B-it-turbo", {}),
    "gpt-oss": ("https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY", "gpt-oss-120b", {"reasoning_effort": "low"}),
    "llama-8b": ("https://api.deepinfra.com/v1/openai/chat/completions", "DEEPINFRA_API_KEY",
                 "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", {}),
}

SYSTEM = (
    "You split a spoken request for a voice-controlled web browser into a short list of single-action steps.\n"
    "Allowed steps (use exactly these forms):\n"
    "  go to <website address, e.g. amazon.com, youtube.com, news.ycombinator.com>\n"
    "  search for <text>          (types into the page's search box and presses Enter)\n"
    "  click <what to click>      (a label, or a position such as: the second result, the link at the top left)\n"
    "  type <text> into <field>\n"
    "  scroll down | scroll up | go back\n"
    "  ask <question about what is on the current page>   (reads or reports something; always the last step)\n"
    "Rules: one action per step; keep the user's own words for click targets; use only the steps the request needs and "
    "never add steps it does not ask for; a request that is already a single action is a single step.\n"
    'Reply with JSON only: {"steps": ["step 1", "step 2"]}'
)

# (request, gold plan as [(kind, argument)])  kinds: go search click type scroll back ask
CASES = [
    ("Go to books.toscrape.com, open the travel category, and tell me how many books are on the page",
     [("go", "books.toscrape.com"), ("click", "travel"), ("ask", "how many books are on the page")]),
    ("Open the mystery category on books.toscrape.com and tell me the title of the first book",
     [("go", "books.toscrape.com"), ("click", "mystery"), ("ask", "the title of the first book")]),
    ("Go to quotes.toscrape.com and tell me the first quote",
     [("go", "quotes.toscrape.com"), ("ask", "the first quote")]),
    ("Go to quotes.toscrape.com, click the login link, and tell me what fields are on the page",
     [("go", "quotes.toscrape.com"), ("click", "login link"), ("ask", "what fields are on the page")]),
    ("On books.toscrape.com open the first book and tell me its price",
     [("go", "books.toscrape.com"), ("click", "the first book"), ("ask", "its price")]),
    ("Go to Amazon, search for MSI gaming monitors, and tell me the cheapest one",
     [("go", "amazon"), ("search", "MSI gaming monitors"), ("ask", "the cheapest one")]),
    ("Open YouTube, search for lofi hip hop beats and play the first video",
     [("go", "youtube"), ("search", "lofi hip hop beats"), ("click", "the first video")]),
    ("Go to Wikipedia, search for Alan Turing, and tell me when he was born",
     [("go", "wikipedia"), ("search", "Alan Turing"), ("ask", "when he was born")]),
    ("Open GitHub, go to trending, and tell me the top repository",
     [("go", "github"), ("click", "trending"), ("ask", "the top repository")]),
    ("Search for quantum computing, scroll down, and open the third result",
     [("search", "quantum computing"), ("scroll", "down"), ("click", "the third result")]),
    ("Go to Flipkart, search for running shoes, scroll down twice, and click the second product",
     [("go", "flipkart"), ("search", "running shoes"), ("scroll", "down"), ("scroll", "down"), ("click", "the second product")]),
    ("Open Gmail and tell me how many unread emails I have",
     [("go", "gmail"), ("ask", "how many unread emails")]),
    ("Go to Hacker News, open the top story, then go back and open the second one",
     [("go", "hacker news"), ("click", "the top story"), ("back", ""), ("click", "the second story")]),
    ("Search for Python tutorials, open the first result, and scroll down",
     [("search", "python tutorials"), ("click", "the first result"), ("scroll", "down")]),
    ("Go to Reddit and tell me the title of the top post",
     [("go", "reddit"), ("ask", "the title of the top post")]),
    # single actions: the plan must not grow
    ("Scroll down", [("scroll", "down")]),
    ("Search for lofi music", [("search", "lofi music")]),
    ("Click the login button", [("click", "login button")]),
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def parse_step(step: str) -> tuple:
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


def same_target(kind: str, gold: str, got: str) -> bool:
    g, p = norm(gold), norm(got)
    if kind in ("back",):
        return True
    if kind == "scroll":
        return g.split()[:1] == p.split()[:1] or not g
    if kind == "go":
        key = g.replace("www ", "").split()[0] if g else ""
        aliases = {"gmail": "mail google", "hacker": "ycombinator", "hackernews": "ycombinator"}
        return bool(key) and (key in p.replace(" ", "") or aliases.get(key, "@@") in p)
    if kind == "ask":     # a paraphrase of the question is fine: share one content word
        stop = {"the", "a", "an", "of", "is", "what", "how", "many", "much", "it", "its", "i", "on", "page", "this",
                "me", "tell", "to", "are", "there", "have", "has"}
        return bool((set(g.split()) - stop) & (set(p.split()) - stop)) or g in p
    if not g:
        return True
    if g in p or p in g:
        return True
    return SequenceMatcher(None, g, p).ratio() >= 0.6 or (len(set(g.split()) & set(p.split())) / max(len(set(g.split())), 1)) >= 0.6


def score(gold: list, steps: list) -> dict:
    got = [parse_step(s) for s in steps]
    ok = sum(1 for (gk, ga), (pk, pa) in zip(gold, got) if gk == pk and same_target(gk, ga, pa))
    return {"steps_gold": len(gold), "steps_got": len(got), "steps_right": ok,
            "exact": len(gold) == len(got) and ok == len(gold),
            "invented": max(len(got) - len(gold), 0), "missing": max(len(gold) - len(got), 0)}


async def call(client, name: str, request: str):
    url, key_env, model, extra = MODELS[name]
    body = {"model": model, "temperature": 0, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": request}],
            "response_format": {"type": "json_object"}, **extra}
    t = time.perf_counter()
    for attempt in range(3):
        r = await client.post(url, headers={"Authorization": f"Bearer {os.getenv(key_env)}"}, json=body)
        if r.status_code == 429 and attempt < 2:
            await asyncio.sleep(8 * (attempt + 1))
            continue
        break
    ms = (time.perf_counter() - t) * 1000
    if r.status_code >= 400:
        return None, ms, f"HTTP {r.status_code}: {r.text[:120]}"
    text = r.json()["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        steps = json.loads(m.group(0))["steps"]
        assert isinstance(steps, list) and all(isinstance(s, str) for s in steps)
        return steps, ms, ""
    except Exception:
        return None, ms, f"not valid JSON steps: {text[:100]!r}"


async def main(models: list, pause: float) -> int:
    sys.path.insert(0, str(ROOT / "02_Reasoning_and_Routing"))
    from dom_fastpath import parse_command   # does the router's rule parser understand the step?
    out = {}
    async with httpx.AsyncClient(timeout=60) as client:
        for name in models:
            if not os.getenv(MODELS[name][1]):
                print(f"SKIP {name}: {MODELS[name][1]} not set")
                continue
            rows, bad = [], 0
            for request, gold in CASES:
                steps, ms, err = await call(client, name, request)
                row = {"request": request, "gold": gold, "ms": round(ms)}
                if steps is None:
                    bad += 1
                    row.update({"error": err, "steps": [], **score(gold, [])})
                else:
                    row.update({"steps": steps, **score(gold, steps)})
                    kinds = [parse_step(s)[0] for s in steps]
                    runnable = [parse_command(s).kind != "unknown" for s, k in zip(steps, kinds) if k != "ask"]
                    row["rules_can_run"] = f"{sum(runnable)}/{len(runnable)}"
                rows.append(row)
                await asyncio.sleep(pause)
            n = len(rows)
            exact = sum(r["exact"] for r in rows)
            right = sum(r["steps_right"] for r in rows)
            total = sum(r["steps_gold"] for r in rows)
            ms = [r["ms"] for r in rows if "error" not in r]
            summary = {"model": MODELS[name][2], "requests": n, "invalid_json": bad, "exact_plans": exact,
                       "steps_right": right, "steps_gold": total, "invented_steps": sum(r["invented"] for r in rows),
                       "missing_steps": sum(r["missing"] for r in rows),
                       "ms_median": round(statistics.median(ms)) if ms else None, "ms_max": max(ms) if ms else None}
            out[name] = {"summary": summary, "rows": rows}
            print(f"{name:<9} exact plans {exact}/{n} | steps right {right}/{total} | invented {summary['invented_steps']} "
                  f"missing {summary['missing_steps']} | invalid JSON {bad} | median {summary['ms_median']} ms (max {summary['ms_max']:.0f})", flush=True)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "plan_bench.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--pause", type=float, default=0.4, help="seconds between calls (rate limits)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.models.split(","), a.pause)))
