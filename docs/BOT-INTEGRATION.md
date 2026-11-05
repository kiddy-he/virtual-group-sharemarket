# 接入聊天机器人

## 最小适配

```js
import {createMarketAdapter} from '../sdk/adapter.mjs';
const adapter = createMarketAdapter(config, {
  // 可选：输入是不可信文本，只能输出 {method,params}；数量缺失时返回 null。
  resolveIntent: undefined,
});

async function onTrustedEvent(event) {
  const ctx = {
    accountId: event.botAccountId,
    senderId: event.verifiedSenderId,
    scope: event.isGroup ? 'group' : 'private',
    groupId: event.isGroup ? event.verifiedGroupId : undefined,
    messageId: event.platformMessageId,
    text: event.currentPlainText,
    nickname: event.displayName,
  };
  const response = await adapter.handle(ctx);
  if (!response) return; // 普通聊天
  if (response.needsClarification) return sendPlain(ctx, response.text);
  if (!response.result.ok) return reportSafeBusinessError(ctx, response.result);
  const files = await adapter.artifacts(response);
  // sendAll 必须遵循 response.destination，发送 text 和全部 files。
  const receipt = await sendAll(response.destination, response.result.text, files);
  if (receipt) await adapter.acknowledge(response, receipt);
}
```

`sendPlain/sendAll/reportSafeBusinessError` 是宿主实现，示例不是可以直接运行的平台驱动。平台事件必须先通过机器人登录、群启用状态、真实 sender 和 message ID 校验。不要使用转发内容、引用消息或模型自报字段作为可信身份。

## 工具注册

`sdk/tools.mjs` 导出 `registerMarketTools(api,{adapter,getContext,deliver})`。宿主 API 需提供 `registerTool`；`getContext(callId)` 从受信请求存储取入站上下文；`deliver(response,files)` 实际投递并返回成功回执。

注册 `sharemarket_query/account/trade/play/admin` 五类工具。当前消息必须以独立 `/fx` 开头，参数不允许指定用户、群、身份、市场或发送路径。管理动作仅 `adminIds` 中的用户私聊可用。工具成功回传简短状态，不把完整账户 JSON 放回群模型，也不自动重复发送结果。

这不是 OpenClaw manifest 或一键安装插件。宿主工具签名、会话上下文和发送协议如有差异，需要实现桥接层。

## 文本与人设改写

底层先生成确定的业务可读文本，宿主可把该文本交给自己的聊天主模型进行人设改写。固定保留金额、数量、成交状态、费用、订单号、虚拟标记与错误含义，禁止虚构成交或省略风险。该步骤没有默认模型和角色，没有读取 SOUL、群历史或私聊记忆。

交易成功后模型改写失败，应投递原业务文本；不得重新下单。先把可投递结果存入宿主队列，再做有限时长的可选改写。个人结果只在私聊上下文中处理。

## 新闻与合并消息

`news_feed` → `produceNews()` → 新闻 SQLite → `readPreparedMarketNews()`。返回的 `nodes` 是平台无关的文本节点，宿主可以将其变换为 QQ 合并消息节点后一次发送；本项目没有 NapCat/OneBot 发送代码。查询不应等待重新调用 LLM。

后台新闻自动播报还需宿主负责：已绑定群的服务授权、去重投递 ID、低优先级独立队列、最近聊天避让、每群限频、取消后再校验、发送回执及不确定恢复。`produceNews()` **只预生成，不发送**，不能单独实现完整自动播报。可从每 5 分钟 1 批、每小时上限和群消息活跃避让开始，在宿主进行配置，避免打断正常聊天。

## 隔离与撤权

一个群只能映射到配置中一个市场，多个群可共享市场。宿主需把账号维度纳入自身权限检查，当前 `groups/adminIds` 是单 bot 配置；不同 bot 建议使用独立配置与适配器。账户在同市场内按 `senderId` 共享，多机器人同一平台用户也共享，因此不要把不同平台不相交的 ID 空间直接混用。

关闭功能、解绑群或撤销管理员后，宿主必须在真正发送前再次检查授权。SDK 读取传入的配置对象，不会自动监控配置文件变化。持久化投递/重试必须由宿主实现，不能仅保留内存结果。
