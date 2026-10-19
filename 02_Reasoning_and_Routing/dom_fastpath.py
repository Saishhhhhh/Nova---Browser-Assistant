"""Model-free command execution on top of browser-use's page reader.

Reads the page with browser-use's DomService (via get_browser_state_summary), picks the
element for a spoken-style command with generic text-matching rules, and runs it through
browser-use's own Tools actions (click/input/send_keys/scroll/navigate/go_back).
No LLM is involved and nothing here is specific to any website.

A command the rules can't resolve confidently is NOT guessed at: run() returns
handled=False so a caller can escalate to the full browser-use agent.

Optional small-model step: pass picker=make_picker_from_env() and, ONLY when the rules
refuse, one short model call gets the command plus a compact numbered element list and
returns which element to click / type into (or "none"). Without a picker nothing here
calls any API.
"""
import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from browser_use.tools.service import Tools

from position_hints import parse_position, resolve_position

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
    box: Optional[tuple] = None                      # (x, y, width, height) in page coordinates
    in_chrome: bool = False                          # inside a nav / aside / header / footer / sidebar / menu

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


CHROME_TAGS = {"nav", "aside", "header", "footer"}
CHROME_WORDS = ("nav", "menu", "sidebar", "side-", "side_", "footer", "header", "breadcrumb", "toolbar")


def _in_chrome(node) -> bool:
    """True if the element sits inside page furniture (navigation, sidebar, header, footer)."""
    cur, depth = node, 0
    while cur is not None and depth < 12:
        name = (getattr(cur, "node_name", "") or "").lower()
        if name in CHROME_TAGS:
            return True
        a = getattr(cur, "attributes", None) or {}
        marks = f"{a.get('class', '')} {a.get('id', '')} {a.get('role', '')}".lower()
        if any(w in marks for w in CHROME_WORDS) or a.get("role") in {"navigation", "banner", "contentinfo", "complementary"}:
            return True
        cur = getattr(cur, "parent_node", None)
        depth += 1
    return False


def _box(node) -> Optional[tuple]:
    pos = getattr(node, "absolute_position", None)
    if pos is None:
        return None
    try:
        return (float(pos.x), float(pos.y), float(pos.width), float(pos.height))
    except Exception:
        return None


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
            box=_box(node),
            in_chrome=_in_chrome(node),
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


