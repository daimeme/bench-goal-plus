# LLM-Verifier E0–E8 实验执行手册（服务器 agent 版）

> 本手册面向**在 Linux 服务器上运行的实验 agent**。目标不是"跑一遍"，
> 而是"产出可被论文引用的、验证过 verifier 确实生效的结果"。
> 每一步都给断言；断言失败时按「失败模式 → 自动修复」表自愈，不中断、不糊弄、不伪造。

---

## 0. 实验目标（唯一验收口径）

### Phase A：E0–E5 评分/排序/策略对照（6 臂 × 3 seed = 18 条）

1. 每个 campaign `completion_evidence_passed == true`，`valid_trajectories == 1`；
2. **e1 / e2 / e3 / e4 / e5 的 `sat.verifier_records > 0`**（"verifier 真的跑了"的硬证据）；
3. **e0 的 `sat.verifier_records == 0`**（hard-only 基线，验证对照成立）；
4. 18 条结果的 `sampling_seed` 与 profile 的 `-s{1,2,3}` 后缀一一对应。

### Phase B：E6–E8 VLIW 反馈控制（3 臂 × 3 seed = 9 条）

| 臂 | verifier 分数 | gate | allocation | steering |
| --- | --- | --- | --- | --- |
| e6 | `robustness`, `headroom`, 6 个 `bottleneck_*` | ✅ on | `vliw_reward_uct/v1` | — |
| e7 | 同上 | ✅ on | `vliw_reward_uct/v1` | `vliw_action_guidance/v1` |
| e8 | 同上 | ❌ off | `vliw_reward_uct/v1` | `vliw_action_guidance/v1` |

Phase B 额外验收（对应审计的三条缺陷）：

1. **门禁生效**：e6/e7 的 LLM 评分次数显著少于 e8（`gated` 记录数 > 0，且 `completed` 记录数 ≈ 真实改动数）；
2. **allocation 方向**：扩张分支的子候选 `delta` 与 `optimization_gain` 同向（消除 +0.404 反转）；
3. **steering 落地**：`sat.steering_applied > 0`，且下一轮 diff 出现 `next_action` 对应的改动；
4. **e8 消融**：e8 与 e7 仅差 gate，用于单独量出门禁的 token/墙钟贡献。

**任何一条不满足，该 campaign 不算数，必须修复后重跑，不得用坏数据凑数。**

---

## 1. 硬性前置（进入执行前，逐项断言）

在 `bench-goal-plus` 根目录执行，每项失败走 §4 的修复表。

| # | 断言 | 检查命令 | 期望 |
|---|---|---|---|
| P1 | bench-goal-plus 在 `llm-verifier-e1e5`，含 base64 修复与 e6–e8 臂 | `git rev-parse --abbrev-ref HEAD; git rev-parse --short HEAD` | `llm-verifier-e1e5`，HEAD ≥ `50cf020`（含 e6–e8 臂；手册自身的后续提交不影响） |
| P2 | goal-plus 源含 overlay + gate + VLIW 策略，且两边 commit 完全对应 | `git -C third_party/muyuan rev-parse --abbrev-ref HEAD; git -C third_party/muyuan rev-parse --short HEAD; git -C third_party/muyuan status --short` | 分支 `llm-verifier-e1e5`，HEAD **精确等于** `b8562d5`，working tree 干净；`controller_overlay.py` 含 `apply_controller_search_strategy_overlay`、`vliw_reward_uct.py` 存在 |
| P3 | `upstreams.json` 的 `goal_plus` 指向私仓 | `python3 -c "import json;u=json.load(open('environment/upstreams.json'))['upstreams']['goal_plus'];print(u['repository'],u['tracking_branch'])"` | `dairenjie/muyuan`、`llm-verifier-e1e5` |
| P4 | 27 个 seed profile 存在（9 臂 × 3 seed） | `ls experiments/edgebench/profiles/vliw-e*-codex-gpt-5-6-sol-2h-k4-c1-s{1,2,3}.json \| wc -l` | `27` |
| P5 | 环境可用（Docker + 鉴权） | `python3 scripts/bench.py check --environment` | 通过，或仅缺非阻塞项并已记录 |

