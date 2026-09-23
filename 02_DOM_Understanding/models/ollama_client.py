"""
Ollama Client with Streaming TTFT and Dual Format Parsing.
Supports strict JSON output and bracket-notation parsing for LFM models.
"""

import time
import json
import re
import asyncio
from typing import Dict, Any, Optional, Tuple, List, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import urllib.request
import urllib.error


class ClickAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["found", "not_found"]
    action: Optional[Literal["click", "type", "select"]] = None
    target: Optional[int] = Field(default=None, description="The integer id of the target element from the list")
    value: Optional[str] = Field(default=None, description="Text to type if action is type")
    reply: Optional[str] = Field(default=None, description="Short 1-sentence speech response")

    @model_validator(mode="after")
    def validate_target_if_found(self):
        if self.status == "found" and self.target is None:
            raise ValueError("Target integer ID must be provided when status is 'found'")
        if self.status == "found" and self.action is None:
            self.action = "click"
        return self


def _extract_first_json_object(text: str) -> Optional[str]:
    """Defense-in-depth repair path: if a model ever slips a preamble past
    the grammar, pull the first balanced {...} block by bracket counting."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434"):
        self.base_url = base_url.rstrip("/")

    def is_server_running(self) -> bool:
        """Checks if Ollama server is responding on localhost:11434."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_local_models(self) -> List[str]:
        """Returns list of currently installed model names in Ollama."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode())
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    async def pull_model(self, model_name: str) -> bool:
        """Pulls a model asynchronously via Ollama REST API."""
        print(f"[OllamaClient] Pulling model '{model_name}' (this may take a minute)...")
        payload = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=600.0).read())
            print(f"[OllamaClient] Successfully pulled '{model_name}'")
            return True
        except Exception as e:
            print(f"[OllamaClient] Error pulling '{model_name}': {e}")
            return False

    async def warmup_model(self, model_name: str) -> bool:
        """Send a trivial prompt to force Ollama to load the model into VRAM."""
        print(f"  [Warmup] Loading '{model_name}' into VRAM...")
        payload = json.dumps({
            "model": model_name,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "options": {"num_predict": 1}
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=180.0).read()
            )
            print(f"  [Warmup] '{model_name}' loaded and ready.")
            return True
        except Exception as e:
            print(f"  [Warmup] Failed for '{model_name}': {e}")
            return False

    async def generate_grounding(
        self,
        model_name: str,
        dom_representation: str,
        voice_command: str,
        system_instruction: Optional[str] = None,
        format_schema: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executes a streaming completion to measure Time-to-First-Token (TTFT),
        total latency, token rate, and parsed decision payload.
        Constrains decoding via format schema to eliminate preambles and key drift.
        """
        if not system_instruction:
            system_instruction = (
                "You are an ultra-fast speech browser grounding agent. "
                "Given the visible webpage elements and user voice command, output ONLY a JSON object "
                "matching the schema.\n"
                "If a matching element exists, output status='found' with its integer target id and action ('click', 'type', or 'select').\n"
                "If NO element on the page matches the user request, output status='not_found'.\n"
                "Format: {\"status\": \"found\"|\"not_found\", \"action\": \"click\"|\"type\"|\"select\"|null, \"target\": <int>|null, \"value\": <str>|null, \"reply\": <str>|null}"
            )

        user_prompt = (
            f"Webpage Elements:\n{dom_representation}\n\n"
            f"User Voice Command: \"{voice_command}\"\n"
            f"Output strictly valid JSON matching the schema:"
        )

        active_format = format_schema if format_schema is not None else ClickAction.model_json_schema()

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "stream": True,
            "format": active_format,
            "options": {
                "temperature": 0.0,
                "num_predict": 48,
                "num_ctx": 4096
            }
        }

        # Measure TTFT and generation metrics
        t0 = time.perf_counter_ns()
        ttft_ns: Optional[int] = None
        full_chunks = []
        token_count = 0

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )

        def read_stream():
            nonlocal ttft_ns, token_count
            with urllib.request.urlopen(req, timeout=180.0) as resp:
                for line in resp:
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line.decode())
                        msg = chunk.get("message", {}).get("content", "")
                        if msg:
                            if ttft_ns is None:
                                ttft_ns = time.perf_counter_ns()
                            full_chunks.append(msg)
                            token_count += 1
                    except Exception:
                        pass

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, read_stream)

        t_end = time.perf_counter_ns()
        total_ms = (t_end - t0) / 1_000_000.0
        ttft_ms = ((ttft_ns - t0) / 1_000_000.0) if ttft_ns else total_ms
        tokens_per_sec = (token_count / (total_ms / 1000.0)) if total_ms > 0 else 0.0

        raw_output = "".join(full_chunks).strip()

        # Strip <think>...</think> blocks from thinking models (e.g. Qwen3)
        clean_output = re.sub(r'<think>[\s\S]*?</think>', '', raw_output).strip()
        parsed_action, is_valid_json = self._parse_output(clean_output)

        return {
            "model": model_name,
            "raw_output": raw_output,
            "parsed_action": parsed_action,
            "is_valid_json": is_valid_json,
            "ttft_ms": round(ttft_ms, 2),
            "total_ms": round(total_ms, 2),
            "tokens_generated": token_count,
            "tokens_per_sec": round(tokens_per_sec, 1)
        }

    def _parse_output(self, text: str) -> Tuple[Dict[str, Any], bool]:
        """
        Parser supporting strict ClickAction validation, bracket-counting repair,
        standard JSON, and bracket-notation (for LFM/Liquid models).
        """
        def format_action_obj(obj: ClickAction) -> Dict[str, Any]:
            if obj.status == "not_found":
                return {
                    "status": "not_found",
                    "action": "not_found",
                    "target": None,
                    "value": None,
                    "reply": obj.reply or "No matching element found on the current page."
                }
            return {
                "status": "found",
                "action": obj.action or "click",
                "target": obj.target,
                "value": obj.value,
                "reply": obj.reply or "Executing action"
            }

        # 1. Try strict Pydantic ClickAction validation
        try:
            action_obj = ClickAction.model_validate_json(text)
            return format_action_obj(action_obj), True
        except Exception:
            pass

        # 2. Defense-in-depth: bracket-counting repair if preamble slipped past
        repaired = _extract_first_json_object(text)
        if repaired:
            try:
                action_obj = ClickAction.model_validate_json(repaired)
                return format_action_obj(action_obj), True
            except Exception:
                try:
                    data = json.loads(repaired)
                    if isinstance(data, dict):
                        st = data.get("status", "found" if data.get("target") is not None else "not_found")
                        return {
                            "status": st,
                            "action": data.get("action", "click" if st == "found" else "not_found"),
                            "target": data.get("target"),
                            "value": data.get("value"),
                            "reply": data.get("reply", "")
                        }, True
                except Exception:
                    pass

        # 3. Try standard JSON or markdown-fenced JSON
        clean_json = text
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            clean_json = m.group(1).strip()
        else:
            m_brace = re.search(r'\{[\s\S]*\}', text)
            if m_brace:
                clean_json = m_brace.group(0)

        try:
            data = json.loads(clean_json)
            if isinstance(data, dict):
                st = data.get("status", "found" if data.get("target") is not None else "not_found")
                return {
                    "status": st,
                    "action": data.get("action", "click" if st == "found" else "not_found"),
                    "target": data.get("target"),
                    "value": data.get("value"),
                    "reply": data.get("reply", "")
                }, True
        except Exception:
            pass

        # 4. Try Bracket-Notation Parser (e.g., [click, 2] or [tool: click, target: 2])
        m_bracket = re.search(r'\[(.*?)\]', text)
        if m_bracket:
            content = m_bracket.group(1).strip()
            # Case A: "click, 2" or "type, 1, hello"
            parts = [p.strip() for p in content.split(',')]
            if len(parts) >= 2:
                action = parts[0].replace('"', '').replace("'", '').lower()
                target_str = re.search(r'\d+', parts[1])
                if target_str:
                    target = int(target_str.group(0))
                    val = parts[2] if len(parts) > 2 else None
                    return {
                        "status": "found",
                        "action": action,
                        "target": target,
                        "value": val,
                        "reply": "Executing action"
                    }, True

        # 5. Fallback: Search for any number after target
        m_fallback = re.search(r'(?:target|id|element|button)\s*[:=]?\s*(\d+)', text, re.IGNORECASE)
        if m_fallback:
            target = int(m_fallback.group(1))
            action = "click"
            if "type" in text.lower():
                action = "type"
            return {
                "status": "found",
                "action": action,
                "target": target,
                "value": None,
                "reply": "Executing action"
            }, False

        return {"status": "not_found", "action": "not_found", "target": None, "raw": text}, False
