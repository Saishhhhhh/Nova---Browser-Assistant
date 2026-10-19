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
- **A spoken correction ("I said go to books.to scrape.com") was not understood as a correction.** It didn't start with a recognised navigation phrase, so it fell to the model-step, which tried to find something to click and picked the wrong thing. Left as a documented gap at the time; **since fixed** — see section 6a.

The benchmark was re-run after the two fixes (not to chase a better number, but because the context-size fix
changes what the model actually sees): 4/4 passed in both conditions, with the comparison answer this time
naming the cheaper book by title. The underlying finding in section 4 is unchanged by this — small-model
phrasing varies a little run to run regardless.

## 6a. The correction gap above, closed

Added a `CORRECTION` regex in `router.py` (same mechanism as the existing `FILLER` regex: a repeating prefix
strip, in `clean_command()`), recognising "no", "wait", "actually", "sorry", "i said", "i meant", "i mean" as
correction/retry markers. Once stripped, the real command underneath reaches the normal rules/`QUESTION`/
`needs_memory` checks unchanged — "no, I meant the second one" becomes "the second one", which Phase 2's own
referential-word handling already covers, so this mostly *unlocks* machinery that already existed rather than
adding new machinery.

Deliberately kept safe: a bare "No." or "no, thanks" is **not** treated as a correction (`is_correction()`
checks that something non-reaction is actually left after stripping), so those still fall through to `CHAT`
exactly as before — confirmed with a small test matrix (11 phrasings, including the two safety cases and the
exact live bug). Also extended: a correction said *while the assistant is busy* now cancels the in-flight step
(via the existing `cancel_agent()`) instead of only queuing the correction to run after it — tested end to end
([`test_cancel_correction.py`](../07_End_To_End_Latency/test_cancel_correction.py)): a long agent call was
confirmed genuinely in flight (`router._agent is not None`), the correction cancelled it (no record written,
the same "stopped, no answer spoken" behaviour as a plain "stop"), and the corrected "scroll down" then ran as
its own turn, successfully. All existing regressions (Exp 2 rules 13/13, handoff, `test_cancel.py`) still pass.

