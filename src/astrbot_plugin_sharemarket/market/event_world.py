"""Persistent, diversified event lifecycles and bounded incremental cash flows.

Only project facts and observed milestones cross disclose(); truth, payoffs and
random streams never do. Capital plans do not execute shareholder operations.
"""
from __future__ import annotations
import copy
import math
import numpy as np
from .event_catalog import SPECS, CATEGORIES, CHANNELS, ALIASES, CATALOG_VERSION
from .stocks import STOCK_POOL
from .causal_state import key, uniform, VERSION

MANUFACTURING = ('制造','机械','设备','汽车','新能源','电池','光伏','半导体','电子','军工','材料','化工','钢铁','有色','食品','农业','饲料','种业','煤炭','石油','家电','医药')
DIGITAL = ('软件','信息','互联网','电子','半导体','传媒','计算机','通信','银行','证券')
BUSINESS = {
 'bank':('企业结算与资金服务','清算及数据服务资源','结算服务平台'),
 'securities':('机构交易与投资服务','行情数据及交易系统资源','机构交易服务平台'),
 'insurance':('保险承保与客户服务','理赔审核及客户服务资源','企业保险服务产品'),
 'pharma':('医药研发与供应服务','医药原辅料及检验服务','候选医药产品'),
 'medical':('医疗与检验服务','医疗耗材及检验资源','医疗服务支持系统'),
 'software':('企业软件与云服务','云资源及关键软件组件','企业协同平台'),
 'chip':('芯片设计与配套服务','晶圆代工及封装测试资源','新一代控制芯片'),
 'hardware':('电子模块设计与制造','电子元件及封装材料','高可靠电子模块'),
 'air':('航空运输与地面保障','航材及维修备件','航空运维调度系统'),
 'shipping':('航运与港口配套服务','船舶维修及港口资源','货运调度服务'),
 'logistics':('仓储配送与运输服务','运输运力及仓储资源','仓配调度系统'),
 'power':('能源供应与运维服务','电网设备及运维备件','电力运行监测系统'),
 'battery':('电池制造与储能服务','电芯及关键电池材料','储能配套模块'),
 'solar':('光伏设备与配套服务','光伏材料及功率器件','光电转换模块'),
 'machine':('设备制造与工业服务','控制器及机械零部件','工业自动化控制模块'),
 'car':('汽车制造与配套服务','车规零部件及配套材料','汽车配套模块'),
 'food':('食品加工与渠道服务','食品原料及包装材料','新配方食品产品'),
 'feed':('饲料加工与配送服务','饲料原料及营养添加剂','饲料配方产品'),
 'farming':('农业生产与技术服务','种苗及农业配套物资','农业生产配套产品'),
 'retail':('零售渠道与客户服务','品牌货源及配送资源','零售供应管理系统'),
 'education':('职业培训与教学服务','课程内容及教学资源','职业培训课程产品'),
 'media':('内容制作与发行服务','内容授权及制作资源','数字内容服务产品'),
 'property':('建设工程与园区服务','工程材料及施工服务','工程运行管理系统'),
 'materials':('工业材料制造与供应','原材料及工艺配套资源','工业材料产品'),
 'generic':('主营业务配套服务','业务配套资源','主营业务产品'),
}
INDUSTRY_GROUPS = (
 ('bank',('银行',)),('securities',('证券','多元金融')),('insurance',('保险',)),
 ('pharma',('医药','创新药','中药','生物制品','疫苗')),('medical',('医疗服务','医疗器械')),
 ('software',('软件','互联网','计算机','通信')),('chip',('半导体','芯片')),('hardware',('电子','消费电子')),
 ('air',('航空','机场')),('shipping',('航运','港口')),('logistics',('物流',)),('power',('电力','公用事业')),
 ('battery',('电池','储能')),('solar',('光伏',)),('car',('汽车','新能源车')),
 ('machine',('机械','自动化','设备','军工','家电')),('feed',('饲料',)),('farming',('农业','养殖','种业')),
 ('food',('食品','饮料','乳品','白酒','调味品')),('education',('教育',)),('retail',('零售','珠宝','纺织')),
 ('media',('传媒',)),('property',('房地产','建筑','建材')),('materials',('有色','钢铁','新材料','化工','煤炭','石油')),
)


