"""
Base interface for site-specific fast-path adapters.
Adapters allow known priority domains to execute common voice actions (search, play,
pause, navigate, keyboard shortcuts) in 0-50ms without DOM parsing or SLM queries.
"""

from typing import List, Dict, Any, Optional
from urllib.parse import urlparse


class BaseSiteAdapter:
    name: str = "BaseAdapter"
    domains: List[str] = []

    def matches(self, url: str) -> bool:
        if not url:
            return False
        try:
            parsed = urlparse(url)
            netloc = (parsed.netloc or "").lower()
            return any(domain.lower() in netloc for domain in self.domains)
        except Exception:
            return False

    async def handle(
        self,
        page: Any,
        voice_command: str,
        tab_manager: Any = None,
        extractor: Any = None
    ) -> Optional[Dict[str, Any]]:
        """
        Processes voice command for this domain.
        Returns a pipeline response dict if handled, or None to fall through.
        """
        raise NotImplementedError
