"""Benchmark runner for Candidate 3: Playwright MCP (Model Context Protocol).

Spawns the Playwright MCP server via stdio and drives it with a real tool-calling
LLM loop: the model receives the MCP server's own tool schemas (browser_navigate,
browser_click, browser_type, browser_snapshot, etc.) and decides every action
itself, including the first navigation. A synthetic 'task_complete' tool is added
so the model can report its final structured result once it's done.
"""
import sys
import os
import time
import json
import asyncio
import argparse
import traceback
from typing import Optional, Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_llm, HEADLESS
from common.tasks import BENCHMARK_TASKS, BenchmarkTask
from common.telemetry import TelemetryLogger, BenchmarkRunResult


# Per-task shape for the synthetic 'task_complete' tool, mirroring the schemas
# used by the browser-use and Stagehand candidates so results are comparable.
TASK_COMPLETE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "ecommerce_filter_extract": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "price": {"type": "string"},
            "upc": {"type": "string"},
        },
        "required": ["title", "price", "upc"],
    },
    "form_auth_and_state": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
        },
        "required": ["success", "message"],
    },
    "media_spa_navigation": {
        "type": "object",
        "properties": {"video_title": {"type": "string"}},
        "required": ["video_title"],
    },
    "github_repo_traversal": {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"number": {"type": "string"}, "title": {"type": "string"}},
                    "required": ["number", "title"],
                },
            },
        },
        "required": ["issues"],
    },
}


def _judge_success(task_id: str, data: Dict[str, Any]) -> bool:
    if task_id == "ecommerce_filter_extract":
        return bool(data.get("upc"))
    if task_id == "form_auth_and_state":
        return bool(data.get("success")) and "secure area" in str(data.get("message", "")).lower()
    if task_id == "media_spa_navigation":
        return bool(data.get("video_title"))
    if task_id == "github_repo_traversal":
        return len(data.get("issues") or []) >= 2
    return False


def _mcp_tool_to_openai(tool) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }


def _unwrap_exception(e: BaseException) -> str:
    """ExceptionGroup/TaskGroup errors hide the real cause behind a generic
    summary; recursively unwrap to find the actual underlying exception(s)."""
    sub = getattr(e, "exceptions", None)
    if not sub:
        return f"{type(e).__name__}: {e}"
    parts = [_unwrap_exception(s) for s in sub]
    return " | ".join(parts)


def _content_to_text(call_result) -> str:
    parts = []
    for block in getattr(call_result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(block))
    text = "\n".join(parts) if parts else "(no content)"
    if getattr(call_result, "is_error", False):
        text = f"ERROR: {text}"
    return text


