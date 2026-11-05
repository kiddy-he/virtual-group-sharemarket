"""Causal market world. Virtual-day units; deterministic, serializable NumPy state.

The financial world and the public estimates are separate. Price innovations
never read undisclosed company results. No LLM, network, clock or SQL in here.
"""
from __future__ import annotations
import hashlib
import math
import numpy as np

VERSION = 'causal-v2.2'
MACRO = ('demand','inflation','rate','credit','fx','commodity','external',
         'uncertainty','passive','geopolitical','wages','logistics')

def key(value):
    return int.from_bytes(hashlib.blake2b(str(value).encode(),digest_size=8).digest(),'little')

def uniform(seed, counter, keys, channel=0):
    """Counter-based SplitMix64; stream membership independent of array order."""
    with np.errstate(over='ignore'):
        z=np.asarray(keys,dtype=np.uint64)+np.uint64(seed)+np.uint64(counter)*np.uint64(0x9E3779B97F4A7C15)+np.uint64(channel)*np.uint64(0xD1B54A32D192ED03)
        z=(z^(z>>np.uint64(30)))*np.uint64(0xBF58476D1CE4E5B9)
        z=(z^(z>>np.uint64(27)))*np.uint64(0x94D049BB133111EB)
        z=z^(z>>np.uint64(31))
    return ((z>>np.uint64(11)).astype(np.float64)+0.5)/9007199254740992.

def normal(seed,counter,keys,channel=0):
    u=uniform(seed,counter,keys,channel*2)
    v=uniform(seed,counter,keys,channel*2+1)
    return np.sqrt(-2*np.log(u))*np.cos(2*np.pi*v)

def profile(codes,stocks):
    keys=np.array([key('profile:'+c) for c in codes],dtype=np.uint64)
    u=lambda j:uniform(92831,1,keys,j)
    sectors=sorted({stocks[c].sector for c in codes});sector=np.array([sectors.index(stocks[c].sector) for c in codes],dtype=np.int64)
    return {'codes':codes,'industries':[stocks[c].industry for c in codes],'names':[stocks[c].name for c in codes],'keys':np.array([key(c) for c in codes],dtype=np.uint64),'sectors':sectors,'sector':sector,
        'quality':.025+.045*u(1),'beta':.65+.65*u(2),'sector_beta':.6+.6*u(3),
        'idio':.009+.016*u(4),'liquidity':.55+1.2*u(5),'export':u(6),
        'imports':u(7),'commodity':u(8)*2-1,'pricing':u(9),'leverage':.15+.4*u(10),
        'rd':u(11),'governance':.65+.35*u(12),'passive':u(13),'concentration':u(14),
        'short_interest':u(15)*.08,'climate':u(16),'cyber':u(17),'duration':4+8*u(18),
        'bank':np.array(['金融' in stocks[c].sector or stocks[c].industry in ('银行','保险') for c in codes],dtype=bool)}

