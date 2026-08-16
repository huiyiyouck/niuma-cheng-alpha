# AI打工人 Demo 全代码流程深读

> 研究日期：2026-08-15 · 执行：PM · 触发：Owner 指出「基于 Demo 延展的产品必须先吃透 Demo」
> 范围：本地快照全部 10 个文件逐行读完（3401 行）+ pip 包 `cnhkmcp` v4.1.4 本体下载比对（构建于 2026-08-11，1223 个文件）。
> 本文修正立项 README 的两处不准确结论（见 §8）。

## 1. 总体架构：五层结构

```text
安装层   运行我_一键安装.sh / setup_unix.py / Step1 / Step4（环境改写）
入口层   brain-consultant.md（agent 人格，装入 ~/.claude/agents）
能力层   platform_functions.py → MCP server "brain-mcp"（39 工具，快照版）
纪律层   settings.json hooks + remind_after_singleSim.py（PostToolUse 强制提醒）
SOP 层   pip 包内 22 个 skills + 6 份示例工作流文档（★ 本地快照缺失此层）
```

## 2. 安装层：完整链路与全局污染点

`运行我_一键安装.sh`（Mac/Linux）：装 Node（brew/镜像 pkg）→ 检查 Python3 → npm 镜像装 Claude Code CLI → 跑 `setup_unix.py`。

`setup_unix.py` 四步：
1. **Step1**（`Step1_init_project_files.py`）：`pip install -U cnhkmcp` → 从包内 `untracked/` 释放核心文件到当前目录（forum_functions.py、platform_functions.py、依赖安装脚本、brain-consultant.md）→ **整个 untracked 目录复制到当前目录** → **skills → `~/.claude/skills`（覆盖合并）** → **settings.json → `~/.claude/settings.json`（直接覆盖！）** → **hooks → `~/.claude/hooks`（删旧覆盖）** → 跑依赖安装脚本。
2. **Step2**：brain-consultant.md → `~/.claude/agents/`。
3. **Step3**：pip 装 playwright/bs4/pandas/requests/mcp + chromium；`claude mcp add --scope user brain-mcp -- python platform_functions.py`；改 `~/.claude.json` 设 **timeout=900**（因单次仿真阻塞可达 15 分钟）。
4. **Step4**：交互选 Kimi/DeepSeek → 验 key 拉模型列表 → 把 `ANTHROPIC_BASE_URL/AUTH_TOKEN/MODEL` 等 7+ 个环境变量写进 shell rc 文件（Windows 版写注册表用户级）。

**全局污染点清单**（v0.1「项目级隔离」要逐一对应解决的）：`~/.claude/settings.json`（覆盖）、`~/.claude/skills`、`~/.claude/agents`、`~/.claude/hooks`、`~/.claude.json`（user-scope MCP 注册）、shell rc 环境变量、全局 pip 包。

## 3. 能力层：`platform_functions.py` 代码流程（2600 行逐段结论）

结构：Pydantic 模型（SimulationSettings 19 字段 / SimulationData REGULAR|SUPER）→ `BrainApiClient` 类（约 1525 行，核心）→ 模块级单例 `brain_client` → 配置管理 → 39 个 `@mcp.tool()` 薄封装（1657-2600 行，纯参数透传 + docstring，无业务逻辑）。

### 3.1 认证机制
- `authenticate`：Basic Auth（base64 email:password）POST `/authentication` → 201 得 **JWT 存 cookie `t`**；401 + `WWW-Authenticate: persona` → **生物识别分支**：playwright 开有头浏览器让人扫脸，每 5s 轮询 POST 生物识别 URL，最多 5 分钟。
- `ensure_authenticated`：每个工具调用前置——cookie 存在性 + GET `/authentication` 探活，失效则用内存/配置凭据**自动重认证**（session 过期自愈，这回答了我们风险 5 的一半：无需实测 session 生命周期，按需重认证即可）。
- **弱点**：认证成功后把明文凭据**回写**进 `user_config.json`（包内该文件即含 credentials.email/password 结构）；凭据随包分发目录明文存放。我们的 #9 凭据纪律正是针对这类做法的反面设计。

### 3.2 仿真流程（单次，阻塞）
`create_simulation`：组 payload（REGULAR 剔除 SUPER 专属字段）→ POST `/simulations` → 从 **Location header** 拿 simulation URL → **while True 轮询**：读 `Retry-After` header，非 0 就 sleep 该秒数，为 0 即完成 → 从进度响应取 `alpha` id → GET `/alphas/{id}` 返回完整详情（含 is.checks）。单次调用一个 Alpha，靠 MCP timeout=900 兜底。返回体附一句人味提示（负 Sharpe 可加负号翻转）。

**【2026-08-16 订正，Architect spike 核出】** MCP 层**有**基础批量仿真：`create_multi_simulation`（2294-2506 行，39 工具清单内）——把 2~8 条表达式打包成数组 POST `/simulations`（平台 multisimulation），逐个轮询子仿真。初版误写「无批量」，原因是我用 `grep batch` 检索而漏了 `multi` 一词。**无并发原语**（Semaphore/gather/ThreadPool）这一点仍成立——multi 是平台侧打包，不是客户端并发。

