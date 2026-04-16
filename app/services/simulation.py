"""
Multi-agent AITA simulation using direct LLM providers.
"""
import asyncio
import uuid
import random
import itertools
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.schemas import Post, SimulationConfig, AgentAction, SimulationRun
from app.llm import adapter as llm
from app.services import storage

COMMENTER_ARCHETYPES = [
    "blunt and practical",
    "dry and sarcastic",
    "empathetic but firm",
    "petty and amused",
    "skeptical and suspicious",
    "mildly judgmental but fair",
]
FOCUS_AREAS = [
    "workplace etiquette",
    "boundaries and respect",
    "fairness and consistency",
    "tone and delivery",
    "social awkwardness",
    "common sense practicality",
]
RESPONSE_LENGTHS = [
    "very short",
    "short",
    "medium-short",
]
DEBATE_STYLES = [
    "likely to challenge another commenter directly",
    "more likely to add a fresh angle than argue",
    "likes backing someone up with a sharper take",
    "likes pushing back on bad reasoning",
]
JUDGMENT_TEMPOS = [
    "quick to judge",
    "slow to judge",
    "likes weighing nuance before deciding",
    "reacts strongly to bad tone",
]
SYMPATHY_BIASES = [
    "tends to sympathize with socially awkward people",
    "tends to sympathize with the person setting boundaries",
    "does not automatically sympathize with the narrator",
    "is alert to missing context and unreliable framing",
]


