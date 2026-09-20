# Contender 02: nodriver

`nodriver` is an async Python browser automation library built by the author of `undetected-chromedriver`. It talks directly to Chromium's DevTools Protocol without using Selenium, chromedriver binaries, or standard WebDriver automation flags.

## Architecture & Mechanics

- **Protocol**: Direct async WebSockets to CDP with an idiomatic Python API (`await tab.select()`, `await element.click()`).
- **Detection Evasion**: Built-in stealth patches to prevent bot detection (does not set `navigator.webdriver = true`).
- **Dependencies**: `nodriver` (`websockets`, `mss`, `deprecated`).

## Advantages & Trade-Offs

- **Pros**:
  - High stealth resistance out of the box (bypasses Cloudflare / Google bot checks easily).
  - Modern `asyncio` Python syntax with clean element chaining.
  - No separate binary driver downloads required.
- **Cons**:
  - `tab.select()` builds Python wrappers around matching nodes, adding serialization overhead on large DOM trees (e.g. 10k nodes).
  - Ecosystem is newer than Playwright / Puppeteer; smaller community and fewer docs.

## How to Run Individually

### 1. Run Local Benchmark (Deterministic Fixtures)
```bash
# Fast smoke test
python contenders/02_nodriver/bench_local.py --smoke

# Multi-iteration run (default: 5 iterations)
python contenders/02_nodriver/bench_local.py --iterations 5

# Visually watch the browser in headed mode
python contenders/02_nodriver/bench_local.py --headed
```

### 2. Run Live Benchmark (Google Search & YouTube)
```bash
# Headless run
python contenders/02_nodriver/bench_live.py

# Headed run
python contenders/02_nodriver/bench_live.py --headed
```

## Output Artifacts

- Local benchmark metrics: `01_Browser_Automation/results/raw/nodriver_local.json`
- Live benchmark metrics: `01_Browser_Automation/results/raw/nodriver_live.json`