> **P2 是上次踩过的坑**：`third_party/muyuan` 默认可能停在 `master`（旧代码，没有 gate / VLIW 策略），
> 必须显式切到 `llm-verifier-e1e5` 并核对 HEAD 精确等于 `b8562d5`，不能只看分支名。
> 交叉校验：`git -C third_party/muyuan rev-parse HEAD` 必须与 muyuan 仓库推送的 `llm-verifier-e1e5`
> HEAD 逐字节相同；任一不一致就 `git fetch fork llm-verifier-e1e5 && git checkout llm-verifier-e1e5`。

> P2 的 goal-plus checkout 路径以 `resolve_goal_plus_source` 实际解析结果为准；
> 若为 `source_kind=external`，改用 `SFORGE_GOAL_PLUS_SOURCE_DIR` 指向的目录做同样检查。

> `b8562d5` 相对上一基线 `73e04d6` 只改了结算呈现：`vp1.coverage`/`vp1.tradeoff` 等并发价值事实、
> `vp2.density` 的落定窗口（首末时间与候选数）、终态总结的选择与措辞契约（含中文输出与引用纪律）。
> 这些差异只影响终态报告文本，不改变评分、gate 或执行路径，因此各臂之间仍可直接比较；
> 不要因为总结文案不同而判定为行为差异。

---

## 2. 执行流程

### 2.1 Smoke（e0-s1 与 e2-s1）

```bash
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e0-codex-gpt-5-6-sol-2h-k4-c1-s1
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e2-codex-gpt-5-6-sol-2h-k4-c1-s1
```

等两条 `finished` 后，跑 §3.1 的验证脚本。**断言：e0-s1 的 `verifier_records==0` 且 e2-s1 的 `verifier_records>0`。**
- 都满足 → 进入 2.2。
- e2-s1 为 0 → 回到 §4，逐条排查，修好再重跑 e2-s1，**不要带着坏 smoke 继续**。

### 2.2 Phase A：铺满 e0–e5（16 条）

```bash
for arm in e0 e1 e2 e3 e4 e5; do
  for seed in 1 2 3; do
    python3 scripts/bench.py launch --benchmark edgebench \
      --profile vliw-${arm}-codex-gpt-5-6-sol-2h-k4-c1-s${seed}
  done
done
```

### 2.3 Phase B：VLIW 反馈控制（e6–e8，9 条）

先跑 **e7-s1 与 e8-s1** 做 smoke：e7 应有 `gated` 记录（门禁生效），e8 的 `completed` 记录数应明显更多（无门禁）。

```bash
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e7-codex-gpt-5-6-sol-2h-k4-c1-s1
python3 scripts/bench.py launch --benchmark edgebench --profile vliw-e8-codex-gpt-5-6-sol-2h-k4-c1-s1
```

两条通过后铺满：

```bash
for arm in e6 e7 e8; do
  for seed in 1 2 3; do
    python3 scripts/bench.py launch --benchmark edgebench \
      --profile vliw-${arm}-codex-gpt-5-6-sol-2h-k4-c1-s${seed}
  done
done
```

> 若资源不足以并发，按 `C=1` 串行排队；`launch` 会返回 campaign 路径并写 `agent-run.json`，
> 用 `python3 scripts/bench.py status --campaign <path>` 轮询，勿 sleep 空转。

---

## 3. 结果验证（每条 campaign 的 gate）

### 3.1 批量验证脚本

把 27 条 campaign 目录放到 `$RESULTS`（即 `runs/edgebench/<id>` 汇总处），执行：

