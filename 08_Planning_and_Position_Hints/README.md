# Experiment 8 — Planning and position hints

**Status: complete.**

| Question | Answer |
|---|---|
| Can "the second result" / "the link at the top left" be resolved without a model? | **Yes, with rules.** 19 of 19 targets on 3 real pages resolved to the element a person would point at (including 4 where refusing was the right answer); 4 of 4 real clicks landed |
| Can a model split a multi-step request into single steps? | **Yes.** Gemma 31B and `gpt-oss-120b` got 18 of 18 plans exactly right; Llama 3.1 8B 16 of 18 (it invented a step twice) |
| Is running the plan through the fast path faster than handing the whole request to the agent? | **No, not on its own.** About the same on harder pages (15.8 s vs 17.5 s median) and slower on easy ones (6.6 s vs 4.6 s) |

So: position hints go into the app as they are. The planner goes in too, but for what it gives (named steps to narrate and recover from), not as a speed-up.

---

## 1. Why this experiment

Experiment 2's router handles one action per command; anything else goes to the full browser agent. Two kinds of request needed a better answer:
- **Several actions in one sentence:** "go to Amazon, search for MSI monitors, and tell me the cheapest one".
- **Pointing at the screen instead of naming things:** "click the button at the top left", "open the second result".

Not in this experiment, because they are behaviours to build and test and not options to compare: spoken progress updates, cancelling a running task and error recovery. Those were built in Experiment 7 and the app.

## 2. Part B: position hints

### What was built
[position_hints.py](../02_Reasoning_and_Routing/position_hints.py), plugged into the router's click rule in [dom_fastpath.py](../02_Reasoning_and_Routing/dom_fastpath.py). No model.

