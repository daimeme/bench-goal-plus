import unittest

from bench_goal_plus.pi_models import apply_sampling_seed


class DeterministicSamplingTests(unittest.TestCase):
    def test_sampling_seed_is_projected_to_every_model(self) -> None:
        registry = {
            "providers": {
                "deepseek": {
                    "models": [
                        {"id": "deepseek-v4-flash"},
                        {
                            "id": "deepseek-v4-pro",
                            "samplingParams": {"top_p": 0.9},
                        },
                    ]
                }
            }
        }

        apply_sampling_seed(registry, seed=7)

        models = registry["providers"]["deepseek"]["models"]
        self.assertEqual(models[0]["samplingParams"], {"seed": 7})
        self.assertEqual(
            models[1]["samplingParams"], {"top_p": 0.9, "seed": 7}
        )
        self.assertNotIn("temperature", models[0]["samplingParams"])

    def test_sampling_params_do_not_mutate_unrelated_registry_fields(self) -> None:
        registry = {"providers": {"deepseek": {"baseUrl": "https://example.invalid"}}}
        apply_sampling_seed(registry, seed=1)
        self.assertEqual(
            registry, {"providers": {"deepseek": {"baseUrl": "https://example.invalid"}}}
        )


if __name__ == "__main__":
    unittest.main()
