"""Conditional event lifecycle, evidence, public news and tagged cashflows."""
from __future__ import annotations
import math
import copy
import numpy as np
from .causal_state import key,uniform

EVENT_TYPES=('contract','research','acquisition','governance','refinancing','supply','cyber','weather','unlock')
TITLES={'contract':'订单竞标','research':'产品研发','acquisition':'并购整合','governance':'治理核查','refinancing':'债务再融资',
        'supply':'供应链调整','cyber':'系统与网络安全','weather':'生产环境风险','unlock':'限售股解禁'}

def u(s,identity,channel=0):
    return float(uniform(s['seed'],key(identity),np.array([key('event')],dtype=np.uint64),channel)[0])

def emit(s,kind,headline,scope,targets,severity=1,stage='confirmed',facts=None,event_id=None,detail=None):
    s['public_seq']+=1
    row={'seq':s['public_seq'],'event_id':event_id or f"public-{s['public_seq']}",'kind':kind,'headline':headline,
         'scope':scope,'targets':[s['profile']['codes'][int(i)] for i in targets],
         'severity':int(severity),'stage':stage,'day':s['day'],'fraction':round(s['fraction'],6),
         'published_tick':s['tick'],'effective_tick':s['tick']+2,'facts':facts or {}}
    if detail is not None:
        allowed=('version','category','category_label','subtype','title','project','source','background','reason','evidence','region','counterparty','subject','industry','channel_label','timeline','metrics','boundary','action','development','next','outcome','parent_event_id','planned_day')
        row['public_detail']={k:copy.deepcopy(detail[k]) for k in allowed if k in detail}
    s['public_news'].append(row);s['public_news']=s['public_news'][-512:]
    s['news_pending'].append(row)
    return row

def queue_value(s,event,value):
    s.setdefault('pending_updates',[]).append({'tick':s['tick']+2,'event_id':event['id'],'value':float(value),'cash_paid':event.get('cash_paid',0.)})

def expected(e):
    if e.get('catalog_version'):
        value=e['actual'] if e['resolved'] else e['q']*e['win']+(1-e['q'])*e['lose']
        return value-e.get('cash_paid',0.)
    if e['resolved']:return e['actual']*max(0.,1-e['paid']/e['duration'])
    return e['q']*e['win']+(1-e['q'])*e['lose']

def create_event(s,i,kind='contract',immediate=False):
    from .event_world import new_event
    return new_event(s,i,kind,immediate)

def advance_events(s):
    pending=s.setdefault('pending_updates',[]);remaining=[];events={e['id']:e for e in s['events']}
    for item in pending:
        if item['tick']>s['tick']:remaining.append(item)
        elif item['event_id'] in events:
            e=events[item['event_id']];e['priced_value']=item['value']-(e.get('cash_paid',0.)-item.get('cash_paid',0.))
    s['pending_updates']=remaining
    now=s['day']+s['fraction']
    for e in s['events']:
        if e.get('catalog_version'):
            from .event_world import advance_extended
            advance_extended(s,e,now);continue
        if e['resolved'] or e['completed']:continue
        i=e['i'];code=s['profile']['codes'][i];kind=e['type']
        if now>=e['resolve']:
            e['resolved']=True;e['stage']=3;e['resolution_day']=s['day']
            # New terms can make a successful outcome economically disappointing.
            terms=.65+.55*u(s,e['id']+':terms',9)
            e['actual']=e['win']*terms if e['truth'] else e['lose']
            if kind=='refinancing' and not e['truth']:
                s['credit_bad_days'][i]+=3
            emit(s,kind,f'公司 {code} 的{TITLES[kind]}结果确认：'+('进展达成，需结合实际条件评估' if e['truth'] else '未达原定目标，后续影响将逐步兑现'),
                'stock',[i],severity=3 if abs(e['actual'])/max(float(s['price'][i]),.01)>.1 else 2,stage='confirmed',event_id=e['id'])
            queue_value(s,e,expected(e));s['audit']['events_resolved']+=1
        elif now>=e['next'] and e['stage']<2:
            stage=e['stage'];positive=u(s,e['id']+f':evidence:{stage}',10)<(.76 if e['truth'] else .24)
            likelihood=.76 if positive else .24
            q=e['q'];e['q']=q*likelihood/max(q*likelihood+(1-q)*(1-likelihood),1e-12)
            e['stage']+=1;e['next']=now+.5+u(s,e['id']+f':delay:{stage}',11)
            emit(s,kind,f'公司 {code} 的{TITLES[kind]}出现'+('积极进展，最终结果仍未确认' if positive else '不确定迹象，需等待进一步披露'),
                'stock',[i],stage='progress' if positive else 'uncertain',event_id=e['id'])
            queue_value(s,e,expected(e))
    revalue(s)

