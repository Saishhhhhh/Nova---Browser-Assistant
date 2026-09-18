# DOM-Understanding Model

## Experimentation

Compare 2-3 small local models, such as Qwen2.5-7B, Phi-3.5, and Llama-3.1-8B, on a fixed task set. Give each model the same instruction and pruned DOM/accessibility tree, then require it to output the next action: click, type, or selector.

## Goal

Find the smallest and fastest model that reliably chooses the correct element and action.

## What To Measure

- Task success rate and per-task accuracy
- Response latency on target hardware
- Invalid or hallucinated selector rate
- Behavior with ambiguous, missing, and stale elements
- Confidence and escalation behavior
- Memory use and tokens processed

## Final Pick Requirements

- Define a success bar, such as greater than 85%
- Respond in approximately 1-2 seconds or less
- Ask for help or escalate when uncertain instead of hallucinating a selector
- Degrade gracefully when the DOM is incomplete or stale

## Results

Record model, quantization, hardware, prompt, task-set version, warm-up procedure, run count, latency, accuracy, failures, recovery behavior, and decision.
