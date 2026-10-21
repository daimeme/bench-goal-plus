#!/usr/bin/env python3
"""Summarize EdgeBench VLIW SAT Phase 1 campaigns across arms and repeats."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.sat_edgebench_analysis import (  # noqa: E402
    edgebench_phase1_summary,
    render_phase1_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign",
        action="append",
        required=True,
        metavar="ARM=PATH",
        help="arm and EdgeBench campaign directory; repeat for every replicate",
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    return parser


def _campaigns(values: list[str]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for value in values:
        arm, separator, path = value.partition("=")
        if not separator or not arm.strip() or not path.strip():
            raise SystemExit(f"expected ARM=PATH, got {value!r}")
        grouped[arm.strip().upper()].append(Path(path.strip()))
    return grouped


def main() -> int:
    args = build_parser().parse_args()
    summary = edgebench_phase1_summary(
        _campaigns(args.campaign),
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    markdown = render_phase1_markdown(summary)
    if args.json_out:
        output = args.json_out.expanduser().absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    if args.markdown_out:
        output = args.markdown_out.expanduser().absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
