# Experiment 4 — Voice activity detection (VAD)

**Status: complete.** The benchmark is done and the live-microphone tool (`live_vad.py`) was tried on my own voice, which worked well (informal check: no timings were recorded).
Result: **Silero VAD, threshold 0.5, declare the end after about 0.5 s of silence.** It was the only detector that stayed correct in every noise condition, at about 3% of one CPU core.

| | Setting |
|---|---|
| Detector | **Silero VAD** (`silero-vad` 6.2.3), speech probability ≥ **0.5** |
| Start of speech | 100 ms of consecutive speech frames; keep **0.3 s** of audio from before the detected start |
| End of speech | **0.5 s** of silence (try 0.3 to 0.4 s if it feels slow, see section 4) |
| Output | the clip from 0.3 s before the start to the moment the end is declared, which goes to Experiment 3's ElevenLabs `scribe_v2` |

---

## 1. What a VAD does in this project

The microphone is open all the time. The VAD decides **when you started** and **when you finished**, and it is the part that sets how soon a command is sent for transcription:

1. **Start:** begin keeping audio, and never send silence or room noise to the speech-to-text engine (which, for some engines, invents words from silence, Experiment 3).
2. **End:** Experiment 3 chose batch transcription of a finished clip, so the clip can only be sent once the VAD is sure you stopped. The silence it waits for is added to every command's delay, on top of the transcription time (about 0.14 s for Sarvam, 0.8 s for ElevenLabs).

The trade-off is a single number, the **hangover** (how long a silence counts as "finished"): too short and "search for… [thinking pause] LG monitor" is cut in two; too long and the assistant feels slow.

## 2. What was tested

Everything runs on **your own recordings from Experiment 3** (`03_Speech_To_Text/data/wav/V0..V10.wav`, 160 s, 40 commands plus 11 s of silence), played to the detector as one continuous stream, the way a live microphone would be heard. No API calls, except the last check.

| Detector | What it is | Settings tried |
|---|---|---|
| **Silero VAD** | small neural model (32 ms frames) | threshold 0.3 / 0.5 / 0.7 |
| **WebRTC VAD** | rule-based detector from the WebRTC project (20 ms frames) | aggressiveness 0, 1, 2, 3 |
| **Energy** | baseline: how many dB above the quietest recent sound | 9 / 12 / 15 dB |

Each was run with a hangover of **0.3, 0.5 and 0.8 s**, and in five conditions:

| Condition | How it was made |
|---|---|
| clean | your recordings as they are |
| pink20 / pink10 / pink5 | pink (fan-like) noise mixed in 20 / 10 / 5 dB **below** the speech level (pink5 is very loud noise) |
| clicks | keyboard-like bursts, about one every 0.7 s, as loud as the speech |

Noise was added to the recordings afterwards, so it is a controlled stand-in for real noise, not a recording of it.

**How each command was judged** (a "window" is the audio the VAD would send: from 0.3 s before the detected start until the end is declared):

| Result | Meaning |
|---|---|
| ok | exactly one window covers the command, and at least 97% of it |
| split | two windows touch it: the end was declared in the middle of the command |
| merged | one window touches two commands: they would be sent as one |
| clipped | part of the command is outside the window (a late start, or a part left out) |
| missed | no window touches it |
| false alarm | a window where nobody spoke (including the silent recording) |

Also measured: **end wait** (from the real end of speech to the VAD declaring it) and **start lag**, and the CPU cost per frame.

### The labels, and one error found and fixed

The "real" start and end of each command come from Experiment 3's energy-based splitter, so they are not an independent measurement (the Energy detector in particular is scoring against its own cousin). I checked them by plotting three recordings (`check_labels.py`). That found a real error: Experiment 3's splitter picks the *largest* pause setting that finds the right number of commands, which glued a click before V5's third command onto it, so the label started 0.65 s early and **every** detector looked "clipped" on it. The labels now use the *smallest* working pause setting, and the plots match. A second label problem remains and is documented below (V10 command 1).

## 3. Results

Full tables: [results/VAD_SUMMARY.md](results/VAD_SUMMARY.md) (all 30 settings, all conditions). The settings that matter, at a 0.5 s hangover (**ok out of 40 / false alarms**):