def create(stocks,prices=None,seed=0):
    codes=sorted(stocks);p=profile(codes,stocks);n=len(codes);m=len(p['sectors'])
    price=np.array([prices[c] if prices else stocks[c].initial_price for c in codes],dtype=float)
    shares=np.full(n,10_000_000.,dtype=float);cap=price*shares
    assets=cap*.85;debt=assets*p['leverage'];payables=assets*.08
    cash=assets*.18;inventory=assets*.14;receivables=assets*.12;fixed=assets-cash-inventory-receivables
    revenue=assets*(.8+.4*p['pricing']);margin=.13+.05*p['pricing'];profit=(revenue*margin-fixed*.045-debt*.045)*.8
    fcf=profit*.68
    s={'version':VERSION,'seed':int(seed)%2**64,'day':0,'tick':0,'fraction':0.,'profile':p,
       'macro':np.zeros(len(MACRO)),'public_macro':np.zeros(len(MACRO)),
       'sector':np.zeros(m),'sector_keys':np.array([key('sector:'+x) for x in p['sectors']],dtype=np.uint64),
       'shares':shares,'issuance_proceeds':np.zeros(n),'assets':assets,'debt':debt,'cash':cash,'inventory':inventory,'receivables':receivables,'payables':payables,'fixed':fixed,
       'equity':assets-debt-payables,'revenue_level':revenue,'core_profit':profit,'margin':margin,
       'public_fcf':fcf.copy(),'public_book':(assets-debt-payables).copy(),'public_cash':cash.copy(),'public_debt':debt.copy(),
       'public_growth':p['quality']*.5,'public_event_cash':np.zeros(n),'public_event_value':np.zeros(n),
       'last_dividend_day':np.full(n,-1,dtype=np.int64),'event_daily_cash':np.zeros(n),'event_book':np.zeros(n),'pending_dividend':np.zeros(n),'total_dividend':np.zeros(n),
       'profit_window':np.zeros(n),'event_window':np.zeros(n),'revenue_window':np.zeros(n),
       'listed_day':np.zeros(n,dtype=np.int64),'report_offset':np.array([key('report:'+c)%63 for c in codes],dtype=np.int64),'last_report':np.full(n,-1,dtype=np.int64),
       'credit_bad_days':np.zeros(n,dtype=np.int64),'loss_reports':np.zeros(n,dtype=np.int64),'distress':np.zeros(n),
       'log_vol':np.zeros(n),'realized2':np.zeros(n),'rv_history':[],
       'mispricing':np.zeros(n),'flow':np.zeros(n),'trend':np.zeros(n),'price':price.copy(),'previous':price.copy(),
       'value':price.copy(),'last_public_value':price.copy(),'productivity':np.zeros(n),'debt_due':np.array([126+key('maturity:'+c)%504 for c in codes],dtype=np.int64),'value_scale':np.ones(n),'valuation_reserve':np.zeros(n),
       'last_return':np.zeros(n),'day_return':np.zeros(n),'daily_volume':np.zeros(n),
       'halt_days':np.zeros(n,dtype=np.int64),'liquidation_day':np.full(n,-1,dtype=np.int64),'alive':np.ones(n,dtype=bool),'pending_actions':[],
       'events':[],'next_event':1,'public_seq':0,'public_news':[],'news_pending':[],
       'attribution':{'information':np.zeros(n),'microstructure':np.zeros(n),'innovation':np.zeros(n)},
       'regime':'calm','regime_days':0,'audit':{'accounting_max_error':0.,'events_created':0,'events_resolved':0,'early_releases':0},
       'last_macro_release':-1,'cashflow_per_share':np.zeros(n),'virtual_calendar':[]}
    base=valuation(s,scaled=False)
    net=(s['public_cash']-s['public_debt'])/s['shares']
    s['value_scale']=(price-net)/np.maximum(base-net,.001)
    # Sparse, bounded exposure network. A company cannot be its own supplier.
    edges=[]
    for i,c in enumerate(codes):
        choices=[j for j in range(n) if j!=i]
        ranked=sorted(choices,key=lambda j:key('supply:'+c+':'+codes[j]))[:2]
        for j in ranked:edges.append((i,j,.06+.08*float(uniform(31,1,np.array([key(c+codes[j])],dtype=np.uint64))[0])))
    s['network']=edges
    return s

def valuation(s,scaled=True):
    p=s['profile'];macro=s['public_macro'];credit=max(0.,macro[3]);rate=.045+macro[2]
    required=np.clip(.09+(.5-p['governance'])*.02+rate*.3+credit*.05,.065,.24)
    growth=np.clip(s['public_growth']+.012*macro[0]-.008*credit,-.02,.045)
    gap=np.maximum(required-growth,.035)
    # Constrained growing-perpetuity approximation with conservative growth.
    g=np.minimum(growth,required-.035)
    pv=s['public_fcf']*(1+g)/gap
    net=s['public_cash']-s['public_debt']
    operating_book=s['public_book']-net
    bank_core=operating_book*.75+np.clip(s['public_fcf'],-np.maximum(operating_book,1)*.1,np.maximum(operating_book,1)*.25)/np.maximum(required,.06)*.65
    core=np.where(p['bank'],bank_core,pv)/s['shares']
    if scaled:core=core*s['value_scale']
    value=core+net/s['shares']
    return np.maximum(.001,value+s['public_event_cash']/s['shares']+s['public_event_value'])