def ensure_event_schema(s):
    """Additive migration: no reroll of financial arrays, prices or old events."""
    s['version']=VERSION
    p=s['profile'];p.setdefault('industries',[STOCK_POOL[c].industry for c in p['codes']])
    p.setdefault('names',[STOCK_POOL[c].name for c in p['codes']])
    s.setdefault('event_cooldowns',{})
    s.setdefault('event_statistics',{'created':{},'resolved':{},'channel_cash':{},'delayed':0,'reopened':0})
    s.setdefault('event_followups',[])
    s['event_catalog_version']=CATALOG_VERSION

def rand(s,identity,channel=0):
    return float(uniform(s['seed'],key(identity),np.array([key('extended-event')],dtype=np.uint64),channel)[0])

def business_group(industry,sector=''):
    for name,tags in INDUSTRY_GROUPS:
        if any(tag in industry for tag in tags):return name
    return 'generic'

def eligible(spec,industry):
    if not spec.industries:return True
    checks={'manufacturing':MANUFACTURING,'digital':DIGITAL,'pharma':('医药','药','生物','疫苗')}
    return any(any(tag in industry for tag in checks.get(group,())) for group in spec.industries)

def subtype_weight(s,i,spec):
    p=s['profile'];category=spec.category;industry=p['industries'][i]
    if not eligible(spec,industry):return 0.
    base=1.
    if category=='research':base*=.35+1.8*p['rd'][i]
    if category=='refinancing':base*=.25+3*min(s['distress'][i],1)+1.8*p['leverage'][i]+max(0.,s['macro'][3])
    if category=='governance':base*=.4+3*(1-p['governance'][i])
    if category=='incident':base*=.30+.6*(p['climate'][i]+p['cyber'][i])
    if category=='capacity':base*=.6+max(0.,s['macro'][0])+.5*p['rd'][i]
    if category=='macro':base*=.25  # Whole-market stories carry broad exposure; keep them scarce.
    if category=='industry':base*=.55
    if spec.channel in ('trade','logistics'):base*=.4+p['export'][i]+p['imports'][i]
    if spec.id=='extreme_weather':base*=.2+1.4*p['climate'][i]
    if spec.id in ('network_outage','data_security'):base*=.2+1.4*p['cyber'][i]
    if spec.id=='payment_collection':base*=.5+p['leverage'][i]
    # Public type-level scarcity prevents the same narrative dominating across companies.
    count=s['event_statistics']['created'].get(spec.id,0)
    base/=math.sqrt(1+count/5)
    return float(base)

def choose_subtype(s,i):
    ensure_event_schema(s);day=s['day'];code=s['profile']['codes'][i];cool=s['event_cooldowns']
    choices=[]
    for spec in SPECS.values():
        if day<cool.get('type:'+code+':'+spec.id,-1) or day<cool.get('category:'+code+':'+spec.category,-1):continue
        if spec.category in ('macro','industry'):
            scope='全市场' if spec.category=='macro' else s['profile']['industries'][i]
            if day<cool.get('scope:'+scope+':'+spec.category,-1):continue
        w=subtype_weight(s,i,spec)
        if w:choices.append((spec,w))
    total=sum(w for _,w in choices)
    if not total:return None
    draw=rand(s,f'select:{day}:{code}',30)*total
    for spec,w in choices:
        draw-=w
        if draw<=0:return spec.id
    return choices[-1][0].id

def exposure_weights(s,i,spec):
    p=s['profile'];anchor=max(float(s['value'][i]),.01);weights={str(i):1.}
    if spec.category in ('macro','industry'):
        targets=[j for j in range(len(p['codes'])) if s['alive'][j] and
                 (spec.category=='macro' or p['industries'][j]==p['industries'][i])]
        weights={}
        for j in targets:
            if spec.channel=='credit':exposure=.3+float(p['leverage'][j])
            elif spec.channel=='trade':exposure=.25+float(p['export'][j]-p['imports'][j])
            elif spec.channel=='cost':exposure=.25-float(p['commodity'][j])*.45
            else:exposure=.3+.4*float(p['beta'][j])
            weights[str(j)]=float(np.clip(exposure,-.6,1.2))*max(float(s['value'][j]),.01)/anchor
    else:
        # These are modeled exposure links, not invented contracts or named buyers.
        for customer,supplier,weight in s['network']:
            if customer!=i:continue
            scale=max(float(s['value'][supplier]),.01)/anchor
            sign=-1 if spec.channel=='cost' else 1
            weights[str(supplier)]=sign*min(.12,float(weight))*scale
        competitors=np.flatnonzero((p['sector']==p['sector'][i]) & (np.arange(len(s['price']))!=i) & s['alive'])
        if len(competitors) and spec.channel in ('order','trade','research','capacity'):
            j=int(competitors[int(rand(s,f'peer:{s["day"]}:{p["codes"][i]}',31)*len(competitors))])
            weights[str(j)]=-.06*max(float(s['value'][j]),.01)/anchor
    return weights