### 3.3 数据探索
- `get_datasets` / `get_datafields`：GET `/data-sets`、`/data-fields`（按 instrumentType/region/delay/universe/dataset.id/search 过滤；datafields **硬编码 limit=50 offset=0**——不分页，只够探索不够穷尽）。
- `get_operators`：GET `/operators`（实测 102 个）。
- `get_platform_setting_options`：OPTIONS `/simulations` → 解析 `actions.POST.settings.children` → 笛卡尔展开成 instrument×region×delay 行（每行带合法 universe/neutralization 列表）——参数空间机器可读的实现范本。

### 3.4 Alpha 分析（统一的「空响应重试」模式）
`get_alpha_pnl` / `get_alpha_yearly_stats`：GET `/alphas/{id}/recordsets/{pnl|yearly-stats}`，**5 次重试 + 2s 起指数退避（×1.5）**，专治平台异步计算首查空响应；`get_record_sets`/`get_record_set_data` 通用记录集读取。`get_messages` 有完整的 base64 图片剥离逻辑（防 token 爆炸，存盘换占位符）。

### 3.5 相关性与「提交检查」的真相
- `get_production_correlation` / `get_self_correlation`：GET `/alphas/{id}/correlations/{prod|self}`，**5 次重试 + 固定 20s 间隔**（比 recordsets 慢得多，印证平台侧异步算相关性）。
- `check_correlation`：取两路相关性 → 从 `schema.max`（或顶层 max、或 records 兜底扫描）提取最大相关 → **与本地硬编码阈值 0.7 比较**得 passes_check。
- `get_submission_check`：**不是平台判定**——就是 check_correlation + get_alpha_details 的拼装，`all_passed` 只反映相关性。Architect R1-A1 的判断被代码证实：平台侧「触发 PENDING 检查出最终结果」的端点在 Demo 中不存在。
- `submit_alpha`：POST `/alphas/{alpha_id}/submit`；**弱错误处理**（成功返回 response.__dict__，异常吞掉返回 False，无失败原因结构化）——我们验收 #8「失败项留明确原因」的反面教材。

### 3.6 平台运营类
leaderboard（`/consultant/boards/leader`）、pyramid multipliers/alphas（带 404 多端点回退探测）、竞赛三件套、教程文档、`value_factor_trendScore`（多样性分 = Atom 占比 × Pyramid 覆盖 × 分布熵，OS 提交窗口内逐个拉详情算）。论坛三工具委托给 forum_functions.py（**快照缺此文件，快照版实际跑不起来**；包 4.1.4 已把论坛改为 support API 直连并入主文件）。

## 4. 纪律层：钩子机制

`settings.json`：PostToolUse 匹配 `mcp__brain-mcp__create_simulation` → 跑 `remind_after_singleSim.py` → **stderr 输出提醒 + exit(2)**（Claude Code 会把 stderr 反馈进对话）——每次仿真后强制注入「单数据集纪律 + 语法自查」提示。整个 Demo 的「流程管控」只有这一条，其余全靠 SOP 层的文字工作流。

## 5. SOP 层（pip 包独有，快照缺失）：22 个 skills

包内 `untracked/skills/` 完整清单（装机时复制到 `~/.claude/skills`）：

| 类别 | skills |
|------|--------|
| 数据探索 | brain-dataset-exploration-general、brain-datafield-exploration-general、brain-data-feature-engineering、brain-deepExplore |
| 组装/生成 | brain-makeSomeGem、brain-enhance-template、brain-inspectRawTemplate-create-Setting、brain-feature-implementation、wq-brain-alpha-optimization-v1 |
| 批量执行 | **brain-simAlphasinBatch-and-track**（详见下） |
| 检查/评审 | **brain-how-to-pass-AlphaTest**（全部提交检查的阈值+改进技巧知识库）、brain-alpha-judge、alpha-expression-verifier、**brain-calculate-alpha-selfcorrQuick** |
| 改造 | **brain-improve-alpha-performance**（5 步工作流：取详情→评估数据字段→arXiv 找理论→变体仿真→验证） |
| 解释/报告 | brain-explain-alphas、brain-nextMove-analysis、示例工作流_daily_report 等 6 份文档 |
| 通用 | planning-with-files、longTaskSolution、Ralph_Loop、论坛浏览 |