def accounting(s):
    s['assets']=np.round(s['cash']+s['inventory']+s['receivables']+s['fixed'],2)
    s['equity']=np.round(s['assets']-s['debt']-s['payables'],2)
    err=np.max(np.abs(s['assets']-s['debt']-s['payables']-s['equity']))
    s['audit']['accounting_max_error']=max(s['audit']['accounting_max_error'],float(err))

def begin_day(s):
    """One completed economic day. Uses pre-day public data for announcements."""
    from .causal_events import emit, daily_events, cashflows
    public_names=('public_macro','public_fcf','public_book','public_cash','public_debt','public_growth')
    old_public={name:s[name].copy() for name in public_names}
    frozen={name:s[name].copy() for name in ('cash','inventory','receivables','fixed','assets','debt','payables','equity','pending_dividend')}
    s['day']+=1;s['fraction']=0.;day=s['day'];p=s['profile'];keys=p['keys'];seed=s['seed'];n=len(keys)
    old=s['macro'].copy();z=normal(seed,day,np.arange(len(MACRO),dtype=np.uint64)+np.uint64(key('macro')),10)
    # Root innovations and lagged causal paths, all stationary around a trend.
    phi=np.array([.992,.990,.997,.985,.995,.994,.990,.965,.97,.98,.992,.94])
    sig=np.array([.012,.008,.001,.014,.006,.015,.012,.02,.02,.008,.006,.018])
    x=old*phi+sig*z
    x[1]+=.002*old[0]+.001*old[5]
    x[2]+=.0003*old[1]-.0001*old[0]
    x[3]+=.004*max(0.,old[2])+.002*max(0.,-old[0])
    x[7]+=.003*abs(old[6])+.003*max(0.,old[3])
    x[11]+=.003*max(0.,old[9])
    s['macro']=np.clip(x,-1.5,1.5)
    sz=normal(seed,day,s['sector_keys'],12)
    s['sector']=.98*s['sector']+.004*x[0]-.003*x[3]+.012*sz
    # Public releases have known lag, measurement error and later revisions.
    if day%5==0:
        prev=s['public_macro'].copy();s['public_macro']=old+normal(seed,day,np.arange(len(MACRO),dtype=np.uint64),14)*sig*.4
        emit(s,'macro','经济运行数据发布，需求、物价与融资指标更新','market',[],severity=2,stage='release',facts={'需求指标':round(float(s['public_macro'][0]),3),'融资指标':round(float(s['public_macro'][3]),3)})
        if day%20==0:
            emit(s,'data_revision','经济历史数据修订，原先增长估计有所调整','market',[],stage='revision',facts={'修订幅度':round(float(s['public_macro'][0]-prev[0]),3)})
        s['last_macro_release']=day
    stress=max(0.,x[3])+max(0.,x[7])+.4*max(0.,-x[0])
    s['regime']='panic' if stress>.65 else 'stressed' if stress>.3 else 'active' if abs(x[0])>.18 else 'calm'
    s['regime_days']+=1
    sector=s['sector'][p['sector']]
    # Persistent growth with bounded industry shares/competitive advantage.
    idio=normal(seed,day,keys,16)*.0018
    s['productivity']*=.999
    expansion=np.clip(p['quality']+s['productivity']+.06*x[0]+.09*sector+.04*p['export']*x[6]-.025*max(0.,x[3]),-.18,.20)
    s['revenue_level']*=np.exp(expansion/252+idio)
    s['margin']=np.clip(.13+.05*p['pricing']+.035*sector+.025*x[0]-.035*p['commodity']*x[5]
        +.025*(p['export']-p['imports'])*x[4]-.025*x[10]-.06*max(0.,x[11]),-.25,.45)
    sales=s['revenue_level']/252
    interest=s['debt']*np.clip(.045+x[2]+max(0.,x[3])*.03,.005,.3)/252
    depreciation=s['fixed']*.045/252
    ebit=sales*s['margin']-depreciation
    core=ebit-interest-np.maximum(0,ebit-interest)*.20
    extra=cashflows(s);s['event_daily_cash']=extra.copy()
    provisions=np.where(p['bank'],s['assets']*.02*max(0.,x[3])**2/252,0.)
    core-=provisions
    profit=core+extra
    old_inventory=s['inventory'].copy();old_receivable=s['receivables'].copy()
    s['inventory']+=(s['revenue_level']*.12-s['inventory'])*.035
    s['receivables']+=(s['revenue_level']*(.09+max(0.,x[3])*.03)-s['receivables'])*.035
    capex=depreciation+s['fixed']*np.maximum(expansion,0)/252
    s['fixed']+=capex-depreciation
    s['cash']+=profit+depreciation-capex-(s['inventory']-old_inventory)-(s['receivables']-old_receivable)
    # Limited refinancing based on credit and leverage, not infinite rescue cash.
    shortfall=np.maximum(0,s['assets']*.025-s['cash'])
    capacity=np.maximum(0,s['assets']*(.7-.15*max(0.,x[3]))-s['debt'])
    borrow=np.minimum(shortfall,capacity)*max(.05,1-max(0.,x[3]))
    s['cash']+=borrow;s['debt']+=borrow
    repay=np.minimum(np.maximum(0,s['cash']-s['assets']*.25),s['debt'])*.02
    s['cash']-=repay;s['debt']-=repay
    unpaid=np.maximum(0,-s['cash']);s['payables']+=unpaid;s['cash']=np.maximum(0,s['cash'])
    s['credit_bad_days']=np.where(unpaid>0,s['credit_bad_days']+1,np.maximum(0,s['credit_bad_days']-1))
    s['core_profit']=core*252;s['profit_window']+=core;s['event_window']+=extra;s['revenue_window']+=sales
    # Retained profits and declared dividends, no random money creation.
    dividend=np.minimum(np.maximum(0,core)*.30,np.maximum(0,s['cash']-s['assets']*.04))
    s['pending_dividend']+=dividend/s['shares']
    for i in np.flatnonzero((s['debt_due']==day)&s['alive']):
        due=float(s['debt'][i])*.25
        pay=min(due,max(0.,float(s['cash'][i]-s['assets'][i]*.03)))
        s['debt'][i]-=pay;s['cash'][i]-=pay
        rolled=due-pay
        roll_prob=np.clip(.97-.45*max(0.,x[3])-.25*s['distress'][i],.05,.99)
        if float(uniform(seed,day,keys[i:i+1],39)[0])>roll_prob and rolled>0:
            s['credit_bad_days'][i]+=5
            emit(s,'debt_maturity',f"公司 {p['codes'][i]} 的到期融资出现缺口，偿债风险上升",'stock',[int(i)],severity=3,stage='confirmed')
        else:
            emit(s,'debt_maturity',f"公司 {p['codes'][i]} 完成本期到期债务安排",'stock',[int(i)],stage='confirmed')
        s['debt_due'][i]+=252
    for name,value in frozen.items():s[name]=np.where(s['alive'],s[name],value)
    accounting(s)
    s['distress']=np.clip(s['debt']/np.maximum(s['assets'],1)-.5,0,1)+np.minimum(s['credit_bad_days']/30,1)
    # Public forecasts advance on known secular expectations, not private idio.
    s['public_fcf']*=np.exp(s['public_growth']/252)
    report=(day%63)==s['report_offset']
    for i in np.flatnonzero(report & s['alive']):
        period=63 if s['last_report'][i]>=0 else max(day-int(s['listed_day'][i]),1)
        annual=float(s['profit_window'][i]*252/period*.68)
        previous=float(s['public_fcf'][i]);surprise=(annual-previous)/max(abs(previous),1)
        s['public_fcf'][i]=annual;s['public_book'][i]=s['equity'][i]-s['event_book'][i]
        s['public_cash'][i]=s['cash'][i]-s['event_book'][i];s['public_debt'][i]=s['debt'][i]
        s['loss_reports'][i]=s['loss_reports'][i]+1 if annual<0 else 0
        s['profit_window'][i]=0;s['event_window'][i]=0;s['revenue_window'][i]=0;s['last_report'][i]=day
        emit(s,'earnings',f"公司 {p['codes'][i]} 发布经营报告，盈利预期更新",'stock',[i],severity=2 if abs(surprise)>.15 else 1,stage='release',facts={'相对原盈利预期变化':f'{surprise*100:+.2f}%'})
    # Negative-return feedback changes conditional uncertainty, not next sign.
    rv=np.sqrt(np.maximum(s['realized2'],1e-10));s['rv_history'].append(rv)
    s['rv_history']=s['rv_history'][-22:]
    history=np.stack(s['rv_history']);baseline=np.sqrt((.008*p['beta'])**2+(.009*p['sector_beta'])**2+p['idio']**2)
    relative=np.log(np.maximum(history,1e-5)/baseline)
    target=.45*relative[-1]+.25*relative[-5:].mean(axis=0)+.15*relative.mean(axis=0)
    s['log_vol']=np.clip(.88*s['log_vol']+.12*target+.04*normal(seed,day,keys,18)+.015*max(0.,stress-.2),-.65,.8)
    s['realized2'][:]=0;s['daily_volume'][:]=0;s['day_return'][:]=0
    s['halt_days']=np.maximum(0,s['halt_days']-1)
    daily_events(s)
    s.setdefault('pending_public',[]).append({'tick':s['tick']+2,'values':{name:s[name].copy() for name in public_names}})
    for name,value in old_public.items():s[name]=value
    s['value']=valuation(s)

