# SAT 协作层（P1–P3 群组协作）实验方案 v2

本方案针对 `muyuan/plugins/goal-plus` 的 `sat-bank` 分支：候选全部结算后、selection 之前，
插入一次 advisor 性质的三段群组协作（P1 审计 / P2 修复 / P3 综合），策略库为 SAT 论文
AIME-2024 bank 的 10 条策略。协作结论只写 `.gp/runs/<run>/collaboration/`，不改变 hard-score
选择。

## 1. 前提修正：臂与臂之间测不出协作

v1 打算用 C0/C1/C2 三个 campaign 的官方分数差来判定协作是否有用。这个设计**结构上无法成立**：

- 协作在 settlement 之后运行，只读 dossier，不写候选、不写 verifier、不改 `selected_*`；
- 因此协作对 campaign 的分数贡献**恒为 0**，C0/C1/C2 的分数差全部来自「这次抽到的候选池不同」。

可测的只有两件事：

1. **反事实**：如果采纳 verdict 而不是硬分胜者，官方分数会变成多少；
2. **信息质量**：verdict 里的断言有多少真的落在证据上。

第 2 项可以完全离线测，第 1 项需要每个候选都有 judge 分数（见 §8 前置 3）。

## 2. 研究问题

- **Q1（主问题）** 在同一冻结候选池上，群组协作能否产出**硬分没给出**的正确信息？
  即：被裁决为 `supported` 的断言中，有多少既不重复 dossier 里的排序，也不由单 agent 对照产生。
- **Q2** 证据通道是否是瓶颈？把同一批策略从 `dossier=summary` 换到 `detailed`
  （逐 case + 阈值 + 轨迹 + 结算标志 + patch），断言的可解析率与正确率是否上升。
- **Q3** "组合"是否优于"集成"？`ensemble`（各策略独立）与 `blackboard`/`staged`
  （策略间传递）在同一池子上的差别。
- **Q4** 三 agent 是否值得？`roster_size=1` 的单 agent 对照与 `3` 的差别。
- **Q5（代价）** 每条策略的 turns / tokens / 墙钟，与它独占的、且被裁决为真的断言数之比。

Q3 之前必须先有 Q2 的结论：如果证据通道不打开，加策略只是让更多 agent 重复同一句话。

## 3. 同一池 replay 是在本设计下唯一匹配的对照

deliberation 是 `(已结算池, dossier 级别, 策略集, combination, roster)` 的纯函数，因此可以对
**任意已存档 campaign** 事后重放任意组合：

```bash
cd /path/to/muyuan/plugins/goal-plus
PYTHONPATH=src python scripts/collaboration_replay.py --archive <campaign 的 goal-plus-state.tar> \
    --out /tmp/replay/r6-detailed --preview            # 只渲染证据，不调模型
PYTHONPATH=src python scripts/collaboration_sweep.py \
    --archive <tar> --out /tmp/sweep --dossier summary,detailed \
    --combination ensemble --roster 3 --dry-run        # 网格 + 指纹，不调模型
```

replay 的输出 store 与存档分离，因此绝不会被误当成 campaign 真正产生的 verdict。同一池子的不同
cell 得到逐字节相同的 dossier（按 sha256 校验），这是臂间比较在 campaign 层面做不到的。

## 4. 因子与水平

| 因子 | 水平 | 说明 |
| --- | --- | --- |
| 策略集 | 10 条单策略；`mechanistic_step_audit`；top-3 组合；全 bank | 单策略消融是 Q1/Q5 的主表 |
| `dossier` | `summary`（仅聚合分）、`detailed`（逐 case/阈值/轨迹/标志/patch） | Q2 的自变量 |
| `combination` | `ensemble`、`blackboard`、`staged` | Q3 |
| `roster_size` | `1`、`3` | Q4 |
| 池子 | r6（1201/1289/1362/1413，headroom 7.33%）、旧 r3 的可用池 ×3 | 每个池子内部配对 |

`dossier=summary` 是 v1 行为（仅标量指标），`detailed` 是当前默认。两者对同一池子的渲染互
为超集，diff 只包含新增证据，便于归因。

## 5. 阶段