```python
# verify.py —— 逐 campaign 断言
import json, glob, os, sys
root = sys.argv[1]  # 27 个 campaign 的父目录
bad = []
rows = []
for cj in sorted(glob.glob(os.path.join(root, "*", "comparison.json"))):
    d = json.load(open(cj))
    cell = d["cells"][0]["best"]
    gp = cell["goal_plus"]; sat = gp.get("sat", {})
    arm = os.path.basename(os.path.dirname(cj)).split("-e")[1][:1]
    seed = os.path.basename(os.path.dirname(cj)).rsplit("-s", 1)[1]
    vr = sat.get("verifier_records") or 0
    gated = sat.get("verifier_gated_records") or 0
    ok = (vr > 0) if arm != "e0" else (vr == 0)
    rows.append((arm, seed, cell["raw_score"], round(cell["edgebench_score"], 2), vr, gated, ok))
    if not ok:
        bad.append((arm, seed, vr))
print("arm seed raw edgebench v_records gated ok")
for r in rows: print(" ", *r)
if bad:
    print("FAIL:", bad); sys.exit(1)
print(f"ALL {len(rows)} VALID")
```

**门禁规则**：

- e0 的 `verifier_records` 必须 `== 0`；
- e1–e8 的 `verifier_records` 必须 `> 0`；
- e6/e7 的 `verifier_gated_records` 必须 `> 0`（门禁真的跳过过 LLM）；
- e8 的 `verifier_gated_records` 必须 `== 0`（gate off 对照）；
- `completion_evidence_passed == true`、`valid_trajectories == 1`（从 `comparison.json` 的 `completion_evidence` 取）；
- `raw_score` 为有限数值，`metric_direction=minimize` 下越小越好。

### 3.2 机制交叉验证（不只靠 score）

**Phase A**

- e2（quality-rank）：`frozen_spec.strategy.selection.ranking_keys == ["quality_score","hard_score"]`；
- e3（allocation）：`strategy.adaptive_search.allocation.policy == "swe_search_uct/v1"`；
- e4（steering）：`steering` 策略 + `sat.steering_applied > 0`。

**Phase B**

- e6/e7/e8：`strategy.verifier.gate == (arm != "e8")`；
- e6/e7/e8：`strategy.verifier.scores` 含 `robustness`、`headroom` 与 6 个 `bottleneck_*`；
- e6/e7/e8：`strategy.adaptive_search.allocation.policy == "vliw_reward_uct/v1"`；
- e7/e8：`strategy.adaptive_search.steering.policy == "vliw_action_guidance/v1"`；
- e6：`strategy.adaptive_search.steering` 缺省；
- 审计复跑：`scripts/e4_calibration.py` 与审计脚本对 27 条重算，检查 `optimization_gain` 与子候选 `delta` 同向、`gate` 后 LLM 调用次数下降。

> 若归档没有 frozen_spec / goal-plus-state.tar，见 §4 的 M4（机制数据没落盘就无法证明策略生效）。

---

## 4. 失败模式 → 自动修复对照表

