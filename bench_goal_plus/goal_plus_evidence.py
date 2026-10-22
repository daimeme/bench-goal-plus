"""Read Goal Plus execution identities and summarize native worker evidence."""

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def summarize_worker_concurrency(
    intervals: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize persisted worker intervals for campaign evidence."""
    normalized: list[dict[str, str]] = []
    invalid_interval_count = 0
    events: list[tuple[datetime, int]] = []
    candidate_ids: set[str] = set()
    for interval in intervals:
        candidate_id = interval.get("candidate_id")
        started_at = interval.get("started_at")
        ended_at = interval.get("ended_at")
        started = _parse_timestamp(started_at)
        ended = _parse_timestamp(ended_at)
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or started is None
            or ended is None
            or ended <= started
        ):
            invalid_interval_count += 1
            continue
        normalized.append(
            {"candidate_id": candidate_id, "started_at": str(started_at),
             "ended_at": str(ended_at)}
        )
        candidate_ids.add(candidate_id)
        events.extend(((started, 1), (ended, -1)))
    live_workers = 0
    max_live_workers = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        live_workers += delta
        max_live_workers = max(max_live_workers, live_workers)
    return {
        "interval_count": len(normalized),
        "invalid_interval_count": invalid_interval_count,
        "candidate_ids": sorted(candidate_ids),
        "max_live_workers": max_live_workers if normalized else None,
        "intervals": normalized,
    }


def overlapping_bound_candidates(
    intervals: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Candidates whose persisted worker intervals overlap in wall time."""
    events_by_candidate: dict[str, list[tuple[datetime, int]]] = {}
    for interval in intervals:
        candidate_id = interval.get("candidate_id")
        started = _parse_timestamp(interval.get("started_at"))
        ended = _parse_timestamp(interval.get("ended_at"))
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or started is None
            or ended is None
            or ended <= started
        ):
            continue
        events_by_candidate.setdefault(candidate_id, []).extend(
            ((started, 1), (ended, -1))
        )
    overlapping: list[str] = []
    for candidate_id, events in events_by_candidate.items():
        live_workers = 0
        for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
            live_workers += delta
            if live_workers > 1:
                overlapping.append(candidate_id)
                break
    return sorted(overlapping)


def session_agent_harness(session: Mapping[str, Any]) -> Literal["codex", "pi"] | None:
    handle = session.get("session_handle")
    harness = session.get("agent_harness")
    if (
        harness not in ("codex", "pi")
        or session.get("runtime_provider") != "direct"
        or not isinstance(handle, Mapping)
        or handle.get("agent_harness") != harness
        or handle.get("runtime_provider") != "direct"
        or not isinstance(handle.get("external_id"), str)
        or not handle["external_id"]
        or any(key in session for key in ("host", "host_handle"))
        or "host" in handle
    ):
        return None
    return harness


def _session_worker_intervals_from_dispatches(
    session: Mapping[str, Any],
    *,
    harness: Literal["codex", "pi"],
    handle: Mapping[str, Any],
    dispatches: list[Any],
) -> list[dict[str, Any]]:
    receipts: dict[str, Mapping[str, Any]] = {}
    for receipt in dispatches:
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("agent_harness") != harness
            or receipt.get("runtime_provider") != "direct"
            or receipt.get("native_session_id") != handle["external_id"]
            or not isinstance(receipt.get("invocation_id"), str)
            or not receipt["invocation_id"]
        ):
            return []
        invocation = receipt["invocation_id"]
        if invocation in receipts and receipts[invocation] != receipt:
            return []
        receipts[invocation] = receipt
    return [
        {
            "run_id": session.get("run_id"),
            "candidate_id": session.get("candidate_id"),
            "agent_session_id": session.get("agent_session_id"),
            "execution_generation": session.get("execution_generation", 0),
            "invocation_id": invocation,
            "started_at": receipt.get("started_at"),
            "ended_at": receipt.get("ended_at"),
        }
        for invocation, receipt in receipts.items()
    ]


