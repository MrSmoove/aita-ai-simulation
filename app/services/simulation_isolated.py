"""
Experimental simulation path with per-agent seeded sessions.

This module is intentionally separate from the main simulation pipeline so
current production behavior remains unchanged.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.llm import adapter as llm
from app.schemas import AgentAction, BatchPostResult, BatchRun, Post, SimulationConfig, SimulationRun
from app.services import simulation as base_sim
from app.services import storage


async def run_single_post(
    post: Post,
    config: SimulationConfig,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrate a multi-agent simulation using isolated commenter sessions.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())

    created_at = datetime.utcnow()
    usage_token, _ = llm.begin_usage_capture()
    try:
        bootstrap_session = await llm.seed_session(
            post.dict(),
            model_name=config.model_name,
            provider=config.provider,
        )
        resolved_provider = bootstrap_session["provider"]
        resolved_model_name = bootstrap_session["model_name"]
        resolved_config = SimulationConfig(
            model_name=resolved_model_name,
            provider=resolved_provider,
            num_commenters=config.num_commenters,
            num_voters=config.num_voters,
            mobility=config.mobility,
            max_steps=len(base_sim._build_wave_schedule(config.timeline_mode, config.max_steps)),
            op_enabled=config.op_enabled,
            timeline_mode=config.timeline_mode,
        )

        schedule = base_sim._build_wave_schedule(resolved_config.timeline_mode, resolved_config.max_steps)
        # Keep provider assignment per post consistent in the isolated path.
        sim_providers = [resolved_provider]
        commenter_profiles = base_sim._build_commenter_profiles(
            resolved_config.num_commenters,
            mobility=resolved_config.mobility,
            available_providers=sim_providers,
        )
        voter_profiles = base_sim._build_voter_profiles(
            resolved_config.num_voters,
            mobility=resolved_config.mobility,
            available_providers=sim_providers,
        )
        base_sim._assign_arrival_waves(commenter_profiles, schedule)
        base_sim._assign_arrival_waves(voter_profiles, schedule)

        # Key experiment: each commenter receives their own seeded session object.
        commenter_sessions: Dict[str, Dict[str, str]] = {}
        for profile in commenter_profiles:
            agent_id = profile["agent_id"]
            agent_provider = profile.get("provider", resolved_provider)
            agent_model = profile.get("model_name", resolved_model_name)
            commenter_sessions[agent_id] = await llm.seed_session(
                post.dict(),
                model_name=agent_model,
                provider=agent_provider,
            )

        op_session = await llm.seed_session(
            post.dict(),
            model_name=resolved_model_name,
            provider=resolved_provider,
        )

        timeline: List[AgentAction] = []
        metadata: Dict[str, Any] = {
            "comment_scores": {},
            "comment_votes": {},
            "commenter_profiles": commenter_profiles,
            "voter_profiles": voter_profiles,
            "timeline_mode": resolved_config.timeline_mode,
            "wave_schedule": schedule,
            "provider": resolved_provider,
            "model_name": resolved_model_name,
            "mobility": resolved_config.mobility,
            "session_mode": "per_commenter_isolated",
        }
        comment_scores: Dict[str, int] = metadata["comment_scores"]
        comment_vote_totals: Dict[str, Dict[str, int]] = metadata["comment_votes"]
        action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        top_level_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        reply_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        vote_counts: Dict[str, int] = {
            profile["agent_id"]: 0
            for profile in (commenter_profiles + voter_profiles)
        }
        total_action_counts: Dict[str, int] = {profile["agent_id"]: 0 for profile in commenter_profiles}
        comment_text_by_id: Dict[str, str] = {}
        comment_role_by_id: Dict[str, str] = {}
        comment_step_by_id: Dict[str, int] = {}
        depth_by_id: Dict[str, int] = {}
        reply_counts: Dict[str, int] = {}
        latest_op_comment_id: Optional[str] = None
        agent_verdict_by_id: Dict[str, Optional[str]] = {}
        verdict_label_by_comment_id: Dict[str, Optional[str]] = {}
        seen_comment_ids_by_agent: Dict[str, set[str]] = {
            profile["agent_id"]: set()
            for profile in (commenter_profiles + voter_profiles)
        }

        for wave in schedule:
            step = wave["step"]
            bucket_label = wave["label"]
            new_arrivals = [profile for profile in commenter_profiles if profile["arrival_wave"] == step]
            arrived_profiles = [profile for profile in commenter_profiles if profile["arrival_wave"] <= step]
            returning_profiles = base_sim._select_returning_profiles(arrived_profiles, step, wave, action_counts, vote_counts)
            voter_new_arrivals = [profile for profile in voter_profiles if profile["arrival_wave"] == step]
            voter_arrived_profiles = [profile for profile in voter_profiles if profile["arrival_wave"] <= step]
            returning_voters = base_sim._select_returning_profiles(
                voter_arrived_profiles,
                step,
                wave,
                action_counts,
                vote_counts,
            )
            active_wave_voters = voter_new_arrivals + returning_voters

            participant_meta = [{"profile": profile, "is_new_arrival": True} for profile in new_arrivals]
            participant_meta.extend({"profile": profile, "is_new_arrival": False} for profile in returning_profiles)
            random.shuffle(participant_meta)

            visible_comment_ids = [
                action.comment_id
                for action in timeline
                if action.comment_id is not None
            ]
            sampled_minutes = base_sim._sample_wave_minutes(wave["start_min"], wave["end_min"], len(participant_meta))
            tasks = []
            pending_comment_meta: List[Dict[str, Any]] = []
            vote_only_profiles: List[Dict[str, Any]] = []
            comment_vote_profiles: List[Dict[str, Any]] = []
            visible_comment_ids_by_agent: Dict[str, List[str]] = {}

            for meta, simulated_minute in zip(participant_meta, sampled_minutes):
                profile = meta["profile"]
                agent_id = profile["agent_id"]
                agent_name = f"commenter_{agent_id[1:]}"
                agent_visible_comment_ids = base_sim._build_agent_visible_comment_ids(
                    profile=profile,
                    available_comment_ids=visible_comment_ids,
                    seen_comment_ids=seen_comment_ids_by_agent[agent_id],
                    comment_scores=comment_scores,
                    comment_step_by_id=comment_step_by_id,
                    current_step=step,
                )
                seen_comment_ids_by_agent[agent_id].update(agent_visible_comment_ids)
                visible_comment_ids_by_agent[agent_id] = agent_visible_comment_ids
                chosen_action = base_sim._choose_agent_action(
                    profile=profile,
                    wave=wave,
                    is_new_arrival=meta["is_new_arrival"],
                    has_visible_comments=bool(agent_visible_comment_ids),
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
                    can_reply = bool(agent_visible_comment_ids) and reply_action_counts[agent_id] < profile["max_reply_comments"]
                    can_top_level = top_level_action_counts[agent_id] < profile["max_top_level_comments"]
                    if can_reply and can_top_level:
                        wants_reply = random.random() > wave["top_level_bias"]
                    elif can_reply:
                        wants_reply = True
                    else:
                        wants_reply = False

                parent_comment_id = None
                if wants_reply and agent_visible_comment_ids:
                    parent_comment_id = base_sim._choose_reply_target(
                        candidate_comment_ids=agent_visible_comment_ids,
                        comment_scores=comment_scores,
                        depth_by_id=depth_by_id,
                        comment_role_by_id=comment_role_by_id,
                        reply_counts=reply_counts,
                        comment_step_by_id=comment_step_by_id,
                        current_step=step,
                    )

                parent_text = comment_text_by_id.get(parent_comment_id) if parent_comment_id else None
                parent_role = comment_role_by_id.get(parent_comment_id) if parent_comment_id else None
                agent_thread_digest = base_sim._build_thread_digest(
                    visible_comment_ids=agent_visible_comment_ids,
                    comment_text_by_id=comment_text_by_id,
                    comment_scores=comment_scores,
                    comment_role_by_id=comment_role_by_id,
                )
                prompt_digest = "" if (parent_comment_id is None and step == 1) else agent_thread_digest
                prompt = base_sim._build_commenter_prompt(
                    post=post,
                    bucket_label=bucket_label,
                    profile=profile,
                    is_top_level=parent_comment_id is None,
                    parent_text=parent_text,
                    parent_role=parent_role,
                    thread_digest=prompt_digest,
                )
                agent_provider = profile.get("provider", resolved_provider)
                agent_model = profile.get("model_name", resolved_model_name)
                tasks.append(
                    llm.generate_comment(
                        commenter_sessions[agent_id],
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

            for voter_profile in vote_only_profiles + active_wave_voters:
                voter_id = voter_profile["agent_id"]
                voter_visible_comment_ids = base_sim._build_agent_visible_comment_ids(
                    profile=voter_profile,
                    available_comment_ids=visible_comment_ids,
                    seen_comment_ids=seen_comment_ids_by_agent[voter_id],
                    comment_scores=comment_scores,
                    comment_step_by_id=comment_step_by_id,
                    current_step=step,
                )
                seen_comment_ids_by_agent[voter_id].update(voter_visible_comment_ids)
                visible_comment_ids_by_agent[voter_id] = voter_visible_comment_ids

            results = await asyncio.gather(*tasks)
            current_wave_comment_ids: List[str] = []
            for index, text in enumerate(results):
                pending = pending_comment_meta[index]
                comment_id = f"{run_id}:{step}:{pending['agent_id']}:{action_counts[pending['agent_id']] + 1}"
                parent_comment_id = pending["parent_comment_id"]
                depth = 0 if not parent_comment_id else min(depth_by_id.get(parent_comment_id, 0) + 1, 4)
                verdict_label = base_sim._extract_verdict_label(text) if parent_comment_id is None else None
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
            base_sim._vote_on_comments(
                voter_profiles=vote_only_profiles + comment_vote_profiles + active_wave_voters,
                candidate_comment_ids=candidate_comment_ids,
                comment_scores=comment_scores,
                comment_vote_totals=comment_vote_totals,
                depth_by_id=depth_by_id,
                comment_role_by_id=comment_role_by_id,
                comment_step_by_id=comment_step_by_id,
                current_step=step,
                vote_counts=vote_counts,
                visible_comment_ids_by_agent=visible_comment_ids_by_agent,
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
                if not base_sim._is_error_stub(op_target_text):
                    thread_digest = base_sim._build_thread_digest(
                        visible_comment_ids=visible_comment_ids,
                        comment_text_by_id=comment_text_by_id,
                        comment_scores=comment_scores,
                        comment_role_by_id=comment_role_by_id,
                    )
                    op_prompt = base_sim._build_op_prompt(
                        post=post,
                        bucket_label=bucket_label,
                        target_comment_text=op_target_text,
                        thread_digest=thread_digest,
                    )
                    op_resp = await llm.generate_comment(
                        op_session,
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
            metadata["agent_seen_comment_counts"] = {
                agent_id: len(seen_ids)
                for agent_id, seen_ids in seen_comment_ids_by_agent.items()
            }

        verdict_cutoff_step = 5 if config.timeline_mode == "24h" else None
        eligible_comment_ids = {
            action.comment_id
            for action in timeline
            if (
                action.role == "commenter"
                and action.comment_id is not None
                and action.parent_comment_id is None
                and (verdict_cutoff_step is None or action.step <= verdict_cutoff_step)
            )
        }
        eligible_scores = {comment_id: comment_scores.get(comment_id, 0) for comment_id in eligible_comment_ids}
        verdict_label_by_comment_id = {
            action.comment_id: action.verdict_label
            for action in timeline
            if action.role == "commenter" and action.parent_comment_id is None and action.verdict_label
        }
        verdict_tally: Dict[str, int] = {}
        for label in verdict_label_by_comment_id.values():
            verdict_tally[label] = verdict_tally.get(label, 0) + 1
        metadata["verdict_tally"] = verdict_tally
        weighted_tally = base_sim._build_weighted_verdict_tally(
            eligible_comment_ids=list(eligible_comment_ids),
            comment_scores=comment_scores,
            comment_vote_totals=comment_vote_totals,
            verdict_label_by_comment_id=verdict_label_by_comment_id,
        )
        metadata["verdict_weighted_tally"] = weighted_tally

        if eligible_scores:
            verdict_comment_id, verdict_score = max(eligible_scores.items(), key=lambda item: item[1])
            metadata["verdict_comment_id"] = verdict_comment_id
            metadata["verdict_score"] = verdict_score
            top_comment_label = verdict_label_by_comment_id.get(verdict_comment_id)
            metadata["top_comment_verdict_label"] = top_comment_label
            if top_comment_label is None and verdict_tally:
                top_comment_label = max(verdict_tally, key=lambda k: verdict_tally[k])
            metadata["verdict_label"] = base_sim._resolve_final_verdict(weighted_tally, top_comment_label)
        else:
            metadata["verdict_comment_id"] = None
            metadata["verdict_score"] = None
            metadata["top_comment_verdict_label"] = None
            metadata["verdict_label"] = base_sim._resolve_final_verdict(weighted_tally, None)

        metadata["usage"] = base_sim._normalize_usage_summary(llm.end_usage_capture(usage_token))

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
    provider_plan = base_sim._build_provider_plan(
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
            scaled_commenters = base_sim._scaled_num_commenters(
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
    batch_usage = base_sim._merge_usage_summaries(
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
            "scaling_rule": "power_cap_min",
            "source_count": len(finalized_posts),
            "provider_distribution": provider_counts,
            "accuracy": {
                "correct": correct,
                "total": total_with_verdict,
                "rate": accuracy,
            },
            "usage": batch_usage,
            "session_mode": "per_commenter_isolated",
        },
        posts=finalized_posts,
    )

    out = batch_run.dict()
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()

    storage.save_batch_run_json(batch_run_id, out)
    return out