# 本地 RPC

## 传输

一条 JSON 对象加换行，一连接一个请求。请求最多 64 KiB；客户端响应上限 32 MiB；SDK 默认总等待 180 秒。服务器业务执行等待 120 秒，图片渲染随后执行，不应把 120 秒当作包含渲染的严格总超时。Unix socket 所有者是服务用户，权限 0600，禁止转发到公网。

```json
{"method":"account","params":{"action":"open"},"actor":{"senderId":"700000001","accountId":"bot","scope":"private","identity":"guest","nickname":"示例玩家"},"operation_id":"demo-open-1"}
```

成功响应通常包含 `ok/market_id/operation_id/text`，可能还有 `data/private/artifact/artifacts/render`。失败响应包含 `ok:false/error`，语义范围错误可能有 `public_error`。`text` 是已格式化业务信息；不要直接把 JSON 发进聊天。

## 身份与幂等

业务请求必须包含可信 `actor` 和稳定 `operation_id`。`actor` 可含 `senderId/accountId/scope/groupId/identity/nickname`；服务广播另外使用 `serviceJobId`。群号、身份与目标由宿主从真实消息事件确定。操作 ID 最长 160 字符；相同 ID 与相同指纹重复执行不会重复记账，变更内容报冲突。

SDK 根据账号、会话类型、群、发送人和消息 ID 生成哈希 ID。一条入站消息只执行一个业务操作。不要在同消息 ID 下执行多项不同业务；多步业务需要宿主设计明确且可信的子操作标识，本 SDK 未提供自动多步代理。

## 方法

| method | action / 参数 | 边界 |
| --- | --- | --- |
| `health` | 无 | 本机运维状态，不是群公开工具 |
| `catalogue` | 无 | 公开代码、分类等标识，不含隐藏世界 |
| `news_feed` | 顶层 `after>=0`、`limit=1..200` | 公开事件增量；返回 `items/latest_seq` |
| `query` | `help/overview/analyze/search/stock/book/chart/rank/history/news/calendar/event/sector` | 查询，股票范围模糊可提示澄清 |
| `account` | `open/rebirth/funds/portfolio/orders/trades/watchlist/watch_add/watch_remove` | 当前请求人账户；个人结果私聊 |
| `trade` | `buy/sell` + `code/quantity/[price]`；`cancel` + `order_id` | 正整数股数，金额必须合法；以实际撮合为准 |
| `play` | `checkin/achievements/props/buy_prop/sell_prop/use_prop/ipo/subscribe/issue/margin_status/borrow_cash/repay_cash/borrow_stock/cover` | 参数参见业务代码及规则；受 features 控制 |
| `admin` | `health/audit/pause/resume/settle/compensate/backup` | 仅管理员私聊；补偿须提供原因 |
| `broadcast` | `overview/news/rank` | 可信服务群任务；SDK 不直接暴露该工具 |
| `outbox` | 可信 `actor` | 最多 50 条未确认元信息，不返回完整结果 |
| `result` | 顶层 `id` + 原 `actor` | 取原操作结果，严格匹配原 actor |
| `ack` | 顶层 `id/receipt` + 原 `actor` | 成功投递确认，与原 actor 绑定 |

`admin.settle` 可使用 `params.token` 区分明确的结算任务；重试必须保留原操作 ID。`compensate` 只作用于当前管理员账户，不支持在计划中指定任意目标用户。`play` 参数结构由相应业务函数决定，示例及单元测试是可执行参考；不要声称任意模型参数都被支持。

## 图片与私密结果

`artifacts` 是多页完整列表，不能只发第一页。SDK 会确认真实文件位于对应市场 `artifacts` 目录、是 PNG、数量不超过 64、每页不超过 25 MiB。宿主应在校验后尽快读取并投递，避免并发清理或同 UID 修改造成竞态。

`private=true` 必须改为私聊目标，并避免把 `data` 返回到群模型上下文。个人业务文本可由可信宿主在私聊内改写，数值、代码、订单号与风险结论必须保持。

## 恢复顺序

超时不等于未成交。先用原 actor 查询 `outbox/result`，对未送达结果使用原投递身份恢复；只有平台确定送达才 ACK。发送状态未知时先核查平台回执，不创建新订单。SDK 不自动重试写请求，也不提供平台级恰好一次投递保证。
