# Bootstrap 初始化流程

## 目标

Bootstrap 是一次性初始化机制，只安装团队工作台（目录结构和进度索引）。它不创建项目上下文、角色日志或迭代。

这不是一个常驻项目经理角色。人类用户是项目 Owner（负责人）和实际项目经理；Bootstrap 只是一次性初始化机制。

Bootstrap 的触发规则、执行者和结束条件由 `docs/baseline/mechanisms.md` 统一定义。本文件只描述 Bootstrap 的具体执行步骤。

## 启动口令

用户可以这样启动：

```text
执行 Bootstrap 初始化流程。
```

工作流加载后，如果 Agent 发现当前项目缺少 `docs/progress/INDEX.md`，应建议用户先执行 Bootstrap 初始化流程，不要直接进入角色工作。

检测到缺失时，Agent 只能建议 Bootstrap，不能自动执行。只有用户明确说"执行 Bootstrap 初始化流程"或确认现在执行，才可以开始创建或修改文件。

## Bootstrap 步骤

1. 确认项目目录和 Git 状态。
   - 先执行 `git rev-parse --is-inside-work-tree` 判断是否为 Git 仓库。
   - 如果不是 Git 仓库，不执行 `git status`、`git pull` 或 `git log`，只询问用户是否初始化 Git。
   - 如果是 Git 仓库，按助手入口文件的 Git 安全规则执行：先 `git status --short`；工作区干净且 `git log @{u}..HEAD --oneline` 为空时，才执行 `git pull --rebase`；否则只执行 `git fetch` 并记录当前有未同步变更。最后执行 `git log --oneline -10`。
   - 如果已有未归属文件，不覆盖、不删除，先记录现状。
2. 创建进度目录结构：
   - `docs/progress/iterations/`
   - `docs/progress/ad-hoc/`
   - `docs/progress/archive/`
   - `docs/progress/roles/`
3. 基于 `docs/templates/progress-index.md` 创建 `docs/progress/INDEX.md`。
   - `当前迭代` 必须是 `无`，`当前模式` 必须是 `未选择`。
   - 下一步入口设为"询问用户是否需要以某个角色或工作类型继续；如不需要，保持 General（通用助手）"。
   - 不允许把下一步写成"进入 PM 创建 PRD"，除非用户已经明确选择启动标准迭代。
4. 在 `docs/progress/INDEX.md` 记录 Bootstrap 结果和下一步入口。
5. 如果当前是 Git 仓库，提交初始 Bootstrap commit；如果用户选择暂不初始化 Git，记录"未提交：非 Git 仓库"。

## Bootstrap 完成后的分流

Bootstrap 完成后，Agent 不自动启动迭代，而是询问用户：

```text
工作台已初始化。你现在需要以某个角色继续工作吗？
可选：PM（产品经理）、Architect（架构师）、Developer（开发工程师）、DevOps（运维/部署工程师）。
如果要启动标准迭代，应由 PM（产品经理）创建 PRD；如果只是让某个角色处理临时任务，可以走非迭代自主任务。
如果暂时不需要，我们可以保持 General（通用助手），或到这里收尾。
```

分流规则：

- 用户选择标准迭代：必须由 PM（产品经理）创建 PRD，PM 会检查并在需要时创建 `project-context.md`。
- 用户选择非迭代工作：按 `work-modes.md` 选择 Product Brief、UI Concept、Tech Spike、Bugfix、Ops Task 等模式。
- 用户选择某个角色：对应角色首次激活时自行创建角色日志。
- 用户只想聊天或暂时没有项目：不创建迭代、不创建 ad-hoc 记录，保持 General（通用助手）。
- 用户要求收尾：执行收尾归档机制。

## Bootstrap 不负责的事

以下内容不在 Bootstrap 范围，由对应角色按需创建：

| 内容 | 创建时机 | 负责角色 |
|------|----------|----------|
| `project-context.md` | 安装时由安装脚本铺占位；PM 首次 PRD 或用户提供事实时填写（手动安装时由 PM 从模板创建） | 安装脚本 / PM（产品经理） |
| 角色日志 | 角色首次激活时 | 对应角色自身 |
| 迭代记录 | 启动标准迭代时 | PM（产品经理） |
| 知识库条目 | 产生可复用知识时 | 各角色 |

## 不允许做的事

- 不允许空项目第一步直接进入实现阶段。
- 不允许用户只是问候或闲聊时自动执行 Bootstrap。
- 不允许 Bootstrap 默认创建 `v0.1` 迭代。
- 不允许 Bootstrap 后把 `INDEX.md` 写成 `当前模式：标准迭代`。
- 不允许非 PM（产品经理）角色在 Bootstrap 后直接创建标准迭代。
- 不允许把当前阶段等动态状态写入 `project-context.md`。
- 不允许 Bootstrap 完成后默认进入 PM（产品经理）PRD 阶段。
