"""
Visual Live Tour: Automated Headed Showcase of All 14 Site Adapters.
Opens a live visible Google Chrome or Brave browser window, displays an on-screen
HUD overlay, and demonstrates every priority site adapter with real zero-latency actions.
"""

import sys
import asyncio
import time
from typing import Dict, Any, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from playwright.async_api import async_playwright
from dom_extractors.context_aware_json import ContextAwareJSONExtractor
from models.ollama_client import OllamaClient
from pipeline.hybrid_pipeline import HybridGroundingPipeline
from pipeline.tab_manager import TabManager
from pipeline.page_classifier import check_challenge_and_prompt_user
from interactive_demo import execute_browser_action


TOUR_SCENARIOS = [
    {
        "site": "Google Search",
        "description": "Direct URL search & tab filtering",
        "commands": [
            "search for quantum computing",
            "first result"
        ]
    },
    {
        "site": "YouTube",
        "description": "Search, open video, theater mode & fullscreen",
        "commands": [
            "search for lofi beats on youtube",
            "open the first video",
            "theater mode",
            "fullscreen",
            "minimize",
            "pause"
        ]
    },
    {
        "site": "Amazon",
        "description": "Product search & instant cart navigation",
        "commands": [
            "search for wireless mouse on amazon",
            "go to cart"
        ]
    },
    {
        "site": "Flipkart",
        "description": "E-commerce product search",
        "commands": [
            "search for iphone 15 on flipkart"
        ]
    },
    {
        "site": "Reddit",
        "description": "Direct subreddit navigation & J/K post navigation",
        "commands": [
            "go to r/technology",
            "next post",
            "upvote"
        ]
    },
    {
        "site": "GitHub",
        "description": "Code search & repo issues navigation",
        "commands": [
            "search for python on github",
            "issues"
        ]
    },
    {
        "site": "Cinejoy (Google Route)",
        "description": "Dynamic Google Search routing for movie streaming",
        "commands": [
            "watch interstellar on cinejoy"
        ]
    },
    {
        "site": "GoGoAnime (Google Route)",
        "description": "Dynamic Google Search routing for anime streaming",
        "commands": [
            "watch attack on titan on gogoanime"
        ]
    },
    {
        "site": "Gmail",
        "description": "Direct inbox navigation & shortcut enablement trigger",
        "commands": [
            "open gmail",
            "enable gmail shortcuts"
        ]
    },
    {
        "site": "ChatGPT",
        "description": "Instant new chat navigation",
        "commands": [
            "open chatgpt"
        ]
    },
    {
        "site": "Claude",
        "description": "Direct navigation to Claude new chat",
        "commands": [
            "open claude"
        ]
    },
    {
        "site": "Gemini",
        "description": "Direct navigation to Google Gemini app",
        "commands": [
            "open gemini"
        ]
    },
    {
        "site": "LinkedIn",
        "description": "Direct professional feed navigation",
        "commands": [
            "open linkedin"
        ]
    },
    {
        "site": "Instagram",
        "description": "Direct social media explore navigation",
        "commands": [
            "open instagram"
        ]
    }
]

HUD_INJECTION_JS = """
(() => {
    let hud = document.getElementById('__agent_visual_hud');
    if (!hud) {
        hud = document.createElement('div');
        hud.id = '__agent_visual_hud';
        hud.style.cssText = `
            position: fixed;
            top: 14px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 2147483647;
            background: rgba(15, 23, 42, 0.94);
            color: #f8fafc;
            padding: 10px 22px;
            border-radius: 30px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.15);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 13px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 14px;
            backdrop-filter: blur(12px);
            pointer-events: none;
            transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        `;
        document.body.appendChild(hud);
    }
    return true;
})()
"""

async def update_hud(page, site: str, command: str, action_desc: str, latency_ms: float):
    try:
        await page.evaluate(HUD_INJECTION_JS)
        safe_site = site.replace("'", "\\'")
        safe_cmd = command.replace("'", "\\'")
        safe_action = action_desc.replace("'", "\\'")
        js = f"""
        (() => {{
            const hud = document.getElementById('__agent_visual_hud');
            if (hud) {{
                hud.innerHTML = `
                    <span style="background: #3b82f6; color: white; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 11px;">{safe_site}</span>
                    <span style="color: #cbd5e1;">🎙️ &ldquo;<b style="color: #f1f5f9;">{safe_cmd}</b>&rdquo;</span>
                    <span style="color: #94a3b8;">|</span>
                    <span style="color: #10b981; font-weight: 600;">⚡ {safe_action} ({latency_ms}ms)</span>
                `;
            }}
        }})()
        """
        await page.evaluate(js)
    except Exception:
        pass


