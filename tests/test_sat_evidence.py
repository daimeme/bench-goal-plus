import json
import shutil
import unittest
from pathlib import Path

from bench_goal_plus.goal_plus_evidence import (
    aggregate_sat_metrics,
    audit_snapshot,
    collaboration_snapshot,
    sat_metrics,
    steering_snapshot,
)
from bench_goal_plus.sat_audit import (
    audit_brief_rows,
    audit_brief_summary,
    verifier_claim_rows,
)


ROOT = Path(__file__).parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SatEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.run_dir = ROOT / ".tmp" / f"sat-evidence-{id(self)}" / ".gp" / "runs" / "run_1"
        self.run_dir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.run_dir.parents[2], True)
        write_json(
            self.run_dir / "verifier" / "tasks" / "verifier_1.json",
            {
                "outcome": "completed",
                "scores": {
                    "claim_specificity": 0.8,
                    "evidence_grounding": 0.6,
                    "correctness_gap": 0.4,
                },
                "steering_findings": {"hypothesis": "pack slots"},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
        write_json(
            self.run_dir / "verifier" / "records" / "record_1.json",
            {
                "record_id": "record_1",
                "outcome": "completed",
                "scores": {
                    "claim_specificity": 0.8,
                    "evidence_grounding": 0.6,
                    "correctness_gap": 0.4,
                },
                "steering_findings": {"hypothesis": "pack slots"},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
        write_json(
            self.run_dir / "steering-attempts" / "steering_0123456789abcdef01234567.json",
            {
                "delivery": {"mode": "apply"},
                "observation": "returned",
                "action": "sat.claim_repair.v1",
            },
        )
        write_json(
            self.run_dir / "steering-diagnostics" / "steering_0123456789abcdef01234567.json",
            {"mode": "apply", "result": {"action": "claim_repair"}},
        )
        write_json(
            self.run_dir / "shared-cache" / "cache_1.json",
            {
                "record_id": "cache_1",
                "section": "reusable_facts",
                "writer": "candidate:c001",
                "content": "packing two slots is valid",
                "evidence_ref": "c001:1",
            },
        )
        write_json(
            self.run_dir / "agent_sessions" / "agent_1.json",
            {
                "candidate_id": "c001",
                "global_evidence_reads": [
                    {
                        "source": "manual",
                        "completed_view_count": 2,
                    },
                    {
                        "source": "manual",
                        "completed_view_count": 1,
                    },
                ],
            },
        )
        collaboration = self.run_dir / "collaboration"
        collaboration.mkdir()
        (collaboration / "events.jsonl").write_text(
            "\n".join(
                json.dumps(item)
                for item in (
                    {
                        "run_id": "run_1",
                        "candidate_id": "c001",
                        "phase": "peer_audit",
                        "kind": "phase_started",
                        "at": "2026-10-20T00:00:00Z",
                    },
                    {
                        "run_id": "run_1",
                        "candidate_id": "c001",
                        "phase": "peer_audit",
                        "kind": "evidence_read",
                        "at": "2026-10-20T00:01:00Z",
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        write_json(
            collaboration / "certificates" / "c001" / "peer_audit.json",
            {
                "protocol": "sat-gp/v2",
                "candidate_id": "c001",
                "phase": "peer_audit",
                "claims": [{"status": "adopt"}],
                "peer_audits": [{"decision": "adopt"}],
            },
        )
        write_json(
            self.run_dir / "audit" / "briefs" / "audit_1.json",
            {
                "brief_id": "audit_1",
                "status": "pending",
                "defects": [{"kind": "semantics"}],
            },
        )
        write_json(
            self.run_dir / "audit" / "briefs" / "audit_2.json",
            {
                "brief_id": "audit_2",
                "status": "accepted",
                "response_reason": "try it",
                "defects": [{"kind": "shortcut"}, {"kind": "resource"}],
            },
        )
        write_json(
            self.run_dir / "audit" / "credentials" / "audit_cred_1.json",
            {"status": "verified", "audit_brief_id": "audit_2"},
        )


    def test_sat_metrics_read_persisted_artifacts(self) -> None:
        metrics = sat_metrics(self.run_dir)
        self.assertEqual(metrics["verifier"]["verifier_records"], 1)
        self.assertEqual(metrics["verifier"]["verifier_completed"], 1)
        self.assertEqual(
            metrics["verifier"]["verifier_text_score_means"]["claim_specificity"],
            0.8,
        )
        self.assertEqual(metrics["steering"]["steering_attempts"], 1)
        self.assertEqual(metrics["steering"]["steering_applied"], 1)
        self.assertEqual(metrics["steering"]["steering_apply_evaluations"], 1)
        self.assertEqual(metrics["evidence"]["global_evidence_reads"], 2)
        self.assertEqual(
            metrics["evidence"]["global_evidence_reader_candidate_count"], 1
        )
        self.assertEqual(metrics["evidence"]["global_evidence_peer_reads"], 1)
        self.assertEqual(metrics["shared_cache"]["shared_cache_records"], 1)
        self.assertEqual(
            metrics["shared_cache"]["shared_cache_candidate_writer_count"], 1
        )
        self.assertEqual(metrics["collaboration"]["events_total"], 2)
        self.assertEqual(metrics["collaboration"]["certificates_total"], 1)
        self.assertEqual(metrics["collaboration"]["claims_total"], 1)
        self.assertEqual(metrics["collaboration"]["peer_audits_total"], 1)
        self.assertEqual(metrics["collaboration"]["evidence_reads_total"], 1)
        self.assertEqual(metrics["audit"]["briefs_total"], 2)
        self.assertEqual(metrics["audit"]["briefs_pending"], 1)
        self.assertEqual(metrics["audit"]["briefs_delivered"], 1)
        self.assertEqual(metrics["audit"]["briefs_accepted"], 1)
        self.assertEqual(metrics["audit"]["audit_acceptance_rate"], 1.0)
        self.assertEqual(metrics["audit"]["credentials_total"], 1)
        self.assertEqual(metrics["audit"]["credentials_verified"], 1)
        self.assertEqual(metrics["audit"]["audit_verified_rate"], 1.0)
        self.assertEqual(metrics["audit"]["defect_kinds"], {"resource": 1, "semantics": 1, "shortcut": 1})

    def test_missing_collaboration_ledger_is_explicitly_absent(self) -> None:
        empty = self.run_dir.parent / "run_empty"
        empty.mkdir()
        self.assertEqual(collaboration_snapshot(empty)["status"], "absent")
        self.assertEqual(steering_snapshot(empty)["steering_attempts"], 0)

    def test_aggregate_metrics_merge_runs(self) -> None:
        first = sat_metrics(self.run_dir)
        aggregate = aggregate_sat_metrics([first, first])
        self.assertEqual(aggregate["runs_with_sat"], 2)
        self.assertEqual(aggregate["metrics"]["verifier_records"], 2)
        self.assertEqual(aggregate["metrics"]["steering_applied"], 2)
        self.assertEqual(aggregate["collaboration_status"], "present")
        self.assertEqual(aggregate["metrics"]["audit_briefs"], 4)
        self.assertEqual(aggregate["metrics"]["audit_briefs_delivered"], 2)
        self.assertEqual(aggregate["metrics"]["audit_credentials_verified"], 2)
        self.assertEqual(aggregate["audit_status"], "present")
        self.assertEqual(aggregate["audit_delivery_rate"], 0.5)
        self.assertEqual(aggregate["audit_verified_rate"], 1.0)
        self.assertEqual(aggregate["audit_defect_kinds"]["semantics"], 2)

    def test_verifier_claim_rows_include_audit_claims_and_defects(self) -> None:
        write_json(
            self.run_dir / "verifier" / "records" / "record_2.json",
            {
                "record_id": "verifier_2",
                "subject": {"candidate_id": "c001", "iteration": 2},
                "outcome": "completed",
                "audit": {
                    "claim": {
                        "claim_id": "claim_1",
                        "statement": "The attempt preserves behavior.",
                        "scope": "hypothesis",
                        "evidence_refs": ["hypothesis"],
                    },
                    "defects": [
                        {
                            "defect_id": "defect_1",
                            "kind": "semantics",
                            "observation": "The tail shape differs.",
                            "evidence_refs": ["controller_evidence"],
                            "confidence": 0.9,
                        }
                    ],
                },
            },
        )
        rows = verifier_claim_rows(self.run_dir)
        audit_rows = [row for row in rows if row["kind"].startswith("audit_")]
        self.assertEqual(
            [row["kind"] for row in audit_rows],
            ["audit_claim", "audit_defect:semantics"],
        )

    def test_audit_brief_rows_join_credentials(self) -> None:
        rows = audit_brief_rows(self.run_dir)
        self.assertEqual(len(rows), 3)
        accepted = [row for row in rows if row["status"] == "accepted"]
        self.assertEqual(len(accepted), 2)
        self.assertEqual(
            {row["credential_status"] for row in accepted},
            {"verified"},
        )
        summary = audit_brief_summary(self.run_dir)
        self.assertEqual(summary["briefs_total"], 2)
        self.assertEqual(summary["credentials_total"], 1)

    def test_audit_snapshot_is_explicitly_absent(self) -> None:
        empty = self.run_dir.parent / "run_audit_empty"
        empty.mkdir()
        snapshot = audit_snapshot(empty)
        self.assertEqual(snapshot["status"], "absent")
        self.assertEqual(snapshot["briefs_total"], 0)


if __name__ == "__main__":
    unittest.main()
