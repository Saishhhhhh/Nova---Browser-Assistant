"""Benchmark runner for Candidate 1: browser-use.

Supports OpenRouter (Gemini, DeepSeek, etc.) and Ollama SLMs (Qwen2.5, Hammer2.1, Llama3.2).
Measures task completion, Time-To-First-Action (TTFA), step count, and total duration.
"""
import sys
import os
import time
import asyncio
import argparse
from typing import Optional

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_browser_use_llm, HEADLESS, EXTRACTION_PROVIDER, EXTRACTION_MODEL
from common.tasks import BENCHMARK_TASKS, BenchmarkTask
from common.telemetry import TelemetryLogger, BenchmarkRunResult
from browser_use import Agent, Browser


async def run_task(
    task: BenchmarkTask,
    provider: str,
    model: Optional[str] = None,
    use_vision: bool = False,
    logger: Optional[TelemetryLogger] = None,
) -> BenchmarkRunResult:
    print(f"\n=======================================================")
    print(f"Running Task: {task.name} ({task.id})")
    print(f"Candidate: browser-use | Provider: {provider} | Model: {model or 'default'}")
    print(f"Vision Enabled: {use_vision}")
    print(f"=======================================================")

    llm = get_browser_use_llm(provider=provider, model_name=model)
    actual_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", model or "unknown")

    # Extraction calls send whole-page content; routing them to a different
    # provider keeps them from exhausting the main model's per-minute token cap.
    extraction_llm = None
    if EXTRACTION_PROVIDER:
        extraction_llm = get_browser_use_llm(provider=EXTRACTION_PROVIDER, model_name=EXTRACTION_MODEL)
        print(f"Extraction model: {getattr(extraction_llm, 'model', EXTRACTION_MODEL)}")

    start_time = time.time()
    first_action_time: Optional[float] = None
    step_count = 0

    def on_step_callback(state, output, step_idx):
        nonlocal first_action_time, step_count
        step_count = step_idx
        if first_action_time is None:
            first_action_time = time.time()
            ttfa = first_action_time - start_time
            print(f"[Telemetry] Time to First Action (TTFA): {ttfa:.2f}s")
        print(f"[Step {step_idx}] Executed action: {getattr(output, 'current_state', '')}")

    browser = Browser(
        headless=HEADLESS,
        no_viewport=True,
        window_position={"width": 0, "height": 0},
        window_size={"width": 1536, "height": 864},
        minimum_wait_page_load_time=0.25,
        wait_for_network_idle_page_load_time=1.0,
        wait_between_actions=0.1,
    )

    agent = Agent(
        task=task.instruction,
        llm=llm,
        use_vision=use_vision,
        register_new_step_callback=on_step_callback,
        browser=browser,
        use_judge=False,
        enable_planning=False,
        flash_mode=True,
        page_extraction_llm=extraction_llm,
    )

    success = False
    error_message = None
    extracted_data = None
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0

    try:
        history = await agent.run(max_steps=task.max_steps)
        total_duration = time.time() - start_time
        
        # Check success: did the agent reach is_done?
        if history and history.is_done():
            success = True
            extracted_data = history.final_result()
            print(f"\n[Result] Task SUCCEEDED in {total_duration:.2f}s!")
            print(f"[Output]: {extracted_data}")
        else:
            success = False
            error_message = "Task did not reach completion within step limit."
            print(f"\n[Result] Task FAILED: {error_message}")

        # Attempt to collect token usage if tracked by history/model
        if hasattr(history, "total_tokens"):
            total_tokens = getattr(history, "total_tokens", 0)

    except Exception as e:
        total_duration = time.time() - start_time
        success = False
        error_message = str(e)
        print(f"\n[Result] Task ERROR: {error_message}")

    ttfa_val = (first_action_time - start_time) if first_action_time else None

    result = BenchmarkRunResult(
        candidate="browser-use",
        provider=provider,
        model=actual_model_name,
        task_id=task.id,
        task_name=task.name,
        success=success,
        total_duration_sec=total_duration,
        time_to_first_action_sec=ttfa_val,
        step_count=step_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        extracted_data=extracted_data,
        error_message=error_message,
    )

    if logger:
        log_path = logger.record_run(result)
        print(f"[Telemetry] Result logged to: {log_path}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Run browser-use benchmarks")
    parser.add_argument(
        "--task",
        choices=list(BENCHMARK_TASKS.keys()) + ["all"],
        default="ecommerce_filter_extract",
        help="Task ID to run, or 'all'",
    )
    parser.add_argument(
        "--provider",
        choices=["groq", "openrouter", "ollama", "deepinfra", "cerebras"],
        default="groq",
        help="LLM provider: 'groq' (free & fast), 'openrouter' (cloud), or 'ollama' (local SLM)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name (e.g., 'google/gemini-2.5-flash', 'qwen2.5:3b', 'hammer2.1:3b')",
    )
    parser.add_argument(
        "--use-vision",
        action="store_true",
        help="Enable screenshot VLM vision mode (default is DOM-first / False)",
    )
    args = parser.parse_args()

    logger = TelemetryLogger()

    tasks_to_run = (
        list(BENCHMARK_TASKS.values())
        if args.task == "all"
        else [BENCHMARK_TASKS[args.task]]
    )

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


if __name__ == "__main__":
    main()
