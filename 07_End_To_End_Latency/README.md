# Experiment 7 — End-to-end latency (the first runnable version of the app)

**Status: in progress.** The app is built, the 10-command waterfall has been measured in **text mode**, and one live voice run has been done (section 4.2), which exposed several real problems that are now fixed. **Another live run is needed** to confirm the fixes by voice (section 6).

---

## 1. What this is

Experiments 1 to 6 each tested one piece. This one connects all of them into one program, [app.py](app.py), and times every stage of every command:

```
you stop speaking
  -> silence wait (Silero VAD, Exp 4/6)
  -> transcript (Sarvam, Exp 3)
  -> router: rules, then one short model call, then the full browser agent (Exp 2, on browser-use from Exp 1)
  -> spoken reply (Deepgram Aura-2 Phoebe, Exp 5)
```

If the router has to start the slow browser agent, the app speaks **"On it."** so you are not left in silence. Nothing in `app.py` is throwaway: it is the skeleton of the final app, with the stage timings kept in.

Changes made to earlier code to connect it: `CommandRouter` got an optional `on_agent_start` callback (Exp 2), and the voice loop (Exp 6) records when each turn was declared finished and reports the browser step in its per-turn line.

## 2. How it was run

```bash
cd 07_End_To_End_Latency
python app.py --script commands_mixed.txt --headless --no-sound   # what produced the results below
python app.py --output-device 6 --start-url books.toscrape.com    # live voice (headphones)
python app.py --text                                              # type commands
```

Real services: DeepInfra `gemma-4-31B-it-turbo` for the model step (10 s limit), Cerebras `gpt-oss-120b` for the agent (max 8 steps, 120 s), Deepgram for speech (the audio was not played with `--no-sound`, but the requests and their timings are real). The browser was hidden.

The 10 commands ([commands_mixed.txt](commands_mixed.txt)) on two practice sites: 6 simple commands for the rules, 1 that needs the model step, 3 questions that need the agent.

## 3. Results (text mode)

All 10 commands succeeded and were correct (including "Sharp Objects" for "open the first book" on the Mystery page, then "tell me its price" → £47.82).

| # | Tier | Command | Browser step | First sound | Answer starts | Finished* |
|---|---|---|---|---|---|---|
| 1 | rules | go to books.toscrape.com | 2.13 s | 2.49 s | 2.49 s | 3.08 s |
| 2 | rules | click travel | 1.92 s | 2.26 s | 2.26 s | 2.84 s |
| 3 | rules | scroll down | 0.53 s | 0.87 s | 0.87 s | 1.47 s |
| 4 | **agent** | tell me the title of the first book on this page | 6.52 s | 3.90 s ("On it.") | 6.86 s | 10.69 s |
| 5 | rules | go back | 0.51 s | 0.84 s | 0.84 s | 1.44 s |
| 6 | rules | click mystery | 1.83 s | 2.17 s | 2.17 s | 2.72 s |
| 7 | **model** | open the first book | 3.27 s | 3.61 s | 3.61 s | 4.07 s |
| 8 | **agent** | tell me its price | 3.44 s | 1.80 s ("On it.") | 3.78 s | 7.57 s |
| 9 | rules | go to quotes.toscrape.com | 1.25 s | 1.61 s | 1.61 s | 2.20 s |
| 10 | **agent** | find a quote by Albert Einstein and tell me what it says | 4.43 s | 3.28 s ("On it.") | 4.78 s | 12.89 s |

\*"Finished" includes the time the spoken answer takes to read out, so it grows with the length of the reply.

All times are from the moment the command was issued. In voice mode, add the silence wait (about 0.5 s) and the transcript (about 0.15 s): **about 0.65 s**.

| Tier | Commands | Median first sound | In voice mode (estimate, +0.65 s) |
|---|---|---|---|
| rules | 6 | 1.89 s (0.85 s for scroll/back, 1.6 to 2.5 s for anything that loads a page) | about 2.5 s |
| model step | 1 | 3.61 s | about 4.3 s |
| agent: "On it." | 3 | 3.28 s | about 3.9 s |
| agent: the answer | 3 | 4.78 s | about 5.4 s |

### Against the targets set in the plan

| Target | Result |
|---|---|
| Simple commands: under 3 s from end of speech to the start of the reply | Met for scroll and back (about 1.5 s); **borderline for page loads** (about 3.1 s in voice mode) because the page itself takes about 2 s |
| Commands that need the model step: under 5 s | Met (about 4.3 s) |
| Commands that reach the full agent: acknowledged immediately | **Not met**: "On it." came at 1.8 to 3.9 s, not immediately (next section) |