def new_event(s,i,kind='contract',immediate=False,parent=None):
    from .causal_events import queue_value, expected
    ensure_event_schema(s);identity=ALIASES.get(kind,kind)
    if identity not in SPECS:raise ValueError('unknown event subtype: '+str(kind))
    spec=SPECS[identity];p=s['profile'];code=p['codes'][i]
    counts=s.setdefault('event_counters',{});counts[code]=counts.get(code,0)+1
    eid=f'event-{code}-{counts[code]}';s['next_event']+=1
    budget_ratio,benefit,cost,lo,hi=CHANNELS[spec.channel]
    # Public annual cashflow estimate bounds the project. Distressed/penny issuers
    # cannot receive price-independent windfalls; broad stories use smaller stakes.
    annual=max(0.,float(s['public_fcf'][i]))/max(float(s['shares'][i]),1.)
    ceiling=max(.00001,min(float(s['price'][i]),float(s['value'][i]))*.018)
    budget=min(annual*budget_ratio,ceiling)*( .65+.7*rand(s,eid,32))
    if spec.category in ('macro','industry'):budget*=.4
    q=float(np.clip(.35+.35*p['governance'][i]-.18*min(s['distress'][i],1)+.15*(rand(s,eid,33)-.5),.12,.85))
    win=budget*benefit*(.65+.7*rand(s,eid,34));lose=-budget*cost*(.65+.7*rand(s,eid,35))
    now=s['day']+s['fraction'];duration=lo+int(rand(s,eid,36)*(hi-lo+1))
    label,source,reason,channel=CATEGORIES[spec.category]
    industry=p['industries'][i];group=business_group(industry,STOCK_POOL[code].sector)
    business,resource,product=BUSINESS[group];project=spec.project.format(business=business,resource=resource,product=product)
    scope='market' if spec.category=='macro' else 'sector' if spec.category=='industry' else 'stock'
    scope_label='全市场' if scope=='market' else industry if scope=='sector' else p['names'][i]
    e={'id':eid,'root_event_id':parent or eid,'parent_event_id':parent,'type':kind,'subtype':identity,'category':spec.category,'channel':spec.channel,
       'catalog_version':CATALOG_VERSION,'i':int(i),'created':now,'next':now+.45+rand(s,eid,37),
       'resolve':now+2.+rand(s,eid,38)*4,'stage':0,'q':q,'truth':rand(s,eid,39)<q,
       'win':win,'lose':lose,'actual':0.,'resolved':False,'resolution_day':None,'duration':duration,
       'paid':0,'cash_paid':0.,'priced_value':0.,'weights':exposure_weights(s,i,spec),'completed':False,
       'delays':0,'reviews':0,'scope':scope,'scope_label':scope_label,'outcome':None,
       'public_detail':{'version':1,'category':spec.category,'category_label':label,'subtype':identity,'title':spec.title,
          'project':project,'source':source,'background':f'本事项围绕{reason}展开，项目对象为{project}。',
          'reason':f'本轮核验依据为{spec.evidence}，公开目标是确认本阶段可执行条件。',
          'evidence':spec.evidence,'region':('既有服务覆盖区域','本地业务配套区域','跨区域服务衔接范围')[int(rand(s,eid,40)*3)],
          'counterparty':('项目合作方','服务采购方','业务衔接方')[int(rand(s,eid,41)*3)],
          'subject':scope_label,'industry':industry,'channel_label':channel,'timeline':[],
          'planned_day':int(math.ceil(now+2.+rand(s,eid,38)*4)),
          'metrics':{'方案测算规模':f'{budget*float(s["shares"][i]):,.2f}元','首轮计划核验期限':f'{2+int(rand(s,eid,42)*4)}个交易日'},
          'boundary':'本阶段审议通过不等于实际回购、分红、增发或股东交易已执行。' if spec.category=='capital' else '阶段进展不等于最终经营效果或股价方向。'}}
    s['events'].append(e);s['audit']['events_created']+=1
    stats=s['event_statistics']['created'];stats[identity]=stats.get(identity,0)+1
    cooldown=s['event_cooldowns'];cooldown['company:'+code]=s['day']+8
    cooldown['type:'+code+':'+identity]=s['day']+90
    cooldown['category:'+code+':'+spec.category]=s['day']+24
    if scope!='stock':cooldown['scope:'+scope_label+':'+spec.category]=s['day']+(21 if scope=='market' else 12)
    if immediate:
        e.update(truth=False,resolved=True,actual=lose,resolution_day=s['day'],stage=3,outcome='negative')
        disclose(s,e,'unexpected','出现突发业务中断并启动处置',f'{spec.evidence}进入应急核验，当前处置尚未完成。')
        s['audit']['events_resolved']+=1
    else:
        disclose(s,e,'reopened' if parent else 'scheduled','重新启动专项核验' if parent else '启动专项方案与资料核验',f'{spec.evidence}已列入首轮核验，最终结果尚未确认。')
    queue_value(s,e,expected(e));return e