| 阶段 | 内容 | 新 campaign | 产出 |
| --- | --- | --- | --- |
| **A 筛选** | 10 条策略各自单跑 × 2 池 × 两档 dossier + `roster=1` 对照 | 0 | 每策略：推荐、flip、turns、tokens、`grounding_rate`、`claim_precision`、独占断言数 |
| **B 组合** | top-3 策略 × {ensemble, blackboard, staged} | 0 | Q3：组合是否产生单策略没有的 supported 断言 |
| **C 证据消融** | 阶段 A 的同位策略 × {summary, detailed} | 0 | **Q1/Q2 的决定性对照** |
| **D 在线确认** | 只有 C 出正结果时，跑 1 个 campaign 验证迁移 | 1 | 外部效度 |

A–C 全部在已有存档上完成，建议先只跑 2 个池子（r6 + 1 个旧池）确认口径，再扩到全部。

成本估算：单策略 9 turn × ~21s ≈ 3 分钟；10 策略 ≈ 30 分钟/池/档。两档 × 2 池 ≈ 2 小时，
其中大部分是模型推理时间，远低于 10 个 2h campaign。

## 6. 指标定义

| 指标 | 定义 | 来源 |
| --- | --- | --- |
| `grounding_rate` | `resolved / cited` | verdict.grounding |
| `claim_precision` | `supported / (cited + uncited)` | verdict.adjudication |
| `decision_flip` | `recommended != selected_candidate_id` | verdict + run.json |
| `veto_value` | `judge(recommended) − judge(winner)` | 需要全候选 judge（§8-3） |
| `unique_supported` | 只有该策略/槽位产出、且 adjudication 为 `supported` 的断言数 | turns + verdict |
| `agreement_rate` | 同策略各阶段立场一致的比例 | `projections/collaboration.py` |
| `cost_per_supported` | `tokens / max(unique_supported, 1)` | verdict.strategy_outcomes |

`supported` 是机械判定：finding 的候选必须在池内，`evidence_ref` 必须解析成
`case:<name>` / `iteration:<cand>/<n>` / `diff:<cand>/<path>` / `metric:<key>` /
`verifier:<name>` 且对象真实存在。散文式引用计 `unresolved`，指向不存在证据计 `contradicted`。
它不是"这句话对不对"，而是"这句话有没有落在证据上"——这是唯一不依赖再借一个模型的判据。

## 7. 预注册判定

以池子为单位，同一池子内部配对：

1. **H1（信息新增）**：阶段 C 中，`detailed` 相对 `summary` 的 `claim_precision` 至少有一个池子
   上升 ≥0.10，且 `supported` 断言数上升 ≥2；同时 `unique_supported(roster=1) < unique_supported(roster=3)`。
   两者同时成立才声称"协作产生了新信息，且三 agent 有独立贡献"。
2. **H2（改判价值）**：存在 cell 使 `decision_flip=True` 且 `veto_value > 0`。若所有 cell 的
   flip 都对应 `veto_value ≤ 0`，则协作层的价值上限就是"否决错误选择"，需要更多池子才可能观测到。
3. **H3（组合优于集成）**：`blackboard`/`staged` 的 `unique_supported` 高于 `ensemble` 且
   `claim_precision` 不下降。否则保留 `ensemble`（更便宜、更可归因）。
4. **H4（单 agent 足够）**：若 `roster=1` 与 `roster=3` 在 `claim_precision` 与 `supported` 上无
   差别，则三 agent 只是三倍成本，报告必须写明。
5. 任一 cell `status != completed`（策略超时、host 拒绝）记为 `partial`，只进机制统计，不进主表。

门槛选择理由：`+0.10` 精度与 `+2` 条 supported 是单次 sweep 内可分辨的最小幅度；小于此值的
差别与同策略重复运行的波动同量级（r6 单策略 9 turn 内 3/3 同立场，波动接近 0，但策略间措辞
差异会带来 ±1 条断言的抖动）。

## 8. 前置条件

1. **Goal Plus 版本**：需要 `sat-bank` 上带 `dossier` / `combination` / `roster_size` 与
   `collaboration replay` 的提交。`check` 预检会直接拒绝没有这些字段的源：
   `selected Goal Plus source has a strategy bank without the deliberation shape knobs`。
