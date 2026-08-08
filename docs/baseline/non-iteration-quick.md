# 非迭代速查（non-iteration-quick）

> 非迭代工作必读骨架。**仅非迭代用**；跨模式安全红线在 `runtime.md`，完整规范见 `work-modes.md`。
> 核心原则：非迭代允许角色自主执行，但「独立 ≠ 无记录」——必须留日志、证据、后续建议。

## 模式总表

| 模式 | 适用 | 执行角色 | 最低记录 |
|------|------|----------|----------|
| Bugfix / 线上问题 | 功能 Bug、小范围修复 | Developer(+DevOps) | Bugfix 记录 + 验证证据 |
| Incident / 故障 | 服务不可用、数据异常、安全、部署事故 | DevOps / Developer | 时间线 + 根因 + 后续动作 |
| Product Brief / 产品方案 | 想法、需求探索，未定落地 | PM | 方案文档 + PM 日志 |
| UI Concept / UI 草案 | 界面 / 交互 / 视觉探索 | UI | 草案 + UI 日志 |
| Tech Spike / 技术预研 | 验证库 / 架构 / 性能可行性 | Architect / Developer | 结论 + 建议 |
| Ops Task / 运维任务 | 部署外部 / 开源、环境、脚本 | DevOps | 命令 / 配置摘要 + 验证 |
| Workflow Audit / 流程审计 | 状态混乱、角色冲突、基线疑问 | 当前会话 Agent | 审计结论 + `BCR-###` 入 coordination |

## 模式选择

- 明确「迭代 / 版本 / 功能落地」→ 标准迭代（非 PM 先询问转 PM）。
- 「Bug / 报错 / 修一下」→ Bugfix；「宕机 / 事故 / 数据异常」→ Incident。
- PM 想方案未要落地 → Brief；UI 做方向未落地 → UI Concept；部署外部项目 → Ops Task。
- 指定角色做事 ≠ 进标准迭代；无法判断是否进迭代时先问。

## 记录与收尾

- 记录路径 `docs/progress/ad-hoc/`，命名 `YYYY-MM-DD-{bugfix|incident|product-brief|ui-concept|spike|ops}-{name}.md`；同步对应角色日志；可复用经验更新 `docs/knowledge/`。
- 收尾（用户喊停或任务完成时）：更新 ad-hoc 记录与角色日志，写最终状态（已完成 / 已中止 / 升级为迭代），补验证证据，判断是否需知识沉淀与后续角色，给下次启动建议。

## 升级为迭代

影响多角色边界、Bug 扩成新功能、故障暴露架构缺陷、临时部署转长期、方案被要求落地 → 在记录写「建议升级为标准迭代：原因 + 建议版本号」，须用户确认，由 PM 创建 PRD；非 PM 不直接建迭代。

## 禁止项与 Review

- 不借 Bugfix 偷做大功能；不借 Ops Task 改产品架构；方案未确认不自动进实现；不跳日志 / 验证；不为走流程拖延故障恢复。
- 默认不套标准迭代完整 Review；仅影响扩大 / 线上风险 / 准备升级时才指定 Review 方。涉及已定稿接口、部署配置、安全代码须在日志说明是否邀请确认。
- 发现已定稿文档问题 → 按 `standard-iteration-quick.md` 定稿后变更三档处理。
