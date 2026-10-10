# Experiment 6 — Turn-taking and the bare voice loop

**Status: complete (with open items, see section 7).** Built and tried a working voice loop with no browser:
**microphone → Silero VAD → Sarvam speech-to-text → a canned reply → Deepgram Aura-2 Phoebe → headphones**, with interruption (barge-in).

| Setting | Value | Evidence |
|---|---|---|
| Wait for silence before "you finished" | **0.5 s default; 0.3 s worked on my voice** | 0.5 s on 9 turns, 0.3 s on 1 turn, no command cut off; 0.3 s gave 0.87 s to first sound |
| Speech needed to count as an interruption | **0.25 s** | 2 live interruptions, both worked; a 96 ms sound was ignored |
| How fast playback stops once an interruption is confirmed | **3 to 12 ms in software, +~100 ms in the sound card** | measured live on headphones |
| Time from end of speech to the first sound of the reply | **about 1.0 s** (0.87 s at the 0.3 s wait) | 10 live replies, median 1.06 s; 0.33 to 0.43 s of it is the voice starting once connection issues were fixed |
| Feedback cue | optional short tick (`--cue tick`), off by default | tried, no verdict recorded |
| Idle prompt | optional (`--idle N`), off by default | built, not tested live |

---

## 1. What turn-taking is

Turn-taking is the set of rules for who speaks when: when your turn is over, when the assistant's turn starts, what happens when you speak over it, and what it ignores (a cough, a click, a pause in the middle of a sentence). A voice assistant has to be given every one of these rules explicitly; people never think about them.

## 2. Objective

Make the voice loop feel like a conversation and not like a walkie-talkie, using the winners of Experiments 3 to 5: **Silero** (4), **Sarvam** speech-to-text (3), **Deepgram Aura-2 Phoebe** (5). The browser agent is left out on purpose so speech problems can't be confused with browser problems.

The questions:
1. How long should the assistant wait before deciding you finished?
2. How fast can it stop talking when you interrupt, and what should count as an interruption?
3. How long from the end of my speech until I hear the reply?
4. Which cues (tick, spoken filler, idle prompt) help?

## 3. What was built

[voice_loop.py](voice_loop.py), one script (about 400 lines):

