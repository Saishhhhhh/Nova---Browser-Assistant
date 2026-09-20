# Contender 04: Puppeteer (Node.js)

Puppeteer is the official Chrome DevTools team browser automation library for Node.js.

## Architecture & Mechanics

- **Protocol**: Direct WebSocket JSON-RPC communication to Chromium via internal CDP client wrappers.
- **Action Execution**:
  - `page.click()` dispatches synthetic or CDP mouse events with center coordinate calculation.
  - `page.type()` sends key events to focused inputs.
  - Full CDP session access via `page.target().createCDPSession()`.
- **Dependencies**: `puppeteer-core` (uses system Google Chrome or Microsoft Edge directly).

## Advantages & Trade-Offs

- **Pros**:
  - Developed and maintained directly by the Google Chrome DevTools team.
  - Extremely fast V8 JSON parsing and WebSocket message handling for massive payloads (e.g. AXTree dumps).
  - High performance event loop in Node.js.
- **Cons**:
  - Node.js runtime required (not pure Python like `nodriver`).
  - Sets `navigator.webdriver = true` by default (requires stealth plugins for strict anti-bot targets).

## How to Run Individually

### 1. Run Local Benchmark (Deterministic Fixtures)
```bash
# Fast smoke test
node contenders/04_puppeteer/bench_local.js --smoke

# Multi-iteration run (default: 5 iterations)
node contenders/04_puppeteer/bench_local.js --iterations 5

# Visually watch the browser in headed mode
node contenders/04_puppeteer/bench_local.js --headed
```

### 2. Run Live Benchmark (Google Search & YouTube)
```bash
# Headless run
node contenders/04_puppeteer/bench_live.js

# Headed run
node contenders/04_puppeteer/bench_live.js --headed
```

## Output Artifacts

- Local benchmark metrics: `01_Browser_Automation/results/raw/puppeteer_local.json`
- Live benchmark metrics: `01_Browser_Automation/results/raw/puppeteer_live.json`
