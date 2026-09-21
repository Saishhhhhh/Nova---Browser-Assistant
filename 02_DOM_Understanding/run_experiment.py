"""
Master Orchestrator for Experiment 02: DOM Understanding & SLM Grounding Benchmark.
"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from benchmarks.bench_extractors import run_extractor_benchmark
from benchmarks.bench_models import run_models_benchmark
from benchmarks.reporter import generate_report


async def main():
    parser = argparse.ArgumentParser(description="Experiment 02 Master Benchmark Orchestrator")
    parser.add_argument("--suite", choices=["extractors", "models", "all"], default="all", help="Benchmark suite to execute")
    parser.add_argument("--models", nargs="+", default=["qwen2.5:1.5b", "llama3.2:1b"], help="Ollama model names to benchmark")
    parser.add_argument("--pull", action="store_true", help="Automatically pull models via Ollama if missing")
    parser.add_argument("--smoke", action="store_true", help="Quick smoke test (5 tasks)")
    parser.add_argument("--report-only", action="store_true", help="Generate report from existing results without re-running")

    args = parser.parse_args()

    print("\n" + "="*70)
    print(">> EXPERIMENT 02: DOM UNDERSTANDING & SLM GROUNDING BENCHMARK")
    print("="*70)

    if args.report_only:
        generate_report()
        return

    # Suite 1: Extractors
    if args.suite in ["extractors", "all"]:
        await run_extractor_benchmark()

    # Suite 2: Models
    if args.suite in ["models", "all"]:
        limit = 5 if args.smoke else None
        await run_models_benchmark(
            model_names=args.models,
            pull_if_missing=args.pull,
            max_tasks=limit
        )

    # Consolidated Report
    generate_report()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