| Part | What it does |
|---|---|
| Microphone side | 16 kHz audio in 32 ms frames → Silero (from Experiment 4's `vad_core.py`) → start/end events |
| End of turn | Silence for `hangover` seconds (0.5 s default) after at least 0.25 s of speech. Shorter sounds are logged as "ignored" and never sent |
| Worker | Sarvam `saaras` transcript (`en-IN`, or auto-detect with `--hinglish`) → canned reply → Deepgram streaming speech |
| Replies | A short acknowledgement for commands ("Scrolling down.", "Searching for lofi beats."), "I heard: ..." otherwise, and a long (about 15 s) answer when you say "tell me", "explain" or "details" so there is something to interrupt |
| Playback | 24 kHz audio in 20 ms blocks from a buffer. `stop()` empties the buffer, so sound ends within one block |
| Barge-in | While a reply is being prepared or spoken, if Silero hears at least `min_speech` (0.25 s) of continuous speech, the reply epoch advances, playback stops, the speech stream is dropped, and your new speech becomes the next turn |
| Live keys | `1 2 3` silence wait 0.3 / 0.5 / 0.8 s; `4 5 6` speech needed to interrupt 0.15 / 0.25 / 0.4 s; `q` quit |
| Log | `results/turns_<time>.json`: every turn's timings and every interruption |
| `--simulate` | Replays recordings from Experiment 3 instead of the microphone, with the sound output simulated, to test the logic without a person |

## 4. Results

### 4.1 Latency, end of speech to first sound

Three real sessions on headphones (USB microphone, output through FxSound), 10 turns with a spoken reply:

| Part | Median | Range |
|---|---|---|
| Silence wait (VAD declares the end) | 512 ms | 320 – 512 ms |
| Speech-to-text (Sarvam) | 158 ms | 126 – 245 ms |
| Voice starts (Deepgram, first audio) | 388 ms | 353 – 918 ms |
| **Until the reply started** | **1.06 s** | **0.87 – 1.57 s** |

Three of the 10 replies were slow (0.85 to 0.92 s for the voice, 1.5 s in total). All three were caused by connection handling that was then fixed (section 4.3). After the fixes, the simulated runs give 0.33 to 0.43 s for the voice and 1.0 to 1.1 s in total, and the one live turn after the fixes took 0.87 s (at the 0.3 s wait).

So the budget is about **0.5 s waiting for silence + 0.15 s transcript + 0.4 s voice ≈ 1.0 s**, and about 0.85 s with the 0.3 s wait. The silence wait is the largest piece, and the only large one we can tune.

### 4.2 Interruption

Two live interruptions (both long replies, headphones):

| Reply played before interruption | Speech needed | Playback silenced (software) | Sound card buffer |
|---|---|---|---|
| 5.0 s | 256 ms | 2.6 ms | about 100 ms |
| about 4 s (see note) | 256 ms | 12.4 ms | about 100 ms |

**Correction:** the session log printed "10.7 s" for the second interruption, but that number was the audio played over the whole session, not that reply (the first reply had played 5.0 s and a short reply about 1.5 s before it, which leaves roughly 4 s). The code now counts per reply. The speech needed (256 ms) and the stop time (3 to 12 ms) were measured per event and are not affected.

From the moment you start speaking to the moment the sound actually stops is therefore about **0.25 s (detection) + 0.01 s + 0.1 s = 0.37 s**. The 0.25 s is a setting: 0.15 s is faster but gives cough and click sounds more chances to interrupt; 0.4 s is safer and slower.

Your new speech is picked up as the next turn: both interruptions were followed by a recognised command ("Scroll down.").

### 4.3 Engineering findings (connection handling)

The first live runs had a slow voice start and I traced it to three separate causes. These would affect any assistant built on Deepgram's HTTP speech:

| Finding | Cost | Fix |
|---|---|---|
| Deepgram **closes idle connections after about 3 to 6 s**, so a normal gap between turns means a reconnect on every reply | +0.5 s | one tiny request every 2 s keeps the connection open |
| An **interrupted stream cannot be reused**, so the reply after an interruption reconnects | +0.5 s | start a new connection as soon as speech is detected |
| The **first speech request of a session is slow** (cold start) | +0.5 s on turn 1 | one throwaway 3-character request at start-up |
| A keep-alive ping in flight when the reply is requested made it open a second connection | +0.5 s on about 1 reply in 5 | no pings while a reply is pending, and the reply waits for a ping already in flight |

None of this showed in the Experiment 5 benchmark, because its requests were back to back.

### 4.4 What was ignored

A 96 ms sound was correctly ignored (shorter than 0.25 s of speech). One interruption was followed by "(nothing recognised)"; if that interruption was a cough or other non-word, then Silero counted it as speech for 0.25 s and the assistant stopped talking for no reason. I do not know which it was (section 7).

## 5. Decision

- **Silence wait: 0.5 s as the default, 0.3 s as an option.** At 0.3 s no command of mine was cut off (1 live command, and in Experiment 4's offline test no command in 40 was split at 0.3 s), and it saves about 0.2 s per turn. I still keep 0.5 s as the default because my commands rarely contain a thinking pause, and an assistant that cuts someone off mid-sentence feels much worse than one that is 0.2 s slow. This is a feel setting; Experiment 7 will fix it with the full pipeline.
- **Interruption: 0.25 s of continuous speech**, headphones assumed. Move to 0.4 s if false interruptions turn out to be a problem.
- **Voice:** Deepgram HTTP streaming with the keep-alive handling above. Flux TTS (Experiment 5) remains the alternative if "what was actually spoken" feedback is wanted when the user cuts in.
- **Cue:** keep the tick optional, off by default, until someone dislikes the silence.

## 6. Files

| File | What it does |
|---|---|
| [voice_loop.py](voice_loop.py) | The voice loop, live or `--simulate` |
| `results/turns_*.json` | One per session: per-turn timings and interruptions (`_sim` = simulated) |

```bash
cd 06_Turn_Taking
python voice_loop.py --list-devices            # find the headphones' output number
python voice_loop.py --output-device 8         # real microphone, a few cents of API calls per session
python voice_loop.py --cue tick --hangover 0.3
python voice_loop.py --simulate                # replays Experiment 3 recordings; no microphone or sound
```

Needs `SARVAM_API_KEY` and `DEEPGRAM_API_KEY` in `.env`, and the packages from Experiments 4 and 5.

## 7. Caveats and what was not tested

- **One speaker, one microphone, a handful of turns.** 10 spoken replies and 2 interruptions are enough to show the loop works and what its delays are, not to give robust percentages.
- **False interruptions are not measured.** I did not run a systematic test of coughs, keyboard clicks, "hmm" and background speech while the assistant is talking. Silero counts any sound it believes is speech, and one possible false interruption in the log was never confirmed.
- **Headphones only.** Speakers would make the microphone hear the assistant's own voice and need echo handling; that was not tested. The output used was FxSound (an audio enhancer), which sends sound to whatever device is behind it.
- **Pause inside a command at 0.3 s:** one 2.4 s command was handled as one turn at 0.3 s, but I cannot tell from the log whether it contained a pause. Not a controlled test.
- **Tick cue, idle prompt and spoken filler** have no recorded verdict; the idle prompt was not run live.
- **Replies are canned.** No browser, no model. Real replies will start later (agent time) and will need the "one moment" style of filler, which was not built.
- **Windows only** for the keyboard shortcuts (`msvcrt`).

## 8. What this hands to Experiment 7

The measured pieces of the voice side are now: **silence wait 0.3 – 0.5 s, transcript 0.15 s, voice start 0.4 s**, so about 1.0 s of fixed cost before any browser work starts. Experiment 7 adds the browser agent's time on top, and the questions it should answer are which of these can be hidden (start speaking "On it." while the browser works; speak the first sentence of a long answer immediately) and which of the 0.5 s silence waits can be trimmed.