## 4. The bottleneck and what to do about it

For the three agent questions, the router spent **1.4 to 3.5 s in the fast path before giving up**, and only then started the agent, which took 1.5 to 3.0 s:

| Command | Fast path before giving up | Agent run | "On it." |
|---|---|---|---|
| #4 title of the first book | 3.5 s | 3.0 s | 3.9 s |
| #8 its price | 1.4 s | 2.0 s | 1.8 s |
| #10 Einstein quote | 2.9 s | 1.5 s | 3.3 s |

The fast path first tries the rules (instant, they find no match), then makes a model call (Gemma, 1.4 to 3.5 s) that answers "none". That model call is the wasted time, and the "On it." is delayed because it only fires when the agent starts.

**Fix to build next (cheap, no new model):**
1. Treat questions ("tell me", "what", "how many", "find", "which") as agent commands straight away and skip the model step. This saves 1.4 to 3.5 s on every question.
2. Speak "On it." when the rules decline, not when the agent starts, so it comes at about 0.4 s instead of 1.8 to 3.9 s.

Together these make the answer to a question arrive in about 2 to 3 s (agent only) and the acknowledgement in well under a second, in text mode.

Second-order observations:
- **Page loads dominate the simple commands.** Navigating or clicking a link took 1.2 to 2.1 s, against 0.5 s for scroll and back. This is the page's own load and settle wait (up to 4 s allowed), so it cannot be fixed on our side beyond not waiting longer than needed.
- **The reply "Done." says nothing.** "Opened Travel" would be better, and costs nothing. This is for the app phase.

### 4.1 The fixes, and the result (first attempt, partly wrong, see 4.2)

Both fixes were built (in [router.py](../02_Reasoning_and_Routing/router.py)): commands that start with "tell me / what / which / how many / find / read / ..." and that the rules cannot handle go straight to the agent, and the speech layer is told to say "On it." as soon as the rules decline. Re-run on the same sites ([after_fix_commands.txt](after_fix_commands.txt), text mode):

| Agent question | "On it." before | "On it." after | Answer starts before | Answer starts after |
|---|---|---|---|---|
| title of the first book | 3.90 s | **0.41 s** | 6.86 s | 7.11 s* |
| its price | 1.80 s | **0.32 s** | 3.78 s | **3.04 s** |
| Einstein quote | 3.28 s | **0.43 s** | 4.78 s | **3.94 s** |

\*The agent itself took 6.3 s on that run (the same call took 3.0 s in the previous run), so single runs vary by a few seconds. Median answer time moved from 4.8 s to 3.9 s, and the acknowledgement from 3.3 s to 0.4 s. The saving on the answer is smaller than the 1.4 to 3.5 s of wasted model call because the agent's own time varies more than that.

**A bug found along the way:** with the first fix in, one agent command finished but its spoken reply failed with "Server disconnected without sending a response". The cause was in my Experiment 6 keep-alive: I had paused the 2 s pings while a command was being worked on (to avoid a collision with the reply), so a longer agent run outlasted Deepgram's idle limit (about 3 to 6 s) and the reply hit a dead connection. Fixed by pinging during the work as well (the reply waits for a ping already in flight) and by retrying once on a dead connection. A 100 s agent run would have failed every time without this.

### 4.2 What the first live voice run showed, and what was fixed

The user's first live run (7 turns, headphones) was useful mostly for what went wrong:

| What happened | Cause | Fix |
|---|---|---|
| "um Go back." took 6.4 s instead of 0.5 s | the filler word stopped the rules matching, so it went to the agent | spoken filler and politeness ("um", "please", "can you", "okay so") are stripped before parsing |
| A book opened "on its own" and the agent clicked around for about 70 s | the speech was cut at the pause: only "Click." arrived. A bare verb went to the full agent, which guessed (it clicked links, opened a product, went home, extracted 20 titles, wrote a file) | a command that is just a verb is never sent to the agent: the assistant asks "Click what?", and the next words ("mystery") are joined to it |
| No spoken feedback for a long time, and the answer never came | every utterance while the agent worked counted as an interruption, so the answer was dropped while the agent kept running; the next command then queued behind it (12.7 s) | speech only interrupts the assistant's own voice; while the browser works, a new command is queued, "stop / cancel / never mind" stops the agent (tested: it halted 0.3 s after "stop" and no answer was spoken), and "Still working on it." is said every 15 s |
| Saying "cool" gave "On it." (reported after the second live run) | anything the rules did not recognise was treated as a slow command: "On it.", then the model step, then the agent | small talk ("cool", "okay", "hmm", "nice", "yes") is ignored, "thanks" gets "You're welcome.", and a one- or two-word fragment that is no known command gets "Sorry, what should I do?" instead of reaching the agent. Tested: none of these made a model or agent call |
| The log said "7.7 s of the reply had been played" four times | the figure was cumulative for the whole session, and `speaking` stayed true during the agent run so several utterances were reported as interruptions | counted per reply; the flag is reset when a reply ends |

