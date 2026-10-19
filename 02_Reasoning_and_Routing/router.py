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

import re

from dom_fastpath import FastPath, parse_command

# Commands that ask for information or an opinion about the page. The rules never match them and the one-model-call
# step only answers "none" (Exp 7 measured 1.4-3.5 s wasted), so they go straight to the agent. Includes advisory /
# opinion phrasing ("should I buy this", "is this worth it") alongside plain factual questions, found missing when
# testing conversational questions like "should I buy this monitor" (it fell through the wasted model-step call).
# Also "ask", the literal word planner.py's step grammar uses for its own question steps (Phase 1/2): without it,
# a plan's "ask the price" step fell through to the model-step (whose job is picking what to click), which guessed
# a click instead of refusing (found while testing Phase 2's comparison steps — it poisoned the scratchpad).
QUESTION = re.compile(
    r"^(?:tell me|ask|what|what's|whats|which|who|how many|how much|how|where|when|why|find|read|summari[sz]e|list|"
    r"count|compare|is there|are there|does|can you tell|should i|should we|should you|is it|is this|is that|"
    r"are these|are those|would you|do you think|did you|can i|could i|recommend)\b", re.I)


# Spoken filler and politeness in front of a command ("um go back", "please scroll down", "can you click travel")
FILLER = re.compile(
    r"^(?:(?:um+|uh+|er+|erm|hmm+|mm+|okay|ok|so|well|like|just|please|hey|now|then|can you|could you|would you|will you|"
    r"i want you to|i would like you to|i'd like you to|go ahead and)\b[\s,.]*)+", re.I)
TRAILING = re.compile(r"[\s,.]*\b(?:please|thanks|thank you)\W*$", re.I)

# A correction or retry ("I said go to X", "no, I meant the second one", "actually, scroll down"). Stripped the
# same way FILLER is, so the real command underneath still reaches the rules/QUESTION/needs_memory checks
# unchanged — a stripped "the second one" is already covered by Phase 2's referential-word handling. "no" alone
# is safe to strip: clean_command() falls back to the original text when stripping leaves nothing, so bare "No."
# still reaches CHAT. Found live: "I said go to books.to scrape.com" (a retry after mis-transcription) was run
# as a literal command and the model-step tried to find something to click matching the whole sentence.
CORRECTION = re.compile(r"^(?:(?:no|wait|actually|sorry|i said|i meant|i mean)\b[\s,.]*)+", re.I)

# A verb with no object. These must never reach the agent, which would guess and click around (seen in Exp 7).
VAGUE = {
    "click": "Click what?", "press": "Press what?", "tap": "Tap what?", "select": "Select what?",
    "choose": "Choose what?", "open": "Open what?", "hit": "Hit what?", "type": "Type what?",
    "enter": "Enter what?", "search": "Search for what?", "go to": "Go where?", "navigate": "Go where?",
    "scroll": "Up or down?", "go": "Go where?",
}


# Small talk and reactions. These are not commands: never send them to the model step or the agent.
CHAT = re.compile(
    r"^(?:cool|nice|great|awesome|perfect|good|fine|okay|ok|alright|all right|got it|yes|yeah|yep|yup|no|nope|hmm+|"
    r"mm+|wow|sure|right|oh|ah|sweet|excellent|wonderful|amazing|thanks|thank you|cheers|good job|well done)[^a-z]*$", re.I)
THANKS = re.compile(r"^(?:thanks|thank you|cheers|good job|well done)[^a-z]*$", re.I)


CLOSE_POPUP = re.compile(
    r"^(?:close|dismiss|get rid of|remove)\s+(?:the |this |that )?(?:popup|pop up|pop-up|dialog|modal|banner|window|it)[^a-z]*$", re.I)


# "Stop" (or "cancel", "never mind") said with nothing running. By the time run_command() executes, the single
# worker thread has nothing else in flight, so there's nothing to cancel - but a bare "Stop." is one word, which
# previously fell into the generic "too short to be a command" clarify path and asked "Sorry, what should I do?"
# in response to someone trying to stop something. Found live: this happened twice in a row in the same session.
STANDALONE_CANCEL = re.compile(r"^(?:stop|cancel|never mind|nevermind|forget it|abort|halt|enough)[^a-z]*$", re.I)


def _safe_strip(regex: re.Pattern, t: str) -> str:
    """Apply `regex`'s strip, but never let it reduce the text to nothing — if it would, keep the input
    unchanged instead. Without this, "No thanks." (CORRECTION strips "No " -> "thanks.", then TRAILING strips
    "thanks." entirely -> "") fell all the way back to clean_command's own empty-fallback, which returns the
    ORIGINAL unstripped text ("No thanks.") rather than the partially-stripped "No" that CHAT can recognise —
    found live: it was treated as a 2-word fragment ("Sorry, what should I do?") instead of a plain decline."""
    new = regex.sub("", t).strip()
    return new if new else t


def clean_command(text: str) -> str:
    t = _safe_strip(TRAILING, text.strip())   # trailing politeness first, so "No thanks." -> "No", not "" -> original
    for _ in range(3):   # FILLER and CORRECTION can interleave ("no, um, I meant..."); a few passes catches it
        new = _safe_strip(FILLER, _safe_strip(CORRECTION, t))
        if new == t:
            break
        t = new
    return t[:1].upper() + t[1:] if t else text.strip()


