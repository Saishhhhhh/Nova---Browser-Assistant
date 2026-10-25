# Building Jarvis: a voice-driven browser assistant, from first principles to a working tool

*Written for: a technical reader (e.g. an interviewer) evaluating this as a portfolio project. It assumes no
prior context and explains what was tried, what was measured, what broke in practice, and why each decision
was made - not just what the final result is.*

## The premise

The goal was never "automate a browser" - browser automation is mature and well-served by existing tools.
The actual goal was to build a **voice-first assistant**: something you talk to, that talks back, and that
happens to act on a browser as its one skill. Speech is the headline feature; the browser is the hands.

That framing drove every decision below. A text-only agent can afford to be slow and verbose. A voice agent
cannot: every extra second of silence while "thinking" is felt directly, every unnecessary word spoken is
time the user is waiting, and every misunderstood word has to be caught and corrected in conversation, not
by scrolling back through a log. The project is organized as nine numbered experiments
(`experiments/01_...` through `09_...`), each answering one question with a measured benchmark before being
built into the real app - and then a tenth phase, this one, which took the working automation and turned it
into **Jarvis**: a named assistant with a floating status overlay, your own name, and your real Brave browser.

## Part 1: the experiments

### 1. Which browser-automation framework? (`experiments/01_Browser Automation`)

