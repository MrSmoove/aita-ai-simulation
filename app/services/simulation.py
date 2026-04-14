"""
Multi-agent AITA simulation using camel-ai.
"""
import asyncio
import uuid
import random
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.schemas import Post, SimulationConfig, AgentAction, SimulationRun
from app.oasis import adapter as oasis
from app.services import storage


async def run_single_post(
    post: Post, 
    config: SimulationConfig, 
    run_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Orchestrate a multi-agent simulation.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())
    
    created_at = datetime.utcnow()
    
    # Initialize session
    session = await oasis.seed_post_to_oasis(post.dict(), config.model_name)
    
    timeline: List[AgentAction] = []
    metadata: Dict[str, Any] = {"comment_scores": {}}
    comment_scores: Dict[str, int] = metadata["comment_scores"]

    # Step 0: Optional OP first reply
    if config.op_enabled:
        op_resp = await oasis.generate_comment(
            session, 
            post.body, 
            "OP", 
            config.model_name
        )
        op_comment_id = f"{run_id}:0:op"
        timeline.append(AgentAction(
            agent_id="op", 
            text=op_resp, 
            step=0, 
            role="op",
            comment_id=op_comment_id,
        ))
        comment_scores[op_comment_id] = 0

    # Steps 1..N: Commenter agents
    for step in range(1, config.max_steps + 1):
        tasks = []
        for i in range(config.num_commenters):
            agent_name = f"commenter_{i+1}"
            # Use post title on first step, else last comment as context
            prompt = f"Title: {post.title}\n\nBody:\n{post.body}" if step == 1 else timeline[-1].text
            tasks.append(
                oasis.generate_comment(session, prompt, agent_name, config.model_name)
            )
        
        results = await asyncio.gather(*tasks)
        for i, text in enumerate(results):
            comment_id = f"{run_id}:{step}:c{i+1}"
            timeline.append(AgentAction(
                agent_id=f"c{i+1}", 
                text=text, 
                step=step, 
                role="commenter",
                comment_id=comment_id,
            ))
            comment_scores[comment_id] = 0

        # Voting phase (after comment generation): each agent votes once or passes.
        # Minimal behavior: random vote vs pass; random target among existing commenter comments.
        voter_ids = [f"c{i+1}" for i in range(config.num_commenters)]
        candidate_comment_ids = [
            a.comment_id
            for a in timeline
            if a.role == "commenter" and a.comment_id is not None
        ]
        if candidate_comment_ids:
            for _voter_id in voter_ids:
                will_vote = random.random() < 0.8  # 80% vote, 20% pass (simple + stable)
                if not will_vote:
                    continue
                target_id = random.choice(candidate_comment_ids)
                comment_scores[target_id] = comment_scores.get(target_id, 0) + 1

        # Allow OP to respond each step if enabled
        if config.op_enabled:
            op_prompt = " ".join([a.text for a in timeline[-config.num_commenters:]])
            op_resp = await oasis.generate_comment(
                session, 
                op_prompt, 
                "OP", 
                config.model_name
            )
            op_comment_id = f"{run_id}:{step}:op"
            timeline.append(AgentAction(
                agent_id="op", 
                text=op_resp, 
                step=step, 
                role="op",
                comment_id=op_comment_id,
            ))
            comment_scores[op_comment_id] = 0

    # Verdict computation (minimal): pick the highest-scored commenter top-level comment.
    # OP comments are excluded from verdict eligibility.
    eligible_comment_ids = {
        a.comment_id
        for a in timeline
        if a.role == "commenter" and a.comment_id is not None
    }
    eligible_scores = {cid: comment_scores.get(cid, 0) for cid in eligible_comment_ids}
    if eligible_scores:
        verdict_comment_id, verdict_score = max(eligible_scores.items(), key=lambda kv: kv[1])
        metadata["verdict_comment_id"] = verdict_comment_id
        metadata["verdict_score"] = verdict_score
    else:
        metadata["verdict_comment_id"] = None
        metadata["verdict_score"] = None

    # Build result
    run = SimulationRun(
        run_id=run_id,
        post=post,
        config=config,
        timeline=timeline,
        created_at=created_at,
        metadata=metadata,
    )

    out = run.dict()
    # Convert datetime to ISO string for JSON serialization
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    
    storage.save_run_db(run_id, post.post_id, config.dict(), out)
    storage.save_run_json(run_id, out)
    return out