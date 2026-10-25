"""Environment, identity, and LLM-provider configuration for Jarvis.

Trimmed from experiments/01_Browser Automation/config.py to just the two providers the
final app actually uses (Cerebras for the browser agent, DeepInfra for the fast-path's
model step and the planner) - the project's other experiments tried Groq/OpenRouter/Ollama
along the way, but nothing in the shipped app depends on them.
"""
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ASSISTANT_NAME = "Jarvis"
USER_NAME = os.getenv("USER_NAME", "there")

CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_MODEL = os.getenv("DEEPINFRA_MODEL", "google/gemma-4-31B-it-turbo")
EXTRACTION_PROVIDER = os.getenv("EXTRACTION_PROVIDER", "").strip()
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "").strip() or None
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")

# Brave, launched with the user's real profile directory (bookmarks/logins/extensions present) rather than
# a disposable automation browser. Defaults match a standard Windows install; override in .env if different.
BRAVE_EXECUTABLE_PATH = os.getenv(
    "BRAVE_EXECUTABLE_PATH", r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
BRAVE_USER_DATA_DIR = os.getenv(
    "BRAVE_USER_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data"))
BRAVE_PROFILE_DIRECTORY = os.getenv("BRAVE_PROFILE_DIRECTORY", "Default")

_cerebras_schema_patched = False


def _patch_schema_optimizer_for_cerebras() -> None:
    """Cerebras' structured-output schema validator rejects the 'minItems' keyword browser_use normally
    emits for action lists. browser_use's own SchemaOptimizer already supports stripping it
    (remove_min_items=True), but the ChatLiteLLM call site never passes that flag, so it's patched in here
    only when Cerebras is actually used."""
    global _cerebras_schema_patched
    if _cerebras_schema_patched:
        return
    from browser_use.llm.schema import SchemaOptimizer

    original = SchemaOptimizer.create_optimized_json_schema

    def patched(model, *, remove_min_items: bool = False, remove_defaults: bool = False):
        return original(model, remove_min_items=True, remove_defaults=remove_defaults)

    SchemaOptimizer.create_optimized_json_schema = staticmethod(patched)
    _cerebras_schema_patched = True


def get_browser_use_llm(provider: str, model_name: Optional[str] = None):
    """Factory returning a browser-use-native LLM (ChatLiteLLM) for the Agent class."""
    from browser_use.llm.litellm import ChatLiteLLM

    if provider == "cerebras":
        if not CEREBRAS_API_KEY:
            raise ValueError("CEREBRAS_API_KEY is not set. Add it to .env.")
        _patch_schema_optimizer_for_cerebras()
        return ChatLiteLLM(model=f"cerebras/{model_name or CEREBRAS_MODEL}", api_key=CEREBRAS_API_KEY, temperature=0.0)
    if provider == "deepinfra":
        if not DEEPINFRA_API_KEY:
            raise ValueError("DEEPINFRA_API_KEY is not set. Add it to .env.")
        return ChatLiteLLM(model=f"deepinfra/{model_name or DEEPINFRA_MODEL}", api_key=DEEPINFRA_API_KEY, temperature=0.0)
    raise ValueError(f"Unsupported provider: {provider}")


# --- remembered input/output audio device choice, set once via the overlay's settings window

_DEVICE_CONFIG_PATH = ROOT / "ash" / ".device_config.json"


def load_device_config() -> dict:
    if _DEVICE_CONFIG_PATH.exists():
        try:
            return json.loads(_DEVICE_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_device_config(cfg: dict) -> None:
    _DEVICE_CONFIG_PATH.write_text(json.dumps(cfg), encoding="utf-8")
