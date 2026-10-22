import json
import shutil
import tarfile
import unittest
from pathlib import Path

from bench_goal_plus.sat_contract import (
    sat_controller_environment,
)
from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.sat_edgebench_analysis import (
    edgebench_phase1_summary,
    load_edgebench_campaign,
)
from experiments.edgebench.controller.profiles import load_profile
from experiments.edgebench.controller.runtime import cell_environment
from experiments.edgebench.controller.sat_evidence import sat_metrics_from_archive


ROOT = Path(__file__).parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def extra_env(env: dict[str, str]) -> dict[str, str]:
    entries = {}
    for item in (env.get("SFORGE_AGENT_EXTRA_ENV") or "").split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            entries[key] = value
    return entries


class EdgeBenchSatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = ROOT / ".tmp" / f"edgebench-sat-{id(self)}"
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def test_sat_profiles_select_expected_arms(self) -> None:
        for index in (1, 2, 3, 4, 5):
            _, profile = load_profile(
                f"vliw-sat-a{index}-pi-deepseek-v4-flash-2h-k4-c1"
            )
            self.assertEqual(profile["experiment_mode"], f"a{index}")
            self.assertEqual(
                profile["global_evidence_mode"],
                "independent" if index == 1 else "manual",
            )
            self.assertEqual(profile["methods"], ["goal-plus-pi-provider"])
            self.assertEqual(profile["model"], "deepseek/deepseek-v4-flash")

    def test_sat_preset_resolves_frozen_contract(self) -> None:
        spec = BenchmarkAgent().resolve_spec(preset_id="edgebench-vliw-sat-a3-2h")
        self.assertEqual(spec.methods, ("goal-plus-pi-provider",))
        self.assertEqual(spec.model, "deepseek/deepseek-v4-flash")
        self.assertEqual(spec.reasoning_effort, "medium")
        self.assertEqual(
            spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1}
        )

    def test_codex_sat_profiles_and_presets(self) -> None:
        for index in (1, 3, 5):
            _, profile = load_profile(
                f"vliw-sat-a{index}-codex-gpt-5-6-sol-2h-k4-c1"
            )
            self.assertEqual(profile["experiment_mode"], f"a{index}")
            self.assertEqual(
                profile["global_evidence_mode"],
                "independent" if index == 1 else "manual",
            )
            self.assertEqual(profile["methods"], ["goal-plus-codex"])
            self.assertEqual(profile["model"], "gpt-5.6-sol")
            spec = BenchmarkAgent().resolve_spec(
                preset_id=f"edgebench-vliw-sat-a{index}-codex-2h"
            )
            self.assertEqual(spec.methods, ("goal-plus-codex",))
            self.assertEqual(spec.model, "gpt-5.6-sol")
            self.assertEqual(spec.reasoning_effort, "medium")
            self.assertEqual(
                spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1}
            )

    def test_audit_n_profiles_and_presets(self) -> None:
        for mode in ("n0", "n0v", "n1", "n2", "n3"):
            _, profile = load_profile(
                f"vliw-audit-{mode}-pi-deepseek-v4-flash-2h-k4-c1"
            )
            self.assertEqual(profile["experiment_mode"], mode)
            self.assertEqual(profile["global_evidence_mode"], "independent")
            self.assertEqual(profile["methods"], ["goal-plus-pi-provider"])
            spec = BenchmarkAgent().resolve_spec(
                preset_id=f"edgebench-vliw-audit-{mode}-pi-2h"
            )
            self.assertEqual(spec.methods, ("goal-plus-pi-provider",))
            self.assertEqual(
                spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1}
            )

    def test_controller_environment_keeps_a1_independent(self) -> None:
        self.assertEqual(
            sat_controller_environment("a1")["GOAL_PLUS_GLOBAL_EVIDENCE_MODE"],
            "independent",
        )
        a3 = sat_controller_environment("a3")
        self.assertEqual(a3["GOAL_PLUS_GLOBAL_EVIDENCE_MODE"], "manual")
        self.assertEqual(a3["GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED"], "1")
        self.assertEqual(a3["GOAL_PLUS_CONTROLLER_EXPERIMENT"], '{"mode":"a3"}')

    def test_cell_environment_injects_sat_overlay(self) -> None:
        cell = {
            "method": "goal-plus-pi-provider",
            "sforge_agent": "pi-goal-plus-provider",
            "reasoning_effort": "medium",
            "model": "deepseek/deepseek-v4-flash",
            "inner_search_concurrency": 4,
            "worker_runtime_seconds": 6600,
            "goal_plus_source": {"source_dir": str(ROOT / "third_party" / "goal_plus")},
            "experiment_mode": "a3",
            "global_evidence_mode": "manual",
            "pi_package_version": "0.83.0",
            "internet": False,
        }
        env = cell_environment(
            cell,
            api_base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        values = extra_env(env)
        self.assertEqual(values["GOAL_PLUS_CONTROLLER_EXPERIMENT"], '{"mode":"a3"}')
        self.assertEqual(values["GOAL_PLUS_GLOBAL_EVIDENCE_MODE"], "manual")
        self.assertEqual(values["GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED"], "1")
        self.assertNotIn("GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL", values)
        self.assertNotIn(
            "SFORGE_GOAL_PLUS_EVIDENCE_ANNOTATOR_TIMEOUT_SECONDS", values
        )

    def test_sat_archive_metrics(self) -> None:
        archive_path = self.scratch / "goal-plus-state.tar"
        files = {
            "runs/run_1/verifier/tasks/verifier_1.json": {
                "record_id": "v1",
                "outcome": "completed",
                "scores": {"claim_specificity": 0.8, "correctness_gap": 0.2},
                "steering_findings": {"hypothesis": {"statement": "x"}},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "runs/run_1/verifier/records/record_1.json": {
                "record_id": "record_1",
                "outcome": "completed",
                "scores": {"claim_specificity": 0.8, "correctness_gap": 0.2},
                "audit": {"claim": {"statement": "x"}, "defects": []},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
            "runs/run_1/steering-attempts/a1.json": {
                "observation": "returned",
                "delivery": {"mode": "apply"},
            },
            "runs/run_1/steering-diagnostics/d1.json": {
                "mode": "shadow",
                "result": {"action": "claim_repair"},
            },
            "runs/run_1/shared-cache/c1.json": {
                "writer": "candidate:c1",
                "section": "reusable_facts",
                "evidence_ref": "e1",
            },
            "runs/run_1/agent_sessions/agent_1.json": {
                "candidate_id": "c1",
                "global_evidence_reads": [
                    {"source": "peer", "completed_view_count": 2}
                ],
            },
            "runs/run_1/collaboration/events.jsonl": (
                '{"kind":"phase_started","phase":"P1"}\n'
                '{"kind":"phase_completed","phase":"P1"}\n'
            ),
            "runs/run_1/collaboration/certificates/c1/P1.json": {
                "claims": [{"status": "supported"}],
                "peer_audits": [{"status": "passed"}],
            },
            "runs/run_1/audit/briefs/audit_1.json": {
                "status": "accepted",
                "defects": [{"kind": "semantics"}],
            },
            "runs/run_1/audit/credentials/audit_cred_1.json": {
                "status": "verified"
            },
        }
        with tarfile.open(archive_path, "w") as archive:
            for name, payload in files.items():
                data = (
                    payload
                    if isinstance(payload, str)
                    else json.dumps(payload)
                ).encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(data)
                import io

                archive.addfile(info, io.BytesIO(data))
        metrics = sat_metrics_from_archive(archive_path)
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["verifier_records"], 1)
        self.assertEqual(metrics["steering_applied"], 1)
        self.assertEqual(metrics["steering_shadow_evaluations"], 1)
        self.assertEqual(metrics["shared_cache_records"], 1)
        self.assertEqual(metrics["shared_cache_candidate_writer_count"], 1)
        self.assertEqual(metrics["global_evidence_peer_reads"], 1)
        self.assertEqual(metrics["collaboration_status"], "present")
        self.assertEqual(metrics["collaboration_events"], 2)
        self.assertEqual(metrics["collaboration_claims"], 1)
        self.assertEqual(metrics["audit_briefs"], 1)
        self.assertEqual(metrics["audit_briefs_accepted"], 1)
        self.assertEqual(metrics["audit_credentials_verified"], 1)
        self.assertEqual(metrics["audit_acceptance_rate"], 1.0)
        self.assertEqual(metrics["audit_verified_rate"], 1.0)

    def test_edgebench_phase1_summary_pairs_repeats(self) -> None:
        campaign_dirs = {}
        for arm, scores in (("A1", (70.0, 72.0)), ("A2", (75.0, 77.0))):
            for repeat, score in enumerate(scores, start=1):
                directory = self.scratch / f"{arm}-r{repeat}"
                write_json(
                    directory / "comparison.json",
                    {
                        "campaign_id": f"{arm}-r{repeat}",
                        "experiment_mode": arm.lower(),
                        "cells": [
                            {
                                "task_id": "vliw_kernel_optimization",
                                "method": "goal-plus-pi-provider",
                                "model": "deepseek/deepseek-v4-flash",
                                "reasoning_effort": "medium",
                                "wall_time_seconds": 7200,
                                "sat_experiment_mode": arm,
                                "valid_trajectories": 1,
                                "official_edgebench_comparable": True,
                                "completion_evidence": {"passed": True},
                                "best": {
                                    "edgebench_score": score,
                                    "raw_score": 1000.0 + score,
                                },
                                "sat": {
                                    "verifier_records": 2,
                                    "steering_applied": 1,
                                    "shared_cache_records": 3,
                                    "global_evidence_peer_reads": 1,
                                    "collaboration_events": 4,
                                },
                            }
                        ],
                    },
                )
                campaign_dirs.setdefault(arm, []).append(directory)
        loaded = load_edgebench_campaign(campaign_dirs["A1"][0])
        self.assertEqual(loaded["mode"], "A1")
        summary = edgebench_phase1_summary(campaign_dirs)
        self.assertEqual(summary["arms"]["A1"]["score_mean"], 71.0)
        self.assertEqual(summary["paired"]["A2 - A1"]["paired_count"], 2)
        self.assertEqual(summary["paired"]["A2 - A1"]["mean_difference"], 5.0)
        self.assertEqual(
            summary["arms"]["A1"]["sat_totals"]["verifier_records"], 4
        )


    def test_edgebench_phase1_summary_pairs_audit_arms(self) -> None:
        campaign_dirs = {}
        for arm, scores in (("N0V", (70.0, 72.0)), ("N1", (75.0, 77.0))):
            for repeat, score in enumerate(scores, start=1):
                directory = self.scratch / f"{arm}-r{repeat}"
                write_json(
                    directory / "comparison.json",
                    {
                        "campaign_id": f"{arm}-r{repeat}",
                        "experiment_mode": arm.lower(),
                        "cells": [
                            {
                                "task_id": "vliw_kernel_optimization",
                                "method": "goal-plus-pi-provider",
                                "model": "deepseek/deepseek-v4-flash",
                                "reasoning_effort": "medium",
                                "wall_time_seconds": 7200,
                                "sat_experiment_mode": arm.lower(),
                                "valid_trajectories": 1,
                                "official_edgebench_comparable": True,
                                "completion_evidence": {"passed": True},
                                "best": {
                                    "edgebench_score": score,
                                    "raw_score": 1000.0 + score,
                                },
                                "sat": {
                                    "verifier_records": 2,
                                    "audit_briefs": 1,
                                    "audit_briefs_delivered": 1,
                                    "audit_briefs_accepted": 1,
                                    "audit_credentials": 1,
                                    "audit_credentials_verified": 1,
                                },
                            }
                        ],
                    },
                )
                campaign_dirs.setdefault(arm, []).append(directory)
        summary = edgebench_phase1_summary(campaign_dirs)
        self.assertEqual(summary["arms"]["N1"]["score_mean"], 76.0)
        self.assertEqual(summary["paired"]["N1 - N0v"]["paired_count"], 2)
        self.assertEqual(summary["paired"]["N1 - N0v"]["mean_difference"], 5.0)
        self.assertEqual(
            summary["arms"]["N1"]["sat_totals"]["audit_credentials_verified"], 2
        )


if __name__ == "__main__":
    unittest.main()
