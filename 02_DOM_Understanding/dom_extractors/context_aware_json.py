"""
Representation E: Context-Aware Indexed Interactive Extractor.
Uses repeated-sibling structure detection to scope cards, and extracts typed
context (price, schedule, stops, airline) in JavaScript to eliminate token bloat
and enable deterministic Python constraint filtering.
"""

import time
import json
from typing import Dict, Any, Tuple, List
from playwright.async_api import Page
from .base import BaseDOMExtractor


class ContextAwareJSONExtractor(BaseDOMExtractor):
    name = "context_aware_json"

    def __init__(self, inject_visual_badges: bool = False, max_walk_depth: int = 5, max_context_chars: int = 120):
        self.inject_visual_badges = inject_visual_badges
        self.max_walk_depth = max_walk_depth
        self.max_context_chars = max_context_chars

    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter_ns()

        script = f"""
            (() => {{
                const INTERACTIVE_SELECTOR = "a, button, input, select, textarea, [role='button'], [role='link'], [role='checkbox'], [role='radio'], [role='option'], [tabindex]";

                const PRICE_RE = /[$€£]\\s?\\d[\\d,]*(?:\\.\\d{{1,2}})?/;
                const TIME_RE = /\\b(\\d{{1,2}}:\\d{{2}}\\s?(?:AM|PM|am|pm)?)\\b/;
                const STOPS_RE = /\\b(non-?stop|direct|\\d+\\s?stop[s]?)\\b/i;

                function isVisible(el) {{
                    if (!el || !(el instanceof Element)) return false;
                    if (el.offsetParent === null && el.tagName !== 'BODY') return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return false;
                    if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) return false;
                    return true;
                }}

                function structureSignature(el) {{
                    const classes = (el.className && typeof el.className === 'string')
                        ? el.className.trim().split(/\\s+/).sort().join('.')
                        : '';
                    return `${{el.tagName}}#${{classes}}`;
                }}

                function isCardElement(el) {{
                    if (!el || !(el instanceof Element)) return false;
                    const role = el.getAttribute && el.getAttribute('role');
                    if (role && ['listitem', 'row', 'article', 'group'].includes(role)) return true;
                    if (['ARTICLE', 'LI', 'TR'].includes(el.tagName)) return true;
                    const className = (typeof el.className === 'string' ? el.className.toLowerCase() : '');
                    if (/(^|\\s|_|-)(card|item|flight|product|result|row)($|\\s|_|-)/.test(className)) return true;
                    return false;
                }}

                function hasRepeatedSiblingStructure(el) {{
                    const parent = el.parentElement;
                    if (!parent) return false;
                    // Don't treat bare generic DIVs with no classes as repeated cards
                    const classes = (el.className && typeof el.className === 'string') ? el.className.trim() : '';
                    if (el.tagName === 'DIV' && !classes) return false;

                    const sig = structureSignature(el);
                    let matches = 0;
                    for (const sibling of parent.children) {{
                        if (sibling !== el && structureSignature(sibling) === sig) matches++;
                        if (matches >= 1) return true;
                    }}
                    return false;
                }}

                function directTextLength(el) {{
                    let len = 0;
                    for (const node of el.childNodes) {{
                        if (node.nodeType === Node.TEXT_NODE) len += node.textContent.trim().length;
                    }}
                    return len;
                }}

                function findCardScope(interactiveEl) {{
                    let node = interactiveEl.parentElement;
                    let depth = 0;
                    let candidate = null;

                    while (node && depth < {self.max_walk_depth} && node !== document.body) {{
                        if (isCardElement(node)) {{
                            return node;
                        }}
                        if (hasRepeatedSiblingStructure(node)) {{
                            candidate = node;
                        }}
                        node = node.parentElement;
                        depth++;
                    }}
                    return candidate;
                }}

                function extractTypedContext(scopeEl, ownText) {{
                    if (!scopeEl) return null;
                    const text = scopeEl.innerText || '';
                    if (!text || text.length > 2500) return null;

                    const ctx = {{}};
                    const price = text.match(PRICE_RE);
                    if (price) ctx.price = parseFloat(price[0].replace(/[^0-9.]/g, ''));

                    const time = text.match(TIME_RE);
                    if (time) ctx.time = time[1];

                    const stops = text.match(STOPS_RE);
                    if (stops) {{
                        const s = stops[1].toLowerCase();
                        ctx.stops = /non-?stop|direct/.test(s) ? 0 : parseInt(s, 10);
                    }}

                    // Extract descriptive snippet minus button text
                    const snippet = text.replace(ownText, '').replace(/\\s+/g, ' ').trim();
                    if (snippet) {{
                        ctx.text = snippet.slice(0, {self.max_context_chars});
                    }}

                    return Object.keys(ctx).length ? ctx : null;
                }}

                const candidates = Array.from(document.querySelectorAll(INTERACTIVE_SELECTOR)).filter(isVisible);
                const visible = [];
                let count = 0;

                for (const el of candidates) {{
                    count++;
                    el.setAttribute('data-agent-index', count);

                    let ownText = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim();
                    ownText = ownText.replace(/\\s+/g, ' ').slice(0, 80);

                    const scope = findCardScope(el);
                    const ctx = extractTypedContext(scope, ownText);

                    const role = el.getAttribute('role') || el.tagName.toLowerCase();
                    const item = {{
                        "id": count,
                        "tag": el.tagName.toLowerCase(),
                        "role": role,
                        "text": ownText
                    }};

                    if (el.id) item["dom_id"] = el.id;
                    if (el.type) item["type"] = el.type;
                    if (el.placeholder) item["placeholder"] = el.placeholder;
                    if (el.value && ['input', 'select'].includes(el.tagName.toLowerCase())) item["value"] = el.value;
                    if (el.tagName.toLowerCase() === 'select') {{
                        item["options"] = Array.from(el.options).map(o => ({{ "val": o.value, "label": o.text.trim() }}));
                    }}
                    if (el.tagName.toLowerCase() === 'input' && ['checkbox', 'radio'].includes(el.type)) {{
                        item["checked"] = el.checked;
                    }}
                    if (ctx) item["ctx"] = ctx;

                    const r = el.getBoundingClientRect();
                    item["coords"] = {{
                        "x": Math.round(r.left + r.width / 2),
                        "y": Math.round(r.top + r.height / 2)
                    }};

                    visible.push(item);
                }}

                return visible;
            }})()
        """

        raw_items: List[Dict[str, Any]] = await page.evaluate(script)
        json_str = json.dumps(raw_items, indent=2)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        tokens = self.estimate_tokens(json_str)

        metadata = {
            "extractor": self.name,
            "extraction_ms": round(elapsed_ms, 2),
            "element_count": len(raw_items),
            "char_count": len(json_str),
            "token_estimate": tokens,
            "raw_items": raw_items
        }
        return json_str, metadata
