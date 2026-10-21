# SAT-GP Phase 0 Linux runbook

Phase 0 的目标是：在 `local-vliw` 上用 30 分钟预算跑 A1–A3，估计分数方差、headroom、共享/verifier 机制是否发生，并决定是否值得进入 EdgeBench VLIW 的 Phase 1。

本 runbook 不启动 EdgeBench Docker/Judge；它只使用 `local-vliw`，因此适合先验证接线和机制。

## 0. 前置条件

- Linux x86_64；
- Python 3.12 + `uv`（`repro_env.py` 需要）；
- 仓库根目录下的 `.bench-env/venv` 可创建；
- Pi CLI 在 `PATH` 中，且 `pi` 能访问 DeepSeek provider；启动前先用 `pi` 的 provider 检查命令确认；
- 可用的 Pi runtime + DeepSeek provider 鉴权；
- 模型统一为 `deepseek-v4-flash`，由 Pi 调用；`reasoning_effort=medium`；
- SAT Goal Plus 源：`muyuan/plugins/goal-plus` 的 `sat` 分支，包含 `d182adb`（A2 verifier-off 修复和 SAT steering adaptive_search overlay 修复）。

```bash
cd /path/to/bench-goal-plus
export BENCH_GOAL_PLUS_SOURCE_DIR=/path/to/muyuan/plugins/goal-plus
export BENCH_GOAL_PLUS_EXPECTED_REF=d182adb

export DEEPSEEK_API_KEY="..."
export DEEPSEEK_BASE_URL="https://your-deepseek-endpoint/v1"
# controller 的 api_base 走 OPENAI_BASE_URL；Pi provider 走 DEEPSEEK_*。
export OPENAI_BASE_URL="$DEEPSEEK_BASE_URL"
export OPENAI_API_KEY="$DEEPSEEK_API_KEY"

python3 scripts/bench.py catalog
```

`BENCH_GOAL_PLUS_SOURCE_DIR` 必须指向 `plugins/goal-plus`，不是 `muyuan` 仓库根目录。

Pi provider 参数在 `setup`、`plan`、`launch` 中保持一致：

```bash
export PI_PROVIDER_ID=deepseek
export PI_API=openai-completions
export PI_KEY_ENV=DEEPSEEK_API_KEY
export PI_BASE_ENV=DEEPSEEK_BASE_URL
```

模型名固定为 `deepseek-v4-flash`。如果 provider 不接受 `model_reasoning_effort=medium`，需要单独调整 reasoning 配置，不能让 Pi 静默回退到默认模型。

## 1. 环境检查

```bash
python3 scripts/repro_env.py bootstrap --only goal_plus
python3 scripts/repro_env.py doctor --only goal_plus

python3 scripts/bench.py setup --preset local-vliw-sat-pilot-30m \
  --pi-provider-id "$PI_PROVIDER_ID" --pi-api "$PI_API" \
  --pi-api-key-env "$PI_KEY_ENV" --pi-api-base-env "$PI_BASE_ENV"
python3 scripts/bench.py check --preset local-vliw-sat-pilot-30m
```

如果没有 `uv`，先按仓库 `benchmark-setup` 流程安装；不要用系统 Python 直接跑 controller。

## 2. 查看 pilot 配置

```bash
python3 scripts/bench.py plan --preset local-vliw-sat-pilot-30m \
  --pi-provider-id "$PI_PROVIDER_ID" --pi-api "$PI_API" \
  --pi-api-key-env "$PI_KEY_ENV" --pi-api-base-env "$PI_BASE_ENV"
```

确认输出：

- `conditions = A1 A2 A3`；
- `T=1800`、`K=4`、`C=1`、`R=1`（R=1 是单个 campaign；Phase 0 用 3 个 campaign 作为重复）；
- `worker_runtime_seconds=1500`；
- `shared_cache=false`（A2/A3 的 cache 由 controller overlay 开启，不靠 prompt）。

启动前确认块：

```text
T=1800：每条 Goal Plus search 的墙钟探索预算
K=4：Goal Plus 主会话启动 4 个共享 Search 的 internal subagents
C=1：一个 campaign 同时只运行 1 个 task cell
R=1：单个 campaign 一次独立重复；Phase 0 另跑 3 个 campaign 作为重复
method=goal-plus-pi（Goal Plus + Pi）
方法运行时源码=external；ref/branch=sat；HEAD=d182adb62393fc54ae5a47bdfb48c87285fead07
单个 cell 拓扑=1 个 outer Goal Plus session + 4 个 internal subagents
同时运行规模=K×C=4×1=4
总 cells=每 campaign 3 个 arm cell（A1/A2/A3）；3 个 campaign 共 9 个 cell
```

## 3. 跑 3 个独立 pilot campaign

建议串行跑，避免 CPU/API 竞争影响方差：

```bash
for r in 1 2 3; do
  python3 scripts/bench.py launch \
    --preset local-vliw-sat-pilot-30m \
    --campaign-id "local-vliw-sat-pilot-r${r}" \
    --pi-provider-id "$PI_PROVIDER_ID" --pi-api "$PI_API" \
    --pi-api-key-env "$PI_KEY_ENV" --pi-api-base-env "$PI_BASE_ENV"
done
```

