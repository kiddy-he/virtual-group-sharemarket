"""Frozen, complete market overview; Pillow reads no live engine/DB state."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .chart import FONT_CANDIDATES

STYLE = 'sector-large-candles-v4'
WIDTH, ROW_HEIGHT = 1600, 252
TZ = timezone(timedelta(hours=8))


def pct(value, base):
    return (value / base - 1) * 100 if value is not None and base is not None and base > 0 else None


def stock_snapshot(stock, quote, history, engine):
    history = [{'ts': int(r['ts']), **{key: float(r[key]) for key in ('open','high','low','close')}} for r in history]
    current = ({'open': quote.open, 'high': quote.high, 'low': quote.low, 'close': quote.price}
               if quote is not None and not engine.is_delisted(stock.code) else None)
    closes = [r['close'] for r in history]
    historical = {str(n): pct(closes[-1], closes[-n-1]) if len(closes) > n else None for n in (1, 5, 20)}
    states = []
    if engine.is_delisted(stock.code): states.append('退市')
    elif engine.is_suspended(stock.code): states.append('停牌')
    if engine.st_flag.get(stock.code, stock.is_st): states.append('ST')
    if quote is None: states.append('暂无报价')
    return {'code': stock.code, 'name': stock.name, 'sector': stock.sector, 'industry': stock.industry,
            'price': quote.price if quote else None,
            'prev_close': quote.prev_close if quote else None,
            'change_pct': pct(quote.price, quote.prev_close) if quote else None,
            'history_pct': historical, 'history': history, 'current_candle': current, 'states': states}


def dimensions(snapshot):
    sectors = len({r['sector'] for r in snapshot['stocks']})
    return WIDTH, 450 + sectors * 98 + len(snapshot['stocks']) * ROW_HEIGHT + 112


def draw_daily_candles(draw, row, left, top, width, height):
    """Draw recorded OHLC only; the outlined last bar is the live, unclosed day."""
    bars = row['history'] + ([row['current_candle']] if row.get('current_candle') else [])
    if not bars:
        return False
    baseline = row.get('prev_close') or bars[0]['open']
    low = min([b['low'] for b in bars] + [baseline])
    high = max([b['high'] for b in bars] + [baseline])
    padding = max((high-low)*.08, abs(high)*.001, .001)
    low -= padding; high += padding
    def yy(price): return top + height - (price-low)/(high-low)*height
    draw.line((left, yy(baseline), left+width, yy(baseline)), fill='#e7dde7', width=1)
    step = width/max(22,len(bars))
    start = left+width-step*len(bars)
    half = max(3, min(13, step*.32))
    for i, bar in enumerate(bars):
        x = start+step*(i+.5)
        color = '#d84b6a' if bar['close']>bar['open'] else '#18816f' if bar['close']<bar['open'] else '#85758d'
        draw.line((x, yy(bar['high']), x, yy(bar['low'])), fill=color, width=2)
        a,b = sorted((yy(bar['open']),yy(bar['close'])))
        if b-a<1: a-=.5;b+=.5  # make a doji visible without inventing a price move
        draw.rectangle((x-half,a,x+half,b),fill=color)
        if i==len(bars)-1 and row.get('current_candle'):
            draw.rectangle((x-half-2,top-1,x+half+2,top+height+1),outline='#b88b39',width=1)
    return True


def render_overview(path, snapshot):
    from PIL import Image, ImageDraw, ImageFont
    fonts = {}
    def font(size):
        if size not in fonts:
            candidate = next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)
            fonts[size] = ImageFont.truetype(str(candidate), size) if candidate else ImageFont.load_default()
        return fonts[size]
    bg, ink, muted, red, green = '#fff8fc', '#443650', '#85758d', '#d84b6a', '#18816f'
    image = Image.new('RGB', dimensions(snapshot), bg)
    d = ImageDraw.Draw(image)
    def text(x, y, value, size=26, color=ink): d.text((x, y), str(value), font=font(size), fill=color)
    def change(x, y, value, missing='数据不足'):
        text(x, y, f'{value:+.2f}%' if value is not None else missing, 27,
             red if value is not None and value > 0 else green if value is not None and value < 0 else muted)
    def fit(value, width, size):
        while value and d.textlength(value, font=font(size)) > width: value = value[:-1]
        return value
    stamp = datetime.fromtimestamp(snapshot['timestamp'], TZ).strftime('%Y-%m-%d %H:%M:%S')
    d.rectangle((0, 0, WIDTH, 172), fill='#f0dcef')
    text(34, 24, '群星行情手账', 52)
    text(36, 100, '爱莉希雅的花笺 · 帕朵的交易清单 · 伊甸的金色乐章', 27)
    scope = snapshot.get('scope', {})
    label = (scope.get('label', '') + ' · 共') if scope.get('filtered') else '全部'
    title = f'{label} {len(snapshot["stocks"])} 只股票   |   交易日 #{snapshot["day"]}   |   {snapshot["phase"]}'
    text(36, 192, title, 26 if d.textlength(title, font=font(31)) > WIDTH-72 else 31)
    text(36, 243, f'快照 {stamp} 北京时间   ·   Tick #{snapshot["tick"]}' + ('   ·   行情已暂停' if snapshot['paused'] else ''), 25, muted)
    average = '所选股票等权涨幅' if scope.get('filtered') else '大盘'
    average_change = snapshot['market_change']
    change_text = f'{average_change:+.2f}%' if average_change is not None else '暂无报价'
    text(36, 288, f'上涨 {snapshot["advancers"]}   平盘 {snapshot["flat"]}   下跌 {snapshot["decliners"]}   {average} {change_text}', 28)
    text(36, 337, '实时涨幅 = 最新价 / 昨收 − 1；历史涨幅截至最近收盘，按虚拟交易日计算。', 25, muted)
    candles = any('current_candle' in r for r in snapshot['stocks'])
    chart_note = '日K：历史OHLC + 当日未收盘。' if candles else '曲线：日收盘 + 实时点。'
    text(36, 378, '历史1/5/20日 = 最近收盘 / 对应天数前收盘 − 1；未复权。' + chart_note, 24, muted)
    sectors = list(dict.fromkeys(r['sector'] for r in snapshot['stocks']))
    y = 450
    for sector in sectors:
        rows = [r for r in snapshot['stocks'] if r['sector'] == sector]
        d.rounded_rectangle((22, y, WIDTH-22, y+43), radius=12, fill='#e9dcef')
        text(36, y+2, f'{sector}   /   {len(rows)} 只', 28)
        y += 52
        for x, label in [(36, '股票 / 实时与历史涨幅'), (636, '近21日K线 + 当日' if candles else '近21次收盘 → 实时')]:
            text(x, y, label, 23, muted)
        y += 46
        for i, row in enumerate(rows):
            if i % 2 == 0: d.rectangle((22, y, WIDTH-22, y+ROW_HEIGHT), fill='#ffffff')
            text(36, y+3, fit(row['name'], 490, 32), 32)
            status = ' · '.join(row['states'])
            text(36, y+49, row['code'] + ('  '+status if status else ''), 23, muted)
            text(36, y+93, f'最新价 {row["price"]:.2f} 元' if row['price'] is not None else '最新价 暂无报价', 27)
            text(36, y+136, '实时涨幅', 26, muted);change(190, y+136, row['change_pct'], '暂无报价')
            for x, n in [(36, 1), (220, 5), (408, 20)]:
                text(x, y+180, f'历史{n}日', 22, muted)
                change(x, y+211, row['history_pct'][str(n)], '暂无日线' if not row['history'] else f'不足{n}日')
            history = row['history']
            left, top, w, h = 636, y+38, 890, 170
            text(left, y+1, '历史日K线 + 当日未收盘' if row.get('current_candle') else '历史日K线', 23, muted)
            if 'current_candle' in row:
                if draw_daily_candles(d, row, left, top, w, h):
                    live = ' + 当日未收盘' if row.get('current_candle') else ''
                    text(left, y+216, f'历史{len(history)}根日K{live} · 每只股票独立价格坐标', 20, muted)
                else: text(left, y+90, '暂无K线与报价', 25, muted)
            elif history:
                closes = [r['close'] for r in history]
                values = [pct(c, closes[0]) for c in closes]
                if row['price'] is not None: values.append(pct(row['price'], closes[0]))
                if all(v is not None for v in values):
                    lo, hi = min(values+[0]), max(values+[0]); span = max(hi-lo, .1)
                    def yy(v): return top+h-(v-lo)/span*h
                    d.line((left, yy(0), left+w, yy(0)), fill='#e7dde7', width=1)
                    points = [(left+j*w/max(1, len(values)-1), yy(v)) for j, v in enumerate(values)]
                    if len(closes)>1: d.line(points[:len(closes)], fill='#ac7bb5', width=3)
                    if len(points)>len(closes): d.line(points[-2:], fill=red if values[-1]>=values[-2] else green, width=3)
                    px, py = points[-1];d.ellipse((px-4,py-4,px+4,py+4), fill='#b88b39')
                    text(left, y+216, f'{len(closes)}次收盘 | 末值{values[-1]:+.2f}%（相对首点）', 20, muted)
                else: text(left, y+90, '历史价格基准不可用', 25, muted)
            else: text(left, y+90, '暂无历史收盘数据', 25, muted)
            y += ROW_HEIGHT
    legend = ('日K实体：开盘→收盘；影线：当日最高/最低。红涨、绿跌、灰平；金框：当日未收盘。'
              if candles else '粉紫线：历史收盘走势 · 红/绿末段：实时变化 · 金点：快照最新价。')
    text(36, y+25, legend, 24, muted)
    text(36, y+65, '本图为虚拟游戏行情；一次查询生成一个固定快照，发送 /fx 行情 获取更新。', 24, muted)
    image.save(path, 'PNG', optimize=True)


def fallback_text(snapshot):
    """Keep all stock results usable when Pillow/font/disk rendering fails."""
    def value(v): return f'{v:+.2f}%' if v is not None else '数据不足'
    lines = [f"查询范围：{snapshot.get('scope', {}).get('label', '全市场')}，共{len(snapshot['stocks'])}只股票。", '行情图生成失败，以下为同一快照的完整行情。历史涨幅截至最近收盘，未复权。']
    for r in snapshot['stocks']:
        price = f'{r["price"]:.2f}' if r['price'] is not None else '暂无报价'
        hist = ' / '.join(value(r['history_pct'][str(n)]) for n in (1, 5, 20))
        lines.append(f'{r["name"]}({r["code"]}) {price}元 实时{value(r["change_pct"])} 历史1/5/20日{hist} '+ ' '.join(r['states']))
    return '\n'.join(lines)


def partition_overview(snapshot):
    """One immutable image per major sector; never re-read prices or histories."""
    sectors=list(dict.fromkeys(r['sector'] for r in snapshot['stocks']))
    if len(sectors)<=1:return [snapshot]
    parts=[]
    for sector in sectors:
        rows=[r for r in snapshot['stocks'] if r['sector']==sector]
        changes=[r['change_pct'] for r in rows if r['change_pct'] is not None]
        scope={**snapshot.get('scope',{}),'label':sector+'板块','filtered':True,'codes':[r['code'] for r in rows]}
        parts.append({**snapshot,'scope':scope,'stocks':rows,'advancers':sum(v>0 for v in changes),
                      'decliners':sum(v<0 for v in changes),'flat':sum(v==0 for v in changes),
                      'quoted_count':len(changes),'unquoted_count':len(rows)-len(changes),
                      'market_change':sum(changes)/len(changes) if changes else None})
    return parts
