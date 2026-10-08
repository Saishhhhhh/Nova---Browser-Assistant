# Experiment 3 — Speech-to-text (STT)

**Status: complete.** Result: **batch transcription of a finished clip, with ElevenLabs Scribe v2 as the primary engine and Sarvam Saaras V4 as the fast / Hinglish alternative.** Streaming transcription was tested and was not worth its complexity for short voice commands.

| Role | Engine and model | Why |
|---|---|---|
| **Primary** | **ElevenLabs `scribe_v2`**, batch | Most accurate (0.6% WER, 97% of commands understood), no errors, no invented words on silence, ~0.8 s per clip |
| **Fast / Hinglish** | **Sarvam `saaras:v4`** (the API default), batch | Fastest by far (~0.14 s per clip), 1.7% WER, got all four Hinglish commands right (ElevenLabs misheard one) |
| **Live captions only, if wanted** | Deepgram `nova-3`, streaming | The only streaming engine that was both reliable and reasonably accurate (2.3% WER) |
| **Free emergency fallback** | Groq `whisper-large-v3-turbo` | 1.2% WER at ~0.18 s, but 20 requests/minute on the free tier |

Not chosen: AssemblyAI (accurate but batch takes ~2.5 s, and its streaming dropped sessions), Deepgram Flux, ElevenLabs Scribe v2 Realtime.

The speech layer is expected to cut a clip out of the microphone stream with a voice-activity detector (Experiment 4) and send the finished clip to the engine. The output feeds Experiment 2's `CommandRouter.run_command(text)`.

---

## 1. What this experiment answers

1. Which cloud speech-to-text engine understands **short browser commands in my voice** best?
2. How long does each take to return text?
3. Does a **vocabulary hint** (a list of names such as "GitHub", "UltraGear") help?
4. Does any engine **invent words from silence**?
5. Is **streaming** (text arrives while speaking) better than **batch** (send the finished clip) for commands this short?
6. Do the engines cope with **Hinglish** (Hindi and English mixed)?

Scope decisions made before starting:
- **Cloud only.** No local Whisper. The laptop has a 4 GB GPU, and the project is built on hosted APIs.
- **Own recordings only.** No public dataset, because what matters is my voice, my microphone and my kind of commands.
- Engines tested: Groq (hosted Whisper), Deepgram, AssemblyAI, ElevenLabs, Sarvam.

---

## 2. The test set

I recorded the lines in [recording_script.md](recording_script.md) as 11 files:

| File | Content |
|---|---|
| V0 | About 10 seconds of silence. Checks that no engine makes up words. |
| V1 | Basics: scroll down / up, go back, open GitHub |
| V2 | Searches, including "LG UltraGear", "MSI gaming monitor under twenty thousand rupees" |
| V3 | Clicking and moving around a page ("pull requests", "page history") |
| V4 | Website names (Flipkart, Gmail, Reddit, Hacker News) |
| V5 | Numbers and positions |
| V6 | Longer commands |
| V7 | Corrections and stopping |
| V8 | Hard words and names, URLs |
| V9 | The same style of command spoken faster |
| V10 | Hinglish: "YouTube खोलो", "नीचे scroll करो", and so on |

V1 – V8 have 4 commands each, V9 has 4, V10 has 4: **40 commands, 114 seconds of audio** including padding, plus the silence file.

[prepare_dataset.py](prepare_dataset.py) (offline, no API calls) converts each recording to 16 kHz mono WAV with ffmpeg, **cuts it into single commands on the pauses**, and pairs each command with its line from the script. For every file it tries pause lengths from 0.9 s down to 0.5 s (then 1.4 s) until the number of commands found equals the number in the script, so a recording that does not split correctly is reported instead of silently mis-aligned. All 11 files split correctly into 40 commands. Each clip keeps ~0.3 s of silence before and ~1.0 s after the speech, and the manifest records exactly where speech starts and ends, which is what the streaming latency is measured against.

The recordings and the cut clips are personal audio and are **gitignored** (`recordings/`, `data/`). The scripts, the results and this write-up are committed.

---

## 3. How the engines were scored

[stt_bench.py](stt_bench.py) runs every clip through an engine and compares the text to the script line.

