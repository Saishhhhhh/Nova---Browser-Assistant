"""
Hybrid Grounding Pipeline.
Combines:
1. Context-Aware DOM Extraction (repeated-structure card scoping + typed fields)
2. Fast-Path Constraint Classifier & Intent Parsing
3. Deterministic Python Filter/Sort over typed context
4. Standard Grounding Fallback for general web actions
"""

import asyncio
import json
import re
import time
from typing import Dict, Any, Optional, List, Tuple, Literal
from pydantic import BaseModel, Field

from dom_extractors.context_aware_json import ContextAwareJSONExtractor
from models.ollama_client import OllamaClient


class ConstraintIntent(BaseModel):
    is_constraint: bool = Field(description="True if the command involves selecting based on price, stops, time, or specific card attributes")
    sort: Optional[Literal["price_asc", "price_desc", "time_asc", "time_desc"]] = None
    max_stops: Optional[int] = None
    time_after: Optional[str] = None   # "HH:MM" in 24h
    time_before: Optional[str] = None  # "HH:MM" in 24h
    keyword: Optional[str] = None      # e.g., "Delta", "United", "JetBlue"
    action: Literal["click", "select", "type", "ask_confirmation"] = "click"


def _to_minutes(t: Optional[str]) -> Optional[int]:
    if not t:
        return None
    t = str(t).strip().upper().replace(" ", "")
    try:
        if "AM" in t or "PM" in t:
            is_pm = "PM" in t
            clean = t.replace("AM", "").replace("PM", "")
            parts = clean.split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if is_pm and h != 12:
                h += 12
            if not is_pm and h == 12:
                h = 0
            return h * 60 + m
        else:
            parts = t.split(":")
            return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
    except Exception:
        return None


def apply_deterministic_constraints(elements: List[Dict[str, Any]], intent: ConstraintIntent) -> List[Dict[str, Any]]:
    """Applies deterministic filtering and sorting over elements with card context."""
    candidates = [e for e in elements if e.get("ctx")]
    if not candidates:
        return []

    # 1. Stops filter
    if intent.max_stops is not None:
        filtered = [e for e in candidates if e["ctx"].get("stops") is not None and e["ctx"]["stops"] <= intent.max_stops]
        if filtered:
            candidates = filtered

    # 2. Time filter
    if intent.time_after:
        ref_min = _to_minutes(intent.time_after)
        if ref_min is not None:
            filtered = [e for e in candidates if _to_minutes(e["ctx"].get("time")) is not None and _to_minutes(e["ctx"]["time"]) >= ref_min]
            if filtered:
                candidates = filtered

    if intent.time_before:
        ref_min = _to_minutes(intent.time_before)
        if ref_min is not None:
            filtered = [e for e in candidates if _to_minutes(e["ctx"].get("time")) is not None and _to_minutes(e["ctx"]["time"]) <= ref_min]
            if filtered:
                candidates = filtered

    # 3. Keyword / Airline match
    if intent.keyword:
        kw = intent.keyword.lower().strip()
        matched = []
        for e in candidates:
            ctx_text = json.dumps(e.get("ctx", {})).lower()
            elem_text = (e.get("text") or "").lower()
            if kw in ctx_text or kw in elem_text:
                matched.append(e)
        if matched:
            # Prioritize actionable buttons/links over filter checkboxes for "Book/Choose flight" commands
            buttons = [e for e in matched if e.get("tag") in ("button", "a")]
            candidates = buttons if buttons else matched

    # 4. Sorting
    if intent.sort == "price_asc":
        candidates.sort(key=lambda e: e["ctx"].get("price", float("inf")))
    elif intent.sort == "price_desc":
        candidates.sort(key=lambda e: -e["ctx"].get("price", float("-inf")))
    elif intent.sort == "time_asc":
        candidates.sort(key=lambda e: _to_minutes(e["ctx"].get("time")) or 9999)

    return candidates


CONSTRAINT_HINTS = {
    "cheap", "cheapest", "lowest", "fastest", "non-stop", "nonstop", "direct", 
    "after", "before", "stop", "stops", "delta", "united", "jetblue", "alaska", 
    "price", "flight", "flights"
}


