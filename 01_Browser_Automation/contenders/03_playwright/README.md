# Contender 03: Playwright

Playwright is Microsoft's browser automation library with built-in auto-waiting, resilient locators, and cross-browser support.

## Architecture & Mechanics

- **Protocol**: Custom Node.js driver communicating with browser processes via patched CDP / protocol streams.
- **Action Execution**:
  - Auto-waits for elements to become visible, enabled, stable, and receive pointer events before clicking.
  - Native input emulation via `locator.press_sequentially()` and `page.mouse.wheel()`.
  - Direct CDP sessions supported via `context.new_cdp_session(page)`.
- **Dependencies**: `playwright` (Python or Node.js).

## Advantages & Trade-Offs

- **Pros**:
  - Industry-leading reliability and developer experience (DX).
  - Built-in auto-waiting prevents flaky tests and race conditions.
  - Multi-tab and multi-context isolation.
- **Cons**:
  - Auto-waiting adds small validation overhead (50–150ms per action).
  - Out-of-the-box automation flags (`navigator.webdriver = true`) can be detected by anti-bot systems unless masked.

## How to Run Individually

### 1. Run Local Benchmark (Deterministic Fixtures)
```bash
# Fast smoke test
python contenders/03_playwright/bench_local.py --smoke

# Multi-iteration run (default: 5 iterations)
python contenders/03_playwright/bench_local.py --iterations 5

# Visually watch the browser in headed mode
python contenders/03_playwright/bench_local.py --headed
```

### 2. Run Live Benchmark (Google Search & YouTube)
```bash
# Headless run
python contenders/03_playwright/bench_live.py

# Headed run
python contenders/03_playwright/bench_live.py --headed
```

### 3. Headed Fast-Track Engine (Voice-Ready Visual Automation)

The `fasttrack/` module provides specialized sub-second skills designed for real-time speech browser agents, featuring visual execution badges and direct DOM/shortcut bypasses:

- **YouTube Skill** (`fasttrack/skills/youtube.py`):
  - Direct search URL formulation (`/results?search_query=...`).
  - Native keyboard shortcut dispatch (`k` to toggle play/pause, `l`/`j` to seek, `m` to mute, `f` for fullscreen) executing in **<35ms**.
  - Direct video element JS state inspection (`paused`, `currentTime`, `duration`, `volume`).
- **Amazon Skill** (`fasttrack/skills/amazon.py`):
  - Parameterized search with instant low-to-high price filter (`s=price-asc-rank`).
  - In-memory batch DOM extraction extracting top products in **<30ms** via single `page.evaluate()`.
- **Google Search Skill** (`fasttrack/skills/google.py`):
  - Direct query URL formulation (`/search?q=...&hl=en`).
  - Organic result title, link, and snippet extraction in **<25ms**.
- **General Interactive Web Snapshot** (`fasttrack/skills/general.py`):
  - In-memory snapshot of all interactive elements (`button`, `a`, `input`, `select`) in **<15ms**.
  - Visual numbered badges (`[1]`, `[2]`, ...) injected directly onto elements with coordinate tracking.
  - Visual glowing bounding boxes (`FastPlaywrightEngine.highlight_element`) with human-friendly action badges.

#### How to Run Fast-Track Demos (Headed)
```bash
# Run all fast-track demos sequentially
python contenders/03_playwright/fasttrack/test_fasttrack.py --skill all

# Run YouTube fast-track (auto-play + instant keyboard shortcuts)
python contenders/03_playwright/fasttrack/test_fasttrack.py --skill youtube --query "lofi coding beats"

# Run Amazon price filter and card extraction
python contenders/03_playwright/fasttrack/test_fasttrack.py --skill amazon --query "mechanical keyboard"

# Run Google Search organic extraction
python contenders/03_playwright/fasttrack/test_fasttrack.py --skill google --query "playwright fast automation"

# Run General web page interactive snapshot and visual numbered badge grounding
python contenders/03_playwright/fasttrack/test_fasttrack.py --skill general
```

## Output Artifacts

- Local benchmark metrics: `01_Browser_Automation/results/raw/playwright_local.json`
- Live benchmark metrics: `01_Browser_Automation/results/raw/playwright_live.json`