| ID | 失败签名 | 根因 | 自动修复动作 |
|---|---|---|---|
| M1 | `prepare` 报 `require_search_strategy_overlay` 失败 | goal-plus 源缺 overlay | `git -C <goal-plus checkout> fetch origin && git -C <…> checkout llm-verifier-e1e5`（≥ `b8562d5`）；确认 P2 后重试 |
| M2 | e1–e5 `verifier_records==0` 但 e0 也 0，且 campaign 正常完成 | env 值在 `SFORGE_AGENT_EXTRA_ENV` 被逗号切碎（base64 bug 未生效） | 确认 bench ≥ `bf9789c`、goal-plus ≥ `4e1abb8`；重新 `launch` 前先清旧 run；仍 0 则读 frozen_spec 排查 overlay 是否写入 `strategy.verifier` |
| M3 | e1–e5 `verifier_records==0`，且 frozen_spec 里 `strategy.verifier` 为空 | overlay 未应用 | 检查 goal-plus 进程环境是否含 `GOAL_PLUS_CONTROLLER_SEARCH_STRATEGY`（base64）；缺则查 runtime.py 注入路径；记录为**新 bug 待查**，不要硬跑 |
| M4 | `sat.available == false` 或归档缺 `goal-plus-state.tar` / frozen_spec | 归档未包含机制数据 | 修 edgebench-native runner 的归档逻辑，补 `goal-plus-state.tar` + `frozen_spec` 进最终产物；重跑该 cell |
| M5 | campaign `partial` / `failed` / `timed_out` | 环境、鉴权、资源、超时 | 读 `controller.log` / `judge.log` 定位；非代码问题则清障后重跑该 cell；代码问题记录并修复 |
| M6 | `seed` 与 profile 不符 | profile/启动串了 | 重跑该条，确认 `--profile` 用的 `-s{seed}` 与目标一致 |
| M7 | 缺 Docker/鉴权/镜像 | 前置环境 | `python3 scripts/bench.py setup --benchmark edgebench --profile vliw-smoke` + `check --environment`，按报错补齐（不读取/记录凭据内容） |
| M8 | e6/e7 的 `verifier_gated_records == 0`，但 `verifier_records > 0` | 门禁未生效：`strategy.verifier.gate` 为 false 或 `attempt_changed_files` 判定异常 | 读 frozen_spec 确认 `gate: true`；若为 true 仍 0，检查 settlement evidence 的 `attempt_changed_files` 是否恒为空（判定会全部 gated，反而应出现 gated>0）；记录并报告 |

**自愈纪律**：修复只做"定位→改一处→重跑该 campaign"，不得手改 `.gp/`、不得伪造 `verifier_records`、不得把缺失当 0。修不动的记入 `open-issues` 并停下来报告。

---

## 5. 完成标准（Definition of Done）

同时满足才算完成：

- [ ] 27 个 campaign 全部 `finished` 且 `completion_evidence_passed=true`；
- [ ] e0 三 seed `verifier_records==0`，e1–e8 各三 seed `verifier_records>0`；
- [ ] e6/e7 的 `verifier_gated_records>0`，e8 的 `==0`；
- [ ] §3.1 的 `verify.py` 输出 `ALL 27 VALID`；
- [ ] 每条都有 frozen_spec + goal-plus-state 归档，可复核 §3.2 的策略字段；
- [ ] 汇总表（arm×seed → raw_score/edgebench_score/runtime/tokens/evaluator_calls/verifier_records/gated_records）落盘为 `report.md` + `.xlsx`；
- [ ] 审计复跑：`optimization_gain` 与子候选 `delta` 同向，`gate` 后 LLM 调用次数显著下降。

## 6. 交付物

- 27 条 campaign 的 `comparison.json` + `report.md` + 同名 `.xlsx`；
- 一条 `e4-calibration.csv`（`scripts/e4_calibration.py` 产出）；
- 一份 `vliw-feedback-audit.md`：门禁前后 LLM 调用数、allocation 方向、steering 执行率；
- 一份 `open-issues.md`：记录所有修过的故障、未解决项、以及任何"策略未生效"的明确证据。

---

## 附：已知坑（复跑前必须都在）

1. **goal-plus 源指向错 fork**（`upstreams.json` → 已改私仓 `dairenjie/muyuan@llm-verifier-e1e5`）；
2. **pre-flight 缺 overlay 检查**（`require_search_strategy_overlay` → 已加）；
3. **env 值逗号被切碎**（base64url 编码 → bench `bf9789c` + goal-plus `4e1abb8` 已修）；
4. **score-only steering 被 findings 挡住**（`application/steering.py` 只在契约启用 diagnostics 时要求 findings → `36ab3db` 起已修，当前基线 `b8562d5`）；
5. **gated 记录必须仍产生 Record**（`VerifierRecord.outcome="gated"`，不产生 lineage gap → `14eef56` 已加）。

这五点是 e1–e5 全 0 与 VLIW 策略无法生效的直接原因；复跑若再出现 `verifier_records==0`，即为**新 bug**，按 M3 记录并停下来报告。
