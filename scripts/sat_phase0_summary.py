#!/usr/bin/env python3
"""Summarize SAT-GP Phase 0 pilot campaigns across repeats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.sat_analysis import (  # noqa: E402
    phase0_summary,
    render_phase0_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign",
        action="append",
        required=True,
        type=Path,
        help="campaign directory; repeat once per pilot repeat",
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = phase0_summary(
        args.campaign,
        bootstrap_iterations=args.bootstrap_iterations,
        bootstrap_seed=args.bootstrap_seed,
    )
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    markdown = render_phase0_markdown(summary)
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
