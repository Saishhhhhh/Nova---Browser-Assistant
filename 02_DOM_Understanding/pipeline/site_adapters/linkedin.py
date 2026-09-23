"""
LinkedIn Site Adapter.
Handles fast-path URL search, jobs search, and direct section navigation.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class LinkedInAdapter(BaseSiteAdapter):
    name = "LinkedIn"
    domains = ["linkedin.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. Jobs Search
        m_jobs = re.search(r"^(?:search\s+(?:for\s+)?jobs?|find\s+jobs?)\s+(.+?)$", cmd)
        if m_jobs:
            raw_query = m_jobs.group(1).strip().strip('"\'')
            url = f"https://www.linkedin.com/jobs/search/?keywords={urllib.parse.quote_plus(raw_query)}"
            return {
                "status": "found",
                "action": "url_navigate",
                "url": url,
                "target": None,
                "reply": f"Searching LinkedIn Jobs for '{raw_query}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 2. General Search
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+linkedin)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "profile", "jobs"):
                url = f"https://www.linkedin.com/search/results/all/?keywords={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching LinkedIn for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 3. Direct Section Navigation
        SECTIONS = [
            (r"\b(feed|home|go\s+to\s+feed)\b", "https://www.linkedin.com/feed/", "Opening LinkedIn feed."),
            (r"\b(messages?|messaging|dms?)\b", "https://www.linkedin.com/messaging/", "Opening LinkedIn messages."),
            (r"\b(notifications|my\s+notifications)\b", "https://www.linkedin.com/notifications/", "Opening LinkedIn notifications."),
            (r"\b(jobs|go\s+to\s+jobs)\b", "https://www.linkedin.com/jobs/", "Opening LinkedIn jobs."),
            (r"\b(my\s+network|network|connections)\b", "https://www.linkedin.com/mynetwork/", "Opening your network."),
            (r"\b(my\s+profile|profile|view\s+profile)\b", "https://www.linkedin.com/in/me/", "Opening your LinkedIn profile.")
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
