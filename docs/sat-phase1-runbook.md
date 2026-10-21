# SAT-GP Phase 1 Linux runbook

Phase 1 在 EdgeBench 的单个 VLIW 任务 `vliw_kernel_optimization` 上运行 A1–A5，使用官方 hidden Judge，目标是把 Phase 0 的机制信号转成可归因的正式硬分数比较。

- 模型：`deepseek/deepseek-v4-flash`，由 Pi 调用；
- 方法：`goal-plus-pi-provider`；
- 每个 campaign：`T=7200`、`K=4`、`C=1`、`R=1`；
- 每个 arm 跑 3 个独立 campaign（r1/r2/r3），因此 R 不能用 C 代替；
- 总共 5 arms × 3 campaigns = 15 个 EdgeBench campaign。

Phase 1 只跑 VLIW 这一题，不跑 EdgeBench 全部 50 题。

## 0. 前置条件

- Linux x86_64；
- Docker 可用，且已能运行 EdgeBench Work/Judge 镜像；
- Python 3.12 + `uv`；
- Pi CLI 可用，且 Pi 的 DeepSeek provider 能调用 `deepseek-v4-flash`；
- `DEEPSEEK_API_KEY` 可用；
- SAT Goal Plus 源：`muyuan/plugins/goal-plus` 的 `sat` 分支，包含 `d182adb62393fc54ae5a47bdfb48c87285fead07`（A2 verifier-off 修复和 SAT steering adaptive_search overlay 修复）。

EdgeBench 的 provider 解析使用 **Pi 的 built-in `deepseek` provider**，所以 profile 里的模型是：

```text
deepseek/deepseek-v4-flash
```

如果 DeepSeek 不是官方 endpoint，需要改用非 builtin provider（例如 `deepseek-proxy/deepseek-v4-flash`），并在 Pi `models.json` 里登记 provider、model、`baseUrl` 和 `$DEEPSEEK_API_KEY`。不要修改 EdgeBench controller 去猜 endpoint。

## 0b. Codex + GPT-5.6-sol 变体

同一套 A1–A5 也提供 Codex profile/preset：

```text
edgebench-vliw-sat-a1-codex-2h
...
edgebench-vliw-sat-a5-codex-2h
```

对应 profile：

```text
vliw-sat-a1-codex-gpt-5-6-sol-2h-k4-c1.json
...
vliw-sat-a5-codex-gpt-5-6-sol-2h-k4-c1.json
```

冻结合同：

```text
method=goal-plus-codex
model=gpt-5.6-sol
reasoning_effort=medium
T=7200, K=4, C=1, R=1
```

Codex 变体不需要 `DEEPSEEK_API_KEY` 或 Pi provider；需要宿主 Codex 鉴权和 Goal Plus MCP probe 通过。

```bash
export SFORGE_GOAL_PLUS_SOURCE_DIR=/path/to/muyuan/plugins/goal-plus
export SFORGE_GOAL_PLUS_EXPECTED_REF=d182adb

python3 scripts/bench.py check --preset edgebench-vliw-sat-a1-codex-2h
python3 scripts/bench.py setup --preset edgebench-vliw-sat-a1-codex-2h
python3 scripts/bench.py plan  --preset edgebench-vliw-sat-a1-codex-2h
```

串行跑 A1–A5（每个 arm 一次；正式 R=3 时重复 3 次）：

```bash
for arm in a1 a2 a3 a4 a5; do
  python3 scripts/bench.py launch \
    --preset "edgebench-vliw-sat-${arm}-codex-2h" \
    --campaign-id "edgebench-vliw-sat-${arm}-codex-r1"
done
```

每个 campaign 到终态后再 `status` 和 `finish`；不要并发跑多个 campaign。`scripts/run_sat_a1_a5.sh` 目前默认使用 Pi preset，Codex 变体请按上面的 preset 名调用。

## 1. 设置环境

```bash
cd /path/to/bench-goal-plus

export SFORGE_GOAL_PLUS_SOURCE_DIR=/path/to/muyuan/plugins/goal-plus
export SFORGE_GOAL_PLUS_EXPECTED_REF=d182adb
export DEEPSEEK_API_KEY="..."

python3 scripts/bench.py catalog
```

确认存在：

```text
edgebench-vliw-sat-a1-2h
...
edgebench-vliw-sat-a5-2h
```

