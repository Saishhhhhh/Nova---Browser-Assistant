"""
General Hybrid Skill.
Extracts visible interactive elements in <15ms, overlays numbered badges [1], [2], [3],
and performs visual hardware clicks on any website.
"""

from typing import Dict, Any, List
from ..engine import FastPlaywrightEngine


class GeneralSkill:
    def __init__(self, engine: FastPlaywrightEngine):
        self.engine = engine

    async def get_interactive_snapshot(self) -> List[Dict[str, Any]]:
        """
        Extracts visible interactive elements in <15ms and overlays numbered badges
        directly on the live web page.
        """
        snapshot = await self.engine.evaluate_js("""
            (() => {
                // Remove previous agent badges
                document.querySelectorAll('.__agent_num_badge').forEach(b => b.remove());

                const candidates = Array.from(document.querySelectorAll(
                    'button, a[href], input, select, textarea, [role="button"], [tabindex="0"]'
                ));

                const interactive = [];
                let counter = 1;

                for (const el of candidates) {
                    if (counter > 40) break; // Limit to 40 primary targets for fast voice parsing

                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);

                    // Visibility check
                    if (rect.width < 10 || rect.height < 10 || style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') {
                        continue;
                    }
                    if (rect.bottom < 0 || rect.top > window.innerHeight) {
                        continue; // Off screen
                    }

                    const role = el.tagName.toLowerCase();
                    let label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || el.value || '').trim();
                    label = label.replace(/[\\r\\n]+/g, ' ').slice(0, 40);

                    // Inject numbered badge on screen
                    const badge = document.createElement('span');
                    badge.className = '__agent_num_badge';
                    badge.textContent = counter;
                    badge.style.cssText = `
                        position: absolute !important;
                        left: ${rect.left + window.scrollX}px !important;
                        top: ${rect.top + window.scrollY}px !important;
                        background: #f59e0b !important;
                        color: #000000 !important;
                        font-family: system-ui, sans-serif !important;
                        font-size: 11px !important;
                        font-weight: 800 !important;
                        padding: 1px 5px !important;
                        border-radius: 4px !important;
                        z-index: 2147483646 !important;
                        pointer-events: none !important;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.3) !important;
                    `;
                    document.body.appendChild(badge);

                    // Tag element for fast indexing
                    el.setAttribute('data-agent-idx', counter);

                    interactive.push({
                        index: counter,
                        tag: role,
                        text: label || '[no-label]',
                        selector: `[data-agent-idx="${counter}"]`
                    });

                    counter++;
                }

                return interactive;
            })()
        """)
        return snapshot or []

    async def click_by_index(self, index: int) -> float:
        """Visually highlights and clicks the element marked with [index]."""
        selector = f"[data-agent-idx='{index}']"
        return await self.engine.click_with_visual(selector, f"Clicking element [{index}]")

    async def type_by_index(self, index: int, text: str) -> float:
        """Types text into the input field marked with [index]."""
        selector = f"[data-agent-idx='{index}']"
        await self.engine.highlight_element(selector)
        await self.engine.notify_action(f"Typing into [{index}]: '{text}'")
        inp = self.engine.page.locator(selector).first
        await inp.fill(text)
        return 10.0
