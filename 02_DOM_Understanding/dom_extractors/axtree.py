"""
Representation B: Accessibility Tree Extractor.
Extracts semantic accessibility nodes via Playwright's CDP accessibility snapshot.
"""

import time
import json
from typing import Dict, Any, Tuple
from playwright.async_api import Page
from .base import BaseDOMExtractor


class AXTreeExtractor(BaseDOMExtractor):
    name = "axtree"

    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter_ns()
        
        # Native CDP accessibility tree
        cdp_client = await page.context.new_cdp_session(page)
        ax_data = await cdp_client.send("Accessibility.getFullAXTree")
        nodes = ax_data.get("nodes", [])
        
        lines = []
        for n in nodes[:150]:  # Cap to top 150 nodes to avoid token blowup
            role = n.get("role", {}).get("value", "")
            name = n.get("name", {}).get("value", "")
            if role in ["button", "link", "textbox", "combobox", "checkbox", "radio", "heading"]:
                lines.append(f"- {role}: {name}")

        tree_str = "\n".join(lines)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        tokens = self.estimate_tokens(tree_str)
        
        metadata = {
            "extractor": self.name,
            "extraction_ms": round(elapsed_ms, 2),
            "node_count": len(nodes),
            "char_count": len(tree_str),
            "token_estimate": tokens
        }
        return tree_str, metadata
