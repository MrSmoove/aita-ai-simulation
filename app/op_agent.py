from __future__ import annotations

from app.models import ScrapedPost, OPAgentConfig


def build_op_agent(post: ScrapedPost) -> OPAgentConfig:
    grounding = f"{post.title}\n\n{post.body}".strip()
    return OPAgentConfig(
        agent_id=f"op_{post.post_id}",
        source_post_id=post.post_id,
        grounding_text=grounding,
        allowed_actions=[
            "CREATE_COMMENT",
            "REFRESH",
            "DO_NOTHING",
        ],
    )