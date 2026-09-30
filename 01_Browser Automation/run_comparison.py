"""Master benchmark execution and comparison script for Browser Automation Experiment 1.

Usage examples:
  # 1. Run browser-use with OpenRouter Gemini 2.5 Flash on E-Commerce task
  python run_comparison.py --framework browser-use --provider openrouter --task ecommerce_filter_extract

  # 2. Run browser-use with local Ollama SLM (Qwen 2.5 3B)
  python run_comparison.py --framework browser-use --provider ollama --model qwen2.5:3b --task ecommerce_filter_extract

  # 3. Run Playwright MCP with OpenRouter
  python run_comparison.py --framework playwright-mcp --provider openrouter --task form_auth_and_state

  # 4. Run all tasks across all candidates
  python run_comparison.py --framework all --provider openrouter --task all
"""
import os
import sys
import argparse
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OLLAMA_MODEL, OLLAMA_BASE_URL
from common.tasks import BENCHMARK_TASKS
from common.telemetry import TelemetryLogger


def print_banner():
    print("=" * 70)
    print("      VOICE-DRIVEN BROWSER AGENT — EXPERIMENT 1 BENCHMARK HARNESS    ")
    print("=" * 70)
    print(f"[*] OpenRouter Model : {OPENROUTER_MODEL}")
    print(f"[*] Ollama Model     : {OLLAMA_MODEL} ({OLLAMA_BASE_URL})")
    print(f"[*] Registered Tasks : {', '.join(BENCHMARK_TASKS.keys())}")
    print("=" * 70 + "\n")


def run():
    parser = argparse.ArgumentParser(description="Experiment 1 Master Benchmark Runner")
    parser.add_argument(
        "--framework",
        choices=["browser-use", "playwright-mcp", "all"],
        default="browser-use",
        help="Framework candidate to benchmark",
    )
    parser.add_argument(
        "--provider",
        choices=["groq", "openrouter", "ollama", "deepinfra", "cerebras"],
        default="groq",
        help="LLM Provider: 'groq' (free & fast), 'openrouter' (free tier/cloud), or 'ollama' (local 4GB VRAM SLM)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Specific model identifier. Defaults to env value.",
    )
    parser.add_argument(
        "--task",
        choices=list(BENCHMARK_TASKS.keys()) + ["all"],
        default="ecommerce_filter_extract",
        help="Task ID to execute, or 'all'",
    )
    parser.add_argument(
        "--use-vision",
        action="store_true",
        help="Enable vision/screenshot fallback mode (default is DOM-first)",
    )
    args = parser.parse_args()

    print_banner()
    logger = TelemetryLogger()

    tasks_to_run = (
        list(BENCHMARK_TASKS.values())
        if args.task == "all"
        else [BENCHMARK_TASKS[args.task]]
    )

    frameworks = (
        ["browser-use", "playwright-mcp"]
        if args.framework == "all"
        else [args.framework]
    )

    for fw in frameworks:
        print(f"\n>>> Starting Benchmark Suite for Candidate: [{fw}] <<<\n")
        if fw == "browser-use":
            from candidate_01_browser_use.run_benchmark import run_task
            for task in tasks_to_run:
                asyncio.run(
                    run_task(
                        task=task,
                        provider=args.provider,
                        model=args.model,
                        use_vision=args.use_vision,
                        logger=logger,
                    )
                )
        elif fw == "playwright-mcp":
            from candidate_03_playwright_mcp.run_benchmark import run_mcp_task
            for task in tasks_to_run:
                asyncio.run(
                    run_mcp_task(
                        task=task,
                        provider=args.provider,
                        model=args.model,
                        logger=logger,
                    )
                )

    print("\n" + "=" * 70)
    print("All requested benchmarks finished! See results/SUMMARY.md for metrics.")
    print("=" * 70)


if __name__ == "__main__":
    run()