| Metric | Meaning |
|---|---|
| **WER** (word error rate) | Wrong, missing or extra words, divided by the number of words I actually said. Micro-averaged over all clips (not an average of per-clip percentages). 0.6% is about 1 wrong word in 160. |
| **Exact** | Share of clips whose normalised text equals the script exactly. |
| **Intent** | Share of clips where Experiment 2's own command parser reads the transcript as the same command as the script. This is the metric that matters for a browser agent: a missing full stop or "ultra gear" vs "UltraGear" does not change what the agent does. |
| **Key terms** | Share of the hard names (GitHub, UltraGear, Kubernetes, toscrape …) that came out right. |
| **Batch latency** | Time to upload one clip and get the text back (only the successful attempt). |
| **Stream latency** | Time from the **end of my speech** to the **final** transcript, with the audio sent at **real-time speed** (100 ms chunks), plus 2 s of silence so the engine can decide I have finished. |
| **Silence words** | Words returned for the silent file (should be zero). |

Both texts are normalised first (lower case, punctuation removed, numbers spelled out, "₹20,000" / "20,000 Rs." = "twenty thousand rupees", "lo-fi" = "lofi", "books.toscrape.com" = "books dot toscrape dot com"). Two scoring bugs were found and fixed during the run (rupee formats, and unknown commands being compared too leniently); the `rescore` command re-scores saved results without calling any API again.

**V10 (Hinglish) is left out of every WER number** because the reference spelling is ambiguous (Devanagari or Roman). It is reported separately in section 5.

---

## 4. Results

### 4.1 Batch (send a finished clip)

All 40 clips, V10 excluded from the score. Sorted by WER.

| Engine and model | WER | Exact | Intent | Key terms | Median latency | Slowest | Silence words |
|---|---|---|---|---|---|---|---|
| **ElevenLabs `scribe_v2`** | **0.6%** | 97% | 97% | 100% | 792 ms | 1222 ms | 0 |
| AssemblyAI (account default = Universal-3.5 Pro) | 0.6% | 97% | 97% | 100% | 2651 ms | 4099 ms | 0 |
| Groq `whisper-large-v3-turbo` | 1.2% | 94% | 94% | 95% | 183 ms | 218 ms | 0 |
| Groq `whisper-large-v3` | 1.7% | 94% | 94% | 100% | 208 ms | 256 ms | **1 ("Thank you.")** |
| **Sarvam (API default = `saaras:v4`)** | 1.7% | 94% | 94% | 100% | **143 ms** | 264 ms | 0 |
| Deepgram `nova-3` | 2.3% | 92% | 92% | 100% | 598 ms | 2179 ms | 0 |

Every engine got the same line wrong: *"Take me to the pull request**s**"* came back as *"pull request"*. It is very likely that I said the singular, so about one word of every engine's error is the reference rather than the engine. Past that line the errors were: Sarvam "books.to scrape.com"; Deepgram "Show me the **registry**" for "page history"; Groq turbo "UltraGare".

### 4.2 Newer and older model versions

Because the first run left AssemblyAI and Sarvam on their default models, I looked up each provider's current model list (third-party pricing pages, October 2026) and tested the named versions on the same 40 clips.

| Engine and model | WER | Intent | Silence words | Median |
|---|---|---|---|---|
| AssemblyAI `universal-3-5-pro` | 0.6% | 97% | 0 | 2175 ms |
| AssemblyAI `universal-2` | 2.9% | 92% | 0 | 1563 ms |
| Sarvam `saaras:v4` | 1.7% | 94% | 0 | 137 ms |
| Sarvam `saaras:v3` | 4.0% | 89% | **1 ("Okay, so")** | 126 ms |
| Sarvam `saarika:v2.5` | 4.0% | 89% | **1 ("Okay, so")** | 135 ms |

**The defaults used in the first run were already the newest models** (they scored identically to `universal-3-5-pro` and `saaras:v4`), so section 4.1 stands. AssemblyAI's API now rejects the old `speech_model` field and wants a `speech_models` list; the adapter was updated. Deepgram's newer **Flux** model only works on the streaming endpoint, so it appears in 4.4.

### 4.3 Vocabulary hints do not help

Each engine's hint feature (Deepgram `keyterm`, AssemblyAI `keyterms_prompt`, ElevenLabs `keyterms`) was run with the list of hard names.

| Engine | WER without | WER with hint |
|---|---|---|
| Deepgram | 2.3% | 2.3% |
| AssemblyAI | 0.6% | 0.6% |
| ElevenLabs | 0.6% | 0.6% |