PROVIDERS = {
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "deepinfra": ("https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
    "ollama": (None, None),  # local: no key; address comes from OLLAMA_BASE_URL
}
DEFAULT_MODELS = {
    "cerebras": "gpt-oss-120b",
    "deepinfra": "google/gemma-4-31B-it-turbo",
    "ollama": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
}
POPUP_JS = """() => {
  const vw = innerWidth, vh = innerHeight;
  for (const el of document.querySelectorAll('body *')) {
    const st = getComputedStyle(el);
    const dlg = el.getAttribute('role') === 'dialog' || el.getAttribute('aria-modal') === 'true' || el.tagName === 'DIALOG';
    if (st.position !== 'fixed' && !dlg) continue;
    if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width >= 0.3 * vw && r.height >= 0.3 * vh && r.width * r.height >= 0.12 * vw * vh) {
      return el.tagName + '.' + String(el.className || '').slice(0, 40);
    }
  }
  return '';
}"""
BOT_TITLE = re.compile(
    r"just a moment|attention required|access denied|verify (?:you are|that you are) (?:a )?human|are you a robot|"
    r"captcha|security check|checking your browser|unusual traffic|robot check", re.I)
CLOSE_WORDS = {"close", "dismiss", "skip", "not now", "no thanks", "maybe later", "later", "cancel", "got it", "x"}
MAX_ELEMENTS = 250
PICK_SYSTEM = (
    "You help a voice-controlled browser. You get a spoken command and a numbered list of the "
    "elements on the current page. Decide which single element the command is about.\n"
    "Reply with ONE line of JSON and nothing else:\n"
    '{"action": "click", "index": <number>}   to click an element\n'
    '{"action": "type", "index": <number>, "text": "<text to type>"}   to type into an input\n'
    '{"action": "none", "index": null}   if the command is a question, needs several steps, '
    "or no element clearly matches\n"
    "Never guess: if you are not fairly sure which element is meant, answer none."
)


# Small local models need the task spelled out with examples (the cloud prompt above makes
# them over-refuse). The examples deliberately use unrelated words (cart, search, weather).
PICK_SYSTEM_SMALL = (
    "You control a web browser by voice. Below is a spoken command and a numbered list of the "
    'elements on the page, each shown as [number] kind "label".\n'
    "Choose the ONE element the command refers to and reply with JSON only.\n"
    'To click: {"action": "click", "index": 12}\n'
    'To type:  {"action": "type", "index": 5, "text": "what to type"}\n'
    'If nothing fits, or the command is a question or needs several steps: {"action": "none", "index": null}\n'
    "Pick the element whose label matches the words of the command, and use its exact number from the list.\n\n"
    'Command: open my shopping cart\nElements:\n[3] a "home"\n[7] a "cart 2"\n[9] button "search"\n'
    '{"action": "click", "index": 7}\n\n'
    'Command: write red shoes in the search\nElements:\n[2] input:search "search"\n[5] a "help"\n'
    '{"action": "type", "index": 2, "text": "red shoes"}\n\n'
    'Command: what is the weather\nElements:\n[1] a "news"\n[4] a "sports"\n'
    '{"action": "none", "index": null}'
)


@dataclass
class Pick:
    action: str = "none"           # click | type | none
    index: Optional[int] = None
    text: Optional[str] = None
    note: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


def format_elements(elements: list, limit: int = MAX_ELEMENTS) -> str:
    """Compact list for the model: '[index] role "label"'. Unlabelled non-input elements are skipped."""
    lines = []
    for e in elements:
        label = (e.labels[0] if e.labels else (e.weak_labels[0] if e.weak_labels else ""))[:80]
        if not label and not e.is_text_input:
            continue
        kind = f"input:{e.input_type or 'text'}" if e.tag == "input" else (e.role or e.tag)
        lines.append(f'[{e.index}] {kind} "{label}"')
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def parse_pick(raw: str) -> Pick:
    """Tolerant parser: finds the JSON object in the reply; anything unusable becomes 'none'."""
    raw = raw or ""
    data = None
    for pattern in (r"\{.*\}", r"\{.*?\}"):
        m = re.search(pattern, raw, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                break
            except ValueError:
                continue
    if not isinstance(data, dict):
        return Pick(note="no usable JSON in reply")
    action = str(data.get("action", "none")).lower()
    idx = data.get("index")
    if isinstance(idx, str):  # small models write "21", "[21]" or "#21"
        m_idx = re.fullmatch(r"\D*(\d+)\D*", idx.strip())
        idx = int(m_idx.group(1)) if m_idx else None
    idx = idx if isinstance(idx, int) and not isinstance(idx, bool) else None
    text = data.get("text")
    text = text if isinstance(text, str) and text.strip() else None
    if action not in {"click", "type"} or idx is None:
        return Pick(note="model answered none")
    if action == "type" and text is None:
        return Pick(note="type without text")
    return Pick(action=action, index=idx, text=text)


class OpenAICompatiblePicker:
    """One short chat call to Cerebras or DeepInfra (both speak the OpenAI API)."""

    def __init__(self, provider: str, model: str, system: Optional[str] = None):
        base_url, key_env = PROVIDERS[provider]
        self.provider, self.model = provider, model
        self.system = system or (PICK_SYSTEM_SMALL if provider == "ollama" else PICK_SYSTEM)
        # Longest we wait for an answer before treating it as "couldn't decide" (seconds).
        self.timeout = float(os.getenv("FASTPATH_TIMEOUT", "10"))
        if provider == "ollama":
            # Ollama's own API: lets us raise the context window (its default of 4096 tokens silently
            # cuts long page lists) and force valid JSON, which the OpenAI-style endpoint can't do.
            self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
            self.timeout = max(self.timeout, 120.0)  # a cold local model can take a while to load
            return
        key = os.getenv(key_env, "")
        if not key or key.startswith("your_"):
            raise RuntimeError(f"{key_env} is not set in .env")
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(base_url=base_url, api_key=key, timeout=self.timeout, max_retries=0)

    async def _pick_ollama(self, command: str, elements: list) -> Pick:
        import httpx
        body = {
            "model": self.model, "stream": False, "format": "json", "keep_alive": "10m",
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": f"Command: {command}\nElements:\n{format_elements(elements)}"},
            ],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 200},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.ollama_url}/api/chat", json=body)
            r.raise_for_status()
        data = r.json()
        pick = parse_pick((data.get("message") or {}).get("content", ""))
        pick.prompt_tokens = data.get("prompt_eval_count", 0)
        pick.completion_tokens = data.get("eval_count", 0)
        return pick

    async def pick(self, command: str, elements: list) -> Pick:
        if self.provider == "ollama":
            return await self._pick_ollama(command, elements)
        extra = {}
        if self.provider == "cerebras" and self.model.startswith("gpt-oss"):
            extra["reasoning_effort"] = "low"  # reasoning tokens would otherwise eat the answer budget
        r = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system},
                {"role": "user", "content": f"Command: {command}\n\nElements:\n{format_elements(elements)}"},
            ],
            temperature=0,
            max_tokens=600,
            **extra,
        )
        pick = parse_pick(r.choices[0].message.content or "")
        if r.usage:
            pick.prompt_tokens, pick.completion_tokens = r.usage.prompt_tokens, r.usage.completion_tokens
        return pick


