import base64
import json
import tempfile
import unittest
from pathlib import Path

from bench_goal_plus.search_strategy import (
    DIAGNOSTIC_SCORE_KEYS,
    SEARCH_STRATEGY_ARMS,
    SEARCH_STRATEGY_ENV,
    VLIW_OPTIMIZER_SCORE_KEYS,
    require_search_strategy_overlay,
    resolve_search_strategy_arm,
    search_strategy_controller_environment,
)


ROOT = Path(__file__).parents[1]
PROFILE_ROOT = ROOT / "experiments" / "edgebench" / "profiles"


class SearchStrategyContractTest(unittest.TestCase):
    def test_arms_cover_the_e0_e8_ladder(self) -> None:
        self.assertEqual(
            set(SEARCH_STRATEGY_ARMS),
            {"e0", "e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"},
        )

    def test_e0_is_hard_only(self) -> None:
        arm = resolve_search_strategy_arm("e0")
        self.assertNotIn("verifier", arm)
        self.assertNotIn("adaptive_search", arm)
        self.assertEqual(arm["selection"]["ranking_keys"], ["hard_score"])

    def test_e1_enables_diagnostic_scores_only(self) -> None:
        arm = resolve_search_strategy_arm("e1")
        self.assertEqual(arm["verifier"]["scores"], DIAGNOSTIC_SCORE_KEYS)
        self.assertNotIn("adaptive_search", arm)
        self.assertEqual(arm["selection"]["ranking_keys"], ["hard_score"])

    def test_e2_ranks_by_quality_score_then_hard(self) -> None:
        arm = resolve_search_strategy_arm("e2")
        self.assertEqual(
            arm["selection"]["ranking_keys"], ["quality_score", "hard_score"]
        )
        self.assertEqual(arm["selection"]["ranking_tolerance"], [0.05, 0.0])
        self.assertEqual(arm["verifier"]["scores"], [])

    def test_e3_enables_allocation(self) -> None:
        arm = resolve_search_strategy_arm("e3")
        self.assertEqual(arm["adaptive_search"]["allocation"]["policy"], "swe_search_uct/v1")
        self.assertNotIn("steering", arm["adaptive_search"])
        self.assertEqual(
            arm["verifier"]["scores"], ["progress_reward", "allocation_utility"]
        )
        self.assertEqual(arm["initial_context"], "fresh")

    def test_e4_enables_steering(self) -> None:
        arm = resolve_search_strategy_arm("e4")
        self.assertEqual(
            arm["adaptive_search"]["steering"]["policy"],
            "search_diagnostic_guidance/v1",
        )
        self.assertNotIn("allocation", arm["adaptive_search"])
        self.assertEqual(arm["verifier"]["scores"], DIAGNOSTIC_SCORE_KEYS)

    def test_e5_enables_both_policies(self) -> None:
        arm = resolve_search_strategy_arm("e5")
        self.assertEqual(arm["adaptive_search"]["allocation"]["policy"], "swe_search_uct/v1")
        self.assertEqual(
            arm["adaptive_search"]["steering"]["policy"],
            "search_diagnostic_guidance/v1",
        )
        self.assertEqual(
            arm["verifier"]["scores"],
            ["progress_reward", "allocation_utility", *DIAGNOSTIC_SCORE_KEYS],
        )

    def test_e6_enables_gated_vliw_allocation(self) -> None:
        arm = resolve_search_strategy_arm("e6")
        self.assertTrue(arm["verifier"]["gate"])
        self.assertEqual(arm["verifier"]["scores"], VLIW_OPTIMIZER_SCORE_KEYS)
        self.assertEqual(
            arm["adaptive_search"]["allocation"]["policy"], "vliw_reward_uct/v1"
        )
        self.assertNotIn("steering", arm["adaptive_search"])

    def test_e7_adds_quantified_bottleneck_steering(self) -> None:
        arm = resolve_search_strategy_arm("e7")
        self.assertTrue(arm["verifier"]["gate"])
        self.assertEqual(
            arm["adaptive_search"]["steering"]["policy"], "vliw_action_guidance/v1"
        )

    def test_e8_is_the_same_arm_with_the_gate_off(self) -> None:
        self.assertFalse(resolve_search_strategy_arm("e8")["verifier"]["gate"])

    def test_unknown_arm_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_search_strategy_arm("bogus")
        self.assertIsNone(resolve_search_strategy_arm(None))

    def test_controller_environment_transports_base64(self) -> None:
        env = search_strategy_controller_environment(resolve_search_strategy_arm("e2"))
        self.assertEqual(set(env), {SEARCH_STRATEGY_ENV})
        value = env[SEARCH_STRATEGY_ENV]
        # base64url is comma-free, so SFORGE_AGENT_EXTRA_ENV does not split it.
        self.assertNotIn(",", value)
        decoded = json.loads(
            base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        )
        self.assertEqual(
            decoded["selection"]["ranking_keys"], ["quality_score", "hard_score"]
        )
        self.assertEqual(search_strategy_controller_environment(None), {})

    def test_profiles_reference_known_arms(self) -> None:
        ids = sorted(
            p.name for p in PROFILE_ROOT.glob("vliw-e*-codex-gpt-5-6-sol-2h-k4-c1.json")
        )
        self.assertEqual(len(ids), 9)
        for name in ids:
            profile = json.loads((PROFILE_ROOT / name).read_text(encoding="utf-8"))
            self.assertIn(profile["search_strategy_arm"], SEARCH_STRATEGY_ARMS)
            self.assertEqual(profile["methods"], ["goal-plus-codex"])
            self.assertEqual(profile["model"], "gpt-5.6-sol")

    def test_seed_variants_cover_nine_arms_three_seeds(self) -> None:
        variants = sorted(
            p.name
            for p in PROFILE_ROOT.glob(
                "vliw-e*-codex-gpt-5-6-sol-2h-k4-c1-s*.json"
            )
        )
        self.assertEqual(len(variants), 27)
        for name in variants:
            profile = json.loads((PROFILE_ROOT / name).read_text(encoding="utf-8"))
            arm = profile["search_strategy_arm"]
            seed = profile["sampling_seed"]
            self.assertIn(arm, SEARCH_STRATEGY_ARMS)
            self.assertIn(seed, (1, 2, 3))
            self.assertEqual(profile["id"], f"vliw-{arm}-codex-gpt-5-6-sol-2h-k4-c1-s{seed}")
            self.assertEqual(profile["methods"], ["goal-plus-codex"])

    def test_require_overlay_rejects_a_source_without_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Missing controller_overlay.py entirely.
            with self.assertRaises(RuntimeError):
                require_search_strategy_overlay(root)
            overlay = (
                root / "src" / "goal_plus" / "application" / "controller_overlay.py"
            )
            overlay.parent.mkdir(parents=True)
            # Present but lacking the search-strategy tokens.
            overlay.write_text("def nothing():\n    pass\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                require_search_strategy_overlay(root)
            # Present with both tokens.
            overlay.write_text(
                'CONTROLLER_SEARCH_STRATEGY_ENV = "GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY"\n'
                "def apply_controller_search_strategy_overlay(spec, raw):\n"
                "    return spec\n",
                encoding="utf-8",
            )
            require_search_strategy_overlay(root)  # must not raise

    def test_require_overlay_covers_the_shared_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = (
                root / "src" / "goal_plus" / "application" / "controller_overlay.py"
            )
            overlay.parent.mkdir(parents=True)
            # A source with the strategy hook but no shared_dir field.
            overlay.write_text(
                'CONTROLLER_SEARCH_STRATEGY_ENV = "GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY"\n'
                "def apply_controller_search_strategy_overlay(spec, raw):\n"
                "    return spec\n",
                encoding="utf-8",
            )
            require_search_strategy_overlay(root)
            with self.assertRaises(RuntimeError):
                require_search_strategy_overlay(root, shared_dir=True)
            with self.assertRaises(RuntimeError):
                require_search_strategy_overlay(root, shared_knowledge=True)

            overlay.write_text(
                'CONTROLLER_SEARCH_STRATEGY_ENV = "GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY"\n'
                'CONTROLLER_SHARED_KNOWLEDGE_ENV = "GOAL_PLUS_CONTROLLER_SHARED_KNOWLEDGE"\n'
                "def apply_controller_search_strategy_overlay(spec, raw):\n"
                "    return spec\n"
                "def apply_controller_shared_knowledge_overlay(spec, raw):\n"
                "    return spec\n"
                "shared_dir = None\n",
                encoding="utf-8",
            )
            require_search_strategy_overlay(
                root, shared_dir=True, shared_knowledge=True
            )  # must not raise


if __name__ == "__main__":
    unittest.main()
