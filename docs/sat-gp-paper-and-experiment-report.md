<!-- markdownlint-disable MD013 -->

# SAT → Goal-Plus：论文分析与实验报告

> 配套 HTML 版：[sat-gp-paper-and-experiment-report.html](sat-gp-paper-and-experiment-report.html)
>
> 论文：SAT: Self-Organizing Agent Teams（arXiv:2609.22682v1）
>
> 实验：EdgeBench VLIW · N0/N0v/N1/N2/N3 · Pi/Codex 分开
>
> 状态：2026-10-29 N2/N3 结果已回填；N3 首次 verified repair，N2 仍少 28 cycles

## 一、论文核心思想

SAT 讨论的不是“让更多模型同时回答”，而是：

> 当没有任何一个成员拥有完整解法时，团队能否通过交换部分推理、挑战具体主张、修复错误并重新综合，构造出单个答案中不存在的正确解？

论文把这种能力称为 **collaborative computation**，并把它做成可搜索、可冻结、可迁移的策略资产。

### 1.1 三个可学习对象

策略写成：

```text
P = (S, τ, α)
```

- `S`：阶段列表，例如独立解题 → 具体审计 → 修复 → 综合。
- `τ`：团队共同遵守的协作规范。
- `α`：成员的持久角色与能力边界。

团队在评测前通过反思式搜索选出最多 10 个互补策略；测试时只执行冻结策略，不再学习。每个策略还要产生一份短而自洽的 **credential**：最终答案加上可被审计的推理依据。

### 1.2 关键判据：不是超过最强成员，而是超过路由 oracle

只看“超过最强成员”不够，因为不同成员可能分别答对不同题。论文因此加入独立答案的 **routing oracle**：如果只是从现有独立答案里挑，理想路由就是上限；超过它，才说明互动产生了新解。

### 1.3 论文结果

| 指标 | 数值 | 含义 |
| --- | ---: | --- |
| 数学/物理 SAT 平均准确率 | 66.7% | 最终答案准确率 |
| 相对最强成员 | +17.9pp | 48.8% → 66.7% |
| 同预算线性化 | 58.7% | 单模型串行多算 |
| 独立答案路由 oracle | 59.0% | 只从独立答案里理想选择 |
| 知识/逻辑最终准确率 | 72.8% | SAT 选中答案 |
| 知识/逻辑候选覆盖率 | 87.9% | 候选池里有正确答案 |

最关键的对照：

- 数学/物理：SAT 66.7% **超过** 最强成员 48.8%、线性化 58.7% 和路由 oracle 59.0%，支持“互动确实产生了新解”。
- 知识/逻辑：覆盖率 87.9% 明显高于最终准确率 72.8%，瓶颈从“生成不出正确候选”转向“审计器选不出正确候选”。

### 1.4 论文的边界

- 数学/物理的强证据不能直接外推到所有任务、模型和成本条件。
- 凭证审计不是形式化证明；它仍可能漏掉“看起来合理”的错误。
- demonstrability 的相关性不能直接当作因果干预效果。
- 问答基准的收益不能直接外推到长程软件工程。

## 二、论文方案图示

SAT 有两个回路：评测前的 **学习回路** 和评测时的 **执行回路**。学习回路决定“怎么合作”，执行回路决定“这次怎么得出答案”。

```mermaid
flowchart TB
  subgraph Learn["评测前：学习回路"]
    A["建立档案<br/>策略、转录、答案、验证探针"] --> B["反思变异<br/>诊断失败，修改角色/阶段/综合规则"]
    B --> C["跨题验证<br/>源题成功后测 5 道验证题"]
    C --> D["选择策略库<br/>按覆盖与互补性选最多 10 个"]
    D --> E["冻结部署<br/>新题只执行，不再学习"]
  end

  subgraph Exec["评测时：执行回路"]
    F["固定团队<br/>成员与角色固定"] --> G["策略执行器<br/>P1 独立 / P2 审计 / P3 修复 / P4 综合"]
    G --> H["凭证池<br/>答案 + 推理依据"]
    H --> I["审计 / 选择<br/>逐份找局部缺陷"]
    I --> J["最终答案<br/>保留可核验依据"]
  end

  E -. "冻结策略" .-> G
```

