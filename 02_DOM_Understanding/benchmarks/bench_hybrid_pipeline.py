"""
Benchmark Suite for Hybrid Constraint-Aware Grounding Pipeline.
Evaluates end-to-end performance of Context-Aware Extraction + Deterministic Filtering + SLM Fallback
across all 25 benchmark tasks.
"""

import sys
import time
import json
import asyncio
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from playwright.async_api import async_playwright
from models.ollama_client import OllamaClient
from pipeline.hybrid_pipeline import HybridGroundingPipeline

FIXTURES_DIR = MODULE_ROOT / "dataset" / "fixtures"
TASKS_FILE = MODULE_ROOT / "dataset" / "tasks.json"


async def find_element_id_by_selector(page, selector: str) -> Optional[int]:
    """Retrieves the injected data-agent-index for a CSS/Playwright selector."""
    try:
        el = page.locator(selector).first
        if await el.count() > 0:
            val = await el.get_attribute("data-agent-index")
            return int(val) if val else None
    except Exception:
        pass
    return None


async def run_hybrid_benchmark_on_model(
    pipeline: HybridGroundingPipeline,
    model_name: str,
    tasks: List[Dict[str, Any]],
    page,
    max_tasks: int = None
) -> Dict[str, Any]:
    print(f"\n------------------------------------------------------------")
    print(f">> [HYBRID PIPELINE EVALUATION]: {model_name}")
    print(f"------------------------------------------------------------")

    task_results = []
    correct_count = 0
    valid_json_count = 0
    fastpath_count = 0
    current_fixture = None

    selected_tasks = tasks[:max_tasks] if max_tasks else tasks

    for task in selected_tasks:
        if "target_selector" not in task:
            continue

        fix = task["fixture"]
        if fix != current_fixture:
            current_fixture = fix
            fixture_path = FIXTURES_DIR / fix
            await page.goto(f"file:///{fixture_path.as_posix()}", wait_until="domcontentloaded")
            await asyncio.sleep(0.08)

        cmd = task["voice_command"]

        # Run hybrid grounding
        res = await pipeline.execute_grounding(
            page=page,
            voice_command=cmd,
            model_name=model_name
        )

        expected_target_id = await find_element_id_by_selector(page, task["target_selector"])

        predicted_target = res.get("target")
        is_valid_json = res.get("is_valid_json", False)
        if is_valid_json:
            valid_json_count += 1

        is_fastpath = res.get("is_constraint_fastpath", False)
        if is_fastpath:
            fastpath_count += 1

        is_correct = False
        if task["expected_action"] == "ask_confirmation":
            is_correct = (res.get("action") == "ask_confirmation") or (predicted_target == expected_target_id)
        else:
            is_correct = (predicted_target == expected_target_id)

        if is_correct:
            correct_count += 1

        status_mark = "✅" if is_correct else "❌"
        path_tag = "⚡ [FastPath]" if is_fastpath else "🤖 [SLM-Full]"
        print(f"  [{status_mark}] Task #{task['id']:<2} | {path_tag} | TTFT: {res['ttft_ms']:>5.1f}ms | Total: {res['total_ms']:>5.1f}ms | Expected: {expected_target_id} -> Pred: {predicted_target} | Cmd: \"{cmd[:32]}...\"", flush=True)

        task_results.append({
            "task_id": task["id"],
            "category": task["category"],
            "difficulty": task["difficulty"],
            "command": cmd,
            "expected_target": expected_target_id,
            "predicted_target": predicted_target,
            "is_correct": is_correct,
            "is_valid_json": is_valid_json,
            "is_fastpath": is_fastpath,
            "ttft_ms": res["ttft_ms"],
            "total_ms": res["total_ms"],
            "raw_output": res.get("raw_output", "")
        })

    total = len(task_results)
    acc = round((correct_count / total) * 100.0, 1) if total > 0 else 0.0
    json_rate = round((valid_json_count / total) * 100.0, 1) if total > 0 else 0.0
    avg_ttft = round(sum(r["ttft_ms"] for r in task_results) / total, 1) if total > 0 else 0.0
    avg_total = round(sum(r["total_ms"] for r in task_results) / total, 1) if total > 0 else 0.0

    print(f"\n>> [{model_name} HYBRID PIPELINE SUMMARY]")
    print(f"   Accuracy: {acc}% ({correct_count}/{total})")
    print(f"   Constraint FastPath Triggers: {fastpath_count}/{total}")
    print(f"   Avg TTFT: {avg_ttft}ms | Avg Total Turnaround: {avg_total}ms")

    return {
        "model": model_name,
        "total_tasks": total,
        "accuracy_pct": acc,
        "json_valid_pct": json_rate,
        "fastpath_triggers": fastpath_count,
        "avg_ttft_ms": avg_ttft,
        "avg_total_ms": avg_total,
        "task_results": task_results
    }


async def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Hybrid Grounding Pipeline Benchmark")
    parser.add_argument("--models", nargs="+", default=["hammer2.1:3b", "llama3.2:3b"], help="Models to benchmark")
    parser.add_argument("--smoke", action="store_true", help="Quick smoke test on first 5 tasks")

    args = parser.parse_args()
    limit = 5 if args.smoke else None

    client = OllamaClient()
    pipeline = HybridGroundingPipeline(ollama_client=client)

    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)["tasks"]

    benchmark_reports = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for m in args.models:
            await client.warmup_model(m)
            report = await run_hybrid_benchmark_on_model(
                pipeline=pipeline,
                model_name=m,
                tasks=tasks,
                page=page,
                max_tasks=limit
            )
            benchmark_reports.append(report)

        await browser.close()

    out_dir = MODULE_ROOT / "results" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hybrid_benchmark.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_reports, f, indent=2)

    print(f"\n[Saved Hybrid Benchmark Metrics] -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
