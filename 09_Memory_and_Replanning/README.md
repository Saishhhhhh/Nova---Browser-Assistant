# Experiment 9 — Conversation memory, scratchpad comparison, and re-planning (Phase 2)

**Status: complete.** Built and wired in: a scratchpad for facts found mid-plan, a short conversation history for
follow-up questions, and one re-plan attempt after a failed step. Tested against the same app **with these
turned off**, on 4 real scripted conversations, then exercised live by voice, which found two real bugs that
were fixed and re-confirmed (section 6).

**Benchmark result: 3 of 4 cases passed identically whether memory was on or off; the 4th (the actual comparison
answer) failed on the stricter check with memory on and passed without it, in the first run** — a result that is
not the clean "memory wins" story I expected going in, and is reported as found rather than re-run until it
looked better. After the two live-testing fixes (section 6), a repeat run passed 4/4 both ways, with the
comparison answer now naming the book; the underlying finding — that the browser agent recovers more on its own
than expected — still stands and is the one worth remembering from this round.

---

## 1. Why this experiment

Earlier in the session the user asked a direct question: *"will the agent have a conversation with me, like
should I buy these monitors, will it talk?"* — and a related one: *"does it have conversation memory, can it
compare two products on its own?"* Up to Phase 1, the honest answer was no: every command was independent, with
no memory of earlier turns, and a plan's final "ask" step had nowhere to put two different products' prices to
compare them. This experiment builds the three pieces that were missing and, critically, **measures whether they
actually make anything better**, rather than assuming they do because they sound like they should.

## 2. What was built

All in [`02_Reasoning_and_Routing/memory.py`](../02_Reasoning_and_Routing/memory.py) and an extension to
[`planner.py`](../02_Reasoning_and_Routing/planner.py), wired into
[`07_End_To_End_Latency/app.py`](../07_End_To_End_Latency/app.py):

| Piece | What it does |
|---|---|
| **Scratchpad + comparison** | Every "ask" step inside a plan has its answer remembered, keyed by the step's own text. The planner's prompt was extended so a comparison request ("should I buy the Acer or the MSI") produces one "ask" step per item plus a final verdict "ask" step. That final step, if it matches comparison wording (`COMPARE_QUESTION` — "cheaper", "which is", "should I buy", "worth it", ...) and the scratchpad has facts, is answered by a **separate, small model call reading only the remembered facts** (`compare_from_scratchpad`), not by sending the browser agent back to a page it has already left. |
| **Conversation history** | The app keeps the last 4 (command, reply) turns. A new command containing referential words (`needs_memory()` — "that", "it", "the cheaper one", "again", "compare", "earlier", ...) and more than two words gets the recent conversation and scratchpad facts appended *after* the real command text, so the rules and the question-detector still see the literal command first; only the agent (which reads the whole string as its task) sees the appended context. |
| **Re-plan once on failure** | When a plan step fails, the planner is called a second time with what was done, what failed, and why, asking for a replacement for the rest of the plan. Tried exactly once per plan — never looped — and only if nothing was produced does the plan give up and report how far it got. |

A `--no-memory` flag on `app.py` turns all three off, falling back to exactly Phase 1's behaviour, so the same
app could be benchmarked both ways.

## 3. The benchmark

[`memory_bench.py`](memory_bench.py): 4 scripted conversations, each run twice (memory on, memory off) against
the real app — real browser, real DeepInfra/Cerebras calls — with an automatic check on the actual spoken reply,
not a guess. One case is a deliberate **control**: it should pass identically either way, since nothing about it
touches memory.

