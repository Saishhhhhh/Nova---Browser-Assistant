"""Part A, second half: run a multi-step request two ways and compare time and correctness.

  python plan_execute.py                # real browser, real model calls (a few cents)

  planned    : a model splits the request into steps (plan_bench's prompt), each step goes through the router:
               rules for go / click / scroll, the browser agent only for the final "ask" question
  agent only : the whole sentence is handed to the browser agent, as before this experiment
Five tasks on the two practice sites, each with a known correct answer.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for sub in ("02_Reasoning_and_Routing", "01_Browser Automation"):
    sys.path.insert(0, str(ROOT / sub))
sys.path.insert(0, str(HERE))

from browser_use import Browser  # noqa: E402
from config import EXTRACTION_MODEL, EXTRACTION_PROVIDER, get_browser_use_llm  # noqa: E402
from dom_fastpath import make_picker_from_env  # noqa: E402
from plan_bench import call as plan_call  # noqa: E402
from router import CommandRouter  # noqa: E402

TASKS = [  # (request, substrings that must all be in the answer, lower case)
    ("Go to books.toscrape.com, open the travel category, and tell me how many books are on the page", ["11"]),
    ("Open the mystery category on books.toscrape.com and tell me the title of the first book", ["sharp objects"]),
    ("Go to quotes.toscrape.com and tell me the first quote", ["world as we have created it"]),
    ("Go to quotes.toscrape.com, click the login link, and tell me what fields are on the page", ["username", "password"]),
    ("On books.toscrape.com open the first book and tell me its price", ["51.77"]),
]


WIKI_TASKS = [
    ("Go to Wikipedia, search for Alan Turing, and tell me what year he was born", ["1912"]),
    ("Go to Wikipedia, search for Python programming language, and tell me who created it", ["guido"]),
    ("Go to Wikipedia, search for Marie Curie, and tell me in which year she won her first Nobel Prize", ["1903"]),
]


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    browser = Browser(headless=True, no_viewport=True, keep_alive=True)
    await browser.start()
    router = CommandRouter(
        browser, picker=make_picker_from_env(), agent_llm=get_browser_use_llm("cerebras"),
        extraction_llm=get_browser_use_llm(EXTRACTION_PROVIDER, EXTRACTION_MODEL) if EXTRACTION_PROVIDER else None,
        agent_max_steps=8, agent_timeout=120.0)
    out = []
    tasks = WIKI_TASKS if "--wiki" in sys.argv else TASKS
    async with httpx.AsyncClient(timeout=60) as client:
        for request, must in tasks:
            row = {"request": request}
            # --- planned
            await router.run_command("go to example.com")      # neutral start for both ways
            t0 = time.perf_counter()
            steps, plan_ms, err = await plan_call(client, "gemma", request)
            row["plan_ms"] = round(plan_ms)
            row["steps"] = steps or []
            answer, log = "", []
            if steps:
                for st in steps:
                    t = time.perf_counter()
                    kind = st.strip().lower().split(" ")[0]
                    if kind == "ask":
                        r = await router._run_agent(st[3:].strip(" :") or st)   # a question about the current page
                    else:
                        r = await router.run_command(st)
                    log.append({"step": st, "tier": r.tier, "ok": r.ok, "ms": round((time.perf_counter() - t) * 1000)})
                    if kind == "ask":
                        answer = r.reply
                    if not r.ok and kind != "ask":
                        break
            row["planned"] = {"ms": round((time.perf_counter() - t0) * 1000), "answer": answer[:200],
                              "correct": bool(answer) and all(m in answer.lower() for m in must), "steps": log}
            # --- agent only
            await router.run_command("go to example.com")
            t0 = time.perf_counter()
            r = await router._run_agent(request)
            row["agent_only"] = {"ms": round((time.perf_counter() - t0) * 1000), "answer": r.reply[:200],
                                 "correct": r.ok and all(m in r.reply.lower() for m in must), "agent_steps": r.agent_steps}
            out.append(row)
            p, a = row["planned"], row["agent_only"]
            print(f"- {request[:70]}\n    planned   : {p['ms'] / 1000:5.1f} s  {'RIGHT' if p['correct'] else 'WRONG'}  "
                  f"(plan {row['plan_ms']} ms; steps {[ (s['tier'], s['ms']) for s in p['steps']]})  {p['answer'][:60]!r}\n"
                  f"    agent only: {a['ms'] / 1000:5.1f} s  {'RIGHT' if a['correct'] else 'WRONG'}  "
                  f"({a['agent_steps']} agent steps)  {a['answer'][:60]!r}", flush=True)
    await browser.kill()
    pl = [r["planned"]["ms"] for r in out]
    ag = [r["agent_only"]["ms"] for r in out]
    print(f"\nplanned: {sum(r['planned']['correct'] for r in out)}/{len(out)} right, median {sorted(pl)[len(pl)//2] / 1000:.1f} s | "
          f"agent only: {sum(r['agent_only']['correct'] for r in out)}/{len(out)} right, median {sorted(ag)[len(ag)//2] / 1000:.1f} s")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / ("plan_execute_wiki.json" if "--wiki" in sys.argv else "plan_execute.json")).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
