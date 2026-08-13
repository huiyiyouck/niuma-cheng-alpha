# 项目上下文

> 项目适配层，只写**项目事实**，不写通用工作流规则，也不写当前阶段 / 迭代 / Review 状态。
>
> **启动契约**：Agent 读「本文件 + `docs/progress/INDEX.md`」后应能回答 8 个问题——
> ① 这是什么项目 ② 技术栈与启动方式 ③ 代码大致在哪（模块地图）④ 依赖哪些外部系统 ⑤ 做什么 / 不做什么 ⑥ 哪些路径受保护、有什么特有约束（①-⑥ 看本文件）⑦ 当前卡在哪 ⑧ 下一步（⑦-⑧ 看 INDEX）。
> 填写时保证每个字段能被一个新接手的 Agent 直接看懂，未知写「待定」、无则写「无」。

## 项目一句话
Alpha 管理平台——Owner 自用的 WorldQuant BRAIN Alpha 研究自动化 + 组装漏斗管理平台：自动组装 → 回测 → 评分分流 → 改造回路 → 高分提交，配套本地库存与谱系管理（定位定稿见 `docs/progress/ad-hoc/2026-08-10-product-brief-alpha-platform.md`）。

## 技术栈
待定（Architect 于 v0.1 设计阶段选型；立项草案倾向 Claude Code + Python MCP，不作约束）。

## 架构与模块地图
> 关键目录 / 模块 → 职责，让 Agent 不通读代码就知道改动该去哪。简单项目写「单一模块」。
- 尚无业务代码（v0.1 实现阶段后回填）
- `docs/research/AI打工人_demo/`：立项调研原始快照（只读参考，非本项目代码）
- `docs/research/brain-platform-facts.md`：BRAIN 平台 API 实测事实（评分体系 / 库存 / 参数空间）

## 启动方式
待定（v0.1 实现阶段后回填）。

## 关键配置 / 环境变量
> 数据库 URL、API key、模型 / 云服务配置等启动必需项（只写名称与用途，不写密钥值）。
- `.brain_credentials`（项目根，git 忽略）：BRAIN 平台账号凭据，JSON 数组 `[email, password]`，由 Owner 手工维护，AI 不经手内容

## 外部依赖与集成
> 数据库、第三方 API、云服务、关键第三方库等。
- WorldQuant BRAIN 平台 API（`https://api.worldquantbrain.com`）：认证 / Alpha 列表与详情 / 仿真 / 检查 / 提交——本项目唯一强依赖
- `coordination_root`：`/Users/ck/Project/niuma-cheng/niuma-cheng-coordination`（本地 checkout）

## 业务边界
- 本项目做：Alpha 组装、批量回测调度、评分分流、改造回路、人工确认后提交、组装漏斗管理（含谱系）、可视化管理
- 本项目不做：收益追踪 / 统计（BRAIN 平台自身机制）；对外分发（纯自用）；接入外部 Agent Hub（预留接口，暂不实现）

## 受保护路径
> 删除需走架构师 Review 门禁（见 `conventions.md §受保护路径删除`）。由 Architect 在 ADR 明确后回填，让 Agent 启动即知哪些不能乱删。
- 缺省最小集：业务源码 / 部署配置 / 工作流框架（`docs/baseline`、`docs/templates`、入口文件）
- `docs/research/AI打工人_demo/`（立项调研快照，只读不改）
- `.brain_credentials`（凭据文件：不删除、不读取内容入日志/文档、不入库）

## 项目特有约束 / 领域术语
> 非通用的硬约束（合规、性能红线、平台限制）和会反复出现的领域名词。
- **凭据纪律（硬约束）**：BRAIN 账号密码只存在于 `.brain_credentials`，任何代码/日志/文档不得打印或复制凭据内容；该文件已入 `.gitignore`
- **提交不可逆（硬约束）**：向平台提交 Alpha 是对外不可逆动作，必须人工确认，禁止全自动提交
- **达标线动态化**：平台 checks 的 limit 随 region/universe 变化，不得硬编码
- 领域术语：Alpha（因子表达式）、组装（生成新 Alpha）、回测/仿真（simulation）、checks（平台机器可读检查清单，PASS/FAIL/WARNING/ERROR/PENDING）、漏斗（组装→回测→分流→改造/提交/淘汰）、谱系（改造产生的父子版本链）、Pyramid（区域/延迟/数据类别组合的平台指标）

## 状态说明
项目级当前状态见 `docs/progress/INDEX.md`；迭代阶段细节见 `docs/progress/iterations/vX.Y.md`。本文件不写状态。
