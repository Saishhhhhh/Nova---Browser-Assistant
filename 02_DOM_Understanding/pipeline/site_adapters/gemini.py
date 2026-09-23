"""
Gemini Site Adapter.
Handles new conversation navigation and prompt input focusing for Gemini.
"""

import re
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class GeminiAdapter(BaseSiteAdapter):
    name = "Gemini"
    domains = ["gemini.google.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 1. New Chat
        if re.search(r"\b(new\s+chat|new\s+conversation|start\s+over|reset\s+chat)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://gemini.google.com/app",
                "reply": "Starting a new Gemini conversation.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 2. Type / Ask prompt
        m_ask = re.search(r"^(?:ask|type|send|tell\s+gemini|prompt)\s+(.+)$", cmd)
        if m_ask:
            prompt_text = m_ask.group(1).strip().strip('"\'')
            return {
                "status": "found",
                "action": "type_selector",
                "selector": "rich-textarea, div[contenteditable='true'], textarea",
                "value": prompt_text,
                "press_enter": True,
                "reply": f"Submitting prompt to Gemini: '{prompt_text[:40]}...'",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
