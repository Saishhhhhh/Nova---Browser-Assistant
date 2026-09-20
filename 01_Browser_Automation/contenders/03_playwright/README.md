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

## Output Artifacts

- Local benchmark metrics: `01_Browser_Automation/results/raw/playwright_local.json`
- Live benchmark metrics: `01_Browser_Automation/results/raw/playwright_live.json`
