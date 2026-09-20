# Contender 01: Raw CDP (Chrome DevTools Protocol)

Direct, low-level asynchronous WebSocket client communicating directly with Chromium's `--remote-debugging-port`.

## Architecture & Mechanics

- **Protocol**: Bidirectional JSON-RPC 2.0 over WebSockets.
- **Dependencies**: `websockets` (no Selenium, no Playwright, no chromedriver binaries).
- **Domains Enabled**: `Page`, `DOM`, `Runtime`, `Input`, `Accessibility`.
- **Action Execution**:
  - Clicks and mouse movements via `Input.dispatchMouseEvent`.
  - Keystrokes via `Input.dispatchKeyEvent`.
  - DOM inspection via `DOM.getBoxModel` and `Runtime.evaluate`.
  - Accessibility tree via `Accessibility.getFullAXTree`.

## Advantages & Trade-Offs

- **Pros**:
  - Lowest possible dispatch latency (<5ms).
  - Zero framework overhead.
  - Full control over low-level CDP events and session management.
- **Cons**:
  - Zero built-in auto-waiting or actionability checks (must implement manually).
  - Chromium-only (does not support Safari/Firefox).
  - Highest lines-of-code (LOC) required to build custom selector and event pipelines.

## How to Run Individually

### 1. Run Local Benchmark (Deterministic Fixtures)
```bash
# Fast smoke test
python contenders/01_raw_cdp/bench_local.py --smoke

# Multi-iteration run (default: 5 iterations)
python contenders/01_raw_cdp/bench_local.py --iterations 5

# Visually watch the browser in headed mode
python contenders/01_raw_cdp/bench_local.py --headed
```

### 2. Run Live Benchmark (Google Search & YouTube)
```bash
# Headless run
python contenders/01_raw_cdp/bench_live.py

# Headed run
python contenders/01_raw_cdp/bench_live.py --headed
```

## Output Artifacts

- Local benchmark metrics: `01_Browser_Automation/results/raw/raw_cdp_local.json`
- Live benchmark metrics: `01_Browser_Automation/results/raw/raw_cdp_live.json`
