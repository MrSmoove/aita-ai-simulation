"""
Direct LLM provider integration for simulation agents.
"""
import asyncio
import os
import time
import warnings
from contextvars import ContextVar
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from app import prompts

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
_DISABLED_PROVIDERS = {p.strip().lower() for p in os.getenv("DISABLED_PROVIDERS", "").split(",") if p.strip()}
OPENAI_MIN_REQUEST_INTERVAL_MS = int(os.getenv("OPENAI_MIN_REQUEST_INTERVAL_MS", "0"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "4"))
OPENAI_RETRY_BASE_DELAY_MS = int(os.getenv("OPENAI_RETRY_BASE_DELAY_MS", "800"))

PROVIDER_DEFAULT_MODELS = {
    "openai": OPENAI_MODEL,
    "deepseek": DEEPSEEK_MODEL,
    "mistral": MISTRAL_MODEL,
    "groq": GROQ_MODEL,
    "gemini": GEMINI_MODEL,
}

MODEL_ALIASES = {
    "oasis-small": {
        "openai": OPENAI_MODEL,
        "deepseek": DEEPSEEK_MODEL,
        "mistral": MISTRAL_MODEL,
        "groq": GROQ_MODEL,
        "gemini": GEMINI_MODEL,
    }
}

if not OPENAI_API_KEY and not DEEPSEEK_API_KEY and not MISTRAL_API_KEY and not GROQ_API_KEY and not GEMINI_API_KEY:
    warnings.warn("No LLM API key set. Responses will be stubs.")


_usage_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("usage_context", default=None)
_openai_rate_lock = asyncio.Lock()
_last_openai_request_ts = 0.0


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "rate limit" in text or "too many requests" in text or "429" in text


async def _wait_for_openai_slot() -> None:
    global _last_openai_request_ts
    if OPENAI_MIN_REQUEST_INTERVAL_MS <= 0:
        return

    min_interval_seconds = OPENAI_MIN_REQUEST_INTERVAL_MS / 1000.0
    async with _openai_rate_lock:
        now = time.monotonic()
        elapsed = now - _last_openai_request_ts
        wait_seconds = max(0.0, min_interval_seconds - elapsed)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        _last_openai_request_ts = time.monotonic()


def available_providers() -> list[str]:
    providers = []
    if OPENAI_API_KEY and "openai" not in _DISABLED_PROVIDERS:
        providers.append("openai")
    if DEEPSEEK_API_KEY and "deepseek" not in _DISABLED_PROVIDERS:
        providers.append("deepseek")
    if MISTRAL_API_KEY and "mistral" not in _DISABLED_PROVIDERS:
        providers.append("mistral")
    if GROQ_API_KEY and "groq" not in _DISABLED_PROVIDERS:
        providers.append("groq")
    if GEMINI_API_KEY and "gemini" not in _DISABLED_PROVIDERS:
        providers.append("gemini")
    return providers


def resolve_provider(provider: Optional[str] = None) -> str:
    normalized = (provider or LLM_PROVIDER or "openai").strip().lower()
    if normalized in PROVIDER_DEFAULT_MODELS:
        return normalized
    return "openai"


def resolve_model_name(provider: str, model_name: Optional[str] = None) -> str:
    resolved_provider = resolve_provider(provider)
    if not model_name:
        return PROVIDER_DEFAULT_MODELS[resolved_provider]

    provider_aliases = MODEL_ALIASES.get(model_name, {})
    return provider_aliases.get(resolved_provider, model_name)


def _build_instruction(agent_name: str, role: str) -> str:
    role_blurb = (
        "You are the original poster responding to the thread."
        if role == "op"
        else "You are one distinct commenter in the thread."
    )
    return f"{prompts.system_prompt()}\n\n{role_blurb}\nYour visible username is {agent_name}."


def begin_usage_capture() -> Any:
    tracker = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "models": {},
        "providers": {},
    }
    token = _usage_context.set(tracker)
    return token, tracker


def end_usage_capture(token: Any) -> Dict[str, Any]:
    tracker = _usage_context.get() or {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "models": {},
        "providers": {},
    }
    _usage_context.reset(token)
    return tracker


def _record_usage(provider: str, model_name: str, prompt_tokens: Optional[int], completion_tokens: Optional[int]) -> None:
    tracker = _usage_context.get()
    if tracker is None:
        return

    tracker["request_count"] += 1
    tracker["prompt_tokens"] += int(prompt_tokens or 0)
    tracker["completion_tokens"] += int(completion_tokens or 0)
    tracker["models"][model_name] = tracker["models"].get(model_name, 0) + 1
    tracker["providers"][provider] = tracker["providers"].get(provider, 0) + 1


async def seed_session(
    post_dict: Dict[str, Any],
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, str]:
    """
    Preserve a lightweight session object for future thread state.
    """
    resolved_provider = resolve_provider(provider)
    resolved_model = resolve_model_name(resolved_provider, model_name)
    return {
        "session_id": f"session-{post_dict.get('post_id', 'unknown')}",
        "post_id": post_dict.get("post_id", "unknown"),
        "provider": resolved_provider,
        "model_name": resolved_model,
    }


