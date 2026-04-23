"""
Multi-agent AITA simulation using direct LLM providers.
"""
import asyncio
import itertools
import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm import adapter as llm
from app.schemas import AgentAction, BatchPostResult, BatchRun, Post, SimulationConfig, SimulationRun
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
ACTIVITY_STYLES = [
    {"label": "drive-by commenter", "return_probability": 0.08, "max_comments": 1, "reply_likelihood": 0.15, "vote_likelihood": 0.55},
    {"label": "casual regular", "return_probability": 0.28, "max_comments": 2, "reply_likelihood": 0.4, "vote_likelihood": 0.72},
    {"label": "thread camper", "return_probability": 0.5, "max_comments": 3, "reply_likelihood": 0.68, "vote_likelihood": 0.82},
]
TIMELINE_24H = [
    {"step": 1, "label": "0-2h", "start_min": 0, "end_min": 120, "arrival_pct": 0.25, "top_level_bias": 0.88, "return_share": 0.0, "op_reply_rate": 0.7},
    {"step": 2, "label": "2-5h", "start_min": 121, "end_min": 300, "arrival_pct": 0.30, "top_level_bias": 0.74, "return_share": 0.18, "op_reply_rate": 0.6},
    {"step": 3, "label": "5-8h", "start_min": 301, "end_min": 480, "arrival_pct": 0.20, "top_level_bias": 0.55, "return_share": 0.24, "op_reply_rate": 0.52},
    {"step": 4, "label": "8-12h", "start_min": 481, "end_min": 720, "arrival_pct": 0.12, "top_level_bias": 0.38, "return_share": 0.28, "op_reply_rate": 0.38},
    {"step": 5, "label": "12-18h", "start_min": 721, "end_min": 1080, "arrival_pct": 0.08, "top_level_bias": 0.24, "return_share": 0.22, "op_reply_rate": 0.24},
    {"step": 6, "label": "18-24h", "start_min": 1081, "end_min": 1440, "arrival_pct": 0.05, "top_level_bias": 0.14, "return_share": 0.16, "op_reply_rate": 0.12},
]


