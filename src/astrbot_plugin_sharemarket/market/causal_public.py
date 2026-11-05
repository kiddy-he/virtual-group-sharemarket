from .stocks import STOCK_POOL
"""Explicit public projection. Never serialize whole world/event dictionaries."""

def _public_text(value):
    text = str(value)
    for old, new in (
        ('虚拟企业 ', '公司 '), ('虚拟群股市', '群股市'), ('虚拟股市', '股市'),
        ('虚拟市场', '本市场'), ('虚拟指数', '指数'), ('虚拟经济', '经济'),
        ('虚拟交易日', '交易日'), ('虚构新闻', '市场快讯'), ('（模拟）', ''),
        ('模拟市场', '本市场'), ('游戏', '市场'), ('玩法', '功能'), ('演示', '常开'),
        ('虚构', '市场'), ('模拟', '市场'), ('虚拟', '市场'),
    ):
        text = text.replace(old, new)
    return text

def query_public(s,action,p,engine):
    if action=='calendar':
        day=s['day'];entries=[]
        for i,code in enumerate(s['profile']['codes']):
            if not s['alive'][i]:continue
            distance=int((s['report_offset'][i]-day)%63) or 63
            if distance<=5:entries.append({'day':day+distance,'code':code,'type':'经营报告计划'})
            if 0<int(s['debt_due'][i])-day<=5:entries.append({'day':int(s['debt_due'][i]),'code':code,'type':'债务到期窗口'})
        # Only already disclosed plans enter the calendar. Private resolution
        # times, probabilities and outcomes are deliberately excluded.
        for event in s.get('events',[]):
            detail=event.get('public_detail',{})
            planned=detail.get('planned_day')
            if not event.get('resolved') and type(planned) is int and day<=planned<=day+10:
                entries.append({'day':planned,'code':s['profile']['codes'][event['i']],
                                'type':detail.get('project','专项事项')+'计划复核（可能延期）','event_id':event['id']})
        entries.sort(key=lambda x:(x['day'],x['code']))
        return {'data':entries[:40],'text':'市场公开日历（日期可知，结果未知）：\n'+('\n'.join(f"第{x['day']}日 {x['code']} {x['type']}" for x in entries[:40]) or '近期暂无已登记事项。')}
    if action=='event':
        eid=str(p.get('event_id') or '')
        if not eid or len(eid)>80:raise ValueError('请提供公开新闻中的事件编号。')
        rows=[{**r,'headline':_public_text(r['headline'])} for r in s['public_news'] if r['event_id']==eid]
        return {'data':rows,'text':'已公开事件进展：\n'+('\n'.join(f"#{r['seq']} [{r['stage']}] {r['headline']}" for r in rows) or '未找到已公开的事件记录。')}
    sector=str(p.get('keyword') or '')
    if sector not in s['profile']['sectors']:raise ValueError('请提供准确板块名称。')
    codes=[c for c in s['profile']['codes'] if engine.quotes.get(c) and STOCK_POOL[c].sector==sector]
    rows=[{'code':c,'price':engine.quotes[c].price,'change_pct':engine.quotes[c].change_pct} for c in codes]
    return {'data':rows,'text':f'{sector} 板块：\n'+'\n'.join(f"{r['code']} {r['price']:.2f}元 {r['change_pct']:+.2f}%" for r in rows)}
