"""Model-free command execution on top of browser-use's page reader.

Reads the page with browser-use's DomService (via get_browser_state_summary), picks the
element for a spoken-style command with generic text-matching rules, and runs it through
browser-use's own Tools actions (click/input/send_keys/scroll/navigate/go_back).
No LLM is involved and nothing here is specific to any website.

A command the rules can't resolve confidently is NOT guessed at: run() returns
handled=False so a caller can escalate (small model, then the full browser-use agent).
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from browser_use.tools.service import Tools

MIN_SCORE = 0.6
GENERIC_WORDS = {"button", "link", "tab", "icon", "option", "field", "box", "input", "menu", "item"}
TEXT_INPUT_TYPES = {"", "text", "search", "email", "password", "url", "tel", "number"}
CLICKABLE_INPUT_TYPES = {"submit", "button", "reset", "image"}
URLISH = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(:\d+)?(/\S*)?$", re.I)


def norm(s: Optional[str]) -> str:
    s = (s or "").lower().replace("’", "").replace("'", "")
    return re.sub(r"[\W_]+", " ", s).strip()


def strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


@dataclass
class ElementInfo:
    index: int
    tag: str
    role: str
    input_type: str
    attrs: dict
    labels: list = field(default_factory=list)       # visible text, accessible name, aria-label, ...
    weak_labels: list = field(default_factory=list)  # name / id attributes

    @property
    def is_text_input(self) -> bool:
        if self.tag == "textarea" or self.role in {"textbox", "searchbox", "combobox"}:
            return True
        return self.tag == "input" and self.input_type in TEXT_INPUT_TYPES

    @property
    def is_actionable(self) -> bool:
        return (
            self.tag in {"a", "button"}
            or self.role in {"button", "link", "tab", "menuitem", "option"}
            or (self.tag == "input" and self.input_type in CLICKABLE_INPUT_TYPES)
        )


def build_elements(selector_map: dict) -> list:
    elements = []
    for index, node in selector_map.items():
        attrs = dict(node.attributes or {})
        ax = getattr(node, "ax_node", None)
        try:
            text = (node.get_all_children_text() or "")[:200]
        except Exception:
            text = ""
        input_type = (attrs.get("type") or "").lower()
        raw = [getattr(ax, "name", None), text, attrs.get("aria-label"), attrs.get("title"),
               attrs.get("placeholder"), attrs.get("alt")]
        if input_type in CLICKABLE_INPUT_TYPES:
            raw.append(attrs.get("value"))
        labels = list(dict.fromkeys(n for n in (norm(x) for x in raw) if n))
        weak = list(dict.fromkeys(n for n in (norm(attrs.get("name")), norm(attrs.get("id"))) if n))
        elements.append(ElementInfo(
            index=index,
            tag=(node.node_name or "").lower(),
            role=(attrs.get("role") or getattr(ax, "role", None) or "").lower(),
            input_type=input_type,
            attrs=attrs,
            labels=labels,
            weak_labels=weak,
        ))
    return elements


def label_score(q: str, label: str) -> float:
    if not q or not label:
        return 0.0
    if q == label:
        return 1.0
    qw, lw = q.split(), label.split()
    if f" {q} " in f" {label} ":
        base = 0.9
    elif set(qw) <= set(lw):
        base = 0.8
    else:
        overlap = len(set(qw) & set(lw)) / len(set(qw))
        fuzzy = SequenceMatcher(None, q, label).ratio()
        base = max(0.5 * overlap if overlap >= 0.6 else 0.0, 0.7 * fuzzy if fuzzy >= 0.85 else 0.0)
    # a short label that contains the query beats a long paragraph that merely mentions it
    return max(base - min(max(len(lw) - len(qw), 0), 30) * 0.01, 0.0)


def _best_label_score(q: str, e: ElementInfo, weak_weight: float) -> float:
    strong = max((label_score(q, l) for l in e.labels), default=0.0)
    weak = max((label_score(q, l) for l in e.weak_labels), default=0.0) * weak_weight
    return max(strong, weak)


def strip_generic_words(q: str) -> str:
    words = [w for w in q.split() if w not in GENERIC_WORDS]
    return " ".join(words) or q


def rank_click_targets(elements: list, query: str) -> list:
    q = strip_generic_words(norm(query))
    scored = []
    for e in elements:
        s = _best_label_score(q, e, weak_weight=0.85)
        if e.is_text_input:
            s -= 0.15  # "click X" rarely means "focus a text box"
        if e.is_actionable:
            s += 0.03
        scored.append((e, s))
    return sorted(scored, key=lambda x: -x[1])  # stable: ties keep page order


def find_field(elements: list, query: str):
    q = strip_generic_words(norm(query))
    scored = [(e, _best_label_score(q, e, weak_weight=1.0)) for e in elements
              if e.is_text_input or e.tag == "select"]
    scored.sort(key=lambda x: -x[1])
    return scored[0] if scored and scored[0][1] >= MIN_SCORE else None


def find_search_box(elements: list):
    best = None
    for e in elements:
        if not e.is_text_input:
            continue
        score = 0
        if e.input_type == "search" or e.role == "searchbox":
            score = 3
        hints = [e.attrs.get(k, "") for k in ("name", "id", "aria-label", "placeholder", "title")]
        if any("search" in h.lower() for h in hints) or e.attrs.get("name") in {"q", "query", "s"}:
            score = max(score, 2)
        if score and (best is None or score > best[1]):
            best = (e, score)
    return best


@dataclass
class Intent:
    kind: str
    text: str = ""
    target: str = ""
    direction: str = "down"
    amount: float = 1.0


def parse_command(command: str) -> Intent:
    t = command.strip().rstrip(".!?")
    m = re.match(r"^(?:go to|navigate to|visit|open)\s+(\S+)$", t, re.I)
    if m and URLISH.match(m.group(1)):
        url = m.group(1)
        return Intent("navigate", target=url if url.lower().startswith("http") else f"https://{url}")
    m = re.match(r"^search(?:\s+for)?\s+(.+)$", t, re.I)
    if m:
        return Intent("search", text=strip_quotes(m.group(1)))
    m = re.match(r"^(?:type|enter|write|fill(?: in)?)\s+(.+?)\s+(?:into|in)\s+(?:the\s+)?(.+)$", t, re.I)
    if m:
        return Intent("type", text=strip_quotes(m.group(1)), target=m.group(2))
    m = re.match(r"^scroll\s+(down|up)(?:\s+(\d+))?$", t, re.I)
    if m:
        return Intent("scroll", direction=m.group(1).lower(), amount=float(m.group(2) or 1))
    if re.match(r"^(?:go back|back|previous page)$", t, re.I):
        return Intent("back")
    m = re.match(r"^(?:click|press|tap|select|choose|open|hit)\s+(?:on\s+)?(?:the\s+)?(.+)$", t, re.I)
    if m:
        return Intent("click", target=strip_quotes(m.group(1)))
    return Intent("unknown")


@dataclass
class Result:
    command: str
    intent: str
    handled: bool
    detail: str = ""
    error: Optional[str] = None
    settle_ms: float = 0.0
    read_ms: float = 0.0
    total_ms: float = 0.0


class FastPath:
    def __init__(self, browser):
        self.browser = browser
        self.tools = Tools()
        self.action_model = self.tools.registry.create_action_model()
        self._dirty = False  # the previous command may have changed the page

    async def _act(self, payload: dict):
        result = await self.tools.act(self.action_model.model_validate(payload), browser_session=self.browser)
        if result.error:
            raise RuntimeError(result.error)
        return result

    async def _settle(self, timeout: float = 4.0) -> None:
        """Wait until the page stops changing (single-page apps update the URL before content renders)."""
        js = ("() => document.readyState + '|' + document.documentElement.scrollHeight + '|' "
              "+ document.getElementsByTagName('*').length")
        deadline = time.perf_counter() + timeout
        last, stable = None, 0
        while time.perf_counter() < deadline:
            try:
                page = await self.browser.get_current_page()
                cur = await asyncio.wait_for(page.evaluate(js), 2)
            except Exception:
                return
            stable = stable + 1 if cur == last and str(cur).startswith("complete") else 0
            if stable >= 2:
                return
            last = cur
            await asyncio.sleep(0.25)

    async def _settle_if_dirty(self, res: Result) -> None:
        if self._dirty:
            t = time.perf_counter()
            await self._settle()
            res.settle_ms = (time.perf_counter() - t) * 1000
            self._dirty = False

    async def _read_page(self) -> list:
        for _ in range(3):
            state = await self.browser.get_browser_state_summary(include_screenshot=False)
            elements = build_elements(state.dom_state.selector_map)
            if elements:
                return elements
            await self._settle(2.0)  # empty read: page not rendered yet
        return []

    async def run(self, command: str) -> Result:
        start = time.perf_counter()
        intent = parse_command(command)
        res = Result(command=command, intent=intent.kind, handled=False)
        try:
            if intent.kind == "unknown":
                res.detail = "no rule matches this command"
            elif intent.kind == "navigate":
                await self._act({"navigate": {"url": intent.target, "new_tab": False}})
                self._dirty = True
                res.handled, res.detail = True, f"navigated to {intent.target}"
            elif intent.kind == "scroll":
                await self._settle_if_dirty(res)
                await self._act({"scroll": {"down": intent.direction == "down", "pages": intent.amount}})
                res.handled, res.detail = True, f"scrolled {intent.direction}"
            elif intent.kind == "back":
                await self._act({"go_back": {}})
                self._dirty = True
                res.handled, res.detail = True, "went back"
            else:
                await self._settle_if_dirty(res)
                t_read = time.perf_counter()
                elements = await self._read_page()
                res.read_ms = (time.perf_counter() - t_read) * 1000
                await self._run_dom_intent(intent, elements, res)
        except Exception as e:
            res.handled, res.error = True, f"{type(e).__name__}: {e}"
        res.total_ms = (time.perf_counter() - start) * 1000
        return res

    async def _run_dom_intent(self, intent: Intent, elements: list, res: Result) -> None:
        if intent.kind == "search":
            hit = find_search_box(elements)
            if not hit:
                res.detail = "no search box found"
                return
            box = hit[0]
            await self._act({"input": {"index": box.index, "text": intent.text, "clear": True}})
            await self._act({"send_keys": {"keys": "Enter"}})
            self._dirty = True
            res.handled, res.detail = True, f"typed '{intent.text}' into [{box.index}] and pressed Enter"
        elif intent.kind == "type":
            hit = find_field(elements, intent.target)
            if not hit:
                res.detail = f"no field matches '{intent.target}'"
                return
            await self._act({"input": {"index": hit[0].index, "text": intent.text, "clear": True}})
            res.handled, res.detail = True, f"typed into [{hit[0].index}] (score {hit[1]:.2f})"
        elif intent.kind == "click":
            ranked = rank_click_targets(elements, intent.target)
            top, score = ranked[0] if ranked else (None, 0.0)
            if top is None or score < MIN_SCORE:
                best = f"best was [{top.index}] {top.labels[:1]} at {score:.2f}" if top else "nothing on page"
                res.detail = f"no confident match for '{intent.target}' ({best})"
                return
            await self._act({"click": {"index": top.index}})
            self._dirty = True
            res.handled, res.detail = True, f"clicked [{top.index}] {top.labels[:1]} (score {score:.2f})"
