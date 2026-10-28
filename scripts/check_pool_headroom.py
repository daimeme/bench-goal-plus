#!/usr/bin/env python3
"""Report whether a finished Goal Plus cell has re-ranking headroom.

The post-settlement audit can only change an answer if at least two candidates
settled a materially different result. This reads the archived Goal Plus state
of one EdgeBench campaign and fails when the pool is degenerate (one improving
candidate, the rest at baseline), which is the failure mode produced by a
broken worker shell sandbox.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path


def _campaigns(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if (path / "comparison.json").is_file())


def _candidate_scores(archive: tarfile.TarFile) -> dict[str, dict[str, object]]:
    scores: dict[str, dict[str, object]] = {}
    for member in archive.getnames():
        if not (member.endswith("/candidate.json") and "/candidates/" in member):
            continue
        payload = archive.extractfile(member)
        if payload is None:
            continue
        record = json.loads(payload.read().decode("utf-8"))
        candidate_id = str(record.get("candidate_id"))
        iterations = record.get("iterations") or []
        values = [
            float(item["score"])
            for item in iterations
            if isinstance(item.get("score"), (int, float))
        ]
        scores[candidate_id] = {
            "iterations": len(iterations),
            "best": min(values) if values else None,
        }
    return scores


def analyse(campaign: Path) -> dict[str, object]:
    tar_path = next(iter(campaign.rglob("goal-plus-state.tar")), None)
    if tar_path is None:
        return {"campaign": campaign.name, "error": "goal-plus-state.tar missing"}
    with tarfile.open(tar_path) as archive:
        scores = _candidate_scores(archive)
    bests = [float(item["best"]) for item in scores.values() if item["best"] is not None]
    if not bests:
        return {"campaign": campaign.name, "error": "no scored candidate iterations"}
    baseline = max(bests)
    improving = sorted(
        (float(item["best"]), candidate_id)
        for candidate_id, item in scores.items()
        if item["best"] is not None and float(item["best"]) < baseline
    )
    top_two = [value for value, _ in improving[:2]]
    gap = None
    if len(top_two) == 2:
        gap = (top_two[1] - top_two[0]) / top_two[0]
    return {
        "campaign": campaign.name,
        "baseline": baseline,
        "candidates": {cid: item for cid, item in sorted(scores.items())},
        "improving_candidates": len(improving),
        "best_two": top_two,
        "relative_gap": gap,
        "headroom": len(improving) >= 2 and gap is not None and gap <= 0.25,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="campaign directory or a parent of campaigns")
    parser.add_argument("--max-gap", type=float, default=0.25, help="max relative gap for the top two")
    args = parser.parse_args(argv)

    targets = [args.path] if (args.path / "comparison.json").is_file() else _campaigns(args.path)
    if not targets:
        print(f"no campaign found under {args.path}", file=sys.stderr)
        return 2

    failed = False
    for campaign in targets:
        report = analyse(campaign)
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        if report.get("headroom") is not True and report.get("error") is None:
            failed = True
        if report.get("relative_gap") is not None and report["relative_gap"] > args.max_gap:
            print(
                f"  -> top-two gap {report['relative_gap']:.2%} exceeds {args.max_gap:.0%}; "
                "re-ranking cannot move the score",
                file=sys.stderr,
            )
    if failed:
        print("FAIL: at least one pool has no re-ranking headroom", file=sys.stderr)
        return 1
    print("OK: every pool has at least two improving candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
