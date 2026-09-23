"""
Interactive Visual Playground for DOM Grounding Agent.
Launches a real visible Chromium browser with:
- Floating amber element badges ([1], [2], [3]...)
- Neon green target highlight animations
- Live natural language command input
- Real-time Playwright execution in slow motion
"""

import sys
import asyncio
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any

MODULE_ROOT = Path(__file__).resolve().parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from playwright.async_api import async_playwright
from models.ollama_client import OllamaClient
from dom_extractors.context_aware_json import ContextAwareJSONExtractor
from pipeline.hybrid_pipeline import HybridGroundingPipeline
from pipeline.dom_stability import act_and_reindex, click_and_reindex, search_and_reindex, wait_for_stable
from pipeline.page_classifier import PageStatus, PageBlockedError, check_and_stabilize_state, check_challenge_and_prompt_user
from pipeline.tab_manager import TabManager, execute_physical_action

FIXTURES_DIR = MODULE_ROOT / "dataset" / "fixtures"

FIXTURE_PAGES = {
    "1": ("Flight Search (Constraints, Prices, Airlines)", FIXTURES_DIR / "search_results.html"),
    "2": ("E-Commerce Store (Product, Colors, Cart)", FIXTURES_DIR / "ecommerce_product.html"),
    "3": ("Checkout Form (Multi-field address, coupons)", FIXTURES_DIR / "checkout_form.html"),
    "4": ("Settings & Safety (2FA switches, Danger zone)", FIXTURES_DIR / "settings_safety.html"),
}

SHOWCASE_ACTIONS = {
    "1": [
        "Book the absolute cheapest flight",
        "Select the cheapest non-stop direct flight",
        "Choose the Delta flight",
        "Book the afternoon flight departing after 12 PM",
        "Clear all filters"
    ],
    "2": [
        "Accept all cookies",
        "Change the switch to Red linear quiet",
        "Select the Shell White colorway",
        "Add this keyboard to my cart",
        "Save this to my wishlist"
    ]
}


async def highlight_element_on_screen(page, element_id: int, message: str = ""):
    """Draws a bright neon highlight box and floating notification on the live webpage."""
    script = f"""
        (() => {{
            const el = document.querySelector('[data-agent-index="{element_id}"]');
            if (!el) return;

            // Remove any previous active highlights
            const oldRing = document.querySelector('.__agent_active_ring');
            if (oldRing) oldRing.remove();
            const oldBanner = document.querySelector('.__agent_floating_banner');
            if (oldBanner) oldBanner.remove();

            // Create glowing highlight ring
            const r = el.getBoundingClientRect();
            const ring = document.createElement('div');
            ring.className = '__agent_active_ring';
            ring.style.cssText = `
                position: absolute;
                left: ${{r.left + window.scrollX - 4}}px;
                top: ${{r.top + window.scrollY - 4}}px;
                width: ${{r.width + 8}}px;
                height: ${{r.height + 8}}px;
                border: 3px solid #10b981;
                background: rgba(16, 185, 129, 0.2);
                border-radius: 8px;
                box-shadow: 0 0 20px #10b981, inset 0 0 10px #10b981;
                z-index: 2147483646;
                pointer-events: none;
                transition: all 0.3s ease-in-out;
            `;
            document.body.appendChild(ring);

            // Floating agent notification banner
            if ("{message}") {{
                const banner = document.createElement('div');
                banner.className = '__agent_floating_banner';
                banner.textContent = "{message}";
                banner.style.cssText = `
                    position: fixed;
                    top: 16px;
                    left: 50%;
                    transform: translateX(-50%);
                    background: #0f172a;
                    color: #38bdf8;
                    font-family: system-ui, -apple-system, sans-serif;
                    font-size: 14px;
                    font-weight: 700;
                    padding: 8px 18px;
                    border-radius: 20px;
                    border: 1px solid #38bdf8;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.7);
                    z-index: 2147483647;
                    pointer-events: none;
                `;
                document.body.appendChild(banner);
            }}

            // Scroll element into view smoothly if needed
            el.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
        }})()
    """
    await page.evaluate(script)


