"""
Google Search Site Adapter.
Handles fast-path URL search, tab filtering (Images, News, Videos), and first result clicks.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from .base import BaseSiteAdapter


class GoogleSearchAdapter(BaseSiteAdapter):
    name = "GoogleSearch"
    domains = ["google.com", "google.co.in", "google.co.uk", "google.ca", "google.de"]

    def _get_current_query(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "q" in qs:
                return qs["q"][0]
        except Exception:
            pass
        return None

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()
        curr_query = self._get_current_query(page.url if page else "")

        # 1. URL Direct Search
        m_search = re.search(r"^(?:search(?:\s+for)?|google|look\s+up|find)\s+(.+?)(?:\s+(?:on|in)\s+google)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "results", "google"):
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Googling '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Tabs: Images, News, Videos
        if re.search(r"\b(images?|show\s+images?|image\s+search)\b", cmd) and curr_query:
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(curr_query)}&tbm=isch",
                "reply": f"Switching to Google Images for '{curr_query}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(news|show\s+news)\b", cmd) and curr_query:
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(curr_query)}&tbm=nws",
                "reply": f"Switching to News for '{curr_query}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(videos?|show\s+videos?)\b", cmd) and curr_query:
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(curr_query)}&tbm=vid",
                "reply": f"Switching to Videos for '{curr_query}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. First result click
        if re.search(r"\b(first\s+result|open\s+(?:the\s+)?first\s+result|click\s+(?:the\s+)?first\s+result)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "#search a:first-of-type, div.g a:first-of-type, #rso a:first-of-type",
                "reply": "Opening the first search result.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 4. Next page of results
        if re.search(r"\b(next\s+page|more\s+results)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "#pnnext, a#pnnext, span:has-text('Next')",
                "reply": "Navigating to next page of results.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
