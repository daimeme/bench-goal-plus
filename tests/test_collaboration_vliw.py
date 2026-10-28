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
EDGE_PROFILE_ROOT = ROOT / "experiments" / "edgebench" / "profiles"


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

    def test_edgebench_codex_presets_bind_one_arm_each(self) -> None:
        for arm in ("c0", "c1", "c2"):
            spec = self.agent.resolve_spec(
                preset_id=f"edgebench-vliw-collab-{arm}-codex-2h"
            )
            self.assertEqual(spec.methods, ("goal-plus-codex",))
            self.assertEqual(spec.conditions, ())
            self.assertEqual(spec.model, "gpt-5.6-sol")
            self.assertEqual(spec.reasoning_effort, "medium")
            self.assertEqual(spec.concurrency(), {"T": 7200, "K": 4, "C": 1, "R": 1})
            profile = json.loads(
                (
                    EDGE_PROFILE_ROOT
                    / f"vliw-collab-{arm}-codex-gpt-5-6-sol-2h-k4-c1.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(profile["collaboration_mode"], arm)
            self.assertNotIn("experiment_mode", profile)
            self.assertEqual(profile["task_ids"], ["vliw_kernel_optimization"])
            self.assertEqual(profile["protocol_source"], "edgebench-official-codex")


class CollaborationProfileValidationTest(unittest.TestCase):
    def _profile(self, **overrides):
        profile = json.loads(
            (
                EDGE_PROFILE_ROOT / "vliw-collab-c1-codex-gpt-5-6-sol-2h-k4-c1.json"
            ).read_text(encoding="utf-8")
        )
        profile.update(overrides)
        return profile

    def test_experiment_mode_and_collaboration_mode_cannot_mix(self) -> None:
        from experiments.edgebench.controller.profiles import load_profile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text(
                json.dumps(self._profile(experiment_mode="a1")), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_profile(target)

    def test_unknown_collaboration_mode_is_rejected(self) -> None:
        from experiments.edgebench.controller.profiles import load_profile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text(
                json.dumps(self._profile(collaboration_mode="c9")), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_profile(target)

    def test_worker_sandbox_mode_is_validated_and_kept(self) -> None:
        from experiments.edgebench.controller.profiles import load_profile

        with tempfile.TemporaryDirectory() as directory:
            ok = Path(directory) / "ok.json"
            ok.write_text(
                json.dumps(self._profile(worker_sandbox_mode="danger-full-access")),
                encoding="utf-8",
            )
            _, profile = load_profile(ok)
            self.assertEqual(profile["worker_sandbox_mode"], "danger-full-access")

            bad = Path(directory) / "bad.json"
            bad.write_text(
                json.dumps(self._profile(worker_sandbox_mode="off")), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_profile(bad)


if __name__ == "__main__":
    unittest.main()

