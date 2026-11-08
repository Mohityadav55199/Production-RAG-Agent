#!/usr/bin/env python3
"""Turn the JSON files written by eval/run_comparison.sh into a Markdown comparison table.

    python eval/summarize_results.py            # prints the table
    python eval/summarize_results.py --write    # also rewrites the table between the markers in eval/README.md
"""

import argparse
import json
import re
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
README = Path(__file__).resolve().parent / "README.md"
BEGIN, END = "<!-- results:begin -->", "<!-- results:end -->"

STAGES = [
    ("1_vector.json", "Vector search"),
    ("2_hybrid.json", "+ exact-term (hybrid) search"),
    ("3_hybrid_rerank.json", "+ reranking"),
    ("4_full_pipeline.json", "+ follow-up question rewriting"),
]


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_table() -> str:
    rows = []
    total = None
    for filename, label in STAGES:
        path = RESULTS / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        m = data["metrics"]
        follow_up = data["category_breakdown"].get("follow_up", {}).get("mrr")
        total = m["total_queries"]
        rows.append(
            f"| {label} | {pct(m['hit_rate_1'])} | {pct(m['hit_rate_5'])} | {pct(m['section_hit_5'])} "
            f"| {m['mrr']:.3f} | {follow_up:.3f} | {m['avg_latency_ms'] / 1000:.2f} s |"
        )
    header = (
        f"Live run on {total} questions (Gemini embeddings, Qdrant, `--min-score 0.63 --max-gap 0.05`, top 5):\n\n"
        "| Pipeline stage | Hit@1 | Hit@5 | Section@5 | MRR | Follow-up MRR | Avg retrieval time |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    return header + "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="update the table inside eval/README.md")
    args = parser.parse_args()

    table = build_table()
    print(table)
    if args.write:
        text = README.read_text(encoding="utf-8")
        block = f"{BEGIN}\n{table}\n{END}"
        if BEGIN in text:
            text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
        else:
            raise SystemExit(f"Add the markers {BEGIN} and {END} to {README} first.")
        README.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
