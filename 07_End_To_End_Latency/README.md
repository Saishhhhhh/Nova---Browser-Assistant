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

### 4.3 Harder sites round ([harder_sites.py](harder_sites.py))

14 commands a person would say, on four heavy public sites (Amazon India, YouTube, GitHub, Flipkart), through the real router with a visible browser, no login. Each command has an automatic check (the URL it should end on, or a sane answer). A screenshot is saved on failure.

**First round: 10 of 14 passed.** The four failures had four different causes:

| Site | Command | What happened | Cause | Fix |
|---|---|---|---|---|
| YouTube | "click the first video" | opened a channel page | the first search result is a channel card; "first video" picked the first link | "video / product / post / issue / article" now prefer links whose address looks like that thing (`watch`, `/dp/`, `/p/`, `/issues/`). A general lexicon, not per-site code; ignored if nothing matches |
| GitHub | "click the first issue" | clicked the "Issues" tab again | the issue list is drawn a moment after the page "settles", so it was not there when the page was read | when the page has just changed, re-read it (up to 3 times, 0.8 s apart) until the list stops growing |
| Flipkart | "search for running shoes" | not found; the agent then wandered for 71 s and failed | a login popup covered the page | a popup/modal detector (a large fixed or dialog element): press Escape, then try its "close / skip / no thanks" button |
| Flipkart | "click the second product" | clicked "Terms of Use" | it picked a link inside the same popup | same fix; and if the popup will not close, the router answers "A popup is covering the page and I could not close it" and does **not** send the agent, which would only flail behind it |

Also added: the command "close the popup" (or "dismiss it", "close this").

**After the fixes: 14 of 14 passed** (Amazon 4/4, YouTube 3/3, GitHub 4/4, Flipkart 3/3). Position tests (19/19, 4/4 clicks) and Experiment 2's rule tests (13/13 on a re-run) still pass.

Things to know about this result:
- **It is not an independent test.** The fixes were made after seeing these exact commands fail, so the 14/14 shows the failures are fixed, not that the next site will work. A fresh set of commands is the real check.
- **The price question took 89 s the first time and 7.7 s on the re-run** (the same command, the same agent). The agent has long stalls; a median over many runs would be needed to say more. The rules path never stalled.
- The check for "tell me the title of this issue" only requires a non-empty answer, so it is weak.
- Typical times on these sites: page load 2 to 9 s, search 2 to 4 s, a position click 4 to 6 s.

### 4.4 A fresh set: the honest generalisation number ([harder_sites.py](harder_sites.py) `--fresh`)

15 commands on four sites that had not been used while building the fixes (Hacker News, BBC News, eBay, Stack Overflow). The checks were written before the run and not changed afterwards.

**First contact: 9 of 15 passed (60%).** Compare with 14/14 on the commands the fixes were made for.

| Root cause | Commands it broke | What happened |
|---|---|---|
| Icon links picked as "the first story" (Hacker News upvote arrow, no label) | 3 (the pick, then "go back" to a blank page, then "click new") | position hints must have a visible label |
| A "verify you are human" page (Stack Overflow, Cloudflare) | 2 | the clicks landed on unrelated links |
| A suggestion chip picked as "the third result" (eBay) | 1 | the chip looks like a result |

**Fixes, all generic:**
1. A result must have a visible label (icon-only links are not "the first story").
2. A bot-check detector (titles such as "Just a moment...", "Access denied", "verify you are human"): the router says "This site is asking to verify that I am not a robot, so I cannot continue here" and does not click.
3. On a dense page (15 or more look-alike links) the position resolver **refuses** unless the address pattern identifies the items, and the model step chooses from the labels. Two intermediate attempts, preferring long titles, still picked a domain link ("patkerr.co.uk") and a chip; a confident wrong pick is worse than handing the choice to the model.

**After the fixes:** BBC 3/3 (it had passed), Hacker News 4/4, eBay 4/4 (position clicks now go through the model step: 4.8 s and 10.3 s), Stack Overflow 2/4. The Stack Overflow misses are the bot-check page, which the app now reports instead of clicking; the page cleared a few seconds later and a retry would work, so the check, which wanted a question page, still shows two "fails".

What this does and does not show:
- **The first-contact rate, about 60%, is the number to remember.** Fixing the failures I saw is not the same as being robust. Each new site has been exposing a new problem.
- Position clicks on dense pages are now slower (a model call, 5 to 10 s) but right.
- eBay was unreliable in other ways: "go to ebay.com" once landed on an eBay "Error Page", and the search needed the agent (23 to 26 s) in two of three runs because the rules did not find its search box. Not investigated.
- The agent still stalls unpredictably (a 7 s question took 89 s in one run).

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
