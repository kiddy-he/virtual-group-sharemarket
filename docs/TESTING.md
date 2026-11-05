# 测试与验收

## 可复现命令

```bash
python -m unittest discover -s src/astrbot_plugin_sharemarket/tests -v
npm test
python scripts/smoke.py
python scripts/simulate.py --days 252 --seeds 3
python scripts/audit-public.py
python -m build
```

Python 测试覆盖市场、SQL 交易、回滚、资金冻结、幂等、恢复、T+1、日结、有限信用、因果信息边界、事件传播、范围查询、K 线和通用帮助图。Node 测试覆盖权限/群隔离、私聊路由、指令前缀、工具结果、模型完成状态、报道事实、缓存与本地 socket / artifact 边界。

`smoke.py` 使用两个真正独立的 Python 子进程和临时 state，验证 socket、开户、不同市场隔离、买单重放、结果恢复与 ACK、所有行情图片以及重启恢复。结束后关闭子进程并清理目录。不会启动机器人或发送真实消息。

`simulate.py` 是轻量纯数值仿真，不等同于完整账本长线测试；用公开测试种子检查有限正价、日涨跌和回撤等指标，只输出聚合统计，不导出可预测生产世界的检查点。固定种子仅用于测试，不应用于真实运行市场。

## 本次独立版验收

实际执行结果记录在 [VALIDATION.md](VALIDATION.md)。CI 在 Python 3.11/3.12 和 Node 24 执行离线回归、临时进程 smoke 和公开文件审计。模型接口使用假的 fetch / request，没有依赖真实账户、QQ 登录或真实资金。

历史集成版的十年多种子报告不在本仓库，也不作为本次重新运行的结果。统计门槛仅用于游戏行为检验，不能据此声称已经校准到真实股票收益或预测能力。截图是程序生成物；无原宿主人物素材。
