"""Controller-owned standard Goal Plus search-strategy arms for E1-E5.

This module is the bench-side twin of ``goal_plus``'s
``GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY`` overlay.  Each arm is a frozen
``strategy`` patch: it deterministically enables quality-score ranking,
allocation, or steering so a campaign arm never depends on the Main agent's
instruction following.  The payload is validated by ``goal_plus`` at freeze
time (``ControllerSearchStrategyOverlay``); here we only resolve the named arm
and transport it.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Mapping

SEARCH_STRATEGY_ENV = "GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY"
SHARED_KNOWLEDGE_ENV = "GOAL_PLUS_CONTROLLER_SHARED_KNOWLEDGE"

DIAGNOSTIC_SCORE_KEYS = [
    "correctness_gap",
    "validation_gap",
    "local_confounder_evidence",
    "discriminating_test_gap",
    "boundary_evidence_strength",
]

# VLIW optimizer scores: two qualitative judgments plus six quantified bottleneck
# scores.  The allocation policy derives its own deterministic optimization_gain
# from the snapshot's hard_score, so no verifier score exists for it.
VLIW_OPTIMIZER_SCORE_KEYS = [
    "robustness",
    "headroom",
    "bottleneck_register",
    "bottleneck_memory",
    "bottleneck_dependency",
    "bottleneck_simd_tail",
    "bottleneck_scheduling",
    "bottleneck_hash",
]

# E0-E8 arm ladder (see the LLM-Verifier paper section).
# e0 hard-only baseline; e1 verifier-on/hard-rank; e2 quality-rank (E1);
# e3 allocation (E2); e4 steering (E3); e5 allocation + steering (combined).
# e6 VLIW feedback (gated verifier + reward-driven allocation); e7 adds the
# quantified-bottleneck steering; e8 is the same as e7 with the gate off.
SEARCH_STRATEGY_ARMS: dict[str, dict[str, Any]] = {
    "e0": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
    },
    "e1": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": DIAGNOSTIC_SCORE_KEYS},
    },
    "e2": {
        "initial_context": "fresh",
        "selection": {
            "ranking_keys": ["quality_score", "hard_score"],
            "ranking_tolerance": [0.05, 0.0],
        },
        "verifier": {"scores": []},
    },
    "e3": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": ["progress_reward", "allocation_utility"]},
        "adaptive_search": {"allocation": {"policy": "swe_search_uct/v1"}},
    },
    "e4": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": DIAGNOSTIC_SCORE_KEYS},
        "adaptive_search": {"steering": {"policy": "search_diagnostic_guidance/v1"}},
    },
    "e5": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {
            "scores": ["progress_reward", "allocation_utility", *DIAGNOSTIC_SCORE_KEYS]
        },
        "adaptive_search": {
            "allocation": {"policy": "swe_search_uct/v1"},
            "steering": {"policy": "search_diagnostic_guidance/v1"},
        },
    },
    "e6": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": VLIW_OPTIMIZER_SCORE_KEYS, "gate": True},
        "adaptive_search": {"allocation": {"policy": "vliw_reward_uct/v1"}},
    },
    "e7": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": VLIW_OPTIMIZER_SCORE_KEYS, "gate": True},
        "adaptive_search": {
            "allocation": {"policy": "vliw_reward_uct/v1"},
            "steering": {"policy": "vliw_action_guidance/v1"},
        },
    },
    "e8": {
        "initial_context": "fresh",
        "selection": {"ranking_keys": ["hard_score"], "ranking_tolerance": [0.0]},
        "verifier": {"scores": VLIW_OPTIMIZER_SCORE_KEYS, "gate": False},
        "adaptive_search": {
            "allocation": {"policy": "vliw_reward_uct/v1"},
            "steering": {"policy": "vliw_action_guidance/v1"},
        },
    },
}


def resolve_search_strategy_arm(arm: str | None) -> dict[str, Any] | None:
    """Return the frozen arm payload, or None when no arm is configured."""

    if arm is None:
        return None
    if arm not in SEARCH_STRATEGY_ARMS:
        raise ValueError(
            f"unsupported search strategy arm {arm!r}; "
            f"expected one of {', '.join(SEARCH_STRATEGY_ARMS)}"
        )
    return dict(SEARCH_STRATEGY_ARMS[arm])


def search_strategy_controller_environment(
    strategy: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return the worker environment that transports the arm, or empty.

    The payload is base64url-encoded: ``SFORGE_AGENT_EXTRA_ENV`` is a
    comma-separated ``KEY=VALUE`` string, so a raw JSON payload (which is full
    of commas) would be split apart by SForge and never reach the Goal Plus
    freeze path.  Base64url is comma-free and survives the transport intact.
    """

    if not strategy:
        return {}
    return {SEARCH_STRATEGY_ENV: _encode_overlay(strategy)}


