#!/usr/bin/env python3
"""Export per-post topic/verdict rows from batch run artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

RUNS_DIR = Path("data/batch_runs")
TOPIC_ORDER = ["family", "relationship", "work", "money", "social"]
TOPIC_KEYWORDS = {
    "family": [
        "mom", "mother", "dad", "father", "parent", "parents", "sister", "brother",
        "sibling", "wedding", "divorce", "baby", "pregnant", "in law", "in-law",
        "stepmom", "stepdad", "stepmother", "stepfather", "son", "daughter", "aunt",
        "uncle", "cousin", "niece", "nephew", "grandma", "grandpa", "family",
    ],
    "relationship": [
        "boyfriend", "girlfriend", "husband", "wife", "partner", "ex", "cheating",
        "dating", "marriage", "fiance", "fiancee", "engaged", "relationship", "spouse",
        "anniversary", "breakup", "broke up", "romantic",
    ],
    "work": [
        "boss", "coworker", "co worker", "job", "manager", "fired", "salary",
        "promotion", "hr", "office", "workplace", "employee", "employer", "intern",
        "team lead", "pay raise", "laid off", "shift", "career",
    ],
    "money": [
        "rent", "loan", "debt", "bill", "afford", "borrow", "owe", "financial",
        "money", "paid", "paying", "payment", "cost", "expensive", "cheap", "cash",
        "income", "budget", "mortgage", "utility", "utilities",
    ],
    "social": [
        "friend", "party", "event", "invite", "neighbor", "gathering", "group",
        "roommate", "classmate", "social", "hangout", "trip", "vacation", "dinner",
        "birthday", "wedding guest", "club", "community",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export rows: run_id | model | post_id | topic | redditor_verdict | ai_verdict | match"
        )
    )
    parser.add_argument(
        "--batch",
        action="append",
        default=[],
        help="Batch id, filename, or full path. Repeat to include multiple batches.",
    )
    parser.add_argument(
        "--source-dir",
        default=str(RUNS_DIR),
        help="Directory containing batch JSON files (default: data/batch_runs)",
    )
    parser.add_argument(
        "--output",
        default="data/batch_runs/topic_verdict_rows.csv",
        help="CSV output path",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=None,
        help="Only include the latest N batch files by modified time",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print CSV to stdout",
    )
    return parser.parse_args()


def resolve_batch_path(batch_arg: str, source_dir: Path) -> Path:
    candidate = Path(batch_arg)
    if candidate.exists():
        return candidate

    if not candidate.suffix:
        by_id = source_dir / f"{batch_arg}.json"
        if by_id.exists():
            return by_id

    by_name = source_dir / candidate.name
    if by_name.exists():
        return by_name

    raise FileNotFoundError(f"Batch file not found: {batch_arg}")


def load_batches(batch_args: List[str], source_dir: Path, latest: Optional[int]) -> List[Path]:
    if batch_args:
        return [resolve_batch_path(arg, source_dir) for arg in batch_args]

    files = sorted(source_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No batch runs found in {source_dir.as_posix()}")
    if latest is not None:
        files = files[-max(0, latest):]
    return files


def _count_occurrences(text: str, keyword: str) -> int:
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return len(re.findall(pattern, text))


def classify_topic(title: str, body: str) -> str:
    text = f"{title} {body}".lower()
    scores = {topic: 0 for topic in TOPIC_ORDER}

    for topic in TOPIC_ORDER:
        for keyword in TOPIC_KEYWORDS[topic]:
            scores[topic] += _count_occurrences(text, keyword)

    best_topic = max(TOPIC_ORDER, key=lambda topic: scores[topic])
    if scores[best_topic] <= 0:
        return "other"
    return best_topic


def to_match_value(explicit_match: Any, redditor_verdict: Optional[str], ai_verdict: Optional[str]) -> str:
    if explicit_match is True:
        return "true"
    if explicit_match is False:
        return "false"
    if redditor_verdict and ai_verdict:
        return "true" if redditor_verdict == ai_verdict else "false"
    return ""


def iter_rows(batch_data: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    run_id = str(batch_data.get("batch_run_id") or "")
    config = batch_data.get("config") or {}
    fallback_model = str(config.get("model_name") or config.get("provider") or "")

    for post_result in batch_data.get("posts") or []:
        post = post_result.get("post") or {}
        post_id = str(post.get("post_id") or "")
        title = str(post.get("title") or "")
        body = str(post.get("body") or "")
        topic = classify_topic(title, body)
        model = str(post_result.get("simulation_model") or fallback_model)
        redditor_verdict = str(
            post_result.get("source_verdict")
            or post.get("true_verdict")
            or ""
        )
        metadata = post_result.get("metadata") or {}
        ai_verdict = str(metadata.get("verdict_label") or "")
        match = to_match_value(post_result.get("verdict_match"), redditor_verdict, ai_verdict)

        yield {
            "run_id": run_id,
            "model": model,
            "post_id": post_id,
            "topic": topic,
            "redditor_verdict": redditor_verdict,
            "ai_verdict": ai_verdict,
            "match": match,
        }


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_csv(output_path: Path, rows: List[Dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "model",
        "post_id",
        "topic",
        "redditor_verdict",
        "ai_verdict",
        "match",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: List[Dict[str, str]], batch_count: int) -> None:
    print(f"Wrote {len(rows)} rows from {batch_count} batch files")
    if not rows:
        return

    topic_counts = Counter(row["topic"] for row in rows)
    ordered_topics = TOPIC_ORDER + ["other"]

    print("\nTopic distribution:")
    total = len(rows)
    for topic in ordered_topics:
        count = topic_counts.get(topic, 0)
        pct = (count / total) * 100 if total else 0.0
        print(f"  {topic:<13}{count:>4}  ({pct:>4.1f}%)")

    print("\nVerdict accuracy by topic (AI vs Redditor):")
    for topic in ordered_topics:
        topic_rows = [row for row in rows if row["topic"] == topic]
        comparable = [row for row in topic_rows if row["match"] in {"true", "false"}]
        if not comparable:
            print(f"  {topic:<13}n/a")
            continue
        correct = sum(1 for row in comparable if row["match"] == "true")
        pct = (correct / len(comparable)) * 100
        print(f"  {topic:<13}{pct:.1f}%")


def main() -> None:
    args = parse_args()
    source_dir = Path(args.source_dir)
    batch_paths = load_batches(args.batch, source_dir, args.latest)

    rows: List[Dict[str, str]] = []
    for batch_path in batch_paths:
        rows.extend(iter_rows(load_json(batch_path)))

    output_path = Path(args.output)
    write_csv(output_path, rows)

    print_summary(rows, len(batch_paths))
    print(f"CSV written to {output_path.as_posix()}")

    if args.stdout:
        writer = csv.DictWriter(
            __import__("sys").stdout,
            fieldnames=[
                "run_id",
                "model",
                "post_id",
                "topic",
                "redditor_verdict",
                "ai_verdict",
                "match",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
