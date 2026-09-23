"""
GoGoAnime Site Adapter.
Routes searches and site access dynamically via Google Search to gracefully handle
domain rotations (gogoanime.pe, gogoanime.gr, etc.), while handling episode navigation
and playback directly.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from .base import BaseSiteAdapter


class GoGoAnimeAdapter(BaseSiteAdapter):
    name = "GoGoAnime"
    domains = ["gogoanime"]

    def matches(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        return "gogoanime" in (parsed.netloc or "").lower()

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. Search Anime via Google (immune to domain changes)
        m_search = re.search(r"^(?:search(?:\s+for)?|find|watch|play|stream)\s+(.+?)(?:\s+(?:on|in)\s+gogoanime)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("anime", "episode", "stream", "video", "gogoanime"):
                search_query = f"gogoanime {raw_query}"
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(search_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Google for '{raw_query}' on GoGoAnime.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Open GoGoAnime via Google Search
        if any(p in cmd for p in ("open gogoanime", "go to gogoanime", "visit gogoanime")):
            url = "https://www.google.com/search?q=gogoanime+watch+anime&btnI=1"
            return {
                "status": "found",
                "action": "url_navigate",
                "url": url,
                "reply": "Opening GoGoAnime via Google.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. Episode Navigation & Media Controls
        if re.search(r"\b(next\s+episode|next\s+ep)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": ".anime_video_body_episodes_r a, a:has-text('Next Episode')",
                "reply": "Navigating to next episode.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(previous\s+episode|prev\s+episode|prev\s+ep)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": ".anime_video_body_episodes_l a, a:has-text('Prev Episode')",
                "reply": "Navigating to previous episode.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(play|pause|resume|stop)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": "Space",
                "focus_selector": "video, #player, iframe",
                "reply": "Toggling anime playback.",
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
                "reply": "Toggling fullscreen on GoGoAnime.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
