#!/usr/bin/env python3
"""
Run a batch simulation from scraped Reddit posts and save a single batch artifact.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio

from app.services import simulation


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch simulations from scraped Reddit posts")
    parser.add_argument("--source", default="data/reddit/aita_posts.json", help="Path to scraped posts JSON")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Model name")
    parser.add_argument("--max-steps", type=int, default=6, help="Max steps per simulated post")
    parser.add_argument("--commenter-cap", type=int, default=50, help="Max commenters per simulated post")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of scraped posts to process")
    args = parser.parse_args()

    result = await simulation.run_batch_from_scrape(
        source_file=args.source,
        model_name=args.model,
        max_steps=args.max_steps,
        commenter_cap=args.commenter_cap,
        limit=args.limit,
    )

    print(f"✓ Batch simulation complete. Batch ID: {result['batch_run_id']}")
    print(f"  Source: {result['source_file']}")
    print(f"  Posts: {len(result['posts'])}")
    print(f"  Saved to: data/batch_runs/{result['batch_run_id']}.json")


if __name__ == "__main__":
    asyncio.run(main())
