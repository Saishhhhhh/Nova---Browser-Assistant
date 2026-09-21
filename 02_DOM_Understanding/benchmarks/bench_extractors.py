"""
Benchmark 1: DOM Representation Extractors.
Evaluates extraction latency, token footprint, and information density across test fixtures.
"""

import sys
import os
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List
from playwright.async_api import async_playwright

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from dom_extractors import (
    RawHTMLExtractor,
    AXTreeExtractor,
    CleanedMarkdownExtractor,
    IndexedJSONExtractor
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "dataset" / "fixtures"


async def benchmark_extractors_on_page(page, fixture_name: str, extractors: list) -> List[Dict[str, Any]]:
    fixture_path = FIXTURES_DIR / fixture_name
    await page.goto(f"file://{fixture_path}", wait_until="domcontentloaded")
    await asyncio.sleep(0.1)

    results = []
    for ext in extractors:
        # Run warm-up
        await ext.extract(page)
        
        # Benchmark 3 runs
        times = []
        tokens = 0
        chars = 0
        for _ in range(3):
            t0 = time.perf_counter_ns()
            output_str, meta = await ext.extract(page)
            t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            times.append(t_ms)
            tokens = meta.get("token_estimate", 0)
            chars = meta.get("char_count", 0)

        p50_ms = round(sorted(times)[len(times) // 2], 2)
        results.append({
            "fixture": fixture_name,
            "extractor": ext.name,
            "latency_p50_ms": p50_ms,
            "char_count": chars,
            "token_estimate": tokens
        })
    return results


async def run_extractor_benchmark() -> Dict[str, Any]:
    print("\n" + "="*65)
    print(">> [BENCHMARK 1] DOM Representation Extraction Latency & Tokens")
    print("="*65)

    extractors = [
        RawHTMLExtractor(),
        AXTreeExtractor(),
        CleanedMarkdownExtractor(),
        IndexedJSONExtractor(inject_visual_badges=False)
    ]

    fixtures = [
        "ecommerce_product.html",
        "checkout_form.html",
        "search_results.html",
        "settings_safety.html"
    ]

    all_metrics = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for fix in fixtures:
            print(f"\n[Fixture: {fix}]")
            metrics = await benchmark_extractors_on_page(page, fix, extractors)
            for m in metrics:
                print(f"  • {m['extractor']:<18} | Latency: {m['latency_p50_ms']:>6.2f}ms | Tokens: ~{m['token_estimate']:>5} | Chars: {m['char_count']:>5}")
            all_metrics.extend(metrics)

        await browser.close()

    # Save results
    out_dir = Path(__file__).resolve().parent.parent / "results" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "extractor_benchmark.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2)

    print(f"\n[Saved Extractor Metrics] -> {out_path}")
    return {"metrics": all_metrics}


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_extractor_benchmark())