1. **Page reader extension:** every element now carries its on-screen position (browser-use's DOM nodes already had it), whether it sits inside navigation / sidebar / header / footer, and the viewport and scroll position of the page read.
2. **Phrase parser:** a target is split into a *corner or edge* ("top left", "bottom", "left"), an *ordinal* ("second", "last", "3rd"), a *kind* (button, link, field, tab, image, or "item" for result / book / video / post ...) and any *label words* left over ("sign in").
3. **Resolver:** works only on what is on screen right now ("last" means the last one you can see). Filters by kind, drops duplicates (a result's picture and title are one result), ignores navigation furniture for "result / book / item", then picks the nearest to the corner or the n-th in reading order.
4. **Label first:** a clear label match (score 0.9 or more) always wins, so "Top Stories" or "(Top)" are still found by name. Position is used only when no label matches strongly.

### Results ([position_bench.py](position_bench.py): 3 real pages, 1280x800, nothing clicked, no model calls)

| Page | Targets | Correct |
|---|---|---|
| books.toscrape.com | first / second / last book, third result, link at the top left, button at the bottom right | 6 / 6 |
| quotes.toscrape.com | link at the top right, top left link, third link, login link at the top right, last link, second button (no buttons: must refuse) | 6 / 6 |
| en.wikipedia.org (Alan Turing) | top left link, top right link, button at the top, field at the top, second link, "sign in" link (page says "Log in": must refuse), twelfth link on the left (must refuse) | 7 / 7 |
| **All** | | **19 / 19** |

[test_position_click.py](test_position_click.py) clicks through the real fast path ("click the second book", "click the last book", "click the link at the top right", "click the third link"): **4 / 4** landed on the right page.

Experiment 2's own rule tests still pass (13/13 on this code; the committed code gave 12/13 on a different run because of one flaky external site).

### Corrections made while testing
- "sign in" lost its "in" (treated as filler). Fixed.
- "the button at the bottom right" on books.toscrape.com was first marked wrong, but my expectation was the error: the book cards do have "Add to basket" buttons. Recorded here as my mistake, not the resolver's.
- A first version tried position words before labels, which would have broken names like "Top Stories". Label-first fixes that.

## 3. Part A: planning

### The prompt
A small grammar of allowed steps (`go to <address>`, `search for ...`, `click ...`, `type ... into ...`, `scroll down/up`, `go back`, `ask ...`), the rules "one action per step, keep the user's words for click targets, never add steps", and a JSON reply. 18 requests ([plan_bench.py](plan_bench.py)): 15 multi-step (practice sites and real ones: Amazon, YouTube, Wikipedia, GitHub, Flipkart, Gmail, Hacker News, Reddit) and 3 single actions (the plan must not grow). Compared with hand-written plans.

### Results (final prompt, one run per model; run-to-run variance below)

| Model | Exact plans | Steps right | Invented | Median time | Slowest |
|---|---|---|---|---|---|
| **DeepInfra `gemma-4-31B-it-turbo`** | **18 / 18** | 48 / 48 | 0 | 0.97 s | 3.0 s |
| **Cerebras `gpt-oss-120b`** (low reasoning) | **18 / 18** | 48 / 48 | 0 | 0.40 s | **24.9 s** |
| DeepInfra `Llama-3.1-8B-Instruct-Turbo` | 16 / 18 | 47 / 48 | **2** | 1.28 s | 1.9 s |

Run to run: Gemma was 18/18 in every run; Llama 8B scored 16, 17 and 16 of 18, always with an invented or wrong extra step (for example a "scroll down" nobody asked for). gpt-oss's 25 s outlier appeared in every run.

Two findings that changed the setup:
- **Site names are not addresses.** With "go to <website or address>" the models wrote "go to Amazon", and the rules cannot navigate to that (8 of 38 action steps unparseable). Asking for an address ("go to amazon.com") fixed it: **0 of 38 unparseable**, so every non-question step can run on the fast path.
- **My scoring was too strict at first** (a paraphrase of a question, and "mail.google.com" for Gmail, were marked wrong). I changed the scoring after seeing that, so the gpt-oss improvement from 16 to 18 is partly the prompt and partly the scoring. The Gemma and Llama numbers did not depend on it.

### Running the plans ([plan_execute.py](plan_execute.py): real browser, real calls)
Each request is run two ways from the same start page: **planned** (the plan call, then each step through the router, with the browser agent only for the final "ask") and **agent only** (the whole sentence handed to the agent, as before).

| Tasks | Correct (planned / agent only) | Median time, planned | Median time, agent only |
|---|---|---|---|
| 5 on the practice sites | 5/5 and 5/5 | 6.6 s | 4.6 s |
| 3 on Wikipedia (search, then a fact) | 3/3 and 3/3 | 15.8 s | 17.5 s |

What the planned time is made of: the plan call 1.4 to 4.6 s, the fast-path steps 0.5 to 2 s each (page loads), and the final question to the agent 1.4 to 11.7 s (Wikipedia's long pages are the slow part). Three runs had a 50 to 70 s stall (one planned, two agent only), which looks like a provider latency spike (Cerebras) and not a property of either method.

## 4. Decision

- **Position hints:** keep, as built. They are rules, free, and handle the phrases that were tested.
- **Planner model:** **Gemma 31B on DeepInfra**, the model the router already uses for its model step: exact in all three runs, no long stalls. `gpt-oss-120b` is faster (0.4 s) and equally accurate but stalled for 25 s on one request in every run. Llama 8B is not safe: it invents steps.
- **Planning is not a speed-up** and should not be added in order to be faster. The plan call costs 1 to 3 s and the fast-path steps still wait for page loads. Its value is: named, inspectable steps; the chance to say "Opened the travel category" after each one; recovery when step 2 fails; and keeping the agent to one question instead of a long wander.
- **When to plan:** only when a request contains several actions (a conjunction joining verbs). A single command skips the planner and goes through the router as before.

## 4a. Update after the harder-sites rounds (see Experiment 7, section 4.3 and 4.4)
Position hints needed three further changes once real heavy sites were used: nouns such as "video / product / post / issue" prefer links whose address looks like that thing; the page is re-read when it has just changed (lists are drawn late); a popup or a "verify you are human" page is dealt with or reported before anything is clicked. On dense pages (15 or more look-alike links) the resolver **refuses** unless the address pattern identifies the items, and the model step picks from the labels: heuristics that preferred long titles still picked domain links and suggestion chips. The 19/19 and 4/4 results above still hold after these changes.

## 5. Caveats
- **Position hints:** 3 pages, 15 pointing targets and 4 refusal cases, written by me after looking at the pages. It is not a blind test, the pages are fairly clean, and dense or dynamic sites (Amazon, YouTube, feeds, pop-ups) are not covered. "result / item" depends on navigation being tagged as navigation.
- **Planning:** 18 requests in my own words, English only, one run each except where noted. The agent-only baseline is the router's own agent (Cerebras, 8 steps, `flash_mode`) and was much faster here than in Experiment 1 because these tasks are short; on heavy multi-step sites it would be slower and the comparison could change. Not measured.
- **Time numbers have a 50 s noise source** (provider stalls); medians are used for that reason, and 3 to 5 tasks is small.
- Nothing here was tested by voice; the planner would sit behind the same speech layer as Experiment 7.

## 6. Files

| File | What it does |
|---|---|
| [../02_Reasoning_and_Routing/position_hints.py](../02_Reasoning_and_Routing/position_hints.py) | Phrase parser and resolver (the reusable piece) |
| [position_bench.py](position_bench.py) | 19 targets on 3 real pages, no clicks, no model calls |
| [test_position_click.py](test_position_click.py) | 4 real clicks through the fast path |
| [plan_bench.py](plan_bench.py) | 18 requests x 3 models, scored against hand-written plans |
| [plan_execute.py](plan_execute.py) | Planned vs agent only on a real browser (`--wiki` for the Wikipedia set) |
| `results/` | One JSON per run |

```bash
cd 08_Planning_and_Position_Hints
python position_bench.py            # free
python test_position_click.py       # free (rules only)
python plan_bench.py                # a few cents
python plan_execute.py              # a few cents of Cerebras / DeepInfra, a real browser
```

## 7. What this hands to the app
- Position hints are already in the router's click rule.
- A `plan(request) -> steps` function (the prompt is in `plan_bench.py`) for multi-action requests, with Gemma, then run the steps and speak a short line after each.
- A "plan failed at step N" path that says what it could not do and asks, using Experiment 7's clarify mechanism.
