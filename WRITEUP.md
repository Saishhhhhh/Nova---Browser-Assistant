# Building Rhasspy: a voice-driven browser assistant, from first principles to a working tool

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
into **Rhasspy**: a named assistant with a floating status overlay, your own name, and your real Brave browser.

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

## Part 3: from automation to Rhasspy

By the end of Part 2, the automation itself was solid, live-tested, and regression-covered. What it still
lacked was a product: it ran on a throwaway browser, had no name, no visible status, and no sense of who it
was talking to. The final phase turned it into **Rhasspy**.

**Design decisions and why:**

- **Brave, your real profile, not a disposable browser.** Rhasspy launches Brave with your actual Brave user
  profile - your bookmarks, saved logins, and extensions are there, because `ash/browser.py` points
  browser-use's `Browser` at your real executable and user-data directory rather than a fresh temp profile.
  The real trade-off, confirmed by reading browser-use's own source rather than assuming: Chromium profiles
  are locked to one running process, so Brave has to be fully closed first. The failure mode when it's still
  open doesn't look like a clean "profile locked" error - it looks like a generic crash - so `ash/browser.py`
  treats any launch failure there as "Brave is probably open" and says so plainly, with a hard timeout so a
  failed launch reports back in seconds instead of hanging.
- **A wake word, built from what already existed, not a new ML model.** Saying "Rhasspy" before a command
  gates whether something gets acted on, so idle conversation in the room doesn't trigger actions. This is
  *not* an acoustic wake-word engine (Porcupine, openWakeWord) - that needs a trained model for a custom name
  and a new dependency. Instead it reuses the exact "strip a known prefix off the transcript" pattern the
  router already used for filler words and corrections. The honest trade-off: it reacts after a full
  utterance is transcribed, not the instant the name is spoken, the way a real wake-word engine would.
- **A floating overlay, not a dashboard tab.** A borderless, always-on-top Tkinter widget shows
  listening/thinking/speaking/error at a glance, draggable, with a settings gear for audio device selection -
  chosen over a browser-tab dashboard because the whole point is that it sits visibly over whatever you're
  doing, the way a real assistant's presence would.
- **A name and a greeting.** Rhasspy greets you by name on startup and recognizes her own name in the wake-word
  gate - small, but it's the difference between a tool and something that feels addressed-to.

**What verification looked like for this phase:** every existing regression suite (`ash/tests/`) was re-run
after the move with zero behavior changes expected in the ported logic, and it caught two real bugs
introduced in the process - a wake-word check that incorrectly applied to test/script mode (breaking four
tests that inject commands directly), and an error-detection heuristic in the Brave launch path that never
actually matched Brave's real failure message. Both were found by running the suite, not by inspection, and
both are now fixed and covered.

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
- **The wake-word gate is software, not hardware-level listening** - see above. A real offline wake-word
  engine remains a clearly-labeled stretch goal.

## Project layout

- `ash/` - the finished app. `run_ash.py` at the repo root is the single entry point.
- `experiments/01_...` through `09_...` - the full experimentation history this was built from, each with
  its own README documenting what was tested and measured. Kept in full, not summarized away, because the
  measurements and dead ends are as much the engineering work as the final answer.
