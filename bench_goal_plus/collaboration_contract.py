"""Controller-owned contract for the post-settlement group deliberation arms.

The upstream Goal Plus runtime reads ``GOAL_PLUS_CONTROLLER_COLLABORATION`` as
JSON and freezes it into ``strategy.collaboration``; the agent's own spec text
cannot opt in or out. This module is the only place that decides which arm a
condition maps to, so a campaign cannot drift from its recorded condition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

COLLABORATION_CONTROLLER_ENV = "GOAL_PLUS_CONTROLLER_COLLABORATION"
COLLABORATION_MODES = ("c0", "c1", "c2")
COLLABORATION_MODE_CONDITIONS = {"c0": "C0", "c1": "C1", "c2": "C2"}
DOSSIER_LEVELS = ("summary", "detailed")
COMBINATION_MODES = ("ensemble", "blackboard", "staged")
DEFAULT_SHAPE: dict[str, Any] = {
    "dossier": "detailed",
    "combination": "ensemble",
    "roster_size": 3,
}

# The bank is frozen upstream; these ids must exist in goal-plus
# domain/collaboration.py. `c1` is the cheapest audit-only arm, `c2` runs the
# whole AIME-2024 bank.
MECHANISTIC_AUDIT = "mechanistic_step_audit"
FULL_BANK_STRATEGIES = (
    "mechanistic_step_audit",
    "weighted_derivation_consensus",
    "minority_reasoning_challenge",
    "divergence_reconciliation",
    "backward_constraint_validation",
    "constraint_inventory_then_solve",
    "independent_solve_then_synthesis",
    "problem_adaptive_method_diversification",
    "suspicious_consensus_challenger",
    "component_recombination_validation",
)

_COLLABORATION_ARMS: dict[str, dict[str, Any]] = {
    "c0": {"mode": "off"},
    "c1": {
        "mode": "advisory",
        "strategy_ids": [MECHANISTIC_AUDIT],
        "max_strategies": 1,
    },
    "c2": {
        "mode": "advisory",
        "strategy_ids": list(FULL_BANK_STRATEGIES),
        "max_strategies": len(FULL_BANK_STRATEGIES),
    },
}


def expected_condition(mode: str) -> str:
    if mode not in COLLABORATION_MODES:
        raise ValueError(f"unsupported collaboration mode: {mode!r}")
    return COLLABORATION_MODE_CONDITIONS[mode]


def collaboration_payload(
    mode: str, shape: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the frozen ``strategy.collaboration`` payload for one arm.

    ``shape`` carries the evidence and conversation knobs (``dossier``,
    ``combination``, ``roster_size``). They are part of the frozen spec, so a
    profile that omits them gets the runtime defaults rather than an implicit
    "same as last time" behaviour.
    """

    if mode not in COLLABORATION_MODES:
        raise ValueError(
            f"unsupported collaboration mode {mode!r}; "
            f"expected one of {', '.join(COLLABORATION_MODES)}"
        )
    payload = dict(_COLLABORATION_ARMS[mode])
    if payload.get("mode") != "off":
        payload.update(validate_deliberation_shape(shape))
    return payload


def validate_deliberation_shape(
    shape: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalise and validate the evidence/conversation knobs."""

    raw = dict(DEFAULT_SHAPE)
    for key, value in dict(shape or {}).items():
        if value is not None:
            raw[key] = value
    dossier = str(raw["dossier"])
    combination = str(raw["combination"])
    try:
        roster_size = int(raw["roster_size"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"roster_size must be an integer, got {raw['roster_size']!r}") from exc
    if dossier not in DOSSIER_LEVELS:
        raise ValueError(
            f"unsupported dossier level {dossier!r}; expected one of "
            + ", ".join(DOSSIER_LEVELS)
        )
    if combination not in COMBINATION_MODES:
        raise ValueError(
            f"unsupported combination {combination!r}; expected one of "
            + ", ".join(COMBINATION_MODES)
        )
    if not 1 <= roster_size <= 3:
        raise ValueError(f"roster_size must be between 1 and 3, got {roster_size}")
    return {"dossier": dossier, "combination": combination, "roster_size": roster_size}


def deliberation_shape(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Read the shape knobs a campaign profile declares."""

    profile = profile or {}
    return validate_deliberation_shape(
        {
            "dossier": profile.get("dossier_level"),
            "combination": profile.get("combination"),
            "roster_size": profile.get("roster_size"),
        }
    )


def collaboration_controller_environment(
    mode: str | None, shape: Mapping[str, Any] | None = None
) -> dict[str, str]:
    """Return the controller env for one arm, or nothing for the baseline."""

    if mode is None or mode == "c0":
        return {}
    payload = collaboration_payload(mode, shape)
    return {
        COLLABORATION_CONTROLLER_ENV: json.dumps(payload, separators=(",", ":"))
    }


def resolve_collaboration_mode(
    condition: Any,
    profile: Mapping[str, Any] | None,
) -> str | None:
    """Resolve the controller-owned arm, rejecting contradictory inputs."""

    condition_mode = getattr(condition, "collaboration_mode", None)
    profile_mode = (profile or {}).get("collaboration_mode")
    if condition_mode and profile_mode and condition_mode != profile_mode:
        raise ValueError(
            f"profile collaboration_mode {profile_mode!r} does not match "
            f"condition mode {condition_mode!r}"
        )
    mode = condition_mode or profile_mode
    if mode is None:
        return None
    if mode not in COLLABORATION_MODES:
        raise ValueError(
            f"unsupported collaboration mode {mode!r}; "
            f"expected one of {', '.join(COLLABORATION_MODES)}"
        )
    if condition is not None:
        expected = expected_condition(mode)
        if getattr(condition, "condition_id", None) != expected:
            raise ValueError(
                f"collaboration mode {mode!r} belongs to condition {expected}, not "
                f"{getattr(condition, 'condition_id', None)!r}"
            )
    return mode


def require_collaboration_controller(goal_plus_root: Path, mode: str) -> None:
    """Fail before prepare when the selected Goal Plus source lacks the overlay."""

    if mode not in COLLABORATION_MODES:
        raise ValueError(f"unsupported collaboration mode: {mode!r}")
    overlay = (
        goal_plus_root
        / "src"
        / "goal_plus"
        / "application"
        / "controller_overlay.py"
    )
    if not overlay.is_file():
        raise RuntimeError(
            "collaboration arms require a Goal Plus source with the controller "
            f"overlay; selected source has no {overlay.relative_to(goal_plus_root)}"
        )
    text = overlay.read_text(encoding="utf-8")
    missing = [
        token
        for token in (
            "CONTROLLER_COLLABORATION_ENV",
            "apply_controller_collaboration_overlay",
        )
        if token not in text
    ]
    if missing:
        raise RuntimeError(
            "selected Goal Plus source has a controller overlay without "
            f"collaboration support (missing {', '.join(missing)})"
        )
    bank = goal_plus_root / "src" / "goal_plus" / "domain" / "collaboration.py"
    if not bank.is_file():
        raise RuntimeError(
            "collaboration arms require Goal Plus domain/collaboration.py "
            "(the SAT strategy bank)"
        )
    if mode == "c0":
        return
    # The controller payload now carries the evidence and conversation knobs;
    # an older source would reject them at freeze, so fail before prepare.
    bank_text = bank.read_text(encoding="utf-8")
    absent = [
        token
        for token in ("dossier", "combination", "roster_size")
        if f"{token}:" not in bank_text
    ]
    if absent:
        raise RuntimeError(
            "selected Goal Plus source has a strategy bank without the "
            f"deliberation shape knobs (missing {', '.join(absent)})"
        )