| Detector | clean | pink20 | pink10 | pink5 (loud) | clicks | End wait, clean (median / 95th pct) | CPU |
|---|---|---|---|---|---|---|---|
| **Silero 0.5** | 39 / 0 | 39 / 0 | 40 / 0 | 40 / 0 | 39 / 0 | **604 / 724 ms** | 2.9% |
| WebRTC 3 (strictest) | 40 / 0 | 40 / 1 | 39 / 1 | 30 / 0 | 36 / **6** | 580 / 620 ms | ~0% |
| WebRTC 2 | 36 / 3 | 39 / 1 | 39 / 1 | 31 / 0 | 30 / 10 | 660 / 820 ms | ~0% |
| WebRTC 0 and 1 | 32 / 13–14 | 40 / 1–2 | 39 / 3–6 | 35–36 / 1–6 | 21–23 / 19–22 | 700 / 1065 ms | ~0% |
| Energy 12 dB | 40 / 0 | 39 / 0 | 32 / 0 | **11** / 0 | 36 / 0 | 480 / 500 ms | 0.6% |

What this shows:
- **Silero was the only detector with no false alarms and 39–40 of 40 commands in every condition**, including loud noise and keyboard clicks. Threshold 0.3 to 0.7 made almost no difference, so the default 0.5 is fine.
- **WebRTC at aggressiveness 0 to 2 triggers on this room's own background noise**: 24 to 29 false alarms on the clean recordings at a 0.3 s hangover, and at longer hangovers the noise keeps one clip "open" until it merges neighbouring commands (up to 17 of 40 merged). Aggressiveness 3 fixes the clean case (40/40) but falls to 30/40 under loud noise and reports 6 false alarms with clicks.
- **The energy baseline is perfect on clean audio and collapses as soon as the noise gets close to the speech level** (11 of 40 at pink5). It also has no way to tell a click from a word.
- **Cost:** Silero needs about 0.9 ms to process 32 ms of audio (2.9% of one core). The others are negligible. Not a factor.
- **Silero adds about 100 ms to the hangover**: its probability takes about that long to fall after the voice stops (0.5 s hangover → 0.6 s median). Energy and WebRTC 3 have no such lag, which is why their end wait is closer to the hangover, but that is a tiny gain compared with their failures in noise.

### The one command flagged at 0.3 and 0.5 s

Every detector shows 39 of 40 at short hangovers because of **V10 command 1** ("YouTube खोलो"). The label runs 0.6 s past Silero's end of speech, because it includes a faint breathy sound after the last word (around −48 dB, visible with `python check_labels.py V10`). Silero says speech ends at 2.98 s and the label says 3.58 s, so a window that ends 0.3 or 0.5 s after Silero's end falls short of the label's end. It looks like breath, not a word, and nothing is lost in practice: the transcription check below used V1–V9 only, so this exact clip is not covered by it, and I have not listened to that tail to be sure. At 0.8 s the window is long enough to cover it.

### Last check: do VAD-cut clips transcribe as well as hand-cut ones?

The V1–V9 recordings (36 commands) were cut by four settings, each clip sent to ElevenLabs `scribe_v2` and scored as in Experiment 3 ([vad_to_stt.py](vad_to_stt.py)):

| Cut by | WER | Exact | Intent understood | Mean clip length |
|---|---|---|---|---|
| hand-cut (Experiment 3) | 0.6% | 97% | 97% | — |
| Silero 0.5, 0.3 s | 0.6% | 97% | 97% | 2.32 s |
| Silero 0.5, 0.5 s | 0.6% | 97% | 97% | 2.51 s |
| WebRTC 3, 0.5 s | 0.6% | 97% | 97% | 2.44 s |
| Energy 12 dB, 0.5 s | 0.6% | 97% | 97% | 2.36 s |

Cutting by VAD loses nothing: the same single "pull request(s)" line is the only error, in every row. (It is the line every engine got "wrong" in Experiment 3, probably because I said the singular.)

## 4. Decision

**Silero VAD, threshold 0.5, hangover 0.5 s, 0.3 s of pre-roll.** Silero is the only detector that held up under noise and clicks with no false alarms, it costs 3% of a core, and clips it cuts transcribe as accurately as hand-cut ones.

