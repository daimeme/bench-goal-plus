"""Cross-campaign analysis for the EdgeBench VLIW SAT Phase 1 matrix."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from bench_goal_plus.sat_analysis import bootstrap_ci


SAT_ARMS = ("A1", "A2", "A3", "A4", "A5")
SAT_CONTRASTS = (("A1", "A2"), ("A2", "A3"), ("A3", "A4"), ("A4", "A5"), ("A1", "A5"))


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def _mde_80(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return 2.8 * statistics.stdev(values) / math.sqrt(len(values))


def load_edgebench_campaign(path: str | Path) -> dict[str, Any]:
    campaign_dir = Path(path).expanduser().resolve()
    comparison_path = campaign_dir / "comparison.json"
    if not comparison_path.is_file():
        raise FileNotFoundError(
            f"EdgeBench comparison.json not found: {comparison_path}; run finish first"
        )
    payload = json.loads(comparison_path.read_text(encoding="utf-8"))
    cells = payload.get("cells") or []
    if not isinstance(cells, list) or len(cells) != 1 or not isinstance(cells[0], dict):
        raise ValueError(
            f"SAT EdgeBench campaign must contain exactly one VLIW cell: {comparison_path}"
        )
    cell = cells[0]
    best = cell.get("best") or {}
    sat = cell.get("sat") or ((best.get("goal_plus") or {}).get("sat") or {})
    mode = str(
        cell.get("sat_experiment_mode")
        or payload.get("experiment_mode")
        or ""
    ).upper()
    if mode not in SAT_ARMS:
        raise ValueError(
            f"campaign has no SAT experiment_mode (A1-A5): {comparison_path}"
        )
    return {
        "campaign_id": payload.get("campaign_id") or campaign_dir.name,
        "campaign_dir": str(campaign_dir),
        "mode": mode,
        "task_id": cell.get("task_id"),
        "method": cell.get("method"),
        "model": cell.get("model"),
        "reasoning_effort": cell.get("reasoning_effort"),
        "wall_time_seconds": cell.get("wall_time_seconds"),
        "score": _number(best.get("edgebench_score")),
        "raw_score": _number(best.get("raw_score")),
        "completion_evidence_passed": bool(
            (cell.get("completion_evidence") or {}).get("passed")
        ),
        "official_comparable": bool(cell.get("official_edgebench_comparable")),
        "valid_trajectories": int(cell.get("valid_trajectories") or 0),
        "sat": sat if isinstance(sat, dict) else {},
        "source": payload,
    }


def edgebench_phase1_summary(
    campaigns: Mapping[str, Iterable[str | Path]],
    *,
    bootstrap_iterations: int = 2000,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    loaded: dict[str, list[dict[str, Any]]] = {}
    for mode, paths in campaigns.items():
        arm = str(mode).upper()
        if arm not in SAT_ARMS:
            raise ValueError(f"unsupported SAT arm: {mode!r}")
        loaded[arm] = [load_edgebench_campaign(path) for path in paths]

    arms: dict[str, Any] = {}
    sat_fields = (
        "verifier_records",
        "verifier_completed",
        "steering_attempts",
        "steering_applied",
        "steering_shadow_evaluations",
        "shared_cache_records",
        "shared_cache_candidate_writer_count",
        "global_evidence_reads",
        "global_evidence_peer_reads",
        "collaboration_events",
        "collaboration_certificates",
    )
    for arm, items in sorted(loaded.items()):
        scores = [item["score"] for item in items if item["score"] is not None]
        raw_scores = [
            item["raw_score"] for item in items if item["raw_score"] is not None
        ]
        sat_totals: dict[str, float] = {}
        for field in sat_fields:
            sat_totals[field] = sum(
                float((item["sat"] or {}).get(field) or 0) for item in items
            )
        arms[arm] = {
            "campaign_count": len(items),
            "scored_count": len(scores),
            "score_mean": _mean(scores),
            "score_stdev": _stdev(scores),
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "raw_score_mean": _mean(raw_scores),
            "completion_pass_count": sum(
                1 for item in items if item["completion_evidence_passed"]
            ),
            "official_comparable_count": sum(
                1 for item in items if item["official_comparable"]
            ),
            "sat_totals": sat_totals,
            "campaigns": [
                {
                    key: item[key]
                    for key in (
                        "campaign_id",
                        "campaign_dir",
                        "mode",
                        "score",
                        "raw_score",
                        "completion_evidence_passed",
                        "official_comparable",
                        "valid_trajectories",
                    )
                }
                for item in items
            ],
        }

    paired: dict[str, Any] = {}
    for base_arm, arm in SAT_CONTRASTS:
        base_items = loaded.get(base_arm) or []
        arm_items = loaded.get(arm) or []
        differences = []
        pairs = []
        for index, (base, candidate) in enumerate(zip(base_items, arm_items), start=1):
            if base["score"] is None or candidate["score"] is None:
                continue
            difference = candidate["score"] - base["score"]
            differences.append(difference)
            pairs.append(
                {
                    "repeat": index,
                    "base_campaign": base["campaign_id"],
                    "arm_campaign": candidate["campaign_id"],
                    "base_score": base["score"],
                    "arm_score": candidate["score"],
                    "difference": difference,
                }
            )
        paired[f"{arm} - {base_arm}"] = {
            "paired_count": len(differences),
            "mean_difference": _mean(differences),
            "stdev_difference": _stdev(differences),
            "bootstrap_ci95": bootstrap_ci(
                differences,
                iterations=bootstrap_iterations,
                seed=bootstrap_seed,
            ),
            "mde_80pct_approx": _mde_80(differences),
            "pairs": pairs,
        }

    a1 = arms.get("A1") or {}
    return {
        "schema_version": 1,
        "benchmark": "edgebench-vliw",
        "task_id": "vliw_kernel_optimization",
        "arms": arms,
        "paired": paired,
        "headroom": {
            "a1_score_mean": a1.get("score_mean"),
            "a1_score_stdev": a1.get("score_stdev"),
            "a1_score_min": a1.get("score_min"),
            "a1_score_max": a1.get("score_max"),
            "ceiling": 100.0,
        },
        "notes": [
            "Scores are official EdgeBench 0-100 values from comparison.json.",
            "A1/A2 use parallel_loops; A3-A5 use adaptive_search with allocation disabled.",
            "A3 is the adaptive verifier-shadow control; A3 - A2 includes the orchestration switch and is not a score gain.",
            "A4 - A3 isolates steering, A5 - A4 isolates the fixed protocol, and A5 - A1 is the total effect.",
            "Paired contrasts align campaigns by list order (r1/r2/r3) for each arm.",
            "SAT totals are summed across the arm's campaigns.",
        ],
    }


def render_phase1_markdown(summary: Mapping[str, Any]) -> str:
    def fmt(value: Any) -> str:
        return f"{value:.6g}" if isinstance(value, (int, float)) else "n/a"

    lines = [
        "# EdgeBench VLIW SAT Phase 1 summary",
        "",
        f"Task: {summary.get('task_id')}",
        "",
        "## Arms",
        "",
        "| Arm | Campaigns | Score mean | Score SD | Raw mean | Completion | SAT verifier | Steering applied | Cache records | Peer reads | Collaboration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, item in (summary.get("arms") or {}).items():
        sat = item.get("sat_totals") or {}
        lines.append(
            f"| {arm} | {item['campaign_count']} | {fmt(item.get('score_mean'))} | "
            f"{fmt(item.get('score_stdev'))} | {fmt(item.get('raw_score_mean'))} | "
            f"{item['completion_pass_count']}/{item['campaign_count']} | "
            f"{sat.get('verifier_records', 0)} | {sat.get('steering_applied', 0)} | "
            f"{sat.get('shared_cache_records', 0)} | "
            f"{sat.get('global_evidence_peer_reads', 0)} | "
            f"{sat.get('collaboration_events', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Paired effects",
            "",
            "| Contrast | Pairs | Mean difference (pp) | Bootstrap 95% CI | MDE (80% power) |",
            "|---|---:|---:|---|---:|",
        ]
    )
    for contrast, item in (summary.get("paired") or {}).items():
        ci = item.get("bootstrap_ci95")
        ci_text = (
            f"[{ci[0]:.6g}, {ci[1]:.6g}]"
            if isinstance(ci, list) and len(ci) == 2
            else "n/a"
        )
        lines.append(
            f"| {contrast} | {item['paired_count']} | "
            f"{fmt(item.get('mean_difference'))} | {ci_text} | "
            f"{fmt(item.get('mde_80pct_approx'))} |"
        )
    headroom = summary.get("headroom") or {}
    lines.extend(
        [
            "",
            "## Headroom (A1)",
            "",
            f"- score mean: {headroom.get('a1_score_mean')}",
            f"- score SD: {headroom.get('a1_score_stdev')}",
            f"- min / max: {headroom.get('a1_score_min')} / {headroom.get('a1_score_max')}",
            "",
            "Scores are official EdgeBench 0-100. A3 is a mechanism arm; do not read A3 - A2 as a guaranteed score gain.",
        ]
    )
    return "\n".join(lines) + "\n"
