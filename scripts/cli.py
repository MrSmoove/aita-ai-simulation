#!/usr/bin/env python3
"""
Simple CLI to run AITA simulations locally without Streamlit.
Usage:
  python scripts/cli.py --post-id p1 --title "Am I the asshole?" --body "My story..." --num-commenters 3 --max-steps 2
"""
import sys
from pathlib import Path

# Add project root to sys.path so "import app" works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import argparse
import json

from app.schemas import Post, SimulationConfig
from app.services import simulation, storage


def render_pretty_run(result: dict) -> str:
    post = result["post"]
    config = result["config"]
    metadata = result.get("metadata") or {}

    lines = [
        f"Run ID: {result['run_id']}",
        f"Created: {result['created_at']}",
        "",
        "Post",
        f"  ID: {post['post_id']}",
        f"  Title: {post['title']}",
        f"  Author: {post.get('author') or 'unknown'}",
        "",
        "Body",
        post["body"],
        "",
        "Config",
        f"  Provider: {config['provider']}",
        f"  Model: {config['model_name']}",
        f"  Commenters: {config['num_commenters']}",
        f"  Steps: {config['max_steps']}",
        f"  OP enabled: {config['op_enabled']}",
        f"  Timeline mode: {config.get('timeline_mode', 'basic')}",
        "",
        "Timeline",
    ]

    for action in result["timeline"]:
        lines.extend(
            [
                f"  Step {action['step']} | {action['role']} | {action['agent_id']} | {action.get('provider') or 'unknown'} | {action.get('bucket_label') or 'n/a'} | {action.get('simulated_minute') or 0}m",
                f"  {action['text']}",
                "",
            ]
        )

    verdict_comment_id = metadata.get("verdict_comment_id")
    verdict_score = metadata.get("verdict_score")
    if verdict_comment_id is not None:
        lines.extend(
            [
                "Verdict",
                f"  Winning comment: {verdict_comment_id}",
                f"  Score: {verdict_score}",
                "",
            ]
        )

    comment_scores = metadata.get("comment_scores") or {}
    comment_votes = metadata.get("comment_votes") or {}
    if comment_scores:
        lines.append("Scores")
        for comment_id, score in comment_scores.items():
            votes = comment_votes.get(comment_id, {})
            upvotes = votes.get("upvotes", 0)
            downvotes = votes.get("downvotes", 0)
            lines.append(f"  {comment_id}: {score} (↑{upvotes} ↓{downvotes})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def main():
    parser = argparse.ArgumentParser(description="Run AITA simulation locally")
    parser.add_argument("--post-id", default="cli-run-1", help="Post ID")
    parser.add_argument("--title", default="Am I the asshole?", help="Post title")
    parser.add_argument("--body", default="My situation...", help="Post body")
    parser.add_argument("--author", default="u/anonymous", help="Author")
    parser.add_argument("--num-commenters", type=int, default=3, help="Number of commenter agents")
    parser.add_argument("--max-steps", type=int, default=2, help="Max simulation steps")
    parser.add_argument("--op-enabled", action="store_true", default=True, help="Enable OP replies")
    parser.add_argument("--provider", default="openai", help="Provider name: openai, gemini, or groq")
    parser.add_argument("--model", default=None, help="Model name (defaults to the provider's configured default)")
    parser.add_argument("--timeline-mode", default="basic", choices=["basic", "24h"], help="Simulation timeline mode")
    parser.add_argument("--output", default=None, help="Output JSON file (default: data/runs/{run_id}.json)")
    parser.add_argument(
        "--pretty-output",
        default=None,
        help="Optional text file path for a readable transcript (default: data/runs/{run_id}.txt)",
    )
    
    args = parser.parse_args()
    
    # Initialize DB
    storage.init_db()
    
    # Create post
    post = Post(
        post_id=args.post_id,
        title=args.title,
        body=args.body,
        author=args.author,
    )
    
    # Create config
    config = SimulationConfig(
        model_name=args.model,
        provider=args.provider,
        num_commenters=args.num_commenters,
        max_steps=args.max_steps,
        op_enabled=args.op_enabled,
        timeline_mode=args.timeline_mode,
    )
    
    print(f"\n▶ Running simulation: {post.post_id}")
    print(f"  Title: {post.title}")
    display_steps = 6 if config.timeline_mode == "24h" else config.max_steps
    print(
        f"  Provider: {config.provider}, Model: {config.model_name or 'default'}, "
        f"Commenters: {config.num_commenters}, Steps: {display_steps}, "
        f"OP: {config.op_enabled}, Timeline: {config.timeline_mode}\n"
    )
    
    # Run simulation
    result = await simulation.run_single_post(post, config)
    
    # Print timeline
    print("\n=== TIMELINE ===")
    for action in result["timeline"]:
        print(f"[Step {action['step']}] {action['role'].upper()} ({action['agent_id']}): {action['text'][:80]}...")
    
    # Save result
    output_path = args.output or f"data/runs/{result['run_id']}.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    pretty_output_path = args.pretty_output or f"data/runs/{result['run_id']}.txt"
    Path(pretty_output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(pretty_output_path, "w") as f:
        f.write(render_pretty_run(result))
    
    print(f"\n✓ Simulation complete. Run ID: {result['run_id']}")
    print(f"  Saved to: {output_path}")
    print(f"  Pretty: {pretty_output_path}")
    print(f"  DB: data/runs.db")
    usage = result.get("metadata", {}).get("usage", {})
    if usage:
        print("  Usage summary:")
        print(f"    Requests: {usage.get('request_count', 0)}")
        print(f"    Prompt tokens: {usage.get('prompt_tokens', 0)}")
        print(f"    Completion tokens: {usage.get('completion_tokens', 0)}")
        print(f"    Total tokens: {usage.get('total_tokens', 0)}")
        if usage.get("models"):
            models = ", ".join(f"{name} ({count})" for name, count in usage["models"].items())
            print(f"    Models: {models}")


if __name__ == "__main__":
    asyncio.run(main())
