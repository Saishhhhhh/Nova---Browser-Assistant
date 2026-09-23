"""
Cinejoy Site Adapter.
Routes searches and site access dynamically via Google Search to gracefully handle
domain rotations (cinejoy.lol, cinejoy.to, etc.), while handling media playback directly.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from .base import BaseSiteAdapter


class CinejoyAdapter(BaseSiteAdapter):
    name = "Cinejoy"
    domains = ["cinejoy"]  # Partial match on hostname or title

    def matches(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        return "cinejoy" in (parsed.netloc or "").lower()

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. Search Cinejoy via Google (immune to domain changes)
        m_search = re.search(r"^(?:search(?:\s+for)?|find|watch|play|stream)\s+(.+?)(?:\s+(?:on|in)\s+cinejoy)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("movie", "film", "stream", "video", "cinejoy"):
                search_query = f"cinejoy {raw_query}"
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(search_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Google for '{raw_query}' on Cinejoy.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Open Cinejoy via Google Search
        if any(p in cmd for p in ("open cinejoy", "go to cinejoy", "visit cinejoy")):
            url = "https://www.google.com/search?q=cinejoy+movies&btnI=1"
            return {
                "status": "found",
                "action": "url_navigate",
                "url": url,
                "reply": "Opening Cinejoy via Google.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. Media Controls when on a video page
        if re.search(r"\b(play|pause|resume|stop)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": "Space",
                "focus_selector": "video, #player, iframe",
                "reply": "Toggling video playback.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(fullscreen|full screen|maximize)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": "f",
                "focus_selector": "video, #player, iframe",
                "reply": "Toggling fullscreen on Cinejoy.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