def disclose(s,e,stage,action,development,metrics=None):
    from .causal_events import emit
    detail=copy.deepcopy(e['public_detail']);spec=SPECS[e['subtype']]
    entry={'day':int(s['day']),'stage':stage,'action':action}
    detail['timeline'].append(entry);detail['timeline']=detail['timeline'][-8:]
    if metrics:detail['metrics'].update(metrics)
    detail['action']=action;detail['development']=development
    if stage=='delayed':detail['planned_day']=int(math.ceil(e['resolve']))
    detail['metrics']['计划复核日']=f'第{detail["planned_day"]}个交易日'
    unresolved=stage in ('scheduled','progress','uncertain','delayed','review','reopened')
    detail['next']='下一阶段继续核验执行条件，最终结果尚未确认。' if unresolved else '后续按已确认的执行边界逐步核对经营兑现；不保证价格方向。'
    if stage=='realized':detail['next']='本阶段有限经营影响已计入结束，相关事实保留供后续查阅。'
    if e.get('outcome'):detail['outcome']=e['outcome']
    if e.get('parent_event_id'):detail['parent_event_id']=e['parent_event_id']
    e['public_detail']=copy.deepcopy(detail)
    code=s['profile']['codes'][e['i']]
    # All modeled beneficiaries are disclosed as exposure targets. They are not
    # represented as signed counterparties merely because the network has an edge.
    targets=[int(j) for j in e['weights']] if e['scope']!='stock' else [e['i']]
    severity=3 if stage=='unexpected' or (stage=='terminated' and e['category'] in ('refinancing','incident')) else 2 if stage in ('confirmed','partial','terminated') else 1
    if stage=='unexpected':detail['boundary']+='突发事件的损失范围及后续恢复仍待核实。'
    return emit(s,e['type'],f'{e["scope_label"]}：{spec.title}，{action}',e['scope'],targets,severity=severity,stage=stage,
                facts=detail['metrics'],event_id=e['id'],detail=detail)

def advance_extended(s,e,now):
    from .causal_events import queue_value, expected
    if e['resolved'] or e['completed']:return
    spec=SPECS[e['subtype']]
    if now>=e['resolve']:
        branch=rand(s,e['id']+':resolution:'+str(e['delays']),44)
        if branch<.15 and e['delays']<2:
            e['delays']+=1;e['resolve']=now+1.+rand(s,e['id']+':delay:'+str(e['delays']),45)*2
            s['event_statistics']['delayed']+=1
            disclose(s,e,'delayed','延长补充核验窗口',f'{spec.evidence}仍需补充交叉核验，原定阶段结论延期，最终结果尚未确认。')
            e['q']=float(np.clip(e['q']*.93,.05,.95));queue_value(s,e,expected(e));return
        e.update(resolved=True,stage=3,resolution_day=s['day'])
        if e['truth'] and branch<.38:
            portion=.45+.35*rand(s,e['id'],46);e['actual']=e['win']*portion;e['outcome']='partial'
            disclose(s,e,'partial','部分核验目标达成并缩减后续范围',f'{spec.positive}；本轮仅部分范围得到确认，剩余目标未获通过。',{'阶段完成比例':f'{portion*100:.1f}%'})
        elif e['truth']:
            e['actual']=e['win']*(.75+.35*rand(s,e['id'],47));e['outcome']='positive'
            disclose(s,e,'confirmed',spec.positive,f'经对{spec.evidence}复核，本轮阶段目标已获确认，后续按照已披露边界执行。')
        else:
            e['actual']=e['lose'];e['outcome']='negative'
            stage='terminated' if branch<.34 else 'confirmed'
            disclose(s,e,stage,spec.negative,f'经对{spec.evidence}复核，本轮原定目标未能达成，已确认范围与后续安排以本次公告为准。')
            if spec.channel=='credit':s['credit_bad_days'][e['i']]+=2
        if e['outcome']=='negative' and e['scope']=='stock' and rand(s,e['id'],48)<.14:
            s['event_followups'].append({'day':s['day']+12+int(rand(s,e['id'],49)*15),'code':s['profile']['codes'][e['i']],'subtype':e['subtype'],'parent':e['id']})
        queue_value(s,e,expected(e));s['audit']['events_resolved']+=1
        stats=s['event_statistics']['resolved'];stats[e['outcome']]=stats.get(e['outcome'],0)+1
    elif now>=e['next'] and e['stage']<2:
        positive=rand(s,e['id']+':evidence:'+str(e['stage']),50)<(.65 if e['truth'] else .35)
        e['q']=float(np.clip(e['q']*(1.35 if positive else .65),.05,.95));e['stage']+=1
        e['next']=now+.6+rand(s,e['id']+':next:'+str(e['stage']),51)
        if positive:
            action='首轮核验材料通过，进入执行条件复核' if e['stage']==1 else '完成扩大范围验证，等待阶段结论'
            disclose(s,e,'progress',action,f'{spec.evidence}已通过本轮检查，尚须核验剩余执行条件，最终结果尚未确认。')
        else:
            stage='uncertain' if e['stage']==1 else 'review'
            disclose(s,e,stage,'发现补充核验事项，复核执行条件',f'{spec.evidence}存在待交叉核验项目，本轮未形成最终结论，结果仍待核实。')
        queue_value(s,e,expected(e))

