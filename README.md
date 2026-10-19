# Voice-Driven Browser Agent — Architecture & Experimentation Plan

## Part 1: Architecture Plan

### Design principle
Every component sits on a **local-first, fast path with an API escalation path**. The system should default to the cheapest/fastest thing that works, and only reach for a heavier model when the fast path signals low confidence or the task genuinely needs deeper reasoning (multi-step planning, ambiguous references).

### High-level pipeline

```
Mic input
   │
   ▼
[VAD] ── detects speech start/end, gates everything downstream
   │
   ▼
[STT] ── streaming transcription (local, fast)
   │
   ▼
[Router] ── decides: simple/known intent → fast local path
                      complex/ambiguous  → API reasoning path
   │
   ├──► [Local Reasoning Model] (small LLM, DOM-only, deterministic actions)
   │
   └──► [API Reasoning Model] (bigger LLM, multi-step planning, handles ambiguity)
                │
                ▼
        [Page Perception Layer]
          └─ DOM/accessibility-tree extraction (DOM-only: no vision fallback)
                │
                ▼
        [Action Execution] ── browser automation layer (click/type/navigate/scroll)
                │
                ▼
        [Verification] ── did the action produce the expected state change?
                │
                ▼
        [Response Generation] ── short natural-language status/question
                │
                ▼
        [TTS] ── speaks back, interruptible (barge-in aware)
```

### Component roles

**VAD (Voice Activity Detection)**
Gatekeeper for the whole loop — nothing downstream should run on silence. Also responsible for barge-in detection (user talking while TTS is playing).

**STT (Speech-to-Text)**
Local and streaming. Should emit partial transcripts so the router can start warming up (e.g., pre-fetching DOM state) before the user finishes speaking.

**Router**
A thin classification step (rule-based + a tiny local model) that decides fast-path vs escalation. This is what actually delivers "fast but good" — most commands (click, scroll, navigate, type) are simple and shouldn't touch an API at all.

**Local Reasoning Model**
A small local LLM operating purely on a pruned DOM/accessibility-tree text representation. Handles deterministic, single-step commands. This is the default path for speed.

**API Reasoning Model**
A larger hosted model, invoked only when: the local model has low confidence, the command is multi-step ("find the cheapest X and add it to cart"), or the command is ambiguous ("click the blue one" with multiple blue elements) and needs deeper context.

**Page Perception Layer**
DOM/accessibility-tree extraction is the only perception path. There is deliberately **no vision fallback** (screenshot + VLM): pages the DOM can't describe, such as canvas apps or purely visual references ("the blue one" with no text to go on), are out of scope. Staying DOM-only keeps the loop fast and cheap, and the router refuses commands it can't ground in the page instead of guessing.

**Action Execution**
The actual browser driver layer — translates a structured action (click selector X, type text into Y, navigate to Z) into real browser events, headed (user-visible).

**Verification**
After each action, a lightweight check that the page state changed as expected (new DOM snapshot diff, URL change, element appeared) — this is what lets the agent self-correct instead of silently failing or plowing ahead on a bad assumption.

**Response Generation + TTS**
Short, natural confirmations/questions, generated from a template or the reasoning model's own output — kept short so TTS latency stays low. TTS must support interruption (barge-in) so the user can talk over it.

### Speed levers (why this shape is fast)
- DOM-only perception avoids screenshot capture and vision inference entirely.
- The router keeps most commands on the local model, reserving the API call for the minority of steps that actually need it.
- Streaming STT + partial transcripts let downstream stages start early instead of waiting for a full utterance.
- Verification is lightweight (diff-based), not another full LLM call, unless the diff itself is ambiguous.

### What "final selection" needs to satisfy, end to end
- Simple single-action commands: under ~3s from end-of-speech to start-of-TTS-response.
- Commands needing the API model step: under ~5s. Commands that fall through to the full browser agent take much longer (minutes on heavy sites in Exp 1), so they get an immediate spoken acknowledgement and spoken progress instead of a latency target.
- No silent failures — every path ends in either a completed action, a clarifying question, or a spoken error.
- Local-only operation should be functional for the common-case commands even if the API is unreachable; the API is a quality upgrade, not a hard dependency.

