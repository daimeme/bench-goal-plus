"""Verifier-claim export and audit helpers for the SAT-GP Phase 0 pilot.

The Goal Plus verifier already persists ``VerifierRecord`` JSON files.  This
module turns their findings and score rationales into a flat JSONL file that a
human can label, then computes a precision/abstention summary.  Recall needs a
separate ground-truth issue inventory and is intentionally reported as
unavailable until that inventory exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


LABELS = {"correct", "incorrect", "unknown"}
FINDING_KINDS = ("hypothesis", "confounder", "open_question", "boundary")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def iter_verifier_records(run_dir: Path) -> list[dict[str, Any]]:
    root = run_dir / "verifier" / "tasks"
    return [
        payload
        for path in sorted(root.glob("verifier_*.json"))
        for payload in [_read_json(path)]
        if payload
    ]


def _finding_rows(
    record: Mapping[str, Any],
    findings: Mapping[str, Any],
    *,
    candidate_id: str | None,
    iteration: Any,
) -> list[dict[str, Any]]:
    rows = []
    record_id = record.get("record_id")
    for kind in FINDING_KINDS:
        finding = findings.get(kind)
        if not isinstance(finding, Mapping):
            continue
        statement = finding.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            continue
        rows.append(
            {
                "claim_id": f"{record_id}:{kind}",
                "kind": kind,
                "statement": statement,
                "evidence_refs": list(finding.get("evidence_refs") or []),
                "scope_ref": finding.get("scope_ref"),
                "score": None,
                "record_id": record_id,
                "candidate_id": candidate_id,
                "iteration": iteration,
                "created_at": record.get("created_at"),
            }
        )
    return rows


def verifier_claim_rows(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in iter_verifier_records(run_dir):
        subject = record.get("subject") or {}
        candidate_id = subject.get("candidate_id")
        iteration = subject.get("iteration")
        findings = record.get("steering_findings")
        if isinstance(findings, Mapping):
            rows.extend(
                _finding_rows(
                    record,
                    findings,
                    candidate_id=candidate_id,
                    iteration=iteration,
                )
            )
        rationales = record.get("score_rationales")
        scores = record.get("scores")
        if isinstance(rationales, Mapping):
            for key, text in rationales.items():
                if not isinstance(text, str) or not text.strip():
                    continue
                score = (scores or {}).get(key) if isinstance(scores, Mapping) else None
                rows.append(
                    {
                        "claim_id": f"{record.get('record_id')}:score:{key}",
                        "kind": f"score_rationale:{key}",
                        "statement": text,
                        "evidence_refs": list(record.get("evidence_refs") or []),
                        "scope_ref": None,
                        "score": score,
                        "record_id": record.get("record_id"),
                        "candidate_id": candidate_id,
                        "iteration": iteration,
                        "created_at": record.get("created_at"),
                    }
                )
    return rows


def export_claims(run_dir: Path, output: Path) -> int:
    rows = verifier_claim_rows(run_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return len(rows)


def export_cell_claims(cell_dir: Path, output: Path) -> int:
    """Export all verifier claims from one campaign cell's ``.gp`` runs."""

    run_root = cell_dir.expanduser().absolute() / "workspace" / ".gp" / "runs"
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_root.glob("run_*")):
        for row in verifier_claim_rows(run_dir):
            item = dict(row)
            item["run_id"] = run_dir.name
            item["claim_id"] = f"{run_dir.name}:{item.get('claim_id')}"
            rows.append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return len(rows)


def write_labels_template(claims_path: Path, output: Path) -> int:
    """Write an annotator template with every claim set to ``unknown``."""

    rows: list[dict[str, Any]] = []
    if claims_path.is_file():
        for line in claims_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            claim_id = payload.get("claim_id") if isinstance(payload, dict) else None
            if isinstance(claim_id, str) and claim_id:
                rows.append(
                    {
                        "claim_id": claim_id,
                        "label": "unknown",
                        "reviewer": "",
                        "notes": "",
                    }
                )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return len(rows)


def load_labels(path: Path) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return labels
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        claim_id = payload.get("claim_id")
        if isinstance(claim_id, str) and claim_id:
            labels[claim_id] = payload
    return labels


def audit_metrics(
    claims: Iterable[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    claim_rows = [claim for claim in claims if isinstance(claim, Mapping)]
    counts = {"correct": 0, "incorrect": 0, "unknown": 0}
    labeled = 0
    by_kind: dict[str, dict[str, int]] = {}
    for claim in claim_rows:
        claim_id = claim.get("claim_id")
        label_payload = labels.get(claim_id) if isinstance(claim_id, str) else None
        label = str((label_payload or {}).get("label") or "").strip().lower()
        if label not in LABELS:
            continue
        labeled += 1
        counts[label] += 1
        kind = str(claim.get("kind") or "unknown")
        bucket = by_kind.setdefault(
            kind, {"correct": 0, "incorrect": 0, "unknown": 0}
        )
        bucket[label] += 1
    precision_denominator = counts["correct"] + counts["incorrect"]
    precision = (
        counts["correct"] / precision_denominator
        if precision_denominator
        else None
    )
    return {
        "claims_total": len(claim_rows),
        "claims_labeled": labeled,
        "label_coverage": labeled / len(claim_rows) if claim_rows else None,
        "correct": counts["correct"],
        "incorrect": counts["incorrect"],
        "unknown": counts["unknown"],
        "precision": precision,
        "abstention_rate": counts["unknown"] / labeled if labeled else None,
        "by_kind": {
            kind: {
                **bucket,
                "precision": (
                    bucket["correct"] / (bucket["correct"] + bucket["incorrect"])
                    if bucket["correct"] + bucket["incorrect"]
                    else None
                ),
            }
            for kind, bucket in sorted(by_kind.items())
        },
        "recall": "unavailable: provide a ground-truth issue inventory",
    }


def audit_from_files(claims_path: Path, labels_path: Path) -> dict[str, Any]:
    claims = []
    if claims_path.is_file():
        for line in claims_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                claims.append(payload)
    return audit_metrics(claims, load_labels(labels_path))
