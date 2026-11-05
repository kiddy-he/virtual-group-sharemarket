"""Offline help card using only procedural shapes and installed fonts."""
from pathlib import Path
import re
import hashlib
import json
import shutil

HELP_STYLE = "public-rules-card-v1"
HELP_CAPABILITIES_VERSION = 2

from .chart import FONT_CANDIDATES


def help_sections(cfg):
    day = (f'常开模式：每 {cfg.day_seconds / 60:g} 分钟为一个交易日。'
           if cfg.market_mode == '247' else '时段模式：按北京时间交易时段推进。')
    return [
        ('01  从这里开始♪', [
            f'首次发送 /fx 开户，即可领取 {format(cfg.initial_cash,",.2f").rstrip("0").rstrip(".")} {cfg.currency}初始资金。',
            '在已开通的群内使用 /fx；是否需要 @ 机器人由接入端决定。',
            '所有操作以 /fx 开头，前缀后留空格。发送 /fx 或 /fx 帮助可查看本图。',
        ]),
        ('02  把这些小指令收好吧', [
            '/fx 开户                创建自己的账户',
            '/fx 行情                全部股票行情长图、日K线与历史涨幅',
            '/fx 行情 银行           仅看某板块/行业的行情长图',
            '/fx 行情 600003         仅看某只股票的行情长图',
            '/fx 新闻 银行           仅看该行业直接关联的快讯',
            '/fx 新闻 600003         仅看某只股票的关联快讯',
            '/fx 搜索 东方           按名称或代码查股票',
            f'/fx 买入 600003 {cfg.lot_size}股    按市价保护规则委托',
            f'/fx 买入 600003 {cfg.lot_size}股 限价8.80',
            f'/fx 卖出 600003 {cfg.lot_size}股    卖出可卖持仓',
            '/fx 持仓                查看自己的持仓',
            '/fx 委托                查询订单与订单号',
            '/fx 撤单 订单号          撤销自己的未成交委托',
            '/fx 签到                领取每日奖励',
        ]),
        ('03  下单前，和我约定这些规则', [
            f'买入数量须为 {cfg.lot_size} 股整数倍；卖出零股仅支持一次卖完该股全部持仓。',
            '股票与股数需要写清楚；限价可省略，集合竞价阶段必须指定限价。',
            'T+1：当日买入的股票，下一交易日才能卖出。卖出所得可继续买股。',
            '委托可能部分成交；未成交部分可撤单，日终自动到期。',
            f'双向佣金万 {cfg.commission_rate * 10000:g}，每单累计最低 {cfg.commission_min:g} 元。',
            f'卖出印花税 {cfg.stamp_tax_rate * 100:g}%，双向过户费 {cfg.transfer_fee_rate * 100:g}%。',
            f'常规涨跌幅：主板 ±{cfg.limit_main * 100:g}%，创业/科创 ±{cfg.limit_growth * 100:g}%，'
            f'北交所 ±{cfg.limit_bse * 100:g}%，ST ±{cfg.limit_st * 100:g}%；IPO首日另有规则。',
            day,
        ]),
        ('04  还有这些功能等着你', [
            '/fx 资金  ·  /fx 成交  ·  /fx 自选  ·  /fx 排行',
            '/fx 成就  ·  /fx 道具（购买、出售、使用）',
            '每日任务、赛季、加速卡已下线；历史记录保留。',
            '群内个人资金、持仓等结果将私聊交付。',
            'IPO和融资融券以市场的开放状态为准。',
            '纯虚拟市场：不使用真实行情、真实资金，不构成投资建议。',
        ]),
    ]


def help_text(cfg):
    return '虚拟群股市 · 纯模拟行情与资金\n/fx 使用说明\n\n' + '\n\n'.join(
        title + '\n' + '\n'.join(lines) for title, lines in help_sections(cfg))


def render_help(path, cfg):
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
    def font(size):
        for candidate in FONT_CANDIDATES:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        raise RuntimeError('Chinese font unavailable')

    width, margin = 1200, 62
    body, small, title_font, heading = font(30), font(25), font(66), font(36)
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    def wrap(text, max_width):
        lines, current = [], ''
        for char in re.findall(r'[A-Za-z0-9/.+%±]+|.', text):
            if current and scratch.textlength(current + char, font=body) > max_width:
                if char in '。，；：！？、）' and len(current) > 1:
                    lines.append(current[:-1]); current = current[-1] + char
                else:
                    lines.append(current); current = char
            else:
                current += char
        if current:
            lines.append(current)
        return lines

    sections = []
    for title, items in help_sections(cfg):
        lines = [wrap(item, width - margin * 2 - 66) for item in items]
        height = 94 + sum(len(item) * 46 + 13 for item in lines) + 18
        sections.append((title, lines, height))
    height = 691 + sum(item[2] + 24 for item in sections) + 68
    im = Image.new('RGB', (width, height), '#fff7fb')
    gradient = ImageDraw.Draw(im)
    for gy in range(height):
        t = gy / height
        gradient.line((0, gy, width, gy), fill=(255, round(247 - 4*t), round(251 + 3*t)))
    d = ImageDraw.Draw(im)
    # Procedural panels: no character portraits or external artwork are distributed.
    for idx, (label, subtitle, accent, tint) in enumerate([
        ('交易', '账户 · 委托 · 撮合', '#ae5d96', '#fbe8f3'),
        ('行情', '分行业 · 日K · 盘口', '#618f87', '#e6f4ed'),
        ('事件', '公开信息 · 虚拟新闻', '#976c5c', '#f5ece0'),
    ]):
        cx, top = margin + idx * 363, 261
        d.rounded_rectangle((cx, top, cx+350, top+270), radius=26, fill=tint)
        d.text((cx+45, top+50), label, font=title_font, fill=accent)
        d.text((cx+25, top+180), subtitle, font=small, fill=accent)
    d.rounded_rectangle((margin, 39, margin + 224, 90), radius=20, fill='#ecdafa')
    d.text((margin + 22, 47), '/fx · SIM', font=small, fill='#784b9d')
    d.text((margin, 123), '群股市', font=title_font, fill='#693f87')
    d.text((margin, 206), '虚拟群股市 · 纯模拟行情与资金', font=small, fill='#986185')
    d.rounded_rectangle((margin, 600, width-margin, 654), radius=17, fill='#f0e5fa')
    d.text((margin+21, 611), '发送 /fx 帮助，就能随时回来找我哦♪', font=small, fill='#78578f')
    y = 691
    for title, items, box_height in sections:
        d.rounded_rectangle((margin, y, width-margin, y+box_height), radius=24, fill='#fffdfd', outline='#ecd1e5', width=2)
        d.text((margin+30, y+22), title, font=heading, fill='#aa548a')
        line_y = y+89
        for lines in items:
            for line in lines:
                d.text((margin+33, line_y), line, font=body, fill='#584c68')
                line_y += 46
            line_y += 13
        y += box_height+24
    d.text((margin, height-54), '规则以当前市场配置为准哦♪', font=small, fill='#95799d')
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    im.save(target, 'PNG', optimize=True)
    return target