def _build_commenter_profiles(num_commenters: int) -> List[Dict[str, str]]:
    combinations = sorted(
        itertools.product(
            COMMENTER_ARCHETYPES,
            FOCUS_AREAS,
            RESPONSE_LENGTHS,
            DEBATE_STYLES,
            JUDGMENT_TEMPOS,
            SYMPATHY_BIASES,
        )
    )

    step = max(1, len(combinations) // max(1, num_commenters))

    profiles: List[Dict[str, str]] = []
    for index in range(num_commenters):
        tone, focus, length, debate_style, judgment_tempo, sympathy_bias = combinations[
            (index * step) % len(combinations)
        ]
        profiles.append(
            {
                "agent_id": f"c{index + 1}",
                "tone": tone,
                "focus_area": focus,
                "response_length": length,
                "debate_style": debate_style,
                "judgment_tempo": judgment_tempo,
                "sympathy_bias": sympathy_bias,
            }
        )
    return profiles


def _build_commenter_prompt(
    post: Post,
    step: int,
    profile: Dict[str, str],
    parent_text: Optional[str] = None,
    parent_role: Optional[str] = None,
) -> str:
    base = (
        "You are a Reddit commenter on r/AmItheAsshole.\n"
        "Write one short AITA-style comment in your own words.\n"
        "Do not start with your username or labels like commenter_1, c1, or OP.\n"
        "Avoid copying the same phrasing as other commenters.\n"
        "Be opinionated and sound like a distinct person.\n\n"
        f"Your tone: {profile['tone']}.\n"
        f"Your focus: {profile['focus_area']}.\n"
        f"Your preferred length: {profile['response_length']}.\n"
        f"Your interaction style: {profile['debate_style']}.\n\n"
        f"How fast you judge: {profile['judgment_tempo']}.\n"
        f"Your sympathy bias: {profile['sympathy_bias']}.\n\n"
        f"Post title: {post.title}\n\n"
        f"Post body:\n{post.body}\n"
    )
    if step == 1 or not parent_text:
        return (
            f"{base}\n"
            "Write an independent top-level reply to the post.\n"
            "Do not try to match an imagined consensus.\n"
            "Decide your own reaction from the post itself."
        )
    return (
        f"{base}\n"
        f"You are replying to {parent_role or 'another commenter'}.\n"
        f"Their comment was:\n{parent_text}\n\n"
        "React to that comment while still addressing the original post.\n"
        "Do not just restate their point in slightly different words."
    )


def _build_op_prompt(post: Post, target_comment_text: str) -> str:
    return (
        f"You are the OP replying on your own AITA thread.\n"
        "Reply briefly in 1-2 sentences. You can clarify, defend yourself, or acknowledge a fair point.\n"
        "Do not give a fresh top-level verdict on your own post.\n\n"
        f"Original post title: {post.title}\n\n"
        f"Original post body:\n{post.body}\n\n"
        f"You are replying to this comment:\n{target_comment_text}\n"
    )


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
    session = await llm.seed_session(post.dict(), config.model_name)
    
    timeline: List[AgentAction] = []
    commenter_profiles = _build_commenter_profiles(config.num_commenters)
    profile_by_agent_id = {profile["agent_id"]: profile for profile in commenter_profiles}

    metadata: Dict[str, Any] = {
        "comment_scores": {},
        "commenter_profiles": commenter_profiles,
    }
    comment_scores: Dict[str, int] = metadata["comment_scores"]
    latest_op_comment_id: Optional[str] = None
    latest_round_comment_ids: List[str] = []
    comment_text_by_id: Dict[str, str] = {}
    comment_role_by_id: Dict[str, str] = {}

    # Steps 1..N: Commenter agents
    for step in range(1, config.max_steps + 1):
        tasks = []
        pending_comment_meta: List[Dict[str, Optional[str]]] = []
        for i in range(config.num_commenters):
            agent_id = f"c{i+1}"
            agent_name = f"commenter_{i+1}"
            profile = profile_by_agent_id[agent_id]
            parent_comment_id: Optional[str] = None
            if step > 1:
                target_pool = latest_round_comment_ids + ([latest_op_comment_id] if latest_op_comment_id else [])
                if target_pool:
                    parent_comment_id = random.choice(target_pool)
            parent_text = comment_text_by_id.get(parent_comment_id) if parent_comment_id else None
            parent_role = comment_role_by_id.get(parent_comment_id) if parent_comment_id else None
            prompt = _build_commenter_prompt(
                post=post,
                step=step,
                profile=profile,
                parent_text=parent_text,
                parent_role=parent_role,
            )
            tasks.append(
                llm.generate_comment(session, prompt, agent_name, config.model_name)
            )
            pending_comment_meta.append({"parent_comment_id": parent_comment_id})
        
        results = await asyncio.gather(*tasks)
        current_round_comment_ids: List[str] = []
        for i, text in enumerate(results):
            comment_id = f"{run_id}:{step}:c{i+1}"
            parent_comment_id = pending_comment_meta[i]["parent_comment_id"]
            timeline.append(AgentAction(
                agent_id=f"c{i+1}", 
                text=text, 
                step=step, 
                role="commenter",
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
            ))
            comment_scores[comment_id] = 0
            comment_text_by_id[comment_id] = text
            comment_role_by_id[comment_id] = "OP" if agent_id == "op" else "another commenter"
            current_round_comment_ids.append(comment_id)

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
        if config.op_enabled and current_round_comment_ids:
            reply_target_id = max(
                current_round_comment_ids,
                key=lambda cid: comment_scores.get(cid, 0),
            )
            reply_target_text = comment_text_by_id[reply_target_id]
            op_prompt = _build_op_prompt(post, reply_target_text)
            op_resp = await llm.generate_comment(
                session, 
                op_prompt, 
                "OP", 
                config.model_name,
                role="op",
            )
            op_comment_id = f"{run_id}:{step}:op"
            timeline.append(AgentAction(
                agent_id="op", 
                text=op_resp, 
                step=step, 
                role="op",
                comment_id=op_comment_id,
                parent_comment_id=reply_target_id,
            ))
            comment_scores[op_comment_id] = 0
            comment_text_by_id[op_comment_id] = op_resp
            comment_role_by_id[op_comment_id] = "OP"
            latest_op_comment_id = op_comment_id

        latest_round_comment_ids = current_round_comment_ids

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
