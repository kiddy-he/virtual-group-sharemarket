# 新闻与模型

## 公开事件到新闻

`market/causal_events.py` 推进事件，`causal_public.py` 限定公开信息。新闻生成只能读取已公开的 `news_feed` 与股票目录。事件描述包含阶段、不确定性和可核实的公开数字；不能读取 seed、未来分支、隐藏经营、聊天历史或宿主记忆。

`sharemarket-news-events.js` 构造具体的公共事件场景；`sharemarket-news-content.js` 让模型形成报道并校验事实、阶段及未完成事项；`sharemarket-news-cache.js` 用 SQLite 保存事件、版本、租约和重试状态。`news-producer.mjs` 是独立一次性准备器，每市场每次最多拉取三页事件，一批最多准备四条报道，持续运行由宿主调度。

新闻保留“虚拟市场快讯”标识，不把假新闻伪装成真实世界报道。模型失败可形成仅公开事实的结果或等待重试；缓存中未准备好的报道不伪装成已完成。

## 启用示例

1. 在本机的 `config/local.json` 中启用 `news.enabled` 与 `llm.enabled`。
2. 选择支持的 `llm.api`、HTTPS `baseUrl` 和供应商模型名；通过部署环境注入 `apiKeyEnv` 指定的密钥。
3. 运行 `node examples/prepare-news.mjs config/local.json`。
4. 宿主读取公共事件后调用 `readPreparedMarketNews(items, context, {config, marketId})`，把返回 `nodes` 转换成平台合并消息。

默认新闻和模型均关闭。真实供应商兼容性需要部署者验证，本次开源验收只使用假模型测试，未花费真实 API 额度。

## 配置驱动

`sdk/llm.mjs` 支持 Chat Completions / Responses 风格 JSON 文本接口，所有模型和服务 URL 来自配置，凭据只来自环境变量。Responses 必须 `status=completed`；Chat Completions 必须 `finish_reason=stop`；截断、工具调用或空输出都会失败。文本生成层再校验严格 JSON 与报道事实。

该适配器不是所有厂商原生 API 的通用实现，不提供 Gemini 原生工具调用、图像生成或联网搜索。自定义供应商可注入 `request` 函数。聊天人设模型、意图分类器由宿主选择，未硬编码原 bot 的模型链。

## 时延与投递

预生成将模型耗时移出查询链；查询直接读取缓存并说明仍在准备的条目。租约、持久化重试与游标避免重复准备。请勿同时运行任意多个无资源上限的新闻 worker。

后台准备器没有自动群发送功能。投递队列、聊天避让、限频、按群启用和回执都属于宿主接入责任，见 [BOT-INTEGRATION.md](BOT-INTEGRATION.md)。