2. **worker shell**：在线阶段仍需 `"worker_sandbox_mode": "danger-full-access"`，因为 EdgeBench
   容器缺少 unprivileged user namespace，Codex 自带沙箱起不来，worker 的每条 shell 都会失败。
   它只影响 Codex candidate 线程，不改变 `allowed_files` / `denied_files` 与冻结 verifier。
   重跑后先用 `scripts/check_pool_headroom.py <campaign>` 确认池内改判空间（≥2 个改进候选、
   前二相对差 ≤25%），否则 cell 记 partial。
3. **全候选 judge**：`veto_value` 要求每个候选都有官方分数，而现在的 native 路径只 judge 被选中
   的那一个。在此之前 `veto_value` 记 unavailable，`decision_flip` 只作为描述量。
4. **patch 证据**：离线 replay 从 `evidence-annotator/artifact-views/<cand>-iteration-*/<av>/workspace`
   取首末两版做 `difflib` 差分；只有一个视图时没有 patch，dossier 里就不出现该段（不猜）。
5. **在线确认阶段**仍然每 arm 一个 campaign，用
   `edgebench-vliw-collab-{c0,c1,c2}-codex-2h`；但报告里的效应量只来自 replay，campaign 分数
   只用于"迁移到真实运行后没有崩"。

## 9. 命令

```bash
# 0) 预检（只需一次）
python3 scripts/bench.py check --preset edgebench-vliw-collab-c1-codex-2h

# 1) 离线网格（不花候选预算）
cd $SFORGE_GOAL_PLUS_SOURCE_DIR
for arm in c1 c2; do
  PYTHONPATH=src python scripts/collaboration_sweep.py \
    --archive /runs/<campaign>/goal-plus-state.tar \
    --out /tmp/sweep/<campaign> --dossier summary,detailed \
    --combination ensemble,blackboard --roster 1,3
done

# 2) 汇总
python3 - <<'PY'
import csv, collections
rows = list(csv.DictReader(open("/tmp/sweep/<campaign>/sweep.csv")))
print(collections.Counter(r["status"] for r in rows))
PY

# 3) 只有 §7-H1/H2 成立才做在线确认
python3 scripts/bench.py plan   --preset edgebench-vliw-collab-c1-codex-2h
python3 scripts/bench.py launch --preset edgebench-vliw-collab-c1-codex-2h \
  --campaign-id edgebench-vliw-collab-c1-codex-r7
python3 scripts/bench.py status --campaign runs/edgebench/edgebench-vliw-collab-c1-codex-r7
python3 scripts/bench.py finish --campaign runs/edgebench/edgebench-vliw-collab-c1-codex-r7
```

## 10. 证据与产物

每个 cell：replay store 下的 `turns.jsonl`、`dossiers/<sha256>.json`、`verdicts/<id>.json`，
以及 sweep 的 `sweep.json` / `sweep.csv`。报告必须同时给出：

- `dossier_sha256`（证明两个 cell 看到的是同一份证据）；
- 每策略 `turns` / `total_tokens` / `duration_seconds`；
- `grounding_rate` 与 `claim_precision`；
- `decision_flip` 与（若可得）`veto_value`。

## 11. 已知限制

1. **同质三 agent**：三槽位共用 main 模型，只有角色与提示不同；论文的异质 roster 收益不在范围内。
2. **策略文本是数学域**：AIME bank 措辞迁移到 VLIW 优化靠 runtime preamble 做术语映射，表达力
   损失未知；`mechanistic_step_audit` 是最域无关的一条。
3. **advisory 不改选择**：协作的收益上限是"识别"，不能超过候选池 coverage。若硬分选择本就选对，
   协作不可能有增益——这时应报告 flip 率与 veto 价值，而不是"协作无效"。
4. **单题**：只跑 `vliw_kernel_optimization`，结论不能外推成跨 benchmark 排名。
5. **archive 只覆盖被标注的 iteration**：artifact view 是按标注迭代落盘的，因此 patch 是"首末
   已标注版"的差分，不是从任务 baseline 起的完整 diff。
