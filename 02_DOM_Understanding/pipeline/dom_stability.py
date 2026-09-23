"""
Post-action stabilization and quiescence for browser agents.

Fixes the failure mode where the agent executes the next command while the
page is mid-navigation or mid-DOM-mutation and extracted badges are stale.

Pattern: after any action that might trigger navigation or async DOM updates
(click, submit, type+Enter), race a navigation event against a MutationObserver
"quiet window" signal (bounded by a hard timeout ceiling), then re-run the extractor.
"""

import asyncio
from typing import Callable, Coroutine, Any, Tuple, Dict, Optional
from playwright.async_api import Page

# Injected into the page: resolves once no DOM mutations have occurred for
# `quiet_ms` milliseconds, or after `timeout_ms` regardless (safety ceiling).
QUIESCENCE_JS = """
([quietMs, timeoutMs]) => new Promise((resolve) => {
  let timer;
  const done = () => {
    if (observer) {
      try { observer.disconnect(); } catch (e) {}
    }
    resolve(true);
  };
  const reset = () => {
    clearTimeout(timer);
    timer = setTimeout(done, quietMs);
  };

  const observer = new MutationObserver(reset);
  try {
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    reset();
  } catch (e) {
    done();
  }

  setTimeout(done, timeoutMs); // hard ceiling regardless of ongoing mutations
})
"""


async def wait_for_stable(page: Page, quiet_ms: int = 300, timeout_ms: int = 4000):
    """Wait for DOM mutations to quiet down, capped at timeout_ms total."""
    try:
        await page.evaluate(QUIESCENCE_JS, [quiet_ms, timeout_ms])
    except Exception:
        pass


async def act_and_reindex(
    page: Page,
    action_coro: Coroutine,
    extractor: Any,
    nav_timeout_ms: int = 3500,
    quiet_ms: int = 300,
    quiet_timeout_ms: int = 4000,
) -> Tuple[str, Dict[str, Any]]:
    """
    Run `action_coro` (e.g. page.click(selector)), then race:
      - a navigation event ('framenavigated' or 'load'), or
      - DOM quiescence (no mutations for quiet_ms)
    whichever resolves first -- then re-extract the DOM before returning.

    This is the wrapper every agent action (click/type/press Enter) should
    go through, closing the "stale badges after navigation" gap.
    """
    nav_wait = page.wait_for_event("framenavigated", timeout=nav_timeout_ms)
    quiescence_wait = wait_for_stable(page, quiet_ms=quiet_ms, timeout_ms=quiet_timeout_ms)

    # Trigger action
    await action_coro

    done, pending = await asyncio.wait(
        [asyncio.create_task(nav_wait), asyncio.create_task(quiescence_wait)],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # If navigation fired, wait for DOM content loaded and a short follow-up quiet window
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=nav_timeout_ms)
    except Exception:
        pass

    await wait_for_stable(page, quiet_ms=200, timeout_ms=1500)

    # Return freshly extracted DOM representation and metadata
    return await extractor.extract(page)


async def click_and_reindex(
    page: Page,
    index: int,
    extractor: Any,
    quiet_ms: int = 300,
    timeout_ms: int = 4000
) -> Tuple[str, Dict[str, Any]]:
    """Click a badge-indexed element and stabilize+reindex."""
    selector = f'[data-agent-index="{index}"]'
    el = page.locator(selector).first
    return await act_and_reindex(page, el.click(), extractor, quiet_ms=quiet_ms, quiet_timeout_ms=timeout_ms)


async def search_and_reindex(
    page: Page,
    index_or_selector: Any,
    query: str,
    extractor: Any,
    quiet_ms: int = 300,
    timeout_ms: int = 4000
) -> Tuple[str, Dict[str, Any]]:
    """Type into a search box, press Enter, and stabilize+reindex the results."""
    if isinstance(index_or_selector, int):
        selector = f'[data-agent-index="{index_or_selector}"]'
    else:
        selector = str(index_or_selector)

    async def do_search():
        el = page.locator(selector).first
        await el.fill("")
        await el.type(query, delay=35)
        await el.press("Enter")

    return await act_and_reindex(page, do_search(), extractor, quiet_ms=quiet_ms, quiet_timeout_ms=timeout_ms)
