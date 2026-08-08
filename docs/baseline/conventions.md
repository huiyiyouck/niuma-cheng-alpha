# 协作与代码规范

> 本文件承载与具体业务无关的通用 Git 协作规范、commit 约定，以及跨角色的安全门禁。
> 项目特有的代码规范（如语言/框架风格）由项目在自己的 `docs/baseline/` 下另立文件。

## Git 工作流（每次会话）

```text
开始：
  1. git pull --rebase（工作区干净时；否则 git fetch）
  2. git log --oneline -10  检查 [角色] 标记和未推送 commit
  3. 确认无冲突或未推送的他人修改

结束：
  1. git add <明确文件列表>（只 add 本任务归属的文件；禁止裸 git add -A / git add .）
  2. git commit -m "[角色] 动作摘要"
  3. 按入口 Git 安全规则同步：工作区干净且无未推送 commit 才 git pull --rebase；否则 git fetch 并提示本地未推送或未提交变更
  4. git push
```

## Commit Message 格式

### 常规提交
`type(scope): description`

示例：
- `feat(api): add new endpoint`
- `fix(ui): correct button alignment`
- `docs: update README`

### 多 Agent 协作标记
`[角色] 动作 — 详情`（用于 Agent 之间传递协作信号）

**角色标识**：PM、Architect、Developer、DevOps

**动作关键词**：待Review、Reviewed、已定稿、会话记录、基线修正

示例：
```
[PM] v0.2 PRD 待Review              ← 产出通知，等待 Review
[Architect] Reviewed v0.2 PRD R1     ← Review 完成，注明轮次
[PM] v0.2 PRD R2 待Review           ← 修改后重新提交，新轮次
[PM] v0.2 PRD 已定稿                 ← 阶段定稿
```

## 禁止事项
- 禁止 force push
- 禁止裸 `git add -A` / `git add .`（多角色共享同一工作区，裸批量暂存会把他人未提交改动卷进自己的 commit，归属错乱且审计线断裂）——一律 `git add <明确文件列表>`，**无例外通道**；批量场景（如框架回流）同样列固定路径清单。判据是「命令里没有 `-A`/`.`」，机器一眼可查（BCR-016）
- 禁止跳过 Git hooks（`--no-verify`）
- 禁止直接修改他人角色日志
- 禁止在 Review 阶段修改产出文档正文（只能追加 Review 章节）
- 禁止未经人工审核修改 `docs/baseline/` 任何文件
- 禁止跳过「受保护路径删除 Review 门禁」直接删除受保护路径下的文件（见下方章节）

## 受保护路径删除 Review 门禁

### 背景

某项目实战中曾发生：一次"基线同步"commit 把生产源码整目录（38 个文件）+ 部署配置 + 7 个组件一起删掉，commit 信息严重不匹配 diff stat；后续 commit 又把 `.gitignore` 中保护源码目录的规则删除，掩盖问题。生产源码在磁盘和 GitHub 同时丢失，仅靠 Linux unlink-while-open 维持 17 小时未被察觉，任何重启都会导致后端宕机。

事故根因是「Agent 自决直接删受保护路径，无第二角色把关」+「commit message 用模糊动词遮蔽实际删除范围」。本门禁把删除从「事后核对」变成「事前 Review 门禁」。

### 受保护路径名单

每个项目首次启用本框架时，应由 Architect 在 ADR 中明确本项目的受保护路径名单。默认写入 `docs/knowledge/decisions/` 下的 ADR（`baseline/` 是工作流框架层，不放项目 ADR）；如果项目已有 ADR 目录，沿用项目约定路径，并在 `docs/knowledge/INDEX.md` 中登记。建议至少覆盖以下三类：

| 类别 | 示例路径 |
|------|----------|
| 业务源码根目录 | `src/`、`server/`、`frontend/`、`app/`、`packages/` |
| 部署与基础设施配置 | `deploy/`、`infra/`、`docker/`、`k8s/`、`.github/workflows/` |
| 工作流框架本身 | `docs/baseline/`、`docs/templates/`、助手入口文件（如 `AGENTS.md`、`CLAUDE.md`）、工具配置目录（如 `.claude/`、`.codex/`） |

如未明确定义，缺省以"工作流框架本身"三个路径作为最小受保护集合。

### 主门禁流程

1. **停止文件级删除**：Agent 不得直接执行 `git rm`、`rm`、清空文件、删除整个文件内容，或在 commit 中产生文件级删除 diff。普通段落删改不触发本门禁，但修改 `docs/baseline/` 仍受人工审核规则约束。
2. **列出清单**：在会话中给出
   - 待删文件完整路径列表
   - 每个文件的删除原因（一行）
   - `git log -1 --format='%h %s' -- <文件>` 简要说明该文件最近一次变更
3. **指定架构师 Review**：明确请求"由架构师角色 Review 本删除清单"。**Review 必须以 Architect 角色身份显式进行**（用户说"你是 Architect"或"切换到架构师"触发角色切换），不允许当前角色 Agent 自称"以架构师视角看一下"自审。
4. **架构师 Review 输出**：架构师必须给出
   - ✅通过 / ❌驳回 / ⚠️有条件通过（注明条件）
   - 驳回或有条件通过时，列出风险点
5. **执行删除**：仅在架构师 ✅通过后，原角色 Agent 才执行删除并 commit。
6. **commit 留痕**：commit message body 必须包含
   ```
   删除清单：
     - <path1>（原因）
     - <path2>（原因）
   Review：架构师 ✅通过（会话时间 / 关联角色日志条目）
   ```

### 配套规则

#### commit message 规范
受保护路径的删除 commit，标题第一行必须包含「删除」「移除」「清理」等明示字样；禁止用「同步」「对齐」「整理」等模糊动词遮蔽删除事实。

#### 协作 commit 二次核对
标注 AI 助手协作信息（如 `Co-Authored-By`）的 commit（无论是否涉及删除），push 前 Agent 必须把 `git diff --stat` 输出贴进会话；如果 stat 与 commit message 描述范围不一致，停下等 Owner 决策。

### 例外情况

- **架构师自身需要删除受保护路径文件**：架构师不能自审。此时必须由 Owner 直接 Review（不能切换到其他 Agent 角色代替）。
- **删除单个文件且属于本会话刚创建的临时文件**：可豁免（避免新建废稿走 Review 的繁琐）。
- **已在标准迭代记录、Change Note、Bugfix/Incident ad-hoc 中明确登记"将删除 X 文件"的删除**：可在执行删除时引用该记录路径，跳过架构师 Review；但 commit message 仍需含「删除」字样和记录路径。