def is_correction(text: str) -> bool:
    """True if `text` opens with a correction/retry phrase AND has real content after it ("no, I meant go
    back", "actually, scroll down") — used to cancel an in-flight command instead of just queuing the
    correction to run after it. A bare "No." or a plain decline ("no, thanks") is NOT a correction: stripping
    would leave nothing, or leave only another reaction, so cancelling would be the wrong call — that stays
    CHAT's job. Strips FILLER only (not CORRECTION) first, so "um, no, I meant..." is still recognised; call
    this on the raw heard text, before clean_command() has already removed the very marker being checked for."""
    t = FILLER.sub("", text.strip())
    if not CORRECTION.match(t):
        return False
    remainder = CORRECTION.sub("", t).strip()
    return bool(remainder) and not CHAT.match(remainder)


def vague_question(text: str) -> str:
    """The question to ask when the command is just a verb, else empty."""
    return VAGUE.get(re.sub(r"[\s.!?,]+$", "", text.strip().lower()), "")


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
                 agent_max_steps: int = 8, agent_timeout: float = 240.0, on_agent_start=None):
        if not getattr(browser.browser_profile, "keep_alive", False):
            raise ValueError("create the Browser with keep_alive=True, or the agent closes it when it finishes")
        self.browser = browser
        self.fast = FastPath(browser, picker=picker)
        self.agent_llm = agent_llm
        self.extraction_llm = extraction_llm
        self.agent_max_steps = agent_max_steps
        self.agent_timeout = agent_timeout
        self._agent = None
        self.on_agent_start = on_agent_start   # called (no arguments) just before the slow agent run begins

    async def run_command(self, command: str) -> RouterResult:
        start = time.perf_counter()
        command = clean_command(command)
        if CLOSE_POPUP.match(command):
            outcome = await self.fast.dismiss_popup()
            ms = (time.perf_counter() - start) * 1000
            said = {"closed": "Closed it.", "none": "There is no popup.", "stuck": "I could not close it."}[outcome]
            return RouterResult(command, "rules", outcome != "stuck", said, detail=f"popup: {outcome}", total_ms=ms, fast_ms=ms)
        if STANDALONE_CANCEL.match(command):
            return RouterResult(command, "chat", True, "", detail="nothing running to stop")
        ask = vague_question(command)
        if ask:
            return RouterResult(command, "clarify", False, ask, detail="command has no target")
        if parse_command(command).kind == "unknown" and not QUESTION.match(command):
            if CHAT.match(command):
                return RouterResult(command, "chat", True, "You're welcome." if THANKS.match(command) else "",
                                    detail="small talk, nothing to do")
            if len(command.split()) <= 2:
                # one or two words that are no known command: do not let the agent guess what was meant
                return RouterResult(command, "clarify", False, "Sorry, what should I do?",
                                    detail="too short to be a command")
        if parse_command(command).kind == "unknown":
            # the rules cannot handle this, so it will not be instant: let the speech layer say "On it." now
            if self.on_agent_start:
                self.on_agent_start()
            if QUESTION.match(command.strip()) and self.agent_llm is not None:
                result = await self._run_agent(command)
                result.detail = f"question, fast path skipped | {result.detail}"
                result.total_ms = (time.perf_counter() - start) * 1000
                return result
        fast = await self.fast.run(command)
        fast_ms = (time.perf_counter() - start) * 1000
        if fast.blocked:   # a popup is in the way: say so, do not send the agent to flail at the page behind it
            said = ("This site is asking to verify that I am not a robot, so I cannot continue here."
                    if fast.detail.startswith("bot check") else
                    "A popup is covering the page and I could not close it. Tell me what to click.")
            return RouterResult(command, "blocked", False, said, detail=fast.detail, total_ms=fast_ms, fast_ms=fast_ms)
        if fast.handled and not fast.error:
            return RouterResult(command, "model" if fast.used_model else "rules", True, fast.spoken or "Done.",
                                detail=fast.detail, total_ms=fast_ms, fast_ms=fast_ms)
        why = fast.error or fast.detail
        if self.agent_llm is None:
            return RouterResult(command, "failed", False, "Sorry, I couldn't do that.",
                                detail=why, total_ms=fast_ms, fast_ms=fast_ms)
        if self.on_agent_start:
            self.on_agent_start()
        result = await self._run_agent(command)
        result.detail = f"fast path declined ({why}) | {result.detail}"
        result.fast_ms = fast_ms
        result.total_ms = (time.perf_counter() - start) * 1000
        return result

    def cancel(self) -> bool:
        """Stop the running agent (it finishes its current step first). True if there was one."""
        agent = self._agent
        if agent is None:
            return False
        agent.stop()
        self.fast._dirty = True
        return True

    async def _run_agent(self, command: str) -> RouterResult:
        agent = Agent(
            task=command, llm=self.agent_llm, browser=self.browser, use_vision=False,
            use_judge=False, enable_planning=False, flash_mode=True,
            page_extraction_llm=self.extraction_llm,
        )
        self._agent = agent
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
        self._agent = None
        self.fast._dirty = True  # the agent changed the page: the fast path must re-read it
        done = history.is_done()
        answer = (history.final_result() or "").strip()
        return RouterResult(
            command, "agent", bool(done and history.is_successful() is not False),
            answer[:400] or "I finished, but I have nothing to report.",
            detail=f"{history.number_of_steps()} steps", agent_steps=history.number_of_steps(),
            agent_urls=[u for u in history.urls() if u],
        )