def make_picker_from_env() -> OpenAICompatiblePicker:
    """FASTPATH_PROVIDER (deepinfra|cerebras|ollama, default deepinfra), optional FASTPATH_MODEL and
    FASTPATH_TIMEOUT (seconds, default 10). DeepInfra Gemma was the most accurate in the 18-command
    benchmark and never hit a rate limit; Cerebras is ~3x faster but rate-limits back-to-back commands."""
    provider = (os.getenv("FASTPATH_PROVIDER") or "deepinfra").strip().lower()
    model = (os.getenv("FASTPATH_MODEL") or "").strip() or DEFAULT_MODELS[provider]
    return OpenAICompatiblePicker(provider, model)


@dataclass
class Intent:
    kind: str
    text: str = ""
    target: str = ""
    direction: str = "down"
    amount: float = 1.0


def _site_name(url: str) -> str:
    """"https://www.books.toscrape.com/" -> "books.toscrape.com", for a short spoken reply."""
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/") or url


def _first_label(labels, fallback: str = "it") -> str:
    return (labels[0] if labels else fallback).strip() or fallback


# A meta-instruction to submit whatever is already typed ("like hit enter", "now", "go ahead") rather than
# literal text to search for. Without this, "search(?:\s+for)?\s+(.+)" blindly captures EVERYTHING after the
# word "search" as the query — found live: "Search now, like hit enter." retyped the search box with the
# literal text "now, like hit enter.", overwriting a correctly-typed query from the previous turn. This is a
# plain regex rule with no model involved; it was not the planner or any model being wrong.
SUBMIT_TAIL = re.compile(r"[\s,]*(?:like\s+|and\s+|then\s+)*(?:hit|press)\s+enter$", re.I)
SUBMIT_LEAD = re.compile(r"^(?:now|then|go ahead|okay|ok)[\s,]*", re.I)
# A bare instruction to submit, with nothing search-shaped in front of it at all ("hit enter", "press enter now").
BARE_SUBMIT = re.compile(r"^(?:now[\s,]+)?(?:go ahead and\s+)?(?:hit|press)\s+enter(?:\s+now)?$", re.I)


def _strip_submit_tail(text: str) -> str:
    """Remove a trailing "like hit enter" / "and press enter" clause and a leading "now" / "go ahead", so the
    search rule below can tell "search for cats, then hit enter" (query: "cats") from "search now, like hit
    enter" (no real query, just a submit instruction)."""
    t = SUBMIT_TAIL.sub("", text).strip()
    t = SUBMIT_LEAD.sub("", t).strip()
    return t


