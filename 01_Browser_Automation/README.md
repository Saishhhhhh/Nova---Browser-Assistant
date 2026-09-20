# Browser Automation Core Benchmark (Experiment 01)

A pure, rigorous engineering benchmark comparing **Raw CDP**, **`nodriver`**, **Playwright**, and **Puppeteer** on the same Chromium binary across latency, DOM scalability, resource efficiency, edge-case reliability, and developer ergonomics.

---

## Architecture & Directory Layout

```
01_Browser_Automation/
├── README.md                          # Experiment documentation & instructions
├── benchmark_harness/                 # Central benchmark orchestrator and local server
│   ├── server/                        # Zero-dependency local test server (port 8765)
│   │   ├── app.py                     # Python HTTP server
│   │   └── static/
│   │       ├── actions.html           # Micro-actions: click, type, hover, scroll
│   │       ├── dom_heavy.html         # 10,000 DOM nodes for query/snapshot tests
│   │       ├── dynamic_spa.html       # Client-side hydration & product filtering
│   │       └── shadow_frames.html     # Nested iframes and open shadow roots
│   ├── run_all.py                     # Master execution runner
│   └── reporter.py                    # Consolidated Markdown & CSV report generator
├── contenders/                        # Independent, modular contender implementations
│   ├── 01_raw_cdp/
│   │   ├── README.md                  # Raw CDP architecture & standalone run commands
│   │   ├── cdp_client.py              # Lightweight async WebSocket CDP client
│   │   ├── bench_local.py             # Local micro-benchmark suite
│   │   └── bench_live.py              # Live Google & YouTube benchmark
│   ├── 02_nodriver/
│   │   ├── README.md                  # nodriver architecture & standalone run commands
│   │   ├── bench_local.py             # Local micro-benchmark suite
│   │   └── bench_live.py              # Live Google & YouTube benchmark
│   ├── 03_playwright/
│   │   ├── README.md                  # Playwright architecture & standalone run commands
│   │   ├── bench_local.py             # Local micro-benchmark suite
│   │   └── bench_live.py              # Live Google & YouTube benchmark
│   └── 04_puppeteer/
│       ├── README.md                  # Puppeteer architecture & standalone run commands
│       ├── package.json               # Node.js dependencies (puppeteer-core)
│       ├── bench_local.js             # Local micro-benchmark suite
│       └── bench_live.js              # Live Google & YouTube benchmark
└── results/                           # Benchmark outputs
    ├── raw/                           # JSON telemetry metrics per run
    ├── report.md                      # Auto-generated comprehensive Markdown report
    └── summary.csv                    # Consolidated tabular metrics CSV
```

---

## How to Run

### Option 1: Master Orchestrator (Run Everything)
The master orchestrator automatically launches the local test fixture server, executes all contenders, and generates the comparison report:

```bash
# Quick smoke test across all 4 contenders (local fixtures)
python benchmark_harness/run_all.py --smoke

# Multi-iteration local benchmark (e.g. 5 iterations for median/p95)
python benchmark_harness/run_all.py --iterations 5

# Run live production sites (Google Search & YouTube)
python benchmark_harness/run_all.py --suite live

# Run both local and live suites with visible browser windows
python benchmark_harness/run_all.py --suite all --headed
```

---

### Option 2: Run Contenders Individually

Each contender is 100% self-contained and runnable independently:

#### 1. Raw CDP (Python)
```bash
# Local test fixtures
python contenders/01_raw_cdp/bench_local.py --smoke
python contenders/01_raw_cdp/bench_local.py --iterations 5 --headed

# Live sites (Google & YouTube)
python contenders/01_raw_cdp/bench_live.py
```

#### 2. nodriver (Python)
```bash
# Local test fixtures
python contenders/02_nodriver/bench_local.py --smoke
python contenders/02_nodriver/bench_local.py --iterations 5 --headed

# Live sites (Google & YouTube)
python contenders/02_nodriver/bench_live.py
```

