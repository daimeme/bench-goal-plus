import json
import shutil
import sys
import unittest
from pathlib import Path

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.runners.factory import create_runner
from experiments.benchmark_compare.sat import (
    SAT_CONTROLLER_EXPERIMENT_ENV,
    SAT_GLOBAL_EVIDENCE_MODE_ENV,
    SAT_TASK_REFERENCE_ENV,
    require_sat_controller_experiment,
    resolve_sat_experiment_mode,
    sat_controller_environment,
)
from experiments.benchmark_compare.conditions import CONDITIONS, resolve_condition


ROOT = Path(__file__).parents[1]
PROFILE_ROOT = ROOT / "benchmarks" / "profiles" / "vliw-sat"
AUDIT_PROFILE_ROOT = ROOT / "benchmarks" / "profiles" / "vliw-audit"
EDGE_PROFILE_ROOT = ROOT / "experiments" / "edgebench" / "profiles"


class SatVliwProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = BenchmarkAgent()

    def test_profiles_are_matched_and_exclude_single_agent_baseline(self) -> None:
        for index in range(1, 6):
            preset_id = f"local-vliw-sat-a{index}-2h"
            spec = self.agent.resolve_spec(preset_id=preset_id)
            self.assertEqual(spec.conditions, (f"A{index}",))
            self.assertEqual(spec.methods, ())
            self.assertEqual(spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1})
            self.assertEqual(spec.worker_runtime_seconds, 6600)
            profile = json.loads(
                (
                    PROFILE_ROOT / f"vliw-sat-a{index}-2h-deepseek-v4-flash-medium.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(profile["benchmark"], "local-vliw")
            self.assertEqual(profile["conditions"], [f"A{index}"])
            self.assertEqual(profile["methods"], ["goal-plus-pi"])
            self.assertEqual(profile["model"], "deepseek-v4-flash")
            self.assertEqual(profile["reasoning_effort"], "medium")
            self.assertEqual(
                (
                    profile["wall_time_seconds"],
                    profile["concurrency"],
                    profile["cell_concurrency"],
                ),
                (7200, 4, 1),
            )
            self.assertEqual(profile["experiment_mode"], f"a{index}")
            for stale_key in ("shared_cache", "shared_evidence", "verifier", "steering"):
                self.assertNotIn(stale_key, profile)

    def test_vliw_task_reference_is_declared_for_verifier_input(self) -> None:
        source = (ROOT / "adapters/local_vliw/adapter.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'GOAL_PLUS_TASK_REFERENCE = ("TASK.md", "problem.py", '
            '"runner.py", "verifier.py")',
            source,
        )
        self.assertIn("include_controller_evidence=True", source)
        self.assertIn('"controller_evidence": controller_evidence', source)
        self.assertEqual(
            SAT_TASK_REFERENCE_ENV, "GOAL_PLUS_CONTROLLER_TASK_REFERENCE"
        )

    def test_common_runner_freezes_condition_and_profile(self) -> None:
        spec = self.agent.resolve_spec(preset_id="local-vliw-sat-a5-2h")
        runner = create_runner(spec.runner)
        commands, _ = runner.prepare_commands(spec)
        command = commands[0]
        self.assertIn("--profile", command)
        self.assertIn("vliw-sat-a5-2h-deepseek-v4-flash-medium.json", " ".join(command))
        self.assertIn("--conditions", command)
        self.assertIn("A5", command)

    def test_matrix_preset_runs_all_arms_in_one_campaign(self) -> None:
        spec = self.agent.resolve_spec(preset_id="local-vliw-sat-matrix-2h")
        self.assertEqual(spec.conditions, ("A1", "A2", "A3", "A4", "A5"))
        self.assertEqual(spec.methods, ())
        self.assertEqual(spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1})
        self.assertEqual(spec.worker_runtime_seconds, 6600)
        profile = json.loads(
            (PROFILE_ROOT / "vliw-sat-matrix-2h-deepseek-v4-flash-medium.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(profile["conditions"], ["A1", "A2", "A3", "A4", "A5"])
        self.assertNotIn("experiment_mode", profile)

    def test_a5_profile_carries_protocol_metadata_without_fake_toggles(self) -> None:
        profile = json.loads(
            (PROFILE_ROOT / "vliw-sat-a5-2h-deepseek-v4-flash-medium.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(profile["sat_protocol"], "sat-gp/v2")
        self.assertEqual(profile["experiment_mode"], "a5")
        self.assertIsNone(CONDITIONS["A5"].search_space_mode)
        self.assertIsNone(CONDITIONS["A5"].coordination_variant)
        self.assertNotIn("shared_cache", profile)
        self.assertNotIn("verifier", profile)
        self.assertNotIn("steering", profile)

    def test_audit_group_profiles_and_modes_are_declared(self) -> None:
        for mode, condition_id in (
            ("n0", "N0"),
            ("n0v", "N0v"),
            ("n1", "N1"),
            ("n2", "N2"),
        ):
            spec = self.agent.resolve_spec(
                preset_id=f"local-vliw-audit-{mode}-2h"
            )
            self.assertEqual(spec.conditions, (condition_id,))
            profile = json.loads(
                (
                    AUDIT_PROFILE_ROOT
                    / f"vliw-audit-{mode}-2h-deepseek-v4-flash-medium.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(profile["experiment_mode"], mode)
            self.assertEqual(profile["conditions"], [condition_id])
            self.assertEqual(
                resolve_sat_experiment_mode(CONDITIONS[condition_id], None),
                mode,
            )
            environment = sat_controller_environment(mode)
            self.assertEqual(
                environment[SAT_GLOBAL_EVIDENCE_MODE_ENV], "independent"
            )

        edge = json.loads(
            (
                EDGE_PROFILE_ROOT
                / "vliw-audit-n1-pi-deepseek-v4-flash-2h-k4-c1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(edge["experiment_mode"], "n1")
        self.assertEqual(edge["global_evidence_mode"], "independent")

    def test_n3_is_explicitly_blocked_on_closure(self) -> None:
        self.assertFalse(CONDITIONS["N3"].implemented)
        with self.assertRaises(ValueError):
            resolve_condition(
                method="goal-plus-pi", concurrency=4, condition_id="N3"
            )
        with self.assertRaises(RuntimeError):
            require_sat_controller_experiment(ROOT, "n3")

    def test_audit_matrix_and_pilot_presets(self) -> None:
        matrix = self.agent.resolve_spec(preset_id="local-vliw-audit-matrix-2h")
        self.assertEqual(matrix.conditions, ("N0v", "N1", "N2"))
        pilot = self.agent.resolve_spec(preset_id="local-vliw-audit-pilot-30m")
        self.assertEqual(pilot.conditions, ("N0v", "N1", "N2"))
        self.assertEqual(pilot.concurrency()["T"], 1800)
        self.assertEqual(pilot.worker_runtime_seconds, 1500)

    def test_sat_mode_mapping_is_controller_owned(self) -> None:
        expected = {
            "A1": "a1",
            "A2": "a2",
            "A3": "a3",
            "A4": "a4",
            "A5": "a5",
        }
        for condition_id, mode in expected.items():
            condition = CONDITIONS[condition_id]
            self.assertEqual(resolve_sat_experiment_mode(condition, None), mode)
            environment = sat_controller_environment(mode)
            self.assertEqual(
                environment[SAT_CONTROLLER_EXPERIMENT_ENV],
                json.dumps({"mode": mode}, separators=(",", ":")),
            )
            self.assertEqual(
                environment[SAT_GLOBAL_EVIDENCE_MODE_ENV],
                "independent" if mode == "a1" else "manual",
            )
        with self.assertRaises(ValueError):
            resolve_sat_experiment_mode(
                CONDITIONS["A3"], {"experiment_mode": "a4"}
            )

    def test_preflight_rejects_pre_sat_goal_plus_source(self) -> None:
        scratch = ROOT / ".tmp" / f"sat-preflight-{id(self)}"
        scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, scratch, True)
        root = scratch
        overlay = (
            root
            / "src"
            / "goal_plus"
            / "application"
            / "controller_overlay.py"
        )
        overlay.parent.mkdir(parents=True)
        overlay.write_text(
            'CONTROLLER_EXPERIMENT_ENV = "GOAL_PLUS_CONTROLLER_EXPERIMENT"\n'
            "def apply_controller_experiment_overlay(spec, raw):\n"
            "    return spec\n",
            encoding="utf-8",
        )
        with self.assertRaises(RuntimeError):
            require_sat_controller_experiment(root, "a5")
        collaboration = root / "src" / "goal_plus" / "domain" / "collaboration.py"
        collaboration.parent.mkdir(parents=True)
        collaboration.write_text("", encoding="utf-8")
        require_sat_controller_experiment(root, "a5")
        require_sat_controller_experiment(root, "a1")

    @unittest.skipIf(
        sys.platform == "win32",
        "the common runner imports POSIX-only modules on this host",
    )
    def test_codex_mcp_forwards_controller_sat_environment(self) -> None:
        from experiments.openevolve_compare.experiment import (
            codex_goal_plus_mcp_args,
        )

        rendered = " ".join(codex_goal_plus_mcp_args())
        for name in (
            "GOAL_PLUS_CONTROLLER_EXPERIMENT",
            "GOAL_PLUS_GLOBAL_EVIDENCE_MODE",
            "GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED",
        ):
            self.assertIn(name, rendered)

    @unittest.skipIf(
        sys.platform == "win32",
        "the common runner imports POSIX-only modules on this host",
    )
    def test_goal_prompt_delegates_sat_switches_to_controller(self) -> None:
        from experiments.openevolve_compare.experiment import render_goal

        prompt = render_goal(
            task_text="optimize",
            artifact_name="solution.py",
            metric_name="cycles",
            metric_direction="minimize",
            wall_seconds=7200,
            closeout_seconds=60,
            concurrency=4,
            agent_harness="codex",
            worker_model="deepseek-v4-flash",
            sat_experiment_mode="a3",
        )
        self.assertIn("GOAL_PLUS_CONTROLLER_EXPERIMENT", prompt)
        self.assertIn("`a3`", prompt)
        self.assertNotIn("Shared Evidence/cache:", prompt)
        self.assertNotIn("Verifier mode:", prompt)
        self.assertNotIn("Steering mode:", prompt)


if __name__ == "__main__":
    unittest.main()
