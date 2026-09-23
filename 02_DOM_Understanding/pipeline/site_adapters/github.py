"""
GitHub Site Adapter.
Handles fast-path URL search, repository sections (Issues, PRs, Code), and keyboard shortcuts.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from .base import BaseSiteAdapter


class GitHubAdapter(BaseSiteAdapter):
    name = "GitHub"
    domains = ["github.com"]

    def _get_repo_base(self, url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) >= 2 and parts[0] not in ("settings", "notifications", "search", "explore", "trending"):
                return f"https://github.com/{parts[0]}/{parts[1]}"
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
        repo_base = self._get_repo_base(page.url if page else "")

        # 1. Direct Search
        m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+?)(?:\s+(?:on|in)\s+github)?$", cmd)
        if m_search:
            raw_query = m_search.group(1).strip().strip('"\'')
            if raw_query and raw_query not in ("bar", "box", "search bar", "code", "repo", "repository"):
                url = f"https://github.com/search?q={urllib.parse.quote_plus(raw_query)}"
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": url,
                    "target": None,
                    "reply": f"Searching GitHub for '{raw_query}'.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

        # 2. Repo Section Navigation
        if re.search(r"\b(issues|go\s+to\s+issues|open\s+issues)\b", cmd):
            if repo_base:
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": f"{repo_base}/issues",
                    "reply": "Opening repo Issues.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }
            return {
                "status": "found",
                "action": "keyboard",
                "keys": ["g", "i"],
                "reply": "Navigating to Issues.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(pull\s+requests|prs|go\s+to\s+prs)\b", cmd):
            if repo_base:
                return {
                    "status": "found",
                    "action": "url_navigate",
                    "url": f"{repo_base}/pulls",
                    "reply": "Opening Pull Requests.",
                    "is_adapter_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }
            return {
                "status": "found",
                "action": "keyboard",
                "keys": ["g", "p"],
                "reply": "Navigating to Pull Requests.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(notifications|my\s+notifications)\b", cmd):
            return {
                "status": "found",
                "action": "url_navigate",
                "url": "https://github.com/notifications",
                "reply": "Opening your GitHub notifications.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        # 3. File Finder & Command Palette
        if re.search(r"\b(file\s+finder|find\s+file|search\s+files)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": "t",
                "reply": "Opening GitHub file finder.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(command\s+palette)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": "Control+k",
                "reply": "Opening command palette.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        if re.search(r"\b(open\s+in\s+vscode|open\s+in\s+editor|web\s+editor)\b", cmd):
            return {
                "status": "found",
                "action": "keyboard",
                "key": ".",
                "reply": "Launching github.dev in-browser editor.",
                "is_adapter_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

        return None
