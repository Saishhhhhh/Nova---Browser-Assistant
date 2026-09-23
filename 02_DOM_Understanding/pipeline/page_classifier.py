"""
Page State Classification and Anti-Bot Challenge Detection.

Classifies pages into NORMAL, BLOCKED, or SPARSE_SUSPECT states before any SLM call.
Prevents empty or challenged DOMs from reaching the grounding model, enforcing a
clean human-in-the-loop handoff instead of hallucinated actions.
"""

import asyncio
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from playwright.async_api import Page


class PageStatus(str, Enum):
    NORMAL = "normal"
    BLOCKED = "blocked"
    SPARSE_SUSPECT = "sparse_suspect"


class PageBlockedError(Exception):
    """Raised when the agent reaches a bot challenge, captcha, or blocked page."""
    def __init__(self, reason: str, status: PageStatus, details: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.details = details or {}


BLOCKED_STATUS_CODES = {202, 403, 503}

CHALLENGE_DETECTION_JS = """
() => {
    const globals = [];
    if (window.awsWafCookieDomainList !== undefined) globals.push("awsWafCookieDomainList");
    if (window.gokuProps !== undefined) globals.push("gokuProps");
    if (window._cf_chl_opt !== undefined) globals.push("_cf_chl_opt");
    if (window._Incapsula_Resource !== undefined) globals.push("_Incapsula_Resource");
    if (window.bmak !== undefined) globals.push("bmak");

    const hasTurnstile = !!document.querySelector(
        'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare.com"], #challenge-running, #cf-please-wait, #challenge-form, .cf-turnstile'
    );

    const title = (document.title || "").toLowerCase();
    const bodyText = (document.body ? document.body.innerText.slice(0, 2000) : "").toLowerCase();

    const textMarkers = [
        "just a moment",
        "verifying you are human",
        "robot check",
        "enter the characters you see below",
        "additional security check",
        "to discuss automated access",
        "access denied",
        "attention required! | cloudflare",
        "our systems have detected unusual traffic",
        "security check",
        "verify you're human",
        "please solve this puzzle",
        "press & hold"
    ];

    const matchedText = textMarkers.filter(m => title.includes(m) || bodyText.includes(m));

    return {
        globals: globals,
        has_turnstile: hasTurnstile,
        matched_text: matchedText,
        title: document.title || "",
        body_text_len: bodyText.length
    };
}
"""


async def classify_page_state(
    page: Page,
    element_count: int,
    html_byte_size: int,
    last_status: Optional[int] = None
) -> Tuple[PageStatus, str, Dict[str, Any]]:
    """
    Classifies page into NORMAL, BLOCKED, or SPARSE_SUSPECT.
    Returns: (PageStatus, reason, details)
    """
    # 1. HTTP Status Code Check
    effective_status = getattr(page, "_last_response_status", None) or last_status
    if effective_status in BLOCKED_STATUS_CODES:
        return (
            PageStatus.BLOCKED,
            f"HTTP status {effective_status} indicates bot mitigation challenge or access restriction",
            {"http_status": effective_status}
        )

    # 2. In-Page Challenge Markers Check
    try:
        markers = await page.evaluate(CHALLENGE_DETECTION_JS)
    except Exception:
        markers = {"globals": [], "has_turnstile": False, "matched_text": [], "title": "", "body_text_len": 0}

    if markers.get("globals"):
        return (
            PageStatus.BLOCKED,
            f"Known bot-mitigation script globals detected: {', '.join(markers['globals'])}",
            markers
        )

    if markers.get("has_turnstile"):
        return (
            PageStatus.BLOCKED,
            "Cloudflare Turnstile challenge iframe detected on page",
            markers
        )

    if markers.get("matched_text"):
        return (
            PageStatus.BLOCKED,
            f"Anti-bot challenge text markers found: {', '.join(markers['matched_text'])}",
            markers
        )

    # 3. Sparse vs Byte-Size Mismatch Heuristic
    # If page has 0 elements or anomalously low elements (<5) while containing significant HTML (>40KB)
    if element_count == 0:
        return (
            PageStatus.SPARSE_SUSPECT,
            "0 interactive elements detected on page",
            {"element_count": 0, "html_byte_size": html_byte_size}
        )

    if element_count < 5 and html_byte_size > 40_000:
        return (
            PageStatus.SPARSE_SUSPECT,
            f"Anomalously low element count ({element_count}) for a {html_byte_size // 1024}KB HTML payload",
            {"element_count": element_count, "html_byte_size": html_byte_size}
        )

    return (PageStatus.NORMAL, "Page passed verification checks", markers)


async def check_and_stabilize_state(
    page: Page,
    element_count: int,
    html_byte_size: int,
    retry_wait_ms: int = 1500
) -> Tuple[PageStatus, str, Dict[str, Any]]:
    """
    Classifies page state with a bounded retry for transient in-flight verification redirects.
    """
    status, reason, details = await classify_page_state(page, element_count, html_byte_size)
    if status == PageStatus.NORMAL:
        return status, reason, details

    # Short bounded wait to allow JS-verification redirects to resolve on their own
    await asyncio.sleep(retry_wait_ms / 1000.0)
    return await classify_page_state(page, element_count, html_byte_size)


async def check_challenge_and_prompt_user(page: Page) -> bool:
    """
    Checks if page is currently challenged by Cloudflare / Turnstile / CAPTCHA / WAF.
    If challenged, alerts the user with high visibility and pauses until the user solves it in the browser.
    Returns True if a challenge was detected, False otherwise.
    """
    try:
        markers = await page.evaluate(CHALLENGE_DETECTION_JS)
    except Exception:
        return False

    is_blocked = bool(markers.get("globals") or markers.get("has_turnstile") or markers.get("matched_text"))
    if not is_blocked:
        return False

    reasons = []
    if markers.get("has_turnstile"):
        reasons.append("Cloudflare Turnstile verification")
    if markers.get("matched_text"):
        reasons.append(f"Bot challenge ('{markers['matched_text'][0]}')")
    if markers.get("globals"):
        reasons.append(f"WAF protection ({markers['globals'][0]})")

    reason_str = ", ".join(reasons) if reasons else "Security verification required"
    print("\n" + "!" * 65)
    print(f"🛑 [BOT CHALLENGE / CAPTCHA DETECTED]: {reason_str}")
    print("👉 Please solve the verification checkbox or puzzle in the browser window.")
    print("!" * 65)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "Press Enter here once you have solved the verification in the browser...")
    await asyncio.sleep(1.0)
    return True

