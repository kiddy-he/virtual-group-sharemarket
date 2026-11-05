"""Single definition of assets and returns; one batch read of all positions."""
import json
import math
from ..storage.money import money

class ValuationService:
    def __init__(self,db):self.db=db
    async def all(self,price_of):
        from .margin import _LEDGER_KEY
        accounts=await self.db.list_accounts()
        positions=await (await self.db.conn.execute('SELECT * FROM positions')).fetchall()
        debt={}
        raw=await self.db.get_meta(_LEDGER_KEY)
        from .margin import MarginService
        ledger=await MarginService(self.db,None)._load()
        def quote(code):
            value=price_of(code)
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError('行情缺失或无效，暂不能可靠估值。')
            return value
        for loan in ledger['loans'].values():
            if loan['status']!='open':continue
            for field in ('principal','interest_accrued','quantity'):
                value=loan.get(field,0)
                if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('invalid margin ledger')
            adjustment=loan.get('corporate_adjustment',0)
            if not isinstance(adjustment,(int,float)) or not math.isfinite(adjustment):raise ValueError('invalid corporate adjustment')
            value=loan['principal'] if loan['kind']=='cash' else quote(loan['code'])*loan['quantity']+loan.get('corporate_adjustment',0)
            debt[loan['user_id']]=debt.get(loan['user_id'],0)+value+loan['interest_accrued']
        mv={}
        for pos in positions:
            mv[pos['user_id']]=mv.get(pos['user_id'],0)+quote(pos['code'])*pos['quantity']
        rewards=await (await self.db.conn.execute("SELECT user_id,SUM(available_cents+frozen_cents)/100.0 total FROM cash_ledger l WHERE l.id>COALESCE((SELECT MAX(epoch.id) FROM cash_ledger epoch WHERE epoch.user_id=l.user_id AND epoch.reason='rebirth_epoch'),0) AND reason IN ('reward','checkin','quest','season','achievement','prop_grant','compensation') GROUP BY user_id")).fetchall()
        rewards={r['user_id']:r['total'] for r in rewards}
        result={}
        for acc in accounts:
            uid=acc['user_id'];cash=acc['cash_available']+acc['cash_frozen'];assets=money(cash+mv.get(uid,0));net=money(assets-debt.get(uid,0));initial=acc['initial_cash'] or 1
            result[uid]={'cash':money(cash),'market_value':money(mv.get(uid,0)),'gross_assets':assets,'debt':money(debt.get(uid,0)),'net_assets':net,'game_return_pct':(net-initial)/initial*100,'investment_return_pct':(net-initial-rewards.get(uid,0))/initial*100}
        return result
