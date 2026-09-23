"""
Tier-1 Deterministic Intent Router.
Resolves universal intent patterns (search, input, media buttons, direct text matching)
directly against extracted DOM elements in <5ms with ZERO SLM tokens.
"""

import re
from typing import Dict, Any, List, Optional, Tuple

META_REFERENTS = {
    "bar", "box", "input", "field", "button", "area", "form", "icon",
    "link", "tab", "menu", "dropdown", "search bar", "search box",
    "search input", "search field", "the search bar", "the search box"
}


def find_search_input(elements: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Finds the most prominent search input on the page."""
    # 1. Semantic role tagged by extractor
    for el in elements:
        if el.get("semantic_role") == "SEARCH_INPUT":
            return el

    # 2. Heuristic attribute matching
    for el in elements:
        if el.get("tag") in ("input", "textarea"):
            t = el.get("type", "").lower()
            dom_id = el.get("dom_id", "").lower()
            ph = el.get("placeholder", "").lower()
            aria = el.get("aria_label", "").lower()
            if t == "search" or "search" in dom_id or "search" in ph or "search" in aria:
                return el

    return None


def match_tier1_intent(voice_command: str, elements: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Evaluates voice command against deterministic patterns using DOM elements.
    Returns response dict if resolved, or None to fall through.
    """
    cmd = voice_command.strip()
    cmd_lower = cmd.lower()

    # Pattern A: "Click (on) the search bar/box"
    if re.search(r"\b(?:click|focus|tap)\s+(?:on\s+)?(?:the\s+)?search\s+(?:bar|box|input|field)\b", cmd_lower):
        s_input = find_search_input(elements)
        if s_input:
            return {
                "status": "found",
                "action": "click",
                "target": s_input["id"],
                "value": None,
                "reply": f"Focusing the search bar (#{s_input['id']}).",
                "is_tier1_fastpath": True,
                "is_constraint_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # Pattern B: "Search (for) X" / "Find X"
    m_search = re.search(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+)$", cmd_lower)
    if m_search:
        query = m_search.group(1).strip().strip('"\'')
        if query not in META_REFERENTS:
            s_input = find_search_input(elements)
            if s_input:
                return {
                    "status": "found",
                    "action": "type",
                    "target": s_input["id"],
                    "value": query,
                    "is_search": True,
                    "reply": f"Searching for '{query}' on #{s_input['id']}.",
                    "is_tier1_fastpath": True,
                    "is_constraint_fastpath": True,
                    "total_ms": 0.0,
                    "is_valid_json": True
                }

    # Pattern C: "Type X" / "Enter X"
    m_type = re.search(r"^(?:type|enter|input|fill\s+in)\s+(?:['\"](.+?)['\"]|(.+))$", cmd, re.IGNORECASE)
    if m_type:
        text_val = (m_type.group(1) or m_type.group(2) or "").strip()
        # Find active or first visible text input
        text_inputs = [
            el for el in elements
            if el.get("tag") in ("input", "textarea")
            and el.get("type") not in ("checkbox", "radio", "submit", "button", "hidden")
        ]
        if text_inputs and text_val:
            target_el = text_inputs[0]
            return {
                "status": "found",
                "action": "type",
                "target": target_el["id"],
                "value": text_val,
                "reply": f"Entering '{text_val}' into #{target_el['id']}.",
                "is_tier1_fastpath": True,
                "is_constraint_fastpath": True,
                "total_ms": 0.0,
                "is_valid_json": True
            }

    # Pattern D: Media buttons via aria-label matching
    MEDIA_COMMANDS = {
        "play": ["play", "resume"],
        "pause": ["pause", "stop"],
        "mute": ["mute", "unmute", "turn off sound"],
        "fullscreen": ["full screen", "fullscreen", "maximize"]
    }
    for action_key, keywords in MEDIA_COMMANDS.items():
        if any(re.search(rf"\b{kw}\b", cmd_lower) for kw in keywords):
            for el in elements:
                aria = (el.get("aria_label") or "").lower()
                el_text = (el.get("text") or "").lower()
                if any(kw in aria or kw in el_text for kw in keywords):
                    return {
                        "status": "found",
                        "action": "click",
                        "target": el["id"],
                        "value": None,
                        "reply": f"Triggering {action_key} on #{el['id']} ('{el.get('text') or aria}').",
                        "is_tier1_fastpath": True,
                        "is_constraint_fastpath": True,
                        "total_ms": 0.0,
                        "is_valid_json": True
                    }

    # Pattern E: Direct "Click X" button text matching
    m_click = re.search(r"^(?:click|press|tap|hit)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+button|\s+link)?$", cmd_lower)
    if m_click:
        target_name = m_click.group(1).strip()
        if target_name and target_name not in ("button", "link", "item"):
            # Exact match first
            for el in elements:
                el_txt = (el.get("text") or "").lower().strip()
                aria = (el.get("aria_label") or "").lower().strip()
                if el_txt == target_name or aria == target_name:
                    return {
                        "status": "found",
                        "action": "click",
                        "target": el["id"],
                        "value": None,
                        "reply": f"Clicking #{el['id']} ('{el.get('text') or aria}').",
                        "is_tier1_fastpath": True,
                        "is_constraint_fastpath": True,
                        "total_ms": 0.0,
                        "is_valid_json": True
                    }
            # Substring match on buttons
            for el in elements:
                if el.get("tag") in ("button", "a") or el.get("role") in ("button", "link"):
                    el_txt = (el.get("text") or "").lower()
                    aria = (el.get("aria_label") or "").lower()
                    if target_name in el_txt or target_name in aria:
                        return {
                            "status": "found",
                            "action": "click",
                            "target": el["id"],
                            "value": None,
                            "reply": f"Clicking #{el['id']} ('{el.get('text') or aria}').",
                            "is_tier1_fastpath": True,
                            "is_constraint_fastpath": True,
                            "total_ms": 0.0,
                            "is_valid_json": True
                        }

    return None
