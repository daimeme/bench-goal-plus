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

import json
from pathlib import Path
from typing import Any, Mapping

SEARCH_STRATEGY_ENV = "GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY"

DIAGNOSTIC_SCORE_KEYS = [
    "correctness_gap",
    "validation_gap",
    "local_confounder_evidence",
    "discriminating_test_gap",
    "boundary_evidence_strength",
]

# E1-E5 arm ladder (see the LLM-Verifier paper section).
# e0 hard-only baseline; e1 verifier-on/hard-rank; e2 quality-rank (E1);
# e3 allocation (E2); e4 steering (E3); e5 allocation + steering (combined).
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
    """Return the worker environment that transports the arm, or empty."""

    if not strategy:
        return {}
    try:
        payload = json.dumps(dict(strategy), separators=(",", ":"))
    except (TypeError, ValueError) as exc:  # noqa: BLE001 - surfaced verbatim
        raise ValueError(f"search strategy is not JSON-serializable: {exc}") from exc
    return {SEARCH_STRATEGY_ENV: payload}


def require_search_strategy_overlay(goal_plus_root: Path) -> None:
    """Fail before prepare when the selected Goal Plus source lacks the overlay.

    The controller exports ``GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY``, but the
    overlay only takes effect if the selected Goal Plus source carries
    ``apply_controller_search_strategy_overlay``.  Without this check a
    ``search_strategy_arm`` campaign silently runs as a hard-only search and
    produces zero verifier records, so it must fail at prepare time instead.
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
            "search-strategy arms require a Goal Plus source with the controller "
            "search-strategy overlay; the selected source has no "
            f"{overlay.relative_to(goal_plus_root)}"
        )
    text = overlay.read_text(encoding="utf-8")
    missing = [
        token
        for token in (
            "CONTROLLER_SEARCH_STRATEGY_ENV",
            "apply_controller_search_strategy_overlay",
        )
        if token not in text
    ]
    if missing:
        raise RuntimeError(
            "the selected Goal Plus source has a controller overlay without "
            f"search-strategy support (missing {', '.join(missing)}); point the "
            "goal-plus upstream at a revision that includes the search-strategy "
            "overlay before running search_strategy_arm campaigns"
        )


__all__ = [
    "SEARCH_STRATEGY_ENV",
    "DIAGNOSTIC_SCORE_KEYS",
    "SEARCH_STRATEGY_ARMS",
    "resolve_search_strategy_arm",
    "search_strategy_controller_environment",
    "require_search_strategy_overlay",
]
