# LLM-Verifier E0–E5 实验执行手册（服务器 agent 版）

> 本手册面向**在 Linux 服务器上运行的实验 agent**。目标不是"跑一遍"，
> 而是"产出可被论文引用的、验证过 verifier 确实生效的 18 条有效结果"。
> 每一步都给断言；断言失败时按「失败模式 → 自动修复」表自愈，不中断、不糊弄、不伪造。

---

## 0. 实验目标（唯一验收口径）

在 EdgeBench VLIW 单任务上，跑满 **6 臂 × 3 seed = 18 个 campaign**，并满足：

1. 每个 campaign `completion_evidence_passed == true`，`valid_trajectories == 1`；
2. **e1 / e2 / e3 / e4 / e5 的 `sat.verifier_records > 0`**（这是"verifier 真的跑了"的硬证据）；
3. **e0 的 `sat.verifier_records == 0`**（hard-only 基线，验证对照成立）；
4. 18 条结果的 `sampling_seed` 与 profile 的 `-s{1,2,3}` 后缀一一对应；
5. 保留每条的 `raw_score / edgebench_score / runtime / tokens / evaluator_calls`，
   供 E1–E5 统计（task×seed 配对）。

**任何一条不满足，该 campaign 不算数，必须修复后重跑，不得用坏数据凑数。**

---

## 1. 硬性前置（进入执行前，逐项断言）

在 `bench-goal-plus` 根目录执行，每项失败走 §4 的修复表。

| # | 断言 | 检查命令 | 期望 |
|---|---|---|---|
| P1 | bench-goal-plus 在 `llm-verifier-e1e5`，含 base64 修复 | `git rev-parse --abbrev-ref HEAD; git log --oneline -1` | `llm-verifier-e1e5`，HEAD ≥ `0a3eab0` |
| P2 | goal-plus 源在含 overlay 的分支，含 base64 解码 | `git -C third_party/muyuan log --oneline -1`（或 `upstreams.json` 指向的 checkout） | HEAD ≥ `f40c3ca`，且 `git -C … grep -l apply_controller_search_strategy_overlay src/goal_plus/application/controller_overlay.py` 非空 |
| P3 | `upstreams.json` 的 `goal_plus` 指向私仓 | `python3 -c "import json;u=json.load(open('environment/upstreams.json'))['upstreams']['goal_plus'];print(u['repository'],u['tracking_branch'])"` | `dairenjie/muyuan`、`llm-verifier-e1e5` |
| P4 | 18 个 seed profile 存在 | `ls experiments/edgebench/profiles/vliw-e*-codex-gpt-5-6-sol-2h-k4-c1-s{1,2,3}.json \| wc -l` | `18` |
| P5 | 环境可用（Docker + 鉴权） | `python3 scripts/bench.py check --environment` | 通过，或仅缺非阻塞项并已记录 |

> P2 的 goal-plus checkout 路径以 `resolve_goal_plus_source` 实际解析结果为准；
> 若为 `source_kind=external`，改用 `SFORGE_GOAL_PLUS_SOURCE_DIR` 指向的目录做同样检查。

---

## 2. 执行流程（18 个 campaign）

对 `arm in e0..e5`、`seed in 1..3`，按序启动。**先跑 e0（基线）和 e2（E1 主对照）各 1 条做 smoke，验证通过再铺满其余 16 条**，避免一次性烧掉 18 条预算。

### 2.1 Smoke（e0-s1 与 e2-s1）

```bash
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e0-codex-gpt-5-6-sol-2h-k4-c1-s1
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e2-codex-gpt-5-6-sol-2h-k4-c1-s1
```

等两条 `finished` 后，跑 §3.1 的验证脚本。**断言：e0-s1 的 `verifier_records==0` 且 e2-s1 的 `verifier_records>0`。**
- 都满足 → 进入 2.2 铺满。
- e2-s1 为 0 → 回到 §4，逐条排查，修好再重跑 e2-s1，**不要带着坏 smoke 继续**。

### 2.2 铺满其余 16 条

```bash
for arm in e0 e1 e2 e3 e4 e5; do
  for seed in 1 2 3; do
    python3 scripts/bench.py launch --benchmark edgebench \
      --profile vliw-${arm}-codex-gpt-5-6-sol-2h-k4-c1-s${seed}
  done
done
```

> 若资源不足以 18 条并发，按 `C=1` 串行排队；`launch` 会返回 campaign 路径并写 `agent-run.json`，
> 用 `python3 scripts/bench.py status --campaign <path>` 轮询，勿 sleep 空转。

---

## 3. 结果验证（每条 campaign 的 gate）

### 3.1 批量验证脚本

把 18 条 campaign 目录放到 `$RESULTS`（即 `runs/edgebench/<id>` 汇总处），执行：

```bash
python3 scripts/e4_calibration.py --campaign <campaign-root> --out /tmp/e4.csv
```

再跑下面的门禁检查（也可写成一次性脚本）：

```python
# verify.py —— 逐 campaign 断言
import json, glob, os, sys
root = sys.argv[1]  # 18 个 campaign 的父目录
bad = []
rows = []
for cj in sorted(glob.glob(os.path.join(root, "*", "comparison.json"))):
    d = json.load(open(cj))
    cell = d["cells"][0]["best"]
    gp = cell["goal_plus"]; sat = gp.get("sat", {})
    arm = os.path.basename(os.path.dirname(cj)).split("-e")[1][:1]
    seed = os.path.basename(os.path.dirname(cj)).rsplit("-s", 1)[1]
    vr = sat.get("verifier_records") or 0
    ok = (vr > 0) if arm != "e0" else (vr == 0)
    rows.append((arm, seed, cell["raw_score"], round(cell["edgebench_score"],2), vr, ok))
    if not ok:
        bad.append((arm, seed, vr))
print("arm seed raw edgebench v_records ok")
for r in rows: print(" ", *r)
if bad:
    print("FAIL:", bad); sys.exit(1)
print("ALL 18 VALID")
```

