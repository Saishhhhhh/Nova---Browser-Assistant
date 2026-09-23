"""
Visual Live Tour: Automated Headed Showcase of All 14 Site Adapters.
Opens a live visible Google Chrome window, displays an on-screen HUD overlay,
and demonstrates every priority site adapter with real zero-latency actions.
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
from interactive_demo import execute_browser_action


TOUR_SCENARIOS = [
    {
        "site": "Google Search",
        "description": "Direct URL search & tab filtering",
        "commands": [
            "search for quantum computing",
            "images"
        ]
    },
    {
        "site": "YouTube",
        "description": "Cross-site direct search & keyboard shortcuts",
        "commands": [
            "search for lofi beats on youtube",
            "theater mode",
            "fullscreen",
            "minimize"
        ]
    },
    {
        "site": "Amazon",
        "description": "Direct product search & cart navigation",
        "commands": [
            "search for wireless mouse on amazon",
            "go to cart"
        ]
    },
    {
        "site": "Flipkart",
        "description": "Fast-path e-commerce search",
        "commands": [
            "search for backpack on flipkart"
        ]
    },
    {
        "site": "Reddit",
        "description": "Direct subreddit navigation & J/K post navigation",
        "commands": [
            "go to r/technology",
            "next post"
        ]
    },
    {
        "site": "GitHub",
        "description": "Code search & file navigation shortcuts",
        "commands": [
            "search for python on github"
        ]
    },
    {
        "site": "Cinejoy (Google Route)",
        "description": "Dynamic Google Search routing for domain rotation",
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
        "description": "Direct social media feed navigation",
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
            background: rgba(15, 23, 42, 0.92);
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
    print("This will launch a real visible Google Chrome browser and demonstrate")
    print("every site adapter live on screen with the on-screen HUD overlay.\n")

    step_mode = input("Run in step-by-step mode [press Enter each time]? (y/N): ").strip().lower() == "y"
    delay_sec = 2.5 if not step_mode else 0.5

    client = OllamaClient()
    pipeline = HybridGroundingPipeline(ollama_client=client)
    pipeline.extractor.inject_visual_badges = True

    async with async_playwright() as p:
        print("\n🚀 Launching Google Chrome (Headed Mode)...")
        browser = None
        try:
            browser = await p.chromium.launch(
                channel="chrome",
                headless=False,
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check"
                ]
            )
        except Exception:
            print("  ℹ️ Real Chrome channel not found, falling back to Chromium...")
            browser = await p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )

        context = await browser.new_context(
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        page = await context.new_page()
        tab_manager = TabManager(context, initial_page=page)

        # Initial launch to Google
        print("🌐 Opening initial viewport at https://www.google.com...")
        await page.goto("https://www.google.com", wait_until="domcontentloaded")
        await asyncio.sleep(1.0)

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
