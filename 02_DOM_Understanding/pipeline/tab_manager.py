"""
Tab Manager and Tier-0 Physical Action Router.

1. TabManager: Neutralizes target="_blank" divergence and tracks adopted popups/tabs
   in a stack so 'go back' returns cleanly to parent listings.
2. Tier-0 Physical Router: Handles physical browser actions (scroll down/up,
   page down/up, top/bottom, back, forward, reload) with 0ms SLM latency.
"""

import re
import asyncio
from typing import Optional, Tuple, Dict, Any, List
from playwright.async_api import Page, BrowserContext


PHYSICAL_PATTERNS: Dict[str, re.Pattern] = {
    "scroll_down": re.compile(r"^(?:scroll\s+down(?:\s+(?:further|more|a\s+bit|a\s+little))?|scroll\s+(?:further|more)|page\s+down|down)$", re.I),
    "scroll_up": re.compile(r"^(?:scroll\s+up(?:\s+(?:further|more|higher|a\s+bit|a\s+little))?|scroll\s+higher|page\s+up|up)$", re.I),
    "scroll_top": re.compile(r"^(?:scroll\s+to\s+(?:the\s+)?top|go\s+to\s+(?:the\s+)?top|jump\s+to\s+top|top)$", re.I),
    "scroll_bottom": re.compile(r"^(?:scroll\s+to\s+(?:the\s+)?bottom|go\s+to\s+(?:the\s+)?bottom|jump\s+to\s+bottom|bottom)$", re.I),
    "go_back": re.compile(r"^(?:go\s+back|back|previous\s+page|return)$", re.I),
    "go_forward": re.compile(r"^(?:go\s+forward|forward|next\s+page)$", re.I),
    "refresh": re.compile(r"^(?:refresh|reload|refresh\s+page|reload\s+page)$", re.I),
}


def match_tier0_physical_action(command: str) -> Optional[str]:
    """Matches command against Tier-0 physical browser controls with 0ms LLM latency."""
    clean = command.strip().lower()
    for action_key, pattern in PHYSICAL_PATTERNS.items():
        if pattern.match(clean):
            return action_key
    return None


class TabManager:
    """Tracks active page and provides tab history stack for window.open() popups."""

    def __init__(self, context: BrowserContext, initial_page: Page):
        self.context = context
        self.active_page = initial_page
        self.tab_history: List[Page] = []
        self._setup_listeners()

    def _setup_listeners(self):
        def on_new_page(new_page: Page):
            if new_page != self.active_page and new_page not in self.tab_history:
                self.tab_history.append(self.active_page)
                self.active_page = new_page
                print(f"  📑 [TabManager] Adopted newly opened tab: {new_page.url or 'new tab'}")

                def on_close():
                    if self.active_page == new_page and self.tab_history:
                        self.active_page = self.tab_history.pop()
                        print(f"  📑 [TabManager] Tab closed, reverted active tab to: {self.active_page.url}")
                new_page.on("close", on_close)

        self.context.on("page", on_new_page)

    async def go_back(self) -> Page:
        """Pops previous tab if we adopted one, else performs native page.go_back()."""
        if self.tab_history:
            prev_page = self.tab_history.pop()
            try:
                await self.active_page.close()
            except Exception:
                pass
            self.active_page = prev_page
            await self.active_page.bring_to_front()
            print("  🔙 [TabManager] Closed tab and returned to previous page.")
            return self.active_page
        else:
            await self.active_page.go_back()
            print("  🔙 [Native] Executed page.go_back().")
            return self.active_page

    async def go_forward(self) -> Page:
        await self.active_page.go_forward()
        return self.active_page

    async def reload(self) -> Page:
        await self.active_page.reload()
        return self.active_page


async def execute_physical_action(
    action_type: str,
    page: Page,
    tab_manager: Optional[TabManager] = None,
    extractor: Any = None
) -> Dict[str, Any]:
    """Executes physical browser control directly without calling any SLM."""
    if action_type == "scroll_down":
        await page.evaluate("window.scrollBy({ top: 650, behavior: 'smooth' })")
        await asyncio.sleep(0.4)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "scroll",
            "direction": "down",
            "reply": "Scrolled down.",
            "is_tier0": True
        }

    elif action_type == "scroll_up":
        await page.evaluate("window.scrollBy({ top: -650, behavior: 'smooth' })")
        await asyncio.sleep(0.4)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "scroll",
            "direction": "up",
            "reply": "Scrolled up.",
            "is_tier0": True
        }

    elif action_type == "scroll_bottom":
        await page.evaluate("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })")
        await asyncio.sleep(0.5)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "scroll",
            "direction": "bottom",
            "reply": "Scrolled to page bottom.",
            "is_tier0": True
        }

    elif action_type == "scroll_top":
        await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
        await asyncio.sleep(0.4)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "scroll",
            "direction": "top",
            "reply": "Scrolled to top.",
            "is_tier0": True
        }

    elif action_type == "go_back":
        if tab_manager:
            active = await tab_manager.go_back()
        else:
            await page.go_back()
            active = page
        await asyncio.sleep(0.5)
        if extractor:
            await extractor.extract(active)
        return {
            "action": "nav",
            "direction": "back",
            "reply": "Navigated back.",
            "is_tier0": True
        }

    elif action_type == "go_forward":
        await page.go_forward()
        await asyncio.sleep(0.5)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "nav",
            "direction": "forward",
            "reply": "Navigated forward.",
            "is_tier0": True
        }

    elif action_type == "refresh":
        await page.reload()
        await asyncio.sleep(0.5)
        if extractor:
            await extractor.extract(page)
        return {
            "action": "nav",
            "direction": "refresh",
            "reply": "Page refreshed.",
            "is_tier0": True
        }

    return {"action": "unknown", "is_tier0": True}
