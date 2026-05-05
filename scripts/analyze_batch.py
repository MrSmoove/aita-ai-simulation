#!/usr/bin/env python3
"""Analyze one batch-run JSON and emit spreadsheet-friendly summaries."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


RUNS_DIR = Path("data/batch_runs")
VERDICTS = ("NTA", "YTA", "ESH", "NAH")


def display_provider_name(name: str) -> str:
    mapping = {
        "openai": "OpenAI",
        "deepseek": "DeepSeek",
        "mistral": "Mistral",
        "groq": "Groq",
        "gemini": "Gemini",
    }
    return mapping.get((name or "").lower(), name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze a batch run JSON for spreadsheet entry")
    parser.add_argument("batch", nargs="?", help="Batch id, batch json filename, or full path. Defaults to latest batch file.")
    parser.add_argument("--run-label", default=None, help="Optional sheet label like Run-009")
    parser.add_argument("--dataset-type", default=None, help="Optional override for the dataset type / label column")
    parser.add_argument(
        "--format",
        choices=["pretty", "json"],
        default="pretty",
        help="Output format",
    )
    parser.add_argument(
        "--write-csv",
        default=None,
        help="Optional output directory for config_row.csv and results_row.csv",
    )
    return parser.parse_args()


def resolve_batch_path(batch_arg: Optional[str]) -> Path:
    if not batch_arg:
        files = sorted(RUNS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not files:
            raise SystemExit("No batch runs found in data/batch_runs")
        return files[-1]

    candidate = Path(batch_arg)
    if candidate.exists():
        return candidate

    if not candidate.suffix:
        batch_file = RUNS_DIR / f"{batch_arg}.json"
        if batch_file.exists():
            return batch_file

    batch_file = RUNS_DIR / candidate.name
    if batch_file.exists():
        return batch_file

    raise SystemExit(f"Batch file not found: {batch_arg}")


def load_batch(batch_path: Path) -> Dict[str, Any]:
    return json.loads(batch_path.read_text(encoding="utf-8"))


def pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def format_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def short_source_label(source_file: str) -> str:
    stem = Path(source_file).stem
    return stem.replace("_", " ")


def infer_dataset_type(source_file: str, posts: list[Dict[str, Any]]) -> str:
    verdict_counts = Counter((post.get("source_verdict") or "UNKNOWN") for post in posts)
    total = len(posts)
    named_counts = [f"{verdict_counts[label]} {label}" for label in VERDICTS if verdict_counts.get(label)]
    source_hint = short_source_label(source_file)
    if named_counts:
        return f"{total} posts ({', '.join(named_counts)}) | {source_hint}"
    return f"{total} posts | {source_hint}"


def models_used_string(usage_models: Dict[str, int], provider_distribution: Dict[str, int]) -> str:
    if provider_distribution:
        ordered_providers = sorted(provider_distribution)
        return ",".join(display_provider_name(name) for name in ordered_providers)
    if usage_models:
        return ",".join(sorted(usage_models))
    return "unknown"


def provider_distribution_string(provider_distribution: Dict[str, int]) -> str:
    if not provider_distribution:
        return "unknown"
    total = sum(provider_distribution.values()) or 1
    ordered = sorted(provider_distribution.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{display_provider_name(name)} {count/total*100:.1f}% ({count})" for name, count in ordered)


def format_run_date(created_at: str) -> str:
    if not created_at:
        return ""
    dt = datetime.fromisoformat(created_at)
    return f"{dt.month}/{dt.day}"


def interaction_mode(provider_distribution: Dict[str, int], provider_strategy: Optional[str]) -> str:
    if len(provider_distribution) > 1:
        return "Cross Model"
    if (provider_strategy or "").lower() == "single":
        return "Single Provider"
    return "Single Model"


def analyze_posts(posts: list[Dict[str, Any]]) -> Dict[str, Any]:
    source_counts = Counter()
    ai_counts = Counter()
    label_totals = Counter()
    label_correct = Counter()
    mismatch_counts = Counter()
    provider_totals = Counter()
    provider_correct = Counter()
    provider_by_mismatch = defaultdict(Counter)

    for post in posts:
        real = post.get("source_verdict")
        ai = (post.get("metadata") or {}).get("verdict_label")
        provider = post.get("simulation_provider") or "unknown"
        match = post.get("verdict_match")

        if real:
            source_counts[real] += 1
            label_totals[real] += 1
        if ai:
            ai_counts[ai] += 1
        provider_totals[provider] += 1
        if match is True:
            provider_correct[provider] += 1
            if real:
                label_correct[real] += 1
        elif match is False and real and ai:
            mismatch_counts[(real, ai)] += 1
            provider_by_mismatch[provider][(real, ai)] += 1

    total_predictions = sum(ai_counts.values())
    label_accuracy = {label: pct(label_correct[label], label_totals[label]) for label in VERDICTS}
    ai_distribution = {label: pct(ai_counts[label], total_predictions) for label in VERDICTS}

    top_mismatch = None
    if mismatch_counts:
        (real, ai), count = mismatch_counts.most_common(1)[0]
        top_mismatch = f"{real} -> {ai}: {count} cases"

    provider_winner = None
    provider_scores = []
    for provider, total in provider_totals.items():
        score = pct(provider_correct[provider], total)
        provider_scores.append((score or 0.0, provider_correct[provider], total, provider))
    if provider_scores:
        score, correct, total, provider = max(provider_scores)
        provider_winner = f"{provider} {score:.1f}% ({correct}/{total})"

    dataset_nta = pct(source_counts["NTA"], sum(source_counts.values()))
    ai_nta = ai_distribution["NTA"]
    nta_bias = None
    if dataset_nta is not None and ai_nta is not None:
        delta = round(ai_nta - dataset_nta, 1)
        if abs(delta) >= 5:
            direction = "toward NTA" if delta > 0 else "away from NTA"
            nta_bias = f"YES ({delta:+.1f} pts {direction})"
        else:
            nta_bias = f"No ({delta:+.1f} pts)"

    notes = []
    if top_mismatch:
        notes.append(f"Top mismatch: {top_mismatch}")
    if provider_winner:
        notes.append(f"Provider winner: {provider_winner}")
    if ai_nta is not None and dataset_nta is not None:
        notes.append(f"AI NTA share {ai_nta:.1f}% vs dataset NTA share {dataset_nta:.1f}%")

    return {
        "source_counts": dict(source_counts),
        "ai_counts": dict(ai_counts),
        "label_accuracy": label_accuracy,
        "ai_distribution": ai_distribution,
        "top_mismatch": top_mismatch,
        "provider_winner": provider_winner,
        "nta_bias": nta_bias,
        "notes": "; ".join(notes),
    }


def build_rows(batch_path: Path, data: Dict[str, Any], run_label: Optional[str], dataset_type_override: Optional[str]) -> Dict[str, Dict[str, Any]]:
    config = data.get("config") or {}
    posts = data.get("posts") or []
    usage = config.get("usage") or {}
    provider_distribution = config.get("provider_distribution") or {}
    accuracy = config.get("accuracy") or {}
    post_analysis = analyze_posts(posts)

    source_file = data.get("source_file") or config.get("source_file") or ""
    dataset_type = dataset_type_override or infer_dataset_type(source_file, posts)
    created_at = data.get("created_at") or ""
    run_date = format_run_date(created_at)

    config_row = {
        "Run ID": run_label or data.get("batch_run_id"),
        "Run Date": run_date,
        "Batch JSON File": batch_path.as_posix(),
        "Notes": "",
        "Dataset": short_source_label(source_file),
        "Total Posts": len(posts),
        "NTA Posts": post_analysis["source_counts"].get("NTA", 0),
        "YTA Posts": post_analysis["source_counts"].get("YTA", 0),
        "ESH Posts": post_analysis["source_counts"].get("ESH", 0),
        "NAH Posts": post_analysis["source_counts"].get("NAH", 0),
        "Dataset Type": dataset_type,
        "Provider Strategy": config.get("provider_strategy"),
        "Models Used": models_used_string(usage.get("models") or {}, provider_distribution),
        "Provider Distribution": provider_distribution_string(provider_distribution),
        "Interaction Mode": interaction_mode(provider_distribution, config.get("provider_strategy")),
        "Timeline Mode": config.get("timeline_mode"),
        "Max Steps / Waves": config.get("max_steps"),
        "Commenter Cap": config.get("commenter_cap"),
        "Commenter Scale": config.get("commenter_scale_power"),
        "Voter Ratio": config.get("voter_ratio"),
        "Mobility": config.get("mobility"),
        "Agent Archetypes": "Blank Slate",
    }

    results_row = {
        "Run ID": run_label or data.get("batch_run_id"),
        "Models Used": models_used_string(usage.get("models") or {}, provider_distribution),
        "Dataset Type": dataset_type,
        "Overall Accuracy %": format_pct(pct(accuracy.get("correct", 0), accuracy.get("total", 0))),
        "NTA Accuracy %": format_pct(post_analysis["label_accuracy"].get("NTA")),
        "YTA Accuracy %": format_pct(post_analysis["label_accuracy"].get("YTA")),
        "ESH Accuracy %": format_pct(post_analysis["label_accuracy"].get("ESH")),
        "NAH Accuracy %": format_pct(post_analysis["label_accuracy"].get("NAH")),
        "AI NTA %": format_pct(post_analysis["ai_distribution"].get("NTA")),
        "AI YTA %": format_pct(post_analysis["ai_distribution"].get("YTA")),
        "AI ESH %": format_pct(post_analysis["ai_distribution"].get("ESH")),
        "AI NAH %": format_pct(post_analysis["ai_distribution"].get("NAH")),
        "NTA Bias?": post_analysis["nta_bias"] or "n/a",
        "Top Mismatch": post_analysis["top_mismatch"] or "n/a",
        "Provider Winner": post_analysis["provider_winner"] or "n/a",
        "Notes / Observations": post_analysis["notes"],
    }

    return {
        "config_row": config_row,
        "results_row": results_row,
    }


def print_pretty(batch_path: Path, data: Dict[str, Any], rows: Dict[str, Dict[str, Any]]) -> None:
    config = data.get("config") or {}
    print(f"Batch: {data.get('batch_run_id')}")
    print(f"File:  {batch_path.as_posix()}")
    print(f"Providers: {provider_distribution_string(config.get('provider_distribution') or {})}")
    print()
    print("Config Tracker Row")
    print("-" * 80)
    for key, value in rows["config_row"].items():
        print(f"{key}: {value}")
    print()
    print("Results Tracker Row")
    print("-" * 80)
    for key, value in rows["results_row"].items():
        print(f"{key}: {value}")


def write_csv_rows(output_dir: Path, rows: Dict[str, Dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, row in rows.items():
        output_path = output_dir / f"{name}.csv"
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    batch_path = resolve_batch_path(args.batch)
    data = load_batch(batch_path)
    rows = build_rows(batch_path, data, args.run_label, args.dataset_type)

    if args.write_csv:
        write_csv_rows(Path(args.write_csv), rows)

    if args.format == "json":
        print(json.dumps(rows, indent=2))
        return

    print_pretty(batch_path, data, rows)


if __name__ == "__main__":
    main()
