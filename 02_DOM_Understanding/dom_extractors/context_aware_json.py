"""
Representation E: Context-Aware Indexed Interactive Extractor.
Uses repeated-sibling structure detection to scope cards, and extracts typed
context (price, schedule, stops, airline) in JavaScript to eliminate token bloat
and enable deterministic Python constraint filtering.

Enhanced with:
- Deep Shadow DOM traversal (penetrates Web Components, e.g. YouTube ytd-*, Gmail)
- Robust visibility detection (checkVisibility, offsetParent, opacity, aria-hidden)
- Semantic role tagging (SEARCH_INPUT, EMAIL_INPUT, PASSWORD_INPUT, PHONE_INPUT)
- First-class aria-label extraction
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

                function querySelectorAllDeep(root, selector, maxCount = 350) {{
                    const results = [];
                    function walk(node) {{
                        if (!node || results.length >= maxCount) return;
                        if (node.querySelectorAll) {{
                            try {{
                                const matched = node.querySelectorAll(selector);
                                for (let i = 0; i < matched.length && results.length < maxCount; i++) {{
                                    results.push(matched[i]);
                                }}
                            }} catch (e) {{}}
                        }}
                        const children = node.children || [];
                        for (let i = 0; i < children.length && results.length < maxCount; i++) {{
                            const child = children[i];
                            if (child.shadowRoot) {{
                                walk(child.shadowRoot);
                            }}
                        }}
                    }}
                    walk(root);
                    return results;
                }}

                function isVisible(el) {{
                    if (!el || !(el instanceof Element)) return false;
                    
                    // Fast pre-filter: offsetParent is null when any ancestor has display:none
                    // (except for body/html and position:fixed elements)
                    if (el.offsetParent === null && el.tagName !== 'BODY' && el.tagName !== 'HTML') {{
                        try {{
                            if (window.getComputedStyle(el).position !== 'fixed') return false;
                        }} catch (e) {{
                            return false;
                        }}
                    }}

                    // Native Chrome 105+ visibility API
                    if (el.checkVisibility) {{
                        try {{
                            if (!el.checkVisibility({{checkOpacity: true, checkVisibilityCSS: true}})) return false;
                        }} catch (e) {{}}
                    }} else {{
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    }}

                    // Aria hidden check
                    if (el.getAttribute('aria-hidden') === 'true') return false;

                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) return false;

                    // Allow 0.8 viewport height of vertical padding for adjacent cards
                    const vPad = window.innerHeight * 0.8;
                    if (r.bottom < -vPad || r.top > window.innerHeight + vPad || r.right < 0 || r.left > window.innerWidth) return false;
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

                    const snippet = text.replace(ownText, '').replace(/\\s+/g, ' ').trim();
                    if (snippet) {{
                        ctx.text = snippet.slice(0, {self.max_context_chars});
                    }}

                    return Object.keys(ctx).length ? ctx : null;
                }}

                // 1. Remove existing agent badges and highlight rings before re-indexing
                document.querySelectorAll('.__agent_num_badge, .__agent_active_ring').forEach(el => el.remove());

                // 2. Neutralize target="_blank" so link navigation stays within the same tab
                document.querySelectorAll('a[target="_blank"]').forEach(a => a.setAttribute('target', '_self'));

                // 3. Deep query selector traversing open shadow DOMs
                const allInteractive = querySelectorAllDeep(document, INTERACTIVE_SELECTOR, 350);
                const candidates = allInteractive.filter(isVisible);
                const visible = [];
                let count = 0;

                for (const el of candidates) {{
                    count++;
                    try {{
                        el.setAttribute('data-agent-index', String(count));
                    }} catch (e) {{}}

                    const ariaLabel = el.getAttribute('aria-label');
                    let ownText = (el.innerText || el.value || el.placeholder || ariaLabel || '').trim();
                    ownText = ownText.replace(/\\s+/g, ' ').slice(0, 80);

                    const scope = findCardScope(el);
                    const ctx = extractTypedContext(scope, ownText);

                    const tag = el.tagName.toLowerCase();
                    const role = el.getAttribute('role') || tag;
                    const item = {{
                        "id": count,
                        "tag": tag,
                        "role": role,
                        "text": ownText
                    }};

                    if (el.id) item["dom_id"] = el.id;
                    if (el.type) item["type"] = el.type;
                    if (el.placeholder) item["placeholder"] = el.placeholder;
                    if (ariaLabel) item["aria_label"] = ariaLabel.trim().slice(0, 80);

                    // Semantic role inference
                    if (tag === 'input' || tag === 'textarea') {{
                        const isSearch = el.type === 'search'
                            || /search/i.test(el.id || '')
                            || /search/i.test(el.placeholder || '')
                            || /search/i.test(el.name || '')
                            || /search/i.test(ariaLabel || '');
                        if (isSearch) {{
                            item["semantic_role"] = "SEARCH_INPUT";
                        }} else if (/email/i.test(el.type || el.name || '')) {{
                            item["semantic_role"] = "EMAIL_INPUT";
                        }} else if (/password/i.test(el.type || '')) {{
                            item["semantic_role"] = "PASSWORD_INPUT";
                        }} else if (/phone|tel|mobile/i.test(el.type || el.name || el.id || '')) {{
                            item["semantic_role"] = "PHONE_INPUT";
                        }}
                    }}

                    if (el.value && ['input', 'select'].includes(tag)) item["value"] = el.value;
                    if (tag === 'select') {{
                        try {{
                            item["options"] = Array.from(el.options).map(o => ({{ "val": o.value, "label": o.text.trim() }}));
                        }} catch (e) {{}}
                    }}
                    if (tag === 'input' && ['checkbox', 'radio'].includes(el.type)) {{
                        item["checked"] = el.checked;
                    }}
                    if (ctx) item["ctx"] = ctx;

                    const r = el.getBoundingClientRect();
                    item["coords"] = {{
                        "x": Math.round(r.left + r.width / 2),
                        "y": Math.round(r.top + r.height / 2)
                    }};

                    // Inject visual numbered badges if enabled
                    if ({str(self.inject_visual_badges).lower()}) {{
                        let existingBadge = document.querySelector(`.__agent_num_badge[data-badge-id="${{count}}"]`);
                        if (!existingBadge) {{
                            const badge = document.createElement('span');
                            badge.className = '__agent_num_badge';
                            badge.setAttribute('data-badge-id', String(count));
                            badge.textContent = String(count);
                            badge.style.cssText = 'position:absolute;background:#f59e0b;color:#111827;font-family:system-ui,-apple-system,sans-serif;font-size:11px;font-weight:900;padding:1px 6px;border-radius:4px;z-index:2147483647;pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,0.6);border:1px solid #ffffff;line-height:16px;';
                            badge.style.left = (r.left + window.scrollX - 4) + 'px';
                            badge.style.top = (r.top + window.scrollY - 8) + 'px';
                            document.body.appendChild(badge);
                        }}
                    }}

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
