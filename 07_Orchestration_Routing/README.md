# Orchestration and Routing

## Experimentation

Run the full pipeline end to end:

`VAD -> STT -> router -> local model or API model -> DOM/vision -> action -> optional TTS`

Compare local-only, API-only, and routed hybrid execution on the task benchmark, including simple commands and complex multi-step workflows.

## Goal

Confirm that the hybrid reduces latency compared with pure API execution without losing much success rate, while improving quality over pure local execution for difficult tasks.

## What To Measure

- End-to-end latency by task complexity
- Success rate and quality
- Local-to-API escalation rate
- Routing reason and correctness
- Retries and recovery behavior
- API cost and local resource use
- User-visible and spoken failure feedback

## Final Architecture Requirements

- Single click, type, or navigate commands complete in a couple of seconds at most
- API model is used only when needed, not by default
- Complex multi-step tasks can escalate for quality
- No silent failures: always confirm, ask, or speak an error

## Results

Record pipeline variant, task, component timings, total latency, model decisions, escalation reason, retries, success or failure, user feedback, cost, and final routing decision.
