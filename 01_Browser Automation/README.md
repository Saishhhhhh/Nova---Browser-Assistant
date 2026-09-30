# Experiment 1 — Browser Automation Tool

**Status: complete.** Winner: **browser-use**, driven by **Cerebras `gpt-oss-120b`**, with page extraction offloaded to **DeepInfra `gemma-4-31B-it-turbo`**.

This folder holds the benchmark harness, the raw results, and the findings. The main finding goes beyond "which tool wins": on real, heavy pages the dominant cost is how much page content the agent sends to the model on every step, not which model or provider is used. That finding reshapes Experiments 2 and 8 (see [Implications](#implications-for-the-next-experiments)).

---

## 1. What was tested

**Question:** which browser-automation framework should be the action-execution layer of the voice agent, measured by task success, latency, DOM-first behaviour, and how easily it takes our own LLM provider?

**Candidates**

| # | Candidate | Approach | Status |
|---|---|---|---|
| 1 | [browser-use](candidate_01_browser_use/) (Python) | Autonomous agent: sends the page's interactive-element list to the model each step, model picks the next action | **Winner** |
| 2 | [Stagehand v4](candidate_02_stagehand/) (TypeScript) | Semantic primitives (`act`, `extract`) over a focused accessibility snapshot | Runner-up |
| 3 | [Playwright MCP](candidate_03_playwright_mcp/) (Python client + `@playwright/mcp`) | Raw browser tools exposed to the model; our own tool-calling loop | Dropped |
| – | Crawl4AI | One-shot page-to-markdown + one LLM call | Removed before the final runs: it cannot click or type, so it can't do most tasks |

**Tasks** (defined in [common/tasks.py](common/tasks.py))

| Task ID | Site | What it requires |
|---|---|---|
| `form_auth_and_state` | the-internet.herokuapp.com/login | Type credentials, submit, confirm the "secure area" banner |
| `ecommerce_filter_extract` | books.toscrape.com | Open the Travel category, open a book, extract title/price/UPC |
| `media_spa_navigation` | youtube.com | Search, open the first video, return its title (heavy, dynamic single-page app) |
| `github_repo_traversal` | github.com/microsoft/playwright | Open Issues, extract the first two open issues (live, changing data) |

**Metrics** (written per run to `results/*.json`, rolled up in [results/SUMMARY.md](results/SUMMARY.md)): success, total duration, time to first action (TTFA), step count, tokens (where the framework exposes them).

---

## 2. Final results (all candidates on Cerebras `gpt-oss-120b`)

These are the full-matrix runs. Earlier rows in `SUMMARY.md` are setup/debug runs on other providers.

| Candidate | Task | Result | Duration | TTFA | Steps | Tokens |
|---|---|---|---|---|---|---|
| browser-use | form_auth_and_state | PASS | 14.2s | 8.3s | 3 | n/a* |
| browser-use | ecommerce_filter_extract | PASS† | 70.2s | 10.0s | 5 | n/a* |
| browser-use | media_spa_navigation | PASS | 214.5s | 14.7s | 5 | n/a* |
| browser-use | github_repo_traversal | PASS† | 138.5s | 69.6s | 3 | n/a* |
| Playwright MCP | form_auth_and_state | PASS | 121.1s | 4.0s | 8 | 36,938 |
| Playwright MCP | ecommerce_filter_extract | PASS | 192.0s | 7.0s | 12 | 71,753 |
| Playwright MCP | media_spa_navigation | PASS | 140.8s | 4.0s | 8 | 63,390 |
| Playwright MCP | github_repo_traversal | PASS | 73.6s | 4.5s | 6 | 33,899 |
| Stagehand | form_auth_and_state | PASS | 70.9s | 5.7s | 5 | 6,539 |
| Stagehand | ecommerce_filter_extract | PASS | 70.6s | 4.5s | 4 | 15,050 |
| Stagehand | media_spa_navigation | FAIL‡ | 21.9s | 7.0s | 5 | 20,542 |
| Stagehand | github_repo_traversal | FAIL§ | 69.5s | – | 1 | – |

\* browser-use does not report token usage through our harness; it records 0.
† browser-use's own built-in "judge" (a second model call that checks the result) disputed these two successes as possibly not grounded in the page. For books.toscrape.com the model may simply know this well-known demo data; for GitHub the issue numbers are live, so that dispute is more credible and was not manually re-checked.
‡ Stagehand extracted a plausible video title but failed our check that the browser was actually on a `/watch` page.
§ Cerebras returned `Tokens per minute limit exceeded`: GitHub's page snapshot was too large for the account's per-minute budget.

### Why browser-use won

- **Only candidate to cleanly pass the hardest, most realistic task** (YouTube). Stagehand failed it.
- **Built-in self-check.** Its judge flags results it doubts instead of silently reporting success. That's useful for a voice agent that must say when it isn't sure.
- **Takes any provider** through its own LLM wrappers (`ChatLiteLLM`), DOM-first by default, vision optional.
- **Playwright MCP** passed everything, but only after a larger step budget, and it was the slowest and most token-hungry: raw tool calls need a separate call to find an element and another to act on it.
- **Stagehand** used far smaller prompts per action (~1.5k tokens per `act` on the login page) and was quickest on its passes, but it failed half the tasks. Its small, focused prompts are the model for the "trimmed page" idea in Experiment 2.

---

## 3. Provider journey (why Cerebras)

The same harness was run against several providers before settling. Each step produced a concrete lesson.

| Provider / model | What happened | Lesson |
|---|---|---|
| Groq `openai/gpt-oss-20b` (free) | Login task passed after retries (~30-39s). E-commerce failed 6/6: a single request needed 11,322 tokens against an **8,000 tokens/minute** cap, so retrying could never succeed. | Free-tier Groq is too small for browser-use page prompts. |
| DeepInfra `Qwen/Qwen2.5-72B-Instruct` | Passed e-commerce in 334.8s; calls repeatedly hit browser-use's 75s timeout. | DeepInfra speed varies hugely by model; this one is slow. |
| **Cerebras `gpt-oss-120b`** | Fast per call (~4s per step). Needed one fix (below). Hit per-minute token limits on heavy pages. | Fastest provider; the per-minute limit is the constraint. |
| DeepInfra `gpt-oss-120b-Turbo` / `gpt-oss-120b` as main model | Repeated invalid actions (`element_index` instead of `index`, invented `type` action, typing the search text into a local file instead of the page, empty actions). | DeepInfra does not appear to enforce browser-use's action schema the way Cerebras does. Keep the main model on Cerebras. |

Pricing decisions: Groq free tier; $5 each on DeepInfra and Cerebras. Total measured spend for the DeepInfra model benchmark was about $0.014.

---

## 4. The latency investigation (YouTube task)

The YouTube task was used to find out why runs took minutes when Cerebras generates at ~2,000+ tokens/s.

| Run | Main model | Extraction model | Duration | Notes |
|---|---|---|---|---|
| Full matrix | Cerebras gpt-oss-120b | same | 214.5s | Defaults: judge, planning/todo file, verbose output |
| + speed flags | Cerebras gpt-oss-120b | same | 159.8s | Extract step alone waited ~65s |
| + separate extraction model | Cerebras gpt-oss-120b | DeepInfra Gemma | 167.8s | Extract dropped to ~10s, but main-model calls 5 and 6 each waited ~60s |
| Main model on DeepInfra | gpt-oss-120b-Turbo | DeepInfra Gemma | 67.2s | Faster, but 10 steps full of invalid-action retries; the search text was never typed |
| Main model on DeepInfra | gpt-oss-120b | DeepInfra Gemma | 248.1s | Every call 10-35s, one 75s timeout, invalid actions |

**What the timings show**

- **Cerebras:** the first ~4 calls take ~4s each, then calls stall for almost exactly one minute. Stagehand logged an extraction taking 60,664 ms and one Cerebras error said `Tokens per minute limit exceeded`. Heavy pages exhaust the account's per-minute token budget in about four steps.
- **DeepInfra:** no per-minute stall, but each call is slow because the prompts are large (the same model answered a 7k-token test prompt in 3-4s).
- **Common root cause:** browser-use sends the page's full interactive-element list every step. YouTube pages have thousands of elements (the agent clicked element #8,844). Switching provider only changes how that cost shows up. This is an inference from timings; browser-use's per-step token counts are not yet logged.
- Smaller contributors: YouTube's first load hits an 8s page-readiness timeout; browser-use's default judge, planning (it writes a `todo.md`) and verbose reasoning add calls.

**Speed settings now in [candidate_01_browser_use/run_benchmark.py](candidate_01_browser_use/run_benchmark.py)**

| Setting | Effect |
|---|---|
| `use_judge=False` | Removes the extra verification call after every task |
| `enable_planning=False` | Stops the todo-file writing and re-planning calls |
| `flash_mode=True` | Shorter model output per step |
| `minimum_wait_page_load_time=0.25`, `wait_for_network_idle_page_load_time=1.0`, `wait_between_actions=0.1` | Shorter page-settle waits |
| `page_extraction_llm` from `EXTRACTION_PROVIDER` / `EXTRACTION_MODEL` | Sends extract calls to a different provider so they don't consume the Cerebras per-minute budget |

---

## 5. DeepInfra model benchmark (for the extraction model)

[deepinfra_model_bench.py](deepinfra_model_bench.py) sends each model a short prompt and a ~7k-token "page dump" with one target line to extract, then checks the answer. Prices were copied from deepinfra.com/pricing. Total time for the long prompt, two runs each:

| Model | Run 1 | Run 2 | Extraction | Cost per long call |
|---|---|---|---|---|
| `google/gemma-4-31B-it-turbo` | 2.22s | 1.80s | correct | $0.00064 |
| `openai/gpt-oss-120b-Turbo` | 1.93s | 1.74s | correct | $0.00114 |
| `mistralai/Mistral-Small-3.2-24B-Instruct-2506` | 1.79s | 3.32s | correct | $0.00054 |
| `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | 3.15s | 2.39s | correct | $0.00014 |
| `openai/gpt-oss-20b` | 2.18s | 3.52s | correct | $0.00023 |
| `openai/gpt-oss-120b` | 2.95s | 4.22s | correct | $0.00028 |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | 3.42s | 3.06s | correct | $0.00071 |
| `Qwen/Qwen2.5-72B-Instruct` | 2.73s | 22.16s | correct | $0.00256 |
| `ibm-granite/granite-4.2-3b` | 1.91s | 1.76s | **empty** | $0.00023 |
| `ibm-granite/granite-4.2-8b` | 4.10s | 2.97s | **empty** | $0.00046 |

- **Picked Gemma 4 31B turbo:** fastest in both runs alongside gpt-oss-120b-Turbo, correct, about half the cost, and it answers directly (13 output tokens vs 108 for gpt-oss, which spends tokens on hidden reasoning).
- Granite models used all 150 output tokens on hidden reasoning and never produced an answer.
- Timings vary by ±1-1.5s between runs; differences under a second are not meaningful.
- A per-token "generation speed" figure was dropped from the script: at these output lengths the whole answer arrives in one burst, which produced impossible numbers.

---

## 6. Caveats

- **One run per candidate per task** in the final matrix. Latency figures are indicative, not statistically solid.
- **Playwright MCP got a larger step budget** (task default + 6) because each action needs a find call and an act call. With the shared budget it ran out of steps on the login task. This is documented in its script.
- **Success checks differ slightly by candidate.** browser-use's check is "agent reported done"; Stagehand and Playwright MCP check the extracted data against the same per-task rules.
- **YouTube video playback fails** in the bundled Chromium ("can't play on your browser"), because it lacks proprietary codecs/DRM. It doesn't affect these tasks (they only read the title) but will matter if the product needs to play video; that needs a real Chrome/Brave install.
- **Search text typed into a file:** a failure mode seen only with gpt-oss on DeepInfra; noted because Experiment 2 should test for it.

---

## 7. Implications for the next experiments

1. **Don't send every command through browser-use's full agent loop.** Most voice commands are single actions. A router should handle known commands with no model call (e.g. YouTube search is a URL: the agent itself fell back to `youtube.com/results?search_query=...`), handle single commands on unknown pages with one model call on a trimmed page, and use the browser-use agent only for complex requests.
2. **Test with realistic voice commands**, not multi-step scripts like these four tasks.
3. **Candidate models must reliably produce browser-use's action format.** gpt-oss on DeepInfra did not.
4. **Page size per step is the main latency lever** (pruning, visible-area-only, caching between steps), ahead of model or provider choice.
5. **Log browser-use token usage** before optimising, so prompt sizes are measured instead of inferred.

---

## 8. Running it

### Setup

From the repository root:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cp .env.example .env        # then fill in keys
cd "01_Browser Automation/candidate_02_stagehand" && npm install   # Stagehand only
```

`requirements.txt` lists `litellm` explicitly: browser-use imports it for every non-OpenAI provider but doesn't depend on it. In the original environment it came from `unclecode-litellm`, installed by Crawl4AI. A fresh install from `requirements.txt` has not been tested.

Stagehand pins `zod` to 4.4.3, the exact version Stagehand 4.1.0 bundles; two zod copies break its types.

### Commands (run from `01_Browser Automation/`)

```bash
# browser-use and/or Playwright MCP (Python master runner)
../.venv/Scripts/python.exe run_comparison.py --framework browser-use --provider cerebras --task form_auth_and_state
../.venv/Scripts/python.exe run_comparison.py --framework all --provider cerebras --task all

# Stagehand (Node). Arguments are positional: <task|all> <provider>
cd candidate_02_stagehand
npx tsx run_benchmark.ts all cerebras

# DeepInfra model speed/cost/correctness benchmark (~$0.007 per full run)
../.venv/Scripts/python.exe deepinfra_model_bench.py
../.venv/Scripts/python.exe deepinfra_model_bench.py --models google/gemma-4-31B-it-turbo openai/gpt-oss-120b-Turbo
```

Providers: `cerebras`, `deepinfra`, `groq`, `openrouter`, `ollama`. Pass `--model` to override the model from `.env`.

On Windows PowerShell 5.1, chain commands with `;` rather than `&&`.

Stagehand writes its JSON into `results/`; `SUMMARY.md` picks it up the next time a Python run regenerates it.

### Layout

```
01_Browser Automation/
├── run_comparison.py            # master runner (browser-use, Playwright MCP)
├── config.py                    # provider factories; Cerebras schema patch; extraction model settings
├── deepinfra_model_bench.py     # standalone DeepInfra model benchmark
├── common/                      # tasks + telemetry (JSON per run, SUMMARY.md)
├── candidate_01_browser_use/    # winner
├── candidate_02_stagehand/      # Stagehand v4 (TypeScript)
├── candidate_03_playwright_mcp/ # dropped; kept as a record
└── results/                     # raw run JSON + SUMMARY.md
```

### Fixes made along the way (useful if you re-run)

- **browser-use + LangChain:** browser-use 0.13 needs its own LLM classes (`ChatLiteLLM`), not LangChain's `ChatOpenAI`. See `get_browser_use_llm` in `config.py`.
- **Cerebras `minItems` error:** Cerebras rejects the `minItems` keyword in browser-use's schema. browser-use has a `remove_min_items` option but its LiteLLM path never passes it, so `config.py` patches it on only when Cerebras is used.
- **Browser window on dual monitors:** pinned to the primary monitor at 1536×864 (`window_position` / `window_size`). `--start-maximized` split the window across monitors. The size is specific to the machine this ran on.
- **Playwright MCP:** the original script was a stub that called a non-existent tool (`navigate`) and reported success regardless. It now runs a real tool-calling loop against `@playwright/mcp` (the package name `@modelcontextprotocol/server-playwright` doesn't exist). The installed `mcp` SDK uses snake_case fields (`input_schema`, `is_error`).
- **Stagehand:** upgraded 1.14 → 4.1.0 and rewritten; v4 supports `cerebras/` and `groq/` model names natively, other providers go through an OpenAI-compatible callback.