def extended_payment(s,e):
    """Finite net incremental cash flow. Remaining PV + paid cash = net outcome.

Front/back-loaded payout profiles vary by economic channel. They do not mint
shares, borrow principal, execute buybacks or reapply an earnings surprise.
"""
    if e['completed']:return None
    if not e['resolved']:
        # Known planning/verification expense can arise before final outcome.
        if s['day']<=int(e['created']) or e.get('last_cost_day')==s['day']:return None
        limit=min(3.,max(0.,s['day']-int(e['created'])))
        cost=min(abs(e['lose'])*.15,max(abs(e['win']),abs(e['lose']))*.08)
        target=-cost*limit/3
        payment=target-e.get('cash_paid',0.)
        e['last_cost_day']=s['day'];e['cash_paid']=target;e['priced_value']-=payment
        return payment
    if s['day']<=e['resolution_day'] or e.get('last_payment_day')==s['day'] or any(x['event_id']==e['id'] for x in s.get('pending_updates',[])):return None
    e['last_payment_day']=s['day']
    e.setdefault('post_initial',e.get('cash_paid',0.));e['paid']+=1
    t=min(1.,e['paid']/max(1,e['duration']))
    channel=e['channel']
    curve=t*t if channel in ('research','investment','integration','capacity') else math.sqrt(t) if channel in ('disruption','legal','impairment','receivables') else t
    target=e['post_initial']+(e['actual']-e['post_initial'])*curve
    payment=target-e.get('cash_paid',0.);e['cash_paid']=target;e['priced_value']=e['actual']-target
    if e['paid']>=e['duration']:
        e['completed']=True;disclose(s,e,'realized','本阶段经营影响计入结束','本事项的有限增量经营影响已全部计入，不重复计入已披露财报。')
    return payment

def daily_extended_events(s):
    ensure_event_schema(s);p=s['profile'];day=s['day'];credit=max(0.,s['macro'][3])
    hazard=.007+.003*p['rd']+.004*(1-p['governance'])+.004*np.minimum(s['distress'],1)+.003*credit*p['leverage']
    draws=uniform(s['seed'],day,p['keys'],60)
    active={e['i'] for e in s['events'] if not e['resolved']}
    cooldown=s['event_cooldowns']
    for index in np.flatnonzero((draws<1-np.exp(-hazard)) & s['alive']):
        i=int(index);code=p['codes'][i]
        if i in active or day<cooldown.get('company:'+code,-1):continue
        subtype=choose_subtype(s,i)
        if subtype:new_event(s,i,subtype)
    # Follow-up work can restart a failed project after fresh public preparation.
    waiting=[]
    for item in s['event_followups']:
        if item['day']>day:waiting.append(item);continue
        if item['code'] not in p['codes']:continue
        i=p['codes'].index(item['code'])
        if not s['alive'][i]:continue
        if i in active or day<cooldown.get('company:'+item['code'],-1):
            item['day']=day+2;waiting.append(item);continue
        new_event(s,i,item['subtype'],parent=item['parent']);active.add(i);s['event_statistics']['reopened']+=1
    s['event_followups']=waiting
