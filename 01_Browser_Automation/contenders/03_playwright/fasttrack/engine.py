"""
Fast-Track Playwright Engine.
Manages a persistent headed Chrome browser, visual element highlighting, and high-speed shortcuts.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


HIGHLIGHTER_SCRIPT = """
(() => {
    if (window.__highlighter_installed) return;
    window.__highlighter_installed = true;

    // Inject styles
    const style = document.createElement('style');
    style.id = '__agent_highlighter_style';
    style.textContent = `
        .__agent_highlight_box {
            position: absolute !important;
            border: 2.5px solid #10b981 !important;
            background: rgba(16, 185, 129, 0.18) !important;
            border-radius: 6px !important;
            pointer-events: none !important;
            z-index: 2147483647 !important;
            transition: all 0.2s ease-out !important;
            box-shadow: 0 0 16px rgba(16, 185, 129, 0.5) !important;
        }
        .__agent_action_badge {
            position: fixed !important;
            top: 16px !important;
            right: 16px !important;
            background: #0f172a !important;
            color: #38bdf8 !important;
            border: 1.5px solid #38bdf8 !important;
            padding: 8px 16px !important;
            border-radius: 8px !important;
            font-family: system-ui, sans-serif !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            z-index: 2147483647 !important;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4) !important;
            transition: opacity 0.3s ease !important;
        }
        .__agent_ripple {
            position: absolute !important;
            width: 32px !important;
            height: 32px !important;
            border-radius: 50% !important;
            background: rgba(56, 189, 248, 0.6) !important;
            transform: translate(-50%, -50%) scale(0.5) !important;
            pointer-events: none !important;
            z-index: 2147483647 !important;
            animation: __agent_ripple_anim 0.6s ease-out forwards !important;
        }
        @keyframes __agent_ripple_anim {
            to {
                transform: translate(-50%, -50%) scale(2.5);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);

    window.__showBadge = (text) => {
        let b = document.getElementById('__agent_badge');
        if (!b) {
            b = document.createElement('div');
            b.id = '__agent_badge';
            b.className = '__agent_action_badge';
            document.body.appendChild(b);
        }
        b.textContent = text;
        b.style.opacity = '1';
        clearTimeout(window.__badge_timer);
        window.__badge_timer = setTimeout(() => {
            if (b) b.style.opacity = '0';
        }, 2000);
    };

    window.__highlightElement = (selector) => {
        const el = document.querySelector(selector);
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        let box = document.getElementById('__agent_box');
        if (!box) {
            box = document.createElement('div');
            box.id = '__agent_box';
            box.className = '__agent_highlight_box';
            document.body.appendChild(box);
        }
        box.style.left = (rect.left + window.scrollX) + 'px';
        box.style.top = (rect.top + window.scrollY) + 'px';
        box.style.width = rect.width + 'px';
        box.style.height = rect.height + 'px';
        box.style.display = 'block';

        // Add ripple at center
        const ripple = document.createElement('div');
        ripple.className = '__agent_ripple';
        ripple.style.left = (rect.left + window.scrollX + rect.width / 2) + 'px';
        ripple.style.top = (rect.top + window.scrollY + rect.height / 2) + 'px';
        document.body.appendChild(ripple);
        setTimeout(() => ripple.remove(), 600);

        clearTimeout(window.__box_timer);
        window.__box_timer = setTimeout(() => {
            if (box) box.style.display = 'none';
        }, 1500);

        return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    };
})();
"""


class FastPlaywrightEngine:
    def __init__(self, headed: bool = True, viewport_width: int = 1280, viewport_height: int = 800):
        self.headed = headed
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self._pw = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        print(f"\n[FastPlaywrightEngine] Launching browser (headed={self.headed})...")
        t0 = time.perf_counter()
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            channel="chrome",
            headless=not self.headed,
            args=[
                f"--window-size={self.viewport_width},{self.viewport_height}",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        self.context = await self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height}
        )
        self.page = await self.context.new_page()

        # Inject visual feedback script on every page load
        await self.context.add_init_script(HIGHLIGHTER_SCRIPT)

        t_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[FastPlaywrightEngine] Browser ready in {t_ms:.1f}ms")
        return self.page

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def notify_action(self, text: str):
        """Displays a clean status badge in the top-right corner of the browser."""
        if self.page:
            try:
                await self.page.evaluate(f"window.__showBadge && window.__showBadge({repr(text)})")
            except Exception:
                pass

    async def highlight_element(self, selector: str):
        """Visually outlines target element with animated glow."""
        if self.page:
            try:
                await self.page.evaluate(f"window.__highlightElement && window.__highlightElement({repr(selector)})")
            except Exception:
                pass

    async def click_with_visual(self, selector: str, action_desc: Optional[str] = None) -> float:
        """Visually highlights the element on screen and performs a native click."""
        t0 = time.perf_counter_ns()
        if action_desc:
            await self.notify_action(f"⚡ {action_desc}")
        await self.highlight_element(selector)
        # Brief pause for visual perception in headed mode
        await asyncio.sleep(0.12)
        await self.page.locator(selector).first.click()
        t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        return t_ms

    async def press_shortcut(self, key: str, action_desc: Optional[str] = None) -> float:
        """Dispatches an instant single-key hardware shortcut (<5ms)."""
        t0 = time.perf_counter_ns()
        if action_desc:
            await self.notify_action(f"⚡ Key [{key}]: {action_desc}")
        await self.page.keyboard.press(key)
        t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        return t_ms

    async def navigate_direct(self, url: str, wait_until: str = "domcontentloaded") -> float:
        """Performs a direct URL navigation with high-res timing."""
        t0 = time.perf_counter_ns()
        await self.page.goto(url, wait_until=wait_until)
        # Re-ensure highlighter
        try:
            await self.page.evaluate(HIGHLIGHTER_SCRIPT)
        except Exception:
            pass
        t_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
        return t_ms

    async def evaluate_js(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    async def stop(self):
        print("\n[FastPlaywrightEngine] Closing browser...")
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()
        self.browser = None
        self.page = None
        self._pw = None
