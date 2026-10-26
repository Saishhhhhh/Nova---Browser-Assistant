"""Launches Brave using the user's real profile, so Nova acts on your actual logged-in browser - your
bookmarks, your saved logins, your extensions - instead of a disposable automation instance.

Brave must be closed before starting Nova: Chromium profiles are locked to one running process at a time,
and (confirmed by reading browser_use's own profile.py) Brave's profile is launched directly rather than
auto-copied to a safe temp copy first, the way Chrome's is. That's what makes it genuinely "your" browser
instead of a sandboxed clone - the trade-off is that a second Brave process can't open the same profile.
"""
import asyncio

from browser_use import Browser

from . import config

LAUNCH_TIMEOUT_S = 15.0   # confirmed live: when the profile is already locked, browser_use doesn't fail fast -
                          # it retries and can fall back toward a cloud-browser attempt that just hangs. A hard
                          # timeout turns that hang into a clean, fast failure with the real cause below.


async def launch() -> Browser:
    browser = Browser(
        executable_path=config.BRAVE_EXECUTABLE_PATH,
        user_data_dir=config.BRAVE_USER_DATA_DIR,
        profile_directory=config.BRAVE_PROFILE_DIRECTORY,
        headless=False, no_viewport=True, keep_alive=True,
    )
    try:
        await asyncio.wait_for(browser.start(), timeout=LAUNCH_TIMEOUT_S)
    except Exception as e:
        # Confirmed live: a Brave process already holding this profile doesn't report a clean "already
        # running" error - the new process just exits almost immediately and browser-use reports it as
        # "exited before CDP became available", which looks identical to Brave failing to start at all.
        # In practice, with a live profile, an already-open Brave is overwhelmingly the likely cause, so
        # ANY launch failure (or timeout) here gets the friendly message, with the real error kept for debugging.
        from .identity import BRAVE_ALREADY_OPEN
        raise RuntimeError(f"{BRAVE_ALREADY_OPEN}\n(underlying error: {type(e).__name__}: {str(e)[:150]})") from e
    return browser