def extract_query_from_command(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    m_quoted = re.search(r'["\']([^"\']+)["\']', cmd)
    if m_quoted:
        return m_quoted.group(1).strip()
    m_search = re.search(r'(?:search\s+for|search|find|type|enter)\s+(.+?)(?:\s+(?:on|in|at)\s+.*)?$', cmd, re.IGNORECASE)
    if m_search:
        return m_search.group(1).strip()
    return None


async def execute_browser_action(page, res: Dict[str, Any], extractor: Any = None, voice_command: str = "", tab_manager: Any = None):
    """Physically triggers the action on the page and stabilizes+re-indexes the DOM."""
    target_id = res.get("target")
    action = res.get("action", "click")
    value = res.get("value")
    active_pg = tab_manager.active_page if tab_manager else page

    # Tier-0 physical browser controls (scroll, nav, reload) with 0ms SLM latency
    if action == "physical":
        action_type = res.get("physical_action", "scroll_down")
        phys_res = await execute_physical_action(action_type, active_pg, tab_manager=tab_manager, extractor=extractor)
        print(f"  ⚡ [Tier-0 Action] {phys_res.get('reply')}")
        return

    # Element or action not found on current page
    if action == "not_found" or res.get("status") == "not_found":
        print(f"\n  ⚠️  [ELEMENT / ACTION NOT FOUND ON CURRENT PAGE]")
        print(f"     {res.get('reply')}\n")
        return

    # Bot mitigation human handoff
    if action == "handoff":
        print(f"\n  🛑 [HUMAN HANDOFF REQUIRED]")
        print(f"     {res.get('reply')}")
        print("     👉 Please interact with the Chrome window directly. Once resolved, type 'refresh'.\n")
        return

    # Tier-0.5 URL Direct Navigation
    if action == "url_navigate":
        nav_url = res.get("url")
        print(f"  🌐 [URL Direct Nav] Navigating to {nav_url}...")
        try:
            await active_pg.goto(nav_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"  ⚠️ Navigation warning: {e}")
        # Detect and prompt user for Cloudflare Turnstile / CAPTCHA
        await check_challenge_and_prompt_user(active_pg)
        if extractor:
            await wait_for_stable(active_pg, quiet_ms=300, timeout_ms=3000)
            try:
                _, meta = await extractor.extract(active_pg)
                print(f"  ✅ Page loaded & stabilized! Indexed {meta['element_count']} elements.")
            except Exception:
                pass
        return

    # Tier-0.5 Keyboard Shortcuts
    if action == "keyboard":
        focus_sel = res.get("focus_selector")
        if focus_sel:
            try:
                await active_pg.click(focus_sel, timeout=1500)
            except Exception:
                pass
        keys = res.get("keys")
        single_key = res.get("key")
        if keys:
            for k in keys:
                await active_pg.keyboard.press(k)
                await asyncio.sleep(0.08)
            print(f"  ⌨️  [Keyboard Shortcut] Pressed sequence: {' -> '.join(keys)}")
        elif single_key:
            await active_pg.keyboard.press(single_key)
            print(f"  ⌨️  [Keyboard Shortcut] Pressed '{single_key}'")
        if extractor:
            await asyncio.sleep(0.3)
            try:
                await extractor.extract(active_pg)
            except Exception:
                pass
        return

    # Tier-0.5 Direct CSS Click Selector
    if action == "click_selector":
        sel = res.get("selector")
        print(f"  👆 [Direct CSS Click] Clicking '{sel}'...")
        try:
            loc = active_pg.locator(sel).first
            await loc.click(timeout=4000)
            print(f"  ✅ Clicked '{sel}' successfully.")
        except Exception as e:
            print(f"  ⚠️ Could not click selector '{sel}': {e}")
        if extractor:
            await wait_for_stable(active_pg, quiet_ms=300, timeout_ms=3000)
            try:
                _, meta = await extractor.extract(active_pg)
                print(f"  ✅ Re-indexed {meta['element_count']} elements.")
            except Exception:
                pass
        return

    # Tier-0.5 Direct CSS Type Selector
    if action == "type_selector":
        sel = res.get("selector")
        val = res.get("value", "")
        press_enter = res.get("press_enter", False)
        print(f"  ⌨️  [Direct CSS Type] Typing '{val[:30]}' into '{sel}'...")
        try:
            loc = active_pg.locator(sel).first
            await loc.fill(val, timeout=4000)
            if press_enter:
                await loc.press("Enter")
            print(f"  ✅ Submitted input successfully.")
        except Exception as e:
            print(f"  ⚠️ Could not type into '{sel}': {e}")
        if extractor:
            await wait_for_stable(active_pg, quiet_ms=300, timeout_ms=3000)
            try:
                _, meta = await extractor.extract(active_pg)
                print(f"  ✅ Re-indexed {meta['element_count']} elements.")
            except Exception:
                pass
        return

    if not target_id:
        print(f"  [Notice] Model chose action='{action}' without an element target.")
        return

    selector = f'[data-agent-index="{target_id}"]'
    el = active_pg.locator(selector).first

    if await el.count() == 0:
        print(f"  [Error] Element with data-agent-index='{target_id}' not found.")
        return

    # Pre-action visibility check
    try:
        if not await el.is_visible():
            print(f"  ⚠️ Element #{target_id} is hidden or scrolled out of view. Attempting scroll into view...")
            await el.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    # Visual highlight pause
    await highlight_element_on_screen(active_pg, target_id, f"🎯 Agent Target: #{target_id} ({action.upper()})")
    await asyncio.sleep(0.5)

    # Perform action
    tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
    input_type = await el.get_attribute("type") or ""

    is_editable = await el.evaluate("""el => {
        if (el.isContentEditable) return true;
        if (['INPUT','TEXTAREA'].includes(el.tagName) &&
            !['checkbox','radio','submit','button','hidden'].includes(el.type)) return true;
        return false;
    }""")

    if action == "type" and not is_editable:
        print(f"  ⚠️ Element #{target_id} is not an editable field ({tag_name}). Re-routing as click.")
        action = "click"

    is_text_input = tag_name in ("input", "textarea") and input_type not in ("checkbox", "radio", "submit", "button")

    if action == "type" or is_text_input:
        extracted_query = extract_query_from_command(voice_command)
        text_to_type = value or extracted_query or "Test text"
        el_id = (await el.get_attribute("id") or "").lower()
        el_name = (await el.get_attribute("name") or "").lower()
        is_search = "search" in el_id or "search" in el_name or input_type == "search" or "search" in voice_command.lower() or res.get("is_search")

        # Guard against hallucinated raw URLs being typed into search inputs
        if is_search and (text_to_type.startswith("http://") or text_to_type.startswith("https://")):
            print(f"  🌐 [Auto-Reroute] Detected raw URL '{text_to_type}' in search action. Navigating directly instead of typing into input.")
            try:
                await active_pg.goto(text_to_type, wait_until="domcontentloaded", timeout=15000)
                await check_challenge_and_prompt_user(active_pg)
                if extractor:
                    await wait_for_stable(active_pg, quiet_ms=300, timeout_ms=3000)
                    _, meta = await extractor.extract(active_pg)
                    print(f"  ✅ Navigated to URL & stabilized! Re-indexed {meta['element_count']} elements.")
            except Exception as e:
                print(f"  ⚠️ Error navigating to raw URL: {e}")
            return

        try:
            if is_search:
                print(f"  🔍 [Search] Searching '{text_to_type}' on #{target_id} & reindexing...")
                if extractor:
                    _, meta = await search_and_reindex(active_pg, target_id, text_to_type, extractor)
                    print(f"  ✅ Search submitted & page stabilized! Re-indexed {meta['element_count']} elements.")
                else:
                    await el.fill("", timeout=4000)
                    await el.type(text_to_type, delay=35)
                    await el.press("Enter")
            else:
                await el.fill("", timeout=4000)
                await el.type(text_to_type, delay=35)
                print(f"  ⌨️  [Type] Typed '{text_to_type}' into #{target_id}")
                if extractor:
                    _, meta = await act_and_reindex(active_pg, asyncio.sleep(0.1), extractor)
                    print(f"  ✅ Input registered. {meta['element_count']} elements indexed.")
        except Exception as e:
            print(f"  ⚠️ Error performing type action on #{target_id}: {e}")

    elif action == "click":
        print(f"  👆 [Click] Clicking element #{target_id} and waiting for DOM stabilization...")
        try:
            if extractor:
                _, meta = await click_and_reindex(active_pg, target_id, extractor)
                print(f"  ✅ Page stabilized! Re-indexed {meta['element_count']} elements with fresh badges.")
            else:
                await el.click(timeout=4000)
        except Exception as e:
            print(f"  ⚠️ Error clicking element #{target_id}: {e}")

    elif action == "select" or tag_name == "select":
        if value:
            try:
                await el.select_option(value=value, timeout=4000)
            except Exception:
                try:
                    await el.select_option(index=0, timeout=4000)
                except Exception as e:
                    print(f"  ⚠️ Select option error: {e}")
            print(f"  🔽 [Select] Selected '{value}' on #{target_id}")
        else:
            try:
                await el.click(timeout=4000)
            except Exception:
                pass
        if extractor:
            _, meta = await act_and_reindex(active_pg, asyncio.sleep(0.1), extractor)
            print(f"  ✅ Selection registered. {meta['element_count']} elements indexed.")

    elif action == "ask_confirmation":
        print(f"  🛡️ [Safety Confirmation Prompted] -> '{res.get('reply', 'Confirm action?')}'")



async def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    print("\n" + "="*65)
    print("🌟 LIVE VISUAL PLAYGROUND: DOM GROUNDING AGENT")
    print("="*65)
    print("Select an environment to explore in a live visible Chrome window:")
    for k, (name, _) in FIXTURE_PAGES.items():
        print(f"  [{k}] {name}")
    print("  [5] Custom URL (Enter any web URL)")
    
    choice = input("\nEnter choice [1-5] (default: 1): ").strip() or "1"

    if choice in FIXTURE_PAGES:
        target_name, file_path = FIXTURE_PAGES[choice]
        target_url = f"file:///{file_path.as_posix()}"
    else:
        target_url = input("Enter full URL (default: https://www.google.com): ").strip() or "https://www.google.com"
        if not target_url.startswith("http"):
            target_url = f"https://{target_url}"
        target_name = target_url

    model_choice = input("Enter Ollama model (default: hammer2.1:3b): ").strip() or "hammer2.1:3b"

    client = OllamaClient()
    pipeline = HybridGroundingPipeline(ollama_client=client)
    # Enable visual badges for live user view
    pipeline.extractor.inject_visual_badges = True

    print(f"\n🚀 Launching Browser (Headed Mode) for: {target_name}...")
    print(f"🤖 Grounding Model: {model_choice}")

    print("\nSelect Browser Engine:")
    print("  [1] Real Google Chrome (Default)")
    print("  [2] Brave Browser (C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe)")
    print("  [3] Connect to existing Brave via Remote Debugging (port 9222)")
    browser_choice = input("Enter choice [1-3] (default: 1): ").strip() or "1"

    launch_args = [
        "--window-size=1280,850",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-sandbox"
    ]

    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

    async with async_playwright() as p:
        if browser_choice == "3":
            print("\n🔌 Connecting to existing Brave session on http://localhost:9222...")
            try:
                browser = await p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0]
                print("  ✅ Connected to live Brave session!")
            except Exception as e:
                print(f"  ❌ Could not connect to Brave on port 9222 ({e}).")
                print("  👉 Tip: Launch Brave with: brave.exe --remote-debugging-port=9222")
                return
        elif browser_choice == "2":
            print(f"\n🦁 Launching Brave Browser ({brave_path})...")
            try:
                browser = await p.chromium.launch(
                    executable_path=brave_path,
                    headless=False,
                    slow_mo=250,
                    args=launch_args
                )
                print("  🌐 Browser Channel: Brave Browser (Headed)")
            except Exception as e:
                print(f"  ⚠️ Could not launch Brave directly ({e}), falling back to Chrome...")
                browser = await p.chromium.launch(channel="chrome", headless=False, slow_mo=250, args=launch_args)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )
        else:
            try:
                browser = await p.chromium.launch(
                    channel="chrome",
                    headless=False,
                    slow_mo=250,
                    args=launch_args
                )
                print("  🌐 Browser Channel: Real Google Chrome binary (stealth mode active)")
            except Exception:
                browser = await p.chromium.launch(
                    headless=False,
                    slow_mo=250,
                    args=launch_args
                )
                print("  🌐 Chrome Channel: Bundled Chromium (stealth flags applied)")
            context = await browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )

        # Patch navigator.webdriver, window.chrome, and plugins bot detection signals
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        page = await context.new_page()
        tab_manager = TabManager(context, initial_page=page)

        # Track HTTP status code of the main-frame navigation
        page._last_response_status = None
        def on_response(resp):
            try:
                if resp.request.is_navigation_request() and resp.frame == tab_manager.active_page.main_frame:
                    tab_manager.active_page._last_response_status = resp.status
            except Exception:
                pass
        page.on("response", on_response)

        await page.goto(target_url, wait_until="domcontentloaded")
        await asyncio.sleep(0.5)

        # Initial extraction to paint badges
        output_json, meta = await pipeline.extractor.extract(tab_manager.active_page)
        count = meta['element_count']

        # Classify initial page state
        p_status, p_reason, _ = await check_and_stabilize_state(
            tab_manager.active_page,
            element_count=count,
            html_byte_size=len(output_json)
        )

        if p_status == PageStatus.BLOCKED:
            print(f"\n🛑 ANTI-BOT CHALLENGE DETECTED: {p_reason}")
            print("  👉 The site is restricting automated sessions. Please complete the verification in Chrome, then type 'refresh'.")
        elif p_status == PageStatus.SPARSE_SUSPECT:
            print(f"\n⚠️  SUSPECT/SPARSE DOM: {p_reason}")
            print("  👉 The page might still be rendering or is an interstitial. Check Chrome and type 'refresh' if needed.")
        else:
            print(f"\n✅ Page Loaded! {count} interactive elements tagged on screen with amber badges.")

        # Show automated showcase option
        if choice in SHOWCASE_ACTIONS:
            print("\n💡 Options:")
            print("  [A] Run Automated Showcase (watch 5 voice commands execute automatically)")
            print("  [I] Interactive Mode (type your own voice commands)")
            mode = input("Choose mode [A/I] (default: A): ").strip().upper() or "A"

            if mode == "A":
                print("\n🎬 Running Automated Showcase...")
                for idx, cmd in enumerate(SHOWCASE_ACTIONS[choice], 1):
                    print(f"\n─────────────────────────────────────────────────────────────")
                    print(f"🎙️ [Voice Command #{idx}]: \"{cmd}\"")
                    res = await pipeline.execute_grounding(tab_manager.active_page, cmd, model_choice, tab_manager=tab_manager)
                    print(f"⚡ Latency: {res['total_ms']}ms | Target: #{res.get('target')} | Action: {res.get('action')}")
                    if res.get("reply"):
                        print(f"🗣️ Speech Reply: \"{res['reply']}\"")
                    await execute_browser_action(tab_manager.active_page, res, pipeline.extractor, voice_command=cmd, tab_manager=tab_manager)
                    await asyncio.sleep(1.2)
                print("\n🎉 Automated showcase finished!")

        # Interactive Command Loop
        print("\n" + "="*65)
        print("🎮 INTERACTIVE COMMAND LOOP")
        print("Type any command in plain English, and watch the browser act!")
        print("Type 'refresh' to redraw badges, or 'exit' to quit.")
        print("="*65)

        while True:
            try:
                user_cmd = input("\n🎙️ Command > ").strip()
                if not user_cmd:
                    continue
                if user_cmd.lower() in ("exit", "quit", "q"):
                    break
                active_page = tab_manager.active_page

                if user_cmd.lower() == "refresh":
                    await pipeline.extractor.extract(active_page)
                    print("🔄 Badges redrawn on screen.")
                    continue

                t0 = asyncio.get_event_loop().time()
                res = await pipeline.execute_grounding(active_page, user_cmd, model_choice, tab_manager=tab_manager)
                elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)

                target_id = res.get("target")
                action = res.get("action", "click")
                path_type = "⚡ [Deterministic FastPath]" if res.get("is_constraint_fastpath") else "🤖 [SLM Grounding]"

                print(f"  {path_type} -> Target: #{target_id} | Action: {action} | Turnaround: {elapsed}ms")
                if res.get("reply"):
                    print(f"  🗣️ \"{res['reply']}\"")
                if not target_id and res.get("raw_output"):
                    print(f"  📝 [Raw Output]: {res.get('raw_output')[:120]}")

                await execute_browser_action(active_page, res, pipeline.extractor, voice_command=user_cmd, tab_manager=tab_manager)

            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                print(f"  ❌ Error: {e}")

        print("\n👋 Closing visual playground. Great session!")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