Also found while fixing: the question pattern for "skip the model step for questions" contained a stray backspace character (an escaping slip), so it **never matched** in the earlier re-run. The "answer 4.8 s to 3.9 s" improvement reported in 4.1 was run-to-run noise, not that fix. With the pattern repaired, a question now goes straight to the agent: fast path 0 ms, "On it." at 0.34 s, answer after a 3.2 s agent step (one run).

Voice-mode numbers from the user's live run (silence 0.51 s + transcript 0.12 to 0.15 s included):

| Command | Tier | First sound | Answer |
|---|---|---|---|
| "Click travel." | rules | 2.79 s | 2.79 s |
| "Scroll down." / "Scroll up." | rules | 1.50 s / 1.61 s | same |
| "Tell me the title of the first book of this page." | agent | "On it." 1.01 s | 5.93 s |
| "um Go back." | agent (should have been rules) | "On it." 0.99 s | 7.92 s |
| "Open the first book." | model | 12.66 s (queued behind a runaway agent) | same |
| "Tell me its price." | agent | "On it." 1.02 s | 4.84 s |

So in voice mode: a scroll is about 1.5 s, a page load about 2.8 s, an acknowledgement about 1.0 s, a simple question's answer about 5 s.

## 5. Caveats

- **The agent answered in one step every time.** The practice sites are simple and the questions have the answer on the page. Experiment 1 measured 160 to 250 s for multi-step tasks on heavy sites, which this set does not represent. The agent times here are best cases, and the plan's "On it." plus spoken progress becomes more important with heavier pages.
- **Text mode skips the voice stages.** The voice numbers are estimated by adding the silence wait and transcript from Experiment 6. The live run replaces the estimate.
- **Headless browser, one machine, one run of each command.** Timings vary by a few tenths of a second between runs, especially for page loads and model calls.
- **Cerebras rate limits** were not hit with 3 agent runs a minute apart. Back-to-back agent commands could still hit the per-minute limit from Experiment 1.
- **Two practice sites** (`books.toscrape.com`, `quotes.toscrape.com`). Real sites with logins, pop-ups and heavier pages are not covered.

## 6. To complete: the live voice run

```bash
cd 07_End_To_End_Latency
python app.py --output-device 6 --start-url books.toscrape.com
```

Say, one at a time (wait for each reply): "click travel", "scroll down", "tell me the title of the first book on this page", "go back", "click mystery", "open the first book", "tell me its price". Then press `q`.

When you quit with `q`, the waterfall table is printed and saved to `results/waterfall_<time>_voice.json`. The things to read off it:
- the real silence wait and transcript per command (replaces the +0.65 s estimate);
- whether "On it." sounds natural, and whether the silence before it feels too long on questions;
- whether the spoken answers are comfortable (is the reply too long to listen to?).

Add the live numbers to section 3 as a "voice mode" column.

## 7. Files

| File | What it does |
|---|---|
| [app.py](app.py) | The app: voice or typed commands, router, spoken reply, per-command waterfall |
| [commands_mixed.txt](commands_mixed.txt) | The 10-command test set |
| [smoke_commands.txt](smoke_commands.txt) | Four rules-only commands for a quick check (no model cost) |
| `results/waterfall_*.json` | One file per run: per-command stage timings |

## 8. What this hands on

- **The app phase:** skip the model step for question-like commands, speak "On it." earlier, make replies informative, and add spoken progress for long agent runs.
- **Experiment 8:** planning and position hints. The commands that cost the most here are the ones the rules refuse, so better understanding of what needs the agent (and splitting multi-step requests into fast-path steps) is where the remaining time is.
