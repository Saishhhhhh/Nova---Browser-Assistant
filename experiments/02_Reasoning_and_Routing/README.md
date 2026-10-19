# Experiment 2 — Reasoning model and command routing

**Status: complete.** Result: a three-step router that is fast for common commands and falls back to the full browser agent for everything else.

1. **Rules** (no model): generic text matching over browser-use's page reader.
2. **One short model call**, only when the rules refuse: **DeepInfra `gemma-4-31B-it-turbo`**, 10-second limit.
3. **The full browser-use agent** (Experiment 1's winner, on Cerebras `gpt-oss-120b`), only when 1 and 2 both decline, on the same open browser.

The single entry point is `CommandRouter.run_command(text)` in [router.py](router.py). It is meant to be the one function the speech layer calls.

---

## 1. Why this experiment changed shape

Experiment 1 showed that sending every command through browser-use's agent loop is far too slow for voice: each step is a model call, and a multi-step task on a heavy site took 160 to 250 seconds. The README plan asked for a "reasoning model comparison". The useful question turned out to be different: *how many commands can skip the agent loop entirely, and which model is good enough for the rest?*

No per-site code was written (no site adapters). Everything below works on any site by matching the words in a command against what is on the page.

---

## 2. What was built

| File | What it does |
|---|---|
| [dom_fastpath.py](dom_fastpath.py) | Understands a command, reads the page, picks the element, acts. Contains the rules, the model step and its providers. |
| [router.py](router.py) | `run_command(text)`: rules, then model step, then the agent. Refuses to start unless the browser was created with `keep_alive=True`. |
| [test_fastpath.py](test_fastpath.py) | Rules on 5 real sites; checks the real outcome (URL, page text, scroll position), not what the code claims. |
| [test_model_step.py](test_model_step.py) | Offline checks (reply parser, defaults, time limit) plus a real browser with a stand-in model. `--live` calls a real model. |
| [bench_model_step.py](bench_model_step.py) | The 18-command benchmark, one model per run, saved to `results/`. |
| [test_handoff.py](test_handoff.py) | Fast path to agent handoff on one shared browser (real calls, a few cents). |
| `results/` | One JSON per benchmark run, including the invalid Cerebras run kept as evidence. |

### The rules

A command is matched against a few patterns: go to a site, `search for X`, `type X into Y`, `scroll up/down`, `go back`, and `click / press / tap / select / choose / open / hit Z`. The page is read with browser-use's own page reader (a numbered list of clickable things and fields). The element is chosen by comparing the words in the command to each element's visible text, accessible name, `aria-label`, `title` and placeholder, with a score. Below a score of 0.6 the rules **refuse** instead of guessing. The action then runs through browser-use's own click, type, scroll and navigate actions, with no agent involved.

Details that mattered once it ran on real sites:
- **Wait for the page to settle** (up to 4 seconds) after a navigation, search or click, because single-page apps change the URL before the content appears.
- **Retry an empty page read** up to 3 times.
- **Scroll checks itself:** it measures the scroll position, and if the page did not move it waits until the page is taller than the window and tries once more.

### The model step

When the rules refuse, one short call is made. The model sees the command and a compact list, `[13] button "search"`, capped at 250 elements, and must answer with one line of JSON: click an index, type text into an index, or `none`. The reply parser is strict: anything unusable, an index that is not on the page, an exception, or a call longer than the time limit all count as **refused**, and nothing is clicked.

Providers: DeepInfra (default), Cerebras, and local Ollama, switched with `FASTPATH_PROVIDER` in `.env`. Cerebras gets `reasoning_effort=low` so hidden reasoning doesn't use up its answer budget. Ollama is called through its own API with an 8,192-token context and forced JSON, because the OpenAI-style endpoint left it at 4,096 tokens and silently cut off long page lists.

---

## 3. Results

### 3.1 The prompt browser-use sends (a correction to Experiment 1)

Measured locally with no API calls:

| Part of each request | Size |
|---|---|
| System prompt, default mode | 5,242 tokens |
| System prompt, `flash_mode` | 504 tokens |
| Action schema (the JSON shape the model must answer in) | ~4,100 tokens |
| Page list: login form | 156 tokens (7 elements) |
| Page list: books.toscrape | 2,243 tokens (189 elements) |
| Page list: YouTube home | 963 tokens (57 elements) |
| Page list: GitHub repo | 8,096 tokens (396 elements) |

Cross-check: the login-page request Groq rejected in Experiment 1 was about 9,500 tokens, which is 5,242 + 4,114 + 156. So about 9,400 tokens of every default-mode step are fixed overhead, and the page itself is usually the smaller part. Experiment 1's README had blamed the page size; that has been corrected there. Not measured: YouTube search and watch pages, and how the history grows per step.

### 3.2 Rules only (no model, no tokens)

5 sites, about 15 commands, outcomes checked in the browser:
- **Passed:** click by visible text (books.toscrape categories and a book, GitHub's Issues tab), search on Wikipedia and YouTube, typing into a named field (read back from the field), scroll, go back, go to a site.
- **Refused correctly:** "click the blue one", "click the thing that looks like a basket", "play the first video", "what is on this page".
- **Speed:** most commands took **1.4 to 2.8 seconds** including about 0.5 seconds of settling and 0.2 to 1.2 seconds of page reading. Going to a new site took 1.4 to 8.8 seconds.
- **Scroll:** before the check-and-retry it passed in 1 of 3 runs of the YouTube scenario. The final version passed 3 of 3 (two earlier runs were lost to a bug of mine in the first version of the retry, since fixed).
- **One flaky scenario:** the-internet.herokuapp.com's login page passed in 3 of 12 full runs. browser-use's own log shows that site sometimes renders an empty page on first load and has to reload, which took about 20 seconds. That is the site, not the rules.

### 3.3 The model step: 18 commands on 8 models

The command set: 14 should act, of which 1 is a control the rules handle themselves (so "of 13" below), and 4 must be refused (vague or multi-step: "click the blue one", "what is on this page", "compare the first two books", "delete everything"). Commands are phrased the way people talk ("take me to the pull requests", "show me the page history", "put quantum computing in the search"). Each is run on a real page and the result is checked in the browser. Temperature 0, one run per model.

| Model | Correct (of 13) | Wrong click | Safely refused | Vague refused (of 4) | Median call | Slowest |
|---|---|---|---|---|---|---|
| **Gemma 4 31B Turbo** (DeepInfra) | **11** | 1 | 1 | 4 | 1.4s | 3.3s |
| gpt-oss-120b (Cerebras, paced) | 10 | 1 | 2 | 4 | **0.43s** | 1.0s |
| gpt-oss-120b Turbo (DeepInfra) | 10 | 1 | 2 | 4 | 1.6s | 2.2s |
| Llama 3.3 70B Turbo (DeepInfra) | 10 | 1 | 2 | 4 | 3.3s | 7.5s |
| Llama 3.1 8B Turbo (DeepInfra) | 9 | 2 | 2 | 1 | 1.3s | 2.8s |
| llama3.2:3b (local) | 4 | 6 | 3 | 3 | 2.9s | 13.0s |
| qwen2.5:3b (local) | 3 | 9 | 1 | 1 | 2.9s | 4.7s |
| phi4-mini 3.8B (local) | 3 | 8 | 2 | 0 | 4.5s | 10.4s |

"Wrong click" means it clicked something and the page was not where it should be. "Safely refused" means it declined a command it should have handled, which falls back to the agent. A refusal is much cheaper than a wrong click.

What the results say:
- **About 30B and up works.** The four larger models got 10 to 11 of 13 right with one wrong click each, and refused every vague command.
- **8B and below does not.** Llama 8B and all three local models guessed on vague commands: "click the blue one" and "delete everything" made them click "add to basket"; phi4-mini acted on all four. They were also right only 3 to 9 times of 13.
- **Local is also slower,** 2.9 to 4.5 seconds per call on a 4GB-VRAM GPU against 0.4 to 1.6 seconds for the cloud models.
- **The typical mistakes** of the good models: "take me to the main page" (picked the page-wide "main menu" element), and "where are the releases" (Gemma clicked "166 tags"). All four larger models refused "go to the next page", a safe failure.

### 3.4 Cerebras and its rate limit

The first Cerebras run looked flawless: no wrong clicks and all four vague commands refused. It was invalid. **7 of its 17 calls failed with a rate-limit error**, and the benchmark counted each failure as a refusal. About 10,000 tokens in roughly 90 seconds was enough to trigger it. That run is kept as `results/bench_cerebras_gpt-oss-120b_UNPACED_7_of_17_rate_limited.json` and excluded from the table. The benchmark now records failed calls in its summary, and a `--pause` option spaces the commands out; the Cerebras row above is the re-run with 20-second pauses (0 failed calls).

So Cerebras is about 3 times faster than Gemma but fails on back-to-back commands, which is how a voice assistant is used. DeepInfra had no failed calls in 4 runs of 17. I did not see the account's actual limit; this comes from the failures.

Every other saved benchmark was checked and had 0 failed model calls and 0 errors.

### 3.5 Handoff to the agent

`test_handoff.py`, real calls, one shared browser, all checks passed:

| Step | Result |
|---|---|
| "go to books.toscrape.com", "click travel" | rules, about 1.9s each |
| "tell me the title of the first book on this page" | rules declined, Gemma answered "none", the agent took over and answered "It's Only the Himalayas" in 1 step, 5.4s in total (2.8s of it the fast path trying) |
| Where the agent started | the Travel page the fast path had left it on, not from scratch |
| Afterwards | the browser was still open and the fast path worked again |

The browser must be created with `keep_alive=True`. Without it browser-use closes the browser when the agent finishes.

---

## 4. Decision

- **Model step:** DeepInfra `gemma-4-31B-it-turbo`, 10-second limit. It was the most accurate, never rate-limited, and is already the page-extraction model. A model that does not answer within the limit counts as a refusal and the command moves on to the agent. Gemma's slowest call was 3.3 seconds, Llama 70B's 7.5.
- **Cerebras `gpt-oss-120b`** is an optional switch (`FASTPATH_PROVIDER=cerebras`) for when speed matters more than reliability. It stays the agent's model, as in Experiment 1.
- **No local reasoning model.** Nothing at 8B or below was safe enough.
- **Spend:** well under 10 cents for the whole experiment.

---

## 5. Caveats

- **Small sample:** 18 commands, one run per model, four sites (books.toscrape, GitHub, Wikipedia, YouTube). A one-command difference is not meaningful, so the ranking among the four larger models is weak; the gap between them and the small ones is not.
- **Local models were tested under different conditions:** they used a different prompt (with examples) and Ollama's own API. A first attempt through the OpenAI-style endpoint scored 3 of 6 on a short check, partly because long page lists were silently cut off. Only qwen2.5:3b, llama3.2:3b and phi4-mini were run fully. gemma2:2b was stopped partway and is not in the table, and other installed small models (xlam, hammer2.1, lfm2.5, granite, smollm2, qwen3:1.7b, phi3.5, llama3.2:1b) were not tried.
- **"Play the first video"** only checks that a video page opened, not that it was the first result.
- **The handoff was tested on one easy question,** which the agent answered in one step. Heavy sites are still as slow as in Experiment 1.
- **Not tested:** Amazon or other bot-protected sites, popups and cookie banners, iframes, non-English commands, commands that need several steps, position commands like "the button at the top left".
- **The page-settle wait** can cost up to 4 seconds on pages that never stop changing, such as YouTube. It is the biggest remaining delay in the rules path.
- **A wrong click still happens about once in 13 commands** on the good models. Checking that the page actually changed after a click would catch some of these.

---

## 6. Not built yet (for the final project)

- A **planner** that splits "go to Amazon and compare LG and MSI monitors" into small steps the fast path can run, with the agent for the hard ones and a spoken summary at the end. Today that command would go to the agent, untested.
- **Position hints** ("top left") in the list sent to the model.
- **Mid-task instructions.** browser-use's agent has `pause()`, `resume()`, `stop()` and `add_new_task()`; nothing here calls them yet.
- **Per-step token logging** for the agent.
- The speech layer, and spoken progress ("on it", "still working") for slow steps.

---

## 7. Running it

From this folder, using the repo's `.venv`. Keys come from the root `.env` (see `.env.example`).

```bash
# Rules on 5 real sites (no API calls)
../.venv/Scripts/python.exe test_fastpath.py            # add --headed to watch

# Model-step checks: offline plus a stand-in model, no API calls
../.venv/Scripts/python.exe test_model_step.py
../.venv/Scripts/python.exe test_model_step.py --live   # real model, ~6 short calls

# The 18-command benchmark, one model per run (real calls; --pause for Cerebras)
../.venv/Scripts/python.exe bench_model_step.py --provider deepinfra --model google/gemma-4-31B-it-turbo
../.venv/Scripts/python.exe bench_model_step.py --provider cerebras --model gpt-oss-120b --pause 20
../.venv/Scripts/python.exe bench_model_step.py --provider ollama --model qwen2.5:3b   # needs `ollama serve`

# Fast path to agent handoff (real calls, a few cents)
../.venv/Scripts/python.exe test_handoff.py
```

Settings in `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `FASTPATH_PROVIDER` | `deepinfra` | `deepinfra`, `cerebras` or `ollama` |
| `FASTPATH_MODEL` | provider's default | e.g. `google/gemma-4-31B-it-turbo` |
| `FASTPATH_TIMEOUT` | `10` | seconds to wait for the model before treating the command as refused |

Using the router from code:

```python
browser = Browser(keep_alive=True)          # keep_alive is required
await browser.start()
router = CommandRouter(browser, picker=make_picker_from_env(),
                       agent_llm=get_browser_use_llm("cerebras"))
result = await router.run_command("take me to the pull requests")
# result.tier is "rules", "model", "agent" or "failed"; result.reply is a short line to speak
```
