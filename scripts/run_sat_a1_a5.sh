#!/usr/bin/env bash
# Run the SAT A1-A5 matrix sequentially.
#
# EdgeBench mode launches five native campaigns (A1..A5) per repeat and waits
# for each campaign controller to finish before calling finish. Local mode
# launches one common-matrix campaign that already contains A1..A5.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
BENCH="$ROOT/scripts/bench.py"
RUNNER="edgebench"
ARMS="a1 a2 a3 a4 a5"
REPEATS=1
PREFIX=""
POLL_SECONDS=60
TIMEOUT_SECONDS=43200
SKIP_SETUP=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/run_sat_a1_a5.sh [options]

Options:
  --runner edgebench|local   edgebench (default) or local-vliw matrix
  --arms "a1 a2 a3 a4 a5"    EdgeBench arms (default: all five)
  --repeats N                independent repeats (default: 1)
  --prefix NAME              campaign-id prefix
  --poll-seconds N           status poll interval (default: 60)
  --timeout-seconds N        per-campaign wait timeout (default: 43200)
  --skip-setup               skip check/setup (still runs plan)
  --dry-run                  print commands without launching
  -h, --help

EdgeBench required env:
  SFORGE_GOAL_PLUS_SOURCE_DIR
  SFORGE_GOAL_PLUS_EXPECTED_REF=d182adb
  DEEPSEEK_API_KEY

Local required env:
  BENCH_GOAL_PLUS_SOURCE_DIR
  BENCH_GOAL_PLUS_EXPECTED_REF=d182adb
  DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, OPENAI_BASE_URL, OPENAI_API_KEY
  PI_PROVIDER_ID, PI_API, PI_KEY_ENV, PI_BASE_ENV
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

run() {
  if (( DRY_RUN )); then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

while (( $# )); do
  case "$1" in
    --runner) RUNNER="${2:?}"; shift 2 ;;
    --arms) ARMS="${2:?}"; shift 2 ;;
    --repeats) REPEATS="${2:?}"; shift 2 ;;
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="${2:?}"; shift 2 ;;
    --timeout-seconds) TIMEOUT_SECONDS="${2:?}"; shift 2 ;;
    --skip-setup) SKIP_SETUP=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$REPEATS" =~ ^[1-9][0-9]*$ ]] || die "--repeats must be a positive integer"
[[ "$POLL_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "--poll-seconds must be positive"
[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "--timeout-seconds must be positive"
[[ -f "$BENCH" ]] || die "bench.py not found at $BENCH"

if [[ "$RUNNER" == "local" ]]; then
  [[ -n "${BENCH_GOAL_PLUS_SOURCE_DIR:-}" ]] || die "BENCH_GOAL_PLUS_SOURCE_DIR is required"
  [[ -n "${BENCH_GOAL_PLUS_EXPECTED_REF:-}" ]] || die "BENCH_GOAL_PLUS_EXPECTED_REF is required"
  [[ -n "${DEEPSEEK_API_KEY:-}" ]] || die "DEEPSEEK_API_KEY is required"
  [[ -n "${OPENAI_BASE_URL:-}" ]] || die "OPENAI_BASE_URL is required"
  [[ -n "${PI_PROVIDER_ID:-}" && -n "${PI_API:-}" && -n "${PI_KEY_ENV:-}" && -n "${PI_BASE_ENV:-}" ]] \
    || die "PI_PROVIDER_ID, PI_API, PI_KEY_ENV and PI_BASE_ENV are required"
  [[ -n "${!PI_KEY_ENV:-}" ]] || die "env named by PI_KEY_ENV is empty: $PI_KEY_ENV"
  [[ -n "${!PI_BASE_ENV:-}" ]] || die "env named by PI_BASE_ENV is empty: $PI_BASE_ENV"
  PREFIX="${PREFIX:-local-vliw-sat-matrix}"
  PRESET="local-vliw-sat-matrix-2h"
  PI_FLAGS=(--pi-provider-id "$PI_PROVIDER_ID" --pi-api "$PI_API"
    --pi-api-key-env "$PI_KEY_ENV" --pi-api-base-env "$PI_BASE_ENV")
  RUNS_ROOT="runs/benchmark-campaigns"
elif [[ "$RUNNER" == "edgebench" ]]; then
  [[ -n "${SFORGE_GOAL_PLUS_SOURCE_DIR:-}" ]] || die "SFORGE_GOAL_PLUS_SOURCE_DIR is required"
  [[ -n "${SFORGE_GOAL_PLUS_EXPECTED_REF:-}" ]] || die "SFORGE_GOAL_PLUS_EXPECTED_REF is required"
  [[ -n "${DEEPSEEK_API_KEY:-}" ]] || die "DEEPSEEK_API_KEY is required"
  PREFIX="${PREFIX:-edgebench-vliw-sat}"
  PI_FLAGS=()
  RUNS_ROOT="runs/edgebench"
else
  die "--runner must be edgebench or local"
fi

status_json() {
  local campaign="$1"
  local output
  if ! output="$("$PYTHON" "$BENCH" status --campaign "$campaign" 2>/dev/null)"; then
    return 1
  fi
  printf '%s' "$output" | "$PYTHON" -c '
import json, sys
payload = json.load(sys.stdin)
runner = payload.get("runner") or {}
print(json.dumps({
    "terminal": bool(runner.get("terminal")),
    "raw_state": runner.get("raw_state"),
    "state": runner.get("state"),
    "controller_alive": runner.get("controller_alive"),
    "can_finalize": bool(runner.get("can_finalize")),
}))
'
}

wait_campaign() {
  local campaign="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local info
  while (( SECONDS < deadline )); do
    if [[ ! -f "$campaign/campaign.json" ]]; then
      sleep "$POLL_SECONDS"
      continue
    fi
    if info="$(status_json "$campaign" 2>/dev/null)"; then
      local terminal raw_state alive can_finalize
      terminal="$("$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["terminal"])' <<<"$info")"
      raw_state="$("$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["raw_state"])' <<<"$info")"
      alive="$("$PYTHON" -c 'import json,sys; v=json.load(sys.stdin)["controller_alive"]; print("" if v is None else str(v).lower())' <<<"$info")"
      can_finalize="$("$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["can_finalize"])' <<<"$info")"
      printf '  state=%s terminal=%s controller_alive=%s\n' "$raw_state" "$terminal" "${alive:-unknown}"
      if [[ "$terminal" == "True" && "$alive" != "true" ]]; then
        if [[ "$can_finalize" != "True" ]]; then
          printf 'ERROR: campaign is terminal but cannot be finalized: %s\n' "$campaign" >&2
          return 2
        fi
        return 0
      fi
    fi
    sleep "$POLL_SECONDS"
  done
  printf 'ERROR: timed out waiting for terminal campaign: %s\n' "$campaign" >&2
  return 1
}