---

## Part 2: Experimentation Plan

Philosophy: **experiment → evidence → decision → build.** Each experiment below is scoped to 1-3 hours and ends in a filled comparison matrix with a defensible winner — no component gets chosen on vibes.

### Order & dependencies

| Order | Experiment | Depends on | Status |
|---|---|---|---|
| 1 | Browser automation tool | none — foundational, gates everything downstream | **Done** — browser-use ([details](01_Browser%20Automation/README.md)) |
| 2 | Reasoning LLM + command routing | needs Exp 1's DOM/action format | **Done** — rules → DeepInfra Gemma → browser-use agent ([details](02_Reasoning_and_Routing/README.md)) |
| 3 | STT | none (independent of the browser work) | Done |
| 4 | VAD | none (independent of the browser work) | Done |
| 5 | TTS | none (independent of the browser work) | Done |
| 6 | Turn-taking / conversation flow | needs winners from 3-5 | Done |
| 7 | End-to-end latency budget (the first runnable version of the app) | needs winners from all above | In progress |
| 8 | Planning and position hints | needs Exp 2's router and Exp 7's integrated loop | Done |
| 9 | Conversation memory, scratchpad comparison, re-planning (Phase 2) | needs Exp 7's integrated loop and Exp 8's planner | Done |

*Dropped: vision / screenshot understanding. The project has no vision fallback (see "Page Perception Layer" above), so there is no experiment for it.*

Rationale: browser automation was the highest-uncertainty, foundational piece, and the reasoning/routing experiment needed a working DOM/action format to test against, so those two went first and gave a working "agent acting on a real page" checkpoint before touching a microphone. The voice stack (STT/VAD/TTS/turn-taking) is independent of the browser stack. Everything converges in the final integration/latency test.

---

