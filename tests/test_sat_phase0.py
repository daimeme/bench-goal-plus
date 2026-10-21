import json
import shutil
import unittest
from pathlib import Path

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.sat_analysis import (
    phase0_summary,
    render_phase0_markdown,
    selection_metrics,
)
from bench_goal_plus.sat_audit import (
    audit_from_files,
    export_claims,
    verifier_claim_rows,
)


ROOT = Path(__file__).parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class SatPhase0Test(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = ROOT / ".tmp" / f"sat-phase0-{id(self)}"
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def test_selection_metrics_report_coverage_and_loss(self) -> None:
        runs = [
            {
                "run_id": "run_1",
                "candidate_best_scores": {"c001": 95, "c002": 90},
                "selected_candidate_id": "c001",
                "selected_score": 95,
            }
        ]
        metrics = selection_metrics(
            runs, seed_score=100, final_score=95, direction="minimize"
        )
        self.assertEqual(metrics["coverage"], "covered")
        self.assertEqual(metrics["coverage_gain"], 10.0)
        self.assertEqual(metrics["selection_loss"], 5.0)
        self.assertEqual(metrics["best_candidate_id"], "c002")
        self.assertFalse(metrics["selected_best_match"])

    def test_pilot_preset_is_matched_and_short(self) -> None:
        spec = BenchmarkAgent().resolve_spec(preset_id="local-vliw-sat-pilot-30m")
        self.assertEqual(spec.conditions, ("A1", "A2", "A3"))
        self.assertEqual(spec.concurrency(), {"T": 1800, "K": 4, "C": 1, "R": 1})
        self.assertEqual(spec.worker_runtime_seconds, 1500)

    def test_phase0_summary_pairs_replicates(self) -> None:
        for index in (1, 2):
            campaign_dir = self.scratch / f"campaign-{index}"
            records = []
            for condition, gain in (("A1", 1.0), ("A2", 3.0), ("A3", 2.0)):
                records.append(
                    {
                        "benchmark_id": "local-vliw",
                        "task_id": "vliw_kernel_optimization",
                        "seed": 1,
                        "condition": condition,
                        "status": "finished",
                        "score": {"final": 100 - gain, "directional_gain": gain},
                        "selection": {
                            "coverage_achieved": True,
                            "selection_loss": 0.5,
                            "candidate_score_spread": 2.0,
                        },
                        "sat": {"metrics": {"verifier_records": 1}},
                    }
                )
            write_json(
                campaign_dir / "campaign-summary.json",
                {
                    "campaign_id": f"campaign-{index}",
                    "records": records,
                },
            )
        summary = phase0_summary([self.scratch / "campaign-1", self.scratch / "campaign-2"])
        self.assertEqual(summary["record_count"], 6)
        self.assertEqual(summary["arms"]["A1"]["cell_count"], 2)
        self.assertEqual(summary["paired"]["A2 - A1"]["paired_count"], 2)
        self.assertEqual(
            summary["paired"]["A2 - A1"]["mean_difference"], 2.0
        )
        self.assertIn("SAT-GP Phase 0", render_phase0_markdown(summary))

    def test_verifier_claim_export_and_precision(self) -> None:
        run_dir = self.scratch / ".gp" / "runs" / "run_1"
        write_json(
            run_dir / "verifier" / "tasks" / "verifier_1.json",
            {
                "record_id": "verifier_1",
                "subject": {"candidate_id": "c001", "iteration": 2},
                "outcome": "completed",
                "scores": {"claim_specificity": 0.8},
                "score_rationales": {
                    "claim_specificity": "The claim names one falsifiable change."
                },
                "steering_findings": {
                    "hypothesis": {
                        "statement": "Packing slots reduces cycles.",
                        "scope_ref": "c001:2",
                        "evidence_refs": ["c001:2"],
                    }
                },
                "evidence_refs": ["c001:2"],
            },
        )
        claims = verifier_claim_rows(run_dir)
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0]["claim_id"], "verifier_1:hypothesis")
        claims_path = self.scratch / "claims.jsonl"
        self.assertEqual(export_claims(run_dir, claims_path), 2)
        labels_path = self.scratch / "labels.jsonl"
        labels_path.write_text(
            "\n".join(
                json.dumps(item)
                for item in (
                    {"claim_id": "verifier_1:hypothesis", "label": "correct"},
                    {
                        "claim_id": "verifier_1:score:claim_specificity",
                        "label": "incorrect",
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        result = audit_from_files(claims_path, labels_path)
        self.assertEqual(result["claims_labeled"], 2)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["by_kind"]["hypothesis"]["correct"], 1)


if __name__ == "__main__":
    unittest.main()
