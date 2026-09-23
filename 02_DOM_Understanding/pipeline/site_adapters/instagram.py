"""
Instagram Site Adapter.
Handles fast-path URL search, profiles, Reels, and Direct Messages.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class InstagramAdapter(BaseSiteAdapter):
    name = "Instagram"
    domains = ["instagram.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. Profile Direct Navigation: "go to profile X", "open @X", "visit X's profile"
        m_prof = re.search(r"\b(?:go\s+to\s+profile|open|visit)\s+@?([a-zA-Z0-9_.]+)\b", cmd)
        if m_prof:
            username = m_prof.group(1).strip()
            if username not in ("explore", "reels", "direct", "messages", "home"):
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": f"https://www.instagram.com/{username}/",
                    "target": None,
                    "reply": f"Opening Instagram profile @{username}.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Direct Section Navigation
        SECTIONS = [
            (r"\b(reels|go\s+to\s+reels|watch\s+reels)\b", "https://www.instagram.com/reels/", "Opening Instagram Reels."),
            (r"\b(explore|discover|trending)\b", "https://www.instagram.com/explore/", "Opening Instagram Explore."),
            (r"\b(direct|messages?|dms?|inbox)\b", "https://www.instagram.com/direct/inbox/", "Opening Instagram Direct Messages."),
            (r"\b(home|feed|go\s+to\s+home)\b", "https://www.instagram.com/", "Navigating to Instagram home.")
        ]
        for pattern, url, reply in SECTIONS:
            if re.search(pattern, cmd):
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "reply": reply,
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        return None