def parse_command(command: str) -> Intent:
    t = command.strip().rstrip(".!?")
    m = re.match(r"^(?:go to|navigate to|visit|open)\s+(\S+)$", t, re.I)
    if m and URLISH.match(m.group(1)):
        url = m.group(1)
        return Intent("navigate", target=url if url.lower().startswith("http") else f"https://{url}")
    if BARE_SUBMIT.match(t):
        return Intent("submit")
    m = re.match(r"^search(?:\s+for)?\s+(.+)$", t, re.I)
    if m:
        text = _strip_submit_tail(strip_quotes(m.group(1)))
        if not text:
            return Intent("submit")
        return Intent("search", text=text)
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
    verified: Optional[bool] = None  # True/False once the effect was checked (scroll); None = not checked
    used_model: bool = False
    picked: str = ""  # label of the element the model chose (empty if it chose nothing valid)
    model_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    settle_ms: float = 0.0
    read_ms: float = 0.0
    blocked: bool = False  # a popup covers the page and could not be closed
    total_ms: float = 0.0
    spoken: str = ""  # a short natural-language reply for the voice layer ("Opened Travel."); "" falls back to "Done."


class FastPath:
    def __init__(self, browser, picker=None):
        self.browser = browser
        self.picker = picker  # optional small-model step; None = rules only, no API calls
        self.tools = Tools()
        self.action_model = self.tools.registry.create_action_model()
        self._dirty = False  # the previous command may have changed the page
        self.viewport = None  # (scroll_x, scroll_y, width, height) of the last page read

    async def _scroll_y(self) -> float:
        page = await self.browser.get_current_page()
        return float(await asyncio.wait_for(page.evaluate("() => window.scrollY"), 3) or 0)

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

    async def _on_real_page(self) -> bool:
        """False before the browser has ever navigated anywhere (about:blank, or browser-use's own
        "Starting agent..." placeholder tab). Found live: with no --start-url, the very first command's popup
        check ran on that placeholder page, found a large DIV on it, and reported "a popup is covering the
        page" — on a page with nothing real loaded at all. Popup/bot checks only make sense on a real page."""
        try:
            url = await self.browser.get_current_page_url()
        except Exception:
            return False
        return (url or "").lower().startswith(("http://", "https://"))

    async def _bot_check(self) -> str:
        """The page's title if it is a "verify you are human" / access-denied interstitial, else ''."""
        if not await self._on_real_page():
            return ""
        try:
            page = await self.browser.get_current_page()
            title = str(await asyncio.wait_for(page.evaluate("() => document.title"), 3) or "")
        except Exception:
            return ""
        return title if BOT_TITLE.search(title) else ""

    async def _popup_present(self) -> str:
        if not await self._on_real_page():
            return ""
        try:
            page = await self.browser.get_current_page()
            return str(await asyncio.wait_for(page.evaluate(POPUP_JS), 3) or "")
        except Exception:
            return ""

    async def dismiss_popup(self) -> str:
        """Close a popup/modal covering the page. Returns "none" (nothing there), "closed" or "stuck"."""
        if not await self._popup_present():
            return "none"
        for _ in range(2):
            try:
                await self._act({"send_keys": {"keys": "Escape"}})
            except Exception:
                pass
            await asyncio.sleep(0.6)
            if not await self._popup_present():
                self._dirty = True
                return "closed"
        # Escape did nothing: click something that says close / skip / no thanks
        for e in await self._read_page():
            if any(l in CLOSE_WORDS for l in e.labels) and e.is_actionable:
                try:
                    await self._act({"click": {"index": e.index}})
                except Exception:
                    continue
                await asyncio.sleep(0.6)
                if not await self._popup_present():
                    self._dirty = True
                    return "closed"
        return "stuck"

    async def _read_page(self) -> list:
        for _ in range(3):
            state = await self.browser.get_browser_state_summary(include_screenshot=False)
            pi = getattr(state, "page_info", None)
            if pi is not None:
                self.viewport = (float(pi.scroll_x), float(pi.scroll_y), float(pi.viewport_width), float(pi.viewport_height))
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
            if intent.kind == "unknown" and self.picker is None:
                res.detail = "no rule matches this command"
            elif intent.kind == "navigate":
                await self._act({"navigate": {"url": intent.target, "new_tab": False}})
                self._dirty = True
                res.handled, res.detail = True, f"navigated to {intent.target}"
                res.spoken = f"Opened {_site_name(intent.target)}."
                title = await self._bot_check()
                if title:
                    res.blocked, res.detail = True, f"bot check: the site is asking to verify the visitor ('{title}')"
            elif intent.kind == "scroll":
                # no upfront settle: _run_scroll checks the page moved and only then waits and retries
                await self._run_scroll(intent, res)
            elif intent.kind == "back":
                await self._act({"go_back": {}})
                self._dirty = True
                res.handled, res.detail = True, "went back"
                res.spoken = "Went back."
            elif intent.kind == "submit":
                # press Enter on whatever already has focus (e.g. a search box just typed into); never retype
                await self._act({"send_keys": {"keys": "Enter"}})
                self._dirty = True
                res.handled, res.detail = True, "pressed Enter (no retyping)"
                res.spoken = "Done."
            else:  # search / type / click, or an unknown command when a model is available
                await self._settle_if_dirty(res)
                title = await self._bot_check()
                if title:
                    res.blocked, res.detail = True, f"bot check: the site is asking to verify the visitor ('{title}')"
                    res.total_ms = (time.perf_counter() - start) * 1000
                    return res
                t_read = time.perf_counter()
                elements = await self._read_page()
                res.read_ms = (time.perf_counter() - t_read) * 1000
                if intent.kind != "unknown":
                    await self._run_dom_intent(intent, elements, res)
                if not res.handled and self.picker is not None:
                    await self._ask_model(command, elements, res)
        except Exception as e:
            res.handled, res.error = True, f"{type(e).__name__}: {e}"
        res.total_ms = (time.perf_counter() - start) * 1000
        return res

    async def _wait_scrollable(self, timeout: float) -> None:
        """Wait until the page is taller than the window (content has rendered), or give up."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                page = await self.browser.get_current_page()
                room = float(await asyncio.wait_for(
                    page.evaluate("() => document.documentElement.scrollHeight - window.innerHeight"), 2) or 0)
            except Exception:
                return
            if room > 50:
                return
            await asyncio.sleep(0.15)

    async def _run_scroll(self, intent: Intent, res: Result) -> None:
        """Scroll, then check the page really moved; if not, wait for it to settle and try once more."""
        payload = {"scroll": {"down": intent.direction == "down", "pages": intent.amount}}
        try:
            before = await self._scroll_y()
        except Exception:
            before = None  # can't measure on this page; just do the action
        after = before
        for attempt in (1, 2):
            await self._act(payload)
            if before is None:
                res.handled, res.detail = True, f"scrolled {intent.direction} (not verified)"
                res.spoken = f"Scrolled {intent.direction}."
                return
            await asyncio.sleep(0.3)
            after = await self._scroll_y()
            if abs(after - before) > 1:
                break
            if attempt == 1:
                await self._wait_scrollable(3.0)
        res.handled = True
        res.verified = abs(after - before) > 1
        res.detail = (f"scrolled {intent.direction} ({before:.0f} -> {after:.0f} px)" if res.verified
                      else f"scroll ran twice but the page did not move (still {after:.0f} px)")
        res.spoken = (f"Scrolled {intent.direction}." if res.verified
                      else f"I tried to scroll {intent.direction}, but the page didn't move.")

    async def _ask_model(self, command: str, elements: list, res: Result) -> None:
        """Rules refused: one short model call picks the element. Anything unclear stays refused."""
        res.used_model = True
        rules_note = res.detail or "no rule matches"
        t = time.perf_counter()
        limit = getattr(self.picker, "timeout", None)
        try:
            pick = await asyncio.wait_for(self.picker.pick(command, elements), limit)
        except asyncio.TimeoutError:
            res.model_ms = (time.perf_counter() - t) * 1000
            res.detail = f"{rules_note} | model timed out after {limit:.0f}s"
            return
        except Exception as e:
            res.model_ms = (time.perf_counter() - t) * 1000
            res.detail = f"{rules_note} | model call failed: {type(e).__name__}"
            return
        res.model_ms = (time.perf_counter() - t) * 1000
        res.prompt_tokens, res.completion_tokens = pick.prompt_tokens, pick.completion_tokens
        target = next((e for e in elements if e.index == pick.index), None) if pick.index is not None else None
        label = (target.labels[:1] or target.weak_labels[:1]) if target else ""
        res.picked = label[0] if label else ""
        if pick.action == "click" and target:
            await self._act({"click": {"index": target.index}})
            self._dirty = True
            res.handled, res.detail = True, f"model clicked [{target.index}] {label}"
            res.spoken = f"Clicked {_first_label(label)}."
        elif pick.action == "type" and target and pick.text:
            await self._act({"input": {"index": target.index, "text": pick.text, "clear": True}})
            res.handled, res.detail = True, f"model typed into [{target.index}] {label}"
            res.spoken = f"Typed into {_first_label(label)}."
        else:
            why = pick.note or "model chose an element that is not on the page"
            res.detail = f"{rules_note} | model declined ({why})"

    async def _run_dom_intent(self, intent: Intent, elements: list, res: Result) -> None:
        if intent.kind == "search":
            hit = find_search_box(elements)
            if not hit and await self._popup_present():
                outcome = await self.dismiss_popup()
                if outcome == "stuck":
                    res.blocked, res.detail = True, "a popup is covering the page and would not close"
                    return
                if outcome == "closed":
                    elements = await self._read_page()
                    hit = find_search_box(elements)
            if not hit:
                res.detail = "no search box found"
                return
            box = hit[0]
            await self._act({"input": {"index": box.index, "text": intent.text, "clear": True}})
            await self._act({"send_keys": {"keys": "Enter"}})
            self._dirty = True
            res.handled, res.detail = True, f"typed '{intent.text}' into [{box.index}] and pressed Enter"
            res.spoken = f"Searched for {intent.text}."
        elif intent.kind == "type":
            hit = find_field(elements, intent.target)
            if not hit:
                res.detail = f"no field matches '{intent.target}'"
                return
            await self._act({"input": {"index": hit[0].index, "text": intent.text, "clear": True}})
            res.handled, res.detail = True, f"typed into [{hit[0].index}] (score {hit[1]:.2f})"
            res.spoken = f"Typed into {_first_label(hit[0].labels, intent.target)}."
        elif intent.kind == "click":
            ranked = rank_click_targets(elements, intent.target)
            top, score = ranked[0] if ranked else (None, 0.0)
            pos_note = ""
            # a clear label match always wins ("Top Stories", "(Top)"); position words are only used when no label
            # matches strongly ("the second result", "the link at the top left")
            if score < 0.9:
                hint = parse_position(intent.target)
                if hint is not None:
                    if res.settle_ms > 0:      # the page just changed: lists are often drawn a moment after it "settles"
                        before = len(elements)
                        for _ in range(3):
                            await asyncio.sleep(0.8)
                            again = await self._read_page()
                            grew = len(again) > before * 1.1
                            elements, before = again, len(again)
                            if not grew:
                                break
                    if await self._popup_present():
                        outcome = await self.dismiss_popup()
                        if outcome == "stuck":
                            res.blocked, res.detail = True, "a popup is covering the page and would not close"
                            return
                        if outcome == "closed":
                            elements = await self._read_page()
                    picked, note = resolve_position(elements, hint, self.viewport)
                    if picked is not None:
                        await self._act({"click": {"index": picked.index}})
                        self._dirty = True
                        res.handled, res.detail = True, f"clicked [{picked.index}] {picked.labels[:1]} by position ({note})"
                        res.spoken = f"Clicked {_first_label(picked.labels, intent.target)}."
                        return
                    pos_note = f"position hint: {note}; "
            if top is None or score < MIN_SCORE:
                best = f"best was [{top.index}] {top.labels[:1]} at {score:.2f}" if top else "nothing on page"
                res.detail = f"{pos_note}no confident match for '{intent.target}' ({best})"
                return
            await self._act({"click": {"index": top.index}})
            self._dirty = True
            res.handled, res.detail = True, f"clicked [{top.index}] {top.labels[:1]} (score {score:.2f})"
            res.spoken = f"Clicked {_first_label(top.labels, intent.target)}."