def _encode_overlay(payload: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:  # noqa: BLE001 - surfaced verbatim
        raise ValueError(f"overlay is not JSON-serializable: {exc}") from exc
    return base64.urlsafe_b64encode(raw).decode("ascii")


def goal_plus_feature_environment(
    *,
    search_strategy: Mapping[str, Any] | None = None,
    shared_dir: bool = False,
    shared_knowledge: bool = False,
) -> dict[str, str]:
    """Return the overlays that enable Goal Plus capabilities at freeze time.

    ``shared_dir`` and ``shared_knowledge`` are controller-owned: the campaign
    decides them, never the agent's instruction following.  ``shared_dir``
    rides the search-strategy overlay because both are applied by the same
    freeze hook; ``shared_knowledge`` has its own channel.
    """

    overlay = dict(search_strategy or {})
    if shared_dir:
        overlay["shared_dir"] = {"enabled": True}
    environment = search_strategy_controller_environment(overlay)
    if shared_knowledge:
        environment[SHARED_KNOWLEDGE_ENV] = _encode_overlay({"enabled": True})
    return environment


def require_search_strategy_overlay(
    goal_plus_root: Path,
    *,
    shared_dir: bool = False,
    shared_knowledge: bool = False,
) -> None:
    """Fail before prepare when the selected Goal Plus source lacks the overlay.

    The controller exports ``GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY`` and
    ``GOAL_PLUS_CONTROLLER_SHARED_KNOWLEDGE``, but they only take effect if the
    selected Goal Plus source carries the matching freeze-time hooks.  Without
    this check a campaign silently runs without the arm or without the shared
    capability it claims to enable, so it must fail at prepare time instead.
    """

    overlay = (
        goal_plus_root
        / "src"
        / "goal_plus"
        / "application"
        / "controller_overlay.py"
    )
    if not overlay.is_file():
        raise RuntimeError(
            "search-strategy arms and shared capabilities require a Goal Plus "
            "source with the controller overlay; the selected source has no "
            f"{overlay.relative_to(goal_plus_root)}"
        )
    text = overlay.read_text(encoding="utf-8")
    required = [
        "CONTROLLER_SEARCH_STRATEGY_ENV",
        "apply_controller_search_strategy_overlay",
    ]
    if shared_dir:
        # The strategy overlay must accept the ``shared_dir`` field.
        required.append("shared_dir")
    if shared_knowledge:
        required.extend(
            (
                "CONTROLLER_SHARED_KNOWLEDGE_ENV",
                "apply_controller_shared_knowledge_overlay",
            )
        )
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError(
            "the selected Goal Plus source has a controller overlay without "
            f"the required support (missing {', '.join(missing)}); point the "
            "goal-plus upstream at a revision that includes the controller "
            "overlays before running this campaign"
        )


__all__ = [
    "SEARCH_STRATEGY_ENV",
    "SHARED_KNOWLEDGE_ENV",
    "DIAGNOSTIC_SCORE_KEYS",
    "VLIW_OPTIMIZER_SCORE_KEYS",
    "SEARCH_STRATEGY_ARMS",
    "goal_plus_feature_environment",
    "resolve_search_strategy_arm",
    "search_strategy_controller_environment",
    "require_search_strategy_overlay",
]
