#!/usr/bin/env python3
"""Export Goal Plus verifier claims and score human labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.sat_audit import (  # noqa: E402
    audit_from_files,
    export_cell_claims,
    export_claims,
    write_labels_template,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export", help="export claims as JSONL")
    target = export.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--run-dir",
        type=Path,
        help="Goal Plus run directory containing verifier/tasks",
    )
    target.add_argument(
        "--cell-dir",
        type=Path,
        help="campaign cell directory; discovers workspace/.gp/runs/*",
    )
    export.add_argument("--output", required=True, type=Path)
    export.add_argument(
        "--labels-template",
        type=Path,
        help="optional JSONL template with every claim set to unknown",
    )

    score = subparsers.add_parser("score", help="score a labeled claims file")
    score.add_argument("--claims", required=True, type=Path)
    score.add_argument("--labels", required=True, type=Path)
    score.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "export":
        if args.cell_dir:
            count = export_cell_claims(args.cell_dir, args.output)
        else:
            count = export_claims(args.run_dir, args.output)
        if args.labels_template:
            write_labels_template(args.output, args.labels_template)
        print(json.dumps({"claims": count, "output": str(args.output)}, indent=2))
        return 0
    result = audit_from_files(args.claims, args.labels)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        output = args.output.expanduser().absolute()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
