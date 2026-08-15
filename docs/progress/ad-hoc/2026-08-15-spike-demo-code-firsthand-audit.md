# 临时工作记录：Demo 全量代码一手核验（Architect）

## 基本信息
- 日期：2026-08-15
- 模式：Tech Spike
- 执行角色：Architect（架构师）
- 是否进入迭代：否（服务于 v0.1 设计阶段，不改变迭代范围）
- 关联迭代：v0.1（设计阶段 R2 → R3 之间）
- 当前状态：已完成

## 背景

Owner 质询设计阶段的信息来源：设计文档与 ADR 中大量「Demo 如何如何」的结论，究竟是我一手读代码得出的，还是转述 PM 的 `docs/research/demo-code-deep-dive.md`。

如实核对后确认：**在本次 spike 之前，我只直接读过 `platform_functions.py` 的 185 行（约 7%），其余 9 个文件 0 行**，部署与运行链路完全未研究。设计中的认证自愈、重试参数、以及 ADR-0004 短路优化的核心依据，全部来自二手研究文档。

Owner 指示：先完成调研，再出设计 R3。本记录是调研结果。

## 操作/产出

**通读范围：快照全部 10 个文件、3401 行，逐行读完。**

| 文件 | 行数 | 本次 |
|------|------|------|
| `platform_functions.py` | 2600 | 全读（此前仅 185 行） |
| `setup_unix.py` | 174 | 全读（此前 0） |
| `Step1_init_project_files.py` | 159 | 全读（此前 0） |
| `Step4_SetAPI_And_Check_LLMModel.py` | 141 | 全读（此前 0） |
| `CLAUDE_SETUPYourOwnModel_kimiExample.md` | 141 | 全读（此前 0） |
| `运行我_一键安装.sh` | 121 | 全读（此前 0） |
| `brain-consultant.md` | 31 | 全读（此前 0） |
| `hooks/remind_after_singleSim.py` | 17 | 全读（此前 0） |
| `settings.json` | 15 | 全读（此前 0） |
| `使用说明.txt` | 2 | 全读（此前 0） |

---

## 验证证据

### 一、对 `demo-code-deep-dive.md` 的核实：一处结论性错误

**❌ deep-dive §8 第 1 条的「修正」本身是错的。**

该节称：

