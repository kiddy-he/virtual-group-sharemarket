# Virtual Group Sharemarket · 群虚拟股市

一个可以独立运行、接入群聊机器人的**纯虚拟股票市场**。Python 负责行情、撮合、账户、账本和图片；JavaScript SDK 负责可信身份映射、`/fx` 指令、业务工具及可选的新闻预生成。

所有价格、公司经营、新闻和资金均为游戏模拟，不接入真实证券行情，不提供真实投资建议。

## 提取范围

本项目从已有聊天机器人集成版本中独立提取，保留 MIT 上游代码及新增的因果市场模型、事务恢复、查询和图片能力。**这是独立服务及接入 SDK，不是可以直接加载的完整 AstrBot / OpenClaw 插件。** Python 包名 `astrbot_plugin_sharemarket` 保留用于导入兼容；来源见 [第三方声明](THIRD_PARTY_NOTICES.md)。

不包含原机器人的凭据、群号、账号、聊天记录、数据库、人物参考图、私有帮助图、生产随机种子和检查点，也不包含原宿主的权限框架与统一投递队列。示例号码均为合成占位符。

## 支持什么

| 部分 | 能力 |
| --- | --- |
| 行情 | `causal-v2` 多因子模拟、行业和公司差异、盘中变化、公共信息延迟、事件阶段与传导 |
| 交易 | 开户、买卖、限价委托、撤单、部分成交、费用、T+1、资金/股份冻结 |
| 账户 | 资金、持仓、委托、成交、自选、排行、签到和成就 |
| 扩展玩法 | IPO、有限融资融券、道具、分红、风险警示与公司退出 |
| 图片 | 通用帮助卡、按行业拆分的行情图片、OHLC K 线、历史图；返回多页时应全部发送 |
| 可靠性 | SQLite、原子操作、稳定操作 ID、检查点恢复、投递 outbox 与确认回执 |
| 接入 | 一市场一进程、群与市场绑定、私聊查询、管理员私聊管理、可注入语义分类器 |
| 新闻 | 公开事件 feed、可选模型改写、后台预生成、持久化租约与退避、合并消息节点 |

每日任务、赛季奖励和加速卡入口已下线，不属于本版开放功能。底层遗留模块不代表公开可用接口。真实行情源、完整交易所、债券/期权市场、自动化自主交易代理也不属于本项目能力。

## 环境

- Linux / 支持 Unix domain socket 的 POSIX 环境；本版在 Linux 验收。
- Python **3.11+**；锁定依赖在 CPython 3.12 下验收。
- 可选 Node.js **24.15+**，新闻缓存使用 `node:sqlite`，无需 npm 依赖。
- 可显示中文的字体，例如发行版的 Noto CJK。缺少字体会影响中文图片，需由部署环境安装。

## 五分钟启动

```bash
git clone https://github.com/kiddy-he/virtual-group-sharemarket.git
cd virtual-group-sharemarket
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'setuptools>=77' wheel
python -m pip install -r requirements-lock.txt
python -m pip install --no-build-isolation --no-deps -e .
sharemarket serve --state-dir state/shared --market-id shared --config config/market.example.json
```

也可以直接 `python -m pip install .`，由 pip 解析兼容的依赖版本。示例使用 24 小时加速市场：20 分钟一个虚拟交易日、3 秒一个 tick。

第二个终端，激活相同虚拟环境：

```bash
sharemarket-rpc --socket state/shared/runtime.sock --request '{"method":"health"}'
sharemarket-rpc --socket state/shared/runtime.sock --request '{"method":"account","params":{"action":"open"},"actor":{"senderId":"700000001","accountId":"bot","scope":"private","identity":"guest","nickname":"示例玩家"},"operation_id":"demo-open-1"}'
node examples/bot.mjs '/fx 帮助'
```

示例程序只打印结果和所有图片路径，**不会连接聊天平台或真正发送消息**，也不会确认发送。`examples/rpc-requests.json` 提供其他本地请求。不要在真实消息中接受用户自行填写的 `actor`。

## 接入群聊

1. 复制 `config/bot.example.json` 为被 Git 忽略的 `config/local.json`，在本机填写真实授权账号及群市场绑定。
2. 每个市场启动独立进程。示例中的 `second` 对应 `state/second`，使用前另行启动。
3. 宿主从真实事件构造可信上下文，调用 `createMarketAdapter().handle(ctx)`。
4. 发送 `result.text` 和经过 `.artifacts()` 校验的**全部**图片。`result.private=true` 必须私聊发给请求人。
5. 平台返回确定的成功回执后调用 `.acknowledge()`。失败或不确定时查询原操作结果，不得换 ID 重复下单。

接入函数 `registerMarketTools()` 可注册五类工具；需要宿主提供工具 API、可信上下文解析和真实发送函数。参见 [接入文档](docs/BOT-INTEGRATION.md)，其中包含新闻合并消息、隐私、权限和模型改写边界。

## 常用指令

| 输入 | 行为 |
| --- | --- |
| `/fx 帮助`、`/fx 开户` | 帮助图片、开通虚拟账户 |
| `/fx 行情`、`/fx 行情 科技` | 全市场或指定范围，多张图应全部投递 |
| `/fx 搜索 科技`、`/fx 个股 600003` | 先找股票，再查询明确代码 |
| `/fx K线 600003`、`/fx 盘口 600003` | 日 K 与盘口 |
| `/fx 买入 600003 100` | 买入 100 股，不保证立即成交 |
| `/fx 卖出 600003 100 限价 10.50` | 明确数量和价格的限价委托 |
| `/fx 撤单 1` | 撤销自己的委托 |
| `/fx 资金`、`/fx 持仓`、`/fx 委托`、`/fx 成交` | 账户信息，私聊投递 |
| `/fx 新闻`、`/fx 新闻 科技` | 已公开的模拟事件；模型新闻需额外接入缓存读取 |
| `/fx 签到`、`/fx 成就`、`/fx 道具` | 已开放玩法 |

只有消息开头的独立 `/fx` 前缀会触发；`/fxfoo` 不触发。其他自然语言操作需宿主注入 `resolveIntent`，默认不联网、不调用任何模型。未知或缺少数量的交易请求应澄清，不能自动猜测下单。

## 文档

- [架构与信息边界](docs/ARCHITECTURE.md)
- [配置、市场时间与依赖](docs/CONFIGURATION.md)
- [本地 RPC 接口](docs/API.md)
- [机器人、工具、投递接入](docs/BOT-INTEGRATION.md)
- [交易规则与可用功能](docs/GAME-RULES.md)
- [模拟新闻与可选 LLM](docs/NEWS-AND-LLM.md)
- [因果市场模型设计](docs/MODEL-DESIGN.md)
- [部署、备份、恢复](docs/OPERATIONS.md)
- [测试与验收](docs/TESTING.md)
- [隐私与开源发布](docs/PRIVACY.md)
- [迁移及限制](docs/MIGRATION.md)
- [English overview](README.en.md)、[贡献](CONTRIBUTING.md)、[安全报告](SECURITY.md)、[变更记录](CHANGELOG.md)

## 测试

```bash
python -m unittest discover -s src/astrbot_plugin_sharemarket/tests -v
npm test
python scripts/smoke.py
python scripts/audit-public.py
```

测试只使用临时目录、合成用户和独立市场，不连接真实聊天平台、不使用生产数据、不调用付费模型。详细覆盖范围及本次结果见 [TESTING.md](docs/TESTING.md)。

## 许可证

MIT，保留原作者版权。参见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目不附带原宿主的角色图或专有媒体素材。
