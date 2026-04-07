from __future__ import annotations

import asyncio
from dotenv import load_dotenv

from app.loader import load_posts_jsonl
from app.simulation import run_single_post


async def main():
    load_dotenv()

    posts = load_posts_jsonl("data/reddit/scraped_posts.jsonl")
    post = posts[0]

    result = await run_single_post(
        post=post,
        profile_path="data/reddit/user_data_36.json",
        db_path="data/reddit_simulation.db",
        out_path=f"data/runs/{post.post_id}.json",
        max_steps=3,
    )

    print("Finished run for:", result["post_id"])


if __name__ == "__main__":
    asyncio.run(main())