并确认 catalog 中 `edgebench-native` 支持 `goal-plus-pi-provider`。

## 2. 资产检查、setup、doctor

EdgeBench 声明了 `local_asset_inventory=true`，必须先做只读 inventory 检查，再 provision：

```bash
python3 scripts/bench.py check --preset edgebench-vliw-sat-a1-2h
```

如果只报告缺失 image/tag，不要用 `internet=true` 或 host evaluator 绕过；确认后再执行 setup/provision：

```bash
python3 scripts/bench.py setup --preset edgebench-vliw-sat-a1-2h
```

`setup` 会运行 EdgeBench 的 provision 和 doctor。必须确认 doctor 的以下门禁通过：

```text
network:api-only-policy
network:offline-task-isolation
```

以及 Work/Judge 镜像、Judge 端口和 Pi provider 端点都完整。

## 3. 先 plan A1，检查合同

```bash
python3 scripts/bench.py plan --preset edgebench-vliw-sat-a1-2h
```

确认：

- `methods = goal-plus-pi-provider`；
- `model = deepseek/deepseek-v4-flash`；
- `T=7200`、`K=4`、`C=1`、`R=1`；
- `worker_runtime_seconds=6600`；
- `goal-plus-source` 是 external `sat` 分支，commit 为 `d182adb62393fc54ae5a47bdfb48c87285fead07`；
- 命令里是 `artifact_only`、`/goal-plus`，且没有 `internet=true`；
- `GOAL_PLUS_CONTROLLER_EXPERIMENT` 会进入 EdgeBench Goal Plus cell env。

启动前确认块：

```text
T=7200：每条 task trajectory / Goal Plus Search 的墙钟探索预算
K=4：Goal Plus 主会话启动 4 个共享 Search 的 internal subagents
C=1：一个 campaign 同时只运行 1 个 task cell
R=1：单个 campaign 一次独立重复；每个 arm 共跑 3 个 campaign
method=goal-plus-pi-provider（Goal Plus + Pi provider）
模型=deepseek/deepseek-v4-flash
方法运行时源码=external；ref/branch=sat；HEAD=d182adb62393fc54ae5a47bdfb48c87285fead07
单个 cell 拓扑=1 个 outer Goal Plus session + 4 个 internal subagents
同时运行规模=K×C=4×1=4
总 cells=15（5 arms × 3 campaigns，每题 1 个 cell）
```

确认后再 launch。

## 4. 启动 15 个 campaign

EdgeBench native runner 支持 detach；`launch` 会启动 campaign，不会像 common-matrix 一样占用前台。**不要并发跑多个 campaign**，否则 Judge 端口和容器资源会互相干扰。

推荐使用仓库脚本，它会：

- 先 check/setup/plan；
- 用 `bench.py status` 的 `runner.terminal` 判断终态，而不是只读 `campaign.json`；
- 等 controller 真正退出后再 `finish`；
- 遇到终态但仍报 running 的 race 时重新等待并重试 `finish`。

```bash
chmod +x scripts/run_sat_a1_a5.sh

# 先空跑检查命令链
scripts/run_sat_a1_a5.sh --runner edgebench --repeats 3 --dry-run

# 正式跑 A1-A5，每个 arm 3 个独立 campaign
scripts/run_sat_a1_a5.sh --runner edgebench --repeats 3
```

如果只需要单次 A1–A5：

```bash
scripts/run_sat_a1_a5.sh --runner edgebench --repeats 1
```

常用选项：

```text
--arms "a1 a2 a3"       只跑部分 arm
--skip-setup            已 setup 过时跳过 check/setup
--poll-seconds 30       状态轮询间隔
--timeout-seconds 43200 单个 campaign 等待上限（默认 12h）
--prefix NAME           campaign-id 前缀
```

local-vliw 的 A1–A5 矩阵也可以用同一个脚本：

```bash
scripts/run_sat_a1_a5.sh --runner local --repeats 1
```

每个 EdgeBench campaign 是 2h exploration + closeout/finalization；`--repeats 3` 共 15 个 campaign，串行约 30 小时以上。不要为了缩短时间并发启动多个 campaign。

## 5. 监控与归档

```bash
python3 scripts/bench.py status \
  --campaign runs/edgebench/edgebench-vliw-sat-a1-r1
```

确认：

- cell 到终态；
- `completion_evidence.passed=true`；
- `official_edgebench_comparable=true`；
- Goal Plus worker/verifier/Judge trajectory 都有证据。

