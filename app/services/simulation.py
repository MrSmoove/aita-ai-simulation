"""
Multi-agent AITA simulation using direct LLM providers.
"""
import asyncio
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm import adapter as llm
from app.schemas import AgentAction, BatchPostResult, BatchRun, Post, SimulationConfig, SimulationRun
from app.services import storage

ACTIVITY_STYLES = [
    {"label": "drive-by commenter", "return_probability": 0.08, "max_comments": 1, "reply_likelihood": 0.15, "vote_likelihood": 0.55},
    {"label": "casual regular", "return_probability": 0.28, "max_comments": 2, "reply_likelihood": 0.4, "vote_likelihood": 0.72},
    {"label": "thread camper", "return_probability": 0.5, "max_comments": 3, "reply_likelihood": 0.68, "vote_likelihood": 0.82},
]
ACTION_TYPES = ["no_engage", "vote_only", "top_level", "reply", "comment_vote"]
VERDICTS = ("NTA", "YTA", "ESH", "NAH")
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


def _scaled_num_commenters(
    real_num_comments: int,
    commenter_cap: int,
    min_commenters: int = 10,
    scale_power: float = 0.5,
) -> int:
    if real_num_comments <= 0:
        return min(min_commenters, commenter_cap)
    return max(min_commenters, min(round(real_num_comments ** scale_power), commenter_cap))


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


def _build_commenter_profiles(
    num_commenters: int,
    available_providers: Optional[List[str]] = None,
    mobility: float = 1.0,
) -> List[Dict[str, Any]]:
    # Distribute activity styles: ~50% drive-by, ~30% casual regular, ~20% thread camper
    activity_counts = _allocate_counts(num_commenters, [0.5, 0.3, 0.2])
    activity_assignments: List[int] = []
    for style_idx, count in enumerate(activity_counts):
        activity_assignments.extend([style_idx] * count)
    random.shuffle(activity_assignments)

    profiles: List[Dict[str, Any]] = []
    for index in range(num_commenters):
        activity_index = activity_assignments[index]
        activity = ACTIVITY_STYLES[activity_index]
        if activity["label"] == "drive-by commenter":
            max_top_level_comments = 1
            max_reply_comments = 0
            max_votes = 2
        elif activity["label"] == "casual regular":
            max_top_level_comments = 1
            max_reply_comments = 1
            max_votes = 4
        else:  # thread camper
            max_top_level_comments = 2
            max_reply_comments = 2
            max_votes = 6
        # Assign provider round-robin so agents come from different models.
        providers = available_providers or ["openai"]
        agent_provider = providers[index % len(providers)]
        agent_model = llm.resolve_model_name(agent_provider, None)
        return_probability = min(0.95, max(0.02, activity["return_probability"] * mobility))
        vote_likelihood = min(0.95, max(0.05, activity["vote_likelihood"] * (0.8 + (0.2 * mobility))))
        profiles.append(
            {
                "agent_id": f"c{index + 1}",
                "activity_style": activity["label"],
                "return_probability": return_probability,
                "max_comments": activity["max_comments"],
                "max_top_level_comments": max_top_level_comments,
                "max_reply_comments": max_reply_comments,
                "max_votes": max_votes,
                "reply_likelihood": activity["reply_likelihood"],
                "vote_likelihood": vote_likelihood,
                "downvote_likelihood": 0.18,
                "arrival_wave": 1,
                "provider": agent_provider,
                "model_name": agent_model,
            }
        )
    return profiles


