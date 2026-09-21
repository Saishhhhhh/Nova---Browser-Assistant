"""
Representation D: Sub-15ms Indexed Interactive Element Extractor.
Extracts visible interactive elements as a compact, structured JSON array with numbered indices.
Injects `data-agent-index` for 1:1 deterministic action execution.
"""

import time
import json
from typing import Dict, Any, Tuple, List
from playwright.async_api import Page
from .base import BaseDOMExtractor


class IndexedJSONExtractor(BaseDOMExtractor):
    name = "indexed_json"

    def __init__(self, inject_visual_badges: bool = True):
        self.inject_visual_badges = inject_visual_badges

    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter_ns()
        
        script = f"""
            (() => {{
                const candidates = Array.from(document.querySelectorAll(
                    "a, button, input, select, textarea, [role='button'], [role='link'], [role='checkbox'], [role='radio'], [tabindex]"
                ));
                let count = 0;
                const visible = [];

                for (const el of candidates) {{
                    // Skip hidden elements
                    if (el.offsetParent === null && el.tagName !== 'BODY') continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    // Check viewport
                    if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) continue;

                    count++;
                    el.setAttribute('data-agent-index', count);

                    // Grab text, placeholder, aria-label, or value
                    let text = el.innerText || el.textContent || '';
                    text = text.replace(/\\s+/g, ' ').trim();
                    if (text.length > 80) text = text.slice(0, 80) + '...';

                    const role = el.getAttribute('role') || el.tagName.toLowerCase();
                    const item = {{
                        "id": count,
                        "tag": el.tagName.toLowerCase(),
                        "role": role,
                        "text": text,
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

                    item["coords"] = {{
                        "x": Math.round(r.left + r.width / 2),
                        "y": Math.round(r.top + r.height / 2)
                    }};

                    // Optionally inject visual badge on screen
                    if ({str(self.inject_visual_badges).lower()}) {{
                        let badge = el.querySelector('.__agent_num_badge');
                        if (!badge) {{
                            badge = document.createElement('span');
                            badge.className = '__agent_num_badge';
                            badge.textContent = count;
                            badge.style.cssText = 'position:absolute;top:-6px;left:-6px;background:#f59e0b;color:#000;font-size:11px;font-weight:800;padding:1px 5px;border-radius:4px;z-index:2147483647;pointer-events:none;box-shadow:0 2px 5px rgba(0,0,0,0.5);';
                            // If element is relative/absolute, append inside, else append to body with coords
                            if (window.getComputedStyle(el).position !== 'static') {{
                                el.appendChild(badge);
                            }} else {{
                                badge.style.left = (r.left + window.scrollX) + 'px';
                                badge.style.top = (r.top + window.scrollY) + 'px';
                                document.body.appendChild(badge);
                            }}
                        }}
                    }}

                    visible.push(item);
                }}
                return visible;
            }})()
        """
        
        raw_items: List[Dict[str, Any]] = await page.evaluate(script)
        
        # Format as compact JSON string for model input
        json_str = json.dumps(raw_items, indent=2)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        tokens = self.estimate_tokens(json_str)
        
        metadata = {
            "extractor": self.name,
            "extraction_ms": round(elapsed_ms, 2),
            "element_count": len(raw_items),
            "char_count": len(json_str),
            "token_estimate": tokens
        }
        return json_str, metadata
