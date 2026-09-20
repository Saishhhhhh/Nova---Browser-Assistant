"""
Fast-Track Google Search Skill.
Implements direct query URL formulation and instant organic results extraction.
"""

import time
import urllib.parse
from typing import Dict, Any, List
from ..engine import FastPlaywrightEngine


class GoogleSkill:
    def __init__(self, engine: FastPlaywrightEngine):
        self.engine = engine

    async def search(self, query: str) -> float:
        """Searches Google quickly while avoiding automated traffic blocks."""
        t0 = time.perf_counter_ns()
        await self.engine.notify_action(f"Google Search: '{query}'")
        await self.engine.navigate_direct("https://www.google.com")

        # Dismiss cookie consent if present
        try:
            consent = self.engine.page.locator(
                "button:has-text('Accept all'), button:has-text('I agree'), button:has-text('Reject all'), button:has-text('Tout accepter')"
            )
            if await consent.count() > 0:
                await consent.first.click(timeout=1000)
        except Exception:
            pass

        search_box = self.engine.page.locator("textarea[name='q'], input[name='q']")
        await search_box.first.wait_for(state="visible", timeout=4000)
        await search_box.first.fill(query)
        await search_box.first.press("Enter")

        try:
            await self.engine.page.wait_for_selector("#search h3, #rso h3, div.g h3, h3", state="visible", timeout=5000)
        except Exception:
            pass

        total_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        return total_ms

    async def extract_results(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Pulls top organic search results in <20ms."""
        try:
            await self.engine.page.wait_for_selector(
                "h3",
                state="visible",
                timeout=5000
            )
        except Exception:
            pass

        results = await self.engine.evaluate_js(f"""
            (() => {{
                const allH3 = Array.from(document.querySelectorAll("h3"));
                const valid = [];
                for (const h of allH3) {{
                    const anchor = h.closest('a') || h.querySelector('a') || h.parentElement?.closest('a');
                    const text = (h.textContent || '').trim();
                    if (!text || text.length < 3) continue;
                    const href = anchor ? anchor.href : '';
                    if (href && (href.includes('google.com/search') || href.includes('support.google'))) continue;
                    const snippetContainer = h.closest('div.g') || h.closest('[data-hveid]') || h.parentElement;
                    const snippet = snippetContainer ? (snippetContainer.innerText || '').slice(0, 150) : '';
                    valid.push({{
                        title: text,
                        link: href,
                        snippet: snippet.replace(/[\\r\\n]+/g, ' ')
                    }});
                    if (valid.length >= {limit}) break;
                }}
                // Fallback: if no valid items, take all non-empty h3s
                if (valid.length === 0) {{
                    for (const h of allH3) {{
                        const text = (h.textContent || '').trim();
                        if (text && text.length > 3) {{
                            valid.push({{ title: text, link: '', snippet: '' }});
                            if (valid.length >= {limit}) break;
                        }}
                    }}
                }}
                return valid.map((item, idx) => ({{ ...item, index: idx + 1 }}));
            }})()
        """)

        # Highlight top result if found
        try:
            await self.engine.highlight_element("h3")
        except Exception:
            pass

        return results or []