### 2.1 为什么固定团队、冻结策略

- 固定团队让不同策略可以在同一组角色上比较。
- 冻结策略防止测试时“边答边学”造成泄漏与不可复现。
- SAT 把“组织能力”当作非参数化资产，而不是给模型改权重。

### 2.2 为什么需要凭证审计

最终候选往往都“看起来合理”。SAT 不先看答案频率，而是逐份凭证找具体局部缺陷：

1. 算术错误；
2. 缺失情况；
3. 无根据假设；
4. 推导跳步；
5. 最终结论不受前文支持。

如果多个候选都没有被发现缺陷，才使用答案频率作强制平票规则；如果所有候选都有缺陷，选择缺陷最小的候选并明确剩余问题。

## 三、Goal-Plus 适配方案

Goal-Plus 的约束与 SAT 不同：

- 候选之间隔离，没有 peer message；
- verifier 异步；
- FrozenSpec、hard Evidence、Selection 不能被审计改写；
- 不能新增队列、host wait loop 或候选轮询。

因此不能复制 SAT 的固定团队和团队阶段，只能迁移“审计 → 修复 → 硬证据”的结构。

### 3.1 一句话架构

> LLM Verifier 负责审计，Steering 只负责投递，Candidate 负责修复，Hard verifier 与 Selection 保持裁判权。

### 3.2 SAT 机制到 Goal-Plus 的对应

| SAT 机制 | Goal-Plus 对应 | 处理 | 理由 |
| --- | --- | --- | --- |
| 固定团队 / 持久角色 | K 个隔离候选 | 替换 | 保留多候选探索，不恢复固定角色和 peer 拓扑 |
| 策略库 P=(S,τ,α) | 冻结 task reference + defect taxonomy | 部分保留 | 本轮不跨 run 学习策略，先验证审计信号 |
| critic / peer audit | LLM Verifier 的 VerifierAudit | 替换 | 审计需要独立性；用 verifier 替代固定 critic |
| repair action | 候选下一次尝试 | 保留 | 执行者必须拥有 edit surface；verifier 不直接改 artifact |
| peer discussion | 单向 brief + pull | 替换 | 只传审计结论，不允许候选互相对话 |
| credential audit / integrator | AuditBroker + repair credential + Selection | 保留但改造 | 审计只给依据；最终选择仍由 hard/quality 规则决定 |
| team phases / strategy search | 不迁移 | 舍弃 | Goal-Plus 没有固定团队；跨 run 学习不在本实验范围 |

### 3.3 架构流程图

```mermaid
flowchart LR
  A["Task + FrozenSpec"] --> B["K 个隔离候选"]
  B --> C["Artifact"]
  C --> D["Hard verifier<br/>correctness + cycles"]
  C --> E["LLM Verifier<br/>claim + ≤2 defects + repair"]
  D -->|"hard facts"| E
  E --> F["AuditBroker<br/>去噪、限长、幂等"]
  F --> G["AuditBrief store"]
  G -.->|"Steering / pull<br/>只负责投递"| H["Candidate reads brief"]
  H --> I["Candidate repairs<br/>改 / 忽略 / 反驳"]
  I --> J["New artifact"]
  J --> D
  J --> K["Hard settlement"]
  K --> L["Credential<br/>verified / rejected"]
  K --> M["Selection<br/>规则不变"]
```

### 3.4 四条所有权边界

| 角色 | 负责 | 不负责 |
| --- | --- | --- |
| LLM Verifier | 独立审计、定位 evidence gap | 不直接改 artifact |
| Steering / pull | 在候选下一次工具调用时送达 brief | 不修复，不 push，不等待 |
| Candidate | 在自己的 edit surface 内修复/忽略/反驳 | 不能改 acceptance、Judge 或 peer artifact |
| Hard verifier + Selection | hard 结果、最终选择 | 不被 brief 改写 |

### 3.5 三个设计理由

**为什么 verifier 不直接修：** verifier 没有候选的 edit surface；直接改 artifact 会把审计和评估混在一起，也会污染 hard Evidence。

**为什么是 pull：** verifier 是异步的，审计产出时候选可能已经结束 turn；持久化 + 拉取把时间解耦，不需要 host wait loop。

