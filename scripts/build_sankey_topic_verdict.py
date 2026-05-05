#!/usr/bin/env python3
"""Build Sankey diagram: topic -> Reddit verdict -> AI verdict."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import plotly.graph_objects as go


INPUT_CSV = Path("data/batch_runs/topic_verdict_rows.csv")
OUTPUT_HTML = Path("data/batch_runs/sankey_topic_verdict.html")
OUTPUT_PNG = Path("data/batch_runs/sankey_topic_verdict.png")

VALID_VERDICTS = ["NTA", "YTA", "NAH", "ESH"]
TOPICS = ["family", "social", "relationship", "money", "work", "other"]

NODES = [
    # topics (0-5)
    "family",
    "social",
    "relationship",
    "money",
    "work",
    "other",
    # reddit verdicts (6-9)
    "Reddit: NTA",
    "Reddit: YTA",
    "Reddit: NAH",
    "Reddit: ESH",
    # AI verdicts (10-13)
    "AI: NTA",
    "AI: YTA",
    "AI: NAH",
    "AI: ESH",
]

NODE_COLORS = [
    "#1D9E75",
    "#378ADD",
    "#D85A30",
    "#BA7517",
    "#7F77DD",
    "#888780",
    # topics
    "#1D9E75",
    "#D85A30",
    "#7F77DD",
    "#BA7517",
    # reddit verdicts
    "#1D9E75",
    "#D85A30",
    "#7F77DD",
    "#BA7517",
    # AI verdicts
]

NODE_X = [
    0.01, 0.01, 0.01, 0.01, 0.01, 0.01,  # topics
    0.5, 0.5, 0.5, 0.5,                  # reddit verdicts
    0.99, 0.99, 0.99, 0.99,              # AI verdicts
]

NODE_Y = [
    0.1, 0.35, 0.55, 0.72, 0.82, 0.90,   # topics
    0.1, 0.72, 0.82, 0.88,               # reddit verdicts
    0.1, 0.88, 0.93, 0.96,               # AI verdicts
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Sankey: topic -> Reddit verdict -> AI verdict")
    parser.add_argument("--input", default=str(INPUT_CSV), help="Input CSV path")
    parser.add_argument("--html", default=str(OUTPUT_HTML), help="Output HTML path")
    parser.add_argument("--png", default=str(OUTPUT_PNG), help="Output PNG path")
    return parser.parse_args()


def hex_to_rgba(hex_color: str, alpha: float = 0.4) -> str:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def print_crosstab(title: str, row_keys: list[str], col_keys: list[str], counts: dict[str, dict[str, int]]) -> None:
    print(title)
    header = [" ".ljust(14)] + [key.rjust(7) for key in col_keys] + ["  Total"]
    print("".join(header))
    for row_key in row_keys:
        row_total = 0
        cells = [row_key.ljust(14)]
        for col_key in col_keys:
            value = counts[row_key][col_key]
            row_total += value
            cells.append(str(value).rjust(7))
        cells.append(f"  {row_total}")
        print("".join(cells))
    print()


def main() -> None:
    args = parse_args()
    input_csv = Path(args.input)
    output_html = Path(args.html)
    output_png = Path(args.png)

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv.as_posix()}")

    topic_to_reddit: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reddit_to_ai: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    total_rows = 0
    skipped_rows = 0

    with input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rv = (row.get("redditor_verdict") or "").strip().upper()
            ai = (row.get("ai_verdict") or "").strip().upper()
            if rv not in VALID_VERDICTS or ai not in VALID_VERDICTS:
                skipped_rows += 1
                continue

            topic = (row.get("topic") or "").strip().lower()
            if topic not in TOPICS:
                topic = "other"

            topic_to_reddit[topic][rv] += 1
            reddit_to_ai[rv][ai] += 1
            total_rows += 1

    node_index = {label: index for index, label in enumerate(NODES)}

    sources: list[int] = []
    targets: list[int] = []
    values: list[int] = []
    link_colors: list[str] = []

    for topic in TOPICS:
        topic_node = topic
        source_idx = node_index[topic_node]
        for verdict in VALID_VERDICTS:
            value = topic_to_reddit[topic][verdict]
            if value == 0:
                continue
            target_idx = node_index[f"Reddit: {verdict}"]
            sources.append(source_idx)
            targets.append(target_idx)
            values.append(value)
            link_colors.append(hex_to_rgba(NODE_COLORS[source_idx], 0.4))

    for verdict in VALID_VERDICTS:
        source_idx = node_index[f"Reddit: {verdict}"]
        for ai_verdict in VALID_VERDICTS:
            value = reddit_to_ai[verdict][ai_verdict]
            if value == 0:
                continue
            target_idx = node_index[f"AI: {ai_verdict}"]
            sources.append(source_idx)
            targets.append(target_idx)
            values.append(value)
            link_colors.append(hex_to_rgba(NODE_COLORS[source_idx], 0.4))

    percentages = [f"{(v / total_rows * 100):.1f}%" if total_rows else "0.0%" for v in values]

    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            node=dict(
                label=NODES,
                color=NODE_COLORS,
                pad=12,
                thickness=14,
                line=dict(width=0),
                x=NODE_X,
                y=NODE_Y,
            ),
            link=dict(
                source=sources,
                target=targets,
                value=values,
                color=link_colors,
                customdata=percentages,
                hovertemplate="%{source.label} -> %{target.label}<br>%{value} posts (%{customdata})<extra></extra>",
            ),
        )
    )

    fig.update_layout(
        title_text=f"Post topic -> Reddit verdict -> AI verdict  (n={total_rows:,})",
        title_font_size=15,
        font_size=13,
        height=550,
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor="white",
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_html))
    fig.write_image(str(output_png), width=1200, height=600, scale=2)

    print(f"Total rows processed: {total_rows}")
    if skipped_rows:
        print(f"Skipped rows (invalid/missing verdicts): {skipped_rows}")
    print()
    print_crosstab(
        "Cross-tab: topic -> redditor_verdict",
        TOPICS,
        VALID_VERDICTS,
        topic_to_reddit,
    )
    print_crosstab(
        "Cross-tab: redditor_verdict -> ai_verdict",
        VALID_VERDICTS,
        VALID_VERDICTS,
        reddit_to_ai,
    )
    print(f"HTML: {output_html.as_posix()}")
    print(f"PNG:  {output_png.as_posix()}")


if __name__ == "__main__":
    main()