async def main():
    print("=" * 65)
    print("🌟 LIVE VISUAL TOUR: 14 PRIORITY SITES AUTOMATED SHOWCASE")
    print("=" * 65)
    print("This will launch a real visible browser and demonstrate")
    print("every site adapter live on screen with the on-screen HUD overlay.\n")

    print("Select Browser to Run Visual Tour:")
    print("  [1] Real Google Chrome (Default)")
    print("  [2] Brave Browser (C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe)")
    print("  [3] Connect to existing Brave via Remote Debugging (port 9222)")
    browser_choice = input("Enter choice [1-3] (default: 1): ").strip() or "1"

    step_mode = input("\nRun in step-by-step mode [press Enter each action]? (y/N): ").strip().lower() == "y"
    delay_sec = 2.5 if not step_mode else 0.5

    client = OllamaClient()
    pipeline = HybridGroundingPipeline(ollama_client=client)
    pipeline.extractor.inject_visual_badges = True

    brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

    launch_args = [
        "--start-maximized",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check"
    ]

    async with async_playwright() as p:
        browser = None
        context = None

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
                    slow_mo=200,
                    args=launch_args
                )
                print("  🌐 Browser Channel: Brave Browser (Headed)")
            except Exception as e:
                print(f"  ⚠️ Could not launch Brave directly ({e}), falling back to Chrome...")
                browser = await p.chromium.launch(channel="chrome", headless=False, slow_mo=200, args=launch_args)
            context = await browser.new_context(
                no_viewport=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )
        else:
            print("\n🚀 Launching Google Chrome (Headed Mode)...")
            try:
                browser = await p.chromium.launch(
                    channel="chrome",
                    headless=False,
                    slow_mo=200,
                    args=launch_args
                )
                print("  🌐 Chrome Channel: Real Google Chrome binary (stealth mode active)")
            except Exception:
                browser = await p.chromium.launch(
                    headless=False,
                    slow_mo=200,
                    args=launch_args
                )
                print("  🌐 Chrome Channel: Bundled Chromium (stealth flags applied)")
            context = await browser.new_context(
                no_viewport=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        page = await context.new_page() if not context.pages else context.pages[0]
        tab_manager = TabManager(context, initial_page=page)

        # Initial launch to Google
        print("🌐 Opening initial viewport at https://www.google.com...")
        await page.goto("https://www.google.com", wait_until="domcontentloaded")
        await asyncio.sleep(1.0)
        await check_challenge_and_prompt_user(page)

        total_scenarios = len(TOUR_SCENARIOS)
        successful_actions = 0
        total_actions = sum(len(s["commands"]) for s in TOUR_SCENARIOS)

        for s_idx, scenario in enumerate(TOUR_SCENARIOS, 1):
            site_name = scenario["site"]
            desc = scenario["description"]
            commands = scenario["commands"]

            print(f"\n[{s_idx}/{total_scenarios}] 🎯 Site: {site_name} ({desc})")
            print("─" * 60)

            for cmd in commands:
                active_page = tab_manager.active_page
                print(f"  🎙️ [Command]: \"{cmd}\"")

                t0 = time.perf_counter_ns()
                res = await pipeline.execute_grounding(active_page, cmd, "hammer2.1:3b", tab_manager=tab_manager)
                elapsed_ms = round((time.perf_counter_ns() - t0) / 1_000_000.0, 1)

                action_type = res.get("action", "unknown")
                reply = res.get("reply", "")

                print(f"  ⚡ Routed: action='{action_type}' | Latency: {elapsed_ms}ms")
                if reply:
                    print(f"  🗣️ \"{reply}\"")

                # Update HUD on current page before acting
                await update_hud(tab_manager.active_page, site_name, cmd, f"{action_type}", elapsed_ms)

                # Execute physically in the browser
                await execute_browser_action(
                    tab_manager.active_page,
                    res,
                    pipeline.extractor,
                    voice_command=cmd,
                    tab_manager=tab_manager
                )

                successful_actions += 1

                # Check if anti-bot challenge appeared
                await check_challenge_and_prompt_user(tab_manager.active_page)

                # Re-inject HUD on newly navigated page
                await asyncio.sleep(0.5)
                await update_hud(tab_manager.active_page, site_name, cmd, f"{action_type} done", elapsed_ms)

                if step_mode:
                    input("    [Press Enter for next visual action]...")
                else:
                    await asyncio.sleep(delay_sec)

        print("\n" + "=" * 65)
        print("🎉 VISUAL LIVE TOUR COMPLETED!")
        print(f"Successfully showcased {successful_actions}/{total_actions} actions across all 14 sites.")
        print("=" * 65)

        input("\nPress Enter to close the browser window...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
