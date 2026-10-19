# Ash

A voice-driven browser assistant. Say "Ash, open GitHub" and she acts on your real Brave browser - your
bookmarks, your logins, your extensions - not a disposable automation instance. Speech is the headline
feature here; browser automation is the hands.

```
python run_ash.py
```

Or just double-click **`Start Ash.bat`** (works from the desktop too - make a shortcut to it). The terminal
window stays open so you still see the live transcript and waterfall log, same as running it by hand.

Say "Ash" before a command - for example, "Ash, search for lofi music." Say "Ash, stop" to cancel anything
in progress. A small floating widget shows whether she's listening, thinking, or speaking; click its gear
icon to pick your microphone and speakers.

**Setup:** copy `.env.example` to `.env` and fill in your API keys (Cerebras, DeepInfra, Deepgram,
ElevenLabs), set `USER_NAME` to your name, and close Brave before starting - Chromium profiles only allow
one running process per profile, so Ash needs Brave to herself while she runs.

```
python run_ash.py --text              # type commands instead of speaking, for quick testing
python run_ash.py --script cmds.txt   # run a list of commands automatically
```

## How this was built

Ash is the finished product of nine rounds of experimentation (speech-to-text, voice activity detection,
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
ash/                 the finished app - router, DOM fast-path, memory, planner, voice loop, overlay
run_ash.py           single entry point
experiments/         the full nine-experiment history this was built from
WRITEUP.md           the complete journey, written up
```