**为什么还要 credential：** 工具返回 brief 不等于候选读了，读了不等于改了，改了不等于分数更好；credential 用后续 hard settlement 关闭最后一公里。

## 四、实验配置

实验目标不是复现 SAT 的团队收益，而是回答一个更窄的问题：在 Goal-Plus 的隔离候选拓扑中，审计—修复信号能否改善 VLIW 答案，并且增量能拆到生产、投递、闭环三个环节。

### 4.1 分组

| 组 | LLM Verifier | 审计产出 | 投递 | 回执 / credential | 用途 |
| --- | --- | --- | --- | --- | --- |
| N0 `optional` | off | off | off | off | 无 verifier 基线 |
| N0v `control` | on | off | off | off | compute-matched 控制 |
| N1 `shadow` | on | shadow | 不投递 | off | 只测审计生产 |
| N2 `pull` | on | apply | pull | off | 只测投递 |
| N3 `closure` | on | apply | pull | response + credential | 测最后一公里 |

主归因链：

```text
N1 − N0v = 审计生产
N2 − N1  = 投递
N3 − N2  = 闭环
N2 − N0v = 审计 + 投递总增量
N0       = 只用于成本解释
```

### 4.2 固定条件

| 维度 | Phase 0 | Phase 1 |
| --- | --- | --- |
| Benchmark | local-vliw | EdgeBench VLIW 官方 Judge |
| 预算 T | 1800s | 7200s（2h） |
| 候选 / 并发 / 重复 | K=4；C=1；R=3 | K=4；C=1；R=3 |
| Harness / 模型 | 同一变体内固定 | Pi 与 Codex 分开，不合并 |
| Judge | 本地 evaluator | 官方 Judge；hidden 只做最终判定 |
| 候选拓扑 | 隔离候选；无 peer；无旧 SAT 角色/阶段 | 同左 |
| Selection | 保持既有 hard/quality 规则 | 同左；审计不得改写 |

### 4.3 步骤

1. **冻结合同**：固定 task、Judge、harness、T/K/C/R、audit contract 和 task reference。
2. **接线 smoke**：N1 只生产、不投递；N2 能 pull；N3 能 respond；确认无 peer、无 push steering、无旧 SAT 角色。
3. **Phase 0**：30 分钟本地预算，N0v/N1/N2，R=3；只回答接线、审计精度、delivery、方差与 headroom。
4. **过 Gate 1**：审计有产出、可送达、候选有行为变化；否则先修 producer/brief/投递，不进入正式矩阵。
5. **Phase 1**：2 小时 EdgeBench；N0v/N1/N2/N3；Pi/Codex 分开；R=3；按 H1/H2/H3 填结果。

### 4.4 测量指标

| 层级 | 指标 | 方向 | 定义 / 来源 |
| --- | --- | --- | --- |
| 主终点 | Judge 0–100 | 按赛事定义 | EdgeBench 官方 Judge；final only |
| 硬门槛 | correctness gate | 不得回退 | hard verifier / 官方 Judge |
| VLIW | max / best / slowest cycles | 越低越好 | VLIW evaluator；不能只报平均值 |
| 审计生产 | briefs、audit completed、defect kinds、precision | — / 越高越好 | audit artifacts + 独立标签 |
| 投递 | delivered、delivery rate | 越高越好 | brief status；delivered / produced |
| 行为 | accepted / ignored / rebutted、artifact change | — | 候选回执 + diff |
| 修复 | uptake、repair lift、harm、time-to-repair | lift 高；harm 低 | brief 前后 hard settlement |
| 闭环 | verified / rejected / queued | verified 越高越好 | credential + 后续 hard score |
| 选择 | coverage、selection loss | coverage 高；loss 低 | run 内 best vs selected |
| 成本 | tokens、cost、verifier calls、latency | 越低越好 | usage + manifest |

统计单位：task × seed/campaign；主报告用 paired difference + bootstrap 95% CI；同时给出 MDE。Pi 与 Codex 不合并。

## 五、实验结果

> 2026-10-29 的 N2/N3 重跑是当前主结果；N0/N0v/N1 是 10-27 参考批次，不构成同一个五臂配对矩阵。N2/N3 使用 goal-plus `235e935`、harness `a690808`。

### 5.1 数据批次与有效性

