"""
Raw CDP (Chrome DevTools Protocol) asynchronous client.
Direct WebSocket JSON-RPC communication without any third-party browser drivers.
"""

import asyncio
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional
import websockets


def find_chrome_executable() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Could not find Google Chrome or Microsoft Edge executable.")


class ChromeProcess:
    def __init__(self, port: int = 9222, headless: bool = True):
        self.port = port
        self.headless = headless
        self.process: Optional[subprocess.Popen] = None
        self.user_data_dir = tempfile.mkdtemp(prefix="raw_cdp_profile_")

    def start(self) -> str:
        exe = find_chrome_executable()
        args = [
            exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--disable-extensions",
            "--window-size=1280,800",
        ]
        if self.headless:
            args.append("--headless=new")

        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for debugging port ready
        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1) as resp:
                    if resp.status == 200:
                        return f"http://127.0.0.1:{self.port}"
            except Exception:
                time.sleep(0.1)
        raise TimeoutError(f"Chrome failed to start debugging port {self.port} within 10s")

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
            self.process = None


class CDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._msg_id = 0
        self._pending_responses: Dict[int, asyncio.Future] = {}
        self._event_listeners: Dict[str, List[asyncio.Queue]] = {}
        self._read_task: Optional[asyncio.Task] = None

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=100 * 1024 * 1024)
        self._read_task = asyncio.create_task(self._listen_loop())
        # Enable essential domains
        await self.send("Page.enable")
        await self.send("DOM.enable")
        await self.send("Runtime.enable")

    async def _listen_loop(self):
        try:
            async for raw in self.ws:
                data = json.loads(raw)
                msg_id = data.get("id")
                if msg_id in self._pending_responses:
                    fut = self._pending_responses.pop(msg_id)
                    if "error" in data:
                        fut.set_exception(RuntimeError(data["error"]))
                    else:
                        fut.set_result(data.get("result", {}))
                elif "method" in data:
                    method = data["method"]
                    if method in self._event_listeners:
                        for q in self._event_listeners[method]:
                            await q.put(data.get("params", {}))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._msg_id += 1
        call_id = self._msg_id
        fut = asyncio.get_running_loop().create_future()
        self._pending_responses[call_id] = fut
        payload = {"id": call_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        return await fut

    def subscribe_event(self, event_name: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._event_listeners.setdefault(event_name, []).append(q)
        return q

    async def navigate(self, url: str, timeout: float = 15.0) -> float:
        t0 = time.perf_counter_ns()
        load_q = self.subscribe_event("Page.loadEventFired")
        await self.send("Page.navigate", {"url": url})
        try:
            await asyncio.wait_for(load_q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        # Wait until document readyState is complete and URL matches
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = await self.evaluate("document.readyState")
            loc = await self.evaluate("window.location.href")
            if state == "complete" and url in (loc or ""):
                break
            await asyncio.sleep(0.05)
        t1 = time.perf_counter_ns()
        return (t1 - t0) / 1_000_000.0

    async def evaluate(self, expression: str) -> Any:
        res = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        })
        val = res.get("result", {})
        return val.get("value")

    async def get_element_center(self, selector: str) -> Optional[tuple[float, float]]:
        rect = await self.evaluate(f"""
            (() => {{
                const el = document.querySelector("{selector}");
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {{ x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }};
            }})()
        """)
        if not rect:
            return None
        return (rect["x"], rect["y"])

    async def click(self, selector: str) -> float:
        t0 = time.perf_counter_ns()
        coords = await self.get_element_center(selector)
        if not coords:
            raise ValueError(f"Element not found for selector: {selector}")
        x, y = coords
        # Move mouse
        await self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        # Mouse press
        await self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1
        })
        # Mouse release
        await self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1
        })
        t1 = time.perf_counter_ns()
        return (t1 - t0) / 1_000_000.0

    async def type_text(self, selector: str, text: str) -> float:
        t0 = time.perf_counter_ns()
        await self.click(selector)
        for char in text:
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "text": char,
                "unmodifiedText": char,
            })
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyUp",
            })
        t1 = time.perf_counter_ns()
        return (t1 - t0) / 1_000_000.0

    async def press_key(self, key: str, code: str, windowsVirtualKeyCode: int):
        await self.send("Input.dispatchKeyEvent", {
            "type": "rawKeyDown",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": windowsVirtualKeyCode
        })
        await self.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": windowsVirtualKeyCode
        })

    async def scroll(self, delta_x: float, delta_y: float) -> float:
        t0 = time.perf_counter_ns()
        await self.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": 200,
            "y": 200,
            "deltaX": delta_x,
            "deltaY": delta_y
        })
        t1 = time.perf_counter_ns()
        return (t1 - t0) / 1_000_000.0

    async def get_accessibility_tree(self) -> tuple[dict, float]:
        t0 = time.perf_counter_ns()
        res = await self.send("Accessibility.getFullAXTree")
        t1 = time.perf_counter_ns()
        return res, (t1 - t0) / 1_000_000.0

    async def close(self):
        if self._read_task:
            self._read_task.cancel()
        if self.ws:
            await self.ws.close()


async def get_page_ws_url(port: int = 9222) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as resp:
        targets = json.loads(resp.read().decode())
        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            raise RuntimeError("No page target available in Chrome.")
        return page_targets[0]["webSocketDebuggerUrl"]
