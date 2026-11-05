"""Deterministic financial-health corporate actions for the causal model."""
import json
from ..market.stocks import STOCK_POOL
from ..market.causal_state import declare_dividends
from ..market.causal_events import emit
from ..storage.money import money

async def run_day(service):
    s=service.engine.causal;engine=service.engine;db=service.db
    stats={k:0 for k in ('dividend','split','st','un_st','suspend','delist')}
    from ..market.causal_state import corporate_actions
    flags=[engine.is_st(c) for c in s['profile']['codes']]
    for action in corporate_actions(s,flags):
        i=action['i'];code=s['profile']['codes'][i];q=engine.get(code);stock=STOCK_POOL[code]
        if action['type']=='dividend':
            await service._cash_dividend(code,q,stock,stats,action['price'])
        elif action['type'] in ('st','un_st'):
            flag=action['type']=='st';engine.set_st(code,flag);stats[action['type']]+=1
            emit(s,'risk_warning',f'虚拟企业 {code} '+('触及已披露的财务风险条件，实施风险警示' if flag else '已披露的经营与财务状况改善，解除风险警示'),'stock',[i],severity=2)
        elif action['type']=='liquidate':
            recovery=action['price']
            for pos in await db.get_position_holders(code):
                acc=await db.get_account(pos['user_id'])
                if not acc:continue
                proceeds=money(recovery*pos['quantity'])
                await db.update_cash_full(pos['user_id'],money(acc['cash_available']+proceeds),acc['cash_withdrawable'],acc['cash_frozen'])
                await db.delete_position(pos['user_id'],code)
            from .margin import _LEDGER_KEY
            raw=await db.get_meta(_LEDGER_KEY)
            if raw:
                ledger=json.loads(raw)
                for loan in ledger['loans'].values():
                    if loan['status']=='open' and loan['kind']=='stock' and loan['code']==code:
                        loan.update(kind='cash',principal=money(loan['quantity']*recovery+loan.get('corporate_adjustment',0)),quantity=0,code=None,corporate_adjustment=0)
                await db.set_meta(_LEDGER_KEY,json.dumps(ledger,ensure_ascii=False))
            engine.delist(code);stats['delist']+=1
            emit(s,'liquidation',f'虚拟企业 {code} 清算完成，股票终止交易','stock',[i],severity=3,facts={'每股回收额':f'{recovery:.2f}元'})
    return stats
