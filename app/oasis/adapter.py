"""
CAMEL-AI LLM client integration.
"""
import os
import asyncio
import warnings
from typing import Any, Dict
from dotenv import load_dotenv

load_dotenv()

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType

from app import prompts

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("LLM_MODEL", "gpt-4-turbo")

if not OPENAI_API_KEY:
    warnings.warn("OPENAI_API_KEY not set. Responses will be stubs.")


async def seed_post_to_oasis(post_dict: Dict[str, Any], model_name: str = "gpt-4-turbo") -> Dict[str, str]:
    """
    Initialize a conversation session with the OP post.
    Returns dict with session_id for tracking.
    """
    session_id = f"session-{post_dict.get('post_id', 'unknown')}"
    return {"session_id": session_id}


async def generate_comment(
    session: Dict[str, str],
    prompt_context: str,
    agent_name: str,
    model_name: str = "gpt-4-turbo",
    role: str = "commenter",
) -> str:
    """Generate a comment using camel-ai ChatAgent."""
    
    if not OPENAI_API_KEY:
        return f"[{agent_name}] (stub) {prompt_context[:40]}..."
    
    try:
        # Create model
        model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type=ModelType.GPT_4_TURBO,
            model_config_dict={
                "api_key": OPENAI_API_KEY,
                "temperature": 0.7,
            },
        )
        
        # Create agent with correct API: system_prompt goes in the role_name + role_type
        agent = ChatAgent(
            role_name=agent_name,
            role_type=role,
            model=model,
        )
        
        # Generate response (run in thread to avoid blocking)
        user_msg = BaseMessage.make_user_message(
            role_name=agent_name,
            content=prompt_context,
        )
        
        response = await asyncio.to_thread(agent.step, user_msg)
        
        if response and len(response) > 0:
            return response[0].content
        return f"[{agent_name}] (no response)"
        
    except Exception as e:
        import logging
        logging.error(f"Error generating comment: {e}")
        return f"[{agent_name}] (error: {str(e)[:50]})"