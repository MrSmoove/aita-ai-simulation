"""
Direct LLM provider integration for simulation agents.
"""
import asyncio
import os
import warnings
from contextvars import ContextVar
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from app import prompts

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()

PROVIDER_DEFAULT_MODELS = {
    "openai": OPENAI_MODEL,
    "gemini": GEMINI_MODEL,
    "groq": GROQ_MODEL,
}

MODEL_ALIASES = {
    "oasis-small": {
        "openai": OPENAI_MODEL,
        "gemini": GEMINI_MODEL,
        "groq": GROQ_MODEL,
    }
}

if not OPENAI_API_KEY and not GEMINI_API_KEY and not GROQ_API_KEY:
    warnings.warn("No LLM API key set (OPENAI_API_KEY, GEMINI_API_KEY, or GROQ_API_KEY). Responses will be stubs.")


_usage_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("usage_context", default=None)


def available_providers() -> list[str]:
    providers = []
    if OPENAI_API_KEY:
        providers.append("openai")
    if GEMINI_API_KEY:
        providers.append("gemini")
    if GROQ_API_KEY:
        providers.append("groq")
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

    if resolved_provider == "gemini" and GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)

            def _generate() -> Any:
                return client.models.generate_content(
                    model=resolved_model,
                    contents=f"{instructions}\n\n{prompt_context}",
                )

            resp = await asyncio.to_thread(_generate)
            usage = getattr(resp, "usage_metadata", None)
            _record_usage(
                "gemini",
                resolved_model,
                getattr(usage, "prompt_token_count", None),
                getattr(usage, "candidates_token_count", None),
            )
            text = getattr(resp, "text", None)
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

        response = await asyncio.to_thread(_generate)
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