到终态后归档：

```bash
python3 scripts/bench.py finish \
  --campaign runs/edgebench/edgebench-vliw-sat-a1-r1
```

`finish` 生成 `comparison.json`、native workbook 和统一 report。不要直接改 native artifact。

如果 campaign 变成 `partial`，保留现状并报告缺失证据；不要重跑覆盖同一个 campaign。

## 6. 跨 arm 汇总

每个 campaign 都 finish 后，跑 Phase 1 汇总：

```bash
python3 scripts/sat_edgebench_summary.py \
  --campaign A1=runs/edgebench/edgebench-vliw-sat-a1-r1 \
  --campaign A1=runs/edgebench/edgebench-vliw-sat-a1-r2 \
  --campaign A1=runs/edgebench/edgebench-vliw-sat-a1-r3 \
  --campaign A2=runs/edgebench/edgebench-vliw-sat-a2-r1 \
  --campaign A2=runs/edgebench/edgebench-vliw-sat-a2-r2 \
  --campaign A2=runs/edgebench/edgebench-vliw-sat-a2-r3 \
  --campaign A3=runs/edgebench/edgebench-vliw-sat-a3-r1 \
  --campaign A3=runs/edgebench/edgebench-vliw-sat-a3-r2 \
  --campaign A3=runs/edgebench/edgebench-vliw-sat-a3-r3 \
  --campaign A4=runs/edgebench/edgebench-vliw-sat-a4-r1 \
  --campaign A4=runs/edgebench/edgebench-vliw-sat-a4-r2 \
  --campaign A4=runs/edgebench/edgebench-vliw-sat-a4-r3 \
  --campaign A5=runs/edgebench/edgebench-vliw-sat-a5-r1 \
  --campaign A5=runs/edgebench/edgebench-vliw-sat-a5-r2 \
  --campaign A5=runs/edgebench/edgebench-vliw-sat-a5-r3 \
  --json-out runs/edgebench/edgebench-vliw-sat-phase1.json \
  --markdown-out runs/edgebench/edgebench-vliw-sat-phase1.md
```

输出包含：

- 每个 arm 的 official score mean/SD、raw score、completion；
- SAT verifier records、steering applied、shared-cache records、peer Evidence reads、collaboration events；
- `A2-A1`、`A3-A2`、`A4-A3`、`A5-A4`、`A5-A1` 的配对差值、bootstrap 95% CI、近似 MDE；
- A1 headroom（score mean/SD/min/max，ceiling=100）。

归因注意：A1/A2 是 `parallel_loops`；A3/A4/A5 是 `adaptive_search` 且 `allocation=None`。A3 是 adaptive 控制臂（verifier shadow），`A4-A3` 才是 steering 的干净增量；`A4-A2` 混合了 orchestration 和 steering，不作因果归因。

## 7. Gate 2

进入 Phase 2 前检查：

1. 15 个 campaign 的 completion evidence 都通过；
2. A1 的 official score 未完全饱和，且 3 次 campaign 有可测方差；
3. A2/A3/A4/A5 的 SAT 机制计数非零：verifier records、steering applied、shared-cache records、peer reads、collaboration events；
4. 配对 CI/MDE 能支持或否定至少一个 arm 的硬收益；
5. 所有 campaign 的 protocol classification 和 official comparability 可解释。

如果 A1 已在 ceiling，或机制计数为零，停止 Phase 2，先调整任务/预算/协议；不要继续堆 A5。

## 8. 关键文件

```text
experiments/edgebench/profiles/vliw-sat-a1-pi-deepseek-v4-flash-2h-k4-c1.json
...
experiments/edgebench/profiles/vliw-sat-a5-pi-deepseek-v4-flash-2h-k4-c1.json

experiments/edgebench/controller/preparation.py
experiments/edgebench/controller/runtime.py
experiments/edgebench/controller/sat_evidence.py
bench_goal_plus/sat_edgebench_analysis.py
scripts/sat_edgebench_summary.py
```

`pi_package_version` 当前 profile 固定为 `0.83.0`。正式跑之前必须确认这个 Pi 版本能加载 `deepseek/deepseek-v4-flash`；如果你的 Pi 版本不同，把 5 个 profile 的 `pi_package_version` 改成实际验证过的精确版本，不要留 `latest`。
