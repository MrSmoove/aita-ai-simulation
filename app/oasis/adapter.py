import asyncio
from typing import Any, Dict, List

# Minimal async adapter stub for camel-oasis. Replace with real client integration.
async def seed_post_to_oasis(post: Dict[str, Any], model_name: str) -> Dict[str, Any]:
    # In real code: call oasis client to create a conversation/seed the post
    await asyncio.sleep(0.1)
    return {"session_id": f"seed-{post.get('post_id')}", "model": model_name}


async def generate_comment(session_id: str, prompt: str, agent_name: str, model_name: str) -> str:
    # Replace with actual call to camel-oasis generation API
    await asyncio.sleep(0.1)
    # Very simple deterministic stub so runs are reproducible-ish
    return f"[{agent_name} @ {model_name}] Reply to '{prompt[:40]}...'"