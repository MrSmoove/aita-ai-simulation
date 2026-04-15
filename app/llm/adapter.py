"""
Direct LLM provider integration for simulation agents.
"""
import asyncio
import os
import warnings
from typing import Any, Dict

from dotenv import load_dotenv

from app import prompts

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()

MODEL_ALIASES = {
    # Backward compatibility for older saved configs.
    "oasis-small": {
        "openai": OPENAI_MODEL,
        "gemini": GEMINI_MODEL,
    }
}

if not OPENAI_API_KEY and not GEMINI_API_KEY:
    warnings.warn("No LLM API key set (OPENAI_API_KEY or GEMINI_API_KEY). Responses will be stubs.")


def resolve_model_name(model_name: str) -> str:
    provider_aliases = MODEL_ALIASES.get(model_name, {})
    return provider_aliases.get(LLM_PROVIDER, model_name)


def _build_instruction(agent_name: str, role: str) -> str:
    role_blurb = (
        "You are the original poster responding to the thread."
        if role == "op"
        else "You are one distinct commenter in the thread."
    )
    return f"{prompts.system_prompt()}\n\n{role_blurb}\nYour visible username is {agent_name}."


def _print_openai_usage(response: Any) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return

    prompt_tokens = getattr(usage, "prompt_tokens", None)
    if prompt_tokens is None:
        prompt_tokens = getattr(usage, "input_tokens", None)

    completion_tokens = getattr(usage, "completion_tokens", None)
    if completion_tokens is None:
        completion_tokens = getattr(usage, "output_tokens", None)

    print(f"prompt_tokens={prompt_tokens}")
    print(f"completion_tokens={completion_tokens}")
    print(f"model={getattr(response, 'model', None)}")


async def seed_session(post_dict: Dict[str, Any], model_name: str = "gpt-4.1-mini") -> Dict[str, str]:
    """
    Preserve a lightweight session object for future thread state.
    """
    return {
        "session_id": f"session-{post_dict.get('post_id', 'unknown')}",
        "post_id": post_dict.get("post_id", "unknown"),
        "model_name": resolve_model_name(model_name),
    }


async def generate_comment(
    session: Dict[str, str],
    prompt_context: str,
    agent_name: str,
    model_name: str = "gpt-4.1-mini",
    role: str = "commenter",
) -> str:
    """Generate a comment via the configured provider."""
    resolved_model = resolve_model_name(model_name)
    instructions = _build_instruction(agent_name, role)

    if LLM_PROVIDER == "gemini" and GEMINI_API_KEY:
        try:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)

            def _generate() -> Any:
                return client.models.generate_content(
                    model=resolved_model,
                    contents=f"{instructions}\n\n{prompt_context}",
                )

            resp = await asyncio.to_thread(_generate)
            text = getattr(resp, "text", None)
            if text:
                return text
            return f"[{agent_name}] (no response)"
        except Exception as e:
            import logging

            logging.error(f"Error generating Gemini comment: {e}")
            return f"[{agent_name}] (error: {str(e)[:50]})"

    if LLM_PROVIDER == "gemini" and not GEMINI_API_KEY:
        return f"[{agent_name}] (stub) GEMINI_API_KEY not set..."

    if LLM_PROVIDER != "openai":
        return f"[{agent_name}] (stub) unsupported provider: {LLM_PROVIDER}"

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
        _print_openai_usage(response)
        text = getattr(response, "output_text", None)
        if text:
            return text
        return f"[{agent_name}] (no response)"

    except Exception as e:
        import logging

        logging.error(f"Error generating comment: {e}")
        return f"[{agent_name}] (error: {str(e)[:50]})"
