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


async def main():
    parser = argparse.ArgumentParser(description="Run AITA simulation locally")
    parser.add_argument("--post-id", default="cli-run-1", help="Post ID")
    parser.add_argument("--title", default="Am I the asshole?", help="Post title")
    parser.add_argument("--body", default="My situation...", help="Post body")
    parser.add_argument("--author", default="u/anonymous", help="Author")
    parser.add_argument("--num-commenters", type=int, default=3, help="Number of commenter agents")
    parser.add_argument("--max-steps", type=int, default=2, help="Max simulation steps")
    parser.add_argument("--op-enabled", action="store_true", default=True, help="Enable OP replies")
    parser.add_argument("--model", default="oasis-small", help="Model name")
    parser.add_argument("--output", default=None, help="Output JSON file (default: data/runs/{run_id}.json)")
    
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
        num_commenters=args.num_commenters,
        max_steps=args.max_steps,
        op_enabled=args.op_enabled,
    )
    
    print(f"\n▶ Running simulation: {post.post_id}")
    print(f"  Title: {post.title}")
    print(f"  Commenters: {config.num_commenters}, Steps: {config.max_steps}, OP: {config.op_enabled}\n")
    
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
    
    print(f"\n✓ Simulation complete. Run ID: {result['run_id']}")
    print(f"  Saved to: {output_path}")
    print(f"  DB: data/runs.db")


if __name__ == "__main__":
    asyncio.run(main())