**Not attempted:** the deeper case of resolving *what* was wrong without the user re-stating it ("no, I meant
the search box" when nothing before made "the search box" obvious) relies entirely on Phase 2's existing
referential/memory handling, which was itself only lightly tested (Experiment 9, section 4). And the URL
space-splitting artefact from the original live bug (Sarvam's "books.to scrape.com") is untouched — a separate,
STT-side issue, not a router one; the agent's own search-and-recover behaviour (section 6) is still what
handles that case in practice.

## 6b. Live voice test of the fix itself: one regression found and fixed, one real gap confirmed

The user ran the fix live (headphones, the real app, not scripted). Most of it worked exactly as intended:

| Said | Result |
|---|---|
| "Click travel." then "I said click travel." | both clicked Travel correctly — the exact original bug, fixed |
| "Go back." then "No, I meant scroll down." | scrolled down, not confused by "no" |
| "No." (alone) | correctly silent, no action — not treated as a correction |
| A long "tell me about every book in detail" task, interrupted mid-reply by "No, I meant scroll up" | the reply was audibly cut off (confirmed: "26.3 s of the reply had been played" when it stopped), and "scroll up" ran next, correctly |

**One real regression, found and fixed on the spot:** "No thanks." got "Sorry, what should I do?" instead of
being treated as a decline. Cause: `CORRECTION` stripped "No " first, leaving "thanks.", which `TRAILING` then
stripped *completely* (its own pattern matches "thanks" with nothing required in front), leaving an empty
string — `clean_command`'s empty-fallback returns the *original, unstripped* text, and "No thanks." as a whole
doesn't match `CHAT` (which only recognises single-phrase reactions), so it fell through to the 2-word-fragment
clarify path. Fixed with `_safe_strip()`: each strip (`TRAILING`, then `CORRECTION`/`FILLER`) now backs out and
keeps its *input* unchanged if applying it would leave nothing, rather than falling all the way back past every
intermediate step to the raw original text. Re-verified against a 14-case matrix (including this exact phrase,
with and without a comma, and everything from section 6a) and the full Exp 2 regression suite (13/13) — no
regressions from the fix-to-the-fix.

**One real, confirmed gap — the thing flagged as uncertain going in:** "click the first book" then "no, I meant
the second one" did **not** pick the second book. Once "no, I meant" is stripped, "the second one" has no verb
("click") in front of it, so it never reaches `position_hints.py` (Experiment 8's ordinal resolver), which only
activates for a parsed *click* intent. Instead it fell to the router's own model-step, which tried to guess an
element from the bare phrase "the second one" and picked something unrelated. This is a real, separate gap from
the "No thanks." one: **a correction that replaces only the object, not the verb, needs the verb carried over
from the previous command** — conceptually the mirror image of the existing `pending` mechanism (which joins a
bare verb like "Click." with the object said next). Not fixed here; would need the router to remember the last
command's verb and re-attach it when a correction's remainder has none.

Also observed, not a bug: "click the first book" after an earlier "scroll down" picked a book further down the
page (position hints resolve against what's currently on screen, by design, from Experiment 8) — expected given
the page had scrolled, not something introduced by this change.

## 6c. A second live session: queued backlog was worse than useless, now fixed

A further live session surfaced a different, more consequential problem than anything above. The user said
"open github.com/saish" (garbled by STT into something that needed the agent's own search-and-recover
behaviour, section 6) — a genuinely slow task. **While it was running, they said three more things trying to
get its attention**, including "Hold hold hold stop stop stop stop." That phrase does **not** start with
"stop" (it starts with "Hold"), so `CANCEL` — anchored at the very start of the string — didn't match it. None
of the three utterances matched `CANCEL` or `is_correction()` either, so all three just queued, faithfully, to
run one after another once the original task eventually stopped (via a plain "stop" said at some point, whose
text isn't visible in the log at all — see below).

The consequence: each queued command went through its *own* slow path (one reached the agent again, one typed
nonsense into a search box via the model-step), so **saying more while frustrated made the wait longer, not
shorter** — the third, sensible command ("open github.com") didn't run until over a minute after it was said.

Two fixes, both requested directly by the user after this session:

1. **`cancel_agent()` now drains the job queue first.** Added `_drain_queue()`, called at the top of
   `cancel_agent()` in all cases (a cancelled agent step, a cancelled plan, and even "nothing to stop") — so a
   "stop" or a correction clears any backlog of "heard while busy" commands instead of making you sit through
   each one. Confirmed with [`test_cancel_drains_queue.py`](../07_End_To_End_Latency/test_cancel_drains_queue.py):
   two distractions were queued during a real slow agent call, "stop" was said, both were dropped (`queue size
   right after cancel: 0`), and the next real command ran immediately (2.9 s) instead of waiting behind them.
2. **A successful cancel now logs what was heard.** Previously, when `CANCEL.match()` succeeded inside
   `_while_busy`, it called `cancel_agent()` and returned immediately with no `self.say(...)` — unlike every
   other branch, which prints "(heard ... while working)". That made a successful stop look like it came from
   nowhere when reading the log back. Now prints `(heard "..." -> stop)` first.

What this does **not** fix, by the user's own choice: `CANCEL` still only matches "stop" as the very first
word ("Hold hold hold stop..." still won't be recognised as a stop). The user said they'll just say "stop"
first when they mean it, so loosening the match itself was explicitly left alone.

All existing cancel tests (`test_cancel.py`, `test_cancel_plan.py`, `test_cancel_correction.py`) and the Exp 2
regression suite (13/13) still pass after this change.

## 6d. A third live session: a plain regex rule retyped the search box, nothing to do with any model

Not a memory/planner bug at all — a **rules** bug (Experiment 2's `dom_fastpath.parse_command`), found in the
same run of live testing. After correctly typing "saishhhhhh" into GitHub's search box (itself a genuine
success — see the session before this one, where an explicit "all lowercase, no spaces" instruction got the
spelled-out letters assembled correctly), the user said **"Search now, like hit enter."**, meaning "submit
what's already there." Instead: the rule `^search(?:\s+for)?\s+(.+)$` captured *everything after the word
"search"* — "now, like hit enter" — as a brand new literal search query, retyped the box with that nonsense,
and pressed Enter on it, destroying the correct query it had just typed one turn earlier.

**This was asked about directly and the user correctly rejected my first answer**, which attributed it to "the
planning model acting dumb" — it isn't the planner, the model-step, or the agent; it's a plain string-matching
regex with no sanity check at all on what it captures.

**Fixed** in `dom_fastpath.py`: a new `submit` intent. `SUBMIT_TAIL` strips a trailing meta-instruction ("like
hit enter", "and press enter") and `SUBMIT_LEAD` strips a leading "now"/"go ahead" from a `search` match's
captured text; if nothing real is left, it becomes `submit` (press Enter, retype nothing) instead of `search`
with that leftover text as the query. A `BARE_SUBMIT` pattern also catches a standalone "hit enter" / "press
enter now" with no "search" in front at all. A real query combined with a submit tail still works normally
("search for cats, then hit enter" → searches "cats").

Confirmed end to end on a real page (Wikipedia): typed "saishhhhhh" into the search box *without* pressing
Enter, said "Search now, like hit enter.", and the URL afterward showed `search=saishhhhhh` — the existing
text was submitted, not overwritten. Exp 2's regression suite (13/13) still passes.

**Two more things this same session surfaced, neither fixed yet:**
- **GitHub's homepage sign-up overlay has no recognisable close mechanism.** `dismiss_popup()`'s Escape-key
  attempts and its `CLOSE_WORDS` list (close/dismiss/skip/no thanks) all missed it — even the agent itself,
  given 6 steps to look, found no close button, only "Sign in"/"Sign up" links that navigate away rather than
  dismissing it. Cost most of a turn and part of another fighting this one popup.
- **A vague, non-actionable utterance ("Saish has 6 H. Keep that in mind.") still reaches the full agent**,
  which then spent its whole step budget on an unrelated detour (trying to dismiss the same popup) rather than
  recognising there was no real instruction in it. `CHAT`/the short-fragment clarify check don't catch this
  because the sentence is long enough and doesn't match either pattern.

## 6e. A fourth live session: the popup check fired on a page that was never real, plus a filler-word gap

Asked directly after this session: *"tell me what wrong do u find here, it literally went to github and
typed github.com"* — on a completely fresh browser (no `--start-url`, nothing navigated yet), the very first
command, **"Search for GitHub."**, came back `tier=blocked`, `"A popup is covering the page and I could not
close it."` There was no popup, and no real page either.

**Root cause**: before any navigation, browser-use's own internal placeholder tab has the title
`"Starting agent <id>..."` — a real DOM, not `about:blank`. `_popup_present()`'s JS found a stray `DIV` on
that placeholder and reported it as a blocking popup, so the fast path refused to even try typing into a
search box, and the command fell through to the full agent, which is why it worked but took far longer than
it should have.

**Fixed** in `dom_fastpath.py`: a new `_on_real_page()` check (current URL starts with `http://`/`https://`),
called as the first line of both `_bot_check()` and `_popup_present()` — before navigation, there's nothing
real to check for popups on, so skip straight past.

Verified with an isolated script: on a blank browser, `search for GitHub` went from a false
`blocked: True, "a popup is covering the page..."` to the correct `blocked: False, "no search box found"`
(falls through toward the agent honestly, instead of lying about a popup). Confirmed real popup detection
still works unchanged: `go to flipkart.com` then `search for running shoes` still handled and submitted
normally. Exp 2's regression suite (13/13, 4/4) and the handoff suite (ALL PASSED) both still pass.

**Smaller fix from the same session**: `"Just search for github.com."` took the slow full-agent path (~16s)
because `"just"` wasn't in `router.py`'s `FILLER` word list, so the fast rules parser didn't recognise it as
a plain `search for X`. Added `just` alongside the existing `so`/`well`/`now` fillers — `"Just search for
github.com."` now strips to `"Search for github.com."` before the rules check, same pattern as every other
filler word already handled there.

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
  as provisional, not as the last word. Confirmed again in section 6b: the correction fix itself, after passing
  text-mode and scripted tests, still had a real regression ("No thanks.") that only showed up once tried live.
- Re-planning was only tested on one kind of failure (an element that does not exist). A failure caused by a
  slow page or a wrong page was not tried.
- **A correction that replaces only the object, not the verb** ("click the first book" / "no, the second one")
  picks the wrong thing — confirmed live, section 6b. The verb needs to carry over from the previous command;
  it currently doesn't.

## 8. Files

| File | What it does |
|---|---|
| [`../02_Reasoning_and_Routing/memory.py`](../02_Reasoning_and_Routing/memory.py) | `ConversationMemory`, `needs_memory()`, `compare_from_scratchpad()`, `COMPARE_QUESTION` |
| [`../02_Reasoning_and_Routing/planner.py`](../02_Reasoning_and_Routing/planner.py) | `replan_after_failure()` added; the comparison-step guidance added to `SYSTEM` |
| [`memory_bench.py`](memory_bench.py) | The 4-case, on/off benchmark |
| `results/memory_bench.json` | Raw per-case replies and timings, both conditions |
| [`../07_End_To_End_Latency/test_cancel_drains_queue.py`](../07_End_To_End_Latency/test_cancel_drains_queue.py) | Reproduces the live queue-backlog problem (section 6c) and confirms the fix |

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
- **Correction-language understanding** ("I said X", "no, I meant Y") — a real, observed gap (section 6), fixed
  and live-tested (sections 6a/6b), including one regression found and fixed live ("No thanks.").
- **Verb-carryover for object-only corrections** ("no, the second one" after "click the first book") — the one
  confirmed, still-open gap from the live test (section 6b). Needs the router to remember the previous
  command's verb and re-attach it when a correction's remainder is a bare object/position phrase with no verb
  of its own.
- **Phase 3+** (status display, one-command start, further site validation, synthesis) is next, per the plan
  discussed with the user; this experiment does not block any of it.