class HybridGroundingPipeline:
    def __init__(self, ollama_client: OllamaClient):
        self.client = ollama_client
        self.extractor = ContextAwareJSONExtractor(inject_visual_badges=False)

    async def parse_constraint_intent(self, voice_command: str, model_name: str) -> ConstraintIntent:
        """Extracts structured constraint intent from user voice command."""
        cmd = voice_command.lower()
        is_potential_constraint = any(w in cmd for w in CONSTRAINT_HINTS)
        if not is_potential_constraint:
            return ConstraintIntent(is_constraint=False)

        system_prompt = (
            "You are a flight and e-commerce constraint parser. Extract search constraints as JSON.\n"
            "Schema:\n"
            "{\n"
            '  "is_constraint": boolean,\n'
            '  "sort": "price_asc"|"price_desc"|"time_asc"|"time_desc"|null,\n'
            '  "max_stops": integer|null,\n'
            '  "time_after": "HH:MM"|null,\n'
            '  "time_before": "HH:MM"|null,\n'
            '  "keyword": string|null,\n'
            '  "action": "click"|"select"|"type"|"ask_confirmation"\n'
            "}\n"
            "Rules:\n"
            "- 'cheapest' -> is_constraint: true, sort: 'price_asc'\n"
            "- 'non-stop' or 'direct' -> is_constraint: true, max_stops: 0\n"
            "- 'Delta' -> is_constraint: true, keyword: 'Delta'\n"
            "- 'after 12 PM' -> is_constraint: true, time_after: '12:00'\n"
            "- If the command is a regular button click or input fill with no constraints, set is_constraint: false"
        )

        user_prompt = f'Voice Command: "{voice_command}"\nOutput JSON:'

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 100}
        }

        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.client.base_url}/api/chat",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}
            )
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=30.0).read())
            data = json.loads(resp.decode())
            content = data.get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            return ConstraintIntent(**parsed)
        except Exception:
            # Fallback heuristic if LLM schema fails
            cmd = voice_command.lower()
            is_c = any(w in cmd for w in ["cheapest", "lowest", "delta", "united", "jetblue", "alaska", "non-stop", "direct", "after", "before", "12 pm"])
            sort = "price_asc" if ("cheapest" in cmd or "lowest" in cmd) else None
            max_stops = 0 if ("non-stop" in cmd or "direct" in cmd) else None
            time_after = "12:00" if "after 12" in cmd else None
            kw = "Delta" if "delta" in cmd else ("United" if "united" in cmd else ("JetBlue" if "jetblue" in cmd else ("Alaska" if "alaska" in cmd else None)))
            return ConstraintIntent(is_constraint=is_c, sort=sort, max_stops=max_stops, time_after=time_after, keyword=kw)

    async def execute_grounding(
        self,
        page,
        voice_command: str,
        model_name: str
    ) -> Dict[str, Any]:
        """
        Main entrypoint:
        Runs DOM extraction and Intent parsing concurrently (asyncio.gather).
        If constraint detected and unambiguous: executes deterministic pick in <1ms.
        Otherwise: executes full SLM grounding over context-enriched DOM.
        """
        t0 = time.perf_counter_ns()

        # Step 1: Run Extraction and Intent Parsing in PARALLEL
        dom_task = asyncio.create_task(self.extractor.extract(page))
        intent_task = asyncio.create_task(self.parse_constraint_intent(voice_command, model_name))

        (dom_json, dom_meta), intent = await asyncio.gather(dom_task, intent_task)
        extraction_ms = dom_meta.get("extraction_ms", 0.0)

        raw_elements: List[Dict[str, Any]] = dom_meta.get("raw_items", [])

        # Step 2: Check if command is a constraint query with matching card elements
        if intent.is_constraint:
            shortlist = apply_deterministic_constraints(raw_elements, intent)
            if len(shortlist) >= 1:
                winner = shortlist[0]
                total_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
                return {
                    "action": intent.action or "click",
                    "target": winner["id"],
                    "value": None,
                    "reply": f"Selected item #{winner['id']} matching your criteria.",
                    "is_constraint_fastpath": True,
                    "shortlist_count": len(shortlist),
                    "ttft_ms": round(extraction_ms, 2),
                    "total_ms": round(total_ms, 2),
                    "raw_output": json.dumps({"action": "click", "target": winner["id"]}),
                    "is_valid_json": True
                }

        # Step 3: Standard Grounding Fallback for non-constraint commands
        grounding_res = await self.client.generate_grounding(
            model_name=model_name,
            dom_representation=dom_json,
            voice_command=voice_command
        )
        total_ms = (time.perf_counter_ns() - t0) / 1_000_000.0

        res_payload = grounding_res.get("parsed_action") or {}
        return {
            "action": res_payload.get("action", "click"),
            "target": res_payload.get("target"),
            "value": res_payload.get("value"),
            "reply": res_payload.get("reply", ""),
            "is_constraint_fastpath": False,
            "ttft_ms": grounding_res.get("ttft_ms", 0.0),
            "total_ms": round(total_ms, 2),
            "raw_output": grounding_res.get("raw_output", ""),
            "is_valid_json": grounding_res.get("is_valid_json", False)
        }
