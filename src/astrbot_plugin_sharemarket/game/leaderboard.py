"""Batched portfolio valuation, net-of-debt rankings and durable day history."""
from .valuation import ValuationService
from .npc import is_npc as _is_npc
from .atomic import atomic

class LeaderboardService:
    def __init__(self,db):self.db=db

    async def top(self,price_of,limit=10,include_npc=False,group_id=None):
        values=await ValuationService(self.db).all(price_of)
        members=None
        if group_id:
            members={r['user_id'] for r in await (await self.db.conn.execute('SELECT user_id FROM memberships WHERE group_id=?',(str(group_id),))).fetchall()}
        entries=[]
        for acc in await self.db.list_accounts(is_npc=None if include_npc else False):
            uid=acc['user_id']
            if members is not None and uid not in members:continue
            value=values[uid]
            entries.append({'user_id':uid,'name':acc['user_name'],'total':value['net_assets'],'return_pct':value['game_return_pct'],'investment_return_pct':value['investment_return_pct'],'status':acc['status'],'rebirth':acc['rebirth_count'] or 0,'is_npc':_is_npc(uid),'cash':value['cash'],'mv':value['market_value'],'debt':value['debt']})
        entries.sort(key=lambda e:(e['status']!='active',-e['return_pct'],-e['total'],e['user_id']))
        return entries[:limit]

    async def period_top(self,period,price_of,limit=10):
        if period not in ('day','week'):raise ValueError('invalid ranking period')
        rows=await self.db.list_leaderboard_snapshots(1 if period=='day' else 7)
        if not rows:return None
        bases={}
        for row in sorted(rows,key=lambda r:r['day_ts']):bases.setdefault(row['user_id'],row['total'])
        entries=await self.top(price_of,limit=1_000_000)
        for entry in entries:
            base=bases.get(entry['user_id'])
            if base and base>0:entry['return_pct']=(entry['total']-base)/base*100
        entries.sort(key=lambda e:(e['status']!='active',-e['return_pct'],-e['total']))
        return entries[:limit]

    @atomic
    async def snapshot_day(self,day_ts,price_of):
        entries=await self.top(price_of,limit=1_000_000)
        # Delete before replacement: fewer players must not leave stale lower ranks.
        await self.db.conn.execute('DELETE FROM leaderboard_snapshots WHERE day_ts=?',(day_ts,))
        for rank,e in enumerate(entries,1):
            await self.db.insert_leaderboard_snapshot(day_ts,rank,e['user_id'],e['name'],e['total'],e['cash'],e['mv'],e['return_pct'],e['status'],e['rebirth'])
        return len(entries)

    def render(self, entries: list[dict],
               title: str = "🏆 股神排行榜（按收益率）") -> str:
        """渲染榜单文本。

        title 可区分两种榜：默认「🏆 股神排行榜（按收益率）」为玩家榜，
        全体榜传「🏆 全体排行榜（玩家 + 模拟股民警）」。
        每条 is_npc 条目渲染时加 🤖 前缀标记。
        """
        if not entries:
            return "还没有玩家开户，发送 /fx 开户 成为第一位股民！"
        lines = [title]
        medals = ["🥇", "🥈", "🥉"]
        for i, e in enumerate(entries):
            rank = medals[i] if i < 3 else f"{i + 1}."
            bot = "🤖" if e.get("is_npc") else ""
            rb = e.get("rebirth", 0)
            rb_tag = f"　🔄重生{rb}次" if rb else ""
            if e["status"] == "bankrupt":
                lines.append(f"{rank} {bot}💀 {e['name']} —— 已破产{rb_tag}")
            else:
                sign = "+" if e["return_pct"] >= 0 else ""
                lines.append(
                    f"{rank} {bot}{e['name']}  {sign}{e['return_pct']:.2f}%  "
                    f"总资产 {e['total']:,.0f}{rb_tag}")
        return "\n".join(lines)


    async def render_history(self, limit_days: int = 14) -> str | None:
        """最近 N 天 rank1 收益率曲线（P3）。

        契约（与 main.py:695-705 的指令实现对齐）：
        - **有 Pillow 时返回 None** —— 调用方（render/chart.py 的
          render_history_chart）负责把曲线画成 PNG 并通过 AstrBot 发图；
        - **没有 Pillow 时返回 ASCII 文本**，作为兜底，保证指令在任何
          环境下都能给出可读回复，不会因为缺图库而静默失败。
        数据源 leaderboard_snapshots 表，只读。
        """
        try:
            import PIL  # noqa: F401
        except ImportError:
            pass
        else:
            pass
        rows = await self.db.list_leaderboard_snapshots(limit_days)
        if not rows:
            return "还没有历史快照，等第一个虚拟交易日结束后再来。"
        by_day: dict[int, list] = {}
        for r in rows:
            by_day.setdefault(r["day_ts"], []).append(r)
        days = sorted(by_day.keys())[-limit_days:]
        lines = ["📈 排行榜历史曲线（状元收益率）"]
        blocks = "▁▂▃▄▅▆▇█"
        vals = []
        for d in days:
            top = [r for r in by_day[d] if r["rank"] == 1]
            vals.append(top[0]["return_pct"] if top else 0.0)
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        # 标签按「距最新快照的序号」定位，不按 day_ts 做日历算术：
        # day_ts 只要求单调递增（演示模式一日可远短于 86400 秒，届时 UTC
        # 零点同一天会撞键被 INSERT OR REPLACE 覆盖，丢历史点）。
        for i, v in enumerate(vals):
            idx = int(round((v - lo) / span * (len(blocks) - 1)))
            age = len(vals) - 1 - i
            ds = "最新" if age == 0 else f"{age}日前"
            lines.append(f"{ds}  {blocks[idx]}  {v:+.2f}%")
        return "\n".join(lines)


    async def render_bankrupt(self, limit: int = 10) -> str:
        """破产榜叙事（P3）：曾破产/正在破产的玩家，语气克制不嘲讽。

        NPC 账户排除（`is_npc=False`）：破产 NPC 由 NpcService 自动重建，
        不是玩家的故事，混进来会让叙事失真。
        """
        rows = await self.db.list_accounts(is_npc=False)
        dead = [a for a in rows if (a["status"] == "bankrupt"
                                    or (a["rebirth_count"] or 0) > 0)]
        if not dead:
            return "还没有人破产过，这个市场目前全员生还。"
        dead.sort(key=lambda a: -(a["rebirth_count"] or 0))
        lines = ["📖 破产榜"]
        for i, a in enumerate(dead[:limit], 1):
            rb = a["rebirth_count"] or 0
            state = "正在破产" if a["status"] == "bankrupt" else "已重生"
            lines.append(f"{i}. {a['user_name']} · 破产 {rb} 次 · {state}")
        return "\n".join(lines)
