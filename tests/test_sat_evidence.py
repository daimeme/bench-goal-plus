import json
import shutil
import unittest
from pathlib import Path

from bench_goal_plus.goal_plus_evidence import (
    aggregate_sat_metrics,
    collaboration_snapshot,
    sat_metrics,
    steering_snapshot,
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


if __name__ == "__main__":
    unittest.main()
