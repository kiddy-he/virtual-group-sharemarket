"""Finite lender balance sheet and separate, bounded credit execution facility.

Credit fills face the house at a reference-centred spread, with no infinite
liquidity and no ability to trade a halted/sealed security. Borrowed shares
remain actual shares; outstanding short claims are recorded separately.
"""
import time
from ..config import CFG
from ..market.stocks import STOCK_POOL
from ..storage.money import cents

def executable(service,code,quantity,side):
    from .margin import MarginError
    e=service.engine;s=e.causal;i=s['profile']['codes'].index(code)
    ok,why=e.can_trade(code)
    if not ok:raise MarginError(why)
    q=e.get(code);stock=STOCK_POOL[code]
    if (side=='sell' and q.price<=q.limit_down(stock)) or (side=='buy' and q.price>=q.limit_up(stock)):
        raise MarginError('涨跌停封板期间无法保证信用交易成交。')
    spread=.0015+.002*float(s['profile']['leverage'][i])
    price=max(q.limit_down(stock),min(q.limit_up(stock),round(e.reference_price(code)*(1+spread if side=='buy' else 1-spread),2)))
    used=int(s['credit_depth'][i]) if s['credit_depth_tick']==s['tick'] else 0
    depth=max(CFG.lot_size,int(s['shares'][i]*.002))
    if quantity>depth-used:raise MarginError('本轮信用交易深度不足，请减少数量或等待下一轮行情。')
    if side=='sell':
        if quantity>s['lending_inventory'][i]:raise MarginError('可借证券库存不足。')
        if cents(price)*quantity>s['house_cash'][i]:raise MarginError('做市商可用资金不足。')
    elif quantity>s['house_inventory'][i]:raise MarginError('买券还券可成交库存不足，请稍后重试。')
    return price

def settle(service,code,qty,side,price,fee,adjustment=0):
    e=service.engine;s=e.causal;i=s['profile']['codes'].index(code)
    # Validation happens before all state changes, so callers may safely report
    # an unavailable fill without leaving a partly-mutated credit facility.
    executable(service,code,qty,side)
    if s['credit_depth_tick']!=s['tick']:
        s['credit_depth'][:]=0;s['credit_depth_tick']=s['tick']
    s['credit_depth'][i]+=qty
    if side=='sell':s['lending_inventory'][i]-=qty;s['short_outstanding'][i]+=qty
    else:s['lending_inventory'][i]+=qty;s['short_outstanding'][i]-=qty
    e.settle_house(code,side,price,qty,fee)
    s['lender_cash']+=cents(adjustment)
    if service.trade is not None:
        pressure=service.trade.matcher.pressure
        pressure[code]=pressure.get(code,0)+(qty if side=='buy' else -qty)

async def liquidate(service,user):
    from .margin import MarginError,_maintenance_ratio
    from .trade import TradeError
    db=service.db;e=service.engine
    acc=await db.get_account(user)
    if not acc or acc['status']!='active':return '账户非活跃，待人工核账。'
    ratio=await service._margin_ratio(user)
    if ratio is None or ratio>=_maintenance_ratio():return '担保比例正常，无需强平。'
    if service.trade is None:raise MarginError('强平交易服务尚未装配，保留原负债。')
    await service.trade.cancel_user_orders(user)
    sold=covered=0
    for pos in sorted(await db.get_positions(user),key=lambda p:(e.get(p['code']).price if e.get(p['code']) else 0)*p['quantity'],reverse=True):
        ok,_=e.can_trade(pos['code'])
        if not ok:continue
        # Forced sale waives T+1, while matching, reserves, fees and daily limits
        # remain the very same production path used by ordinary orders.
        await db.upsert_position(user,pos['code'],pos['quantity'],pos['quantity'],pos['cost_price'])
        try:
            await service.trade.sell(user,pos['code'],pos['quantity'])
            await service.trade.cancel_user_orders(user,'sell')
        except TradeError:
            await service.trade.cancel_user_orders(user,'sell')
        left=await db.get_position(user,pos['code'])
        if left:
            filled=pos['quantity']-left['quantity'];sold+=int(filled>0)
            await db.upsert_position(user,pos['code'],left['quantity'],max(0,pos['sellable']-filled),left['cost_price'])
        else:sold+=1
        ratio=await service._margin_ratio(user)
        if ratio is None or ratio>=_maintenance_ratio():break
    ledger=await service._load()
    # Cover securities before using remaining cash for principal, otherwise a
    # cash loan can consume all cash needed to close a dangerous short.
    for loan in list(service._open_loans(ledger,user)):
        if loan['kind']!='stock' or not loan['quantity']:continue
        acc=await db.get_account(user);q=e.get(loan['code'])
        if not q:continue
        qty=min(loan['quantity'],int(max(0,acc['cash_available']-10)/(q.price*1.02)))
        qty=min(qty,max(CFG.lot_size,int(e.causal['shares'][e.causal['profile']['codes'].index(loan['code'])]*.002)))
        if qty<=0:continue
        try:await service._cover(user,loan['code'],qty);covered+=1
        except MarginError:pass
    ledger=await service._load();acc=await db.get_account(user)
    await service._repay_debt(user,acc['cash_available'],ledger)
    net=await service._net_worth(user);ratio=await service._margin_ratio(user)
    if net<0:await db.set_status(user,'frozen',int(time.time()))
    pending=ratio is not None and ratio<_maintenance_ratio()
    return f'⚠️ 强平成交：卖出 {sold} 只、还券 {covered} 笔，净资产 {net:,.2f} 元。'+('流动性不足的剩余负债保留，等待后续清算。' if pending else '担保比例已恢复。')+('账户净资产为负，已冻结。' if net<0 else '')