def _build_voter_profiles(
    num_voters: int,
    mobility: float = 1.0,
    available_providers: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    providers = available_providers or ["openai"]
    for index in range(max(0, num_voters)):
        agent_provider = providers[index % len(providers)]
        agent_model = llm.resolve_model_name(agent_provider, None)
        profiles.append(
            {
                "agent_id": f"v{index + 1}",
                "activity_style": "vote-only",
                "return_probability": min(0.95, max(0.05, 0.22 * mobility)),
                "max_comments": 0,
                "max_top_level_comments": 0,
                "max_reply_comments": 0,
                "max_votes": max(1, round(3 * mobility)),
                "reply_likelihood": 0.0,
                "vote_likelihood": min(0.98, max(0.2, 0.75 * mobility)),
                "downvote_likelihood": 0.18,
                "arrival_wave": 1,
                "provider": agent_provider,
                "model_name": agent_model,
            }
        )
    return profiles


def _build_agent_visible_comment_ids(
    profile: Dict[str, Any],
    available_comment_ids: List[str],
    seen_comment_ids: set[str],
    comment_scores: Dict[str, int],
    comment_step_by_id: Dict[str, int],
    current_step: int,
) -> List[str]:
    if not available_comment_ids:
        return []

    # Blend high-score comments with a few recent unseen comments.
    sorted_by_score = sorted(
        available_comment_ids,
        key=lambda cid: (comment_scores.get(cid, 0), comment_step_by_id.get(cid, 0)),
        reverse=True,
    )
    top_visible = sorted_by_score[:25]
    recent_unseen = [
        cid for cid in reversed(available_comment_ids)
        if cid not in seen_comment_ids
    ][:10]

    merged: List[str] = []
    for comment_id in top_visible + recent_unseen:
        if comment_id not in merged:
            merged.append(comment_id)
    return merged


def _build_weighted_verdict_tally(
    eligible_comment_ids: List[str],
    comment_scores: Dict[str, int],
    comment_vote_totals: Dict[str, Dict[str, int]],
    verdict_label_by_comment_id: Dict[str, Optional[str]],
) -> Dict[str, float]:
    tally: Dict[str, float] = {label: 0.0 for label in VERDICTS}
    for comment_id in eligible_comment_ids:
        label = verdict_label_by_comment_id.get(comment_id)
        if not label:
            continue
        totals = comment_vote_totals.get(comment_id, {})
        upvotes = totals.get("upvotes", 0)
        score = comment_scores.get(comment_id, 0)
        weight = max(1.0, 1.0 + (0.5 * upvotes) + score)
        tally[label] = tally.get(label, 0.0) + weight
    return {label: round(value, 3) for label, value in tally.items() if value > 0}


def _resolve_final_verdict(weighted_tally: Dict[str, float], top_comment_label: Optional[str]) -> Optional[str]:
    if weighted_tally:
        best_weight = max(weighted_tally.values())
        winners = [label for label, weight in weighted_tally.items() if weight == best_weight]
        if top_comment_label and top_comment_label in winners:
            return top_comment_label
        for label in VERDICTS:
            if label in winners:
                return label
    return top_comment_label


def _choose_agent_action(
    profile: Dict[str, Any],
    wave: Dict[str, Any],
    is_new_arrival: bool,
    has_visible_comments: bool,
    comment_count: int,
    top_level_count: int,
    reply_count: int,
    vote_count: int,
    total_action_count: int,
    step: int,
    total_steps: int,
) -> str:
    can_comment = comment_count < profile["max_comments"]
    can_top_level = can_comment and top_level_count < profile["max_top_level_comments"]
    can_reply = can_comment and has_visible_comments and reply_count < profile["max_reply_comments"]
    can_vote = has_visible_comments and vote_count < profile["max_votes"]

    # Ensure each arrived agent takes at least one action by the final wave when possible.
    if step == total_steps and total_action_count == 0:
        if can_vote:
            return "vote_only"
        if can_top_level:
            return "top_level"
        if can_reply:
            return "reply"
        return "no_engage"

    weights: Dict[str, float] = {
        "no_engage": 0.18 if is_new_arrival else 0.26,
        "vote_only": 0.18,
        "top_level": max(0.05, wave["top_level_bias"] * (0.62 if is_new_arrival else 0.42)),
        "reply": max(0.05, (1 - wave["top_level_bias"]) * (0.48 if not is_new_arrival else 0.3)),
        "comment_vote": 0.14,
    }

    allowed: List[str] = ["no_engage"]
    if can_vote:
        allowed.append("vote_only")
    if can_top_level:
        allowed.append("top_level")
    if can_reply:
        allowed.append("reply")
    if can_vote and (can_top_level or can_reply):
        allowed.append("comment_vote")

    probabilities = [weights[action] for action in allowed]
    return random.choices(allowed, weights=probabilities, k=1)[0]


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


def _extract_verdict_label(text: str) -> Optional[str]:
    """Return the first YTA/NTA/ESH/NAH tag found in the first 60 characters."""
    match = re.search(r"\b(YTA|NTA|ESH|NAH)\b", text[:60], re.IGNORECASE)
    return match.group(1).upper() if match else None


_ERROR_STUB_RE = re.compile(r"^\[.+?\] \((error|stub|no response)", re.IGNORECASE)


def _is_error_stub(text: str) -> bool:
    return bool(_ERROR_STUB_RE.match(text))


def _build_thread_digest(
    visible_comment_ids: List[str],
    comment_text_by_id: Dict[str, str],
    comment_scores: Dict[str, int],
    comment_role_by_id: Dict[str, str],
    top_k: int = 5,
) -> str:
    """Return a short digest of the most visible comments for agent context."""
    if not visible_comment_ids:
        return ""

    valid_ids = [
        cid for cid in visible_comment_ids
        if cid in comment_text_by_id and not _is_error_stub(comment_text_by_id[cid])
    ]
    if not valid_ids:
        return ""

    # Top-k by score
    sorted_by_score = sorted(valid_ids, key=lambda cid: comment_scores.get(cid, 0), reverse=True)
    top_ids = sorted_by_score[:top_k]

    # Append up to 2 most recent comments not already in the top set
    top_set = set(top_ids)
    recent_extra = [cid for cid in reversed(valid_ids) if cid not in top_set][:2]
    digest_ids = top_ids + recent_extra

    lines = []
    for cid in digest_ids:
        role = comment_role_by_id.get(cid, "?")
        score = comment_scores.get(cid, 0)
        snippet = comment_text_by_id[cid][:120].replace("\n", " ")
        score_str = f"+{score}" if score >= 0 else str(score)
        lines.append(f"[{role}, {score_str}]: {snippet}")

    return "\n".join(lines)


AITA_RULES = (
    "r/AmItheAsshole rules:\n"
    "- Commenters must vote using one of: YTA (you're the asshole), NTA (not the asshole), "
    "ESH (everyone sucks here), NAH (no assholes here), or INFO (need more information).\n"
    "- Top-level comments must start with a verdict.\n"
    "- Judge only the situation described — do not moralize beyond it.\n"
    "- Do not ask for more information if you can make a reasonable judgment.\n"
    "- Replies do not need a verdict tag."
)


def _build_commenter_prompt(
    post: Post,
    bucket_label: str,
    profile: Dict[str, Any],
    is_top_level: bool,
    parent_text: Optional[str] = None,
    parent_role: Optional[str] = None,
    thread_digest: str = "",
) -> str:
    base = (
        "You are a Reddit user browsing r/AmItheAsshole.\n"
        f"{AITA_RULES}\n\n"
        f"This post was made {bucket_label} ago.\n"
        f"Post title: {post.title}\n\n"
        f"Post body:\n{post.body}\n"
    )
    digest_block = (
        f"\nTop comments so far:\n{thread_digest}\n"
        if thread_digest else ""
    )
    if is_top_level or not parent_text:
        return (
            f"{base}"
            f"{digest_block}\n"
            "Write your comment. Start with your verdict (YTA, NTA, ESH, or NAH) on the very first line, then explain your reasoning."
        )
    return (
        f"{base}"
        f"{digest_block}\n"
        f"You are replying to this comment by {parent_role or 'another user'}:\n"
        f"{parent_text}\n\n"
        "Write your reply."
    )


def _build_op_prompt(post: Post, bucket_label: str, target_comment_text: str, thread_digest: str = "") -> str:
    digest_block = (
        f"What people are saying so far:\n{thread_digest}\n\n"
        if thread_digest else ""
    )
    return (
        "You are the original poster (OP) on r/AmItheAsshole.\n"
        "You posted this thread and are now responding to comments.\n"
        "Reply in 1-2 sentences — you can clarify facts, defend yourself, or acknowledge a fair point. Do not give yourself a verdict.\n\n"
        f"Your post title: {post.title}\n\n"
        f"Your post:\n{post.body}\n\n"
        f"{digest_block}"
        f"Reply to this comment:\n{target_comment_text}\n"
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
    vote_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    eligible = [
        profile
        for profile in arrived_profiles
        if profile["arrival_wave"] < step
        and (
            action_counts.get(profile["agent_id"], 0) < profile["max_comments"]
            or vote_counts.get(profile["agent_id"], 0) < profile.get("max_votes", 4)
        )
        and random.random() < profile["return_probability"]
    ]
    random.shuffle(eligible)
    target = round(len(arrived_profiles) * wave["return_share"])
    return eligible[:target]


def _vote_on_comments(
    voter_profiles: List[Dict[str, Any]],
    candidate_comment_ids: List[str],
    comment_scores: Dict[str, int],
    comment_vote_totals: Dict[str, Dict[str, int]],
    depth_by_id: Dict[str, int],
    comment_role_by_id: Dict[str, str],
    comment_step_by_id: Dict[str, int],
    current_step: int,
    vote_counts: Dict[str, int],
    visible_comment_ids_by_agent: Optional[Dict[str, List[str]]] = None,
    agent_verdict_by_id: Optional[Dict[str, Optional[str]]] = None,
    verdict_label_by_comment_id: Optional[Dict[str, Optional[str]]] = None,
) -> None:
    """Vote on comments, biased toward comments whose verdict matches the voter's own verdict.

    This replicates real Reddit AITA behavior: users upvote comments they agree with
    and downvote comments whose judgment they oppose, so the top-scored comment
    reflects the community consensus verdict.
    """
    if not candidate_comment_ids:
        return

    for voter in voter_profiles:
        voter_id = voter["agent_id"]
        if vote_counts.get(voter_id, 0) >= voter.get("max_votes", 4):
            continue
        if random.random() > voter.get("vote_likelihood", 0.65):
            continue

        visible_for_voter = None
        if visible_comment_ids_by_agent:
            visible_for_voter = set(visible_comment_ids_by_agent.get(voter_id, []))

        voteable_ids = [
            comment_id
            for comment_id in candidate_comment_ids
            if comment_role_by_id.get(comment_id) != voter_id
            and (visible_for_voter is None or comment_id in visible_for_voter)
        ]
        if not voteable_ids:
            continue

        voter_verdict = (agent_verdict_by_id or {}).get(voter_id)

        weights = []
        for comment_id in voteable_ids:
            depth = depth_by_id.get(comment_id, 0)
            score = comment_scores.get(comment_id, 0)
            age = max(0, current_step - comment_step_by_id.get(comment_id, current_step))
            depth_multiplier = {0: 1.65, 1: 1.18, 2: 0.82, 3: 0.5}.get(min(depth, 3), 0.35)
            visibility = 1 + min(score, 24) * 0.1 + min(age, 6) * 0.08
            # Boost visibility of comments whose verdict matches the voter's own
            comment_verdict = (verdict_label_by_comment_id or {}).get(comment_id)
            if voter_verdict and comment_verdict:
                if voter_verdict == comment_verdict:
                    visibility *= 2.2  # strongly prefer same-verdict comments
                else:
                    visibility *= 0.4  # suppress opposing-verdict comments
            weights.append(max(0.05, depth_multiplier * visibility))

        target_id = random.choices(voteable_ids, weights=weights, k=1)[0]
        current_score = comment_scores.get(target_id, 0)

        # Determine upvote vs downvote using verdict alignment
        comment_verdict = (verdict_label_by_comment_id or {}).get(target_id)
        if voter_verdict and comment_verdict:
            if voter_verdict == comment_verdict:
                # Agree — almost always upvote
                downvote_bias = 0.04
            else:
                # Disagree — strongly downvote
                downvote_bias = 0.78
        else:
            # No verdict info — use score-based neutral bias
            downvote_bias = 0.08 if current_score >= 0 else 0.28
            downvote_bias += min(depth_by_id.get(target_id, 0), 3) * 0.04

        is_downvote = random.random() < min(0.85, downvote_bias)
        vote_totals = comment_vote_totals.setdefault(target_id, {"upvotes": 0, "downvotes": 0})
        if is_downvote:
            vote_totals["downvotes"] += 1
            comment_scores[target_id] = current_score - 1
        else:
            vote_totals["upvotes"] += 1
            comment_scores[target_id] = current_score + 1
        vote_counts[voter_id] = vote_counts.get(voter_id, 0) + 1


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
    ordered = [name for name in ["openai", "deepseek", "mistral", "groq", "gemini"] if name in available]
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
        # Keep provider assignment per post consistent when a provider is resolved.
        sim_providers = [resolved_provider]
        commenter_profiles = _build_commenter_profiles(resolved_config.num_commenters, sim_providers)
        _assign_arrival_waves(commenter_profiles, schedule)
        profile_by_agent_id = {profile["agent_id"]: profile for profile in commenter_profiles}

        timeline: List[AgentAction] = []
        metadata: Dict[str, Any] = {
            "comment_scores": {},
            "comment_votes": {},
            "commenter_profiles": commenter_profiles,
            "timeline_mode": resolved_config.timeline_mode,
            "wave_schedule": schedule,
            "provider": resolved_provider,
            "model_name": resolved_model_name,
        }
        comment_scores: Dict[str, int] = metadata["comment_scores"]
        comment_vote_totals: Dict[str, Dict[str, int]] = metadata["comment_votes"]
        action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        top_level_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        reply_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        vote_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        total_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        comment_text_by_id: Dict[str, str] = {}
        comment_role_by_id: Dict[str, str] = {}
        comment_step_by_id: Dict[str, int] = {}
        depth_by_id: Dict[str, int] = {}
        reply_counts: Dict[str, int] = {}
        latest_op_comment_id: Optional[str] = None
        # Tracks each agent's own verdict so votes are cast in alignment with it
        agent_verdict_by_id: Dict[str, Optional[str]] = {}
        verdict_label_by_comment_id: Dict[str, Optional[str]] = {}

        for wave in schedule:
            step = wave["step"]
            bucket_label = wave["label"]
            new_arrivals = [profile for profile in commenter_profiles if profile["arrival_wave"] == step]
            arrived_profiles = [profile for profile in commenter_profiles if profile["arrival_wave"] <= step]
            returning_profiles = _select_returning_profiles(arrived_profiles, step, wave, action_counts, vote_counts)

            participant_meta = [{"profile": profile, "is_new_arrival": True} for profile in new_arrivals]
            participant_meta.extend({"profile": profile, "is_new_arrival": False} for profile in returning_profiles)
            random.shuffle(participant_meta)

            visible_comment_ids = [
                action.comment_id
                for action in timeline
                if action.comment_id is not None
            ]
            thread_digest = _build_thread_digest(
                visible_comment_ids=visible_comment_ids,
                comment_text_by_id=comment_text_by_id,
                comment_scores=comment_scores,
                comment_role_by_id=comment_role_by_id,
            )
            sampled_minutes = _sample_wave_minutes(wave["start_min"], wave["end_min"], len(participant_meta))
            tasks = []
            pending_comment_meta: List[Dict[str, Any]] = []
            vote_only_profiles: List[Dict[str, Any]] = []
            comment_vote_profiles: List[Dict[str, Any]] = []

            for meta, simulated_minute in zip(participant_meta, sampled_minutes):
                profile = meta["profile"]
                agent_id = profile["agent_id"]
                agent_name = f"commenter_{agent_id[1:]}"
                chosen_action = _choose_agent_action(
                    profile=profile,
                    wave=wave,
                    is_new_arrival=meta["is_new_arrival"],
                    has_visible_comments=bool(visible_comment_ids),
                    comment_count=action_counts[agent_id],
                    top_level_count=top_level_action_counts[agent_id],
                    reply_count=reply_action_counts[agent_id],
                    vote_count=vote_counts[agent_id],
                    total_action_count=total_action_counts[agent_id],
                    step=step,
                    total_steps=len(schedule),
                )

                if chosen_action == "no_engage":
                    continue

                if chosen_action == "vote_only":
                    vote_only_profiles.append(profile)
                    total_action_counts[agent_id] += 1
                    continue

                wants_reply = chosen_action == "reply"
                if chosen_action == "comment_vote":
                    can_reply = bool(visible_comment_ids) and reply_action_counts[agent_id] < profile["max_reply_comments"]
                    can_top_level = top_level_action_counts[agent_id] < profile["max_top_level_comments"]
                    if can_reply and can_top_level:
                        wants_reply = random.random() > wave["top_level_bias"]
                    elif can_reply:
                        wants_reply = True
                    else:
                        wants_reply = False

                parent_comment_id = None
                if wants_reply and visible_comment_ids:
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
                    thread_digest=thread_digest,
                )
                agent_provider = profile.get("provider", resolved_provider)
                agent_model = profile.get("model_name", resolved_model_name)
                tasks.append(
                    llm.generate_comment(
                        session,
                        prompt,
                        agent_name,
                        model_name=agent_model,
                        provider=agent_provider,
                    )
                )
                pending_comment_meta.append(
                    {
                        "agent_id": agent_id,
                        "action_type": chosen_action,
                        "parent_comment_id": parent_comment_id,
                        "simulated_minute": simulated_minute,
                        "bucket_label": bucket_label,
                        "provider": agent_provider,
                        "model_name": agent_model,
                    }
                )
                if chosen_action == "comment_vote":
                    comment_vote_profiles.append(profile)

            results = await asyncio.gather(*tasks)
            current_wave_comment_ids: List[str] = []
            for index, text in enumerate(results):
                pending = pending_comment_meta[index]
                comment_id = f"{run_id}:{step}:{pending['agent_id']}:{action_counts[pending['agent_id']] + 1}"
                parent_comment_id = pending["parent_comment_id"]
                depth = 0 if not parent_comment_id else min(depth_by_id.get(parent_comment_id, 0) + 1, 4)
                verdict_label = _extract_verdict_label(text) if parent_comment_id is None else None
                timeline.append(
                    AgentAction(
                        agent_id=pending["agent_id"],
                        text=text,
                        step=step,
                        role="commenter",
                        comment_id=comment_id,
                        parent_comment_id=parent_comment_id,
                        provider=pending.get("provider", resolved_provider),
                        model_name=pending.get("model_name", resolved_model_name),
                        simulated_minute=pending["simulated_minute"],
                        bucket_label=pending["bucket_label"],
                        verdict_label=verdict_label,
                    )
                )
                action_counts[pending["agent_id"]] += 1
                total_action_counts[pending["agent_id"]] += 1
                if parent_comment_id is None:
                    top_level_action_counts[pending["agent_id"]] += 1
                else:
                    reply_action_counts[pending["agent_id"]] += 1
                comment_scores[comment_id] = comment_scores.get(comment_id, 0)
                comment_vote_totals[comment_id] = comment_vote_totals.get(comment_id, {"upvotes": 0, "downvotes": 0})
                comment_text_by_id[comment_id] = text
                comment_role_by_id[comment_id] = pending["agent_id"]
                comment_step_by_id[comment_id] = step
                depth_by_id[comment_id] = depth
                verdict_label_by_comment_id[comment_id] = verdict_label
                if verdict_label and parent_comment_id is None:
                    agent_verdict_by_id[pending["agent_id"]] = verdict_label
                if parent_comment_id:
                    reply_counts[parent_comment_id] = reply_counts.get(parent_comment_id, 0) + 1
                current_wave_comment_ids.append(comment_id)

            candidate_comment_ids = [
                action.comment_id
                for action in timeline
                if action.role == "commenter" and action.comment_id is not None
            ]
            _vote_on_comments(
                voter_profiles=vote_only_profiles + comment_vote_profiles,
                candidate_comment_ids=candidate_comment_ids,
                comment_scores=comment_scores,
                comment_vote_totals=comment_vote_totals,
                depth_by_id=depth_by_id,
                comment_role_by_id=comment_role_by_id,
                comment_step_by_id=comment_step_by_id,
                current_step=step,
                vote_counts=vote_counts,
                agent_verdict_by_id=agent_verdict_by_id,
                verdict_label_by_comment_id=verdict_label_by_comment_id,
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
                op_target_text = comment_text_by_id.get(reply_target_id, "")
                # Skip OP reply if the best comment is an error stub
                if not _is_error_stub(op_target_text):
                    op_prompt = _build_op_prompt(
                        post=post,
                        bucket_label=bucket_label,
                        target_comment_text=op_target_text,
                        thread_digest=thread_digest,
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
                    comment_vote_totals[op_comment_id] = {"upvotes": 0, "downvotes": 0}
                    comment_text_by_id[op_comment_id] = op_resp
                    comment_role_by_id[op_comment_id] = "OP"
                    comment_step_by_id[op_comment_id] = step
                    depth_by_id[op_comment_id] = op_depth
                    reply_counts[reply_target_id] = reply_counts.get(reply_target_id, 0) + 1
                    latest_op_comment_id = op_comment_id

            metadata["latest_op_comment_id"] = latest_op_comment_id

        # Verdict = highest-voted top-level commenter comment at the 18h mark.
        # In 24h mode the 18-24h wave (step 6) posts after the verdict snapshot, so exclude it.
        verdict_cutoff_step = 5 if config.timeline_mode == "24h" else None
        eligible_comment_ids = {
            action.comment_id
            for action in timeline
            if (
                action.role == "commenter"
                and action.comment_id is not None
                and action.parent_comment_id is None  # top-level only
                and (verdict_cutoff_step is None or action.step <= verdict_cutoff_step)
            )
        }
        eligible_scores = {comment_id: comment_scores.get(comment_id, 0) for comment_id in eligible_comment_ids}
        # Tally all verdict labels from top-level commenter comments.
        verdict_label_by_comment_id = {
            action.comment_id: action.verdict_label
            for action in timeline
            if action.role == "commenter" and action.parent_comment_id is None and action.verdict_label
        }
        verdict_tally: Dict[str, int] = {}
        for label in verdict_label_by_comment_id.values():
            verdict_tally[label] = verdict_tally.get(label, 0) + 1
        metadata["verdict_tally"] = verdict_tally

        if eligible_scores:
            verdict_comment_id, verdict_score = max(eligible_scores.items(), key=lambda item: item[1])
            metadata["verdict_comment_id"] = verdict_comment_id
            metadata["verdict_score"] = verdict_score
            # Fall back to tally majority if the top comment has no label (e.g. error stub)
            label = verdict_label_by_comment_id.get(verdict_comment_id)
            if label is None and verdict_tally:
                label = max(verdict_tally, key=lambda k: verdict_tally[k])
            metadata["verdict_label"] = label
        else:
            metadata["verdict_comment_id"] = None
            metadata["verdict_score"] = None
            metadata["verdict_label"] = None

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
    voter_ratio: float = 1.0,
    commenter_min: int = 1,
    commenter_scale_power: float = 0.5,
    mobility: float = 1.0,
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
            scaled_commenters = _scaled_num_commenters(
                raw_post.get("num_comments", 0),
                commenter_cap,
                min_commenters=commenter_min,
                scale_power=commenter_scale_power,
            )
            simulated_config = SimulationConfig(
                model_name=plan["model_name"],
                provider=plan["provider"],
                num_commenters=scaled_commenters,
                num_voters=max(0, round(scaled_commenters * max(0.0, voter_ratio))),
                mobility=mobility,
                max_steps=max_steps,
                op_enabled=op_enabled,
                timeline_mode=timeline_mode,
            )
            simulated = await run_single_post(post, simulated_config)
            ai_verdict = (simulated.get("metadata") or {}).get("verdict_label")
            real_verdict = raw_post.get("verdict")
            verdict_match = (ai_verdict == real_verdict) if (ai_verdict and real_verdict) else None
            batch_posts[index] = BatchPostResult(
                post=post,
                source_num_comments=raw_post.get("num_comments", 0),
                source_score=raw_post.get("score"),
                source_verdict=real_verdict,
                source_top_comment=raw_post.get("top_comment"),
                source_top_comment_score=raw_post.get("top_comment_score"),
                source_url=raw_post.get("url"),
                simulation_provider=plan["provider"],
                simulation_model=plan["model_name"],
                simulated_config=simulated.get("config", simulated_config.dict()),
                timeline=[AgentAction(**action) for action in simulated["timeline"]],
                metadata=simulated.get("metadata"),
                verdict_match=verdict_match,
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

    correct = sum(1 for p in finalized_posts if p.verdict_match is True)
    total_with_verdict = sum(1 for p in finalized_posts if p.verdict_match is not None)
    accuracy = round(correct / total_with_verdict, 3) if total_with_verdict > 0 else None

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
            "voter_ratio": voter_ratio,
            "commenter_min": commenter_min,
            "commenter_scale_power": commenter_scale_power,
            "mobility": mobility,
            "op_enabled": op_enabled,
            "concurrency": concurrency,
            "scaling_rule": f"real_comments^{commenter_scale_power}_cap_{commenter_cap}_min_{commenter_min}",
            "source_count": len(finalized_posts),
            "provider_distribution": provider_counts,
            "accuracy": {
                "correct": correct,
                "total": total_with_verdict,
                "rate": accuracy,
            },
            "usage": batch_usage,
        },
        posts=finalized_posts,
    )

    out = batch_run.dict()
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()

    storage.save_batch_run_json(batch_run_id, out)
    return out