每个 campaign 约 3 × 30 分钟探索（A1/A2/A3 三个 cell）+ closeout；3 个 campaign 总计约 4.5–5 小时。`common-matrix` 不提供 detached controller，`launch` 必须在前台或 tmux/screen 中运行；不要用 `nohup` 或多个 controller 伪造并发。如果某个 campaign 变成 `partial`，先保留现状并检查原因，不要重跑覆盖。

查看状态：

```bash
python3 scripts/bench.py status --campaign runs/benchmark-campaigns/local-vliw-sat-pilot-r1
```

到达终态后归档：

```bash
python3 scripts/bench.py finish --campaign runs/benchmark-campaigns/local-vliw-sat-pilot-r1
```

## 4. 生成 Phase 0 汇总

```bash
python3 scripts/sat_phase0_summary.py \
  --campaign runs/benchmark-campaigns/local-vliw-sat-pilot-r1 \
  --campaign runs/benchmark-campaigns/local-vliw-sat-pilot-r2 \
  --campaign runs/benchmark-campaigns/local-vliw-sat-pilot-r3 \
  --json-out runs/benchmark-campaigns/local-vliw-sat-pilot-phase0.json \
  --markdown-out runs/benchmark-campaigns/local-vliw-sat-pilot-phase0.md
```

输出包含：

- 每个 arm 的 final mean / SD、directional gain、coverage rate、selection loss、candidate spread；
- `A2 - A1`、`A3 - A2`、`A1 - A3` 的配对差值、bootstrap 95% CI、近似 MDE；
- A1 headroom 摘要。

注意：A3 现在是 `adaptive_search` + verifier shadow 的控制臂（`allocation=None`）；`A3 - A2` 同时包含 orchestration 切换，不作为硬分数收益，只用于检查 verifier 是否产生记录。

## 5. 导出并审计 A3 verifier claims

先找到 A3 的 cell 目录（每个 campaign 一个）：

```bash
A3_CELL=runs/benchmark-campaigns/local-vliw-sat-pilot-r1/cells/local-vliw-a3-seed-1
```

导出 claims 和标注模板：

```bash
python3 scripts/sat_verifier_audit.py export \
  --cell-dir "$A3_CELL" \
  --output runs/benchmark-campaigns/local-vliw-sat-pilot-r1/a3-claims.jsonl \
  --labels-template runs/benchmark-campaigns/local-vliw-sat-pilot-r1/a3-labels.jsonl
```

编辑 `a3-labels.jsonl`，把每条 `label` 从 `unknown` 改为：

- `correct`：claim 与硬 evidence 一致；
- `incorrect`：claim 与硬 evidence 不一致；
- `unknown`：无法判断。

Phase 0 只要求抽样 20–30 条 claims（优先 hypothesis/confounder/boundary），不要求全量标注。

然后计算 precision：

```bash
python3 scripts/sat_verifier_audit.py score \
  --claims runs/benchmark-campaigns/local-vliw-sat-pilot-r1/a3-claims.jsonl \
  --labels runs/benchmark-campaigns/local-vliw-sat-pilot-r1/a3-labels.jsonl \
  --output runs/benchmark-campaigns/local-vliw-sat-pilot-r1/a3-audit.json
```

`precision` 是已标注 claims 中 `correct / (correct + incorrect)`；`label_coverage` 是标注覆盖率。recall 需要单独的 ground-truth issue inventory，本阶段不伪造。

注意：当前 A3 verifier 默认沿用 worker 模型，属于同模型自审；Phase 0 的 precision 只用于检查 verifier 是否产生可用信号，不应直接当成 SAT 论文里独立 auditor 的能力。

## 6. 检查单

```bash
# per campaign
python3 - <<'PY'
import json
from pathlib import Path
for r in (1,2,3):
    p=Path(f"runs/benchmark-campaigns/local-vliw-sat-pilot-r{r}/campaign-summary.json")
    s=json.loads(p.read_text())
    print(r, s["state"], [(c["condition"], c.get("selection",{}).get("coverage_rate")) for c in s["condition_summaries"]])
PY
```

Gate 1 通过条件：

- A1 的 3 个 campaign 有可测方差，且 final 未完全饱和；
- A2 的 `shared_cache_records` / candidate writers 非零（cache 写入），以及 `global_evidence_reads` 非零（peer evidence 读取）；当前 SAT 分支没有单独的 cache-read receipt，Phase 2 可补；
- A3 有 verifier records，且抽样 precision 可接受；
- A1/A2/A3 的 coverage/selection loss 能区分“候选池有更好的解但没选中”与“候选池没有更好的解”。

如果 A1 已经接近 ceiling，或 A2/A3 机制没有发生，停止 Phase 1，先调整任务/预算/指标。

## 7. 产物位置

```
runs/benchmark-campaigns/local-vliw-sat-pilot-r{1,2,3}/
  campaign.json
  campaign-summary.json       # per-campaign records, sat, selection
  campaign-summary.md         # human-readable condition/coverage tables
  cells/local-vliw-a{1,2,3}-seed-1/
    experiment.json
    workspace/.gp/runs/...    # verifier/steering/collaboration artifacts
```

Phase 0 完成后，把 `campaign-summary.json`、`phase0-summary.json`、`a3-audit.json` 和 Gate 1 结论一起归档；不要只保留最终分数。
