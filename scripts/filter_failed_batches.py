#!/usr/bin/env python3
"""
Filter out posts with failed/error comments from batch run JSON files.
Posts are removed if any comment in their timeline contains "(error:".
"""
import json
import sys
from pathlib import Path


def has_failed_comments(timeline: list) -> bool:
    """Check if any comment in the timeline has failed (contains error marker)."""
    for action in timeline:
        text = action.get("text", "")
        if "(error:" in text:
            return True
    return False


def filter_batch_run(batch_file: Path) -> dict:
    """Load batch, remove posts with failed comments, return cleaned batch and counts."""
    with open(batch_file, "r", encoding="utf-8") as f:
        batch = json.load(f)
    
    original_posts = batch.get("posts", [])
    cleaned_posts = []
    removed_count = 0
    
    for post in original_posts:
        timeline = post.get("timeline", [])
        if has_failed_comments(timeline):
            removed_count += 1
        else:
            cleaned_posts.append(post)
    
    batch["posts"] = cleaned_posts
    
    # Recalculate accuracy based on remaining posts
    if cleaned_posts:
        correct = sum(1 for p in cleaned_posts if p.get("verdict_match") is True)
        total = sum(1 for p in cleaned_posts if p.get("verdict_match") is not None)
        if total > 0:
            batch["config"]["accuracy"] = {
                "correct": correct,
                "total": total,
                "rate": round(correct / total, 3)
            }
    
    return batch, removed_count, len(original_posts)


def main():
    batch_dir = Path("data/batch_runs")
    if not batch_dir.exists():
        print(f"Batch directory not found: {batch_dir}")
        sys.exit(1)
    
    batch_files = sorted(batch_dir.glob("*.json"))
    print(f"Found {len(batch_files)} batch files\n")
    
    total_removed = 0
    total_posts_processed = 0
    
    for batch_file in batch_files:
        try:
            cleaned_batch, removed, total = filter_batch_run(batch_file)
            total_removed += removed
            total_posts_processed += total
            
            if removed > 0:
                # Save the cleaned batch back
                with open(batch_file, "w", encoding="utf-8") as f:
                    json.dump(cleaned_batch, f, indent=2)
                print(f"✓ {batch_file.name}: removed {removed}/{total} posts with failed comments")
            else:
                print(f"  {batch_file.name}: no failed posts found ({total} posts)")
        except Exception as e:
            print(f"✗ {batch_file.name}: error - {e}")
    
    print(f"\nSummary:")
    print(f"  Total posts processed: {total_posts_processed}")
    print(f"  Total posts removed: {total_removed}")
    print(f"  Posts retained: {total_posts_processed - total_removed}")


if __name__ == "__main__":
    main()
