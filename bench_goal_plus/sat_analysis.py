"""Pure analysis helpers for the SAT-GP Phase 0 pilot.

The helpers here deliberately avoid importing the campaign controller so they
can be tested and reused without a POSIX host.  They consume the compact run
records produced by ``collect_goal_plus_state`` and the campaign summaries
written by the benchmark campaign controller.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def directional_gain(
    base: float | None,
    candidate: float | None,
    direction: str | None,
) -> float | None:
    """Positive means ``candidate`` is better than ``base``."""

    if base is None or candidate is None:
        return None
    if direction == "maximize":
        return candidate - base
    if direction == "minimize":
        return base - candidate
    return None


def directional_best(
    scores: Iterable[Any],
    direction: str | None,
) -> float | None:
    values = [
        float(value)
        for value in scores
        if _numeric(value) is not None
    ]
    if not values:
        return None
    return max(values) if direction == "maximize" else min(values)


def selection_metrics(
    runs: Iterable[Mapping[str, Any]],
    *,
    seed_score: float | None,
    final_score: float | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Compute candidate coverage and selection loss for one cell.

    ``coverage`` asks whether the candidate pool found something better than
    the seed.  ``selection_loss`` asks how much the selected candidate gave up
    relative to the best candidate.  Both are direction-aware; a positive
    selection loss means the pool contained a better solution than the one
    that was selected.
    """

    run_list = [run for run in runs if isinstance(run, Mapping)]
    if not run_list:
        return {
            "coverage": "unavailable: no Goal Plus run evidence",
            "coverage_gain": None,
            "coverage_achieved": None,
            "selection_loss": None,
            "selection_loss_ratio": None,
            "best_candidate_id": None,
            "best_candidate_score": None,
            "selected_candidate_id": None,
            "selected_process_score": None,
            "final_score": final_score,
            "final_gap_to_best": None,
            "candidate_count": 0,
            "candidate_with_scores": 0,
            "candidate_score_spread": None,
            "selected_best_match": None,
        }

    candidate_scores: dict[str, float] = {}
    selected_scores: dict[str, float] = {}
    selected_ids: dict[str, str] = {}
    for run in run_list:
        run_id = str(run.get("run_id") or "")
        for candidate_id, score in (run.get("candidate_best_scores") or {}).items():
            value = _numeric(score)
            if isinstance(candidate_id, str) and value is not None:
                candidate_scores[f"{run_id}/{candidate_id}"] = value
        selected_id = run.get("selected_candidate_id")
        selected_score = _numeric(run.get("selected_score"))
        if isinstance(selected_id, str) and selected_score is not None:
            selected_ids[run_id] = selected_id
            selected_scores[run_id] = selected_score

    if not candidate_scores:
        return {
            "coverage": "unavailable: no candidate iteration scores",
            "coverage_gain": None,
            "coverage_achieved": None,
            "selection_loss": None,
            "selection_loss_ratio": None,
            "best_candidate_id": None,
            "best_candidate_score": None,
            "selected_candidate_id": None,
            "selected_process_score": None,
            "final_score": final_score,
            "final_gap_to_best": None,
            "candidate_count": len(candidate_scores),
            "candidate_with_scores": 0,
            "candidate_score_spread": None,
            "selected_best_match": None,
        }

    best_score = directional_best(candidate_scores.values(), direction)
    if best_score is None:
        return {
            "coverage": "unavailable: unknown metric direction",
            "coverage_gain": None,
            "coverage_achieved": None,
            "selection_loss": None,
            "selection_loss_ratio": None,
            "best_candidate_id": None,
            "best_candidate_score": None,
            "selected_candidate_id": None,
            "selected_process_score": None,
            "final_score": final_score,
            "final_gap_to_best": None,
            "candidate_count": len(candidate_scores),
            "candidate_with_scores": len(candidate_scores),
            "candidate_score_spread": None,
            "selected_best_match": None,
        }
    best_key = min(
        candidate_scores,
        key=lambda key: (
            candidate_scores[key]
            if direction == "minimize"
            else -candidate_scores[key]
        ),
    )
    best_candidate_id = best_key.split("/", 1)[-1]
    selected_process_score = next(iter(selected_scores.values()), None)
    selected_candidate_id = next(iter(selected_ids.values()), None)
    coverage_gain = directional_gain(seed_score, best_score, direction)
    selection_loss = directional_gain(
        selected_process_score, best_score, direction
    )
    final_gap = directional_gain(final_score, best_score, direction)
    spread = max(candidate_scores.values()) - min(candidate_scores.values())
    denominator = abs(best_score) if best_score else None
    return {
        "coverage": (
            "covered"
            if coverage_gain is not None and coverage_gain > 0
            else "not_covered"
            if coverage_gain is not None
            else "unavailable: missing seed score"
        ),
        "coverage_gain": coverage_gain,
        "coverage_achieved": (
            coverage_gain > 0 if coverage_gain is not None else None
        ),
        "selection_loss": selection_loss,
        "selection_loss_ratio": (
            selection_loss / denominator
            if selection_loss is not None and denominator
            else None
        ),
        "best_candidate_id": best_candidate_id,
        "best_candidate_score": best_score,
        "selected_candidate_id": selected_candidate_id,
        "selected_process_score": selected_process_score,
        "final_score": final_score,
        "final_gap_to_best": final_gap,
        "candidate_count": len(candidate_scores),
        "candidate_with_scores": len(candidate_scores),
        "candidate_score_spread": spread,
        "selected_best_match": (
            selected_process_score is not None
            and selected_process_score == best_score
            if direction in {"minimize", "maximize"}
            else None
        ),
    }


