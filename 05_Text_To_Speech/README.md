# Experiment 5 — Text to speech (TTS)

**Status: complete.** Result: **Deepgram Aura-2, voice Phoebe (`aura-2-phoebe-en`)**, streamed over HTTP as raw 24 kHz audio. Chosen by ear from 41 Aura-2 voices; the speed numbers below are measured on that voice.

| Role | Choice | Why |
|---|---|---|
| **Assistant voice (English)** | **Deepgram `aura-2-phoebe-en`** | Picked by ear. About 0.46 s to first audio, 1.9 s for a 3 s sentence, about $0.03 per 1,000 characters |
| Hinglish replies (optional) | Sarvam Bulbul v3 (`bulbul:v3`, speaker `ritu`) | Deepgram has no Hindi voice. Sarvam streams MP3 and starts in about 0.18 s |
| Worth revisiting for interruption | Deepgram Flux TTS (`flux-haley-en` etc.) | It tells you how much audio was actually played when interrupted (about 0.3 s round trip). It was not faster and costs about 50% more |

---

## 1. What this experiment answers

The assistant's voice mirrors Experiment 3: speech-to-text hears you, text-to-speech answers. The questions:
1. How long until the first sound arrives after the text is ready?
2. Does it **stream**, so speech can start before the whole sentence is generated?
3. How cleanly can it be **stopped** mid-sentence (the base of barge-in)?
4. Which voice do I like to hear all day?
5. Does it cope with **Hinglish**, and what does it cost?

**Scope decisions:** cloud only; only providers I already had keys for (ElevenLabs, Sarvam, Deepgram, Groq). No Google, Azure, OpenAI or local Kokoro/Piper, by choice.

## 2. What was tested

Eight sentences the assistant would really say ([tts_bench.py](tts_bench.py)):
confirmations ("Scrolling down."), a clarification ("I found two sign in buttons. Which one do you want?"), answers with numbers ("…priced at fifty-one pounds seventy-seven."), a search ("Searching for MSI gaming monitors under twenty thousand rupees."), an error, one long answer (8.7 s of speech), and two Hinglish lines.

| Engine | Model | How it is called |
|---|---|---|
| ElevenLabs | Flash v2.5, Multilingual v2 | HTTP stream, raw PCM |
| Sarvam | Bulbul v3 | full WAV file (REST) and streaming MP3 |
| Deepgram | Aura-2 (Thalia, then Phoebe) | HTTP stream, raw PCM |
| Deepgram | Flux TTS (`flux-haley-en`) | WebSocket, kept open, `Speak` / `Flush` / `Interrupt` |
| Groq | Orpheus | **not tested**: the org admin must accept the model's terms in the Groq console first, and I did not pursue it (English only, preview tier) |

One persistent connection per engine, 3 runs per sentence, English sentences scored for speed. "First audio" means the first 0.1 s of sound arrived. All voices are female so the listening comparison was fair.

## 3. Results: speed

Median over the six English sentences (3 runs each). Measured from my machine, so treat as an ordering.

| Engine / model | First audio (median) | Slowest first audio | Whole sentence ready (median) | Real-time factor* |
|---|---|---|---|---|
| ElevenLabs Flash v2.5 | **180 ms** | 277 ms | 338 ms | 0.09 |
| Sarvam Bulbul v3, streaming MP3 | **177 ms** | 190 ms | 772 ms | n/a |
| Deepgram Aura-2 (Thalia) | 397 ms | 1017 ms | 1393 ms | 0.35 |
| **Deepgram Aura-2 (Phoebe), chosen** | **458 ms** | 947 ms | 1869 ms | 0.54 |
| Deepgram Flux TTS (Haley) | 516 ms | 1815 ms | 3825 ms | 0.77 |
| ElevenLabs Multilingual v2 | 749 ms | 1097 ms | 882 ms | 0.22 |
| Sarvam Bulbul v3, full file | 822 ms | 1781 ms | 822 ms | 0.22 |

\*Time to generate divided by the length of the audio. Below 1 means faster than speaking. The slowest numbers are mostly the first request, which pays for opening the connection (about 1 s for Deepgram HTTP, about 1.8 s for Flux).

What this shows:
- **ElevenLabs Flash and Sarvam streaming are the fastest to start** (under 0.2 s). Everything else starts in 0.4 to 0.8 s.
- **Deepgram Aura-2 is in the middle**: about 0.4 to 0.5 s. Phoebe measured slightly slower than Thalia (458 vs 397 ms), probably network variation and not the voice.
- **Flux TTS did not reproduce the "as little as 80 ms" Deepgram advertises** from my machine: 0.4 to 0.7 s per sentence, and it pace-limits audio to about real time, so the whole sentence takes longer.
- **Multilingual v2 and Sarvam's full-file mode** only make sense for pre-made audio, not a live assistant, because the wait equals the whole sentence (Sarvam) or the first audio is slow (Multilingual).

## 4. Results: interruption

