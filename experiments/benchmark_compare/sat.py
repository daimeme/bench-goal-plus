"""Controller-owned SAT-GP experiment arm wiring.

The runtime freezes verifier/steering/cache/protocol from
``GOAL_PLUS_CONTROLLER_EXPERIMENT``.  This module re-exports the shared
contract from :mod:`bench_goal_plus.sat_contract` so common and native runners
cannot drift.
"""

from __future__ import annotations

from bench_goal_plus.sat_contract import (
    SAT_ANNOTATOR_DISABLED_ENV,
    SAT_CONTROLLER_EXPERIMENT_ENV,
    SAT_EXPERIMENT_MODES,
    SAT_GLOBAL_EVIDENCE_MODE_ENV,
    expected_condition,
    expected_global_evidence_mode,
    require_sat_controller_experiment,
    resolve_sat_experiment_mode,
    sat_controller_environment,
)

__all__ = [
    "SAT_ANNOTATOR_DISABLED_ENV",
    "SAT_CONTROLLER_EXPERIMENT_ENV",
    "SAT_EXPERIMENT_MODES",
    "SAT_GLOBAL_EVIDENCE_MODE_ENV",
    "expected_condition",
    "expected_global_evidence_mode",
    "require_sat_controller_experiment",
    "resolve_sat_experiment_mode",
    "sat_controller_environment",
]
