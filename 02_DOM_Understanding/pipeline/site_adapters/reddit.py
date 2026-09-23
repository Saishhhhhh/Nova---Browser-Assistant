"""
Reddit Site Adapter.
Handles subreddit URL navigation, direct search, and Reddit J/K/A/Z keyboard shortcuts.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class RedditAdapter(BaseSiteAdapter):
    name = "Reddit"
    domains = ["reddit.com", "old.reddit.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. Subreddit Direct Navigation: "go to r/technology" or "open subreddit gaming"
        m_sub = re.search(r"\b(?:go\s+to|open|visit)\s+(?:r/|subreddit\s+)([a-zA-Z0-9_]+)\b", cmd)
        if m_sub:
            sub = m_sub.group(1).strip()
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.reddit.com/r/{sub}/",
                "target": None,
                "reply": f"Opening subreddit r/{sub}.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 2. URL Direct Search
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+reddit)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "post", "subreddit"):
                url = f"https://www.reddit.com/search/?q={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Reddit for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 3. Reddit Keyboard Shortcuts
        KEYBOARD_SHORTCUTS = [
            (r"\b(next\s+post|next)\b", "j", "Moving to next post."),
            (r"\b(previous\s+post|prev\s+post|back\s+post)\b", "k", "Moving to previous post."),
            (r"\b(upvote|like\s+post)\b", "a", "Upvoting post."),
            (r"\b(downvote|dislike\s+post)\b", "z", "Downvoting post."),
            (r"\b(open\s+post|expand\s+post|view\s+comments)\b", "Enter", "Opening post."),
            (r"\b(save\s+post|save)\b", "s", "Saving post."),
            (r"\b(reply|comment)\b", "r", "Opening reply field."),
            (r"\b(new\s+post|create\s+post)\b", "c", "Creating new post.")
        ]

        for pattern, key, reply in KEYBOARD_SHORTCUTS:
            if re.search(pattern, cmd):
                return {
                    "status": "found",
                    "action": "keyboard",
                    "key": key,
                    "reply": reply,
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        if any(p in cmd for p in ("go to home", "homepage", "open home")):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.reddit.com",
                "reply": "Navigating to Reddit home.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
