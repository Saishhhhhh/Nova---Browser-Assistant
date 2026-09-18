# Browser Automation Core

## Experimentation

Compare Playwright, raw CDP, and a `browser-use`-style wrapper. Test click, type, scroll, and navigate actions plus DOM/accessibility-tree extraction on 5-10 real sites:

- Static pages
- SPA-heavy pages
- Iframe-heavy pages
- Lazy-loaded pages
- Complex forms and interactive widgets

## Goal

Find the fastest reliable approach to execute browser actions and extract a compact, LLM-readable page representation.

## What To Measure

- Action overhead for click, type, scroll, and navigate
- DOM/accessibility-tree extraction latency
- Tree size and estimated token count
- Cold-start and warm-run latency
- Stale-element and silent-failure rate
- Retry rate and successful task completion rate
- Behavior during re-renders, lazy loading, and dynamic content

## Final Pick Requirements

- Action overhead under 100-200 ms
- Pruned interactive-element tree extracted well under 1 second, including heavy SPAs
- Dynamic content handled without silently failing
- Errors observable and recoverable

## Results

Record the hypothesis, site and task, implementation version, browser version, hardware, run count, median latency, p95 latency, success rate, failure mode, recovery behavior, and final decision.