How a sentence is stopped mid-way, tested on the longest sentence, stopping after about 0.5 s of audio:

| Engine | What happens | Time |
|---|---|---|
| Aura-2 (HTTP), ElevenLabs, Sarvam | Close the HTTP connection. The next request works at normal speed. | about 0.1 ms to close |
| **Flux TTS** (WebSocket) | Send `Interrupt`; the server replies `SpeechInterrupted` with how many milliseconds of audio were played, so the assistant knows what the user actually heard. The same connection works for the next sentence. | about 300 ms round trip |

Closing the connection is instant, but it only stops *more audio arriving*. Silencing what is already in the player's buffer is up to our playback code, which is Experiment 6's job. This matters because Aura-2 delivers the sentence faster than it plays (a 3 s sentence arrives in about 1.9 s), so seconds of audio can be waiting in the buffer when the user interrupts. Flux limits how far ahead it sends, so there is less to throw away, and it can report what was spoken.

## 5. Results: how it sounds

**No scored blind test was completed.** I built a blind listening script ([listen_test.py](listen_test.py)), but the decision was made by ear, not by scores:

1. ElevenLabs clips were removed from the test when credits became a concern, so the blind comparison shrank to Sarvam against Deepgram.
2. Aura-2 had 41 English voices with different genders, accents and styles, so I generated sentence 5 ("I couldn't find that button…") in all of them ([deepgram_voices.py](deepgram_voices.py) writes `data/voices/index.html` with a play button per voice) and listened non-blind.
3. Phoebe was chosen. Deepgram describes it as *American, feminine, energetic, warm, casual*.

So "Phoebe sounds best" is one listener's preference, with no naturalness scores, and the engine ranking above is on speed and capabilities, not sound quality.

## 6. Hinglish

- **Deepgram (Aura-2 and Flux): no Hindi voice.** English only.
- **ElevenLabs and Sarvam do speak Hindi / Hinglish.** Sarvam is the one kept in the plan, because its streaming mode starts in 0.18 s.
- I generated the two Hinglish lines for ElevenLabs and Sarvam but did not rate them, so I can't say which pronounces better. If the assistant replies in Hinglish, that needs listening to Sarvam's output once before relying on it.

## 7. Decision

**Deepgram Aura-2 Phoebe** for English replies. Reasons: a voice I like, streaming, starts in about 0.45 s, the cheapest of the good options per character, and I already have the key and credits.

**What I gave up:**
- ElevenLabs Flash would start in 0.18 s, about 0.3 s sooner, and probably sounds good. It was dropped because of credit usage, not speed.
- Flux TTS has the better interruption story, but it was slower to start and costs more.

**Rough cost** (list prices from the web search, per 1,000 characters): Aura-2 $0.030, Flux $0.045, ElevenLabs Flash $0.05, Sarvam about ₹3 (about $0.035). A typical reply of 60 characters costs a fraction of a cent on any of them.

## 8. Caveats

- Speed was measured on one machine and network, 6 sentences, 3 runs each. A one-or-two-tenth difference is noise.
- The sound-quality decision is subjective and unscored (section 5).
- Groq Orpheus was not tested (terms not accepted). Deepgram's other Aura (v1) voices were not tested.
- Flux TTS voices were found by guessing names; the account accepted 8 (haley, heather, alexis, nora, hannah, cole, jack, luke) and there may be more. Their gender and accent are not published by the API, so they were not described.
- Model names and prices come from web searches of third-party sites; the model names were confirmed by the APIs accepting them.
- Not tested: the voice reading a long answer end to end, how it handles numbers and URLs outside my 8 sentences, and language switching inside one reply.

## 9. Files

| File | What it does |
|---|---|
| [tts_bench.py](tts_bench.py) | The speed and interruption benchmark, and generates the clips (`--engines`, `--repeats`) |
| [listen_test.py](listen_test.py) | Blind scoring script (built, not used for the final decision) |
| [deepgram_voices.py](deepgram_voices.py) | Makes one sentence in every Deepgram voice, with an HTML page to play them |
| `results/tts_bench.json`, `results/deepgram_tts_models.json` | Timings per request; the list of Deepgram voices |
| `data/` | Generated audio (gitignored) |

```bash
cd 05_Text_To_Speech
python tts_bench.py --engines dg_phoebe,dg_flux,el_flash --repeats 3   # real API calls, a few cents
python deepgram_voices.py                                               # then open data/voices/index.html
python listen_test.py                                                   # blind scoring of the saved clips
```

## 10. What this hands to the next experiments

- **Experiment 6 (turn-taking):** the real barge-in test. Play Phoebe through speakers or headphones, let the VAD from Experiment 4 listen, and measure how fast playback stops when the user speaks. Decide between "close the connection and flush the player" (Aura-2) and Flux's `Interrupt` with spoken-text feedback.
- **Experiment 7 (end-to-end latency):** the voice adds about 0.45 s before the first sound. Start speaking on the first sentence, not the whole reply, to hide the rest.
