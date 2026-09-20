"""
Fast-Track YouTube Skill.
Implements direct URL search, auto-play, and instant sub-5ms keyboard media controls.
"""

import asyncio
import urllib.parse
from typing import Dict, Any
from ..engine import FastPlaywrightEngine


class YouTubeSkill:
    def __init__(self, engine: FastPlaywrightEngine):
        self.engine = engine

    async def search(self, query: str) -> float:
        """Fast-tracks search by navigating directly to results URL (skips home page & typing)."""
        encoded = urllib.parse.quote(query)
        target_url = f"https://www.youtube.com/results?search_query={encoded}"
        await self.engine.notify_action(f"Deep-linking YouTube: '{query}'")
        nav_ms = await self.engine.navigate_direct(target_url)

        # Handle cookie consent if shown
        try:
            btn = self.engine.page.locator("button:has-text('Accept all'), button:has-text('Reject all')")
            if await btn.count() > 0:
                await btn.first.click(timeout=1000)
        except Exception:
            pass

        return nav_ms

    async def play_first_video(self) -> Dict[str, Any]:
        """Visually locates and clicks the first organic video result, waiting for player ready."""
        video_selector = "ytd-video-renderer #video-title"
        first_video = self.engine.page.locator(video_selector).first
        await first_video.wait_for(state="visible", timeout=12000)

        title = (await first_video.text_content() or "").strip()
        click_ms = await self.engine.click_with_visual(video_selector, f"Playing: {title[:30]}...")

        # Wait for video player
        player_sel = "#movie_player video, video.html5-main-video"
        player = self.engine.page.locator(player_sel).first
        await player.wait_for(state="attached", timeout=15000)
        await self.engine.page.wait_for_function(
            "() => { const v = document.querySelector('#movie_player video, video.html5-main-video'); return v && v.readyState >= 1; }"
        )

        return {
            "title": title,
            "click_ms": click_ms,
            "success": True
        }

    async def toggle_play_pause(self) -> Dict[str, Any]:
        """Dispatches instant 'k' key shortcut to toggle Play / Pause without locating elements."""
        ms = await self.engine.press_shortcut("k", "Play/Pause (Shortcut 'k')")
        state = await self.get_playback_state()
        return {"action": "play_pause", "latency_ms": ms, "state": state}

    async def seek_forward(self) -> Dict[str, Any]:
        """Dispatches instant 'l' key shortcut to jump forward +10 seconds."""
        ms = await self.engine.press_shortcut("l", "Seek +10s (Shortcut 'l')")
        state = await self.get_playback_state()
        return {"action": "seek_forward", "latency_ms": ms, "state": state}

    async def seek_backward(self) -> Dict[str, Any]:
        """Dispatches instant 'j' key shortcut to jump back -10 seconds."""
        ms = await self.engine.press_shortcut("j", "Seek -10s (Shortcut 'j')")
        state = await self.get_playback_state()
        return {"action": "seek_backward", "latency_ms": ms, "state": state}

    async def toggle_mute(self) -> Dict[str, Any]:
        """Dispatches instant 'm' key shortcut to toggle Mute / Unmute."""
        ms = await self.engine.press_shortcut("m", "Mute/Unmute (Shortcut 'm')")
        state = await self.get_playback_state()
        return {"action": "toggle_mute", "latency_ms": ms, "state": state}

    async def toggle_fullscreen(self) -> Dict[str, Any]:
        """Dispatches instant 'f' key shortcut to toggle Fullscreen."""
        ms = await self.engine.press_shortcut("f", "Fullscreen (Shortcut 'f')")
        return {"action": "toggle_fullscreen", "latency_ms": ms}

    async def get_playback_state(self) -> Dict[str, Any]:
        """Extracts current video player status (paused, currentTime, duration) in ~2ms."""
        return await self.engine.evaluate_js("""
            (() => {
                const v = document.querySelector('#movie_player video, video.html5-main-video');
                if (!v) return { ready: false };
                return {
                    ready: true,
                    paused: v.paused,
                    muted: v.muted,
                    currentTime: Math.round(v.currentTime),
                    duration: Math.round(v.duration || 0)
                };
            })()
        """)