**门禁规则**：
- e0 的 `verifier_records` 必须 `== 0`；
- e1–e5 的 `verifier_records` 必须 `> 0`；
- `completion_evidence_passed == true`、`valid_trajectories == 1`（从 `comparison.json` 的 `completion_evidence` 取）；
- `raw_score` 为有限数值、`metric_direction=minimize` 下越小越好。

### 3.2 机制交叉验证（E1–E5 不只靠 score）

- e2（quality-rank）：从归档确认 `frozen_spec.strategy.selection.ranking_keys == ["quality_score","hard_score"]`；
- e3（allocation）：确认 `strategy.adaptive_search.allocation.policy == "swe_search_uct/v1"`；
- e4（steering）：确认 `steering` 策略 + `sat.steering_applied` 有记录。

> 若归档没有 frozen_spec / goal-plus-state.tar，见 §4 的 M5（这是上次的教训：机制数据没落盘就无法证明策略生效）。

---

## 4. 失败模式 → 自动修复对照表

| ID | 失败签名 | 根因 | 自动修复动作 |
|---|---|---|---|
| M1 | `prepare` 报 `require_search_strategy_overlay` 失败 | goal-plus 源缺 overlay | `git -C <goal-plus checkout> fetch origin && git -C <…> checkout llm-verifier-e1e5`（或 cherry-pick `f40c3ca`）；确认 P2 后重试 |
| M2 | e1–e5 `verifier_records==0` 但 e0 也 0，且 campaign 正常完成 | env 值在 `SFORGE_AGENT_EXTRA_ENV` 被逗号切碎（base64 bug 未生效） | 确认 bench ≥ `0a3eab0`、goal-plus ≥ `f40c3ca`；重新 `launch` 前先清旧 run；仍 0 则读 frozen_spec 排查 overlay 是否写入 `strategy.verifier` |
| M3 | e1–e5 `verifier_records==0`，且 frozen_spec 里 `strategy.verifier` 为空 | overlay 未应用 | 检查 goal-plus 进程环境是否含 `GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY`（base64）；缺则查 runtime.py 注入路径；记录为**新 bug 待查**，不要硬跑 |
| M4 | `sat.available == false` 或归档缺 `goal-plus-state.tar` / frozen_spec | 归档未包含机制数据 | 修 edgebench-native runner 的归档逻辑，补 `goal-plus-state.tar` + `frozen_spec` 进最终产物；重跑该 cell |
| M5 | campaign `partial` / `failed` / `timed_out` | 环境、鉴权、资源、超时 | 读 `controller.log` / `judge.log` 定位；非代码问题则清障后重跑该 cell；代码问题记录并修复 |
| M6 | `seed` 与 profile 不符 | profile/启动串了 | 重跑该条，确认 `--profile` 用的 `-s{seed}` 与目标一致 |
| M7 | 缺 Docker/鉴权/镜像 | 前置环境 | `python3 scripts/bench.py setup --benchmark edgebench --profile vliw-smoke` + `check --environment`，按报错补齐（不读取/记录凭据内容） |

**自愈纪律**：修复只做"定位→改一处→重跑该 campaign"，不得手改 `.gp/`、不得伪造 `verifier_records`、不得把缺失当 0。修不动的记入 `open-issues` 并停下来报告，不要带着未知状态硬凑 18 条。

---

## 5. 完成标准（Definition of Done）

同时满足才算完成：

- [ ] 18 个 campaign 全部 `finished` 且 `completion_evidence_passed=true`；
- [ ] e0 三 seed `verifier_records==0`，e1–e5 各三 seed `verifier_records>0`；
- [ ] §3.1 的 `verify.py` 输出 `ALL 18 VALID`；
- [ ] 每条都有 frozen_spec + goal-plus-state 归档，可复核 §3.2 的策略字段；
- [ ] 汇总表（arm×seed → raw_score/edgebench_score/runtime/tokens/evaluator_calls/verifier_records）落盘为 `report.md` + `.xlsx`。

## 6. 交付物

- 18 条 campaign 的 `comparison.json` + `report.md` + 同名 `.xlsx`；
- 一条 `e4-calibration.csv`（`scripts/e4_calibration.py` 产出）；
- 一份 `open-issues.md`：记录所有修过的故障、未解决项、以及任何"策略未生效"的明确证据（如 M3 场景）。

---

## 附：本轮已修的三个已知坑（复跑前必须都在）

1. **goal-plus 源指向错 fork**（`upstreams.json` → 已改私仓 `dairenjie/muyuan@llm-verifier-e1e5`）；
2. **pre-flight 缺 overlay 检查**（`require_search_strategy_overlay` → 已加）；
3. **env 值逗号被切碎**（base64url 编码 → bench `0a3eab0` + goal-plus `f40c3ca` 已修）。

这三点是上一轮 18 条全 0 的直接原因；本次复跑若再出现 `verifier_records==0`，即为**第四类新 bug**，按 M3 记录并停下来报告。
