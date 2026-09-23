"""
Flipkart Site Adapter.
Handles fast-path URL search, cart/buy actions, and dismisses login overlays.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class FlipkartAdapter(BaseSiteAdapter):
    name = "Flipkart"
    domains = ["flipkart.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. URL Direct Search
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+flipkart)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "product", "item"):
                url = f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Flipkart for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Add to Cart / Buy Now
        if re.search(r"\b(add\s+to\s+cart|put\s+in\s+cart)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "button:has-text('ADD TO CART'), button._2KpZ6l._2U9uOA",
                "reply": "Adding item to your Flipkart cart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(buy\s+now|instant\s+checkout)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "button:has-text('BUY NOW'), button._2KpZ6l._2UUcR8",
                "reply": "Proceeding with Buy Now on Flipkart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. Direct Navigation
        if re.search(r"\b(go\s+to\s+cart|open\s+cart|view\s+cart|my\s+cart)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.flipkart.com/viewcart",
                "reply": "Opening your Flipkart cart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(my\s+orders|order\s+history|go\s+to\s+orders)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.flipkart.com/account/orders",
                "reply": "Opening your Flipkart orders.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if any(p in cmd for p in ("go to home", "homepage", "open home")):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.flipkart.com",
                "reply": "Navigating to Flipkart home.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
