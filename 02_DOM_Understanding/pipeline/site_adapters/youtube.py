"""
YouTube Site Adapter.
Handles fast-path URL-direct searches, playback controls, and keyboard shortcuts
with zero SLM latency.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class YouTubeAdapter(BaseSiteAdapter):
    name = "YouTube"
    domains = ["youtube.com", "youtu.be"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. URL Direct Search: "search for X" / "find X" / "search X"
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+youtube)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "video", "youtube"):
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching YouTube for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Navigation shortcuts
        if any(p in cmd for p in ("go to home", "homepage", "open home")):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.youtube.com",
                "reply": "Navigating to YouTube home.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if any(p in cmd for p in ("subscriptions", "my subscriptions")):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://www.youtube.com/feed/subscriptions",
                "reply": "Opening your YouTube subscriptions.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. Direct Selectors for Like / Subscribe
        if re.search(r"\b(?:like\s+(?:this\s+)?video|like)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "like-button-view-model button, button#like-button, ytd-like-button-renderer button",
                "reply": "Liking this video.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(?:subscribe|sub)\b", cmd) and not "unsubscribe" in cmd:
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "ytd-subscribe-button-renderer button, #subscribe-button button",
                "reply": "Subscribing to channel.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3.5. Open / Play First Video
        if re.search(r"\b(?:open|play|click|watch)\s+(?:the\s+)?(?:first\s+video|first\s+result|first\s+one|video)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "ytd-video-renderer a#video-title, ytd-rich-item-renderer a#video-title, #contents ytd-thumbnail a, a#video-title",
                "reply": "Opening the first video.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 4. Playback Keyboard Shortcuts (with video focus)
        KEYBOARD_SHORTCUTS = [
            (r"\b(play|pause|resume|stop)\b", "k", "Toggling playback (play/pause)."),
            (r"\b(fullscreen|full screen|maximize|minimize|exit fullscreen)\b", "f", "Toggling fullscreen."),
            (r"\b(theater|theatre|cinema mode)\b", "t", "Toggling theater mode."),
            (r"\b(mute|unmute)\b", "m", "Toggling mute."),
            (r"\b(captions|subtitles)\b", "c", "Toggling captions/subtitles."),
            (r"\b(skip forward|skip ahead|fast forward|forward 10)\b", "l", "Skipping ahead 10 seconds."),
            (r"\b(skip back|rewind|back 10)\b", "j", "Rewinding 10 seconds."),
            (r"\b(next video|next)\b", "Shift+N", "Playing next video."),
            (r"\b(previous video|prev video)\b", "Shift+P", "Playing previous video."),
            (r"\b(speed up|faster)\b", "Shift+.", "Increasing playback speed."),
            (r"\b(slow down|slower)\b", "Shift+,", "Decreasing playback speed."),
            (r"\b(miniplayer|picture in picture)\b", "i", "Toggling miniplayer.")
        ]

        for pattern, key, reply in KEYBOARD_SHORTCUTS:
            if re.search(pattern, cmd):
                return {
                    "status": "found",
                    "action": "keyboard",
                    "key": key,
                    "focus_selector": "video, #movie_player",
                    "reply": reply,
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # Volume controls (multi-press)
        if re.search(r"\b(volume up|louder)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "keys": ["ArrowUp", "ArrowUp", "ArrowUp"],
                "focus_selector": "video, #movie_player",
                "reply": "Increasing volume.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(volume down|quieter|lower volume)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "keys": ["ArrowDown", "ArrowDown", "ArrowDown"],
                "focus_selector": "video, #movie_player",
                "reply": "Decreasing volume.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
