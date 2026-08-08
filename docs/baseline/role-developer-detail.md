# Developer 详细规程（按需）

> `role-developer.md` 的低频执行细节，仅在实际触发时读取，默认不加载。

## 子 Agent 调度流程

前置：确认设计文档已定稿（界面要点在 PRD 内）。

1. 将实现任务拆解为前端任务和后端任务。
2. 读取 `docs/baseline/subagents/sub-frontend.md` 和 `sub-backend.md`。
3. 按子 Agent 定义的输入格式模板分别准备（占位符 `vX.Y` 替换为实际版本号）：
   - 前端：sub-frontend.md 完整内容 + 任务描述 + 接口契约 + 关键约束
   - 后端：sub-backend.md 完整内容 + 任务描述 + 接口契约 + 数据模型 + 关键约束
4. 用 Agent 工具并行启动两个子 Agent（`run_in_background: true`，建议 `isolation: "worktree"` 避免文件冲突）。
5. 等待完成；若子 Agent 长时间无响应（建议上限 10 分钟），终止并由 Developer 接手。

## 验证和失败处理

子 Agent 返回后 Developer 必须验证：① 前后端接口一致；② 前端构建 / 测试通过；③ 后端构建 / 测试通过。

- 第一轮不通过：把具体错误反馈给同一子 Agent 修正。
- 第二轮仍不通过：Developer 自己接手。不允许子 Agent 修正超过两轮。

验证全部通过后，Developer 合并产出并提交。

## 并行限制

前后端子 Agent 不能互相依赖对方实时产出，必须基于同一份接口契约（设计文档已定义）独立工作。接口定义不足时，Developer 先补充再分发。
