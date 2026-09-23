"""
Gmail Site Adapter.
Handles fast-path URL search, navigation (Inbox, Sent, Drafts), compose, and
Gmail keyboard shortcuts (C, R, A, F, E, #, J, K, etc.) with auto-enablement support.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from .base import BaseSiteAdapter


class GmailAdapter(BaseSiteAdapter):
    name = "Gmail"
    domains = ["mail.google.com"]

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        cmd = voice_command.strip().lower()

        # 0. User requested: "enable shortcuts" / "turn on keyboard shortcuts"
        if re.search(r"\b(?:enable|turn\s+on|activate)\s+(?:the\s+)?(?:gmail\s+)?shortcuts\b", cmd):
            # Press '?' in Gmail to open shortcuts help modal, which has an "Enable" link if disabled
            return {
                "status": "found",
                "action": "keyboard",
                "key": "?",
                "reply": "Opening Gmail keyboard shortcuts dialog. Click 'Enable' to activate shortcuts.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 1. URL Direct Search (100% reliable, no shortcut toggle needed)
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:in|on)\s+gmail|\s+emails?)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "email", "mail"):
                url = f"https://mail.google.com/mail/u/0/#search/{urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching Gmail for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Section Navigation via Direct URLs (Instant & infallible)
        NAV_URLS = [
            (r"\b(inbox|go\s+to\s+inbox|open\s+inbox)\b", "https://mail.google.com/mail/u/0/#inbox", "Navigating to Gmail Inbox."),
            (r"\b(sent|sent\s+emails|go\s+to\s+sent)\b", "https://mail.google.com/mail/u/0/#sent", "Navigating to Sent Mail."),
            (r"\b(drafts|go\s+to\s+drafts)\b", "https://mail.google.com/mail/u/0/#drafts", "Navigating to Drafts."),
            (r"\b(starred|starred\s+emails)\b", "https://mail.google.com/mail/u/0/#starred", "Navigating to Starred emails."),
            (r"\b(trash|bin|deleted\s+items)\b", "https://mail.google.com/mail/u/0/#trash", "Navigating to Trash."),
            (r"\b(spam|junk)\b", "https://mail.google.com/mail/u/0/#spam", "Navigating to Spam.")
        ]
        for pattern, url, reply in NAV_URLS:
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

        # 3. Compose (Primary: Click Compose button; Secondary: Press C)
        if re.search(r"\b(compose|new\s+email|write\s+an?\s+email|new\s+message)\b", cmd):
            return {
                "status": "found",
                "action": "click_selector",
                "selector": "div[role='button'][gh='cm'], .T-I.T-I-KE.L3, div.T-I-KE",
                "reply": "Opening compose window.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 4. Email Action Keyboard Shortcuts
        KEYBOARD_SHORTCUTS = [
            (r"\b(reply\s+all)\b", "a", "Replying to all."),
            (r"\b(reply)\b", "r", "Opening reply field."),
            (r"\b(forward)\b", "f", "Forwarding email."),
            (r"\b(archive)\b", "e", "Archiving conversation."),
            (r"\b(delete|trash\s+this|remove\s+email)\b", "#", "Deleting email."),
            (r"\b(star|unstar)\b", "s", "Toggling star status."),
            (r"\b(mark\s+as\s+unread)\b", "Shift+U", "Marking email as unread."),
            (r"\b(mark\s+as\s+read)\b", "Shift+I", "Marking email as read."),
            (r"\b(next\s+email|next\s+thread)\b", "j", "Navigating to next email."),
            (r"\b(previous\s+email|prev\s+email)\b", "k", "Navigating to previous email."),
            (r"\b(back\s+to\s+inbox|back\s+to\s+list)\b", "u", "Returning to thread list."),
            (r"\b(send|send\s+email)\b", "Control+Enter", "Sending email.")
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

        return None