def innovations(s,dt,pressures=None):
    """Tick reference returns and liquidity: same function in live and research.

    Normal variance mixture (97.5% N(0,1), 2.5% N(0,3^2)), normalized to unit
    variance, plus stochastic volatility. Finite tails without df=3 instability.
    """
    from .causal_events import advance_events
    s['tick']+=1;s['fraction']=min(1.,s['fraction']+dt)
    releases=[]
    for release in s.setdefault('pending_public',[]):
        if release['tick']<=s['tick']:
            for name,value in release['values'].items():s[name]=value
        else:releases.append(release)
    s['pending_public']=releases
    advance_events(s)
    p=s['profile'];seed=s['seed'];t=s['tick'];keys=p['keys'];m=len(p['sectors'])
    a=normal(seed,t,keys,22)
    mix=np.where(uniform(seed,t,keys,46)<.025,3.,1.)/math.sqrt(1.2)
    a*=mix
    market=float(normal(seed,t,np.array([key('market')],dtype=np.uint64),25)[0])
    sectors=normal(seed,t,s['sector_keys'],26)
    stress=max(0.,s['public_macro'][3])+max(0.,s['public_macro'][7])
    vol=np.exp(s['log_vol'])*min(1.8,1+.55*stress)
    sigma2=((.008*p['beta'])**2+(.009*p['sector_beta'])**2+p['idio']**2)*vol**2
    noise=(.008*p['beta']*market+.009*p['sector_beta']*sectors[p['sector']]+p['idio']*a)*vol*math.sqrt(dt)
    value=valuation(s);s['value']=value
    # Slow adjustment towards evolving PUBLIC valuation, with heterogeneous beliefs.
    gap=np.log(np.maximum(value,.001)/np.maximum(s['price'],.001))
    revision=np.log(np.maximum(value,.001)/np.maximum(s['last_public_value'],.001))
    attention=.45+.3*p['pricing']
    information=attention*revision+np.clip(.02*gap,-.08,.08)*dt
    s['last_public_value']=value.copy()
    old=s['flow'].copy()
    pressure=np.zeros(len(keys)) if pressures is None else np.asarray(pressures,dtype=float)
    desired=.0025*np.tanh(pressure/(5000*p['liquidity']))
    s['flow']=old*math.exp(-dt/.15)+desired*(1-math.exp(-dt/.15))
    micro=s['flow']-old
    # Passive/rebalancing and short squeeze are bounded inventory-demand levels.
    old_mis=s['mispricing'].copy();public=s['public_macro']
    passive=.006*p['passive']*public[8]+s.get('public_supply',np.zeros(len(keys)))
    squeeze=.01*(p['short_interest']+s.get('short_outstanding',np.zeros(len(s['price'])))/s['shares'])*np.maximum(0,s['trend']*30)*(1-p['liquidity']/2)
    s['mispricing']+=(passive+squeeze-s['mispricing'])*(1-math.exp(-dt/2))
    micro+=s['mispricing']-old_mis
    ret=information+micro+noise-.5*sigma2*dt
    ret=np.where(s['alive'] & (s['halt_days']==0),ret,0.)
    s['last_return']=ret;s['realized2']+=ret**2;s['day_return']+=ret
    s['trend']=math.exp(-dt/3)*s['trend']+(1-math.exp(-dt/3))*ret/max(dt,1e-12)
    for k,v in [('information',information),('microstructure',micro),('innovation',noise)]:s['attribution'][k]+=v
    return ret

