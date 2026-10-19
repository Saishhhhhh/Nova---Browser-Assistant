"""Configuration and LLM provider factory for browser automation benchmarks."""
import os
from typing import Optional, Literal
from dotenv import load_dotenv

# Search for .env in current directory or parent directory
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_MODEL = os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen2.5-72B-Instruct")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")
# Optional separate model for browser-use's page-extraction calls; empty = reuse the main model.
EXTRACTION_PROVIDER = os.getenv("EXTRACTION_PROVIDER", "").strip()
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "").strip() or None
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")

ProviderType = Literal["openrouter", "ollama", "groq", "deepinfra", "cerebras"]

_cerebras_schema_patched = False


def _patch_schema_optimizer_for_cerebras() -> None:
    """Cerebras' structured-output schema validator rejects the 'minItems'
    keyword browser_use normally emits for action lists. browser_use's own
    SchemaOptimizer already supports stripping it (remove_min_items=True),
    but the ChatLiteLLM call site never passes that flag, so it's patched in
    here only when Cerebras is actually used.
    """
    global _cerebras_schema_patched
    if _cerebras_schema_patched:
        return
    from browser_use.llm.schema import SchemaOptimizer

    original = SchemaOptimizer.create_optimized_json_schema

    def patched(model, *, remove_min_items: bool = False, remove_defaults: bool = False):
        return original(model, remove_min_items=True, remove_defaults=remove_defaults)

    SchemaOptimizer.create_optimized_json_schema = staticmethod(patched)
    _cerebras_schema_patched = True


def get_llm(provider: ProviderType = "groq", model_name: Optional[str] = None):
    """Factory returning an initialized LangChain LLM instance for Groq, OpenRouter, or Ollama.
    
    Args:
        provider: 'groq', 'openrouter', or 'ollama'
        model_name: specific model string, or defaults to env config
    """
    from langchain_openai import ChatOpenAI

    if provider == "groq":
        api_key = GROQ_API_KEY
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY is not set. Please set GROQ_API_KEY in .env or pass it via environment variable."
            )
        target_model = model_name or GROQ_MODEL
        return ChatOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            model=target_model,
            temperature=0.0,
        )

    elif provider == "openrouter":
        api_key = OPENROUTER_API_KEY
        if not api_key or api_key == "your_openrouter_api_key_here":
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or OPENROUTER_MODEL
        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            model=target_model,
            temperature=0.0,
            default_headers={
                "HTTP-Referer": "https://github.com/browser-automation-benchmarks",
                "X-Title": "Browser Automation Benchmark",
            },
        )

    elif provider == "ollama":
        target_model = model_name or OLLAMA_MODEL
        # Ollama supports OpenAI-compatible /v1 endpoints natively with tool-calling
        return ChatOpenAI(
            base_url=f"{OLLAMA_BASE_URL.rstrip('/')}/v1",
            api_key="ollama",
            model=target_model,
            temperature=0.0,
        )

    elif provider == "deepinfra":
        api_key = DEEPINFRA_API_KEY
        if not api_key or api_key == "your_deepinfra_api_key_here":
            raise ValueError(
                "DEEPINFRA_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or DEEPINFRA_MODEL
        return ChatOpenAI(
            base_url="https://api.deepinfra.com/v1/openai",
            api_key=api_key,
            model=target_model,
            temperature=0.0,
        )

    elif provider == "cerebras":
        api_key = CEREBRAS_API_KEY
        if not api_key or api_key == "your_cerebras_api_key_here":
            raise ValueError(
                "CEREBRAS_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or CEREBRAS_MODEL
        return ChatOpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=api_key,
            model=target_model,
            temperature=0.0,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_browser_use_llm(provider: ProviderType = "groq", model_name: Optional[str] = None):
    """Factory returning a browser-use-native LLM (ChatLiteLLM) for the Agent class.

    browser-use's Agent requires its own browser_use.llm.BaseChatModel interface
    (it reads a `.provider` attribute), so a plain langchain_openai.ChatOpenAI
    instance from get_llm() will not work here.
    """
    from browser_use.llm.litellm import ChatLiteLLM

    if provider == "groq":
        if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
            raise ValueError(
                "GROQ_API_KEY is not set. Please set GROQ_API_KEY in .env or pass it via environment variable."
            )
        target_model = model_name or GROQ_MODEL
        return ChatLiteLLM(model=f"groq/{target_model}", api_key=GROQ_API_KEY, temperature=0.0)

    elif provider == "openrouter":
        if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_api_key_here":
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or OPENROUTER_MODEL
        return ChatLiteLLM(model=f"openrouter/{target_model}", api_key=OPENROUTER_API_KEY, temperature=0.0)

    elif provider == "ollama":
        target_model = model_name or OLLAMA_MODEL
        # litellm's "ollama_chat/" prefix is the recommended path for chat-style models
        return ChatLiteLLM(model=f"ollama_chat/{target_model}", api_base=OLLAMA_BASE_URL, temperature=0.0)

    elif provider == "deepinfra":
        if not DEEPINFRA_API_KEY or DEEPINFRA_API_KEY == "your_deepinfra_api_key_here":
            raise ValueError(
                "DEEPINFRA_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or DEEPINFRA_MODEL
        return ChatLiteLLM(model=f"deepinfra/{target_model}", api_key=DEEPINFRA_API_KEY, temperature=0.0)

    elif provider == "cerebras":
        if not CEREBRAS_API_KEY or CEREBRAS_API_KEY == "your_cerebras_api_key_here":
            raise ValueError(
                "CEREBRAS_API_KEY is not set. Please set it in .env or pass it via environment variable."
            )
        target_model = model_name or CEREBRAS_MODEL
        _patch_schema_optimizer_for_cerebras()
        return ChatLiteLLM(model=f"cerebras/{target_model}", api_key=CEREBRAS_API_KEY, temperature=0.0)

    else:
        raise ValueError(f"Unsupported provider: {provider}")
