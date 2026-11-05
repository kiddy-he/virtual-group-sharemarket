"""User-facing projections: business data is never serialized as a chat reply."""
import math

RETIRED_ACTIONS = {
    'tasks':'每日任务功能已下线。交易进度统计尚未接通全部成交路径，当前不再记录任务或发放任务奖励。',
    'season':'赛季功能已下线。积分统计尚未接通全部成交路径，历史积分与领奖记录保留。',
    'claim_season':'赛季功能已下线，当前不再发放赛季奖励。历史积分与领奖记录保留。',
}
RETIRED_PROPS = {'speed_card':'加速卡未接通日常任务完成流程，已下线；已有库存仍可按原回售价出售。'}
PUBLIC_PLAY_ACTIONS = ('checkin','achievements','props','buy_prop','sell_prop','use_prop')

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('invalid display amount')
    return f'{value:,.2f}'.rstrip('0').rstrip('.')

def play_text(action,data,currency='金币'):
    from .props import PROP_BY_ID
    if action in RETIRED_ACTIONS:return RETIRED_ACTIONS[action]
    if action=='checkin':
        return f'签到成功，奖励{number(data["reward"])}{currency}已到账。连续签到{data["new_streak"]}天；每天可签到一次。'
    if action=='achievements':
        lines=[f'成就记录：本次新达成{len([i for i in data["achievements"] if i.get("newly_claimed")])}项，奖励{number(data["reward"])}{currency}已到账。']
        for item in data['achievements']:
            state='已达成' if item['done'] else '未达成'
            lines.append(f'{item.get("name","成就")}：{state}。{item.get("desc","")}；进度：{item.get("progress","暂无记录")}。')
        return '\n'.join(lines)
    if action=='props':
        lines=['今日道具推荐（每日轮换展示；其他已知道具也可按编号购买）：']
        for item in data['shop']['items']:
            lines.append(f'{item["name"]}（{item["prop_id"]}）：售价{number(item["price"])}{currency}，回售价{number(item["sell_price"])}{currency}；今日还可购买{item["left_today"]}件。{item["description"]}。')
        lines.append('我的道具：')
        owned=[item for item in data['owned'] if item['quantity']>0]
        lines.extend(f'{item["name"]}（{item["prop_id"]}）：{item["quantity"]}件'+('；已下线，仅可出售。' if item['prop_id'] in RETIRED_PROPS else '。') for item in owned)
        if not owned:lines.append('暂无道具。')
        lines+=['购买：/fx 购买 道具编号 数量','出售：/fx 出售 道具编号 数量','使用：/fx 使用 道具编号；使用会消耗一件道具。']
        return '\n'.join(lines)
    item=PROP_BY_ID.get(data.get('prop_id'),{});name=item.get('name','道具')
    if action=='buy_prop':
        return f'成功购买{name}{data["quantity"]}件，已扣除{number(data["total_price"])}{currency}；可用余额{number(data["remaining_cash"])}{currency}。'
    if action=='sell_prop':
        return f'成功出售{name}{data["quantity"]}件，获得{number(data["total_income"])}{currency}，已到账；可用余额{number(data["remaining_cash"])}{currency}。'
    if action=='use_prop':
        effect=data['effect'];kind=effect['type'];lines=[f'成功使用{name}1件，剩余{data["remaining_quantity"]}件。']
        if kind=='grant_cash':lines.append(f'本次奖励{number(effect["amount"])}{currency}已到账。')
        elif kind=='fee_immunity':lines.append('下一笔委托免交易手续费；效果在提交委托时消耗，之后撤单不会返还该效果。同类效果不叠加，后使用的覆盖此前效果。')
        elif kind=='fee_discount':lines.append('下一笔委托的交易手续费打5折；效果在提交委托时消耗，之后撤单不会返还该效果。同类效果不叠加，后使用的覆盖此前效果。')
        elif kind=='trend_preview':
            lines.append('以下仅为随机生成的趣味区间，不读取未来股价，不是本市场后续走势预测：')
            lines.extend(f'第{p["day"]}天样例涨跌幅：{p["change_pct"]*100:+.2f}%。' for p in effect['preview'])
        elif kind=='review':
            lines.append(f'最近{effect["trades_count"]}笔成交中，已实现盈利{effect["win"]}笔、已实现亏损{effect["loss"]}笔，已实现盈亏合计{number(effect["total_pnl"])}{currency}。买入记录和零盈亏记录不计入盈利/亏损笔数。')
        else:raise ValueError('unsupported user-facing prop effect')
        return '\n'.join(lines)
    raise ValueError('missing user-facing gameplay projection')

def health_text(health):
    return (f'股市运行状态：已处理{health["ticks"]}次行情更新，待处理请求{health["queue_depth"]}项，'
            f'结算失败{health["settlement_failures"]}次。账本'+('已核对一致。' if health['reconciled'] else '尚未核对一致。')+
            ('最近运行正常。' if not health['last_error'] else '检测到运行错误，请查看本机日志。'))
