import unittest

from bench_goal_plus.pi_models import apply_sampling_params


class DeterministicSamplingTests(unittest.TestCase):
    def test_sampling_temperature_is_projected_to_every_model(self) -> None:
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

        apply_sampling_params(registry, temperature=0.0)

        models = registry["providers"]["deepseek"]["models"]
        self.assertEqual(models[0]["samplingParams"], {"temperature": 0.0})
        self.assertEqual(
            models[1]["samplingParams"], {"top_p": 0.9, "temperature": 0.0}
        )

    def test_sampling_params_do_not_mutate_unrelated_registry_fields(self) -> None:
        registry = {"providers": {"deepseek": {"baseUrl": "https://example.invalid"}}}
        apply_sampling_params(registry, temperature=0.0)
        self.assertEqual(
            registry, {"providers": {"deepseek": {"baseUrl": "https://example.invalid"}}}
        )


if __name__ == "__main__":
    unittest.main()
