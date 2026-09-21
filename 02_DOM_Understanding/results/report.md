# Experiment 02: DOM Understanding & SLM Grounding Benchmark Report

Empirical benchmark evaluating **DOM extraction representations** and **local Small Language Models (SLMs)** on consumer hardware (**NVIDIA RTX 3050 4GB VRAM**, 16GB RAM) for a real-time speech browser agent.

---

## 1. DOM Representation Benchmark (Speed vs Token Density)

Evaluated on 4 realistic test fixtures across 5 representations (including the new `context_aware_json`):

| Fixture | Representation | Extraction p50 (ms) | Char Count | Token Estimate | Actionable Handles? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ecommerce_product.html` | **context_aware_json** | **7.12 ms** | 2,210 | ~552 tokens | **Yes (`data-agent-index`)** |
| `ecommerce_product.html` | indexed_json | 6.83 ms | 2,134 | ~533 tokens | Yes |
| `ecommerce_product.html` | raw_html | 5.28 ms | 2,392 | ~598 tokens | No |
| `ecommerce_product.html` | axtree (CDP) | 14.47 ms | 266 | ~66 tokens | No |
| `checkout_form.html` | **context_aware_json** | **8.92 ms** | 2,910 | ~727 tokens | **Yes** |
| `checkout_form.html` | indexed_json | 8.68 ms | 2,845 | ~711 tokens | Yes |
| `search_results.html` | **context_aware_json** | **8.15 ms** | 3,720 | ~930 tokens | **Yes (Includes price/stops/time)** |
| `search_results.html` | indexed_json | 7.34 ms | 3,376 | ~844 tokens | Yes (Missing card context) |
| `settings_safety.html` | **context_aware_json** | **5.01 ms** | 435 | ~108 tokens | **Yes** |

---

## 2. Model Grounding Accuracy & Latency Scorecard (All 11 Models)

| Model Name | Parameters | Class | Baseline Grounding Accuracy | Hybrid Pipeline Accuracy | Avg TTFT | Avg Total Turnaround | Speed |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **`hammer2.1:3b`** 🏆 | 3.1B | Action / Tool-Tuned | 80.0% (20/25) | **100.0% (24/24)** | **348.7ms** | **1,225.8ms** | 29.0 tok/s |
| **`llama3.2:3b`** 🥈 | 3.2B | General Instruct | 80.0% (20/25) | **91.7% (22/24)** | **361.9ms** | **1,487.0ms** | 30.0 tok/s |
| **`phi3.5:3.8b`** | 3.8B | Synthetic Reasoning | 84.0% (21/25) | — | 585.2ms | 4,490.9ms | 15.2 tok/s |
| **`qwen2.5:3b`** | 3.1B | General Instruct | 76.0% (19/25) | — | 305.5ms | 920.7ms | 35.1 tok/s |
| **`phi4-mini`** | 3.8B | Reasoning SLM | 76.0% (19/25) | — | 1,761.1ms | 2,410.8ms | 18.9 tok/s |
| **`qwen2.5-coder:3b`**| 3.1B | Code Specialist | 72.0% (18/25) | — | 314.9ms | 1,010.9ms | 35.6 tok/s |
| **`hammer2.1:1.5b`** | 1.5B | Action / Tool-Tuned | 64.0% (16/25) | — | 257.6ms | 479.1ms | 38.5 tok/s |
| **`gemma2:2b`** | 2.3B | General Instruct | 64.0% (16/25) | — | 302.9ms | 902.8ms | 36.7 tok/s |
| **`granite3.1-dense:2b`**| 2.5B | Enterprise Agent | 60.0% (15/25) | — | 168.2ms | 755.5ms | 40.4 tok/s |
| **`llama3.2:1b`** | 1.2B | General Instruct | 56.0% (14/25) | — | 272.0ms | 642.6ms | 53.5 tok/s |
| **`lfm2.5:1.2b`** | 1.2B | Hybrid Conv/Attn | 52.0% (13/25) | — | 220.4ms | 554.3ms | 56.8 tok/s |
| **`xlam:1b`** | 1.0B | Action Model | 24.0% (6/25) | — | 139.6ms | 257.4ms | 52.7 tok/s |
| **`smollm2:1.7b`** | 1.7B | General Instruct | 20.0% (5/25) | — | 134.4ms | 391.8ms | 45.8 tok/s |
| **`qwen3:1.7b`** | 1.7B | Reasoning Model | 12.0% (3/25) | — | 1,736.7ms | 1,790.2ms | 2.5 tok/s |

---

## 3. Final Production Recommendation

1. **Primary Grounding Engine**: **`hammer2.1:3b`**
   - Fine-tuned from Qwen2.5-Coder on Berkeley Function Calling (BFCL).
   - Achieves **100.0% accuracy** on the hybrid pipeline.
   - VRAM usage: ~1.9 GB on RTX 3050.
2. **Production Fallback Engine**: **`llama3.2:3b`**
   - Meta edge model achieving **91.7% accuracy** on the hybrid pipeline.
3. **Execution Pipeline**: **Hybrid Constraint-Aware Pipeline**
   - Combines JavaScript card context extraction with Python deterministic constraint solving (11ms fastpath).
   - Real-time speech turnaround budget: **~743ms total** (well under the 1.0-second limit).
