# 运行时加载路由

本文件仅在切换到工作流角色或执行工作流流程后读取。保持 General（通用助手）时不读本文件、不加载基线、不写进度。

原则：**先判定任务，再加载规则；只读当前需要的文件。**

## 工作流默认只读

1. 当前入口文件（Codex `AGENTS.md` / Claude Code `CLAUDE.md`）
2. `docs/baseline/runtime.md`
3. `docs/baseline/project-context.md`（如存在）
4. `docs/progress/INDEX.md`（如存在）
5. 当前角色手册 `docs/baseline/role-{role}.md`（已指定角色时）
6. 当前角色日志摘要：优先 `{role}-current.md` / `{role}-summary.md`，否则读 `roles/{role}.md` 最近 10 条或头部摘要。
7. **进入标准迭代各阶段时**，本角色 `docs/progress/roles/{role}-corrections.md` **强制全读**（有界 ≤30 条、角色专属、是本角色犯过的流程错，信噪比最高、token 省，属蒸馏结论非过程轨迹）。**文件不存在视为空 corrections（无需创建、直接跳过，不构成阻塞；需记录首条纠错时才从 `docs/templates/role-corrections.md` 创建）。** 非迭代 / 收尾 / 关闭等场景仍按需读（复盘 / Review 失败时）。

未指定角色时先问以哪个角色继续，不为猜角色加载所有手册；General 不进入本路由。

## 入口顺序

1. **初始化**：缺 `INDEX.md` → 只建议 Bootstrap、不自动建文件；用户确认后才读 `mechanisms.md` + `bootstrap.md` 执行，Bootstrap 不启动标准迭代。
2. **工作模式**：判断标准迭代 / 非迭代 / 收尾 / 关闭 / 知识库（见下表）。
3. **角色运行**：非迭代任务由相关角色直接处理；标准迭代只能 PM 创建 PRD 启动，其他角色只能建议转 PM。

> 若 `INDEX.md` 是旧版「v0.1 / 标准迭代」遗留状态，先纠正为「当前迭代：无 / 模式：未选择」，不要顺势进 PM。

## 工作模式分流表

| 用户意图 | 模式 | 额外读取 |
|----------|------|----------|
| 做版本、迭代、完整功能落地 | 标准迭代 | `standard-iteration-quick.md`、当前 `vX.Y.md` 相关阶段；非 PM 先询问转 PM |
| Bug、线上问题、临时修复 | 非迭代 Bugfix / Incident | `non-iteration-quick.md`、相关 ad-hoc |
| 产品想法、界面草案、技术预研、运维任务 | 非迭代方案 / 预研 / 任务 | `non-iteration-quick.md`、相关 ad-hoc |
| 今天收尾、下班、先停一下 | 收尾归档 | `mechanisms.md`；达阈值再读 `context-policy.md` |
| 迭代是否结束、关闭版本 | 迭代关闭检查 | `mechanisms.md`、当前迭代记录、必要 summary |
| 发现规则需改、增删角色 | 基线修正提案 | 写 `BCR-###` 入 coordination 基线修正提案池（见 `cross-project-collaboration.md`），不在本项目改 baseline |
| 跨项目需求 / 契约 / 状态、读写 coordination 仓 | 跨项目协作 | `cross-project-collaboration.md`；按其发现机制定位 coordination 仓 |
| 查询经验、写入长期知识 | 知识库 | `knowledge-base.md`、`docs/knowledge/INDEX.md` |

无法判断是否进迭代时先问；指定角色不等于进标准迭代。产出物只读当前任务相关；新建文档时才读对应模板。

## 全模式红线与默认原则

适用所有模式（迭代 / 非迭代 / Bootstrap / 收尾 / 关闭 / 审计），不依赖速查表。

- **[P0]** 禁止 force push、禁止跳过 hooks、禁止覆盖未归属修改。
- **[P0]** 受保护路径（业务源码 / 部署配置 / baseline / 模板 / 入口文件，由 ADR 明确）删除必须走架构师 Review 门禁。
- **[P0]** 标注 AI 协作信息的 commit，push 前贴 `git diff --stat` 核对；与 message 范围不符则停等 Owner。
- **[P0]** Review 阶段不得改产出正文，只能追加 Review 章节。
- **[P0]** 未初始化项目须用户确认才能 Bootstrap 写入文件。
- **[P0]** 阶段推进唯一依据 = 约定名门禁 `l1-gates` 在当前 commit 的**绿灯结论**；绿灯以外（红 / 未跑 / 进行中 / 查不到 / 无该 workflow）**一律不自动推进**，退回 Owner 确认并在迭代记录登记降级留痕；不得以任何理由绕过 CI。本条 **fail-closed**——与 corrections 缺失视为空、无 coordination 降级登记两处 fail-open 条文方向相反，勿类推。
- **[P0]** 生产发布放行属对外不可逆动作（A4），须 Owner 明示放行；关闭检查机器化不构成发布授权。
- **[P0]** 基线修正只能写 `BCR-###` 入 coordination 基线修正提案池，不在下游项目直接改 `baseline/`。
- **[P0]** 跨仓写入：写 coordination 协调仓前先确认仓位置（按发现机制，不猜路径）+ git 同步状态 + 改动范围；只写跨项目事实，**不在 A 项目会话改 B 项目 `docs/progress/`**（详见 `cross-project-collaboration.md`）。
- **[P1]** 机制（Bootstrap / 收尾 / 关闭 / 审计）不得代写其他角色结论或角色日志；禁止直接改他人角色日志。
- **[P1]** 标准迭代核心产出默认 ≥2 个 Review 方，少于 2 须用户确认。
- **[P1]** 当前阶段未定稿不进下一阶段（非迭代除外）；已定稿不静默改（轻量走 Change Note、重大回阶段）。
- **[P1]** 只做当前角色允许做的事；人类是 Owner，不虚拟常驻项目经理。
- **[P2]** 中文对话与中文记录是默认规则。

## 跨模式触发索引

- 删除受保护路径 → `conventions.md §受保护路径删除 Review 门禁`。
- 收尾 / 关闭 / 审计机制 → `mechanisms.md`。
- 基线修正 / 增删角色 → `cross-project-collaboration.md §基线修正提案流转（BCR）`、`multi-agent-workflow.md §14、§15`。
- 标准迭代协议 → `standard-iteration-quick.md`；非迭代协议 → `non-iteration-quick.md`；再深则 `multi-agent-workflow.md` / `work-modes.md`。
- 跨项目需求 / 契约 / 状态、读写 coordination 仓 → `cross-project-collaboration.md`。
- 角色日志归档阈值 → `context-policy.md`。
- 新建文档读 `docs/templates/` 对应模板：`prd`（含界面要点）/ `design` / `change-note` / `iteration-summary` / `progress-index`；Developer 自测用 `test-report`（自测报告）。

## 不默认读取

除默认只读与触发索引涉及的文件外，其余 baseline、所有模板、历史迭代 / 角色日志全文、知识库全文均不默认加载，按触发条件再读。
