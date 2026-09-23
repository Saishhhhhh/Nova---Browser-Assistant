"""
Site Adapters Registry.
Maintains domain adapters for priority sites and resolves fast-path actions.
"""

import re
import urllib.parse
from typing import List, Optional, Dict, Any

from .base import BaseSiteAdapter
from .youtube import YouTubeAdapter
from .amazon import AmazonAdapter
from .flipkart import FlipkartAdapter
from .reddit import RedditAdapter
from .gmail import GmailAdapter
from .google_search import GoogleSearchAdapter
from .github import GitHubAdapter
from .linkedin import LinkedInAdapter
from .instagram import InstagramAdapter
from .chatgpt import ChatGPTAdapter
from .claude_ai import ClaudeAdapter
from .gemini import GeminiAdapter
from .cinejoy import CinejoyAdapter
from .gogoanime import GoGoAnimeAdapter

# Registered priority adapters in lookup order
ALL_ADAPTERS: List[BaseSiteAdapter] = [
    YouTubeAdapter(),
    AmazonAdapter(),
    FlipkartAdapter(),
    RedditAdapter(),
    GmailAdapter(),
    GoogleSearchAdapter(),
    GitHubAdapter(),
    LinkedInAdapter(),
    InstagramAdapter(),
    ChatGPTAdapter(),
    ClaudeAdapter(),
    GeminiAdapter(),
    CinejoyAdapter(),
    GoGoAnimeAdapter()
]


def get_adapter(url: str) -> Optional[BaseSiteAdapter]:
    """Finds the adapter matching the current page URL."""
    if not url:
        return None
    for adapter in ALL_ADAPTERS:
        if adapter.matches(url):
            return adapter
    return None


def match_cross_site_intent(voice_command: str) -> Optional[Dict[str, Any]]:
    """
    Detects if the user wants to navigate to or search on a priority site from ANY page.
    Enables global voice commands like "search 24 inch monitor on amazon" or "watch interstellar on cinejoy".
    """
    cmd = voice_command.strip().lower()

    # 1. Cinejoy & GoGoAnime (routed via Google Search per user specification)
    if "cinejoy" in cmd:
        m = re.search(r"^(?:search(?:\s+for)?|find|watch|stream|play)?\s*(.+?)\s*(?:on|in|from)?\s*cinejoy$", cmd)
        query = m.group(1).strip() if m else ""
        if query and query not in ("open", "go to", "visit"):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus('cinejoy ' + query)}",
                "reply": f"Searching Google for '{query}' on Cinejoy.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://www.google.com/search?q=cinejoy+movies&btnI=1",
            "reply": "Opening Cinejoy via Google.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if "gogoanime" in cmd:
        m = re.search(r"^(?:search(?:\s+for)?|find|watch|stream|play)?\s*(.+?)\s*(?:on|in|from)?\s*gogoanime$", cmd)
        query = m.group(1).strip() if m else ""
        if query and query not in ("open", "go to", "visit"):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus('gogoanime ' + query)}",
                "reply": f"Searching Google for '{query}' on GoGoAnime.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://www.google.com/search?q=gogoanime+watch+anime&btnI=1",
            "reply": "Opening GoGoAnime via Google.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    # 2. YouTube
    if "youtube" in cmd:
        m = re.search(r"^(?:search(?:\s+for)?|find|watch|play)\s+(.+?)\s+(?:on|in)\s+youtube$", cmd)
        if m:
            q = m.group(1).strip()
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}",
                "reply": f"Searching YouTube for '{q}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }
        if re.search(r"\b(open|go\s+to|visit)\s+youtube\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.youtube.com",
                "reply": "Opening YouTube.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # 3. Amazon
    if "amazon" in cmd:
        m = re.search(r"^(?:search(?:\s+for)?|find|buy)\s+(.+?)\s+(?:on|in)\s+amazon$", cmd)
        if m:
            q = m.group(1).strip()
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.amazon.in/s?k={urllib.parse.quote_plus(q)}",
                "reply": f"Searching Amazon for '{q}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }
        if re.search(r"\b(open|go\s+to|visit)\s+amazon\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.amazon.in",
                "reply": "Opening Amazon.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # 4. Flipkart
    if "flipkart" in cmd:
        m = re.search(r"^(?:search(?:\s+for)?|find|buy)\s+(.+?)\s+(?:on|in)\s+flipkart$", cmd)
        if m:
            q = m.group(1).strip()
            return {
                "status": "found",
                "action": "url_navigate",
                "url": f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(q)}",
                "reply": f"Searching Flipkart for '{q}'.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }
        if re.search(r"\b(open|go\s+to|visit)\s+flipkart\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.flipkart.com",
                "reply": "Opening Flipkart.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # 5. Gmail
    if "gmail" in cmd:
        if re.search(r"\b(open|go\s+to|visit|check)\s+gmail\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://mail.google.com/mail/u/0/#inbox",
                "reply": "Opening Gmail.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # 6. Google Search
    m_google = re.search(r"^(?:google|search\s+google\s+for|search\s+on\s+google\s+for)\s+(.+)$", cmd)
    if m_google:
        q = m_google.group(1).strip()
        return {
            "status": "found",
            "action": "url_navigate",
            "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}",
            "reply": f"Googling '{q}'.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    # 7. AI Assistants: ChatGPT, Claude, Gemini
    if re.search(r"\b(open|go\s+to)\s+chatgpt\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://chatgpt.com/",
            "reply": "Opening ChatGPT.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if re.search(r"\b(open|go\s+to)\s+claude\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://claude.ai/new",
            "reply": "Opening Claude.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if re.search(r"\b(open|go\s+to)\s+gemini\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://gemini.google.com/app",
            "reply": "Opening Google Gemini.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    # 8. GitHub, Reddit, LinkedIn, Instagram
    if re.search(r"\b(open|go\s+to)\s+github\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://github.com",
            "reply": "Opening GitHub.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if re.search(r"\b(open|go\s+to)\s+reddit\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://www.reddit.com",
            "reply": "Opening Reddit.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if re.search(r"\b(open|go\s+to)\s+linkedin\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://www.linkedin.com/feed/",
            "reply": "Opening LinkedIn.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    if re.search(r"\b(open|go\s+to)\s+instagram\b", cmd):
        return {
            "status": "found",
            "action": "url_navigate",
            "url": "https://www.instagram.com/",
            "reply": "Opening Instagram.",
            "is_adapter_fastpath": True,
            "total_ms": 0.0,
            "is_valid_json": True
        }

    return None
