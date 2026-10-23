"""Project exact host Pi model metadata into isolated benchmark runtimes."""

import json
import os
from pathlib import Path
from typing import Any


def apply_sampling_seed(
    registry: dict[str, Any], *, seed: int = 1
) -> dict[str, Any]:
    """Pin the provider sampling seed without flattening model diversity.

    Pi merges ``samplingParams`` into the provider request.  The registry is
    benchmark-owned and written to the run directory, so this does not mutate
    the user's Pi home or a shared provider catalog.  Temperature is left at
    the model/provider default on purpose: forcing it to zero would make
    concurrent candidates produce nearly identical outputs.
    """

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("sampling seed must be a non-negative integer")
    providers = registry.get("providers")
    if not isinstance(providers, dict):
        return registry
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            params = model.get("samplingParams")
            merged = dict(params) if isinstance(params, dict) else {}
            merged["seed"] = seed
            model["samplingParams"] = merged
    return registry


def native_catalog_model(provider: str, model: str, api: str) -> dict[str, Any]:
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent")))
    catalog_path = agent_dir / "models-store.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    native = next((item for item in (catalog.get(provider) or {}).get("models", [])
                   if item.get("id") == model and item.get("api") == api), None)
    if native is None:
        raise ValueError(f"{provider} model {model!r} is absent from the host Pi catalog; refresh Pi models before launch")
    fields = {"id", "name", "reasoning", "input", "cost", "contextWindow",
              "maxTokens", "thinkingLevelMap", "compat"}
    return {key: value for key, value in native.items() if key in fields}