| Case | What it needs | Memory ON | Memory OFF |
|---|---|---|---|
| Comparison: "tell me the price of the first book, then the second book, and tell me which is cheaper" | scratchpad | **FAIL** — "The first book is cheaper." (correct, but doesn't name it; my check wanted the title or both prices) | **PASS** — the agent's own answer named both books and both prices |
| Follow-up: ask a price, navigate to an unrelated page, then "what was the first book's price again" | conversation history | PASS — £51.77, correct | PASS — £51.77, also correct |
| Advisory question: "should I buy this book" (control) | nothing | PASS | PASS |
| Re-plan: click a button that does not exist, then "tell me what happened" | re-planning | PASS (replanned once, as designed) | PASS (correctly did **not** replan) |

**3 of 4 passed in both conditions; the comparison case failed with memory on and passed without it.**

## 4. What actually happened, and why that matters more than the pass/fail count

- **The comparison answer was correct either way, and the content tells the real story.** With memory, `compare_from_scratchpad` correctly identified the first book as cheaper from the two remembered facts (£51.77 vs £53.74) — but it answered "The first book is cheaper," not "A Light in the Attic, at £51.77, is cheaper than Tipping the Velvet," because the scratchpad's keys are the plan's own step text ("ask the price of the first book"), not the book's name, and the small compare prompt had no reason to repeat a title it was never given as a fact. **Without memory**, the final step went to the ordinary browser agent, which — while sitting on the second book's page — still produced "Which is cheaper, the first book (A Light in the Attic, £51.77) or the second book (Tipping the Velvet, £53.74)?", correctly naming both books and both prices, inside its normal step budget. It phrased this as a question rather than a statement, which the router marked as a failed step (`is_successful()` came back false) even though the content was exactly right — a separate, minor scoring quirk, not a memory problem.
- **The follow-up case did not actually distinguish the two conditions.** Both recalled the price correctly after navigating to an unrelated page. That means the browser-use agent, given a shared browser session and its own step budget, was *already* capable of recovering this fact on its own — most likely by browsing back within its own steps — without needing the conversation-history text I appended. **This is a real gap in this benchmark, not a hidden strength of memory**: a fact that is still findable by browsing is a weak test of "memory." A better test would use a fact the agent genuinely cannot re-derive by browsing (something the user stated that is nowhere on any page, or a price that has since changed), and that case was not built here.
- **Re-planning worked exactly as designed** — one attempt, no loop — but the retried step's actual content was poor: asked to explain what happened after a failed click, the agent's final answer was the literal string *"What happened?"* — effectively an empty echo of its own task, not an explanation. The mechanism is correct; the usefulness of what it produced, in this one case, was not.
- **The advisory-question control behaved identically both ways**, confirming memory on/off doesn't accidentally change anything it shouldn't — the one clean result in this round.

## 5. Decision

**Keep all three pieces, but do not claim they were proven necessary here.** They are cheap (a few hundred
milliseconds to ~2 s of extra model calls, only when triggered), they never made anything worse in this
benchmark, and they are very likely to matter in cases this benchmark didn't stress — e.g. comparing three or
more items (where the agent's own browsing can no longer hold everything in view at once), a fact that has
changed since it was last seen, or something only the user said and that appears on no page at all. What this
round actually demonstrates is a repeat of Experiment 8's finding about the planner: **the underlying browser
agent, given a reasonable step budget and a shared session, is more capable on its own than expected**, which
narrows — without eliminating — the case for building scaffolding on top of it.

One concrete improvement worth making before trusting the scratchpad path for real comparisons: `remember()`
should key and phrase facts with the actual item name, not the plan step's own wording, so `compare_from_scratchpad`
can name what it's comparing instead of saying "the first one."

## 6. Live voice test found two real bugs, both fixed

The benchmark above only ever ran in text mode. A live voice session (the user, by microphone, not scripted)
surfaced two real problems that no amount of text-mode testing would have caught, because they only show up
once conversations run long enough and commands get queued behind a busy assistant:

| Bug | What happened live | Fix |
|---|---|---|
| **Conversation-history context grew unbounded.** `max_turns=4` caps the *number* of turns kept, but not their *size* — each remembered reply was quoted in full. By turn 7 of one real session, the appended context was several full paragraphs long (every prior advisory answer, quoted verbatim), and some later agent calls visibly slowed down as a result (one took 31 s just to get "On it." out, mostly spent on a bloated prompt). | `memory.py`: every quoted command and reply is capped to 16 words (`_short()`), and the whole context block is capped again at 500 characters as a safety net, in case many scratchpad entries still add up. |
| **The waterfall's time breakdown didn't account for queueing.** When a command was transcribed while the assistant was still busy with a previous turn (see `_while_busy` in `app.py`), it waited in the job queue until that turn finished. The printed "silence + transcript + browser + voice" breakdown didn't include that wait, so one real line printed components adding to 4.3 s next to a reported "17.13 s until it started speaking," with nothing accounting for the other ~13 s — confusing to read, even though the total was correct. | `app.py`: both `_run_single` and `_handle_plan` now compute `queued_ms` (time between the real end of speech and when the job actually started being handled) and show it as its own line item whenever it exceeds 100 ms. |

Also observed live, not bugs, worth recording:
- **The agent recovered gracefully from a mis-transcribed URL twice**, on its own: given "books.tostrap.com" (Sarvam mangled "books.toscrape.com" into something that doesn't resolve), it tried `https://`, then `http://`, then searched DuckDuckGo for the string, found the real site, and navigated there — all within its own step budget, with no help from anything built in this project.
- **A nonsense fragment ("And yeah.") correctly triggered "Sorry, what should I do?"** rather than being guessed at.
- **"Stop" correctly cancelled a plan mid-flight, live**, confirming the Phase 1 mechanism tested only in text mode before.
- **The advisory-question answer, live, was genuinely context-aware**: asked "should I buy this book" on books.toscrape.com, the agent recognised it as a demo site with randomly generated prices and said so, rather than inventing confident real-world buying advice.
- **A spoken correction ("I said go to books.to scrape.com") is not understood as a correction.** It doesn't start with a recognised navigation phrase, so it fell to the model-step, which tried to find something to click and picked the wrong thing. Not fixed — documented as a known gap; handling "no, I meant X" framing well would need the router to recognise correction language and extract the real command from inside it, which is a real piece of work, not a quick fix.

The benchmark was re-run after the two fixes (not to chase a better number, but because the context-size fix
changes what the model actually sees): 4/4 passed in both conditions, with the comparison answer this time
naming the cheaper book by title. The underlying finding in section 4 is unchanged by this — small-model
phrasing varies a little run to run regardless.

## 7. Caveats

- **4 cases, one run each, one session, one speaker's phrasing of each request.** Not a statistically powerful
  test; it is a check that the mechanisms work and a first honest look at whether they help.
- **The follow-up case does not actually stress conversation history**, as explained above — a genuine test of
  memory's value needs a fact the agent cannot recover by browsing, which was not built into this round.
- **The comparison scratchpad case's "failure" is a strict-checker artefact as much as a real defect** — the
  compare answer was factually correct, just under-specific. Both are worth fixing (the naming issue is cheap
  to fix; "is this check too strict" is a benchmark question, not an app one).
- The scored benchmark (section 3/4) ran in text mode only. It was tried live by voice separately (section 6),
  which found real bugs text mode couldn't — so text-mode-only testing of any new mechanism should be treated
  as provisional, not as the last word.
- Re-planning was only tested on one kind of failure (an element that does not exist). A failure caused by a
  slow page or a wrong page was not tried.
- A spoken correction ("I said X", "no, I meant Y") is not understood as a correction (section 6) — it is run
  as a literal new command, which can go badly wrong (it was interpreted as a click target in the live test).

## 8. Files

| File | What it does |
|---|---|
| [`../02_Reasoning_and_Routing/memory.py`](../02_Reasoning_and_Routing/memory.py) | `ConversationMemory`, `needs_memory()`, `compare_from_scratchpad()`, `COMPARE_QUESTION` |
| [`../02_Reasoning_and_Routing/planner.py`](../02_Reasoning_and_Routing/planner.py) | `replan_after_failure()` added; the comparison-step guidance added to `SYSTEM` |
| [`memory_bench.py`](memory_bench.py) | The 4-case, on/off benchmark |
| `results/memory_bench.json` | Raw per-case replies and timings, both conditions |

```bash
cd 09_Memory_and_Replanning
python memory_bench.py          # real browser, real model calls, ~8 runs, a few cents
```

Also exercised ad hoc while building this, in `07_End_To_End_Latency/`: `test_memory_commands.txt` (comparison +
follow-up), `test_replan_commands.txt` (the re-plan path) — these are what actually found the one real bug fixed
along the way (below), not the scored benchmark itself.

## 9. One real bug found and fixed along the way (the planner/router integration)

Planner-emitted steps use the literal word `"ask ..."` for a question step. The router's `QUESTION` detector
(added in Phase 0/Experiment 7 to skip a wasted model-step call on natural questions like "tell me" or "what")
did **not** recognise the word "ask" itself. So a plan's `"ask the price of the first book"` step fell through to
the router's model-step, whose job is picking something to click — and it guessed a click instead of recognising
it could not answer and refusing, which then poisoned the scratchpad with a non-answer. Fixed by adding `ask` to
`QUESTION` in [`router.py`](../02_Reasoning_and_Routing/router.py). Confirmed fixed: the same comparison case
went from a garbled scratchpad to two correct prices once this was in. This is the kind of integration bug that
only shows up once two separately-built pieces (the planner's own grammar, the router's question detector) are
actually run together — exactly why this was tested end to end before being called done.

## 10. What this hands on

- **The app** already has all three mechanisms wired in behind `args.memory` (default on; `--no-memory` to
  disable). No further wiring needed.
- **A genuine memory-value test**, if ever wanted: a case where the correct answer requires a fact that no page
  currently reachable by the browser contains — the gap this round left open.
- **Correction-language understanding** ("I said X", "no, I meant Y") — a real, observed gap (section 6), not
  attempted here. Would need the router to recognise correction framing and pull the real command out of it.
- **Phase 3+** (status display, one-command start, further site validation, synthesis) is next, per the plan
  discussed with the user; this experiment does not block any of it.
