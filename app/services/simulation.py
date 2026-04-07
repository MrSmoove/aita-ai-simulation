import asyncio
import uuid
from datetime import datetime
from typing import Dict, Any, List

from app.schemas import Post, SimulationConfig, AgentAction, SimulationRun
from app.oasis import adapter as oasis
from app.services import storage


async def run_single_post(post: Post, config: SimulationConfig) -> Dict[str, Any]:
    """
    Orchestrate a short multi-agent simulation.
    - seeds post into oasis
    - runs num_commenters agents for max_steps
    - optionally runs an OP reply after seeding and between steps
    """
    run_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    session = await oasis.seed_post_to_oasis(post.dict(), config.model_name)

    timeline: List[AgentAction] = []

    # Optional OP first reply
    if config.op_enabled:
        op_resp = await oasis.generate_comment(session["session_id"], post.body, "OP", config.model_name)
        timeline.append(AgentAction(agent_id="op", text=op_resp, step=0, role="op"))

    # commenter agents
    for step in range(1, config.max_steps + 1):
        tasks = []
        for i in range(config.num_commenters):
            agent_name = f"commenter_{i+1}"
            prompt = post.title if step == 1 else timeline[-1].text
            tasks.append(oasis.generate_comment(session["session_id"], prompt, agent_name, config.model_name))
        results = await asyncio.gather(*tasks)
        for i, text in enumerate(results):
            timeline.append(AgentAction(agent_id=f"c{i+1}", text=text, step=step, role="commenter"))

        # allow OP to respond each step if enabled
        if config.op_enabled:
            op_prompt = " ".join([a.text for a in timeline[-config.num_commenters:]])
            op_resp = await oasis.generate_comment(session["session_id"], op_prompt, "OP", config.model_name)
            timeline.append(AgentAction(agent_id="op", text=op_resp, step=step, role="op"))

    run = SimulationRun(
        run_id=run_id,
        post=post,
        config=config,
        timeline=timeline,
        created_at=created_at,
    )

    out = run.dict()
    storage.save_run_db(run_id, post.post_id, config.dict(), out)
    storage.save_run_json(run_id, out)
    return out