async def generate_comment(
    session: Dict[str, str],
    prompt_context: str,
    agent_name: str,
    model_name: Optional[str] = None,
    role: str = "commenter",
    provider: Optional[str] = None,
) -> str:
    """Generate a comment via the configured provider."""
    resolved_provider = resolve_provider(provider or session.get("provider"))
    resolved_model = resolve_model_name(resolved_provider, model_name or session.get("model_name"))
    instructions = _build_instruction(agent_name, role)

    if resolved_provider == "deepseek" and DEEPSEEK_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
            )

            def _generate() -> Any:
                return client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt_context},
                    ],
                    temperature=0.7,
                )

            response = await asyncio.to_thread(_generate)
            usage = getattr(response, "usage", None)
            _record_usage(
                "deepseek",
                getattr(response, "model", None) or resolved_model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            choice = response.choices[0] if getattr(response, "choices", None) else None
            message = getattr(choice, "message", None)
            text = getattr(message, "content", None)
            if text:
                return text
            return f"[{agent_name}] (no response)"
        except Exception as e:
            import logging

            logging.error(f"Error generating DeepSeek comment: {e}")
            return f"[{agent_name}] (error: {str(e)[:50]})"

    if resolved_provider == "deepseek" and not DEEPSEEK_API_KEY:
        return f"[{agent_name}] (stub) DEEPSEEK_API_KEY not set..."

    if resolved_provider == "mistral" and MISTRAL_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=MISTRAL_API_KEY,
                base_url=MISTRAL_BASE_URL,
            )

            def _generate_mistral() -> Any:
                return client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt_context},
                    ],
                    temperature=0.7,
                )

            response = await asyncio.to_thread(_generate_mistral)
            usage = getattr(response, "usage", None)
            _record_usage(
                "mistral",
                getattr(response, "model", None) or resolved_model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            choice = response.choices[0] if getattr(response, "choices", None) else None
            message = getattr(choice, "message", None)
            text = getattr(message, "content", None)
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                    for part in text
                )
            if text:
                return text
            return f"[{agent_name}] (no response)"
        except Exception as e:
            import logging

            logging.error(f"Error generating Mistral comment: {e}")
            return f"[{agent_name}] (error: {str(e)[:50]})"

    if resolved_provider == "mistral" and not MISTRAL_API_KEY:
        return f"[{agent_name}] (stub) MISTRAL_API_KEY not set..."

    if resolved_provider == "gemini" and GEMINI_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=GEMINI_API_KEY,
                base_url=GEMINI_BASE_URL,
            )

            def _generate_gemini() -> Any:
                return client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt_context},
                    ],
                    temperature=0.7,
                )

            response = await asyncio.to_thread(_generate_gemini)
            usage = getattr(response, "usage", None)
            _record_usage(
                "gemini",
                getattr(response, "model", None) or resolved_model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            choice = response.choices[0] if getattr(response, "choices", None) else None
            message = getattr(choice, "message", None)
            text = getattr(message, "content", None)
            if text:
                return text
            return f"[{agent_name}] (no response)"
        except Exception as e:
            import logging
            logging.error(f"Error generating Gemini comment: {e}")
            return f"[{agent_name}] (error: {str(e)[:50]})"

    if resolved_provider == "gemini" and not GEMINI_API_KEY:
        return f"[{agent_name}] (stub) GEMINI_API_KEY not set..."

    if resolved_provider == "groq" and GROQ_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )

            def _generate() -> Any:
                return client.chat.completions.create(
                    model=resolved_model,
                    messages=[
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": prompt_context},
                    ],
                    temperature=0.7,
                )

            response = await asyncio.to_thread(_generate)
            usage = getattr(response, "usage", None)
            _record_usage(
                "groq",
                getattr(response, "model", None) or resolved_model,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
            choice = response.choices[0] if getattr(response, "choices", None) else None
            message = getattr(choice, "message", None)
            text = getattr(message, "content", None)
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                    for part in text
                )
            await asyncio.sleep(2)  # Groq free tier rate limit buffer
            if text:
                return text
            return f"[{agent_name}] (no response)"
        except Exception as e:
            import logging

            logging.error(f"Error generating Groq comment: {e}")
            return f"[{agent_name}] (error: {str(e)[:50]})"

    if resolved_provider == "groq" and not GROQ_API_KEY:
        return f"[{agent_name}] (stub) GROQ_API_KEY not set..."

    if resolved_provider != "openai":
        return f"[{agent_name}] (stub) unsupported provider: {resolved_provider}"

    if not OPENAI_API_KEY:
        return f"[{agent_name}] (stub) {prompt_context[:40]}..."

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)

        def _generate() -> Any:
            return client.responses.create(
                model=resolved_model,
                instructions=instructions,
                input=prompt_context,
                temperature=0.7,
            )

        response = None
        last_error: Optional[Exception] = None
        for attempt in range(OPENAI_MAX_RETRIES + 1):
            try:
                await _wait_for_openai_slot()
                response = await asyncio.to_thread(_generate)
                break
            except Exception as e:
                last_error = e
                if _is_rate_limit_error(e) and attempt < OPENAI_MAX_RETRIES:
                    backoff_seconds = (OPENAI_RETRY_BASE_DELAY_MS / 1000.0) * (2 ** attempt)
                    await asyncio.sleep(backoff_seconds)
                    continue
                raise

        if response is None and last_error is not None:
            raise last_error

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        if prompt_tokens is None:
            prompt_tokens = getattr(usage, "input_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        if completion_tokens is None:
            completion_tokens = getattr(usage, "output_tokens", None)

        _record_usage(
            "openai",
            getattr(response, "model", None) or resolved_model,
            prompt_tokens,
            completion_tokens,
        )
        text = getattr(response, "output_text", None)
        if text:
            return text
        return f"[{agent_name}] (no response)"

    except Exception as e:
        import logging

        logging.error(f"Error generating comment: {e}")
        return f"[{agent_name}] (error: {str(e)[:50]})"
