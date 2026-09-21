# Experiment 02: DOM Understanding & SLM Grounding Benchmark

This directory contains the complete benchmarking and evaluation suite for **Experiment 02: DOM Understanding & Semantic Grounding**.

Here, we determine:
1. **The Optimal DOM Representation**: Comparing **Raw Pruned HTML**, **Accessibility Tree (AXTree)**, **Cleaned Markdown**, and **Indexed Interactive JSON**.
2. **The Optimal Local Small Language Model (SLM)**: Benchmarking sub-4B models (**Qwen3-1.7B / Qwen2.5-1.5B**, **LFM2.5-1.2B**, **Llama 3.2 1B/3B**, **NuExtract-3**, **Qwen3-0.6B**) running on an **NVIDIA RTX 3050 4GB Laptop GPU** via Ollama.

---

## Architecture & Directory Layout

```
02_DOM_Understanding/
├── README.md                      # Comprehensive guide, architecture, and instructions
├── run_experiment.py              # Master CLI orchestrator (--suite, --models, --pull, --smoke)
├── dom_extractors/                # The 4 DOM Representation Extractors
│   ├── base.py                    # Base extractor interface
│   ├── raw_html.py                # Pruned HTML (scripts, styles, SVGs stripped)
│   ├── axtree.py                  # CDP Accessibility Tree snapshot
│   ├── cleaned_markdown.py        # Flattened Markdown text representation
│   └── indexed_json.py            # Sub-15ms Numbered JSON crawler ([1], [2] handles)
├── dataset/                       # Benchmark Fixtures & Tasks
│   ├── tasks.json                 # 25 standardized voice navigation & action tasks with ground truth
│   └── fixtures/                  # 4 realistic test fixtures
│       ├── ecommerce_product.html # Product details, variants, cart, cookie banner
│       ├── checkout_form.html     # Multi-field shipping address, radio buttons, coupons
│       ├── search_results.html    # Multi-card price & duration constraint comparison
│       └── settings_safety.html   # Danger zone, account deletion, 2FA toggle switches
├── models/                        # LLM Serving & Parsers
│   └── ollama_client.py           # Streaming TTFT client with dual JSON & bracket-notation parsers
├── benchmarks/                    # Execution Suites
│   ├── bench_extractors.py        # Benchmark 1: Extraction latency & token footprint
│   ├── bench_models.py            # Benchmark 2: Model grounding accuracy & TTFT
│   └── reporter.py                # Scorecard and CSV report generator
└── results/
    ├── raw/                       # Raw JSON metrics per run
    ├── report.md                  # Auto-generated comprehensive report
    └── summary.csv                # Tabular scorecard
```

---

## 1. DOM Representation Benchmark Results

We benchmarked all 4 representations across the 4 local test fixtures on Chrome:

| Fixture | Representation | Extraction Latency (p50) | Character Count | Estimated Tokens | Actionable Handles? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ecommerce_product.html` | **indexed_json** | **6.83 ms** | 2,134 | ~533 | **Yes (`[1]`, `[2]`, `[3]`)** |
| `ecommerce_product.html` | raw_html | 5.28 ms | 2,392 | ~598 | No (Raw HTML only) |
| `ecommerce_product.html` | axtree | 14.47 ms | 266 | ~66 | Partial (Roles only, no coords) |
| `ecommerce_product.html` | cleaned_markdown | 4.84 ms | 425 | ~106 | No |
| `checkout_form.html` | **indexed_json** | **8.68 ms** | 2,845 | ~711 | **Yes (Includes placeholders & types)** |
| `checkout_form.html` | raw_html | 4.66 ms | 1,862 | ~465 | No |
| `checkout_form.html` | axtree | 16.50 ms | 366 | ~91 | No |
| `checkout_form.html` | cleaned_markdown | 5.13 ms | 452 | ~113 | No |
| `search_results.html` | **indexed_json** | **7.34 ms** | 3,376 | ~844 | **Yes (Full card text & prices)** |
| `search_results.html` | raw_html | 6.94 ms | 3,315 | ~828 | No |
| `search_results.html` | axtree | 24.65 ms | 381 | ~95 | No |
| `search_results.html` | cleaned_markdown | 4.27 ms | 763 | ~190 | No |
| `settings_safety.html` | **indexed_json** | **4.76 ms** | 418 | ~104 | **Yes (Checkboxes & buttons)** |
| `settings_safety.html` | raw_html | 3.48 ms | 1,516 | ~379 | No |
| `settings_safety.html` | axtree | 10.35 ms | 77 | ~19 | No |
| `settings_safety.html` | cleaned_markdown | 3.63 ms | 502 | ~125 | No |

### Conclusion on Representation
**Indexed JSON (`IndexedJSONExtractor`) is the clear winner for speech browser agents**:
1. **Ultra-Fast**: Injected V8 crawler executes in **4.7ms to 8.6ms** (2x to 3x faster than CDP AXTree).
2. **Compact**: Fits within **100 to 850 tokens**, preserving small model context windows.
3. **100% Deterministic**: Injects `data-agent-index` directly on DOM nodes, eliminating selector guessing.

---

## 2. Standardized Voice Grounding Tasks (25 Scenarios)

The evaluation suite under `dataset/tasks.json` assesses models across 5 difficulty tiers:
1. **Direct Button Grounding** (e.g. *"Accept all cookies"*, *"Add this keyboard to my cart"*)
2. **Synonym & Icon Matching** (e.g. *"Put it in my shopping bag"*, *"Save this to my wishlist"*)
3. **Multi-Field Form Filling** (e.g. *"First name Saish, last name Karm, email saish@example.com"*)
4. **Constraint Reasoning** (e.g. *"Book the cheapest non-stop direct flight"*, *"Book the afternoon flight after 12 PM"*)
5. **Safety Confirmation** (e.g. *"Delete my entire account right now"*, *"Turn off two-factor authentication"*)

---

## 3. How to Run the Benchmarks

### Prerequisites
Make sure Ollama is running on your machine (`http://127.0.0.1:11434`):
```powershell
# Verify Ollama is running
ollama list
```

### 1. Run DOM Representation Benchmark (Zero Dependencies)
```bash
python benchmarks/bench_extractors.py
```

### 2. Run Model Grounding Benchmark on Your RTX 3050

```bash
# Fast 5-task smoke test with auto-pull
python benchmarks/bench_models.py --smoke --pull --models qwen2.5:1.5b

# Full 25-task evaluation on your preferred models
python benchmarks/bench_models.py --pull --models qwen2.5:1.5b llama3.2:1b llama3.2:3b

# Run master orchestrator
python run_experiment.py --suite all --smoke
```

### 3. Generate Scorecard & Summary
```bash
python benchmarks/reporter.py
```
Output reports will be generated under `results/report.md` and `results/summary.csv`.