### 重点 1：brain-simAlphasinBatch-and-track（批量仿真，810 行脚本 + 1535 行 ace_lib）
- `batch_simulator.py`：JSON 输入 → **alpha fingerprint 去重** → 分批提交（--batch-size/--concurrency）→ **CSV 状态文件断点续传** → **平台并发限制退避**（`_submit_with_retry` 最多 8 次、遇并发/限流渐进等待）→ `--detached` 后台运行 + PID 追踪 + 轮询协议 → 仿真报错解读（`lookINTO_SimError_message`）。
- `ace_lib.py`：线程安全单例 Session（带 relogin 锁）+ ThreadPool 并发——证实**平台支持并发仿真但有并发上限**（需退避处理），这是我们风险 5「限流阈值」的直接实证。
- **对 v0.1 的意义**：fingerprint 去重 ↔ 我们验收 #2 幂等；CSV 断点 ↔ 验收 #10；退避 ↔ 验收 #6 分批节流——机制同构，可直接借鉴其模式（不照搬代码，其凭据处理不合我们纪律）。

### 重点 2：brain-calculate-alpha-selfcorrQuick（本地自相关快算，733 行）
用 PnL 数据**在本地计算** self-correlation 与 PPAC（Power Pool Alpha Correlation），绕开平台相关性接口的慢查询；明确策略：**self-corr > 0.7 则 prod-corr 必然 > 0.7，可免查平台直接判死**。
- **对 v0.1 的意义**：#6 提交前预判的第二实现路径（本地算 vs 平台接口），更快且省配额；设计阶段应评估两路取舍。PRD 口径（阈值带来源）兼容此路径，无需改。

### 重点 3：brain-how-to-pass-AlphaTest
社区沉淀的全套检查阈值与改进技巧（Fitness 公式、D0/D1 各指标门槛、逐检查的改进手法）——**v0.2 改造核心「病历→药方」映射的现成知识库**。

## 6. 快照 vs pip 包 v4.1.4 差异结论

| 维度 | 快照（2026-08-08 入库） | 包 v4.1.4（2026-08-11 构建） |
|------|------------------------|------------------------------|
| platform_functions.py | 2600 行 / 39 工具 | 3792 行 / 51 工具 |
| 论坛能力 | 委托 forum_functions.py（**快照缺该文件，无法直接运行**） | 已并入主文件，改走 support/help-center API |
| skills | 无 | 22 个（SOP 层主体） |
| 差异性质 | — | 核心平台函数（认证/仿真/相关性/提交）**一致**；增量集中在论坛/支持中心 + set_alpha_properties 签名 |

包仍在活跃演进（构建目录名含 20260811）。复现实验：`pip3 download cnhkmcp --no-deps`。

## 7. Demo 弱点清单（本产品必须避免的）

1. 明文凭据存包目录 `user_config.json`，认证成功后还回写凭据 → 我们：`.brain_credentials` + git 忽略 + #9 结构化断言。
2. `submit_alpha` 吞异常返回 False，无失败原因 → 我们：#8 失败原因回写。
3. 相关性阈值 0.7 硬编码 → 我们：阈值必带来源字段（#6）。
4. 全局环境污染七处（§2 清单）→ 我们：项目级隔离。
5. 单次仿真阻塞式轮询占满 MCP 通道 900s → 我们：v0.1 不做仿真调度（范围外），v0.2 做时参考 batch skill 的 detached 模式而非阻塞模式。
6. datafields 硬编码 limit=50 不分页 → 穷尽场景需自行分页。

## 8. 对立项 README 的修正

1. **【2026-08-16 订正】原第 1 条撤回。** 初版称「README 写的『单次/批量仿真』不准确、MCP 层无批量」——**错**：MCP 层有 `create_multi_simulation`（2~8 表达式打包，见 §3.2 订正），`docs/research/README.md:14` 的表述**从未错过、无需回退**。正确的关系是：MCP 层提供基础批量（平台 multisimulation 打包），pip 包 skill `brain-simAlphasinBatch-and-track` 提供更完整的批量调度（fingerprint 去重 / CSV 断点 / 并发退避 / detached），两者并存不矛盾。此错由 Architect 一手核验（`docs/progress/ad-hoc/2026-08-15-spike-demo-code-firsthand-audit.md`）查出。
2. 原表述「研究流程靠人：仅一条钩子纪律 → 研究流程模板化全新做」——**已过时**：包 4.1.4 已有 22 个 skills 构成完整 SOP 层（探索/组装/批量/检查/改造/报告全链路），我们的「研究流程模板化」不是从零建，而是**评估-取舍-吸收**这套现成 SOP。（此条经 Architect 复核成立。）

## 9. 对本产品各版本的直接启示

- **v0.1（当前迭代）**：机制借鉴 batch skill（fingerprint/CSV 断点/退避）；预判增加本地自相关快算备选路径；`ensure_authenticated` 自愈模式解决 session 风险；`get_platform_setting_options` 的笛卡尔展开是达标线动态读取的参考实现。**PRD 已定稿口径与本研究无冲突，无需回阶段**；设计阶段新增输入已列入上述条目。
- **v0.2（改造回路）**：brain-improve-alpha-performance 5 步工作流 + brain-how-to-pass-AlphaTest 阈值知识库 = 改造核心的 SOP 与知识底座。
- **v0.3（组装核心）**：brain-makeSomeGem / enhance-template / 数据探索四件套 = 组装核心的现成方法论；brain-consultant 人格与示例工作流文档 = prompt 底稿。
