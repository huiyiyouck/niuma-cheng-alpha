# 团队知识库索引

> 本索引用于快速定位项目级知识。Agent 启动时只读索引，不全文读取知识库。

## Product（产品）

## UI（界面）

## Architecture（架构）

## Engineering（工程）

## Testing（测试）

## DevOps（运维/部署）

## Decisions（决策）

> v0.1 设计阶段产出，状态均为「提议」，待设计文档 Review 通过后转「已采纳」。

| ADR | 决策 | 状态 |
|-----|------|------|
| `decisions/ADR-0001-技术栈与存储选型.md` | Python 3.11+ / SQLite / 平台原始与本地派生双表分层 | 提议 |
| `decisions/ADR-0002-全量同步切片与对账策略.md` | 时间窗自适应二分切片；窗口级对账为主口径，offset 穷尽降为封顶诊断 | 提议 |
| `decisions/ADR-0003-受保护路径名单.md` | 受保护路径以「不可重算」为判据；`data/snapshots/` 纳入、`data/inventory.db` 排除 | 提议 |
| `decisions/ADR-0004-提交前预判的实现路径.md` | 平台相关性接口 + self/prod 两阶段短路；本地 PnL 快算列 v0.2 备选 | 提议 |

## Opportunities（机会池）

## Retrospectives（复盘）

