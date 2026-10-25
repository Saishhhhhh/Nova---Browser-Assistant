# Jarvis

A voice-driven browser assistant. Say "Jarvis, open GitHub" and she acts on your real Brave browser - your
bookmarks, your logins, your extensions - not a disposable automation instance. Speech is the headline
feature here; browser automation is the hands.

```
python run_jarvis.py
```

Or just double-click **`Start Jarvis.bat`** (works from the desktop too - make a shortcut to it). The
terminal window stays open so you still see the live transcript and waterfall log, same as running it by
hand.

Say "Jarvis" before a command - for example, "Jarvis, search for lofi music." Say "Jarvis, stop" to
cancel anything in progress. A small floating widget shows whether she's listening, thinking, or speaking;
click its gear icon to pick your microphone and speakers.

**Setup:** `pip install -r requirements.txt` (or `pip install .`, using `pyproject.toml`), copy
`.env.example` to `.env` and fill in your API keys (Cerebras, DeepInfra, Deepgram, ElevenLabs), set
`USER_NAME` to your name, and close Brave before starting - Chromium profiles only allow one running
process per profile, so Jarvis needs Brave to herself while she runs.

```
python run_jarvis.py --text              # type commands instead of speaking, for quick testing
python run_jarvis.py --script cmds.txt   # run a list of commands automatically
```

**Real wake-word detection:** the name "Jarvis" was picked deliberately - it matches a pretrained,
ready-to-use model in [openWakeWord](https://github.com/dscripka/openWakeWord), a free, fully local,
no-account wake-word engine. When `openwakeword` is installed, she reacts the instant you say her name, off
the raw audio - not by transcribing the whole sentence first and checking the text for it. Either that
acoustic signal or the text-based check is enough to count as addressed, so a quiet miss on one doesn't
reject the command. Without the package installed, everything still works via the text-based check alone.

**How well does it actually work?** `python -m jarvis.benchmark` runs a fixed set of real tasks against the
router (navigation, search, extraction, refusing ambiguous commands) twice each and reports a measured
success rate - not a vibe, a number, checked against the real page state or reply text. See `WRITEUP.md`
for the latest result and what the failures actually meant.

## How this was built

Jarvis is the finished product of nine rounds of experimentation (speech-to-text, voice activity detection,
text-to-speech, turn-taking, reasoning/routing, planning, memory) and a long cycle of live voice testing
that found and fixed real bugs one at a time - not just a benchmark that happened to work on paper.

**[Read the full write-up (WRITEUP.md)](WRITEUP.md)** for the complete journey: what was tried, what was
measured, what broke in practice, and why each decision was made.

The experimentation history itself lives in **[`experiments/`](experiments/)** - nine numbered folders, each
with its own README documenting that experiment's question, method, and result. Kept in full, not
summarized away, because the dead ends and the measurements are as much the engineering work as the final
answer.

## Project layout

```
jarvis/               the finished app - router, DOM fast-path, memory, planner, voice loop, overlay
tests/                regression suite (pytest-style scripts; see each file's own docstring to run it)
results/              generated session logs, benchmark results, saved turn audio - not code
run_jarvis.py         single entry point
pyproject.toml        makes this an installable package (`pip install .`); requirements.txt also works
experiments/          the full nine-experiment history this was built from
WRITEUP.md            the complete journey, written up
```
