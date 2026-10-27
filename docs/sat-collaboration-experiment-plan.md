# SAT 协作层（P1–P3 群组协作）VLIW 实验方案

本方案针对 `muyuan/plugins/goal-plus` 的 `sat-bank` 分支：候选全部结算后、selection 之前，
插入一次 advisor 性质的三段群组协作（P1 审计 / P2 修复 / P3 综合），策略库为 SAT 论文
AIME-2024 bank 的 10 条策略。协作结论只写 `.gp/runs/<run>/collaboration/`，不改变 hard-score
选择。因此本实验测的不是"更多采样"，而是**识别**（recognition）能否被组织化的对话改善。

## 1. 研究问题

在相同任务、模型、`T/K/C` 与官方 evaluator 下，候选结算后加一次群组协作，能否提高：

- **Q1（主问题）** campaign 的 deadline best `cycles`；
- **Q2** best-so-far 曲线下面积（AUC）与首次达到目标的时间；
- **Q3** 协作裁决与 hard-score 选择的一致率（一致 = 协作没有额外信息；不一致 = 协作在改判）。

以及代价：协作吃掉的 token、调用数与墙钟，是否值得。

## 2. 与 A/N 系列的分工

现有的 A1–A5、N0–N3 属于 sat 分支的 *verifier/audit/steering* 覆盖（每 candidate 结算后触发），
依赖 `GOAL_PLUS_CONTROLLER_EXPERIMENT` overlay。`sat-bank` 分支没有该 overlay，只有一个
**候选池级别、结算后一次**的协作阶段。两者不可混跑，也不构成同一消融轴：

| 维度 | A/N 系列（sat） | C 系列（sat-bank，本方案） |
| --- | --- | --- |
| 触发 | 每个 verifier record | 所有候选结算后一次 |
| 作用对象 | 单 candidate 的 claim/证据 | 整个候选池的横向比较 |
| 影响选择 | 通过 repair/steering 间接影响 | **不影响**，只记录 verdict |
| 控制器通道 | `GOAL_PLUS_CONTROLLER_EXPERIMENT` | `GOAL_PLUS_CONTROLLER_COLLABORATION` |

## 3. 条件设计

三个条件共用 `goal-plus-pi`、`parallel_loops`、same model/reasoning、`T=7200`、`K=4`、`C=1`：

| 条件 | 协作 | 策略 | 每题协作调用量（估） | 作用 |
| --- | --- | --- | ---: | --- |
| **C0** | 无 | — | 0 | 基线：与不加该特性时逐字节相同 |
| **C1** | advisory | `mechanistic_step_audit` 1 条 | 9 | 机制检验：最小、最便宜的审计回路 |
| **C2** | advisory | 完整 10 条 bank | ~90 | 覆盖率检验：多策略组合是否带来额外识别 |

C1 与 C2 的差是"策略条数"的边际价值；C0 与 C1 的差是"有没有协作"的总效应。三者都保持
hard-score 选择不变，所以任何收益只能来自"候选池里的正确答案被更早/更准地识别"。

对照组说明：

- **C0 即对照组**，也是唯一的 baseline；不需要额外 A1，因为 `sat-bank` 上不存在 A1 的
  verifier overlay，C0 就是未修改的 Goal Plus 行为。
- 同模型同预算，不存在"更强模型"替代解释；差异只能来自对话结构。
- 协作发生在 `T` 之后的选择阶段，因此 C1/C2 的额外调用**不计入**候选探索预算。报告必须
  同时给出协作墙钟与 token，避免把"多花的推理时间"读成"更好的搜索"。

## 4. 指标

**主指标（decision-grade）**：官方/隐藏 judge 的 deadline best `cycles`（minimize），以及相对
基线 147734 的改进率。

**曲线指标**：best-so-far AUC（按 evaluator call 索引与按墙钟两种横轴）、首次改进时间、
最终 evaluator call 数（不匹配时作为解释变量）。

**协作机制指标**（来自 `cell.sat.deliberation_*` 与 `.gp/runs/*/collaboration/`）：

- `deliberation_turns` / `deliberation_verdicts` / `completed` / `failed`；
- `deliberation_recommendations`（有推荐候选的 verdict 数）；
- `deliberation_turn_findings`（审计发现的 claim 数）、`deliberation_unresolved_risks`；
- verdict 推荐候选与最终 `selected_candidate_id` 的一致/不一致（离线从二者 JSON 计算）；
- 协作墙钟与 token（从 `invocation`/usage 汇总，缺失记 unavailable，不记 0）。

**成本指标**：worker tokens/cost、主控 tokens/cost、judge 调用数、整体墙钟；C1/C2 另记协作
自身的调用数与耗时。