No change in accuracy, and the hint costs extra on ElevenLabs (+$0.05 per hour). Not used. (Deepgram's median batch time fell from 598 to 374 ms with the hint; I read that as network variation, not an effect of the hint.)

### 4.4 Streaming (text arrives while speaking)

Audio was played in real time, so each engine needed the full ~6 s per clip.

| Engine | WER | Intent | Final text after I stop, median (slowest) | First partial text | Failed clips |
|---|---|---|---|---|---|
| Deepgram `nova-3` | 2.3% | 92% | 743 ms (3475 ms) | 903 ms | 0 |
| AssemblyAI (default streaming model `universal-3-6-pro`) | 9.5% | 94% | 650 ms (1745 ms) | 656 ms | 6 of 40 |
| ElevenLabs `scribe_v2_realtime` (VAD commit after 0.5 s) | 4.6% | 86% | 999 ms (1287 ms) | 2107 ms | 4 of 40 |
| Deepgram `flux-general-en` | 5.2% | 83% | 1229 ms (1455 ms) | 674 ms | 0 |

Observations:
- **Streaming did not beat batch on accuracy for any engine.** Deepgram `nova-3` was identical in both modes (2.3%); the others were worse.
- **Flux, designed for voice agents, was less accurate than `nova-3` on my voice** ("LG" came out as "l g", "So it's for…" was added at the start of one clip) and finished ~500 ms later.
- **ElevenLabs Realtime** added a stray word to a clip ("Sir, it's for MSI gaming monitor…"). Four clips failed with `invalid_request` and I did not find the cause.
- **AssemblyAI streaming** returned an English command in Devanagari script ("सर्च फॉर एलजी…"). The first run lost 15 clips to `1008 policy violation` disconnects; after adding one retry, 6 still failed. The cause is unknown (it could be a connection limit on the account).
- WER is only computed on clips that returned text, so the engines with failed clips look slightly better than they would on a complete run.
- The three new streaming runs executed at the same time to save time. They use different providers, so they should not interfere, but the failures above were not investigated further.

**Not tested: Sarvam streaming.** Sarvam offers streaming at the same price. I skipped it because I had not written an adapter for its protocol, and the decision to use batch made it low value. It remains a possible later check.

### 4.5 Silence

Only two configurations produced words from the 10-second silent file: Groq `whisper-large-v3` ("Thank you.") and the older Sarvam models ("Okay, so"). This is the classic Whisper-family hallucination and is a real risk when a microphone is open but nobody is speaking. The recommended engines, ElevenLabs `scribe_v2` and Sarvam `saaras:v4`, returned nothing. The streaming engines were not scored on silence.

---

## 5. Hinglish (indicative only)

V10 is four commands, so this is a sanity check, not a measurement. The script lines are "YouTube खोलो", "Lo-fi music search करो", "नीचे scroll करो", "पीछे जाओ".

| Engine | Output |
|---|---|
| **Sarvam `saaras:v4`** | यूट्यूब खोलो। / Lo-Fi music search. / नीचे स्क्रॉल करो। / पीछे जाओ। |
| Deepgram `nova-3` (multi) | YouTube खोलो. / Lo fi music search करो. / नीचे scroll करो. / **B2B.** |
| ElevenLabs `scribe_v2` | YouTube खोलो। / लोफाई म्युझिक सर्च करा / नीचे scroll करो। / **पीठे जाओ** |
| AssemblyAI `universal-3-5-pro` | YouTube खोलो / लोफाई म्यूजिक सर्च करो / नीचे स्क्रोल करो / पीछे जाओ। |
| Groq Whisper turbo | YouTube Kholo / लोफाइ म्यूजिक सर्च करो / … / **B. Tizzo.** |

**Sarvam and AssemblyAI** got the meaning of all four right (Sarvam dropped "करो" from the second line). Deepgram, Groq and ElevenLabs each misheard "पीछे जाओ" ("go back"). AssemblyAI was as good as Sarvam here but takes ~2.2 s in batch. Engines also differ in script: some write Devanagari, some Roman. If Hinglish matters, the router needs to handle both spellings (Experiment 2's rules only know English words today).

---

## 6. Decision

**Batch, not streaming.** My commands are 1 to 3 seconds long, and streaming only saves time on long speech, where text can be produced while you are still talking. Here:
- Streaming's "final text after I stop" was 650 to 1230 ms. With batch, the clip is sent once the voice-activity detector sees a short pause, and the answer comes back in ~140 ms (Sarvam) or ~800 ms (ElevenLabs). The totals are in the same range, with better accuracy and far fewer failure modes (no websockets, no dropped sessions).
- Streaming is worth revisiting for interrupting the agent while it is speaking and for live captions. That belongs in Experiment 6 (turn-taking), not here.

**Engine choice:**
1. **ElevenLabs `scribe_v2` (primary).** Best accuracy, no errors, no phantom words.
2. **Sarvam `saaras:v4` (fast / Hinglish).** Roughly 5x faster than ElevenLabs. If the latency budget in Experiment 7 needs it, it may become the primary, at the cost of ~1 percentage point of WER (3 more commands out of 100 misread).
3. **Groq turbo** as a free emergency option.

Credits on hand (dev use is a few cents): ElevenLabs 10,000, Sarvam 1,000, Deepgram $200, AssemblyAI $50. Quoted prices from the web search are per audio hour: ElevenLabs batch $0.22 (Realtime $0.39), Sarvam about $0.30, Deepgram Nova-3 about $0.29 to $0.46 depending on a promotion, AssemblyAI $0.15 to $0.45, Groq turbo $0.04. All trivial at this scale.

---

## 7. Caveats

- **One speaker, one microphone, one room, 40 commands.** Differences of a point or two (Sarvam 1.7% vs Deepgram 2.3%) are within what a different day or microphone could change. Large gaps (ElevenLabs 0.6% vs streaming Flux 5.2%, silence hallucinations) are more trustworthy.
- **The reference is the script, not what I actually said.** At least one error shared by every engine is probably me, not them.
- **Batch latency includes my network and the provider's queue at that moment.** Treat the medians as ordering, not as guarantees. AssemblyAI's number includes its job-polling loop (0.25 s steps).
- **The voice-activity wait is not included in batch latency.** Experiment 4 measures how long it takes to decide I have finished speaking; that time is added to every batch number above.
- Streaming failures on AssemblyAI and ElevenLabs were not root-caused, so their streaming numbers are less certain than the others.
- Model names and prices in 4.2 and section 6 come from third-party sites; the model names were confirmed by the APIs accepting or rejecting them, the prices were not checked against the providers' own pages.
- This experiment used each provider's **short-clip HTTP endpoint**. Long recordings or other audio formats were not tested.

---

## 8. Files

| File | What it does |
|---|---|
| [recording_script.md](recording_script.md) | What to read aloud (V0 to V10) |
| [prepare_dataset.py](prepare_dataset.py) | Offline: converts and splits the recordings into `data/segments/*.wav` and `data/manifest.json` |
| [stt_bench.py](stt_bench.py) | Runs the engines, scores them, writes `results/` |
| `results/stt_<mode>_<engine>.json` | One file per run: summary plus the text returned for every clip |
| `results/SUMMARY.md` | All runs in one table (generated) |
| `recordings/`, `data/` | My audio (gitignored) |

API keys go in `.env` (see [.env.example](../.env.example)), never in the repository.

### Reproduce

```bash
cd 03_Speech_To_Text
python prepare_dataset.py                                   # needs my recordings in recordings/ and ffmpeg
python stt_bench.py batch                                   # the default engine list
python stt_bench.py batch --engines elevenlabs,sarvam:saaras:v4,assemblyai:universal-3-5-pro --boost
python stt_bench.py stream --engines deepgram,deepgram_flux,elevenlabs_rt,assemblyai   # ~4 min per engine
python stt_bench.py rescore                                 # re-score saved results, no API calls
python stt_bench.py report                                  # writes results/SUMMARY.md
```

Use `--only V1,V2` or `--limit N` for a quick smoke test. Anyone reproducing this needs their own recordings, because mine are not published.

---

## 9. What this hands to the next experiments

- **Experiment 4 (VAD):** needs to decide when a clip ends. Its pause length is added to the batch latency here; it should also reject non-speech so the engines are never asked to transcribe silence.
- **Experiment 6 (turn-taking):** decides whether streaming is worth bringing back for barge-in.
- **Experiment 7 (end-to-end latency):** can choose between ElevenLabs and Sarvam with the full pipeline timing in hand.
- **Router (Experiment 2):** should tolerate small spelling differences ("pull request" vs "pull requests", "ultra gear") and Hinglish words.