def _session_binding_invocation_id(session: Mapping[str, Any]) -> str | None:
    run_requests = session.get("run_requests")
    if isinstance(run_requests, list):
        for request in run_requests:
            if (
                isinstance(request, Mapping)
                and isinstance(request.get("call_id"), str)
                and request["call_id"]
            ):
                return request["call_id"]
    agent_session_id = session.get("agent_session_id")
    if isinstance(agent_session_id, str) and agent_session_id:
        return agent_session_id
    return None


def _session_worker_intervals_from_binding(
    session: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Accept Goal Plus native-rpc sessions that bound workers but omitted dispatches."""
    candidate_id = session.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        return []
    bound_at = metadata.get("bound_at")
    if not isinstance(bound_at, str) or not bound_at:
        return []
    started_at = bound_at
    ended_at = session.get("updated_at")
    if not isinstance(ended_at, str) or not ended_at:
        return []
    started = _parse_timestamp(started_at)
    ended = _parse_timestamp(ended_at)
    if started is None or ended is None:
        return []
    if ended <= started:
        created_at = session.get("created_at")
        if isinstance(created_at, str) and created_at:
            started_at = created_at
            started = _parse_timestamp(started_at)
        if started is None or ended <= started:
            return []
    invocation_id = _session_binding_invocation_id(session)
    if invocation_id is None:
        return []
    return [{
        "run_id": session.get("run_id"),
        "candidate_id": candidate_id,
        "agent_session_id": session.get("agent_session_id"),
        "execution_generation": session.get("execution_generation", 0),
        "invocation_id": invocation_id,
        "started_at": started_at,
        "ended_at": ended_at,
    }]


def session_worker_intervals(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use native invocation receipts; allocation and resource release are not execution."""
    harness = session_agent_harness(session)
    if harness is None:
        return []
    handle = session["session_handle"]
    metadata = handle.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    dispatches = metadata.get("dispatches")
    if isinstance(dispatches, list) and dispatches:
        return _session_worker_intervals_from_dispatches(
            session,
            harness=harness,
            handle=handle,
            dispatches=dispatches,
        )
    return _session_worker_intervals_from_binding(session, metadata=metadata)


def frozen_agent_harness(frozen: Mapping[str, Any]) -> Literal["codex", "pi"] | None:
    spec = frozen.get("spec")
    workspace = spec.get("workspace") if isinstance(spec, Mapping) else None
    if not isinstance(workspace, Mapping) or workspace.get("provider") not in (
        "git_worktree", "copy",
    ):
        return None
    if frozen.get("runtime_provider") != "direct":
        return None
    if any(key in frozen for key in ("native_host", "worker_host")) or "backend" in workspace:
        return None
    agent_harness = frozen.get("agent_harness")
    if agent_harness in ("codex", "pi"):
        return agent_harness
    return None


SAT_TEXT_SCORE_KEYS = (
    "claim_specificity",
    "evidence_grounding",
    "causal_coherence",
    "repair_actionability",
    "uncertainty_calibration",
)
SAT_DIAGNOSTIC_SCORE_KEYS = (
    "correctness_gap",
    "validation_gap",
    "local_confounder_evidence",
    "discriminating_test_gap",
    "boundary_evidence_strength",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def collaboration_snapshot(run_dir: Path) -> dict[str, Any]:
    """Read the SAT-GP collaboration ledger without importing goal_plus.

    The runtime writes append-only events under
    ``.gp/runs/<run_id>/collaboration/`` and one JSON certificate per
    candidate phase.  Keeping this reader schema-only lets old runtimes and
    non-SAT arms report an explicit empty ledger instead of failing.
    """

    root = run_dir / "collaboration"
    events = _read_jsonl(root / "events.jsonl")
    certificates = [
        payload
        for path in sorted((root / "certificates").glob("*/*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    event_counts = Counter(str(item.get("kind") or "unknown") for item in events)
    phase_counts = Counter(str(item.get("phase") or "unknown") for item in events)
    claim_statuses: Counter[str] = Counter()
    claims_total = 0
    peer_audits_total = 0
    for certificate in certificates:
        claims = certificate.get("claims")
        if isinstance(claims, list):
            claims_total += len(claims)
            claim_statuses.update(
                str(claim.get("status"))
                for claim in claims
                if isinstance(claim, Mapping) and claim.get("status")
            )
        audits = certificate.get("peer_audits")
        if isinstance(audits, list):
            peer_audits_total += len(audits)
    status = "present" if events or certificates else "absent"
    return {
        "status": status,
        "protocol": next(
            (
                item.get("protocol")
                for item in certificates
                if isinstance(item.get("protocol"), str)
            ),
            "sat-gp/v2",
        ),
        "events_total": len(events),
        "event_counts": dict(sorted(event_counts.items())),
        "phase_event_counts": dict(sorted(phase_counts.items())),
        "phase_transitions": [
            {
                "phase": item.get("phase"),
                "kind": item.get("kind"),
                "at": item.get("at"),
            }
            for item in events
            if item.get("kind") in {"phase_started", "phase_completed"}
        ],
        "certificates_total": len(certificates),
        "claims_total": claims_total,
        "claim_status_counts": dict(sorted(claim_statuses.items())),
        "peer_audits_total": peer_audits_total,
        "evidence_reads_total": event_counts.get("evidence_read", 0),
    }


def steering_snapshot(run_dir: Path) -> dict[str, Any]:
    """Summarize SAT verifier/steering artifacts for one Search run."""

    attempts = [
        payload
        for path in sorted((run_dir / "steering-attempts").glob("*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    diagnostics = [
        payload
        for path in sorted((run_dir / "steering-diagnostics").glob("*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    delivery_modes = Counter(
        str((item.get("delivery") or {}).get("mode") or "unknown")
        for item in attempts
    )
    observations = Counter(str(item.get("observation") or "unknown") for item in attempts)
    actions = Counter(
        str(item.get("action") or "no_supported_action") for item in attempts
    )
    diagnostic_actions: Counter[str] = Counter()
    diagnostic_modes: Counter[str] = Counter()
    for item in diagnostics:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        diagnostic_actions.update([str(result.get("action") or "no_op")])
        diagnostic_modes.update([str(item.get("mode") or "unknown")])
    return {
        "steering_attempts": len(attempts),
        "steering_shadow_evaluations": diagnostic_modes.get("shadow", 0),
        "steering_apply_evaluations": diagnostic_modes.get("apply", 0),
        "steering_delivery_modes": dict(sorted(delivery_modes.items())),
        "steering_observations": dict(sorted(observations.items())),
        "steering_actions": dict(sorted(actions.items())),
        "steering_diagnostics": len(diagnostics),
        "steering_diagnostic_actions": dict(sorted(diagnostic_actions.items())),
        "steering_diagnostic_modes": dict(sorted(diagnostic_modes.items())),
        "steering_applied": sum(
            1
            for item in attempts
            if item.get("observation") == "returned"
            and (item.get("delivery") or {}).get("mode") == "apply"
        ),
        "steering_not_delivered": sum(
            1
            for item in attempts
            if item.get("observation") in {"not_sent", "unknown"}
        ),
    }


def global_evidence_reads(run_dir: Path) -> dict[str, Any]:
    """Count persisted Global Evidence read receipts and their readers."""

    reads: list[dict[str, Any]] = []
    candidates: set[str] = set()
    for path in sorted((run_dir / "agent_sessions").glob("agent_*.json")):
        session = _read_json(path)
        records = session.get("global_evidence_reads")
        if not isinstance(records, list) or not records:
            continue
        reads.extend(item for item in records if isinstance(item, dict))
        candidate_id = session.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id:
            candidates.add(candidate_id)
    sources = Counter(str(item.get("source") or "unknown") for item in reads)
    peer_reads = sum(
        1
        for item in reads
        if isinstance(item.get("completed_view_count"), int)
        and item["completed_view_count"] > 1
    )
    return {
        "global_evidence_reads": len(reads),
        "global_evidence_peer_reads": peer_reads,
        "global_evidence_read_sources": dict(sorted(sources.items())),
        "global_evidence_reader_candidates": sorted(candidates),
        "global_evidence_reader_candidate_count": len(candidates),
    }


def shared_cache_snapshot(run_dir: Path) -> dict[str, Any]:
    """Summarize the shared-cache fact log for the A2 sharing arm."""

    records = [
        payload
        for path in sorted((run_dir / "shared-cache").glob("*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    sections = Counter(str(item.get("section") or "unknown") for item in records)
    writers = Counter(str(item.get("writer") or "unknown") for item in records)
    candidate_writers = {
        str(item.get("writer")).partition(":")[2]
        for item in records
        if str(item.get("writer") or "").startswith("candidate:")
        and str(item.get("writer")).partition(":")[2]
    }
    return {
        "shared_cache_records": len(records),
        "shared_cache_sections": dict(sorted(sections.items())),
        "shared_cache_writers": dict(sorted(writers.items())),
        "shared_cache_candidate_writers": sorted(candidate_writers),
        "shared_cache_candidate_writer_count": len(candidate_writers),
        "shared_cache_supersedes": sum(
            1 for item in records if item.get("supersedes")
        ),
        "shared_cache_with_evidence": sum(
            1 for item in records if item.get("evidence_ref")
        ),
    }


def verifier_snapshot(run_dir: Path) -> dict[str, Any]:
    """Summarize LLM verifier records, including SAT text-description scores."""

    record_paths = sorted(
        (run_dir / "verifier" / "records").glob("record_*.json")
    )
    if not record_paths:
        # Older runs stored terminal outcomes under tasks/; keep the fallback
        # so historical artifacts remain readable.
        record_paths = sorted(
            (run_dir / "verifier" / "tasks").glob("verifier_*.json")
        )
    records = [
        payload
        for path in record_paths
        for payload in [_read_json(path)]
        if payload
    ]
    completed = [item for item in records if item.get("outcome") == "completed"]
    failed = [item for item in records if item.get("outcome") == "failed"]
    score_totals: dict[str, float] = {}
    score_counts: Counter[str] = Counter()
    for item in completed:
        scores = item.get("scores")
        if not isinstance(scores, dict):
            continue
        for key, value in scores.items():
            if isinstance(value, (int, float)):
                score_totals[str(key)] = score_totals.get(str(key), 0.0) + float(value)
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
    return {
        "verifier_records": len(records),
        "verifier_completed": len(completed),
        "verifier_failed": len(failed),
        "verifier_scored_records": sum(1 for item in completed if item.get("scores")),
        "verifier_text_score_means": text_means,
        "verifier_diagnostic_score_means": diagnostic_means,
        "verifier_with_diagnostics": sum(
            1 for item in completed if item.get("steering_findings") is not None
        ),
        "verifier_usage_tokens": sum(
            int(sum(
                value
                for key, value in (item.get("usage") or {}).items()
                if key.endswith("tokens")
                and isinstance(value, (int, float))
            ))
            for item in completed
        ),
    }


def audit_snapshot(run_dir: Path) -> dict[str, Any]:
    """Summarize audit briefs and repair credentials without importing Goal Plus."""

    briefs = [
        payload
        for path in sorted((run_dir / "audit" / "briefs").glob("*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    credentials = [
        payload
        for path in sorted((run_dir / "audit" / "credentials").glob("*.json"))
        for payload in [_read_json(path)]
        if payload
    ]
    statuses = Counter(str(item.get("status") or "unknown") for item in briefs)
    credential_statuses = Counter(
        str(item.get("status") or "unknown") for item in credentials
    )
    defect_kinds: Counter[str] = Counter()
    for brief in briefs:
        defects = brief.get("defects")
        if isinstance(defects, list):
            defect_kinds.update(
                str(defect.get("kind") or "unknown")
                for defect in defects
                if isinstance(defect, Mapping)
            )
    delivered_statuses = {"delivered", "accepted", "ignored", "rebutted"}
    delivered = sum(statuses[status] for status in delivered_statuses)
    accepted = statuses.get("accepted", 0)
    total = len(briefs)
    credential_total = len(credentials)
    return {
        "status": "present" if briefs or credentials else "absent",
        "briefs_total": total,
        "briefs_pending": statuses.get("pending", 0),
        "briefs_delivered": delivered,
        "briefs_accepted": accepted,
        "briefs_ignored": statuses.get("ignored", 0),
        "briefs_rebutted": statuses.get("rebutted", 0),
        "briefs_superseded": statuses.get("superseded", 0),
        "briefs_expired": statuses.get("expired", 0),
        "brief_status_counts": dict(sorted(statuses.items())),
        "defects_total": sum(defect_kinds.values()),
        "defect_kinds": dict(sorted(defect_kinds.items())),
        "credentials_total": credential_total,
        "credentials_queued": credential_statuses.get("queued", 0),
        "credentials_verified": credential_statuses.get("verified", 0),
        "credentials_rejected": credential_statuses.get("rejected", 0),
        "credential_status_counts": dict(sorted(credential_statuses.items())),
        "audit_delivery_rate": delivered / total if total else None,
        "audit_acceptance_rate": accepted / delivered if delivered else None,
        "audit_verified_rate": (
            credential_statuses.get("verified", 0) / credential_total
            if credential_total
            else None
        ),
    }


def sat_metrics(run_dir: Path) -> dict[str, Any]:
    """Return the SAT mechanism evidence attached to one Goal Plus run."""

    return {
        "verifier": verifier_snapshot(run_dir),
        "steering": steering_snapshot(run_dir),
        "evidence": global_evidence_reads(run_dir),
        "shared_cache": shared_cache_snapshot(run_dir),
        "collaboration": collaboration_snapshot(run_dir),
        "audit": audit_snapshot(run_dir),
    }


SAT_METRIC_FIELDS = (
    "verifier_records",
    "verifier_completed",
    "verifier_failed",
    "verifier_scored_records",
    "verifier_with_diagnostics",
    "steering_attempts",
    "steering_shadow_evaluations",
    "steering_apply_evaluations",
    "steering_diagnostics",
    "steering_applied",
    "steering_not_delivered",
    "global_evidence_reads",
    "global_evidence_peer_reads",
    "global_evidence_reader_candidate_count",
    "shared_cache_records",
    "shared_cache_candidate_writer_count",
    "shared_cache_supersedes",
    "shared_cache_with_evidence",
    "collaboration_events",
    "collaboration_certificates",
    "collaboration_claims",
    "collaboration_peer_audits",
    "collaboration_evidence_reads",
    "audit_briefs",
    "audit_briefs_pending",
    "audit_briefs_delivered",
    "audit_briefs_accepted",
    "audit_briefs_ignored",
    "audit_briefs_rebutted",
    "audit_credentials",
    "audit_credentials_verified",
    "audit_credentials_rejected",
    "audit_defects",
)


def _mean_known(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_sat_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run SAT mechanism evidence for one cell or arm."""

    if not items:
        return {
            "metrics": {field: 0 for field in SAT_METRIC_FIELDS},
            "runs_with_sat": 0,
            "collaboration_status": "absent",
            "audit_status": "absent",
            "audit_defect_kinds": {},
            "audit_delivery_rate": None,
            "audit_acceptance_rate": None,
            "audit_verified_rate": None,
            "text_score_means": {},
            "diagnostic_score_means": {},
            "steering_actions": {},
            "steering_observations": {},
            "steering_diagnostic_actions": {},
        }

    metrics = {field: 0 for field in SAT_METRIC_FIELDS}
    text_scores: dict[str, list[float]] = {}
    diagnostic_scores: dict[str, list[float]] = {}
    actions: dict[str, int] = {}
    observations: dict[str, int] = {}
    diagnostic_actions: dict[str, int] = {}
    collaboration_status = "absent"
    audit_status = "absent"
    audit_defect_kinds: dict[str, int] = {}
    for item in items:
        verifier = item.get("verifier") or {}
        steering = item.get("steering") or {}
        evidence = item.get("evidence") or {}
        shared_cache = item.get("shared_cache") or {}
        collaboration = item.get("collaboration") or {}
        audit = item.get("audit") or {}
        metrics["verifier_records"] += int(verifier.get("verifier_records") or 0)
        metrics["verifier_completed"] += int(verifier.get("verifier_completed") or 0)
        metrics["verifier_failed"] += int(verifier.get("verifier_failed") or 0)
        metrics["verifier_scored_records"] += int(
            verifier.get("verifier_scored_records") or 0
        )
        metrics["verifier_with_diagnostics"] += int(
            verifier.get("verifier_with_diagnostics") or 0
        )
        metrics["steering_attempts"] += int(steering.get("steering_attempts") or 0)
        metrics["steering_shadow_evaluations"] += int(
            steering.get("steering_shadow_evaluations") or 0
        )
        metrics["steering_apply_evaluations"] += int(
            steering.get("steering_apply_evaluations") or 0
        )
        metrics["steering_diagnostics"] += int(
            steering.get("steering_diagnostics") or 0
        )
        metrics["steering_applied"] += int(steering.get("steering_applied") or 0)
        metrics["steering_not_delivered"] += int(
            steering.get("steering_not_delivered") or 0
        )
        metrics["global_evidence_reads"] += int(
            evidence.get("global_evidence_reads") or 0
        )
        metrics["global_evidence_peer_reads"] += int(
            evidence.get("global_evidence_peer_reads") or 0
        )
        metrics["global_evidence_reader_candidate_count"] += int(
            evidence.get("global_evidence_reader_candidate_count") or 0
        )
        metrics["shared_cache_records"] += int(
            shared_cache.get("shared_cache_records") or 0
        )
        metrics["shared_cache_candidate_writer_count"] += int(
            shared_cache.get("shared_cache_candidate_writer_count") or 0
        )
        metrics["shared_cache_supersedes"] += int(
            shared_cache.get("shared_cache_supersedes") or 0
        )
        metrics["shared_cache_with_evidence"] += int(
            shared_cache.get("shared_cache_with_evidence") or 0
        )
        metrics["collaboration_events"] += int(
            collaboration.get("events_total") or 0
        )
        metrics["collaboration_certificates"] += int(
            collaboration.get("certificates_total") or 0
        )
        metrics["collaboration_claims"] += int(
            collaboration.get("claims_total") or 0
        )
        metrics["collaboration_peer_audits"] += int(
            collaboration.get("peer_audits_total") or 0
        )
        metrics["collaboration_evidence_reads"] += int(
            collaboration.get("evidence_reads_total") or 0
        )
        if collaboration.get("status") == "present":
            collaboration_status = "present"
        metrics["audit_briefs"] += int(audit.get("briefs_total") or 0)
        metrics["audit_briefs_pending"] += int(audit.get("briefs_pending") or 0)
        metrics["audit_briefs_delivered"] += int(audit.get("briefs_delivered") or 0)
        metrics["audit_briefs_accepted"] += int(audit.get("briefs_accepted") or 0)
        metrics["audit_briefs_ignored"] += int(audit.get("briefs_ignored") or 0)
        metrics["audit_briefs_rebutted"] += int(audit.get("briefs_rebutted") or 0)
        metrics["audit_credentials"] += int(audit.get("credentials_total") or 0)
        metrics["audit_credentials_verified"] += int(
            audit.get("credentials_verified") or 0
        )
        metrics["audit_credentials_rejected"] += int(
            audit.get("credentials_rejected") or 0
        )
        metrics["audit_defects"] += int(audit.get("defects_total") or 0)
        if audit.get("status") == "present":
            audit_status = "present"
        for kind, count in (audit.get("defect_kinds") or {}).items():
            audit_defect_kinds[str(kind)] = (
                audit_defect_kinds.get(str(kind), 0) + int(count)
            )
        for key, value in (verifier.get("verifier_text_score_means") or {}).items():
            if isinstance(value, (int, float)):
                text_scores.setdefault(str(key), []).append(float(value))
        for key, value in (
            verifier.get("verifier_diagnostic_score_means") or {}
        ).items():
            if isinstance(value, (int, float)):
                diagnostic_scores.setdefault(str(key), []).append(float(value))
        for key, value in (steering.get("steering_actions") or {}).items():
            actions[str(key)] = actions.get(str(key), 0) + int(value)
        for key, value in (steering.get("steering_observations") or {}).items():
            observations[str(key)] = observations.get(str(key), 0) + int(value)
        for key, value in (
            steering.get("steering_diagnostic_actions") or {}
        ).items():
            diagnostic_actions[str(key)] = diagnostic_actions.get(str(key), 0) + int(value)
    audit_total = metrics["audit_briefs"]
    audit_delivered = metrics["audit_briefs_delivered"]
    audit_credentials = metrics["audit_credentials"]
    return {
        "metrics": metrics,
        "runs_with_sat": len(items),
        "collaboration_status": collaboration_status,
        "audit_status": audit_status,
        "audit_defect_kinds": dict(sorted(audit_defect_kinds.items())),
        "audit_delivery_rate": (
            audit_delivered / audit_total if audit_total else None
        ),
        "audit_acceptance_rate": (
            metrics["audit_briefs_accepted"] / audit_delivered
            if audit_delivered
            else None
        ),
        "audit_verified_rate": (
            metrics["audit_credentials_verified"] / audit_credentials
            if audit_credentials
            else None
        ),
        "text_score_means": {
            key: round(_mean_known(values) or 0.0, 6)
            for key, values in sorted(text_scores.items())
        },
        "diagnostic_score_means": {
            key: round(_mean_known(values) or 0.0, 6)
            for key, values in sorted(diagnostic_scores.items())
        },
        "steering_actions": dict(sorted(actions.items())),
        "steering_observations": dict(sorted(observations.items())),
        "steering_diagnostic_actions": dict(sorted(diagnostic_actions.items())),
    }


def merge_sat_aggregates(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge already-aggregated SAT summaries for a condition or arm."""

    known = [item for item in items if isinstance(item, dict) and "metrics" in item]
    if not known:
        return aggregate_sat_metrics([])
    metrics = {field: 0 for field in SAT_METRIC_FIELDS}
    text_scores: dict[str, list[float]] = {}
    diagnostic_scores: dict[str, list[float]] = {}
    actions: dict[str, int] = {}
    observations: dict[str, int] = {}
    diagnostic_actions: dict[str, int] = {}
    collaboration_status = "absent"
    audit_status = "absent"
    audit_defect_kinds: dict[str, int] = {}
    for item in known:
        for key, value in (item.get("metrics") or {}).items():
            if key in metrics:
                metrics[key] += int(value or 0)
        if item.get("collaboration_status") == "present":
            collaboration_status = "present"
        if item.get("audit_status") == "present":
            audit_status = "present"
        for kind, count in (item.get("audit_defect_kinds") or {}).items():
            audit_defect_kinds[str(kind)] = (
                audit_defect_kinds.get(str(kind), 0) + int(count)
            )
        for key, value in (item.get("text_score_means") or {}).items():
            if isinstance(value, (int, float)):
                text_scores.setdefault(str(key), []).append(float(value))
        for key, value in (item.get("diagnostic_score_means") or {}).items():
            if isinstance(value, (int, float)):
                diagnostic_scores.setdefault(str(key), []).append(float(value))
        for key, value in (item.get("steering_actions") or {}).items():
            actions[str(key)] = actions.get(str(key), 0) + int(value)
        for key, value in (item.get("steering_observations") or {}).items():
            observations[str(key)] = observations.get(str(key), 0) + int(value)
        for key, value in (item.get("steering_diagnostic_actions") or {}).items():
            diagnostic_actions[str(key)] = diagnostic_actions.get(str(key), 0) + int(value)
    audit_total = metrics["audit_briefs"]
    audit_delivered = metrics["audit_briefs_delivered"]
    audit_credentials = metrics["audit_credentials"]
    return {
        "metrics": metrics,
        "runs_with_sat": sum(int(item.get("runs_with_sat") or 0) for item in known),
        "collaboration_status": collaboration_status,
        "audit_status": audit_status,
        "audit_defect_kinds": dict(sorted(audit_defect_kinds.items())),
        "audit_delivery_rate": (
            audit_delivered / audit_total if audit_total else None
        ),
        "audit_acceptance_rate": (
            metrics["audit_briefs_accepted"] / audit_delivered
            if audit_delivered
            else None
        ),
        "audit_verified_rate": (
            metrics["audit_credentials_verified"] / audit_credentials
            if audit_credentials
            else None
        ),
        "text_score_means": {
            key: round(_mean_known(values) or 0.0, 6)
            for key, values in sorted(text_scores.items())
        },
        "diagnostic_score_means": {
            key: round(_mean_known(values) or 0.0, 6)
            for key, values in sorted(diagnostic_scores.items())
        },
        "steering_actions": dict(sorted(actions.items())),
        "steering_observations": dict(sorted(observations.items())),
        "steering_diagnostic_actions": dict(sorted(diagnostic_actions.items())),
    }