**The hangover is a feel setting, not a measured optimum.** After the live try-out I kept 0.5 s as the default; `--hangover` changes it. In my 40 commands no real command was split even at 0.3 s, and 0.3 s saves about 200 ms per command. But I speak with almost no pauses inside a command, and the recordings have a 1 second gap between commands. Real use ("search for… hmm… LG monitor") will have hesitations, so I would start at 0.5 s and lower it only after trying it live. This is what `--hangover` in the live tool is for.

What this does to the pipeline, using Experiment 3's numbers (rough, not measured end to end):
- end of speech → VAD declares it: **about 0.6 s** (0.5 s hangover + 0.1 s Silero lag)
- → transcription: about **0.14 s** (Sarvam) or **0.8 s** (ElevenLabs)
- so the text appears about **0.75 s (Sarvam) to 1.4 s (ElevenLabs)** after you stop speaking. The hangover is the biggest piece we control, which is why Experiment 6 will tune it (and why Sarvam as the engine may win in Experiment 7).

## 5. Caveats

- One speaker, one USB microphone, one quiet room, 40 commands. Settings that differ by one command (39 vs 40) are not a ranking.
- Noise was **added to** clean recordings, so it misses real-world effects (a microphone's automatic gain, noise that changes over time). Real room noise and a live test are still needed. The live tool exists for that.
- The end of each command is measured against an energy-based label that includes the decaying tail of the last word, so "end wait" is probably a little shorter than it feels. The labels were checked by eye on three of eleven recordings.
- **Not tested: interrupting the assistant while it speaks (barge-in).** It needs the assistant's own voice playing out of the speakers into the microphone, which means Experiment 5 (text to speech) first. It belongs in Experiment 6.
- Picovoice Cobra and the speech engines' built-in end-of-speech detection were not tested (Cobra by choice; the engine-side detection only works with streaming, which Experiment 3 set aside).

## 6. Try it on your own voice

```bash
cd 04_Voice_Activity_Detection
python live_vad.py                                  # Silero, WebRTC and Energy side by side; no API calls
python live_vad.py --transcribe elevenlabs          # also sends each command to ElevenLabs and prints the delay
python live_vad.py --vad silero --hangover 0.3      # a snappier setting
python live_vad.py --transcribe sarvam --hinglish
python live_vad.py --list-devices                   # to pick another microphone with --device
```

Speak a command, then stop. The first detector in `--vad` cuts the clip. Each one prints `START` and `END` lines, and the status line shows what every detector thinks right now. After each command it prints the transcript and *silence wait + transcript time = how long you waited*. Everything you say is saved in `live_out/` (gitignored) so it can be re-scored later.

Things worth trying: a long pause in the middle of a command; a fan or a video playing; typing while you talk; a whispered command; a very fast one; clapping or coughing (it should ignore these).

## 7. Files

| File | What it does |
|---|---|
| [vad_core.py](vad_core.py) | The three detectors and the streaming start/end state machine, shared by everything else |
| [vad_bench.py](vad_bench.py) | The benchmark (about 40 s, offline): `python vad_bench.py` (`--quick` for clean audio only) |
| [check_labels.py](check_labels.py) | Plots a recording with its labels and the VAD's output, to check the labels by eye |
| [vad_to_stt.py](vad_to_stt.py) | The last check: VAD-cut clips through ElevenLabs (real API calls, a few cents) |
| [live_vad.py](live_vad.py) | The live microphone tool |
| `results/` | `vad_bench.json`, `VAD_SUMMARY.md`, `vad_to_stt.json` |

Needs `pip install silero-vad webrtcvad-wheels sounddevice matplotlib` and the Experiment 3 recordings (they are not published, so a reader would use their own).

## 8. Handed to the next experiments

- **Experiment 5 (text to speech):** needed before barge-in can be tested.
- **Experiment 6 (turn-taking):** tune the hangover for feel; test speaking over the assistant (the VAD must hear you through the speakers' echo).
- **Experiment 7 (end-to-end latency):** the 0.6 s silence wait is the biggest single piece that is not an API call; Sarvam vs ElevenLabs is then a question of 0.65 s difference on top of that.
