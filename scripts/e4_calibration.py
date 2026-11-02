#!/usr/bin/env python3
"""E4 calibration: score-vs-truth from VerifierRecords and Judge results.

This reads every Goal Plus ``VerifierRecord`` persisted inside a campaign's
``goal-plus-state.tar`` archives and the campaign's official EdgeBench Judge
outcome, then writes one CSV row per settled attempt plus a small calibration
summary.  It does not fabricate ground truth: the "hard_score" column is the
frozen public verifier, the "official_score"/"pass_rate" columns are the hidden
Judge, and any correlation is reported with the sample size so it cannot be
misread as a paired, significance-tested result.

Usage:
    python scripts/e4_calibration.py --campaign runs/edgebench/<campaign-id> \
        [--out calibration.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import tarfile
from pathlib import Path
from typing import Any

DIAGNOSTIC_KEYS = (
    "correctness_gap",
    "validation_gap",
    "local_confounder_evidence",
    "discriminating_test_gap",
    "boundary_evidence_strength",
)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx = ranks(xs)
    ry = ranks(ys)
    n = len(xs)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den_x = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    den_y = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def read_verifier_records(state_tar: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with tarfile.open(state_tar) as tf:
        for member in tf.getmembers():
            if "/verifier/records/" not in member.name:
                continue
            if not member.name.endswith(".json"):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            try:
                records.append(json.loads(handle.read().decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    return sorted(records, key=lambda r: (r.get("queue_sequence") or 0))


def record_rows(records: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        subject = record.get("subject") or {}
        settlement = subject.get("settlement") or {}
        evidence = settlement.get("evidence") or {}
        hard_score = evidence.get("hard_score")
        scores = record.get("scores") or {}
        rows.append(
            {
                "run_id": run_id,
                "candidate_id": settlement.get("candidate_id"),
                "iteration": settlement.get("iteration"),
                "queue_sequence": record.get("queue_sequence"),
                "outcome": record.get("outcome"),
                "hard_score": hard_score,
                "quality_score": record.get("quality_score"),
                **{key: scores.get(key) for key in DIAGNOSTIC_KEYS},
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    campaign = args.campaign
    comparison = campaign / "comparison.json"
    judge = {}
    if comparison.is_file():
        judge = json.loads(comparison.read_text(encoding="utf-8"))

    all_rows: list[dict[str, Any]] = []
    for state_tar in sorted(campaign.rglob("goal-plus-state.tar")):
        run_id = state_tar.parent.name if state_tar.parent.name else "run"
        records = read_verifier_records(state_tar)
        all_rows.extend(record_rows(records, run_id))

    if not all_rows:
        print(f"no VerifierRecords found under {campaign}")
        return 1

    out_path = args.out or (campaign / "e4-calibration.csv")
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_id", "candidate_id", "iteration", "queue_sequence",
                        "outcome", "hard_score", "quality_score", *DIAGNOSTIC_KEYS],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(all_rows)

    completed = [r for r in all_rows if r["outcome"] == "completed"
                 and r["quality_score"] is not None and r["hard_score"] is not None]
    qs = [float(r["quality_score"]) for r in completed]
    hs = [float(r["hard_score"]) for r in completed]
    rho = _spearman(qs, hs)

    print(f"records: {len(all_rows)} (completed={len(completed)})")
    print(f"official edgebench_score: {judge.get('edgebench_score')}")
    print(f"quality_score ~ hard_score Spearman rho: {rho} (n={len(completed)}, "
          "descriptive, not significance-tested)")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
