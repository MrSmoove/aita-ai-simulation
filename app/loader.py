from __future__ import annotations

import json
from pathlib import Path
from typing import list

from app.models import ScrapedPost


def load_posts_jsonl(path: str | Path) -> list[ScrapedPost]:
    posts: list[ScrapedPost] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            posts.append(
                ScrapedPost(
                    post_id=str(obj.get("post_id") or obj.get("id")),
                    title=(obj.get("title") or "").strip(),
                    body=(obj.get("body") or obj.get("selftext") or "").strip(),
                    true_verdict=obj.get("true_verdict"),
                    topic=obj.get("topic"),
                    author=obj.get("author"),
                )
            )
    return posts