def tick_cents(values):
    """One binary-float quote boundary rule, half-up within one ULP."""
    return np.floor(np.nextafter(np.asarray(values,dtype=float)*100,np.inf)+.5).astype(np.int64)

def price_limits(previous,percent):
    pc=tick_cents(previous);bp=np.rint(np.asarray(percent)*10000).astype(np.int64)
    return np.maximum(1,(pc*(10000-bp)+5000)//10000),np.maximum(1,(pc*(10000+bp)+5000)//10000)

def init_venue(s):
    n=len(s['price'])
    s['venue_cash']=np.tile(tick_cents(s['price'])*1_000_000,(2,1))
    s['venue_inventory']=np.full((2,n),1_000_000,dtype=np.int64)
    s['venue_initial_cash']=s['venue_cash'].sum(axis=0).copy()
    s['venue_initial_inventory']=s['venue_inventory'].sum(axis=0).copy()
    s['reference']=s['price'].copy()
    s['house_cash']=tick_cents(s['price'])*1_000_000
    s['house_inventory']=np.full(n,1_000_000,dtype=np.int64)
    s['house_fees']=0
    s['locked_inventory']=np.full(n,6_500_000,dtype=np.int64)
    s['lending_inventory']=np.full(n,500_000,dtype=np.int64)
    s['short_outstanding']=np.zeros(n,dtype=np.int64)
    s['lender_cash']=int((tick_cents(s['price'])*500_000).sum())
    s['credit_depth_tick']=-1
    s['credit_depth']=np.zeros(n,dtype=np.int64)
    s['public_supply']=np.zeros(n)

def market_tick(s,dt,limits,pressures=None,background=True):
    if 'venue_cash' not in s:init_venue(s)
    ret=innovations(s,dt,pressures)
    low,high=limits
    reference=np.clip(s['reference']*np.exp(ret),low/100,high/100)
    cents=np.clip(tick_cents(reference),low,high)
    # Two finite, funded institutional cohorts cross at the new quote. Their
    # aggregate accounts are conserved; volume is executed shares, never a label.
    rng=uniform(s['seed'],s['tick'],s['profile']['keys'],70)
    intensity=(.25+np.minimum(4,np.abs(ret)/max(math.sqrt(dt),1e-8)*90))
    lots=(1+rng*4)*intensity*s['profile']['liquidity']*dt*400
    qty=(100*np.floor(lots+uniform(s['seed'],s['tick'],s['profile']['keys'],71))).astype(np.int64)
    qty=np.minimum(qty,10000)
    buyer=np.where(ret>=0,0,1);seller=1-buyer;idx=np.arange(len(cents))
    qty=np.minimum(qty,s['venue_inventory'][seller,idx])
    qty=np.minimum(qty,s['venue_cash'][buyer,idx]//np.maximum(cents,1))
    qty=(qty//100)*100
    qty=np.where(s['alive'] & (s['halt_days']==0) & background,qty,0)
    amount=cents*qty
    s['venue_cash'][buyer,idx]-=amount;s['venue_cash'][seller,idx]+=amount
    s['venue_inventory'][buyer,idx]+=qty;s['venue_inventory'][seller,idx]-=qty
    s['price']=np.where(qty>0,cents/100,s['price'])
    s['reference']=reference;s['daily_volume']+=qty
    return s['price'],qty


def extend(s,stocks,prices):
    """Add IPOs without resetting old financial, event or random stream state."""
    oldcodes=s['profile']['codes'];new=create(stocks,prices,s['seed']);init_venue(new);newcodes=new['profile']['codes']
    if oldcodes==newcodes:return s
    new['listed_day'][:]=s['day'];new['debt_due']+=s['day']
    index={c:i for i,c in enumerate(newcodes)};dest=np.array([index[c] for c in oldcodes])
    for name,value in list(s.items()):
        if name=='profile':continue
        if isinstance(value,np.ndarray) and value.ndim==1 and len(value)==len(oldcodes) and name not in ('macro','public_macro','sector','sector_keys'):
            new[name][dest]=value
        elif name not in ('profile','network','sector','sector_keys','rv_history','attribution','venue_cash','venue_inventory','venue_initial_cash','venue_initial_inventory','reference'):
            new[name]=value
    for name,value in s['profile'].items():
        if isinstance(value,np.ndarray) and value.ndim==1 and len(value)==len(oldcodes) and name not in ('sector',):new['profile'][name][dest]=value
        elif name in ('industries','names'):
            for old_i,new_i in enumerate(dest):new['profile'][name][int(new_i)]=value[old_i]
    for j,sector in enumerate(s['profile']['sectors']):new['sector'][new['profile']['sectors'].index(sector)]=s['sector'][j]
    for e in new['events']:
        e['i']=int(dest[e['i']]);e['weights']={str(int(dest[int(i)])):w for i,w in e['weights'].items()}
    new['attribution']={name:np.zeros(len(newcodes)) for name in s['attribution']}
    for name,v in s['attribution'].items():new['attribution'][name][dest]=v
    new['rv_history']=[]
    for history in s['rv_history']:
        item=np.full(len(newcodes),.02);item[dest]=history;new['rv_history'].append(item)
    import copy
    new['pending_public']=copy.deepcopy(s.get('pending_public',[]))
    for release in new['pending_public']:
        for name,value in list(release['values'].items()):
            if name=='public_macro':continue
            enlarged=new[name].copy();enlarged[dest]=value;release['values'][name]=enlarged
    for name in ('venue_cash','venue_inventory'):new[name][:,dest]=s[name]
    for name in ('venue_initial_cash','venue_initial_inventory','reference','house_cash','house_inventory','lending_inventory','short_outstanding','credit_depth'):new[name][dest]=s[name]
    return new


def declare_dividends(s):
    """Quarterly actual cash payout, same routine in live and long-run harness."""
    if not s['day'] or s['day']%63:return np.zeros(len(s['price']))
    amount=np.minimum(s['pending_dividend'],np.maximum(0,s['cash']-s['assets']*.03)/s['shares'])
    # Capital-retention covenant: no distributions from a reported deficit or
    # loss, nor a payout that exceeds the quarter's conservative equity appraisal.
    # This also prevents repeated penny-price / larger-than-price dividend loops.
    cap=np.maximum(0.,np.minimum(s['price'],valuation(s))-.01)*.10
    eligible=s['alive']&(s['last_dividend_day']!=s['day'])&(s['equity']>0)&(s['public_book']>0)&(s['public_fcf']>0)
    amount=np.where(eligible,np.floor(np.minimum(amount,cap)*100)/100,0.)
    s['last_dividend_day'][amount>0]=s['day']
    dollars=amount*s['shares']
    s['last_public_value']=np.maximum(.001,s['last_public_value']-amount)
    s['cash']-=dollars;s['public_cash']-=dollars;s['public_book']-=dollars;s['pending_dividend']-=amount;s['total_dividend']+=amount
    # Cohorts and house are real holders; outside shareholders receive the rest.
    if 'venue_inventory' in s:
        s['venue_cash']+=s['venue_inventory']*tick_cents(amount)
        s['venue_initial_cash']+=s['venue_inventory'].sum(axis=0)*tick_cents(amount)
        s['house_cash']+=s['house_inventory']*tick_cents(amount)
        s['lender_cash']+=int((s['lending_inventory']*tick_cents(amount)).sum())
    accounting(s)
    return amount


def corporate_actions(s,flags):
    """Shared production/research corporate policy; returns committed actions."""
    from .causal_events import emit
    actions=[];amounts=declare_dividends(s)
    for i in range(len(s['price'])):
        if not s['alive'][i]:continue
        if amounts[i]>0:actions.append({'type':'dividend','i':i,'price':float(amounts[i])})
        bad=s['loss_reports'][i]>=2 or s['public_book'][i]<=0
        good=s['loss_reports'][i]==0 and s['last_report'][i]>=126 and s['public_book'][i]>0 and s['credit_bad_days'][i]==0
        if bad and not flags[i]:actions.append({'type':'st','i':i})
        elif flags[i] and good:actions.append({'type':'un_st','i':i})
        if s['credit_bad_days'][i]>=30 and s['public_book'][i]<=0 and s['liquidation_day'][i]<0:
            s['liquidation_day'][i]=s['day']
            emit(s,'liquidation',f"公司 {s['profile']['codes'][i]} 进入三个交易日的清算准备期，回收额按债权优先后的剩余资产计算",'stock',[i],severity=3)
        if s['liquidation_day'][i]>=0 and s['day']-s['liquidation_day'][i]>=3:
            residual=max(0.,s['cash'][i]+s['receivables'][i]*.6+s['inventory'][i]*.5+s['fixed'][i]*.45-s['debt'][i]-s['payables'][i])
            recovery=float(tick_cents([residual/s['shares'][i]])[0]/100)
            actions.append({'type':'liquidate','i':i,'price':recovery})
            rc=int(tick_cents([recovery])[0]);s['venue_cash'][:,i]+=s['venue_inventory'][:,i]*rc
            s['venue_initial_cash'][i]+=int(s['venue_inventory'][:,i].sum())*rc
            s['venue_inventory'][:,i]=0;s['venue_initial_inventory'][i]=0
            s['house_cash'][i]+=s['house_inventory'][i]*rc;s['house_inventory'][i]=0
            s['lender_cash']+=int(s['lending_inventory'][i])*rc;s['lending_inventory'][i]=0;s['short_outstanding'][i]=0
            s['alive'][i]=False
            for name in ('cash','inventory','receivables','fixed','assets','debt','payables','equity'):s[name][i]=0
    dead=set(np.flatnonzero(~s['alive']))
    s['events']=[e for e in s['events'] if e['i'] not in dead]
    for e in s['events']:e['weights']={i:w for i,w in e['weights'].items() if int(i) not in dead}
    from .causal_events import revalue
    revalue(s)
    return actions