finish_campaign() {
  local campaign="$1"
  local attempt
  for attempt in 1 2 3; do
    if run "$PYTHON" "$BENCH" finish --campaign "$campaign"; then
      return 0
    fi
    printf 'finish attempt %s failed; re-checking terminal state\n' "$attempt" >&2
    wait_campaign "$campaign" || return 1
    sleep 10
  done
  return 1
}

run_campaign() {
  local preset="$1"
  local campaign_id="$2"
  local campaign_root="$3"
  local campaign="$campaign_root/$campaign_id"
  shift 3 || true

  printf '\n=== %s ===\n' "$campaign_id"
  run "$PYTHON" "$BENCH" plan --preset "$preset" "$@"

  set +e
  if (( DRY_RUN )); then
    run "$PYTHON" "$BENCH" launch --preset "$preset" --campaign-id "$campaign_id" "$@"
    set -e
    return 0
  fi
  "$PYTHON" "$BENCH" launch --preset "$preset" --campaign-id "$campaign_id" "$@"
  local launch_rc=$?
  set -e
  if (( launch_rc != 0 )); then
    printf 'WARNING: launch returned %s; waiting for campaign evidence\n' "$launch_rc" >&2
  fi
  if [[ ! -f "$campaign/campaign.json" ]]; then
    printf 'ERROR: campaign manifest was not created: %s\n' "$campaign" >&2
    return 1
  fi

  wait_campaign "$campaign"
  run "$PYTHON" "$BENCH" status --campaign "$campaign"
  finish_campaign "$campaign"
}

if (( ! SKIP_SETUP )); then
  if [[ "$RUNNER" == "edgebench" ]]; then
    run "$PYTHON" "$BENCH" check --preset "edgebench-vliw-sat-a1-2h"
    run "$PYTHON" "$BENCH" setup --preset "edgebench-vliw-sat-a1-2h"
  else
    run "$PYTHON" "$BENCH" setup --preset "$PRESET" "${PI_FLAGS[@]}"
    run "$PYTHON" "$BENCH" check --preset "$PRESET"
  fi
fi

if [[ "$RUNNER" == "local" ]]; then
  for ((repeat = 1; repeat <= REPEATS; repeat++)); do
    cid="${PREFIX}-r${repeat}"
    run_campaign "$PRESET" "$cid" "$RUNS_ROOT" "${PI_FLAGS[@]}"
  done
else
  # EdgeBench assets are shared by the VLIW profiles; check/setup once above.
  for repeat in $(seq 1 "$REPEATS"); do
    for arm in $ARMS; do
      cid="${PREFIX}-${arm}-r${repeat}"
      run_campaign "edgebench-vliw-sat-${arm}-2h" "$cid" "$RUNS_ROOT"
    done
  done
fi

printf '\nDone. Campaigns are under %s/\n' "$RUNS_ROOT"