#### 3. Playwright (Python)
```bash
# Local test fixtures
python contenders/03_playwright/bench_local.py --smoke
python contenders/03_playwright/bench_local.py --iterations 5 --headed

# Live sites (Google & YouTube)
python contenders/03_playwright/bench_live.py
```

#### 4. Puppeteer (Node.js)
```bash
# Local test fixtures
node contenders/04_puppeteer/bench_local.js --smoke
node contenders/04_puppeteer/bench_local.js --iterations 5 --headed

# Live sites (Google & YouTube)
node contenders/04_puppeteer/bench_live.js
```

---

## Latest Benchmark Results

Generated automatically from [results/report.md](file:///c:/Karm/Test/Browser-Automation-Experimentation/01_Browser_Automation/results/report.md):

### 1. Local Micro-Benchmarks (Zero Network Jitter)
*Measurements in milliseconds (lower is better)*

| Contender | Cold Launch (ms) | Click p50 / p95 (ms) | Type 50 chars p50 (ms) | 10k DOM Query p50 (ms) | AXTree Extraction p50 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Raw CDP** | **686.4** | **15.2 / 15.2** | 158.9 | **0.89** | 1144.2 (30k nodes) |
| **nodriver** | **536.5** | **5.9 / 5.9** | 145.1 | 1018.6 | 2492.7 |
| **Playwright** | 1064.2 | 83.7 / 83.7 | **118.9** | 38.3 | 3324.7 (30k nodes) |
| **Puppeteer** | 603.4 | 100.3 / 100.3 | 168.0 | 13.8 | **956.7 (30k nodes)** |

### 2. Live Production Benchmarks (Google Search & YouTube)
| Contender | Google Search Total (ms) | YouTube Video Trigger (ms) | YouTube Video Title |
| :--- | :--- | :--- | :--- |
| **Raw CDP** | 9339.1 | 5243.5 | 3 AM Coding Session - Lofi Hip Hop Mix |
| **nodriver** | 7197.3 | 13579.9 | N/A (SPA root hydration challenge) |
| **Playwright** | 7782.6 | **4861.8** | 3 AM Coding Session - Lofi Hip Hop Mix |
| **Puppeteer** | 7655.4 | 5741.3 | 3 AM Coding Session - Lofi Hip Hop Mix |

### 3. Code Complexity & Maintenance
| Contender | Runtime | Runner LOC | Helper LOC | Total LOC | Auto-Waiting | Bot Stealth |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Raw CDP** | Python | 312 | 229 | **541** | No (Manual) | Full control |
| **nodriver** | Python | 373 | 0 | **373** | Partial | Native stealth |
| **Playwright** | Python | 287 | 0 | **287** | Yes (Full) | Detectable default |
| **Puppeteer** | Node.js | 310 | 0 | **310** | Moderate | Detectable default |

---

## Key Architectural Conclusions

1. **Primitive Action Dispatch Latency**:
   - `nodriver` and `Raw CDP` achieve the fastest raw click dispatches (sub-25ms) by bypassing high-level actionability heuristics.
   - `Playwright`'s actionability checks add ~60–80ms to clicks, but guarantee element visibility, stability, and event handling without race conditions.
2. **DOM Scalability (10,000 Elements)**:
   - Direct `querySelector` via CDP evaluates in **sub-1ms** in Raw CDP and **~14ms** in Puppeteer.
   - `nodriver` incurred a 1,000ms serialization penalty because its `tab.select()` builds Python object representations for matched nodes.
3. **Accessibility Tree Dumps**:
   - Extracting 30,000+ AXTree nodes is fastest in **Puppeteer (956ms)** due to Node's native V8 JSON stream throughput, compared to **1.1s** in Raw CDP, **2.5s** in `nodriver`, and **3.3s** in Playwright.
4. **Speech-Agent Recommendation**:
   - For an ultra-fast speech agent loop (<500ms), avoid full Accessibility Tree dumps on every turn. Instead, combine **Raw CDP or lightweight Playwright locators** with **injected JS beacons** that stream only visible interactive elements.