> 原表述「platform_functions.py 封装约 40 个 MCP 工具：认证、单次/**批量**仿真…」——**不准确**：MCP 层无批量仿真，批量在 pip 包 skill `brain-simAlphasinBatch-and-track` 中实现（快照未含）。

**实际情况**：快照的 `platform_functions.py` 中确有批量仿真能力，共三处：

| 位置 | 内容 |
|------|------|
| 2293–2387 | `create_multi_simulation`：接受 2–8 个 alpha 表达式，一次 `POST /simulations` 提交 JSON **数组** |
| 2389–2506 | `_wait_for_multisimulation_completion`：轮询 `children`，逐个等待子仿真完成并取详情 |
| 2558–2595 | `lookINTO_SimError_message`：批量解析多个 simulation location 的错误 |

`create_multi_simulation` 在 39 个 `@mcp.tool()` 清单内（我逐个数过，确为 39 个）。

**结论：`docs/research/README.md:14` 的原表述「约 40 个 MCP 工具…单次/批量仿真」是正确的；deep-dive §8 声称「修正」了它，但该结论本身是错的。**

**源文件状态已核实（2026-08-15）：`docs/research/README.md` 至今未被改动，仍是正确表述——deep-dive 只是在自己文档里写了修正意见，并未实际改动源文件。因此无需回退任何内容，唯一需订正的是 deep-dive §8 第 1 条自身。**（另：deep-dive §8 称其为「立项 README」，实际指 `docs/research/README.md`，非项目根 `README.md`；根 README 从未包含该表述。）

影响面：v0.3 组装核心会依赖批量仿真，若按 deep-dive 的结论行事，会误以为该能力需要从 pip 包 skill 移植，而它就在快照里。deep-dive 是 INDEX 挂的设计阶段必读输入之一，冷启动会话会读到这条错误结论——污染面持续存在，但不产生即时阻塞（v0.1 范围不含仿真）。

pip 包的 `brain-simAlphasinBatch-and-track` skill 与之**并存**、不矛盾——skill 提供的是更完整的批量调度（fingerprint 去重 / CSV 断点 / 并发退避 / detached 后台），MCP 层提供的是基础的多表达式提交与等待。两者是不同层次。

### 二、deep-dive 准确、本次一手确认的结论

- 39 个 MCP 工具 ✓（逐个计数）
- 认证：Basic Auth → 201 → JWT 存 cookie `t`；401 + `WWW-Authenticate: persona` → playwright 有头浏览器、每 5 秒轮询、上限 60 次（5 分钟）✓（99–232 行）
- `ensure_authenticated` 每次工具调用前探活 + 失效自动重认证 ✓（257–271 行）
- 相关性接口 5 次重试、固定 20 秒间隔、**无指数退避** ✓（1016–1134 行）
- `get_alpha_pnl` / `get_alpha_yearly_stats` 5 次重试、2 秒起、×1.5 指数退避 ✓（419–481、952–1014 行）
- `get_datafields` 硬编码 `limit=50, offset=0` ✓（398–399 行）
- `get_platform_setting_options` 用 `OPTIONS /simulations` 笛卡尔展开 ✓（1412–1478 行）
- 认证成功后明文凭据回写 `user_config.json` ✓（1609–1615 行）
- `submit_alpha` 吞异常返回 `False` ✓（537–539 行）
- hook `exit(2)` 强制注入单数据集纪律 ✓（`hooks/remind_after_singleSim.py`）
- 七处全局污染 ✓（Step1 + setup_unix 逐条确认）

### 三、数字订正

**相关性接口最坏耗时不是 100 秒，是约 80 秒等待。**

代码（1020–1023、1033–1036 行）：`max_retries = 5`，5 次尝试之间只有 **4 次** `sleep(20)`，且无退避递增。所以最坏 = 80 秒 sleep + 5 次请求往返时间。

设计 §7.1 的 R-1 写的是「最坏 100 秒/条」——偏高约 20%。**量级结论不变**（500 条候选仍是十几小时），但数字应订正。

### 四、deep-dive 未覆盖、本次新发现（按对本项目的价值排序）

| # | 发现 | 位置 | 对本项目的意义 |
|---|------|------|----------------|
| **B1** | **`submit_alpha` 成功时 `return response.__dict__`**——`requests.Response.__dict__` 含 `request`（PreparedRequest，其 headers 带 Cookie/Authorization）、`cookies`、`raw`。MCP 工具层再包 `{"success": success}` 原样返回。**这不只是「弱错误处理」，是一条凭据泄露路径**：JWT cookie 会被序列化进 MCP 响应，进入 LLM 对话上下文 | 535 行 + 1912–1913 行 | 强佐证设计 §3.1 的 `SubmitOutcome` 只返回 `ok/error/raw` 而非整个 Response；应补进 §8「不照搬 Demo」清单 |
| **B2** | **多个 MCP 工具把明文凭据作为工具参数**：`get_glossary_terms(email, password)`、`search_forum_posts(...)`、`read_forum_post(...)`、`get_daily_and_quarterly_payment(...)`，签名里就有 `password`。凭据流经 MCP 协议消息 → 进入 LLM 上下文。**比落盘更严重**：落盘至少还在本地 | 2064、2091、2120、2510 行 | 我们的 `BrainClient` 凭据只在构造时注入、不出现在任何方法签名 ✓ 设计已避开，但值得写明这是有意为之 |
| **B3** | **轮询终止条件有类型 bug**：`if simulation_progress.headers.get("Retry-After", 0) == 0: break`——HTTP header 值是**字符串**，`"0" == 0` 为 `False`。仅当 header 缺失（返回默认 int `0`）才 break；若平台返回 `"0"`，会 `sleep(0.0)` 忙等死循环。同型 bug 见多仿真等待 | 332 行、2444–2446 行 | v0.1 不做仿真，无直接影响；v0.2 做调度时必须避免照抄。记入知识库 |
| **B4** | **Step1 的覆盖是破坏性且无备份**：`~/.claude/settings.json` 先 `unlink()` 再 move；`~/.claude/hooks` 先 `shutil.rmtree()` 再 move。用户已有的 Claude Code 配置与钩子**直接丢失，无提示、无备份** | Step1 113–137 行 | 「项目级隔离」这一立项核心诉求的具体靶子。v0.2 常驻方案必须给出不碰用户全局配置的路径 |
| **B5** | **LLM API key 明文写入 shell rc 文件**（`export ANTHROPIC_AUTH_TOKEN="sk-..."`），且 `set_unix_env_var` 遇已存在的同名 export **只跳过不更新**——换 key 时旧值残留、新值不生效，用户无从察觉 | setup_unix 36–49 行、Step4 116–130 行 | 第二类凭据面（BRAIN 账号之外）。本项目不涉及 LLM key，但「已存在则跳过」是配置管理的典型反面案例 |
| **B6** | `authenticate` 工具的 docstring 声称凭据可来自 `.brain_credentials`，但**代码中无任何读取该文件的实现**，只读 `load_config()` | 1592–1603 行 | 我们项目的 `.brain_credentials` 是 Owner 自有约定，非从 Demo 继承的实现——设计中不应假设 Demo 有可复用的加载逻辑 |
| **B7** | **列表 API 的 `limit` 至少支持 500**：`value_factor_trendScore` 内部以 `limit=500` 调用 `get_user_alphas` | 635 行 | 直接优化机会：设计 §4.1 叶子窗口分页目前用 `limit=100`，若提到 500，1 万条的请求数从 ~100 次降到 ~20 次 |
| B8 | `_resolve_config_path` 支持 `MCP_CONFIG_FILE` 环境变量覆盖配置路径，默认落**脚本同目录** `user_config.json` | 1529–1551 行 | 补全 deep-dive 弱点 1 的精确路径 |
| B9 | Step4 把选定模型同时写入 `ANTHROPIC_MODEL` / `DEFAULT_OPUS` / `DEFAULT_SONNET` / `DEFAULT_HAIKU` / `SUBAGENT_MODEL` 五个变量；Demo 依赖 Kimi/DeepSeek 经 `ANTHROPIC_BASE_URL` 转接 | Step4 116–130 行 | Demo 的运行前提，与本项目无关（我们不做 LLM 转接） |
| B10 | `使用说明.txt` 用 `%USERPROFILE%` 路径（Windows），而快照提供的是 Unix 安装脚本 | 使用说明.txt | 文档与实际不匹配，说明快照是混合来源 |

### 五、部署与运行方式（此前完全未研究，现补全）

**安装链路**：`运行我_一键安装.sh` → 检查/安装 Node（brew 或从 npmmirror 下载 pkg 后 `sudo installer`）→ 检查 Python3 → `npm install -g @anthropic-ai/claude-code`（失败则 sudo 重试）→ `python3 setup_unix.py`。

`setup_unix.py` 四步：

1. **Step1**：`pip install -U cnhkmcp` → 从包内 `untracked/` 释放核心文件到当前目录 → 整个 `untracked/` 复制到当前目录 → `skills/` → `~/.claude/skills`（copytree 覆盖合并）→ `settings.json` → `~/.claude/settings.json`（**unlink 后 move**）→ `hooks/` → `~/.claude/hooks`（**rmtree 后 move**）→ 跑依赖安装脚本
2. **Step2**：`brain-consultant.md` → `~/.claude/agents/`
3. **Step3**：pip 装 playwright/bs4/pandas/requests/mcp + `playwright install chromium` → `claude mcp remove brain-mcp` → `claude mcp add --scope user brain-mcp -- <python> platform_functions.py` → 改 `~/.claude.json` 设 `timeout=900`
4. **Step4**：交互选 Kimi/DeepSeek → 输入 API key → 拉模型列表 → 选模型 → 写 7+ 个环境变量到 shell rc

**运行方式**：重启终端 → `claude --agent brain-consultant`（或按 `使用说明.txt` 双击桌面快捷方式，Windows 版）。

**功能全貌**：五层——安装层 / 入口层（brain-consultant 人格，含 Pyramid 与仿真设置领域知识）/ 能力层（39 个 MCP 工具）/ 纪律层（1 条 PostToolUse 钩子，`exit(2)` 强制注入单数据集纪律）/ SOP 层（22 个 skills，**仅存在于 pip 包，快照缺失**）。

**快照可运行性**：`platform_functions.py` 第 30 行 `from forum_functions import forum_client`，而**快照缺 `forum_functions.py`**——快照版本直接跑会在 import 阶段失败。deep-dive §6 已指出此点 ✓ 确认。

---

## 结论

1. **deep-dive 总体可靠，但有一处结论性错误**（§8 第 1 条「MCP 层无批量仿真」），需订正；该文档其余被我引用过的结论，本次全部一手确认成立。
2. **一处数字需订正**：相关性最坏耗时 80 秒而非 100 秒（设计 §7.1 R-1）。
3. **一处可直接优化**：列表 API `limit` 至少支持 500（设计 §4.1 分页参数）。
4. **两条新增的凭据泄露反面案例**（B1/B2），可强化设计 §8「不照搬 Demo」清单——当前只列了三处冲突，应补第四处「不返回 Response 对象」。
5. **ADR-0004 短路依据的可验证性未改变**：`brain-calculate-alpha-selfcorrQuick` 属 SOP 层，**确认不在快照内**，本次通读无法验证「self-corr > 0.7 ⇒ prod-corr > 0.7」。该结论仍是二手，ADR-0004 风险节的标注（「来自 Demo skill 的经验陈述，非平台文档保证」）应补一句「源文件不在本仓库快照内」。
6. **部署链路已补全**，v0.2「项目级隔离」的具体靶子（B4 的破坏性覆盖、B5 的 rc 污染）已定位。

## 后续建议

- 是否建议升级为标准迭代：否（服务于 v0.1 设计阶段，不改变范围）
- 建议起始角色：Architect（继续出设计 R3，把本记录的第 2/3/4/5 条一并落入正文）

**需由他人处置的事项**（我不改他人产出正文）：

| 事项 | 归属 | 紧急度 | 说明 |
|------|------|--------|------|
| `demo-code-deep-dive.md` §8 第 1 条订正 | PM | **不阻塞，下次 PM 会话顺手改** | 该文档是 PM 产出，我不改他人正文。建议改为「MCP 层**有**基础批量仿真（`create_multi_simulation`，2–8 表达式，在 39 工具清单内）；pip 包 skill 提供的是更完整的批量调度（fingerprint/CSV 断点/并发退避/detached），两者并存、不矛盾」。同时 §6 差异表「核心平台函数一致」的结论不受影响 |
| ~~立项 README 表述回退~~ | — | **经核实无需处置** | `docs/research/README.md:14` 从未被改动，至今仍是正确表述；deep-dive 只是声称修正、未实际改动源文件。无需回退 |
| PM 角色日志 `roles/pm.md` 含同一条错误结论 | PM | 不阻塞 | 角色日志是历史留痕，不追溯改写；建议 PM 在订正 deep-dive 时于新条目中更正，不改旧条目 |

## 收尾归档
- 收尾日期：2026-08-15
- 最终状态：已完成
- 已更新当前角色日志：是
- 其他角色待补充/确认：PM——deep-dive §8 第 1 条订正（不阻塞任何在途流程；`docs/research/README.md` 经核实无需回退）
- 已更新 `docs/progress/INDEX.md`：是
- 已更新知识库：待设计 R3 一并处理（B3 轮询 bug 拟入 `docs/knowledge/engineering/`）
- 关联 commit：见本次提交
- 下一次启动建议：Architect 出设计 R3，处置 Developer D16–D20 + DevOps N11–N13，并把本记录结论第 2/3/4/5 条落入设计正文与 ADR
