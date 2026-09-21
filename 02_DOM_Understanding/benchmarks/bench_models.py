"""
Benchmark 2: SLM Grounding & Accuracy Benchmark across Standardized Voice Tasks.
Evaluates local Ollama models on TTFT, generation speed, JSON syntax validity, and grounding accuracy.
"""

import sys
import os
import time
import json
import asyncio
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from playwright.async_api import async_playwright

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from dom_extractors import IndexedJSONExtractor
from models import OllamaClient

DATASET_PATH = MODULE_ROOT / "dataset" / "tasks.json"
FIXTURES_DIR = MODULE_ROOT / "dataset" / "fixtures"


async def find_element_id_by_selector(page, selector: str) -> Optional[int]:
    """Retrieves the injected data-agent-index for a CSS selector."""
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            val = await el.get_attribute("data-agent-index")
            return int(val) if val else None
    except Exception:
        pass
    return None


async def run_model_task_evaluation(
    client: OllamaClient,
    model_name: str,
    tasks: List[Dict[str, Any]],
    page,
    extractor: IndexedJSONExtractor,
    max_tasks: Optional[int] = None
) -> Dict[str, Any]:
    print(f"\n" + "-"*60)
    print(f">> [EVALUATING MODEL]: {model_name}")
    print("-"*60)

    task_results = []
    correct_count = 0
    valid_json_count = 0
    current_fixture = None
    dom_str = ""

    selected_tasks = tasks[:max_tasks] if max_tasks else tasks

    for task in selected_tasks:
        # Skip multi-field tasks that don't have a single target_selector
        if "target_selector" not in task:
            print(f"  [⏭️] Task #{task['id']:<2} | Skipped (multi-field task, no single target_selector)")
            continue

        fix = task["fixture"]
        # Navigate only when fixture changes
        if fix != current_fixture:
            current_fixture = fix
            fixture_path = FIXTURES_DIR / fix
            await page.goto(f"file://{fixture_path}", wait_until="domcontentloaded")
            await asyncio.sleep(0.08)
            dom_str, _ = await extractor.extract(page)

        # Resolve ground truth target ID on this page
        expected_target_id = await find_element_id_by_selector(page, task["target_selector"])

        # Query model
        cmd = task["voice_command"]
        res = await client.generate_grounding(
            model_name=model_name,
            dom_representation=dom_str,
            voice_command=cmd
        )

        parsed = res["parsed_action"]
        is_valid_json = res["is_valid_json"]
        if is_valid_json:
            valid_json_count += 1

        predicted_target = parsed.get("target")
        is_correct = False

        if task["expected_action"] == "ask_confirmation":
            # For destructive actions, either target matches or action is ask_confirmation
            is_correct = (parsed.get("action") == "ask_confirmation") or (predicted_target == expected_target_id)
        else:
            is_correct = (predicted_target == expected_target_id)

        if is_correct:
            correct_count += 1

        status_mark = "✅" if is_correct else "❌"
        print(f"  [{status_mark}] Task #{task['id']:<2} | TTFT: {res['ttft_ms']:>5.1f}ms | Total: {res['total_ms']:>5.1f}ms | Expected: {expected_target_id} -> Pred: {predicted_target} | Cmd: \"{cmd[:35]}...\"")

        task_results.append({
            "task_id": task["id"],
            "category": task["category"],
            "difficulty": task["difficulty"],
            "command": cmd,
            "expected_target": expected_target_id,
            "predicted_target": predicted_target,
            "is_correct": is_correct,
            "is_valid_json": is_valid_json,
            "ttft_ms": res["ttft_ms"],
            "total_ms": res["total_ms"],
            "tokens_generated": res["tokens_generated"],
            "tokens_per_sec": res["tokens_per_sec"],
            "raw_output": res["raw_output"]
        })

    total = len(selected_tasks)
    acc = round((correct_count / total) * 100.0, 1) if total > 0 else 0.0
    json_rate = round((valid_json_count / total) * 100.0, 1) if total > 0 else 0.0

    avg_ttft = round(sum(r["ttft_ms"] for r in task_results) / total, 1) if total > 0 else 0.0
    avg_total = round(sum(r["total_ms"] for r in task_results) / total, 1) if total > 0 else 0.0
    avg_tok_s = round(sum(r["tokens_per_sec"] for r in task_results) / total, 1) if total > 0 else 0.0

    print(f"\n>> [{model_name} SUMMARY]")
    print(f"   Accuracy: {acc}% ({correct_count}/{total})")
    print(f"   Valid JSON Rate: {json_rate}%")
    print(f"   Avg TTFT: {avg_ttft}ms | Avg Total Latency: {avg_total}ms | Speed: {avg_tok_s} tok/s")

    return {
        "model": model_name,
        "total_tasks": total,
        "accuracy_pct": acc,
        "json_valid_pct": json_rate,
        "avg_ttft_ms": avg_ttft,
        "avg_total_ms": avg_total,
        "avg_tokens_per_sec": avg_tok_s,
        "task_results": task_results
    }


async def run_models_benchmark(
    model_names: List[str],
    pull_if_missing: bool = False,
    max_tasks: Optional[int] = None
) -> Dict[str, Any]:
    print("\n" + "="*65)
    print(">> [BENCHMARK 2] SLM Grounding & Accuracy Evaluation")
    print("="*65)

    client = OllamaClient()
    if not client.is_server_running():
        print("\n[ERROR] Ollama server is not running on http://127.0.0.1:11434!")
        print("Please start Ollama (e.g., launch Ollama from Start Menu or run 'ollama serve').")
        return {"error": "Ollama not running"}

    local_models = client.list_local_models()
    print(f"[Ollama] Detected local models: {local_models}")

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        tasks = json.load(f)["tasks"]

    extractor = IndexedJSONExtractor(inject_visual_badges=False)
    benchmark_reports = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for m in model_names:
            # Check if model exists or pull
            matches = [lm for lm in local_models if m in lm]
            if not matches:
                if pull_if_missing:
                    pulled = await client.pull_model(m)
                    if not pulled:
                        print(f"Skipping model '{m}' (pull failed)")
                        continue
                else:
                    print(f"Model '{m}' not found in local models. Run with --pull to download automatically.")
                    continue

            resolved_name = matches[0] if matches else m

            # Warmup: force Ollama to load model into VRAM before timing
            await client.warmup_model(resolved_name)

            report = await run_model_task_evaluation(
                client=client,
                model_name=resolved_name,
                tasks=tasks,
                page=page,
                extractor=extractor,
                max_tasks=max_tasks
            )
            benchmark_reports.append(report)

        await browser.close()

    # Save metrics
    out_dir = MODULE_ROOT / "results" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "models_benchmark.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_reports, f, indent=2)

    print(f"\n[Saved Model Benchmark Metrics] -> {out_path}")
    return {"reports": benchmark_reports}


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="SLM Grounding Benchmark")
    parser.add_argument("--models", nargs="+", default=["qwen2.5:1.5b", "llama3.2:1b"], help="Model names to test")
    parser.add_argument("--pull", action="store_true", help="Auto-pull models if missing")
    parser.add_argument("--smoke", action="store_true", help="Quick smoke test on first 5 tasks")

    args = parser.parse_args()
    limit = 5 if args.smoke else None
    asyncio.run(run_models_benchmark(model_names=args.models, pull_if_missing=args.pull, max_tasks=limit))
