# Voice-Driven Browser Agent — Architecture & Experimentation Plan

## Part 1: Architecture Plan

### Design principle
Every component sits on a **local-first, fast path with an API escalation path**. The system should default to the cheapest/fastest thing that works, and only reach for a heavier model when the fast path signals low confidence or the task genuinely needs deeper reasoning (multi-step planning, ambiguous references, vision).

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
          ├─ DOM/accessibility-tree extraction (default, fast)
          └─ Vision fallback (screenshot + VLM, only when DOM is insufficient)
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
A larger hosted model, invoked only when: the local model has low confidence, the command is multi-step ("find the cheapest X and add it to cart"), or the command is ambiguous ("click the blue one" with multiple blue elements) and needs vision or deeper context.

**Page Perception Layer**
DOM/accessibility-tree extraction is the default and should cover the large majority of actions. Vision (screenshot + VLM) is a fallback only — for canvas apps, custom widgets, or genuinely ambiguous visual references the DOM can't resolve. Keeping vision as the exception, not the default, is what keeps the loop fast and cheap.

**Action Execution**
The actual browser driver layer — translates a structured action (click selector X, type text into Y, navigate to Z) into real browser events, headed (user-visible).

**Verification**
After each action, a lightweight check that the page state changed as expected (new DOM snapshot diff, URL change, element appeared) — this is what lets the agent self-correct instead of silently failing or plowing ahead on a bad assumption.

**Response Generation + TTS**
Short, natural confirmations/questions, generated from a template or the reasoning model's own output — kept short so TTS latency stays low. TTS must support interruption (barge-in) so the user can talk over it.

### Speed levers (why this shape is fast)
- DOM-first perception avoids screenshot capture + vision inference on almost every step.
- The router keeps most commands on the local model, reserving the API call for the minority of steps that actually need it.
- Streaming STT + partial transcripts let downstream stages start early instead of waiting for a full utterance.
- Verification is lightweight (diff-based), not another full LLM call, unless the diff itself is ambiguous.

### What "final selection" needs to satisfy, end to end
- Simple single-action commands: under ~3s from end-of-speech to start-of-TTS-response.
- Commands needing vision or API escalation: under ~5s.
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
| 3 | Vision / screenshot understanding | needs Exp 1's real pages/screenshots | Not started |
| 4 | STT | none (independent, can run in parallel with 1-3) | Not started |
| 5 | VAD | none (independent, can run in parallel with 1-3) | Not started |
| 6 | TTS | none (independent, can run in parallel with 1-3) | Not started |
| 7 | Turn-taking / conversation flow | needs winners from 4-6 | Not started |
| 8 | End-to-end latency budget | needs winners from all above | Not started — scope note added after Exp 1 |

Rationale: browser automation is the highest-uncertainty, foundational piece — the reasoning-LLM experiment needs a working DOM/action format to test against, and vision can't run without real screenshots, so both are hard-blocked on it. The voice stack (STT/VAD/TTS/turn-taking) is independent of the browser stack and can be run in parallel if you want to keep pace, but front-loading the browser chain de-risks the novel/hard part of the project first and gives you a working "agent acting on a real page" checkpoint before touching a microphone. Everything converges in the final integration/latency test.

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

### Exp 3 — Vision / screenshot understanding
**Approaches:** pure DOM (baseline), screenshot+VLM, Set-of-Mark prompting, hybrid DOM+screenshot.
**Models:** Gemini and Claude (via DeepInfra), Qwen3-VL (DeepInfra), Moondream (local). Cerebras has no vision models.
**Test:** 10 real page screenshots (reuse from Exp 1), 5 questions each covering element location, page context, and referential commands ("click the blue one"); score accuracy, latency, cost per call.
**Winner needs:** highest accuracy specifically on cases DOM extraction can't resolve — vision should only be justified where it clearly beats the DOM-only baseline.

### Exp 4 — STT
**Candidates:** Faster-Whisper, whisper.cpp, Distil-Whisper (local); Whisper API, Deepgram, Google STT, AssemblyAI, Azure (cloud).
**Test:** word-error-rate on ~20 short imperative voice commands (include accent variation), latency from end-of-speech to final transcript, streaming/partial-result support, local resource usage.
**Winner needs:** low WER on command-style speech, sub-second latency, streaming support (needed for turn-taking).

### Exp 5 — VAD
**Candidates:** Silero VAD, WebRTC VAD, custom energy/zero-crossing detector, Picovoice Cobra, STT-builtin endpointing.
**Test:** detection latency for speech start/end against manually marked ground truth; false-positive rate under background noise; behavior during barge-in (speaking while TTS plays).
**Winner needs:** detection latency under ~100-150ms, low false positives, reliable barge-in detection.

### Exp 6 — TTS
**Candidates:** Kokoro, Piper (local); edge-tts, ElevenLabs, Google TTS, Azure TTS, OpenAI TTS (cloud).
**Test:** time-to-first-audio, blind naturalness scoring (1-10) on ~10 response sentences, streaming support, cleanness of mid-sentence interruption.
**Winner needs:** time-to-first-audio under ~300-500ms, naturalness ≥7/10, clean interruption for barge-in.

### Exp 7 — Turn-taking & conversation flow
Uses the Exp 4-6 winners in a bare voice loop (no browser). Tune endpointing delay (test ~300/500/800ms) for the best balance of "doesn't cut off" vs "doesn't feel laggy." Test barge-in behavior and decide on feedback cues (listening chime, processing indicator) and idle timeout.
**Winner needs:** an endpointing value with no mid-sentence cutoffs, working barge-in, a conversational feel you're satisfied with.

### Exp 8 — End-to-end latency budget
Wire together the winners from Exp 1-7 (browser tool → reasoning routing → vision fallback → STT → VAD → TTS → turn-taking) into the full loop and instrument every stage (VAD detection → STT → routing → reasoning → perception → action → verification → TTS). Run ~10 full commands (mix of simple and multi-step) and produce a latency waterfall. Identify the bottleneck stage and propose one concrete fix (parallelizing STT with DOM pre-fetch, caching the DOM tree between steps, streaming TTS on partial output, etc.).
**Target:** under 3s end-of-speech → start-of-response for simple commands; under 5s for vision-requiring commands.
**Note from Exp 1 and 2:** the levers are the number of model calls per command and the fixed prompt each carries, not page size. Keep simple commands off the agent loop (the rules and one short model call take 1.4-3s; the agent took minutes on heavy sites in Exp 1), keep `flash_mode` on, and keep page extraction on a separate provider. Also budget for: a page-settle wait of up to 4s on pages that keep changing, the 10s model time limit, and Cerebras per-minute rate limits on back-to-back commands. Speak a short "on it" immediately so the user doesn't sit in silence while any of this runs.

---

## Synthesis — after all experiments
1. Fill in one "final stack" table: Browser tool / STT / VAD / TTS / Local reasoning model / API reasoning model / Vision model / routing rule / endpointing value. Decided so far: **Browser tool = browser-use** with Cerebras `gpt-oss-120b` for the agent (Exp 1); **routing = rules → DeepInfra `gemma-4-31B-it-turbo` (10s limit) → agent** (Exp 2); **local reasoning model = none** (nothing at 8B or below was safe enough in Exp 2).
2. Validate the *combination* in Exp 8, not just each piece in isolation — a component that wins its own experiment but breaks the end-to-end budget should be swapped, not tolerated.
3. Only then move to the integration build.