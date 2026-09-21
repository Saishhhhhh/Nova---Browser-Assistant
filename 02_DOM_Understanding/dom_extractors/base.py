"""
Base class for DOM representation extractors.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
from playwright.async_api import Page


class BaseDOMExtractor(ABC):
    name: str = "base"

    @abstractmethod
    async def extract(self, page: Page) -> Tuple[str, Dict[str, Any]]:
        """
        Extracts the DOM representation from the given Playwright page.
        Returns:
            - representation_string: The formatted prompt payload string.
            - metadata: Metrics including extraction_ms, token_estimate, element_count, etc.
        """
        pass

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate: ~4 chars per token for English / HTML."""
        return max(1, len(text) // 4)
