#!/usr/bin/env python3
"""
Compare multiple batch runs side by side.

Usage:
  # Compare all runs
  python scripts/compare_runs.py

  # Compare specific runs
  python scripts/compare_runs.py <batch_id_1> <batch_id_2> ...

  # Last N runs
  python scripts/compare_runs.py --last 5
"""
import sys
import json
import argparse
from pathlib import Path
from collections import Counter

RUNS_DIR = Path("data/batch_runs")

CONFIG_FIELDS = [
    ("source_file",           "dataset"),
    ("provider_strategy",     "strategy"),
    ("timeline_mode",         "timeline"),
    ("commenter_cap",         "cap"),
    ("voter_ratio",           "voter_r"),
    ("commenter_scale_power", "scale^"),
    ("mobility",              "mob"),
    ("concurrency",           "conc"),
]

VERDICT_LABELS = ["NTA", "YTA", "ESH", "NAH", "INFO", "SPLIT", "MIXED", "INCONCLUSIVE"]


def load_batch(path: Path) -> dict:
    return json.load(open(path, encoding="utf-8"))


def verdict_dist(data: dict) -> Counter:
    return Counter(
        (p.get("metadata") or {}).get("verdict_label")
        for p in data["posts"]
    )


def provider_summary(data: dict) -> str:
    dist = data["config"].get("provider_distribution") or {}
    if not dist:
        return data["config"].get("provider_strategy", "?")
    if len(dist) == 1:
        name = next(iter(dist))
        return name
    total = sum(dist.values())
    return "+".join(f"{k}({v/total:.0%})" for k, v in sorted(dist.items()))


def short_id(batch_id: str) -> str:
    return batch_id[:8]


def short_source(source_file: str) -> str:
    return Path(source_file).stem[:28]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", help="Batch IDs to compare")
    parser.add_argument("--last", type=int, default=None, help="Show last N runs")
    args = parser.parse_args()

    all_files = sorted(RUNS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)

    if args.ids:
        files = [RUNS_DIR / f"{bid}.json" for bid in args.ids]
        missing = [f for f in files if not f.exists()]
        if missing:
            print(f"Not found: {missing}")
            sys.exit(1)
    elif args.last:
        files = all_files[-args.last:]
    else:
        files = all_files

    if not files:
        print("No batch runs found.")
        return

    runs = [(f, load_batch(f)) for f in files]

    # ── Header ────────────────────────────────────────────────────────────────
    col_w = 10
    id_w  = 10
    src_w = 30

    header_parts = [
        f"{'ID':<{id_w}}",
        f"{'created':<19}",
        f"{'dataset':<{src_w}}",
        f"{'providers':<18}",
        f"{'cap':>4}",
        f"{'vr':>4}",
        f"{'sc^':>4}",
        f"{'mob':>4}",
        f"{'conc':>4}",
        f"{'acc':>6}",
        f"{'NTA':>5}",
        f"{'YTA':>5}",
        f"{'ESH':>4}",
        f"{'NAH':>4}",
        f"{'other':>6}",
    ]
    header = "  ".join(header_parts)
    print(header)
    print("─" * len(header))

    for path, data in runs:
        cfg   = data["config"]
        acc   = cfg.get("accuracy", {})
        dist  = verdict_dist(data)
        total = sum(dist.values())
        other = total - dist["NTA"] - dist["YTA"] - dist["ESH"] - dist["NAH"]

        created = data.get("created_at", "")[:19]
        src     = short_source(cfg.get("source_file", ""))
        prov    = provider_summary(data)
        bid     = short_id(data["batch_run_id"])
        rate    = acc.get("rate", 0)
        correct = acc.get("correct", "?")
        tot     = acc.get("total", "?")

        row_parts = [
            f"{bid:<{id_w}}",
            f"{created:<19}",
            f"{src:<{src_w}}",
            f"{prov:<18}",
            f"{cfg.get('commenter_cap', '?'):>4}",
            f"{cfg.get('voter_ratio', '?'):>4}",
            f"{cfg.get('commenter_scale_power', '?'):>4}",
            f"{cfg.get('mobility', '?'):>4}",
            f"{cfg.get('concurrency', '?'):>4}",
            f"{correct}/{tot} {rate*100:.0f}%",
            f"{dist['NTA']:>5}",
            f"{dist['YTA']:>5}",
            f"{dist['ESH']:>4}",
            f"{dist['NAH']:>4}",
            f"{other:>6}",
        ]
        print("  ".join(row_parts))


if __name__ == "__main__":
    main()
