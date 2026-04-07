from __future__ import annotations

import os
from typing import Any

from oasis import ActionType, LLMAction, ManualAction

from app.models import ScrapedPost
from app.op_agent import build_op_agent
from app.oasis_adapter import build_model, build_agent_graph, make_env
from app.storage import save_run


async def run_single_post(
    post: ScrapedPost,
    profile_path: str,
    db_path: str,
    out_path: str,
    max_steps: int = 3,
) -> dict[str, Any]:
    if os.path.exists(db_path):
        os.remove(db_path)

    model = build_model()
    agent_graph = await build_agent_graph(profile_path, model)
    env = make_env(agent_graph, db_path)

    await env.reset()

    # Seed the real scraped Reddit post through a manual action.
    # For now, agent 0 creates the initial post with the scraped content.
    # Later, you can replace this with a more explicit seeded-post insertion flow.
    seeded_content = f"{post.title}\n\n{post.body}".strip()

    actions_0 = {
        env.agent_graph.get_agent(0): ManualAction(
            action_type=ActionType.CREATE_POST,
            action_args={"content": seeded_content},
        )
    }
    await env.step(actions_0)

    op_agent = build_op_agent(post)

    run_log: dict[str, Any] = {
        "post_id": post.post_id,
        "title": post.title,
        "true_verdict": post.true_verdict,
        "op_agent": op_agent.model_dump(),
        "steps": [],
    }

    for step_idx in range(max_steps):
        actions = {
            agent: LLMAction()
            for _, agent in env.agent_graph.get_agents()
        }
        await env.step(actions)
        run_log["steps"].append({"step": step_idx + 1, "status": "completed"})

    await env.close()
    save_run(out_path, run_log)
    return run_log