def _build_basic_schedule(max_steps: int) -> List[Dict[str, Any]]:
    schedule: List[Dict[str, Any]] = []
    counts = max(1, max_steps)
    bucket_size = max(10, 180 // counts)
    for index in range(counts):
        schedule.append(
            {
                "step": index + 1,
                "label": f"Wave {index + 1}",
                "start_min": index * bucket_size,
                "end_min": ((index + 1) * bucket_size) - 1,
                "arrival_pct": 1 / counts,
                "top_level_bias": max(0.22, 0.82 - (index * 0.12)),
                "return_share": min(0.28, 0.08 + (index * 0.04)),
                "op_reply_rate": max(0.18, 0.58 - (index * 0.08)),
            }
        )
    return schedule


def _build_wave_schedule(timeline_mode: str, max_steps: int) -> List[Dict[str, Any]]:
    if timeline_mode == "24h":
        return [dict(bucket) for bucket in TIMELINE_24H]
    return _build_basic_schedule(max_steps)


def _allocate_counts(total: int, percentages: List[float]) -> List[int]:
    if total <= 0:
        return [0 for _ in percentages]

    raw = [total * pct for pct in percentages]
    counts = [int(value) for value in raw]
    remainder = total - sum(counts)
    fractions = sorted(
        range(len(percentages)),
        key=lambda idx: raw[idx] - counts[idx],
        reverse=True,
    )
    for idx in fractions[:remainder]:
        counts[idx] += 1
    return counts


def _scaled_num_commenters(real_num_comments: int, commenter_cap: int) -> int:
    if real_num_comments <= 0:
        return min(10, commenter_cap)
    return max(10, min(round(real_num_comments ** 0.5), commenter_cap))


def _empty_usage_summary() -> Dict[str, Any]:
    return {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "models": {},
        "providers": {},
    }


def _normalize_usage_summary(usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    summary = _empty_usage_summary()
    if not usage:
        return summary

    summary["request_count"] = int(usage.get("request_count", 0) or 0)
    summary["prompt_tokens"] = int(usage.get("prompt_tokens", 0) or 0)
    summary["completion_tokens"] = int(usage.get("completion_tokens", 0) or 0)
    summary["total_tokens"] = summary["prompt_tokens"] + summary["completion_tokens"]
    summary["models"] = dict(usage.get("models", {}))
    summary["providers"] = dict(usage.get("providers", {}))
    return summary


def _merge_usage_summaries(summaries: List[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    merged = _empty_usage_summary()
    for usage in summaries:
        normalized = _normalize_usage_summary(usage)
        merged["request_count"] += normalized["request_count"]
        merged["prompt_tokens"] += normalized["prompt_tokens"]
        merged["completion_tokens"] += normalized["completion_tokens"]
        for model_name, count in normalized["models"].items():
            merged["models"][model_name] = merged["models"].get(model_name, 0) + count
        for provider_name, count in normalized["providers"].items():
            merged["providers"][provider_name] = merged["providers"].get(provider_name, 0) + count
    merged["total_tokens"] = merged["prompt_tokens"] + merged["completion_tokens"]
    return merged


def _build_commenter_profiles(num_commenters: int) -> List[Dict[str, Any]]:
    combinations = sorted(
        itertools.product(
            COMMENTER_ARCHETYPES,
            FOCUS_AREAS,
            RESPONSE_LENGTHS,
            DEBATE_STYLES,
            JUDGMENT_TEMPOS,
            SYMPATHY_BIASES,
            range(len(ACTIVITY_STYLES)),
        )
    )

    step = max(1, len(combinations) // max(1, num_commenters))
    profiles: List[Dict[str, Any]] = []
    for index in range(num_commenters):
        tone, focus, length, debate_style, judgment_tempo, sympathy_bias, activity_index = combinations[
            (index * step) % len(combinations)
        ]
        activity = ACTIVITY_STYLES[activity_index]
        profiles.append(
            {
                "agent_id": f"c{index + 1}",
                "tone": tone,
                "focus_area": focus,
                "response_length": length,
                "debate_style": debate_style,
                "judgment_tempo": judgment_tempo,
                "sympathy_bias": sympathy_bias,
                "activity_style": activity["label"],
                "return_probability": activity["return_probability"],
                "max_comments": activity["max_comments"],
                "reply_likelihood": activity["reply_likelihood"],
                "vote_likelihood": activity["vote_likelihood"],
                "arrival_wave": 1,
            }
        )
    return profiles


def _assign_arrival_waves(profiles: List[Dict[str, Any]], schedule: List[Dict[str, Any]]) -> None:
    counts = _allocate_counts(len(profiles), [bucket["arrival_pct"] for bucket in schedule])
    shuffled = profiles[:]
    random.shuffle(shuffled)
    cursor = 0
    for wave_index, count in enumerate(counts, start=1):
        for profile in shuffled[cursor: cursor + count]:
            profile["arrival_wave"] = wave_index
        cursor += count
    for profile in shuffled[cursor:]:
        profile["arrival_wave"] = len(schedule)


def _build_commenter_prompt(
    post: Post,
    bucket_label: str,
    profile: Dict[str, Any],
    is_top_level: bool,
    parent_text: Optional[str] = None,
    parent_role: Optional[str] = None,
) -> str:
    base = (
        "You are a Reddit commenter on r/AmItheAsshole.\n"
        "Write one short AITA-style comment in your own words.\n"
        "Do not start with your username or labels like commenter_1, c1, or OP.\n"
        "Avoid copying the same phrasing as other commenters.\n"
        "Be opinionated and sound like a distinct person.\n\n"
        f"Thread age: {bucket_label} after the original post.\n"
        f"Your tone: {profile['tone']}.\n"
        f"Your focus: {profile['focus_area']}.\n"
        f"Your preferred length: {profile['response_length']}.\n"
        f"Your interaction style: {profile['debate_style']}.\n"
        f"How fast you judge: {profile['judgment_tempo']}.\n"
        f"Your sympathy bias: {profile['sympathy_bias']}.\n"
        f"Your thread behavior: {profile['activity_style']}.\n\n"
        f"Post title: {post.title}\n\n"
        f"Post body:\n{post.body}\n"
    )
    if is_top_level or not parent_text:
        return (
            f"{base}\n"
            "Write a direct top-level reply to the post.\n"
            "Do not copy an imaginary consensus. Decide your own reaction."
        )
    return (
        f"{base}\n"
        f"You are replying to {parent_role or 'another commenter'}.\n"
        f"Their comment was:\n{parent_text}\n\n"
        "React to that comment while still addressing the original post.\n"
        "Do not just repeat them in slightly different words."
    )


def _build_op_prompt(post: Post, bucket_label: str, target_comment_text: str) -> str:
    return (
        "You are the OP replying on your own AITA thread.\n"
        "Reply briefly in 1-2 sentences. You can clarify, defend yourself, or acknowledge a fair point.\n"
        "Do not give yourself a verdict.\n\n"
        f"Thread age: {bucket_label} after posting.\n"
        f"Original post title: {post.title}\n\n"
        f"Original post body:\n{post.body}\n\n"
        f"You are replying to this comment:\n{target_comment_text}\n"
    )


def _sample_wave_minutes(start_min: int, end_min: int, count: int) -> List[int]:
    if count <= 0:
        return []
    if end_min <= start_min:
        return [start_min for _ in range(count)]
    return sorted(random.randint(start_min, end_min) for _ in range(count))


def _choose_reply_target(
    candidate_comment_ids: List[str],
    comment_scores: Dict[str, int],
    depth_by_id: Dict[str, int],
    comment_role_by_id: Dict[str, str],
    reply_counts: Dict[str, int],
    comment_step_by_id: Dict[str, int],
    current_step: int,
) -> Optional[str]:
    if not candidate_comment_ids:
        return None

    weights = []
    for comment_id in candidate_comment_ids:
        depth = depth_by_id.get(comment_id, 0)
        score = comment_scores.get(comment_id, 0)
        age = max(0, current_step - comment_step_by_id.get(comment_id, current_step))
        role_multiplier = 0.72 if comment_role_by_id.get(comment_id) == "OP" else 1.0
        depth_multiplier = {0: 1.9, 1: 1.3, 2: 0.72, 3: 0.38}.get(min(depth, 3), 0.25)
        momentum = 1 + min(reply_counts.get(comment_id, 0), 6) * 0.16
        visibility = 1 + min(score, 24) * 0.12 + min(age, 6) * 0.07
        weights.append(max(0.05, role_multiplier * depth_multiplier * momentum * visibility))

    return random.choices(candidate_comment_ids, weights=weights, k=1)[0]


def _select_returning_profiles(
    arrived_profiles: List[Dict[str, Any]],
    step: int,
    wave: Dict[str, Any],
    action_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    eligible = [
        profile
        for profile in arrived_profiles
        if profile["arrival_wave"] < step
        and action_counts.get(profile["agent_id"], 0) < profile["max_comments"]
        and random.random() < profile["return_probability"]
    ]
    random.shuffle(eligible)
    target = round(len(arrived_profiles) * wave["return_share"])
    return eligible[:target]


def _vote_on_comments(
    voter_profiles: List[Dict[str, Any]],
    candidate_comment_ids: List[str],
    comment_scores: Dict[str, int],
    depth_by_id: Dict[str, int],
    comment_step_by_id: Dict[str, int],
    current_step: int,
) -> None:
    if not candidate_comment_ids:
        return

    for voter in voter_profiles:
        if random.random() > voter.get("vote_likelihood", 0.65):
            continue

        weights = []
        for comment_id in candidate_comment_ids:
            depth = depth_by_id.get(comment_id, 0)
            score = comment_scores.get(comment_id, 0)
            age = max(0, current_step - comment_step_by_id.get(comment_id, current_step))
            depth_multiplier = {0: 1.65, 1: 1.18, 2: 0.82, 3: 0.5}.get(min(depth, 3), 0.35)
            visibility = 1 + min(score, 24) * 0.1 + min(age, 6) * 0.08
            weights.append(max(0.05, depth_multiplier * visibility))

        target_id = random.choices(candidate_comment_ids, weights=weights, k=1)[0]
        comment_scores[target_id] = comment_scores.get(target_id, 0) + 1


def _build_provider_plan(
    total_posts: int,
    provider_strategy: str,
    provider: Optional[str],
    model_name: Optional[str],
) -> List[Dict[str, str]]:
    strategy = (provider_strategy or "balanced").strip().lower()
    if strategy == "single":
        chosen_provider = llm.resolve_provider(provider)
        chosen_model = llm.resolve_model_name(chosen_provider, model_name)
        return [{"provider": chosen_provider, "model_name": chosen_model} for _ in range(total_posts)]

    available = llm.available_providers()
    ordered = [name for name in ["openai", "gemini", "groq"] if name in available]
    if not ordered:
        ordered = [llm.resolve_provider(provider)]

    return [
        {
            "provider": ordered[index % len(ordered)],
            "model_name": llm.resolve_model_name(ordered[index % len(ordered)], None),
        }
        for index in range(total_posts)
    ]


async def run_single_post(
    post: Post,
    config: SimulationConfig,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrate a multi-agent simulation.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    created_at = datetime.utcnow()
    usage_token, _ = llm.begin_usage_capture()
    try:
        session = await llm.seed_session(
            post.dict(),
            model_name=config.model_name,
            provider=config.provider,
        )
        resolved_provider = session["provider"]
        resolved_model_name = session["model_name"]
        resolved_config = SimulationConfig(
            model_name=resolved_model_name,
            provider=resolved_provider,
            num_commenters=config.num_commenters,
            max_steps=len(_build_wave_schedule(config.timeline_mode, config.max_steps)),
            op_enabled=config.op_enabled,
            timeline_mode=config.timeline_mode,
        )

        schedule = _build_wave_schedule(resolved_config.timeline_mode, resolved_config.max_steps)
        commenter_profiles = _build_commenter_profiles(resolved_config.num_commenters)
        _assign_arrival_waves(commenter_profiles, schedule)
        profile_by_agent_id = {profile["agent_id"]: profile for profile in commenter_profiles}

        timeline: List[AgentAction] = []
        metadata: Dict[str, Any] = {
            "comment_scores": {},
            "commenter_profiles": commenter_profiles,
            "timeline_mode": resolved_config.timeline_mode,
            "wave_schedule": schedule,
            "provider": resolved_provider,
            "model_name": resolved_model_name,
        }
        comment_scores: Dict[str, int] = metadata["comment_scores"]
        action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        comment_text_by_id: Dict[str, str] = {}
        comment_role_by_id: Dict[str, str] = {}
        comment_step_by_id: Dict[str, int] = {}
        depth_by_id: Dict[str, int] = {}
        reply_counts: Dict[str, int] = {}
        latest_op_comment_id: Optional[str] = None

        for wave in schedule:
            step = wave["step"]
            bucket_label = wave["label"]
            new_arrivals = [profile for profile in commenter_profiles if profile["arrival_wave"] == step]
            arrived_profiles = [profile for profile in commenter_profiles if profile["arrival_wave"] <= step]
            returning_profiles = _select_returning_profiles(arrived_profiles, step, wave, action_counts)

            participant_meta = [{"profile": profile, "is_new_arrival": True} for profile in new_arrivals]
            participant_meta.extend({"profile": profile, "is_new_arrival": False} for profile in returning_profiles)
            random.shuffle(participant_meta)

            visible_comment_ids = [
                action.comment_id
                for action in timeline
                if action.comment_id is not None
            ]
            sampled_minutes = _sample_wave_minutes(wave["start_min"], wave["end_min"], len(participant_meta))
            tasks = []
            pending_comment_meta: List[Dict[str, Any]] = []

            for meta, simulated_minute in zip(participant_meta, sampled_minutes):
                profile = meta["profile"]
                agent_id = profile["agent_id"]
                agent_name = f"commenter_{agent_id[1:]}"
                wants_reply = (
                    bool(visible_comment_ids)
                    and random.random() < profile["reply_likelihood"]
                    and random.random() > wave["top_level_bias"] * (1.0 if meta["is_new_arrival"] else 0.75)
                )
                parent_comment_id = None
                if wants_reply:
                    parent_comment_id = _choose_reply_target(
                        candidate_comment_ids=visible_comment_ids,
                        comment_scores=comment_scores,
                        depth_by_id=depth_by_id,
                        comment_role_by_id=comment_role_by_id,
                        reply_counts=reply_counts,
                        comment_step_by_id=comment_step_by_id,
                        current_step=step,
                    )

                parent_text = comment_text_by_id.get(parent_comment_id) if parent_comment_id else None
                parent_role = comment_role_by_id.get(parent_comment_id) if parent_comment_id else None
                prompt = _build_commenter_prompt(
                    post=post,
                    bucket_label=bucket_label,
                    profile=profile,
                    is_top_level=parent_comment_id is None,
                    parent_text=parent_text,
                    parent_role=parent_role,
                )
                tasks.append(
                    llm.generate_comment(
                        session,
                        prompt,
                        agent_name,
                        model_name=resolved_model_name,
                        provider=resolved_provider,
                    )
                )
                pending_comment_meta.append(
                    {
                        "agent_id": agent_id,
                        "parent_comment_id": parent_comment_id,
                        "simulated_minute": simulated_minute,
                        "bucket_label": bucket_label,
                    }
                )

            results = await asyncio.gather(*tasks)
            current_wave_comment_ids: List[str] = []
            for index, text in enumerate(results):
                pending = pending_comment_meta[index]
                comment_id = f"{run_id}:{step}:{pending['agent_id']}:{action_counts[pending['agent_id']] + 1}"
                parent_comment_id = pending["parent_comment_id"]
                depth = 0 if not parent_comment_id else min(depth_by_id.get(parent_comment_id, 0) + 1, 4)
                timeline.append(
                    AgentAction(
                        agent_id=pending["agent_id"],
                        text=text,
                        step=step,
                        role="commenter",
                        comment_id=comment_id,
                        parent_comment_id=parent_comment_id,
                        provider=resolved_provider,
                        model_name=resolved_model_name,
                        simulated_minute=pending["simulated_minute"],
                        bucket_label=pending["bucket_label"],
                    )
                )
                action_counts[pending["agent_id"]] += 1
                comment_scores[comment_id] = comment_scores.get(comment_id, 0)
                comment_text_by_id[comment_id] = text
                comment_role_by_id[comment_id] = pending["agent_id"]
                comment_step_by_id[comment_id] = step
                depth_by_id[comment_id] = depth
                if parent_comment_id:
                    reply_counts[parent_comment_id] = reply_counts.get(parent_comment_id, 0) + 1
                current_wave_comment_ids.append(comment_id)

            candidate_comment_ids = [
                action.comment_id
                for action in timeline
                if action.role == "commenter" and action.comment_id is not None
            ]
            _vote_on_comments(
                voter_profiles=arrived_profiles,
                candidate_comment_ids=candidate_comment_ids,
                comment_scores=comment_scores,
                depth_by_id=depth_by_id,
                comment_step_by_id=comment_step_by_id,
                current_step=step,
            )

            if (
                resolved_config.op_enabled
                and current_wave_comment_ids
                and random.random() < wave["op_reply_rate"]
            ):
                reply_target_id = max(
                    current_wave_comment_ids,
                    key=lambda cid: comment_scores.get(cid, 0),
                )
                op_prompt = _build_op_prompt(
                    post=post,
                    bucket_label=bucket_label,
                    target_comment_text=comment_text_by_id[reply_target_id],
                )
                op_resp = await llm.generate_comment(
                    session,
                    op_prompt,
                    "OP",
                    model_name=resolved_model_name,
                    role="op",
                    provider=resolved_provider,
                )
                op_comment_id = f"{run_id}:{step}:op"
                op_minute = min(wave["end_min"], max(wave["start_min"], wave["end_min"] - 1))
                op_depth = min(depth_by_id.get(reply_target_id, 0) + 1, 4)
                timeline.append(
                    AgentAction(
                        agent_id="op",
                        text=op_resp,
                        step=step,
                        role="op",
                        comment_id=op_comment_id,
                        parent_comment_id=reply_target_id,
                        provider=resolved_provider,
                        model_name=resolved_model_name,
                        simulated_minute=op_minute,
                        bucket_label=bucket_label,
                    )
                )
                comment_scores[op_comment_id] = 0
                comment_text_by_id[op_comment_id] = op_resp
                comment_role_by_id[op_comment_id] = "OP"
                comment_step_by_id[op_comment_id] = step
                depth_by_id[op_comment_id] = op_depth
                reply_counts[reply_target_id] = reply_counts.get(reply_target_id, 0) + 1
                latest_op_comment_id = op_comment_id

            metadata["latest_op_comment_id"] = latest_op_comment_id

        eligible_comment_ids = {
            action.comment_id
            for action in timeline
            if action.role == "commenter" and action.comment_id is not None
        }
        eligible_scores = {comment_id: comment_scores.get(comment_id, 0) for comment_id in eligible_comment_ids}
        if eligible_scores:
            verdict_comment_id, verdict_score = max(eligible_scores.items(), key=lambda item: item[1])
            metadata["verdict_comment_id"] = verdict_comment_id
            metadata["verdict_score"] = verdict_score
        else:
            metadata["verdict_comment_id"] = None
            metadata["verdict_score"] = None

        metadata["usage"] = _normalize_usage_summary(llm.end_usage_capture(usage_token))

        run = SimulationRun(
            run_id=run_id,
            post=post,
            config=resolved_config,
            timeline=timeline,
            created_at=created_at,
            metadata=metadata,
        )

        out = run.dict()
        if isinstance(out.get("created_at"), datetime):
            out["created_at"] = out["created_at"].isoformat()

        storage.save_run_db(run_id, post.post_id, resolved_config.dict(), out)
        storage.save_run_json(run_id, out)
        return out
    except Exception:
        llm.end_usage_capture(usage_token)
        raise


async def run_batch_from_scrape(
    source_file: str,
    model_name: Optional[str] = None,
    max_steps: int = 6,
    commenter_cap: int = 50,
    op_enabled: bool = True,
    limit: Optional[int] = None,
    concurrency: int = 1,
    provider_strategy: str = "balanced",
    provider: Optional[str] = None,
    timeline_mode: str = "basic",
) -> Dict[str, Any]:
    batch_run_id = str(uuid.uuid4())
    created_at = datetime.utcnow()

    with open(source_file, "r", encoding="utf-8") as f:
        raw_posts = json.load(f)

    if limit is not None:
        raw_posts = raw_posts[:limit]

    concurrency = max(1, concurrency)
    total_posts = len(raw_posts)
    batch_posts: List[Optional[BatchPostResult]] = [None] * len(raw_posts)
    provider_plan = _build_provider_plan(
        total_posts=total_posts,
        provider_strategy=provider_strategy,
        provider=provider,
        model_name=model_name,
    )
    progress_state = {
        "completed": 0,
        "active": 0,
        "failed": 0,
    }
    progress_lock = asyncio.Lock()

    async def _print_progress() -> None:
        async with progress_lock:
            print(
                f"Completed {progress_state['completed']}/{total_posts} posts | "
                f"active: {progress_state['active']} | failed: {progress_state['failed']}"
            )

    async def _run_one(index: int, raw_post: Dict[str, Any]) -> None:
        async with progress_lock:
            progress_state["active"] += 1

        try:
            plan = provider_plan[index]
            post = Post(
                post_id=raw_post["post_id"],
                title=raw_post["title"],
                body=raw_post["body"],
                true_verdict=raw_post.get("verdict"),
                topic=raw_post.get("topic_category"),
                author=raw_post.get("author"),
            )
            simulated_config = SimulationConfig(
                model_name=plan["model_name"],
                provider=plan["provider"],
                num_commenters=_scaled_num_commenters(raw_post.get("num_comments", 0), commenter_cap),
                max_steps=max_steps,
                op_enabled=op_enabled,
                timeline_mode=timeline_mode,
            )
            simulated = await run_single_post(post, simulated_config)
            batch_posts[index] = BatchPostResult(
                post=post,
                source_num_comments=raw_post.get("num_comments", 0),
                source_score=raw_post.get("score"),
                source_verdict=raw_post.get("verdict"),
                source_top_comment=raw_post.get("top_comment"),
                source_top_comment_score=raw_post.get("top_comment_score"),
                source_url=raw_post.get("url"),
                simulation_provider=plan["provider"],
                simulation_model=plan["model_name"],
                simulated_config=simulated.get("config", simulated_config.dict()),
                timeline=[AgentAction(**action) for action in simulated["timeline"]],
                metadata=simulated.get("metadata"),
            )
        except Exception:
            async with progress_lock:
                progress_state["failed"] += 1
                progress_state["active"] -= 1
                progress_state["completed"] += 1
            await _print_progress()
            raise
        else:
            async with progress_lock:
                progress_state["active"] -= 1
                progress_state["completed"] += 1
            await _print_progress()

    if concurrency == 1:
        for index, raw_post in enumerate(raw_posts):
            await _run_one(index, raw_post)
    else:
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded_run(index: int, raw_post: Dict[str, Any]) -> None:
            async with semaphore:
                await _run_one(index, raw_post)

        await asyncio.gather(
            *[
                _guarded_run(index, raw_post)
                for index, raw_post in enumerate(raw_posts)
            ]
        )

    finalized_posts = [post for post in batch_posts if post is not None]
    batch_usage = _merge_usage_summaries(
        [post.metadata.get("usage") if post.metadata else None for post in finalized_posts]
    )
    provider_counts: Dict[str, int] = {}
    for post in finalized_posts:
        provider_counts[post.simulation_provider or "unknown"] = provider_counts.get(post.simulation_provider or "unknown", 0) + 1

    batch_run = BatchRun(
        batch_run_id=batch_run_id,
        source_file=str(Path(source_file)),
        created_at=created_at,
        config={
            "model_name": model_name,
            "provider": provider,
            "provider_strategy": provider_strategy,
            "timeline_mode": timeline_mode,
            "max_steps": max_steps,
            "commenter_cap": commenter_cap,
            "op_enabled": op_enabled,
            "concurrency": concurrency,
            "scaling_rule": "sqrt_cap_min10",
            "source_count": len(finalized_posts),
            "provider_distribution": provider_counts,
            "usage": batch_usage,
        },
        posts=finalized_posts,
    )

    out = batch_run.dict()
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()

    storage.save_batch_run_json(batch_run_id, out)
    return out
