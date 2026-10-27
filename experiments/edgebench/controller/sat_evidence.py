"""Read SAT-GP mechanism evidence from an EdgeBench Goal Plus state archive."""

from __future__ import annotations

import json
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any

from bench_goal_plus.goal_plus_evidence import (
    SAT_DIAGNOSTIC_SCORE_KEYS,
    SAT_TEXT_SCORE_KEYS,
)


def _json(payload: bytes | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        value = json.loads(payload.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _jsonl(payload: bytes | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    rows = []
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def sat_metrics_from_archive(archive_path: Path) -> dict[str, Any]:
    """Summarize verifier/steering/cache/evidence/collaboration artifacts."""

    if not archive_path.is_file():
        return {"available": False, "reason": "goal-plus-state.tar absent"}
    verifier_records = 0
    verifier_completed = 0
    verifier_failed = 0
    verifier_with_diagnostics = 0
    verifier_usage_tokens = 0
    score_totals: dict[str, float] = {}
    score_counts: Counter[str] = Counter()
    steering_attempts = 0
    steering_shadow = 0
    steering_apply = 0
    steering_applied = 0
    steering_not_delivered = 0
    steering_diagnostics = 0
    shared_cache_records = 0
    shared_cache_writers: set[str] = set()
    shared_cache_supersedes = 0
    shared_cache_with_evidence = 0
    global_evidence_reads = 0
    global_evidence_peer_reads = 0
    evidence_reader_candidates: set[str] = set()
    collaboration_events: list[dict[str, Any]] = []
    collaboration_certificates = 0
    collaboration_claims = 0
    collaboration_claim_statuses: Counter[str] = Counter()
    collaboration_peer_audits = 0
    deliberation_turn_payloads: list[dict[str, Any]] = []
    deliberation_verdict_payloads: list[dict[str, Any]] = []
    audit_briefs = 0
    audit_brief_statuses: Counter[str] = Counter()
    audit_defect_kinds: Counter[str] = Counter()
    audit_credentials = 0
    audit_credential_statuses: Counter[str] = Counter()
    verifier_task_payloads: list[dict[str, Any]] = []
    verifier_record_payloads: list[dict[str, Any]] = []
    try:
        with tarfile.open(archive_path) as archive:
            for member in archive:
                if not member.isfile() or member.size <= 0:
                    continue
                name = member.name
                relevant = (
                    ("/verifier/tasks/" in name and name.endswith(".json"))
                    or ("/verifier/records/" in name and name.endswith(".json"))
                    or ("/steering-attempts/" in name and name.endswith(".json"))
                    or ("/steering-diagnostics/" in name and name.endswith(".json"))
                    or ("/shared-cache/" in name and name.endswith(".json"))
                    or ("/agent_sessions/" in name and name.endswith(".json"))
                    or name.endswith("/collaboration/events.jsonl")
                    or (
                        "/collaboration/certificates/" in name
                        and name.endswith(".json")
                    )
                    or name.endswith("/collaboration/turns.jsonl")
                    or (
                        "/collaboration/verdicts/" in name
                        and name.endswith(".json")
                    )
                    or ("/audit/briefs/" in name and name.endswith(".json"))
                    or ("/audit/credentials/" in name and name.endswith(".json"))
                )
                if not relevant:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                payload = extracted.read()
                if "/verifier/records/" in name and name.endswith(".json"):
                    record = _json(payload)
                    if record:
                        verifier_record_payloads.append(record)
                elif "/verifier/tasks/" in name and name.endswith(".json"):
                    record = _json(payload)
                    if record:
                        verifier_task_payloads.append(record)
                elif "/steering-attempts/" in name and name.endswith(".json"):
                    attempt = _json(payload)
                    if not attempt:
                        continue
                    steering_attempts += 1
                    observation = attempt.get("observation")
                    mode = (attempt.get("delivery") or {}).get("mode")
                    if observation == "returned" and mode == "apply":
                        steering_applied += 1
                    if observation in {"not_sent", "unknown"}:
                        steering_not_delivered += 1
                elif "/steering-diagnostics/" in name and name.endswith(".json"):
                    diagnostic = _json(payload)
                    if not diagnostic:
                        continue
                    steering_diagnostics += 1
                    mode = diagnostic.get("mode")
                    if mode == "shadow":
                        steering_shadow += 1
                    elif mode == "apply":
                        steering_apply += 1
                elif "/shared-cache/" in name and name.endswith(".json"):
                    record = _json(payload)
                    if not record:
                        continue
                    shared_cache_records += 1
                    writer = str(record.get("writer") or "")
                    if writer.startswith("candidate:") and writer.partition(":")[2]:
                        shared_cache_writers.add(writer.partition(":")[2])
                    if record.get("supersedes"):
                        shared_cache_supersedes += 1
                    if record.get("evidence_ref"):
                        shared_cache_with_evidence += 1
                elif "/agent_sessions/" in name and name.endswith(".json"):
                    session = _json(payload)
                    reads = session.get("global_evidence_reads")
                    if not isinstance(reads, list):
                        continue
                    global_evidence_reads += len(reads)
                    global_evidence_peer_reads += sum(
                        1
                        for item in reads
                        if isinstance(item, dict)
                        and isinstance(item.get("completed_view_count"), int)
                        and item["completed_view_count"] > 1
                    )
                    candidate_id = session.get("candidate_id")
                    if isinstance(candidate_id, str) and candidate_id and reads:
                        evidence_reader_candidates.add(candidate_id)
                elif name.endswith("/collaboration/events.jsonl"):
                    collaboration_events.extend(_jsonl(payload))
                elif "/collaboration/certificates/" in name and name.endswith(
                    ".json"
                ):
                    certificate = _json(payload)
                    if not certificate:
                        continue
                    collaboration_certificates += 1
                    claims = certificate.get("claims")
                    if isinstance(claims, list):
                        collaboration_claims += len(claims)
                        collaboration_claim_statuses.update(
                            str(claim.get("status"))
                            for claim in claims
                            if isinstance(claim, dict) and claim.get("status")
                        )
                    audits = certificate.get("peer_audits")
                    if isinstance(audits, list):
                        collaboration_peer_audits += len(audits)
                elif name.endswith("/collaboration/turns.jsonl"):
                    deliberation_turn_payloads.extend(_jsonl(payload))
                elif "/collaboration/verdicts/" in name and name.endswith(".json"):
                    verdict = _json(payload)
                    if verdict:
                        deliberation_verdict_payloads.append(verdict)
                elif "/audit/briefs/" in name and name.endswith(".json"):
                    brief = _json(payload)
                    if not brief:
                        continue
                    audit_briefs += 1
                    audit_brief_statuses.update(
                        [str(brief.get("status") or "unknown")]
                    )
                    defects = brief.get("defects")
                    if isinstance(defects, list):
                        audit_defect_kinds.update(
                            str(defect.get("kind") or "unknown")
                            for defect in defects
                            if isinstance(defect, dict)
                        )
                elif "/audit/credentials/" in name and name.endswith(".json"):
                    credential = _json(payload)
                    if not credential:
                        continue
                    audit_credentials += 1
                    audit_credential_statuses.update(
                        [str(credential.get("status") or "unknown")]
                    )
    except (tarfile.TarError, OSError):
        return {"available": False, "reason": "goal-plus-state.tar unreadable"}

    for record in verifier_record_payloads or verifier_task_payloads:
        verifier_records += 1
        outcome = record.get("outcome")
        if outcome == "completed":
            verifier_completed += 1
        elif outcome == "failed":
            verifier_failed += 1
        if record.get("steering_findings") is not None or record.get("audit") is not None:
            verifier_with_diagnostics += 1
        usage = record.get("usage")
        if isinstance(usage, dict):
            verifier_usage_tokens += int(
                sum(
                    value
                    for key, value in usage.items()
                    if key.endswith("tokens")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                )
            )
        scores = record.get("scores")
        if isinstance(scores, dict):
            for key, value in scores.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    score_totals[str(key)] = (
                        score_totals.get(str(key), 0.0) + float(value)
                    )
                    score_counts[str(key)] += 1

    text_means = {
        key: round(score_totals[key] / score_counts[key], 6)
        for key in SAT_TEXT_SCORE_KEYS
        if score_counts.get(key)
    }
    diagnostic_means = {
        key: round(score_totals[key] / score_counts[key], 6)
        for key in SAT_DIAGNOSTIC_SCORE_KEYS
        if score_counts.get(key)
    }
    deliberation_completed = sum(
        1
        for item in deliberation_verdict_payloads
        if item.get("status") == "completed"
    )
    deliberation_failed = sum(
        1
        for item in deliberation_verdict_payloads
        if item.get("status") == "failed"
    )
    deliberation_turn_findings = sum(
        len(item.get("findings") or [])
        for item in deliberation_turn_payloads
        if isinstance(item.get("findings"), list)
    )
    deliberation_unresolved_risks = sum(
        len(item.get("unresolved_risks") or [])
        for item in deliberation_verdict_payloads
        if isinstance(item.get("unresolved_risks"), list)
    )
    audit_delivered = sum(
        audit_brief_statuses[status]
        for status in {"delivered", "accepted", "ignored", "rebutted"}
    )
    audit_accepted = audit_brief_statuses.get("accepted", 0)
    audit_verified = audit_credential_statuses.get("verified", 0)
    return {
        "available": True,
        "verifier_records": verifier_records,
        "verifier_completed": verifier_completed,
        "verifier_failed": verifier_failed,
        "verifier_with_diagnostics": verifier_with_diagnostics,
        "verifier_usage_tokens": verifier_usage_tokens,
        "verifier_text_score_means": text_means,
        "verifier_diagnostic_score_means": diagnostic_means,
        "steering_attempts": steering_attempts,
        "steering_shadow_evaluations": steering_shadow,
        "steering_apply_evaluations": steering_apply,
        "steering_applied": steering_applied,
        "steering_not_delivered": steering_not_delivered,
        "steering_diagnostics": steering_diagnostics,
        "shared_cache_records": shared_cache_records,
        "shared_cache_candidate_writer_count": len(shared_cache_writers),
        "shared_cache_supersedes": shared_cache_supersedes,
        "shared_cache_with_evidence": shared_cache_with_evidence,
        "global_evidence_reads": global_evidence_reads,
        "global_evidence_peer_reads": global_evidence_peer_reads,
        "global_evidence_reader_candidate_count": len(evidence_reader_candidates),
        "collaboration_status": (
            "present"
            if collaboration_events or collaboration_certificates
            else "absent"
        ),
        "collaboration_events": len(collaboration_events),
        "collaboration_event_counts": dict(
            sorted(Counter(str(item.get("kind") or "unknown") for item in collaboration_events).items())
        ),
        "collaboration_certificates": collaboration_certificates,
        "collaboration_claims": collaboration_claims,
        "collaboration_claim_statuses": dict(
            sorted(collaboration_claim_statuses.items())
        ),
        "collaboration_peer_audits": collaboration_peer_audits,
        "deliberation_status": (
            "present"
            if deliberation_turn_payloads or deliberation_verdict_payloads
            else "absent"
        ),
        "deliberation_turns": len(deliberation_turn_payloads),
        "deliberation_verdicts": len(deliberation_verdict_payloads),
        "deliberation_completed": deliberation_completed,
        "deliberation_failed": deliberation_failed,
        "deliberation_recommendations": deliberation_completed,
        "deliberation_turn_findings": deliberation_turn_findings,
        "deliberation_unresolved_risks": deliberation_unresolved_risks,
        "audit_briefs": audit_briefs,
        "audit_briefs_pending": audit_brief_statuses.get("pending", 0),
        "audit_briefs_delivered": audit_delivered,
        "audit_briefs_accepted": audit_accepted,
        "audit_briefs_ignored": audit_brief_statuses.get("ignored", 0),
        "audit_briefs_rebutted": audit_brief_statuses.get("rebutted", 0),
        "audit_brief_status_counts": dict(sorted(audit_brief_statuses.items())),
        "audit_defects": sum(audit_defect_kinds.values()),
        "audit_defect_kinds": dict(sorted(audit_defect_kinds.items())),
        "audit_credentials": audit_credentials,
        "audit_credentials_verified": audit_verified,
        "audit_credentials_rejected": audit_credential_statuses.get("rejected", 0),
        "audit_credential_status_counts": dict(
            sorted(audit_credential_statuses.items())
        ),
        "audit_delivery_rate": (
            audit_delivered / audit_briefs if audit_briefs else None
        ),
        "audit_acceptance_rate": (
            audit_accepted / audit_delivered if audit_delivered else None
        ),
        "audit_verified_rate": (
            audit_verified / audit_credentials if audit_credentials else None
        ),
    }