def revalue(s):
    out=np.zeros(len(s['price']))
    for e in s['events']:
        for index,weight in e['weights'].items():out[int(index)]+=e['priced_value']*weight
    s['public_event_value']=out

def cashflows(s):
    """Amortize identified finite event cashflows; no second earnings shock."""
    cash=np.zeros(len(s['price']))
    for e in s['events']:
        if e.get('catalog_version'):
            from .event_world import extended_payment
            payment=extended_payment(s,e)
            if payment is not None:
                for index,weight in e['weights'].items():
                    j=int(index);cash[j]+=payment*weight*s['shares'][j]
                channel=e['channel'];stats=s['event_statistics']['channel_cash']
                stats[channel]=stats.get(channel,0.)+payment*s['shares'][e['i']]
            continue
        if not e['resolved'] or e['completed'] or s['day']<=e['resolution_day']:continue
        # A minimum two-tick public staging period precedes financial realization.
        if any(x['event_id']==e['id'] for x in s.get('pending_updates',[])):continue
        payment=e['actual']/e['duration'];e['paid']+=1
        e['priced_value']=e['actual']*max(0.,1-e['paid']/e['duration'])
        for index,weight in e['weights'].items():
            j=int(index);cash[j]+=payment*weight*s['shares'][j]
        if e['paid']>=e['duration']:
            e['completed']=True
            if e['type']=='research' and e['truth']:
                s['productivity'][e['i']]+=.004
                s['public_growth'][e['i']]=min(.045,s['public_growth'][e['i']]+.001)
            emit(s,e['type'],f"公司 {s['profile']['codes'][e['i']]} 的{TITLES[e['type']]}本阶段兑现完成",'stock',[e['i']],stage='realized',event_id=e['id'])
    s['public_event_cash']+=cash;s['event_book']+=cash
    revalue(s)
    # Paid events have no remaining cashflows and need not inflate checkpoints.
    s['events']=[e for e in s['events'] if not e['completed']]
    return cash

def daily_events(s):
    p=s['profile'];day=s['day'];keys=p['keys'];macro=s['macro'];credit=max(0.,macro[3])
    from .event_world import daily_extended_events
    daily_extended_events(s)
    accidents=uniform(s['seed'],day,keys,62)
    for i in np.flatnonzero((accidents<.00015*(p['climate']+p['cyber'])) & s['alive']):
        create_event(s,int(i),'weather' if p['climate'][i]>p['cyber'][i] else 'cyber',True)
    for i in np.flatnonzero(s['debt_due']-day==5):
        emit(s,'debt_calendar',f"公司 {p['codes'][i]} 五个交易日后面临本期债务到期窗口",'stock',[int(i)],stage='scheduled')
    if day%21==18:
        emit(s,'policy_calendar','政策例会将在三个交易日后举行，政策结果尚未确定','market',[],stage='scheduled')
    if day%21==0:
        # Only observed decision is public; rate path itself evolved causally.
        s['public_macro'][2]=s['macro'][2]
        emit(s,'policy','政策例会公布利率决定，融资条件与估值预期更新','market',[],severity=2,stage='confirmed',facts={'政策利率':f'{(.045+macro[2])*100:.2f}%'})
    s['public_supply']*=math.exp(-1/3)
    unlock_date=np.array([key('unlock:'+c)%252 for c in p['codes']])
    for i in np.flatnonzero(((unlock_date-day)%252==3) & s['alive']):
        emit(s,'unlock_calendar',f"公司 {p['codes'][i]} 的部分限售股计划在三个交易日后解禁",'stock',[int(i)],stage='scheduled')
    for i in np.flatnonzero((unlock_date==day%252) & s['alive']):
        released=min(int(s['shares'][i]*.005),int(s['locked_inventory'][i]))
        s['locked_inventory'][i]-=released;s['house_inventory'][i]+=released
        s['public_supply'][i]-=.004*p['concentration'][i]
        emit(s,'unlock',f"公司 {p['codes'][i]} 的已公告限售股解禁进入流通，交易供给可能变化",'stock',[int(i)],stage='implementation')
    if day%63==0:
        ranks=np.argsort(np.argsort(s['price']*s['shares']*p['liquidity'])).astype(float)/max(1,len(keys)-1)
        p['passive']=.7*p['passive']+.3*ranks
        emit(s,'index_rebalance','指数季度调整进入执行窗口，被动资金将分批调仓','market',[],stage='implementation')
    # Expose known reporting calendar without private numbers or direction.
    if day%7==0:
        upcoming=[int(i) for i in np.flatnonzero(((s['report_offset']-day)%63<=3) & s['alive'])]
        if upcoming:emit(s,'earnings_calendar','未来三个交易日有企业计划披露经营报告','market',upcoming,stage='scheduled')
