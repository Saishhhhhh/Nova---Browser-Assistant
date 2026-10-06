"""The single entry point the speech layer calls: CommandRouter.run_command(text).

Order of attempts:
  1. rules            - no model at all (dom_fastpath)
  2. one short model call (dom_fastpath, only when the rules refuse; DeepInfra Gemma by default)
  3. the full browser-use agent - only when 1 and 2 both decline

The agent runs on the SAME open browser, so it continues from whatever page the fast path
left it on. For that the Browser must be created with keep_alive=True: otherwise the agent
closes the browser when its run ends and nothing after it works.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from browser_use import Agent

from dom_fastpath import FastPath


@dataclass
class RouterResult:
    command: str
    tier: str                 # "rules" | "model" | "agent" | "failed"
    ok: bool
    reply: str                # short text for the speech layer to say
    detail: str = ""
    total_ms: float = 0.0
    fast_ms: float = 0.0      # time spent in rules + model step before (possibly) escalating
    agent_steps: int = 0
    agent_urls: list = field(default_factory=list)


class CommandRouter:
    def __init__(self, browser, picker=None, agent_llm=None, extraction_llm=None,
                 agent_max_steps: int = 8, agent_timeout: float = 240.0):
        if not getattr(browser.browser_profile, "keep_alive", False):
            raise ValueError("create the Browser with keep_alive=True, or the agent closes it when it finishes")
        self.browser = browser
        self.fast = FastPath(browser, picker=picker)
        self.agent_llm = agent_llm
        self.extraction_llm = extraction_llm
        self.agent_max_steps = agent_max_steps
        self.agent_timeout = agent_timeout

    async def run_command(self, command: str) -> RouterResult:
        start = time.perf_counter()
        fast = await self.fast.run(command)
        fast_ms = (time.perf_counter() - start) * 1000
        if fast.handled and not fast.error:
            return RouterResult(command, "model" if fast.used_model else "rules", True, "Done.",
                                detail=fast.detail, total_ms=fast_ms, fast_ms=fast_ms)
        why = fast.error or fast.detail
        if self.agent_llm is None:
            return RouterResult(command, "failed", False, "Sorry, I couldn't do that.",
                                detail=why, total_ms=fast_ms, fast_ms=fast_ms)
        result = await self._run_agent(command)
        result.detail = f"fast path declined ({why}) | {result.detail}"
        result.fast_ms = fast_ms
        result.total_ms = (time.perf_counter() - start) * 1000
        return result

    async def _run_agent(self, command: str) -> RouterResult:
        agent = Agent(
            task=command, llm=self.agent_llm, browser=self.browser, use_vision=False,
            use_judge=False, enable_planning=False, flash_mode=True,
            page_extraction_llm=self.extraction_llm,
        )
        try:
            history = await asyncio.wait_for(agent.run(max_steps=self.agent_max_steps), self.agent_timeout)
        except asyncio.TimeoutError:
            agent.stop()
            self.fast._dirty = True
            return RouterResult(command, "failed", False, "That is taking too long, I stopped.",
                                detail=f"agent timed out after {self.agent_timeout:.0f}s")
        except Exception as e:
            self.fast._dirty = True
            return RouterResult(command, "failed", False, "Sorry, something went wrong.",
                                detail=f"agent error: {type(e).__name__}: {e}"[:200])
        self.fast._dirty = True  # the agent changed the page: the fast path must re-read it
        done = history.is_done()
        answer = (history.final_result() or "").strip()
        return RouterResult(
            command, "agent", bool(done and history.is_successful() is not False),
            answer[:400] or "I finished, but I have nothing to report.",
            detail=f"{history.number_of_steps()} steps", agent_steps=history.number_of_steps(),
            agent_urls=[u for u in history.urls() if u],
        )
