import json
import tempfile
import unittest
from pathlib import Path

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.collaboration_contract import (
    COLLABORATION_CONTROLLER_ENV,
    collaboration_controller_environment,
    collaboration_payload,
    require_collaboration_controller,
    resolve_collaboration_mode,
)
from experiments.benchmark_compare.conditions import CONDITIONS, resolve_condition


ROOT = Path(__file__).parents[1]
PROFILE_ROOT = ROOT / "benchmarks" / "profiles" / "vliw-collab"


class CollaborationVliwTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = BenchmarkAgent()

    def test_single_arm_presets_are_matched(self) -> None:
        for arm in ("c0", "c1", "c2"):
            preset_id = f"local-vliw-collab-{arm}-2h"
            spec = self.agent.resolve_spec(preset_id=preset_id)
            self.assertEqual(spec.methods, ())
            self.assertEqual(spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1})
            self.assertEqual(spec.worker_runtime_seconds, 6600)
            profile = json.loads(
                (PROFILE_ROOT / f"vliw-collab-{arm}-2h-deepseek-v4-flash-medium.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(profile["benchmark"], "local-vliw")
            self.assertEqual(profile["conditions"], [arm.upper()])
            self.assertEqual(profile["collaboration_mode"], arm)

    def test_matrix_preset_carries_three_conditions(self) -> None:
        spec = self.agent.resolve_spec(preset_id="local-vliw-collab-matrix-2h")
        self.assertEqual(spec.conditions, ("C0", "C1", "C2"))
        self.assertEqual(spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1})

    def test_pilot_preset_uses_the_short_budget(self) -> None:
        spec = self.agent.resolve_spec(preset_id="local-vliw-collab-pilot-30m")
        self.assertEqual(spec.conditions, ("C0", "C1"))
        self.assertEqual(spec.concurrency()["T"], 1800)
        self.assertEqual(spec.worker_runtime_seconds, 1500)

    def test_conditions_map_to_controller_arms(self) -> None:
        for condition_id, mode in (("C0", "c0"), ("C1", "c1"), ("C2", "c2")):
            condition = CONDITIONS[condition_id]
            self.assertEqual(condition.method, "goal-plus-pi")
            self.assertIsNone(condition.sat_experiment_mode)
            self.assertEqual(condition.collaboration_mode, mode)
            self.assertEqual(
                resolve_condition(
                    method="goal-plus-pi", concurrency=4, condition_id=condition_id
                ),
                condition,
            )

    def test_controller_environment_is_empty_for_the_baseline(self) -> None:
        self.assertEqual(collaboration_controller_environment(None), {})
        self.assertEqual(collaboration_controller_environment("c0"), {})
        self.assertNotIn(COLLABORATION_CONTROLLER_ENV, collaboration_controller_environment("c0"))

    def test_controller_environment_freezes_the_arm(self) -> None:
        single = json.loads(
            collaboration_controller_environment("c1")[COLLABORATION_CONTROLLER_ENV]
        )
        self.assertEqual(single["mode"], "advisory")
        self.assertEqual(single["strategy_ids"], ["mechanistic_step_audit"])
        self.assertEqual(single["max_strategies"], 1)

        full = collaboration_payload("c2")
        self.assertEqual(full["mode"], "advisory")
        self.assertEqual(len(full["strategy_ids"]), 10)
        self.assertEqual(full["max_strategies"], 10)

    def test_mode_must_match_its_condition(self) -> None:
        with self.assertRaises(ValueError):
            resolve_collaboration_mode(CONDITIONS["C1"], {"collaboration_mode": "c2"})
        self.assertEqual(resolve_collaboration_mode(CONDITIONS["C2"], None), "c2")
        with self.assertRaises(ValueError):
            resolve_collaboration_mode(CONDITIONS["C2"], {"collaboration_mode": "c9"})

    def test_requirement_preflight_rejects_a_source_without_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                require_collaboration_controller(Path(directory), "c1")


if __name__ == "__main__":
    unittest.main()