Three candidates - **browser-use**, **Stagehand v4**, **Playwright MCP** - were run against four real tasks
(a login form, an e-commerce filter-and-extract, a YouTube search, a GitHub repo traversal), each scored for
success, latency, step count, and token cost. **browser-use won**: it passed every task, and critically, it
is DOM-first (works from the page's actual interactive elements, not a screenshot or a semantic re-encoding),
which matters a lot for what came next. An early draft of this README overstated why agentic loops are slow
- it isn't the size of the per-step page listing (measured directly: 156 tokens on a trivial page), it's the
fixed overhead of the system prompt and action schema repeated every single step. That correction mattered:
it meant the fix wasn't "send a smaller page," it was "don't call the model every step at all" - which is
exactly what Experiment 2 built.

### 2. Reasoning and routing (`experiments/02_Reasoning_and_Routing`)

The core architectural decision of the whole project: **most commands don't need a model at all.**
"Scroll down," "go back," "search for X," "click the Sign In button" - these are mechanical. A full
agentic loop (read page, ask a model what to do, act, repeat) pays a multi-second, multi-call tax for
something a regex and a DOM query can do instantly and for free.

So `dom_fastpath.py` was built: a layer of **rules** (regex command parsing, label-matching DOM search,
scroll-and-verify, popup/bot-check detection) that handles the common case with zero model calls. When the
rules don't recognize the command, there's a **one-shot small-model step** (a single call to a cheap model
that picks one element to click or type into from the page's element list) - still one call, not a loop.
Only when *that* also fails does it escalate to the **full browser-use agent**, which can plan and take
several actions but costs real time. This three-tier router (`CommandRouter.run_command()`) is the spine
everything else sits on.

### 3. Speech-to-text (`experiments/03_Speech_To_Text`)

Five engines (Groq/Whisper, Deepgram, AssemblyAI, ElevenLabs, Sarvam) were benchmarked on word-error rate,
latency, and - specifically because this project's commands are mostly English with occasional Hindi/English
code-switching ("Hinglish") - how well each handled that mix. **ElevenLabs Scribe v2** came out most accurate
(0.6% WER); **Sarvam `saaras:v4`** was far faster (~0.14s vs ~0.8s) and handled Hinglish better. The initial
build shipped with Sarvam as primary for speed; later live testing (see Part 2) made accuracy the bigger
lever, and ElevenLabs became the default.

### 4. Voice activity detection (`experiments/04_Voice_Activity_Detection`)

Deciding *when you've finished speaking* turns out to be its own hard problem, independent of transcription
accuracy. A Silero VAD model, wrapped in a small state machine (`Endpointer`) that tracks a configurable
silence "hangover" before declaring an utterance done, was chosen over simpler energy-threshold detection -
it's far more robust to background noise and doesn't need per-environment tuning.

### 5. Text-to-speech (`experiments/05_Text_To_Speech`)

Benchmarked for naturalness and, again, latency to first audio - the gap between "the assistant decided what
to say" and "you can hear the first sound" is part of the felt responsiveness of the whole system. Deepgram
Aura-2 (voice: Phoebe) won on speed-to-first-byte with streaming support, which matters more for a live
conversation than marginal prosody differences.

### 6. Turn-taking (`experiments/06_Turn_Taking`)

The piece that makes it feel like a conversation rather than a walkie-talkie: **barge-in**. You can speak
over the assistant mid-reply and it stops instantly, rather than finishing its sentence. This needed its own
small architecture - a job queue, a single worker thread, and an `interrupt()` hook that silences playback
within one 20ms audio block - built and proven here before anything from Experiment 2 was wired in.

### 7. Putting it together, with every stage timed (`experiments/07_End_To_End_Latency`)

The first version of the actual runnable app: microphone → VAD → STT → the Experiment-2 router → browser →
TTS, with a full "waterfall" breakdown printed after every command (silence wait, transcription time, how
the router handled it, time to first spoken sound). This is also where replies stopped being a flat "Done."
and became specific ("Opened Travel.", "Scrolled down.", "Clicked the second result.") - because a voice
assistant that only ever says "Done." doesn't let you verify it did the right thing without looking at the
screen, which defeats the point of using voice at all.

### 8. Planning and position hints (`experiments/08_Planning_and_Position_Hints`)

Two things that only matter once commands get more ambitious: a **planner** that splits a request like "go
to Amazon, search for MSI monitors, and tell me the cheapest one" into individual steps run one at a time
through the router (rather than handing the whole sentence to the slow agent and hoping), and **position
hints** - resolving "the second result" or "the link at the top right" against the page's actual on-screen
layout, with no model involved, since pure label-matching has nothing to match against for a reference like
that.

### 9. Memory and live-testing-driven hardening (`experiments/09_Memory_and_Replanning`)

Two things were added here: a lightweight **conversation memory** (recent turns plus a small scratchpad of
remembered facts, so "which one is cheaper" can be answered from what was already found rather than
re-reading the page) and **one-shot re-planning** when a plan step fails outright.

But the more important thing this phase produced wasn't a feature - it was a **process**. The benchmark
proved the mechanisms worked in principle; it did not prove the app worked in practice. So the project
shifted to repeated live voice sessions: run the actual app, speak to it, paste the real terminal output,
find what's actually wrong, fix it, prove the fix with a direct reproduction (not just "looks right"), add a
regression test built from the literal failing transcript, and only then move on. This found and fixed, in
order: a correction-handling regression ("No thanks." was mangled by an over-eager strip order), a queued
backlog that made "stop" ineffective, a plain regex bug that let "Search now, like hit enter." retype a
correct search with garbage, a false-positive popup check that fired on browser-use's own pre-navigation
placeholder page, a filler-word gap, and - the most serious one - a search action on GitHub that **typed a
query and never pressed Enter, silently claiming success anyway**, found only by deliberately reproducing it
five times and getting it wrong four of those times. The fix for that last one is the clearest statement of
the lesson: **a result is only as honest as what it actually verifies** - the system now reads back what
landed in a box before trusting it, instead of assuming an action worked because no exception was thrown.

## Part 2: what live testing actually found (and what it means)

Every fix above came from the same loop: build, test live by voice, get a real failure, diagnose the actual
root cause (not the first plausible-sounding guess), fix it, prove it with a direct reproduction, write a
regression test from the literal transcript, confirm the full suite still passes, document it, commit it.
A few of these are worth calling out because they contradict an easy assumption:

- **"The model is dumb" was usually wrong.** More than once, a bug that looked like a language-model failure
  turned out to be a plain regex with no model involved at all (the "Search now, like hit enter." bug), or a
  false positive in a JavaScript popup check running on a page that was never actually loaded. Blaming the
  model first, without checking the deterministic code path, would have wasted real engineering time on
  prompt-tuning that could never have fixed either bug.
- **Success has to be verified, not assumed.** The GitHub search-box bug is the clearest example: the code
  reported "Searched for X" on every single attempt, even on the four out of five attempts where the typed
  text came out corrupted or nothing was typed at all. Nothing checked. The fix wasn't a smarter prompt or a
  retry loop that happened to work - it was reading back the actual DOM value before trusting it, and saying
  so honestly when it didn't match.
- **Spelling things out loud is a genuinely hard problem with no clean fix.** Letters spelled individually
  ("S-A-I-S-H") sometimes get mis-transcribed, sometimes get joined with stray spaces, and sometimes get
  dropped entirely by a model that was supposed to retype them faithfully. Some of this got a deterministic
  fix (collapsing a run of single letters into one word, with no model in that step); the rest - a model
  genuinely mishearing or miscounting - couldn't be patched after the fact, because no downstream code can
  invent information a transcription never captured. The honest answer was documenting a reliable phrasing
  (spell it plainly, nothing else in the sentence) rather than claiming a fix that didn't exist.

## Part 3: from automation to Jarvis

By the end of Part 2, the automation itself was solid, live-tested, and regression-covered. What it still
lacked was a product: it ran on a throwaway browser, had no name, no visible status, and no sense of who it
was talking to. The final phase turned it into **Jarvis**.

**Design decisions and why:**

- **Brave, your real profile, not a disposable browser.** Jarvis launches Brave with your actual Brave user
  profile - your bookmarks, saved logins, and extensions are there, because `ash/browser.py` points
  browser-use's `Browser` at your real executable and user-data directory rather than a fresh temp profile.
  The real trade-off, confirmed by reading browser-use's own source rather than assuming: Chromium profiles
  are locked to one running process, so Brave has to be fully closed first. The failure mode when it's still
  open doesn't look like a clean "profile locked" error - it looks like a generic crash - so `ash/browser.py`
  treats any launch failure there as "Brave is probably open" and says so plainly, with a hard timeout so a
  failed launch reports back in seconds instead of hanging.
- **A wake word, built from what already existed, not a new ML model - at first.** Saying the assistant's
  name before a command gates whether something gets acted on, so idle conversation in the room doesn't
  trigger actions. The first version was text-based only: it reuses the exact "strip a known prefix off the
  transcript" pattern the router already used for filler words and corrections, reacting after a full
  utterance is transcribed rather than the instant the name is spoken. That turned into its own short saga,
  below.
- **A floating overlay, not a dashboard tab.** A borderless, always-on-top Tkinter widget shows
  listening/thinking/speaking/error at a glance, draggable, with a settings gear for audio device selection -
  chosen over a browser-tab dashboard because the whole point is that it sits visibly over whatever you're
  doing, the way a real assistant's presence would.
- **A name and a greeting.** Jarvis greets you by name on startup and recognizes her own name in the wake-word
  gate - small, but it's the difference between a tool and something that feels addressed-to.

**What verification looked like for this phase:** every existing regression suite (`ash/tests/`) was re-run
after the move with zero behavior changes expected in the ported logic, and it caught two real bugs
introduced in the process - a wake-word check that incorrectly applied to test/script mode (breaking four
tests that inject commands directly), and an error-detection heuristic in the Brave launch path that never
actually matched Brave's real failure message. Both were found by running the suite, not by inspection, and
both are now fixed and covered.

## Part 4: the wake-word name saga, and a real acoustic engine after all

The assistant went through four names before settling - each change driven by a real finding, not taste:

1. **Ash** - the original name. STT consistently mangled it in ordinary sentences.
2. **Misa** - tried next, rolled back on request before it was properly tested.
3. **Rhasspy** - picked specifically to get a free, local, no-account acoustic wake-word engine
   ([openWakeWord](https://github.com/dscripka/openWakeWord)) instead of Porcupine, which requires a
   Picovoice account and rejects personal email addresses at signup. Rhasspy has a pretrained model, so no
   custom training was needed - but live testing found it was *also* hard to say and consistently
   mis-transcribed ("Raspy", "Raspberry", "Rashmi"). More importantly, replaying the exact same saved audio
   offline through the real detector scored 0.65-0.89 - well above threshold - while the live session had
   just rejected it. That gap pointed at a genuine integration bug, not a bad model: openWakeWord needs a
   little trailing audio after a word to recognize it confidently, and for a short utterance, the voice
   activity detector can decide you're done talking before that recognition catches up.
4. **Jarvis** - another pretrained openWakeWord model, chosen for being short and easy to say, with no
   training step either. Also deliberately *not* "Alexa" (suggested, then reconsidered): Alexa is Amazon's
   actual wake word, so saying it would trigger any real Echo device in the room, trademark issues aside.
   The timing bug above was fixed properly (a brief catch-up window lets the detector finish processing
   audio it already has before a rejection is finalized) rather than just hoping a different word would
   paper over it.

Even with the fix, Jarvis still missed an occasional quieter or rushed utterance live - confirmed with
`WAKE_DEBUG` score logging that it was a genuine low-confidence read, not the same timing bug recurring. No
wake-word engine, including commercial ones, has a 0% miss rate. The actual fix was to stop trusting the
acoustic signal alone: the wake decision now combines it with the text-based check using OR - either one
catching the name is enough. This only ever accepts more utterances than acoustic-only did, never fewer.

## Part 5: measuring the agent, not just finding its bugs

Everything above was live-testing-driven: run it, hit a failure, fix that specific thing, write a regression
test so it stays fixed. That proves specific bugs stay fixed. It does not answer "out of a broad set of
different tasks, what fraction actually succeed, and is that number consistent?" - the question Experiment 1
asked of candidate frameworks at the very start of the project, but that was never asked again of the
*finished*, fully-assembled router once rules, the model-step, and the full agent were all wired together.

`ash/benchmark.py` closes that gap: 15 tasks spanning plain navigation, search, scrolling, a named keystroke,
model-step element picking, three-tier full-agent extraction (checked against real, stable ground truth on
`books.toscrape.com` and `quotes.toscrape.com`, not just "it didn't crash"), and two deliberate edge cases -
a compound request run with no planner, and a genuinely unanswerable command that should be refused. Each
task runs from a fixed starting page and is repeated twice, since an LLM-driven agent is not perfectly
deterministic.

**Honest result, not a round number: 27 of 30 runs (15 tasks x 2 repeats) pass - 90%.** Every failure is
informative, not a mystery:

- **The compound task fails 2/2, by design.** It tests whether the bare router can do multi-part requests
  with no planner, and the honest answer is no - the model-step clicked "travel" and stopped, never reaching
  the second half of the request. That's exactly why the planner exists; this task's job was to show what's
  missing without it, not to pass.
- **The ambiguous-click refusal was inconsistent - 1/2** - and the reason is the most interesting result the
  benchmark produced. The task ("click the blue one," from a clean homepage, no blue element in sight) was
  meant to test a confident refusal. The first run did exactly that: declined in 3 steps, ~7 seconds. On the
  second run, the full agent spent its larger step budget exploring further and found a real blue "Add to
  Basket" button on a product page - books.toscrape.com's actual buttons are blue - and clicked it. That's
  not a bug; it's the agent being more resourceful than the task assumed. The honest finding here is that
  *the benchmark task itself* was based on a false premise (that no blue element existed anywhere reachable),
  not that the system misbehaved - a reminder that writing a benchmark that actually tests what you think it
  tests is its own non-trivial problem.
- **GitHub's own search combobox is still intermittently flaky to type into** - the same JS-vs-programmatic-
  input race documented earlier in this project. It showed up again in this run (an "m" dropped from
  "microsoft/playwright") but the task still passed, because the check also accepted the URL containing
  "playwright" - which it did, corrupted text and all. Worth knowing honestly: the check passed, the
  underlying typing still didn't land cleanly.

Building the benchmark itself caught a bug in the benchmark: an early version checked page state the instant
a command returned, which raced a still-settling navigation on Wikipedia and scored a genuine success as a
failure. Fixed by polling briefly instead of checking once - the same "verify, don't assume" lesson from the
GitHub search-typing bug earlier in this project, this time applied to the measurement tool itself.

## What's still open, honestly

- **STT mishearing a word outright** has no downstream fix - nothing after transcription can recover a word
  that was never heard correctly in the first place.
- **A correction that replaces only the object, not the verb** ("click the first book" / "no, the second
  one") picks the wrong thing, because the verb from the previous command doesn't carry over. Scoped and
  understood, not yet fixed.
- **Replacing the router's regex layer with one structured-parsing model call** was proposed as a more
  unified design and deliberately *not* built in the same pass as a batch of urgent live fixes - that's a
  large enough change to deserve its own measured comparison against the current system, not a rush job
  riding on the back of something else.
- **GitHub's own search combobox is still intermittently flaky** to type into (a JS-controlled component
  fighting programmatic input) - the fix shipped earlier was making the system honest when this happens, not
  making the site reliable; the benchmark caught this exact failure mode again.
- **An "unanswerable" command's outcome isn't actually consistent run to run** - sometimes a confident
  refusal in seconds, sometimes the agent uses its full step budget to explore further and takes a real
  action instead. Measured by the benchmark (`ambiguous_click_refused`, 1/2 passes), not yet addressed - and
  arguably not simply a bug, since the "wrong" outcome was the agent finding a real match the task didn't
  account for.

## Project layout

- `ash/` - the finished app. `run_ash.py` at the repo root is the single entry point.
- `experiments/01_...` through `09_...` - the full experimentation history this was built from, each with
  its own README documenting what was tested and measured. Kept in full, not summarized away, because the
  measurements and dead ends are as much the engineering work as the final answer.
