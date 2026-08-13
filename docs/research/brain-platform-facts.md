# BRAIN 平台调研事实（API 实测）

> 调研日期：2026-08-13 · 方式：只读 API 调研（认证 → 拉取真实账号数据）· 执行：PM
> 原始 JSON 留存于会话 scratchpad（临时），本文件为可长期引用的事实蒸馏。
> 用途：Product Brief「评分分流 / 改造回路」设计依据；v0.1 PRD 输入。

## 1. 账号库存现状（漏斗左侧远大于右侧）

| 阶段 | 数量 | 备注 |
|------|------|------|
| 未提交（stage=IS, UNSUBMITTED） | 10000 | API `count` 恰为 10000，可能是计数上限，实际或更多，待分页验证 |
| 已提交（stage=OS, ACTIVE） | 88 | 提交后平台持续跟踪 OS 指标 |

最近 20 个未提交 Alpha 创建于 2026-01-24 ~ 02-01，为批量生成产物——印证「组装快、推进慢」的漏斗形态。

## 2. 评分体系 = 机器可读的 checks 清单（核心发现）

每个 Alpha 详情（`GET /alphas/{id}`）自带 `is.checks[]`，每条：`name / result / limit / value`。
`result` 取值：`PASS / FAIL / WARNING / ERROR / PENDING`。

**推论：评分分流可 100% 程序化**——FAIL 项直接给出「差哪个指标、差多少」（value vs limit），改造方向判断有现成的结构化输入，规则引擎即可起步，LLM 用于生成具体改法。

### 实测观察到的 checks（GLB 区域样本）

**第一梯队 · 回测即出（硬门槛，limit 明确）**：

| check | 达标线（GLB 实测） | 说明 |
|-------|-------------------|------|
| LOW_SHARPE | ≥ 1.58 | 主 Sharpe |
| LOW_FITNESS | ≥ 1.0 | Fitness |
| LOW_2Y_SHARPE | ≥ 1.58 | 近两年 Sharpe |
| LOW_GLB_AMER/EMEA/APAC_SHARPE | ≥ 1 | 区域分解 Sharpe（GLB 特有） |
| LOW_SUB_UNIVERSE_SHARPE | ≥ 0.5 | 子 universe |
| LOW_TURNOVER / HIGH_TURNOVER | 0.01 ~ 0.7 | 换手率区间 |
| CONCENTRATED_WEIGHT | — | 权重集中度 |
| IS_LADDER_SHARPE | — | 阶梯 Sharpe |
| UNITS | —（WARNING 常见） | 量纲检查 |
| CLUSTER_TEST | —（样本中全为 ERROR） | 含义待查 |

**第二梯队 · 提交前按需计算（初始 PENDING）**：SELF_CORRELATION、PROD_CORRELATION、DATA_DIVERSITY、REGULAR_SUBMISSION、POWER_POOL_CORRELATION——相关性阈值惯例 0.7（Demo 源码）。

**加分/主题类**：MATCHES_PYRAMID（带 multiplier）、MATCHES_THEMES、OSMOSIS_ALLOCATION（WARNING 不阻塞）。

> 注意：limit 随 region/universe 变化（上表为 GLB/TOP3000 实测值），产品内不可写死，须以 API 返回为准。

## 3. 指标结构（管理面数据模型输入）

- **主指标**：`sharpe / fitness / turnover / returns / drawdown / margin / pnl / longCount / shortCount`
- **多视图**：`is`（全样本）、`train` / `test`（样本内外分段）、区域分解（glbAmer/glbApac/glbEmea）、`investabilityConstrained`、`riskNeutralized`
- **提交后 OS 侧**：`os.sharpe / sharpe125 / sharpe250 / sharpe500 / osISSharpeRatio` 等（本产品范围外，不跟踪）

## 4. 列表 API 即可做库存同步

`GET /users/self/alphas?stage=IS&limit=20&order=-dateCreated` 每项**自带完整 settings + 代码 + is 指标 + checks**——本地漏斗库可直接分页拉取增量同步，无需逐个详情请求。

## 5. 组装端搜索空间

- 仿真 settings 可配置 19 项（`OPTIONS /simulations` 机器可读全集）：region / universe / delay / decay / neutralization / truncation …
- 操作符 102 个（`GET /operators`）
- 数据字段：`GET /data-fields`（按 region/delay/dataset 过滤，本轮未拉全量）
- Alpha 描述有结构惯例（Idea / Rationale for data / Rationale for operators）——样本即 AI 生成，组装端沿用此格式

## 6. 对产品设计的直接结论

1. **评分分流自动化成立**：checks 的 FAIL/PASS + value/limit 差距 → 规则化分流（淘汰 / 改造 / 提交）无技术障碍。
2. **改造回路的输入现成**：FAIL 清单即「病历」，改造核心 = 病历 → 改法的映射（先规则模板，后 LLM 增强）。
3. **本地库存库必须建**：平台列表只有筛选排序，无谱系、无漏斗视图、无「为什么卡住」；10000 条未提交靠平台页面无法管理。
4. **两段式检查影响流程设计**：第一梯队回测即出（免费、快），第二梯队提交前按需计算（慢、有配额风险）——漏斗中「已回测→可提交判定」应拆成两步。
5. **达标线动态化**：不同 region/universe 门槛不同，规则引擎读 API 实时值，不硬编码。
