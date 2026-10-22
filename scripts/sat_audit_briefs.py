#!/usr/bin/env python3
"""Export and summarize Goal Plus audit briefs and repair credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.sat_audit import (  # noqa: E402
    audit_brief_rows,
    audit_brief_summary,
    export_audit_briefs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser(
        "export", help="export audit brief/credential rows as JSONL"
    )
    target = export.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-dir", type=Path)
    target.add_argument("--cell-dir", type=Path)
    export.add_argument("--output", required=True, type=Path)

    summary = subparsers.add_parser("summary", help="print audit counts/rates")
    target = summary.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-dir", type=Path)
    target.add_argument("--cell-dir", type=Path)
    summary.add_argument("--output", type=Path)
    return parser


def _cell_summary(cell_dir: Path) -> dict:
    run_root = cell_dir.expanduser().absolute() / "workspace" / ".gp" / "runs"
    runs = [audit_brief_summary(run_dir) for run_dir in sorted(run_root.glob("run_*"))]
    briefs = sum(int(item.get("briefs_total") or 0) for item in runs)
    delivered = sum(int(item.get("briefs_delivered") or 0) for item in runs)
    accepted = sum(int(item.get("briefs_accepted") or 0) for item in runs)
    credentials = sum(int(item.get("credentials_total") or 0) for item in runs)
    verified = sum(int(item.get("credentials_verified") or 0) for item in runs)
    return {
        "runs": len(runs),
        "briefs_total": briefs,
        "briefs_delivered": delivered,
        "briefs_accepted": accepted,
        "credentials_total": credentials,
        "credentials_verified": verified,
        "audit_delivery_rate": delivered / briefs if briefs else None,
        "audit_acceptance_rate": accepted / delivered if delivered else None,
        "audit_verified_rate": verified / credentials if credentials else None,
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "export":
        if args.cell_dir:
            count = export_audit_briefs(args.cell_dir, args.output)
        else:
            rows = audit_brief_rows(args.run_dir)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False, sort_keys=True)
                    for row in rows
                )
                + ("\n" if rows else ""),
                encoding="utf-8",
            )
            count = len(rows)
        print(json.dumps({"rows": count, "output": str(args.output)}))
        return 0
    summary = (
        _cell_summary(args.cell_dir)
        if args.cell_dir
        else audit_brief_summary(args.run_dir)
    )
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
