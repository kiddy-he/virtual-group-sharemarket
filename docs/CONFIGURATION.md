# 配置

## 市场进程配置

传给 `sharemarket serve --config config/market.example.json`。修改后应在完成备份后重启对应市场进程；不是所有参数都支持热更新。

| 字段 | 默认/例值 | 说明 |
| --- | --- | --- |
| `modelVersion` | 示例 `causal-v2`；省略为 `legacy` | 新部署建议明确使用因果模型；不要随意改变已有市场版本 |
| `npcTrading` | `true` | NPC 交易开关，与背景机构数值模型不同 |
| `databaseName` | `market.sqlite` | 只能是当前 state 目录下的文件名，不能带路径 |
| `retentionDays` | `90` | 保留策略，合法 7–3650 |
| `artifactRetentionHours` | `24` | 图片清理阈值，合法 1–8760；未确认 outbox 引用受保护 |
| `features` | 见示例 | `ipo/margin/props/quests/season` 布尔值，已下线入口仍不可用 |
| `rules` | `Config` 对应字段 | 规则覆盖，未知字段/错误类型拒绝启动 |
| `modelSeed` | 默认随机 | 仅测试可显式固定；真实市场不公开 seed |

`quests=true` 仍服务签到等已保留玩法，不表示每日任务入口已上线。真实配置不要存进版本控制。规则字段和实际默认值以 [`config.py`](../src/astrbot_plugin_sharemarket/config.py) 为准。

### 时间

`rules.market_mode="247"` 是全天加速市场，`day_seconds=1200` 为 20 分钟一个虚拟交易日，`tick_seconds=3` 为盘中推进间隔。`realtime` 按上海交易时段与内置交易日历运行。内置年度日历为 2024–2026；未来年份未知时采用保守拒绝交易策略，运维必须更新日历后使用，不能当作自动获得所有法定假日。

`initial_cash` 是虚拟货币初始额度；买卖数量、费用和限价规则参见 [交易规则](GAME-RULES.md)。改变 tick 频率会影响性能及行为，应先做隔离模拟。

`calendar` 可配置 `coveredYears`、`closedDates` 和 `openDates`。年度覆盖声明需要同时核实该年休市日期；仅把年份加入 coveredYears 并不等于已经补全节假日。不要将猜测日历投入实时模式。

## 宿主接入配置

[`bot.example.json`](../config/bot.example.json) 是独立 SDK 使用的配置示例，不是生产机器人配置。

- `enabled`：宿主总开关；关闭后拒绝新请求。
- `groups`：可信群 ID 到市场 ID 的映射。
- `markets`：每市场的 `enabled` 和 `stateDir`；相对路径以宿主工作目录为基准。
- `privateQueries/privateMarket`：私聊入口及其选择的市场。当前一个私聊入口配置一个市场。
- `adminIds`：仅这些可信用户可在私聊调用管理动作；群内管理员消息也不开放管理工具。
- `stateRoot`：新闻缓存根目录。
- `news`：默认关闭，配置 `accountId/personaName` 仅控制公开报道上下文。
- `llm`：默认关闭；配置协议、base URL、model、API key 的环境变量名及超时。

配置示例的两个市场都被声明为 enabled，但进程需分别启动。只有完成真实权限校验的宿主才能构造 `ctx`。SDK 不验证 QQ 登录，也不从用户文本识别管理员身份。

## 可选模型配置

`llm.api` 支持 `chat-completions` 或 `responses`，base URL 必须是 HTTPS 且不含用户名/密码，密钥只从 `apiKeyEnv` 指向的环境变量读取。`timeoutMs` 合法范围 1000–180000。没有默认供应商、模型名或密钥；不默认请求网络。不把环境变量写到日志、提示词或 Git。

部署代理、DNS、证书和供应商访问权限由运行环境处理；项目没有写死本机代理。示例 URL `api.example.invalid` 不可调用，必须在本机私有配置中替换。