### Exp 1 — Browser automation tool — ✅ Done
**Tested:** browser-use, Stagehand v4, Playwright MCP (Crawl4AI removed: it can't click or type). 4 tasks (login form, e-commerce extraction, YouTube search + open video, GitHub issues), headed, same model for every candidate (Cerebras `gpt-oss-120b`).
**Result:** browser-use 4/4 (2 successes disputed by its own self-check), Playwright MCP 4/4 but slowest and most token-hungry, Stagehand 2/4.
**Decision:** **browser-use** as the browser-control layer; main model **Cerebras `gpt-oss-120b`**; page extraction on **DeepInfra `gemma-4-31B-it-turbo`**.
**Key finding:** a full agent loop costs one model call per step, each carrying a large fixed prompt (~9.4k tokens in default mode), so it can't meet a voice-latency budget for simple commands on any provider. Cerebras hit a per-minute limit after ~4 steps; DeepInfra calls were slow; gpt-oss on DeepInfra also produced invalid browser-use actions. (An earlier version of this line blamed the page content sent each step; measuring showed the page list is small, 156 to 8,096 tokens, so that was corrected.) Full write-up, numbers and caveats: [01_Browser Automation/README.md](01_Browser%20Automation/README.md).

### Exp 2 — Reasoning LLM + command routing — ✅ Done
**Built:** a router with three tiers, no per-site code: (1) generic text-matching rules over browser-use's page reader, no model; (2) when the rules refuse, one short model call that picks the element to click/type into, or refuses; (3) the full browser-use agent on the same open browser. Entry point: `CommandRouter.run_command(text)`.
**Tested:** 18 spoken-style commands on real sites (14 should act, 4 vague ones must be refused) on 8 models, plus the rules on 5 sites and the handoff to the agent.
**Result:** models of about 30B and up got 10-11 of 13 right with 1 wrong click and refused all 4 vague commands. Everything at 8B or below, local or cloud, guessed on vague commands (1 to 4 wrong clicks) and was right 3-9 times of 13, so **no small local model is usable for this step**. Rules alone take ~1.4-2.8s per command with no model; the model step adds 0.4s (Cerebras) to 1.4s (Gemma).
**Decision:** model step = **DeepInfra `gemma-4-31B-it-turbo`** (most accurate, never rate-limited) with a 10s time limit; Cerebras `gpt-oss-120b` is ~3x faster but rate-limited 7 of 17 back-to-back calls, so it is an optional switch, not the default. The agent keeps Cerebras `gpt-oss-120b`. Full write-up, tables and caveats: [02_Reasoning_and_Routing/README.md](02_Reasoning_and_Routing/README.md).

### Exp 3 — STT — ✅ Done
**Tested:** cloud engines only (Groq Whisper, Deepgram, AssemblyAI, ElevenLabs Scribe, Sarvam), on my own 40 recorded commands (plus a silence file and 4 Hinglish lines), batch and streaming, with and without vocabulary hints, including each provider's newer model versions.
**Result:** ElevenLabs `scribe_v2` and AssemblyAI were the most accurate (0.6% WER, 97% of commands understood); Sarvam `saaras:v4` was ~5x faster (143 ms vs 792 ms) at 1.7% WER; Deepgram `nova-3` was 2.3%. Streaming was not more accurate for any engine (Deepgram Flux 5.2%, ElevenLabs Realtime 4.6%, AssemblyAI streaming dropped 6 of 40 clips). Vocabulary hints changed nothing. Whisper `large-v3` invented "Thank you." on silence.
**Decision (revised after Exp 6/7 ran on it live):** **batch transcription of a clip cut by the VAD, Sarvam `saaras:v4` primary** — 5x faster than ElevenLabs (143 ms vs 792 ms) at a still-low 1.7% WER, the app's actual engine since Exp 6, and it doesn't burn ElevenLabs credits on every turn. ElevenLabs `scribe_v2` is the accuracy fallback (0.6% WER) if Sarvam mistranscribes too often in practice; Groq turbo is the free fallback. Streaming is left for Experiment 6 (interruption). Caveats: one speaker, 40 commands; Sarvam streaming untested. Full write-up: [03_Speech_To_Text/README.md](03_Speech_To_Text/README.md).

### Exp 4 — VAD — ✅ Done
**Tested:** Silero VAD, WebRTC VAD (4 aggressiveness levels) and an energy-threshold baseline, each with 0.3 / 0.5 / 0.8 s of silence before "you finished", on my own 40 recorded commands played as a continuous stream, clean and with pink noise (3 levels) and keyboard-like clicks added. Then VAD-cut clips were sent to ElevenLabs, and everything was tried on my live microphone with `live_vad.py`.
**Result:** Silero was the only detector with no false alarms and 39-40 of 40 commands in every condition (about 3% of one CPU core). WebRTC at looser settings fires on room noise and merges commands; its strictest setting loses 10 commands in loud noise and gives 6 false alarms with clicks; the energy baseline drops to 11 of 40 in loud noise. VAD-cut clips transcribe exactly like hand-cut ones (0.6% WER).
**Decision:** **Silero, threshold 0.5, 0.5 s hangover, 0.3 s pre-roll** (the end is declared about 0.6 s after speech stops; tune by feel in Exp 6). Not tested: barge-in (needs Exp 5's speech output). One finding fixed along the way: Exp 3's clip splitter had merged a click into one command. Full write-up: [04_Voice_Activity_Detection/README.md](04_Voice_Activity_Detection/README.md).

### Exp 5 — TTS — ✅ Done
**Tested:** speed, streaming and interruption on 8 assistant-style sentences (6 English, 2 Hinglish) for ElevenLabs (Flash v2.5, Multilingual v2), Sarvam Bulbul v3 (full file and streaming), Deepgram Aura-2 and Deepgram Flux TTS; the 41 English Aura-2 voices were auditioned by ear. Groq Orpheus was not tested (terms not accepted). Google, Azure, OpenAI and local engines were excluded by choice.
**Result:** ElevenLabs Flash (180 ms) and Sarvam streaming (177 ms) start fastest; Aura-2 starts in about 0.4-0.5 s; Flux TTS did not reach its advertised 80 ms from my machine (about 0.5 s) but is the only one that reports how much audio was played when interrupted (about 0.3 s round trip). Deepgram has no Hindi voice.
**Decision:** **Deepgram Aura-2, voice Phoebe** (picked by ear, no scored blind test), streamed raw over HTTP; Sarvam Bulbul v3 as the optional Hinglish voice; Flux TTS is the candidate to revisit for barge-in in Exp 6. Full write-up: [05_Text_To_Speech/README.md](05_Text_To_Speech/README.md).

### Exp 6 — Turn-taking / conversation flow — ✅ Done
**Built:** a bare voice loop with no browser: microphone → Silero → Sarvam STT → canned reply → Deepgram Aura-2 Phoebe, with interruption (barge-in), live hotkeys to change the silence wait and the speech needed to interrupt, and a logged summary per session. Tried live on headphones (3 sessions, 10 spoken replies, 2 interruptions), plus a simulated run on recordings.
**Result:** end of speech to first sound is about **1.0 s** (0.5 s silence wait + 0.15 s transcript + 0.4 s voice; 0.87 s at the 0.3 s wait). Interruption needs 0.25 s of speech and playback is silenced within 3-12 ms in software plus about 100 ms in the sound card (about 0.37 s from the start of speech to silence). Engineering finding: Deepgram drops idle connections after 3-6 s, after interrupted streams and on the first request of a session, each costing about 0.5 s; fixed with a keep-alive ping, a warm-up request and not pinging while a reply is pending.
**Decision:** silence wait 0.5 s default (0.3 s viable), interruption at 0.25 s of speech, tick cue optional and off. Not tested: false interruptions (cough, clicks), speakers/echo, the idle prompt. Full write-up: [06_Turn_Taking/README.md](06_Turn_Taking/README.md).

### Exp 7 — End-to-end latency budget
This is the first runnable version of the app, built as the real skeleton (not a throwaway script) with the stage timings kept in. Wire together the winners from Exp 1-6 (browser tool → reasoning routing → STT → VAD → TTS → turn-taking) into the full loop and instrument every stage (VAD detection → STT → routing → reasoning → perception → action → verification → TTS). Run ~10 full commands (mix of simple and multi-step) and produce a latency waterfall. Identify the bottleneck stage and propose one concrete fix (parallelizing STT with DOM pre-fetch, caching the DOM tree between steps, streaming TTS on partial output, etc.).
**Target:** under 3s end-of-speech → start-of-response for simple commands; under 5s for commands that need the API model step. Commands that fall through to the full browser agent are acknowledged immediately and given spoken progress instead.
**Note from Exp 1 and 2:** the levers are the number of model calls per command and the fixed prompt each carries, not page size. Keep simple commands off the agent loop (the rules and one short model call take 1.4-3s; the agent took minutes on heavy sites in Exp 1), keep `flash_mode` on, and keep page extraction on a separate provider. Also budget for: a page-settle wait of up to 4s on pages that keep changing, the 10s model time limit, and Cerebras per-minute rate limits on back-to-back commands. Speak a short "on it" immediately so the user doesn't sit in silence while any of this runs. The voice loop built in Exp 6 (Sarvam for STT) is the starting point.

**Status (text mode done, live voice pending):** the app skeleton is built ([07_End_To_End_Latency/app.py](07_End_To_End_Latency/app.py)) and 10 commands were timed through the whole router on two practice sites: all 10 correct. Rules-tier commands give the first sound in 0.85 s (scroll/back) to 2.5 s (page loads); the model step 3.6 s; the agent's "On it." came at 1.8-3.9 s and its answer at 3.8-6.9 s (text mode, add about 0.65 s for the silence wait and transcript in voice mode). **Bottleneck:** for questions the fast path spends 1.4-3.5 s (rules refuse, then one model call answers "none") before the agent even starts. **Fixes built and re-measured:** question-like commands go straight to the agent and "On it." is spoken as soon as the rules decline: "On it." now comes at 0.3-0.4 s (was 1.8-3.9 s) and the median answer at 3.9 s (was 4.8 s). Correction: the question-skip pattern had an escaping slip and did not match in that re-run, so the answer gain was noise; it works now (fast path 0 ms, "On it." 0.34 s). The first live voice run found and fixed: filler words ("um") sent simple commands to the agent; a bare verb ("Click.") reached the agent, which clicked around for 70 s; speech during agent work dropped the answer and queued commands. Now: fillers are stripped, a bare verb asks "Click what?", "stop" cancels the agent (0.3 s), "Still working on it." every 15 s. A second live run is needed to confirm by voice. A harder-sites round (14 commands on Amazon India, YouTube, GitHub, Flipkart) passed 10/14 at first; the failures (a channel card picked as a video, a list drawn late, a login popup covering the page) were fixed generically, then 14/14 passed. Not an independent test: the fixes were made on those commands. A fresh set of 15 commands on four unseen sites (Hacker News, BBC, eBay, Stack Overflow) passed 9/15 at first contact (60%); causes: icon links picked as results, a Cloudflare verification page, a suggestion chip picked as a result. After generic fixes (labelled results only, bot-check detection, refuse on dense look-alike pages and let the model step choose) 13/15, the two misses being the bot-check page reported correctly. **Phase 1 (planner + informative replies):** every reply now describes what actually happened ("Clicked travel.", "Opened books.toscrape.com.") instead of "Done."; multi-step requests ("go to Amazon, search for X, tell me the cheapest") are split by Exp 8's planner and run as steps, each with its own spoken reply, a failed step stops the plan and says how far it got, and "stop" cancels a plan in progress, not just one step — tested in text mode (3-step plan, single command correctly skips the planner, a failing plan stops at the right step, cancel-mid-plan stops 1.8 s after "stop"). Live voice confirmation of all of this is still pending. Details: [07_End_To_End_Latency/README.md](07_End_To_End_Latency/README.md).

### Exp 8 — Planning and position hints — ✅ Done
**Built and tested:** (B) a rule-based position resolver ("the second result", "the link at the top left", "the last button") using the on-screen positions the page reader already had, plugged into the router's click rule; (A) a planner prompt that splits a multi-action request into the router's single-action steps, scored for 3 models on 18 requests and run against a real browser for 8 tasks.
**Result:** position hints resolved 19 of 19 targets on 3 real pages (including 4 where refusing was correct) and 4 of 4 real clicks landed; Gemma 31B and `gpt-oss-120b` planned 18/18 exactly (Llama 8B 16/18, it invents steps); every non-question step is runnable by the rules once the planner is asked for web addresses. Planned execution was **not faster** than the agent alone: 6.6 s vs 4.6 s on easy practice sites, 15.8 s vs 17.5 s on Wikipedia, both always correct.
**Decision:** keep position hints; use Gemma as the planner and only for requests with several actions, for its named steps (narration, per-step recovery) and not for speed. Caveats: 3 pages for position hints, expectations written after looking at them, 8 execution tasks, provider stalls of 50 s on either path. Full write-up: [08_Planning_and_Position_Hints/README.md](08_Planning_and_Position_Hints/README.md).

### Exp 9 — Conversation memory, scratchpad comparison, re-planning (Phase 2) — ✅ Done
**Built:** a scratchpad that remembers every plan "ask" step's answer, so a final verdict step ("which is cheaper") can be answered from those facts by a small model call instead of re-browsing a page the agent has left; a short conversation-history context appended to a later command that uses referential words ("the cheaper one", "again", "compare"); one re-plan attempt (never looped) when a plan step fails. A `--no-memory` flag turns all three off for comparison.
**Tested:** 4 scripted conversations through the real app, each run with and without memory (real browser, real model calls), one of them a deliberate control expected to behave identically either way.
**Result (not the clean win expected):** 3 of 4 cases passed identically with memory on and off; the comparison case's stricter check failed with memory on ("The first book is cheaper," correct but didn't name it) and passed without it (the agent's own unprompted answer named both books and both prices). The follow-up case — meant to show memory's value — passed either way, because the browser agent could already recover the fact by browsing on its own within its normal step budget, which is a gap in the test design, not evidence the feature is useless. Re-planning worked exactly as designed (one attempt, no loop) but the retried step's actual content was poor in that one case. One real integration bug found and fixed along the way: planner-emitted "ask ..." steps weren't recognised by the router's own question detector, so they fell through to a model step that guessed a click instead of refusing.
**Decision:** keep all three mechanisms (cheap, never made anything worse here, likely to matter on cases this round didn't stress — 3+ item comparisons, facts that have changed, facts only the user stated). Explicitly not claiming they were proven necessary by this round. A live voice session afterward found and fixed two real bugs (conversation-history context growing unbounded in size across a long session; the waterfall's timing breakdown not accounting for a command queued behind a busy turn) and surfaced a third — a spoken correction like "I said X" was run as a literal new command, not understood as a correction — which was then planned and fixed: a `CORRECTION` regex strips the retry/correction preamble ("no", "wait", "actually", "i said", "i meant") the same way filler words already were, and a correction said while the assistant is busy now cancels the in-flight step instead of only queuing behind it. **Tried live**: the retry, plain-correction, bare-"no" safety, and cancel-mid-task cases all worked; one regression was found and fixed on the spot ("No thanks." broke, now fixed with a safer strip-order); one real gap was confirmed and left open — a correction that replaces only the object, not the verb ("no, the second one"), picks the wrong thing because the verb from the previous command isn't carried over. **A second live session** found a bigger problem: "stop" only matches as the very first word, so "Hold hold hold stop stop stop stop." didn't cancel anything, and the three things said while frustrated all queued and ran one after another — saying more made the wait *longer*. Fixed: a successful cancel now drains the job queue of anything not yet started, and logs what it heard (a successful stop previously left no trace in the log). `CANCEL`'s first-word-only matching was left as is, by the user's own choice. **A third live session** found a bug with nothing to do with any model: after correctly typing a search term, "Search now, like hit enter." was parsed by a plain regex (Experiment 2's `dom_fastpath.parse_command`, `^search(?:\s+for)?\s+(.+)$`) as a brand-new search for the literal text "now, like hit enter," overwriting the correct query and submitting that instead. Fixed with a new `submit` intent that strips a trailing "like hit enter" / leading "now" from a search match and, if nothing real is left, presses Enter without retyping anything — confirmed end to end (typed a query, said the exact failing phrase, the original query was submitted, not overwritten). Also surfaced, not yet fixed: GitHub's sign-up overlay has no close mechanism my popup-dismissal recognises, and a vague non-command ("Saish has 6 H, keep that in mind") still reaches the full agent and can burn its whole step budget on an irrelevant detour. **A fourth live session** found that on a completely fresh browser (no navigation yet), the popup check itself fired a false positive: browser-use's own internal placeholder tab (title "Starting agent...") has a real DOM, and the popup-detection JS found a stray DIV on it and reported a blocking popup that didn't exist, sending a plain "Search for GitHub." to the slow full agent instead of the fast path. Fixed with an `_on_real_page()` guard (checks the URL actually starts with `http`) on both the popup and bot checks — confirmed the false block is gone and real popup detection (Flipkart) still works unchanged. Same session: "Just search for github.com." also took the slow path because "just" wasn't in the filler-word list; added it alongside "so"/"well"/"now". Full write-up: [09_Memory_and_Replanning/README.md](09_Memory_and_Replanning/README.md).

---

## Synthesis — after all experiments
1. Fill in one "final stack" table: Browser tool / STT / VAD / TTS / Local reasoning model / API reasoning model / routing rule / endpointing value. Decided so far: **Browser tool = browser-use** with Cerebras `gpt-oss-120b` for the agent (Exp 1); **routing = rules → DeepInfra `gemma-4-31B-it-turbo` (10s limit) → agent** (Exp 2); **local reasoning model = none** (nothing at 8B or below was safe enough in Exp 2); **STT = batch Sarvam `saaras:v4`** (5x faster than ElevenLabs at 1.7% WER, the app's real engine since Exp 6; ElevenLabs `scribe_v2` is the accuracy fallback) (Exp 3); **VAD = Silero, 0.5 threshold, 0.5 s hangover** (Exp 4); **TTS = Deepgram Aura-2 Phoebe** (Exp 5); **turn-taking = 0.5 s silence wait, 0.25 s of speech to interrupt** (Exp 6).
2. Validate the *combination* in Exp 7, not just each piece in isolation — a component that wins its own experiment but breaks the end-to-end budget should be swapped, not tolerated.
3. Only then move to the integration build.