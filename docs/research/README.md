# 立项调研原始材料

## AI打工人_demo（快照入库 2026-08-08）

- 来源：`/Users/ck/Project/world_qunat/AI打工人_demo`（原目录保留未动，此处为只读快照）
- 是什么：「BRAIN CLI 助手」Claude Code 版——面向 Kimi/DeepSeek 用户的一键安装包，把 Claude Code 改造成 WorldQuant BRAIN 量化研究助手（`claude --agent brain-consultant`）。

### 结构速览（参谋长立项调研结论，2026-08-08）

| 层 | 文件 | 作用 |
|---|---|---|
| 安装器 | `运行我_一键安装.sh` + `setup_unix.py`（Mac/Linux）、`Step1/4`（Windows，可打 EXE 分发） | 装 Node / Python / Claude Code CLI（国内镜像），pip 装 `cnhkmcp` 并释放核心文件 |
| 模型接入 | `Step4_SetAPI_And_Check_LLMModel.py` | 交互式配 Kimi/DeepSeek 为 Claude Code 后端（`ANTHROPIC_BASE_URL` 等环境变量） |
| 能力核心 | `platform_functions.py`（注册为 `brain-mcp`） | 约 40 个 MCP 工具封装 BRAIN API：认证、单次/批量仿真、Alpha 详情/PnL/年度统计、数据集与字段、操作符、相关性检查、提交检查与提交、论坛搜索/阅读、Pyramid、排行榜、比赛、收入、仿真报错解读 |
| 角色与纪律 | `brain-consultant.md` + `settings.json` 钩子（`hooks/remind_after_singleSim.py`） | BRAIN 专家人格；PostToolUse 钩子在每次仿真后强制「单数据集纪律 + 语法检查」提醒 |

真正的研究能力在 pip 包 `cnhkmcp` 中，本目录是安装器与文件快照。

### 已识别的改造点（供 Bootstrap / PRD 参考，非结论）

1. 全局污染：安装脚本覆盖 `~/.claude/settings.json`、`~/.claude/skills`、`~/.claude/agents` 与全局环境变量 → 需改为项目级隔离（项目内 `.claude/`、`.mcp.json`、`.env`）。
2. 纯交互式：无 headless / 自启 → 服务器托管（`claude -p` 或 Agent SDK + systemd/cron）+ 一键启动。
3. 无管理面：无任务队列、运行记录、多研究项目管理 →「Alpha 管理平台」层全新建。
4. 研究流程靠人：仅一条钩子纪律 → 研究流程模板化（假设→数据→表达式→仿真→检查→提交 SOP 沉淀为模板/skills）。
5. 分发：Windows EXE 思路可借鉴；服务器场景更宜 Docker / 一键脚本。
