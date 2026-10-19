"""Standalone speed/cost benchmark for DeepInfra chat models.

Not part of the candidate comparison harness - this is a smaller, separate
tool for picking a model (e.g. for browser-use's page_extraction_llm) based
on real measured numbers instead of vendor-published benchmarks.

Sends one large-context prompt (to simulate a real DOM/page-extraction call)
and one short prompt per model, measuring:
  - time to first token (TTFT)
  - total wall-clock time
  - estimated cost, using the PRICING table below
  - whether the long-context call actually extracted the right text
    (checked against EXPECTED_EXTRACTION - a model that's fast but wrong
    is useless, so this is not optional)

A per-token "generation speed" stat was deliberately dropped: at these
output lengths (well under a few hundred tokens), responses often arrive
in one network burst right after the first token, making total-time minus
TTFT collapse toward zero and any tokens/total-gen-time division produce
meaningless numbers (some early runs showed "84,000 tok/s", which no real
model does). Total wall-clock time is the only timing number trustworthy
at this scale.

IMPORTANT: PRICING below is hand-entered from public DeepInfra pricing pages
at the time this script was written and can go stale. Verify against
https://deepinfra.com/pricing before trusting the cost numbers.

This script makes real, billed API calls. It does nothing on import/parse -
review MODELS and MAX_OUTPUT_TOKENS below, then run it deliberately.
"""
import os
import time
import argparse
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")

# (input $/1M tokens, output $/1M tokens) - confirmed directly from deepinfra.com/pricing
# at the time this script was written; re-check if pricing seems stale later.
PRICING = {
    "openai/gpt-oss-120b-Turbo": (0.15, 0.60),
    "openai/gpt-oss-120b": (0.037, 0.17),
    "openai/gpt-oss-20b": (0.03, 0.14),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.10, 0.32),
    "google/gemma-4-31B-it-turbo": (0.09, 0.34),
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": (0.02, 0.04),
    "Qwen/Qwen2.5-72B-Instruct": (0.36, 0.40),
    "ibm-granite/granite-4.2-3b": (0.03, 0.12),
    "ibm-granite/granite-4.2-8b": (0.06, 0.25),
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506": (0.075, 0.20),
}

MODELS = list(PRICING.keys())
MAX_OUTPUT_TOKENS = 150

# ~8-10k tokens of filler to stand in for a real DOM/accessibility-tree dump.
_FILLER_PARAGRAPH = (
    "This section of the page contains a list of interactive elements: "
    "buttons, links, input fields and text blocks, each with an index, a "
    "role, and a short description used for automated navigation. "
)
LONG_CONTEXT = (
    _FILLER_PARAGRAPH * 120
    + "\n\nTARGET ELEMENT [index=4821]: <h1 class='video-title'>lofi hip hop radio - beats to relax/study to</h1>\n\n"
    + _FILLER_PARAGRAPH * 60
)
LONG_PROMPT = (
    "Here is a dump of page elements:\n\n" + LONG_CONTEXT +
    "\n\nExtract only the text content of the element marked TARGET ELEMENT above. Respond with just the text."
)
SHORT_PROMPT = "Reply with exactly the word: ready"
EXPECTED_EXTRACTION = "lofi hip hop radio - beats to relax/study to"


def _is_correct(output_text: str) -> bool:
    return EXPECTED_EXTRACTION.lower() in output_text.lower()


@dataclass
class RunResult:
    model: str
    prompt_label: str
    ttft_sec: Optional[float] = None
    total_sec: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    output_text: str = ""
    error: Optional[str] = None

    def cost_usd(self) -> Optional[float]:
        if self.model not in PRICING:
            return None
        in_price, out_price = PRICING[self.model]
        return (self.input_tokens * in_price + self.output_tokens * out_price) / 1_000_000


def run_one(client: OpenAI, model: str, prompt: str, label: str) -> RunResult:
    result = RunResult(model=model, prompt_label=label)
    start = time.time()
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = []
        for chunk in stream:
            if result.ttft_sec is None and chunk.choices and chunk.choices[0].delta.content:
                result.ttft_sec = time.time() - start
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
            if getattr(chunk, "usage", None):
                result.input_tokens = chunk.usage.prompt_tokens
                result.output_tokens = chunk.usage.completion_tokens
        result.output_text = "".join(chunks).strip()
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
    result.total_sec = time.time() - start
    return result


def print_result(r: RunResult):
    if r.error:
        print(f"  [{r.prompt_label}] ERROR: {r.error}")
        return
    ttft = f"{r.ttft_sec:.2f}s" if r.ttft_sec is not None else "N/A"
    cost = r.cost_usd()
    cost_str = f"${cost:.6f}" if cost is not None else "N/A (no pricing entry)"
    print(
        f"  [{r.prompt_label}] TTFT={ttft}  total={r.total_sec:.2f}s  "
        f"in={r.input_tokens}tok  out={r.output_tokens}tok  cost={cost_str}"
    )
    print(f"      output: {r.output_text!r}")
    if r.prompt_label == "long-context":
        verdict = "CORRECT" if _is_correct(r.output_text) else "WRONG/MISSING"
        print(f"      extraction check: {verdict}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark DeepInfra model speed/cost")
    parser.add_argument("--models", nargs="*", default=MODELS, help="Subset of models to test")
    parser.add_argument("--skip-long", action="store_true", help="Skip the large-context prompt")
    args = parser.parse_args()

    if not DEEPINFRA_API_KEY or DEEPINFRA_API_KEY.startswith("your_"):
        raise SystemExit("DEEPINFRA_API_KEY is not set in .env")

    client = OpenAI(base_url="https://api.deepinfra.com/v1/openai", api_key=DEEPINFRA_API_KEY)

    total_cost = 0.0
    print(f"Testing {len(args.models)} model(s), max_output_tokens={MAX_OUTPUT_TOKENS}\n")

    for model in args.models:
        print(f"=== {model} ===")
        r_short = run_one(client, model, SHORT_PROMPT, "short")
        print_result(r_short)
        if (r_short.cost_usd() or 0) > 0:
            total_cost += r_short.cost_usd()

        if not args.skip_long:
            r_long = run_one(client, model, LONG_PROMPT, "long-context")
            print_result(r_long)
            if (r_long.cost_usd() or 0) > 0:
                total_cost += r_long.cost_usd()
        print()

    print(f"Estimated total spend this run: ${total_cost:.6f}")
    print("(Pricing table is hand-entered and may be stale - verify at https://deepinfra.com/pricing)")


if __name__ == "__main__":
    main()