| Arm | batch | campaign | raw cycles | Judge | runtime | budget | eval | verifier records | briefs (prod / deliv) | completion |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| N0 | 10-27 | `edgebench-vliw-audit-n0-codex-r4` | 1298 | 82.60 | 6170s | 85.7% | 20 | 0 | 0 / 0 | pass |
| N0v | 10-27 | `edgebench-vliw-audit-n0v-codex-r4` | 1441 | 75.62 | 4836s | 67.2% | 15 | 7 | 0 / 0 | pass |
| N1 | 10-27 | `edgebench-vliw-audit-n1-codex-r4` | 1354 | 79.78 | 2943s | 40.9% | 9 | 8 | 3 / 0 | pass |
| N2 | 10-29 | `edgebench-vliw-audit-n2-codex-r13` | **1351** | **79.93** | 7721s | 107.2% | 24 | 6 | 3 / 2 | pass |
| N3 | 10-29 | `edgebench-vliw-audit-n3-codex-r12` | 1379 | 78.56 | 5425s | 75.3% | 15 | 10 | 10 / 6 | pass |

全部为 `K=4`、`C=1`、`R=1`；`official_edgebench_comparable=false`。N2 的 7721s 超过 T=7200s，包含 finalization grace；探索 cutoff 仍是 T。N0 1298 仍是全表最低 cycles，但它是 10-27 参考批次。

### 5.2 表 R1 · 机制计数

| Arm | Briefs | Delivered | Accepted | Ignored | Rebutted | Pending | Credentials (verified / rejected) | Delivery rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| N0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | — |
| N0v | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | — |
| N1 shadow | 3 | 0 | 0 | 0 | 0 | 3 | 0 / 0 | 0.0 |
| N2 apply | 3 | 2 | 0 | 0 | 0 | 1 | 0 / 0 | 66.7% |
| N3 closure | 10 | 6 | 1 | 0 | 4 | 4 | 1 / 0 | 60.0% |

N2 的 closure 关闭，accepted/credential 不适用。N3 的 6 条 delivered = 1 accepted + 4 rebutted + 1 delivered 未回答；另有 4 条 pending。

### 5.3 表 R2 · 描述性差值（非配对因果）

| 对比 | n pairs | Mean Δ Judge | Bootstrap 95% CI | MDE | 方向 / 解释 |
| --- | ---: | ---: | --- | ---: | --- |
| N2 − N1 | 1 | +0.15 | — | — | ≈ 持平；N2 1351 vs N1 1354，跨批次 |
| N3 − N2 | 1 | −1.37 | — | — | ↓；N3 比 N2 多 28 cycles |
| N2 − N0v | 1 | +4.30 | — | — | ↑；跨批次，N0v 预算更低 |
| N3 − N0v | 1 | +2.93 | — | — | ↑；跨批次，不是 audit 因果 |
| N0v − N0 | 1 | −6.97 | — | — | ↓；verifier-only 控制 |

全部为 R=1；没有重复，因此没有 CI/MDE。`n=1` 只表示一个 task×run，不是统计配对样本。N2/N3 的 28 cycles 差值在单次运行噪声内。

### 5.4 表 R3 · 审计质量与行为

| Arm | audit 记录 (ok/fail) | 完成率 | briefs | delivered | accepted | rebutted | pending | credentials (verified/rejected) | repair lift |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| N1 shadow | 6 / 2 | 75.0% | 3 | 0 | 0 | 0 | 3 | 0 / 0 | — |
| N2 apply | 3 / 3 | 50.0% | 3 | 2 | 0 | 0 | 1 | 0 / 0 | — |
| N3 closure | 10 / 0 | 100.0% | 10 | 6 | 1 | 4 | 4 | 1 / 0 | −164 cycles（c004 1543→1379） |
| **合计** | **19 / 5** | **79.2%** | **16** | **8** | **1** | **4** | **8** | **1 / 0** | 仅 N3 c004 可计算 |

Precision 仍不可计算：没有独立 defect 标签。N3 的 4 条 rebuttal 明确表示 frozen process verifier 只暴露 `small_seed_0/1/2` 和 `main_public_seed_123`，无法生成 brief 要求的 per-case evidence；这是 evidence surface / task reference 问题，不是候选无理由拒绝。