async def run_mcp_task(
    task: BenchmarkTask,
    provider: str,
    model: Optional[str] = None,
    logger: Optional[TelemetryLogger] = None,
) -> BenchmarkRunResult:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    print(f"\n=======================================================")
    print(f"Running Task: {task.name} ({task.id})")
    print(f"Candidate: Playwright MCP | Provider: {provider} | Model: {model or 'default'}")
    print(f"=======================================================")

    start_time = time.time()
    first_action_time: Optional[float] = None
    step_count = 0
    success = False
    error_message = None
    extracted_data = None
    prompt_tokens = 0
    completion_tokens = 0

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        mcp_args = ["-y", "@playwright/mcp@latest", "--viewport-size", "1280x720"]
        if HEADLESS:
            mcp_args.append("--headless")

        server_params = StdioServerParameters(
            command="npx",
            args=mcp_args,
            env=os.environ.copy(),
        )

        llm = get_llm(provider=provider, model_name=model)
        actual_model_name = getattr(llm, "model_name", None) or getattr(llm, "model", model or "unknown")

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                print(f"[Playwright MCP] Connected. Available tools: {[t.name for t in tools_result.tools]}")

                openai_tools = [_mcp_tool_to_openai(t) for t in tools_result.tools]
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "description": "Call this once the task is fully done, with the extracted result.",
                        "parameters": TASK_COMPLETE_SCHEMAS[task.id],
                    },
                })

                llm_with_tools = llm.bind_tools(openai_tools)

                messages: List[Any] = [
                    SystemMessage(content=(
                        "You control a real web browser through the provided tools. "
                        "Complete the user's task step by step, calling exactly one tool per turn, "
                        "using as few tool calls as possible. Start by navigating to the required page yourself. "
                        "Trust the result returned by each action (browser_click, browser_type, etc.) - "
                        "if the tool call succeeded, assume the action happened. "
                        "When you need element references, prefer a single browser_snapshot call over multiple "
                        "browser_find calls - one snapshot gives you every element's reference at once. "
                        "Only call browser_find/browser_snapshot again if the page has actually changed since "
                        "your last one. "
                        "As soon as you have the information the task asks for, call 'task_complete' immediately "
                        "with the extracted result matching its schema exactly - do not keep double-checking."
                    )),
                    HumanMessage(content=task.instruction),
                ]

                # Raw tool-calling needs more round-trips than the higher-level
                # candidates for the same task (discover-ref + act are separate
                # calls here, vs one action in browser-use/Stagehand). Giving
                # this candidate the task's nominal step count would penalize
                # it for being lower-level, not for being worse - so it gets a
                # documented, larger budget instead of the shared ceiling.
                effective_max_steps = task.max_steps + 6
                print(f"[Playwright MCP] Step budget: {effective_max_steps} (task default {task.max_steps} + 6 for tool-call granularity)")

                for _ in range(effective_max_steps):
                    response = await llm_with_tools.ainvoke(messages)
                    usage = getattr(response, "usage_metadata", None) or {}
                    prompt_tokens += usage.get("input_tokens", 0) or 0
                    completion_tokens += usage.get("output_tokens", 0) or 0

                    tool_calls = getattr(response, "tool_calls", None) or []
                    if not tool_calls:
                        messages.append(response)
                        messages.append(HumanMessage(content="Please call a tool, or task_complete if you are done."))
                        continue

                    messages.append(response)
                    done = False
                    for call in tool_calls:
                        name = call["name"]
                        args = call.get("args") or {}
                        call_id = call["id"]

                        if name == "task_complete":
                            extracted_data = args
                            success = _judge_success(task.id, args)
                            print(f"\n[Step {step_count}] task_complete called: {json.dumps(args)}")
                            done = True
                            messages.append(ToolMessage(content="Recorded.", tool_call_id=call_id))
                            continue

                        if first_action_time is None:
                            first_action_time = time.time()
                        step_count += 1
                        print(f"[Step {step_count}] {name}({json.dumps(args)})")
                        try:
                            call_result = await session.call_tool(name, args)
                            result_text = _content_to_text(call_result)
                        except Exception as tool_err:
                            result_text = f"ERROR calling {name}: {tool_err}"
                        # Keep the loop's context bounded; snapshots/screenshots can be large.
                        messages.append(ToolMessage(content=result_text[:8000], tool_call_id=call_id))

                    if done:
                        break
                else:
                    error_message = "Did not call task_complete within the step limit."

    except Exception as e:
        error_message = _unwrap_exception(e)
        print(f"\n[Result] MCP Error: {error_message}")
        traceback.print_exc()

    total_duration = time.time() - start_time
    ttfa_val = (first_action_time - start_time) if first_action_time else None
    print(f"\n[Result] Task {'SUCCEEDED' if success else 'FAILED'} in {total_duration:.2f}s")
    if extracted_data is not None:
        print(f"[Output]: {json.dumps(extracted_data)}")

    result = BenchmarkRunResult(
        candidate="playwright-mcp",
        provider=provider,
        model=model or "default",
        task_id=task.id,
        task_name=task.name,
        success=success,
        total_duration_sec=total_duration,
        time_to_first_action_sec=ttfa_val,
        step_count=step_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        extracted_data=extracted_data,
        error_message=error_message,
    )

    if logger:
        log_path = logger.record_run(result)
        print(f"[Telemetry] Result logged to: {log_path}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Run Playwright MCP benchmarks")
    parser.add_argument(
        "--task",
        choices=list(BENCHMARK_TASKS.keys()) + ["all"],
        default="ecommerce_filter_extract",
        help="Task ID to run",
    )
    parser.add_argument(
        "--provider",
        choices=["groq", "openrouter", "ollama", "deepinfra", "cerebras"],
        default="cerebras",
        help="LLM provider",
    )
    parser.add_argument("--model", default=None, help="Model name")
    args = parser.parse_args()

    logger = TelemetryLogger()
    tasks_to_run = list(BENCHMARK_TASKS.values()) if args.task == "all" else [BENCHMARK_TASKS[args.task]]
    for task in tasks_to_run:
        asyncio.run(run_mcp_task(task=task, provider=args.provider, model=args.model, logger=logger))


if __name__ == "__main__":
    main()