def _stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def bootstrap_ci(
    values: list[float],
    *,
    iterations: int = 2000,
    seed: int = 0,
) -> list[float] | None:
    """Return a deterministic percentile bootstrap 95% CI for the mean."""

    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return [low, high]


def _mde_80(differences: list[float]) -> float | None:
    """Approximate 80%-power minimum detectable effect for alpha=0.05."""

    if len(differences) < 2:
        return None
    sd = statistics.stdev(differences)
    return 2.8 * sd / math.sqrt(len(differences))


def _record_value(record: Mapping[str, Any], *path: str) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def load_campaign_records(campaign_dirs: Iterable[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in campaign_dirs:
        campaign_dir = Path(value).expanduser().resolve()
        summary_path = campaign_dir / "campaign-summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        campaign_id = str(payload.get("campaign_id") or campaign_dir.name)
        for record in payload.get("records") or []:
            if not isinstance(record, dict):
                continue
            enriched = dict(record)
            enriched["_campaign_id"] = campaign_id
            enriched["_campaign_dir"] = str(campaign_dir)
            records.append(enriched)
    return records


def _arm_identity(record: Mapping[str, Any]) -> tuple[str, str, str, Any]:
    return (
        str(record.get("_campaign_id")),
        str(record.get("benchmark_id")),
        str(record.get("task_id")),
        record.get("seed"),
    )


def _record_gain(record: Mapping[str, Any]) -> float | None:
    return _numeric(_record_value(record, "score", "directional_gain"))


def _record_final(record: Mapping[str, Any]) -> float | None:
    return _numeric(_record_value(record, "score", "final"))


def phase0_summary(
    campaign_dirs: Iterable[str | Path],
    *,
    bootstrap_iterations: int = 2000,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    """Summarize Phase 0 pilot campaigns into arm statistics and paired effects."""

    records = load_campaign_records(campaign_dirs)
    campaigns = sorted({str(record.get("_campaign_id")) for record in records})
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_condition[str(record.get("condition") or record.get("method"))].append(record)

    arms: dict[str, Any] = {}
    for condition, selected in sorted(by_condition.items()):
        finals = [value for record in selected for value in [_record_final(record)] if value is not None]
        gains = [value for record in selected for value in [_record_gain(record)] if value is not None]
        coverage = [
            value
            for record in selected
            for value in [_record_value(record, "selection", "coverage_achieved")]
            if isinstance(value, bool)
        ]
        selection_loss = [
            value
            for record in selected
            for value in [_numeric(_record_value(record, "selection", "selection_loss"))]
            if value is not None
        ]
        spread = [
            value
            for record in selected
            for value in [_numeric(_record_value(record, "selection", "candidate_score_spread"))]
            if value is not None
        ]
        sat_metrics = defaultdict(float)
        for record in selected:
            for key, value in ((record.get("sat") or {}).get("metrics") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    sat_metrics[key] += float(value)
        arms[condition] = {
            "cell_count": len(selected),
            "finished_count": sum(1 for record in selected if record.get("status") == "finished"),
            "final_mean": _mean(finals),
            "final_stdev": _stdev(finals),
            "directional_gain_mean": _mean(gains),
            "directional_gain_stdev": _stdev(gains),
            "coverage_count": sum(1 for value in coverage if value),
            "coverage_rate": (sum(1 for value in coverage if value) / len(coverage) if coverage else None),
            "selection_loss_mean": _mean(selection_loss),
            "candidate_score_spread_mean": _mean(spread),
            "sat_metrics": dict(sorted(sat_metrics.items())),
        }

    indexed = {
        (*_arm_identity(record), str(record.get("condition") or record.get("method"))): record
        for record in records
    }
    comparisons = (("A1", "A2"), ("A2", "A3"), ("A1", "A3"))
    paired: dict[str, Any] = {}
    for base_condition, arm_condition in comparisons:
        pairs = []
        for key, base_record in indexed.items():
            if key[-1] != base_condition:
                continue
            arm_record = indexed.get((*key[:-1], arm_condition))
            if arm_record is None:
                continue
            base_gain = _record_gain(base_record)
            arm_gain = _record_gain(arm_record)
            if base_gain is None or arm_gain is None:
                continue
            pairs.append(
                {
                    "campaign_id": key[0],
                    "benchmark_id": key[1],
                    "task_id": key[2],
                    "seed": key[3],
                    "base_gain": base_gain,
                    "arm_gain": arm_gain,
                    "difference": arm_gain - base_gain,
                }
            )
        differences = [item["difference"] for item in pairs]
        paired[f"{arm_condition} - {base_condition}"] = {
            "paired_count": len(pairs),
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
    headroom = {
        "a1_final_mean": a1.get("final_mean"),
        "a1_final_stdev": a1.get("final_stdev"),
        "a1_coverage_rate": a1.get("coverage_rate"),
        "a1_selection_loss_mean": a1.get("selection_loss_mean"),
        "a1_candidate_score_spread_mean": a1.get("candidate_score_spread_mean"),
    }
    return {
        "schema_version": 1,
        "campaign_ids": campaigns,
        "record_count": len(records),
        "arms": arms,
        "paired": paired,
        "headroom": headroom,
        "notes": [
            "Paired differences use score.directional_gain, which is already direction-aware.",
            "A1/A2 use parallel_loops; A3 uses adaptive_search with allocation disabled.",
            "A3 - A2 includes the orchestration switch and is a mechanism check, not a score gain.",
            "mde_80pct_approx is an approximate two-sided alpha=0.05, 80% power planning value.",
            "Coverage=covered means the candidate pool beat the seed before final selection.",
        ],
    }


def render_phase0_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# SAT-GP Phase 0 pilot summary",
        "",
        f"Campaigns: {', '.join(summary.get('campaign_ids') or []) or 'n/a'}",
        "",
        "## Arms",
        "",
        "| Arm | Cells | Finished | Final mean | Final SD | Gain mean | Coverage | Selection loss | Spread |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, arm in (summary.get("arms") or {}).items():
        def fmt(value: Any) -> str:
            return f"{value:.6g}" if isinstance(value, (int, float)) else "n/a"
        lines.append(
            f"| {condition} | {arm.get('cell_count', 0)} | {arm.get('finished_count', 0)} | "
            f"{fmt(arm.get('final_mean'))} | {fmt(arm.get('final_stdev'))} | "
            f"{fmt(arm.get('directional_gain_mean'))} | "
            f"{fmt(arm.get('coverage_rate'))} | "
            f"{fmt(arm.get('selection_loss_mean'))} | "
            f"{fmt(arm.get('candidate_score_spread_mean'))} |"
        )
    lines.extend(
        [
            "",
            "## Paired effects",
            "",
            "| Contrast | Pairs | Mean difference | Bootstrap 95% CI | MDE (80% power) |",
            "|---|---:|---:|---|---:|",
        ]
    )
    for contrast, item in (summary.get("paired") or {}).items():
        ci = item.get("bootstrap_ci95")
        ci_text = (
            f"[{ci[0]:.6g}, {ci[1]:.6g}]" if isinstance(ci, list) and len(ci) == 2 else "n/a"
        )
        def fmt(value: Any) -> str:
            return f"{value:.6g}" if isinstance(value, (int, float)) else "n/a"
        lines.append(
            f"| {contrast} | {item.get('paired_count', 0)} | "
            f"{fmt(item.get('mean_difference'))} | {ci_text} | "
            f"{fmt(item.get('mde_80pct_approx'))} |"
        )
    headroom = summary.get("headroom") or {}
    lines.extend(
        [
            "",
            "## Headroom (A1)",
            "",
            f"- final mean: {headroom.get('a1_final_mean')}",
            f"- final SD: {headroom.get('a1_final_stdev')}",
            f"- coverage rate: {headroom.get('a1_coverage_rate')}",
            f"- selection loss mean: {headroom.get('a1_selection_loss_mean')}",
            f"- candidate score spread mean: {headroom.get('a1_candidate_score_spread_mean')}",
            "",
            "A3 is a recognition arm; do not read A3 - A2 as a hard-score gain.",
        ]
    )
    return "\n".join(lines) + "\n"