> **第一个真实 audit 修复：** N3 c004 的 accepted brief 来自 1543 cycles；候选修复后 hard settlement 为 1379 cycles，credential 状态 verified。这是本次迁移第一次出现 `accepted → artifact change → hard settlement → verified credential` 的完整链路，−164 cycles。
>
> **但 N3 没有超过 N2：** N2 c004 在没有 closure 的情况下走 147734 → 1817 → 1482 → 1351；N3 c004 走 147734 → 1543 → 1379（repair）→ 1379 retain。N3 的修复改善了自己的候选，但 N2 的搜索路径仍然得到更低 cycles（1351 vs 1379）。

### 5.5 结果解读规则

- 先看 briefs / delivered / uptake，再看 artifact change / repair lift，最后看 Judge 与 cycles。
- 机制不成立时，不解释分数；N1 没有 delivery、N2 没有 closure、N3 有 pending 时，分数差异不能归因于 audit。
- VLIW 必须同时报告 max、best、slowest case；不能只报平均 cycles。
- hidden Judge 只做最终判定；public feedback 不能替代 hidden 结论。
- Pi 与 Codex 分开报告；缺失或 incomplete 的 campaign 不进入均值。

## 六、结论

论文侧结论和本实验结论分开写。最新 N3 已经证明“修复可以发生”，但还没有证明“审计提高最终答案”。

### 6.1 论文侧结论

- SAT 在数学/物理任务上展示了“协作计算”：最终准确率超过最强成员和独立答案路由 oracle。
- 在知识/逻辑任务上，候选覆盖率 87.9% 明显高于最终准确率 72.8%，主要瓶颈转向审计与选择。
- 固定团队、冻结策略、反思式搜索和凭证审计可以组合成可迁移的非参数化组织能力。
- 这些结论不能直接外推到软件工程、所有模型或所有成本条件。

### 6.2 本实验结论

**H1 生产：** N3 10/10 audit、N2 3/6、N1 6/8；producer 已能产出 brief，但 N2 只有 50% 完成率，precision 仍不可计算。

**H2 投递：** N2 1351 vs N1 1354，几乎持平；N2 有 2 条 delivered，但没有 closure/response/credential，不能归因于 delivery。

**H3 闭环：** N3 1 accepted / 1 verified；c004 1543→1379，修复机制成立。但 N3 1379 比 N2 1351 多 28 cycles，最终收益未成立。

**总体：** 可迁移的是“局部修复能力”；尚不能证明它能稳定改善最终选择。

### 6.3 结论边界

当前可以说：

- Goal-Plus 已具备“verifier 审计 → brief → candidate 修复 → hard credential”的可执行结构；
- N3 首次出现 verified repair：1 accepted、1 credential verified，c004 −164 cycles；
- 4 条 N3 rebuttal 是 evidence surface 问题，不是候选不配合。

当前不能说：

- audit 提高了 VLIW Judge 或降低了 cycles：N3−N2 = −1.37 Judge，方向相反；
- 闭环改变了最终候选：N2 1351 仍优于 N3 1379；
- N2 的 1351 是 delivered brief 的因果收益：没有 closure/response/credential；
- N0 的 1298 是“无 audit 更优”：它来自 10-27 批次，c002 走 6 次迭代。

### 6.4 下一步

1. **修 evidence surface：** 4/6 N3 delivered 被 rebutted，原因是 frozen verifier 只暴露固定 case；收窄 brief 或提供可调用的 per-case surface。
2. **清 pending 并跑 R=3：** 同批 N2/N3，同一 harness commit、同一 T/K/C/R；N0v/N1 也同批重跑，才能算配对 CI/MDE。
3. **再决定 audit 去留：** 如果 repair 比例/verified rate 稳定但 N3−N2 仍为负，说明闭环改善可观测性和局部修复，不是最终选择。

## 参考

- 论文：[arXiv:2609.22682v1](https://arxiv.org/abs/2609.22682v1)
- HTML 版：[sat-gp-paper-and-experiment-report.html](sat-gp-paper-and-experiment-report.html)
- 论文原文 HTML：[arXiv HTML](https://arxiv.org/html/2609.22682v1)
- 审计实验简报：[sat-gp-audit-experiment-brief.html](sat-gp-audit-experiment-brief.html)