## 5. 预注册的判定规则

以 3 个独立 campaign（seed 1/2/3，R 用 campaign 而不是 C 表达）为单位：

1. **H1 成立**：C1 的 deadline best 在多数字段上优于 C0（配对差的中位数 > 0），且 3 个
   campaign 中至少 2 个方向一致；同时 C1 的失败/超时率不高于 C0。
2. **H1 不成立但 Q3 高**：协作推荐与选择一致率 ≥ 2/3 且 campaign 间方差大 → 说明当前
   selection 已接近该池子的识别上限，协作没有可改判的空间；记录为"selection-limited"。
3. **C2 vs C1**：只有当 C2 相对 C1 的配对差中位数 > 0 且幅度超过 seed 间离散度时，才声称
   "bank 规模有边际价值"；否则只保留 C1（更便宜）。
4. 任一条协作 verdict `status=failed` 或 `deliberation_status=absent` 的 cell 标记为
   `partial`，不进入主比较，只进入机制统计。

## 6. 运行矩阵

| 阶段 | 预设 | 条件 | 预算 | 目的 |
| --- | --- | --- | --- | --- |
| P0 wiring | `local-vliw-collab-pilot-30m` | C0/C1 | T=1800 | 接线与成本 sanity，不出效应量 |
| P1 主实验 | `local-vliw-collab-matrix-2h` | C0/C1/C2 | T=7200 | 一次 campaign 跑满三个条件 |
| P1 复跑 | `local-vliw-collab-c{0,1,2}-2h` | 单臂 | T=7200 | 逐臂复跑或补齐失败 cell |
| P2 官方判分 | `edgebench-vliw-collab-*`（待接） | C0/C1 | T=7200 | 用 EdgeBench hidden judge 复核 |

命令（在 `bench-goal-plus` 根目录）：

```bash
export SFORGE_GOAL_PLUS_SOURCE_DIR=/path/to/muyuan/plugins/goal-plus
export SFORGE_GOAL_PLUS_EXPECTED_REF=<sat-bank 的 commit>
export DEEPSEEK_API_KEY=...

python3 scripts/bench.py check --preset local-vliw-collab-pilot-30m
python3 scripts/bench.py setup --preset local-vliw-collab-pilot-30m
python3 scripts/bench.py plan  --preset local-vliw-collab-pilot-30m
python3 scripts/bench.py launch --preset local-vliw-collab-pilot-30m

# P1：一次 campaign，三条件 × 1 task × 1 seed；seed 复跑三次得到 R=3
for r in 1 2 3; do
  python3 scripts/bench.py launch --preset local-vliw-collab-matrix-2h \
    --campaign-id "local-vliw-collab-matrix-r${r}"
  python3 scripts/bench.py status --campaign "runs/benchmark-campaigns/local-vliw-collab-matrix-r${r}"
  python3 scripts/bench.py finish --campaign "runs/benchmark-campaigns/local-vliw-collab-matrix-r${r}"
done
```

## 7. 证据与产物

每个 cell：

- `runs/benchmark-campaigns/<campaign>/cells/<cell>/`：controller 日志、`experiment.json`；
- cell 内 Goal Plus workspace：`.gp/runs/<run_id>/collaboration/{turns.jsonl,verdicts/*.json}`；
- `cell.sat.deliberation_*`：turns/verdicts/completed/failed/recommendations 等计数；
- campaign 级 `campaign-summary.json` / `.md` 与（native 路径）`comparison.json`。

判定必须基于 `finish` 后的 `campaign-summary.json` 与 `.gp` 原始 verdict；partial cell 只进机制表。

## 8. 已知限制（必须在报告里写清）

1. **同质三 agent**：三个槽位共用 main 模型，只有角色与提示不同。论文的异质 roster 收益
   不在本实验范围内；因此结果的下界偏保守。
2. **策略文本是数学域**：AIME bank 的措辞（整数答案、约束、方法多样化）迁移到 VLIW 优化，
   靠 runtime preamble 做术语映射；表达力损失未知，C1 只取最域无关的 `mechanistic_step_audit`。
3. **advisory 不改选择**：C 系列的收益上限是"选择质量"，不能超过团队 coverage。若 C0 的
   hard-score 选择本就把最好的候选选出来，协作不可能有增益——这时应报告 Q3 一致率而不是
   "协作无效"。
4. **成本不对称**：C1 每题约 9 次、C2 约 90 次 one-shot 调用，且发生在 `T` 之后。报告必须
   同时给墙钟/token，禁止只报分数。
5. **单题**：只跑 `vliw_kernel_optimization` 一题，结论不能外推成跨 benchmark 排名。
