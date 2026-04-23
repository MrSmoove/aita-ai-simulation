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
from app.services import storage


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch simulations from scraped Reddit posts")
    parser.add_argument("--source", default="data/reddit/aita_posts.json", help="Path to scraped posts JSON")
    parser.add_argument("--provider", default=None, help="Provider name for single-provider runs")
    parser.add_argument("--provider-strategy", default="balanced", choices=["balanced", "single"], help="How providers are assigned across posts")
    parser.add_argument("--model", default=None, help="Model name for single-provider runs")
    parser.add_argument("--timeline-mode", default="basic", choices=["basic", "24h"], help="Simulation timeline mode")
    parser.add_argument("--max-steps", type=int, default=6, help="Max steps per simulated post")
    parser.add_argument("--commenter-cap", type=int, default=50, help="Max commenters per simulated post")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of posts to simulate in parallel")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of scraped posts to process")
    args = parser.parse_args()
    storage.init_db()

    result = await simulation.run_batch_from_scrape(
        source_file=args.source,
        model_name=args.model,
        max_steps=args.max_steps,
        commenter_cap=args.commenter_cap,
        concurrency=args.concurrency,
        provider_strategy=args.provider_strategy,
        provider=args.provider,
        timeline_mode=args.timeline_mode,
        limit=args.limit,
    )

    print(f"✓ Batch simulation complete. Batch ID: {result['batch_run_id']}")
    print(f"  Source: {result['source_file']}")
    print(f"  Posts: {len(result['posts'])}")
    print(f"  Provider strategy: {result['config'].get('provider_strategy')}")
    print(f"  Timeline mode: {result['config'].get('timeline_mode')}")
    print(f"  Saved to: data/batch_runs/{result['batch_run_id']}.json")
    usage = result.get("config", {}).get("usage", {})
    provider_distribution = result.get("config", {}).get("provider_distribution", {})
    if provider_distribution:
        print(
            "  Providers: "
            + ", ".join(f"{name} ({count})" for name, count in provider_distribution.items())
        )
    if usage:
        print("  Usage summary:")
        print(f"    Requests: {usage.get('request_count', 0)}")
        print(f"    Prompt tokens: {usage.get('prompt_tokens', 0)}")
        print(f"    Completion tokens: {usage.get('completion_tokens', 0)}")
        print(f"    Total tokens: {usage.get('total_tokens', 0)}")
        if usage.get("models"):
            models = ", ".join(f"{name} ({count})" for name, count in usage["models"].items())
            print(f"    Models: {models}")
        if usage.get("providers"):
            providers = ", ".join(f"{name} ({count})" for name, count in usage["providers"].items())
            print(f"    Provider calls: {providers}")


if __name__ == "__main__":
    asyncio.run(main())
