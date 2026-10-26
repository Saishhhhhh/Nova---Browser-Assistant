<div align="center">

<h1><b>🤖 Nova</b></h1>
<p><strong>A voice assistant that actually browses the web for you — on your real browser, with your real bookmarks and logins.</strong></p>

[![Python](https://img.shields.io/badge/Python_3.11-3776AB.svg?style=flat&logo=Python&logoColor=white)](https://www.python.org/)
[![browser--use](https://img.shields.io/badge/browser--use-Agent_Framework-10b981.svg?style=flat)](https://github.com/browser-use/browser-use)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Speech_to_Text-8b5cf6.svg?style=flat)](https://elevenlabs.io/)
[![Deepgram](https://img.shields.io/badge/Deepgram-Text_to_Speech-13EF93.svg?style=flat)](https://deepgram.com/)
[![openWakeWord](https://img.shields.io/badge/openWakeWord-Wake_Word_Engine-f59e0b.svg?style=flat)](https://github.com/dscripka/openWakeWord)
[![Brave](https://img.shields.io/badge/Brave-Real_Browser_Profile-FB542B.svg?style=flat&logo=brave&logoColor=white)](https://brave.com/)

</div>

---

## 📋 Table of Contents

- [Description](#-description)
- [Features](#-features)
- [Architecture](#-architecture)
- [Command Lifecycle](#-command-lifecycle)
- [Project Structure](#-project-structure)
- [Built With](#️-built-with)
- [Getting Started](#-getting-started)
- [Documentation](#-documentation)

---

## 📚 Description

**Nova** is a voice-driven assistant that controls a real web browser on your behalf. Say her name,
give her a command, and she listens, understands, and acts — searching, clicking, filling in forms,
reading pages back to you, and answering questions about what's on screen, all through natural spoken
conversation.

Unlike a typical browser-automation script, Nova runs on **your actual Brave browser**, with your real
profile — bookmarks, saved logins, and extensions all present, exactly as if you were sitting at the
keyboard yourself. And unlike a typical voice assistant, she's genuinely fast: most commands are handled
by lightweight rule-based logic in a fraction of a second, with a full reasoning agent kept in reserve for
anything that actually needs it.

---

## ✨ Features

- 🎙️ **Natural Voice Control** — speak naturally; no rigid command syntax required
- 👂 **Real Acoustic Wake Word** — say "Nova" and she reacts off the raw audio instantly, combined with a
  transcript-based check as a second signal for extra reliability
- ⚡ **Three-Tier Command Routing** — instant rule-based actions for common requests, a lightweight model
  for element-picking, and a full autonomous agent for anything genuinely complex — each command takes the
  fastest path that can actually handle it
- 🌐 **Your Real Browser, Not a Sandbox** — runs on your own Brave profile, so logins, bookmarks, and
  extensions are already there
- 🧠 **Conversation Memory** — remembers recent turns and facts within a session, so you can ask follow-up
  questions ("which one is cheaper?") without repeating context
- 🗂️ **Automatic Multi-Step Planning** — a single spoken request like "go to Amazon, search for monitors,
  and tell me the cheapest one" is automatically split into steps and executed in order
- 🔁 **Self-Correcting Plans** — if one step of a plan fails, Nova tries a one-shot replacement for the
  rest of the plan instead of simply giving up
- ⌨️ **Literal Keyboard Shortcuts** — "hit F" or "press M" sends a real keystroke (handy for fullscreen,
  mute, and other site shortcuts), not a guess at what to click
- 🗣️ **Natural, Interruptible Speech** — replies stream back as real speech, and you can talk over her at
  any point to interrupt and redirect
- 🖥️ **Live Status Overlay** — a small floating widget shows whether she's listening, thinking, or
  speaking, with one click to change your microphone or speakers
- 📊 **Measured, Not Guessed** — a built-in benchmark suite runs a real battery of tasks against the agent
  and reports an actual, reproducible success rate

---

## 🏗 Architecture

```mermaid
graph TB
    subgraph "Input"
        MIC["🎙️ Microphone"] --> VAD["Voice Activity Detection<br/>(Silero)"]
        VAD --> STT["Speech-to-Text<br/>(ElevenLabs)"]
    end

    subgraph "Wake-Word Gate"
        STT --> WW1["Acoustic Detector<br/>(openWakeWord)"]
        STT --> WW2["Transcript Check"]
        WW1 --> GATE{"Either signal<br/>fires?"}
        WW2 --> GATE
    end

    GATE -->|addressed| ROUTER["Command Router"]
    GATE -->|not addressed| IGNORE["Ignored"]

    subgraph ROUTER ["⚡ Three-Tier Router"]
        direction TB
        R1["Tier 1: Rules<br/>(regex + DOM matching)"]
        R2["Tier 2: Model-Step<br/>(single LLM call)"]
        R3["Tier 3: Full Agent<br/>(autonomous, multi-step)"]
        R1 -->|can't handle it| R2
        R2 -->|can't handle it| R3
    end

    subgraph "Support Systems"
        MEM["🧠 Conversation Memory<br/>+ Scratchpad"]
        PLAN["🗂️ Planner<br/>(multi-step splitting)"]
    end

    MEM <--> ROUTER
    PLAN <--> ROUTER

    ROUTER --> BROWSER["🌐 Brave Browser<br/>(your real profile)"]
    BROWSER --> ROUTER

    ROUTER --> TTS["Text-to-Speech<br/>(Deepgram)"]
    TTS --> SPEAKER["🔊 Speakers"]

    ROUTER -.-> OVERLAY["🖥️ Status Overlay"]

    style MIC fill:#1a1a2e,color:#e0e0e0,stroke:#8b5cf6
    style VAD fill:#1a1a2e,color:#e0e0e0,stroke:#8b5cf6
    style STT fill:#1a1a2e,color:#e0e0e0,stroke:#8b5cf6
    style WW1 fill:#1a1a2e,color:#e0e0e0,stroke:#f59e0b
    style WW2 fill:#1a1a2e,color:#e0e0e0,stroke:#f59e0b
    style GATE fill:#1a1a2e,color:#e0e0e0,stroke:#f59e0b
    style R1 fill:#1a1a2e,color:#10b981,stroke:#10b981
    style R2 fill:#1a1a2e,color:#f59e0b,stroke:#f59e0b
    style R3 fill:#1a1a2e,color:#ef4444,stroke:#ef4444
    style MEM fill:#1a1a2e,color:#e0e0e0,stroke:#3b82f6
    style PLAN fill:#1a1a2e,color:#e0e0e0,stroke:#3b82f6
    style BROWSER fill:#1a1a2e,color:#e0e0e0,stroke:#FB542B
    style TTS fill:#1a1a2e,color:#e0e0e0,stroke:#13EF93
    style SPEAKER fill:#1a1a2e,color:#e0e0e0,stroke:#13EF93
    style OVERLAY fill:#1a1a2e,color:#e0e0e0,stroke:#ec4899
```

A full breakdown of every component, and the reasoning behind each design choice, lives in
[**ARCHITECTURE.md**](ARCHITECTURE.md).

---

## 🔄 Command Lifecycle

Every spoken command travels through the same pipeline, but the router always takes the **fastest path
that can actually do the job** — most everyday commands never touch a language model at all.

```mermaid
flowchart TD
    START(["🎙️ You speak"]) --> VAD["Silence detected -\nclip captured"]
    VAD --> STT["Transcribed to text"]
    STT --> WAKE{"Addressed to\nNova?"}
    WAKE -->|no| END1(["Ignored"])
    WAKE -->|yes| RULES{"Tier 1: Rules\ncan handle it?"}

    RULES -->|yes, instantly| ACT1["Act on the browser"]
    RULES -->|no| MODEL{"Tier 2: Model-step\ncan pick an element?"}

    MODEL -->|yes| ACT2["Act on the browser"]
    MODEL -->|no| AGENT["Tier 3: Full autonomous agent\nplans and acts over multiple steps"]

    ACT1 --> VERIFY["Verify the real outcome\n(page state / reply), not just 'it ran'"]
    ACT2 --> VERIFY
    AGENT --> VERIFY

    VERIFY --> REPLY["Natural-language reply"]
    REPLY --> TTS["Spoken aloud\n(interruptible)"]
    TTS --> END2(["Ready for the next command"])

    style RULES fill:#1a1a2e,color:#10b981,stroke:#10b981
    style MODEL fill:#1a1a2e,color:#f59e0b,stroke:#f59e0b
    style AGENT fill:#1a1a2e,color:#ef4444,stroke:#ef4444
    style VERIFY fill:#1a1a2e,color:#8b5cf6,stroke:#8b5cf6
```

---

## 📁 Project Structure

```
Nova/
├── 🤖 nova/                      # The application package
│   ├── app.py                     # Main loop: ties voice, router, memory, and the overlay together
│   ├── router.py                  # The three-tier command router
│   ├── dom_fastpath.py            # Tier 1 (rules) + Tier 2 (model-step) logic
│   ├── planner.py                 # Multi-step request splitting and re-planning
│   ├── memory.py                  # Conversation history + scratchpad
│   ├── voice.py                   # Microphone loop, turn-taking, barge-in
│   ├── vad.py                     # Voice activity detection (Silero)
│   ├── wakeword.py                # Text-based wake-word check
│   ├── openwakeword_wake.py       # Acoustic wake-word detector
│   ├── browser.py                 # Launches Brave with your real profile
│   ├── overlay.py                 # Floating status widget
│   ├── benchmark.py               # Measured success-rate evaluation suite
│   └── config.py / identity.py    # Environment config and assistant identity
│
├── 🧪 tests/                       # Regression suite
├── 📊 results/                     # Generated session logs and benchmark reports
├── 📦 experiments/                 # The full research history this was built from
│
├── run_nova.py                   # Entry point — `python run_nova.py`
├── pyproject.toml                  # Package metadata and dependencies
└── .env                            # API keys and configuration (not committed)
```

---

## 🛠️ Built With

### 🎙️ Speech
![ElevenLabs](https://img.shields.io/badge/ElevenLabs-Scribe_v2_STT-8b5cf6.svg?style=flat)
![Deepgram](https://img.shields.io/badge/Deepgram-Aura--2_TTS-13EF93.svg?style=flat)
![Silero](https://img.shields.io/badge/Silero-Voice_Activity_Detection-3b82f6.svg?style=flat)
![openWakeWord](https://img.shields.io/badge/openWakeWord-Wake_Word_Detection-f59e0b.svg?style=flat)

### 🧠 Reasoning & Automation
![browser-use](https://img.shields.io/badge/browser--use-Agent_Framework-10b981.svg?style=flat)
![Cerebras](https://img.shields.io/badge/Cerebras-gpt--oss--120b-ef4444.svg?style=flat)
![DeepInfra](https://img.shields.io/badge/DeepInfra-Gemma-ec4899.svg?style=flat)

### 🖥️ Interface & Runtime
![Python](https://img.shields.io/badge/Python_3.11-3776AB.svg?style=flat&logo=Python&logoColor=white)
![Tkinter](https://img.shields.io/badge/Tkinter-Status_Overlay-3776AB.svg?style=flat)
![Brave](https://img.shields.io/badge/Brave-Real_Browser_Profile-FB542B.svg?style=flat&logo=brave&logoColor=white)

---

## 🚀 Getting Started

```bash
# 1. Clone and install
git clone https://github.com/Saishhhhhh/Nova---Browser-Assistant.git
cd Nova---Browser-Assistant
pip install -r requirements.txt   # or: pip install .

# 2. Configure
cp .env.example .env              # fill in your API keys and your name

# 3. Close Brave (she needs sole use of your profile), then run
python run_nova.py
```

Or just double-click **`Start Nova.bat`**. Say **"Nova"** before any command — for example,
*"Nova, open GitHub,"* or *"Nova, search for lofi music."*

```bash
python run_nova.py --text              # type commands instead of speaking, for quick testing
python run_nova.py --script cmds.txt   # run a list of commands automatically
python -m nova.benchmark                # run the measured success-rate benchmark
```

---

## 📖 Documentation

- [🏗️ **ARCHITECTURE.md**](ARCHITECTURE.md) — a complete, diagram-heavy walkthrough of every system, how
  they fit together, and the reasoning behind each design decision

---

<div align="center">

**Built with ❤️ by [Saish](https://github.com/Saishhhhhh)**

</div>
