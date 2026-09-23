"""
Amazon Site Adapter.
Handles fast-path URL search, direct add-to-cart/buy-now CSS targets, and order/cart navigation.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from .base import BaseSiteAdapter


class AmazonAdapter(BaseSiteAdapter):
    name = "Amazon"
    domains = ["amazon.in", "amazon.com", "amazon.co.uk", "amazon.ca", "amazon.de", "amazon.fr"]

    def _get_base_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            for d in self.domains:
                if d in netloc:
                    return d
        except Exception:
            pass
        return "amazon.in"

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()
        domain = self._get_base_domain(page.url if page else "")

        # 1. URL Direct Search: "search for X" / "find X"
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+amazon)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "product", "item"):
                url = f"https://www.{domain}/s?k={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Amazon for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Add to Cart / Buy Now Direct Selectors
        if re.search(r"\b(add\s+to\s+cart|put\s+in\s+cart)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "#add-to-cart-button, input#add-to-cart-button, #submit.add-to-cart-announce",
                "reply": "Adding item to your Amazon cart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(buy\s+now|instant\s+checkout)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "#buy-now-button, input#buy-now-button",
                "reply": "Proceeding with Buy Now.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. Direct Navigation (Cart, Orders, Wishlist, Sign in)
        if re.search(r"\b(go\s+to\s+cart|open\s+cart|view\s+cart|my\s+cart)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.{domain}/gp/cart/view.html",
                "reply": "Opening your Amazon cart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(checkout|proceed\s+to\s+checkout)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "#sc-buy-box-ptc-button, #proceed-to-checkout-action, input[name='proceedToRetailCheckout']",
                "reply": "Proceeding to checkout.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(my\s+orders|order\s+history|go\s+to\s+orders)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.{domain}/gp/css/order-history",
                "reply": "Opening your Amazon order history.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(wishlist|my\s+wishlist)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.{domain}/hz/wishlist/ls",
                "reply": "Opening your Amazon wishlist.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(sign\s+in|login|log\s+in)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.{domain}/ap/signin",
                "reply": "Navigating to Amazon sign in.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if any(p in cmd for p in ("go to home", "homepage", "open home")):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.{domain}",
                "reply": "Navigating to Amazon homepage.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
