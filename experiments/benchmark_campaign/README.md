# Generic benchmark campaign controller

This controller expands the existing standalone artifact runner into a paired
`benchmark x condition x seed` campaign. It does not own worker scheduling or
replace native evaluators. Every cell still uses
`experiments/benchmark_compare/experiment.py`; the campaign layer owns only the
matrix, durable progress, resume behavior, and derived reports.

## Conditions

| Condition | Existing implementation | Sharing boundary |
|---|---|---|
| B0 | Plain Codex with `K=1` | One isolated long-lived lane |
| B1 | Plain Codex with `K>=2` | Independent lanes, best selected only after the deadline |
| B2 | Not implemented | Runtime cannot expose only final/best while hiding intermediate evidence |
| B3 / way2 | Goal Plus Search Space `observe` | Plans and Evidence are shared; reviewer rejection is recorded but not enforced |
| B4 / way1 | Goal Plus Search Space `enforce` | Plans, Evidence, reject/reserve, verifier linkage, and lineage continuation |
| A1 | Goal Plus SAT baseline | No LLM verifier, no steering, no shared cache, isolated Global Evidence |
| A2 | A1 + shared cache (verifier/steering off) | Controller-frozen shared cache; peer Global Evidence readable |
| A3 | A2 + verifier shadow | LLM verifier and text-description scores; steering delivery is `shadow` |
| A4 | A3 + steering apply | Diagnostic steering attempts are actually sent and observed |
| A5 | A4 + SAT-GP v2 | `sat_collaborative_repair/v1` and the `sat-gp/v2` collaboration ledger |

`way0` is also rejected explicitly: Goal Plus does not currently offer the
required combination of hidden plans and disabled Evidence updates with
reject/admission still enabled.

## SAT-GP A1-A5 wiring

The SAT arms are **controller-owned**. The runner sets
`GOAL_PLUS_CONTROLLER_EXPERIMENT={"mode":"aN"}` before the Goal Plus MCP
server freezes the SearchSpec; the runtime overlay then installs the verifier,
steering policy, shared cache, and (for A5) the collaboration protocol. The Goal
prompt only tells the agent not to override those switches. It must not carry
`verifier`, `steering`, or `shared_cache` toggles of its own.

This requires a Goal Plus source that has the controller experiment overlay,
i.e. the `sat` branch of `dairenjie/muyuan` (the reference checkout is
`C:\Users\Forge\muyuan\plugins\goal-plus`). The reference branch must also
include the A2 verifier-off fix and SAT steering adaptive_search overlay fix (`d182adb`): A2 isolates information sharing and
must not turn on the LLM verifier before A3. Select the source explicitly for a
run:

```bash
export BENCH_GOAL_PLUS_SOURCE_DIR=/path/to/muyuan/plugins/goal-plus
export BENCH_GOAL_PLUS_EXPECTED_REF=sat
```

The managed `third_party/muyuan` checkout remains on `master`; `prepare` fails
early with a specific message when the selected source has no overlay, so an
old runtime cannot silently turn every arm into A1.

Run the whole paired matrix in one campaign:

```bash
python3 scripts/bench.py plan --preset local-vliw-sat-matrix-2h
python3 scripts/bench.py launch --preset local-vliw-sat-matrix-2h
```

For the Phase 0 pilot, use `local-vliw-sat-pilot-30m` (A1–A3, T=1800, K=4,
C=1) and run three independent campaigns. `scripts/sat_phase0_summary.py`
aggregates repeats, paired differences, bootstrap CI, and headroom;
`scripts/sat_verifier_audit.py` exports verifier claims and scores a labeled
precision audit. The Linux runbook is `docs/sat-phase0-runbook.md`.

The matrix preset runs A1-A5 once per task/seed, so `campaign-summary.json`
contains non-empty `sat_ablation` pairs and per-arm mechanism counts (verifier
records, steering attempts, Global Evidence reads, collaboration events). A
missing collaboration ledger is reported as `collaboration_status=absent`, not
as zero successful collaboration.

## Lifecycle

Prepare a cheap local matrix without calling a model:

```bash
.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py prepare \
  --campaign-dir runs/benchmark-campaigns/local-vliw-shakedown \
  --benchmarks local-vliw \
  --conditions B0 B1 B3 B4 \
  --seeds 1 2 \
  --wall-time-seconds 360 --concurrency 2 \
  --worker-runtime-seconds 120 --model gpt-5.6-sol
```

Run prepared cells and inspect progress from another shell:

```bash
.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py run \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown \
  --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py status \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown
```

An interrupted invocation preserves every cell and can be run again. Terminal
cells are skipped. The controller stays in the foreground so the existing
runner retains ownership of Codex deadline handling and process closeout.

`campaign-summary.json` and `campaign-summary.md` preserve native metrics and
add directional gain, evaluator/token totals, best-score trajectory/AUC when
evaluator histories are available, threshold timing when `--threshold
BENCHMARK=VALUE` is supplied, Search Space duplicate/Evidence metrics, and a
paired B1-vs-B4 view. Shared-tool reuse remains explicitly unavailable until
Goal Plus persists attributable tool provenance.
