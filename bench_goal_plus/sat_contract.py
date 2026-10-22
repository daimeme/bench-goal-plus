"""Shared SAT-GP experiment-arm contract for common and native runners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

SAT_CONTROLLER_EXPERIMENT_ENV = "GOAL_PLUS_CONTROLLER_EXPERIMENT"
SAT_GLOBAL_EVIDENCE_MODE_ENV = "GOAL_PLUS_GLOBAL_EVIDENCE_MODE"
SAT_ANNOTATOR_DISABLED_ENV = "GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED"
SAT_TASK_REFERENCE_ENV = "GOAL_PLUS_CONTROLLER_TASK_REFERENCE"
SAT_EXPERIMENT_MODES = (
    "a1", "a2", "a3", "a4", "a5",
    "n0", "n0v", "n1", "n2", "n3",
)
SAT_MODE_CONDITIONS = {
    "a1": "A1", "a2": "A2", "a3": "A3", "a4": "A4", "a5": "A5",
    "n0": "N0", "n0v": "N0v", "n1": "N1", "n2": "N2", "n3": "N3",
}


def expected_condition(mode: str) -> str:
    if mode not in SAT_EXPERIMENT_MODES:
        raise ValueError(f"unsupported SAT experiment mode: {mode!r}")
    return SAT_MODE_CONDITIONS[mode]


def expected_global_evidence_mode(mode: str) -> str:
    """A1 and every N arm must not see peer evidence."""

    if mode not in SAT_EXPERIMENT_MODES:
        raise ValueError(f"unsupported SAT experiment mode: {mode!r}")
    return "manual" if mode in {"a2", "a3", "a4", "a5"} else "independent"


def resolve_sat_experiment_mode(
    condition: Any,
    profile: Mapping[str, Any] | None,
) -> str | None:
    """Resolve a controller-owned SAT arm, rejecting contradictions."""

    condition_mode = getattr(condition, "sat_experiment_mode", None)
    profile_mode = (profile or {}).get("experiment_mode")
    if condition_mode and profile_mode and condition_mode != profile_mode:
        raise ValueError(
            f"profile experiment_mode {profile_mode!r} does not match "
            f"condition mode {condition_mode!r}"
        )
    mode = condition_mode or profile_mode
    if mode is None:
        return None
    if mode not in SAT_EXPERIMENT_MODES:
        raise ValueError(
            f"unsupported SAT experiment mode {mode!r}; "
            f"expected one of {', '.join(SAT_EXPERIMENT_MODES)}"
        )
    if condition is not None:
        expected = expected_condition(mode)
        if getattr(condition, "condition_id", None) != expected:
            raise ValueError(
                f"SAT mode {mode!r} belongs to condition {expected}, not "
                f"{getattr(condition, 'condition_id', None)!r}"
            )
    return mode


def sat_controller_environment(mode: str) -> dict[str, str]:
    """Return the controller-owned environment for one SAT arm."""

    if mode not in SAT_EXPERIMENT_MODES:
        raise ValueError(f"unsupported SAT experiment mode: {mode!r}")
    return {
        SAT_CONTROLLER_EXPERIMENT_ENV: json.dumps(
            {"mode": mode}, separators=(",", ":")
        ),
        SAT_GLOBAL_EVIDENCE_MODE_ENV: expected_global_evidence_mode(mode),
        SAT_ANNOTATOR_DISABLED_ENV: "1",
    }


def require_sat_controller_experiment(goal_plus_root: Path, mode: str) -> None:
    """Fail before prepare when the selected Goal Plus source lacks SAT wiring."""

    if mode not in SAT_EXPERIMENT_MODES:
        raise ValueError(f"unsupported SAT experiment mode: {mode!r}")
    overlay = (
        goal_plus_root
        / "src"
        / "goal_plus"
        / "application"
        / "controller_overlay.py"
    )
    if not overlay.is_file():
        raise RuntimeError(
            "SAT A/N requires a Goal Plus source with the controller "
            "experiment overlay; selected source has no "
            f"{overlay.relative_to(goal_plus_root)}"
        )
    text = overlay.read_text(encoding="utf-8")
    missing = [
        token
        for token in (
            "CONTROLLER_EXPERIMENT_ENV",
            "apply_controller_experiment_overlay",
        )
        if token not in text
    ]
    if missing:
        raise RuntimeError(
            "selected Goal Plus source has a controller overlay without SAT "
            f"support (missing {', '.join(missing)})"
        )
    if mode == "a5":
        collaboration = (
            goal_plus_root / "src" / "goal_plus" / "domain" / "collaboration.py"
        )
        if not collaboration.is_file():
            raise RuntimeError(
                "SAT A5 requires Goal Plus domain/collaboration.py for the "
                "sat-gp/v2 ledger"
            )
