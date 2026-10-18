"""Phase 2 (Experiment 9): short conversation memory and a scratchpad of facts within one session.

Two separate problems this fixes, both confirmed broken before this: each command was fully independent
(no memory between turns), and a multi-step plan had no way to compare facts gathered at different steps
("should I buy the Acer or the MSI" needs both prices remembered while looking at neither page any more).

  memory = ConversationMemory()
  memory.add_turn("tell me the price", "It's £51.77.")
  memory.remember("ask the price of the Acer", "£12,499")
  ...
  if needs_memory(next_command):
      augmented = f"{next_command} ({memory.context_block()})"   # appended, so rules/QUESTION still see the
                                                                   # real command first; the agent sees the context

Kept deliberately small: a handful of recent turns and a flat dict of facts, not a general memory store.
"""
import os
import re
import time
from dataclasses import dataclass, field

import httpx

COMPARE_MODEL_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
COMPARE_MODEL_KEY_ENV = "DEEPINFRA_API_KEY"
COMPARE_MODEL_NAME = "google/gemma-4-31B-it-turbo"

# Words that point at something outside the current command: an earlier answer, an earlier page, a past turn.
# A command matching this is given the conversation context; one that doesn't is left alone (most commands don't
# need it, and every extra word costs the agent a little more to read).
REFERENTIAL = re.compile(
    r"\b(that one|the other one|the first one|the second one|the last one|the cheaper one|the more expensive one|"
    r"the one before|the previous one|it|that|those|these|earlier|before|previously|again|compare|cheaper|"
    r"more expensive|which (?:one|is)|both|either)\b", re.I)


def needs_memory(text: str) -> bool:
    return bool(REFERENTIAL.search(text))


@dataclass
class Turn:
    command: str
    reply: str
    ok: bool = True


@dataclass
class ConversationMemory:
    max_turns: int = 4
    turns: list = field(default_factory=list)       # most recent last
    scratchpad: dict = field(default_factory=dict)  # label (usually the "ask" step's own text) -> its answer

    def add_turn(self, command: str, reply: str, ok: bool = True) -> None:
        self.turns.append(Turn(command, reply, ok))
        self.turns = self.turns[-self.max_turns:]

    def remember(self, label: str, value: str) -> None:
        self.scratchpad[label] = value

    def clear_scratchpad(self) -> None:
        self.scratchpad = {}

    def context_block(self) -> str:
        """One line of recent turns and remembered facts, meant to be appended after the live command."""
        parts = []
        if self.turns:
            parts.append("earlier: " + "; ".join(f'you said "{t.command}" and I said "{t.reply}"' for t in self.turns))
        if self.scratchpad:
            parts.append("remembered: " + "; ".join(f"{k} -> {v}" for k, v in self.scratchpad.items()))
        return " | ".join(parts)


async def compare_from_scratchpad(client: httpx.AsyncClient, question: str, scratchpad: dict) -> tuple:
    """Answer `question` using only the facts already in `scratchpad` — no browser, it's reasoning over
    what earlier plan steps already found. -> (answer: str, ms: float)."""
    facts = "\n".join(f"- {q}: {a}" for q, a in scratchpad.items()) or "(no facts were recorded)"
    body = {"model": COMPARE_MODEL_NAME, "temperature": 0, "max_tokens": 200,
            "messages": [
                {"role": "system", "content": "Answer the question using only the facts given below; do not invent "
                                              "anything not in them. Reply in one or two short sentences, spoken "
                                              "out loud to the person who asked."},
                {"role": "user", "content": f"Facts:\n{facts}\n\nQuestion: {question}"}]}
    t = time.perf_counter()
    r = await client.post(COMPARE_MODEL_URL, headers={"Authorization": f"Bearer {os.getenv(COMPARE_MODEL_KEY_ENV)}"}, json=body)
    ms = (time.perf_counter() - t) * 1000
    if r.status_code >= 400:
        return f"I couldn't work that out: HTTP {r.status_code}.", ms
    return (r.json()["choices"][0]["message"]["content"] or "").strip() or "I'm not sure.", ms


# A plan's final step is a comparison/verdict question, not something to read off whatever page we are on.
COMPARE_QUESTION = re.compile(
    r"\b(compare|cheaper|more expensive|better|which (?:one|is)|should i (?:buy|get|choose|pick)|"
    r"worth it|good deal|recommend)\b", re.I)
