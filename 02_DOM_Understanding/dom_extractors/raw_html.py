"""
Representation A: Pruned Raw HTML Extractor.
Extracts HTML while stripping non-semantic bloat (<script>, <style>, <svg>, comments).
"""

import time
import re
from typing import Dict, Any, Tuple
from playwright.async_api import Page
from .base import BaseDOMExtractor


class RawHTMLExtractor(BaseDOMExtractor):
    name = "raw_html"

    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter_ns()
        
        # Pull innerHTML of body
        raw = await page.evaluate("""
            (() => {
                const clone = document.body.cloneNode(true);
                // Strip scripts, styles, SVGs, iframes
                const remove = clone.querySelectorAll('script, style, svg, noscript, iframe, link');
                remove.forEach(el => el.remove());
                return clone.innerHTML;
            })()
        """)
        
        # Clean up whitespace and comments
        cleaned = re.sub(r'<!--.*?-->', '', raw, flags=re.DOTALL)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        tokens = self.estimate_tokens(cleaned)
        
        metadata = {
            "extractor": self.name,
            "extraction_ms": round(elapsed_ms, 2),
            "char_count": len(cleaned),
            "token_estimate": tokens
        }
        return cleaned, metadata
