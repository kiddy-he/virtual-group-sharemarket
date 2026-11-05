"""Production adapter for the causal world, preserving the existing quote API."""
from __future__ import annotations
import math
import time
import numpy as np
from .engine import PriceEngine,BOARD_NORMAL,BOARD_SEALED
from .stocks import STOCK_POOL
from .causal_state import create,begin_day,market_tick,price_limits,tick_cents,extend,init_venue,VERSION
from ..config import CFG

class CausalPriceEngine(PriceEngine):
    def __init__(self,seed=0,tick_seconds=None,day_seconds=None):
        super().__init__(seed,tick_seconds,day_seconds)
        self.causal=create(STOCK_POOL,seed=seed);init_venue(self.causal)
        self.model_version=VERSION
        self.quote_kind='executed aggregate institution trades; finite cohort balances'
        self.causal_news_cursor=0
    def migrate_legacy(self):
        # Preserve player prices and outstanding orders. Rebase the NEW economic
        # model once, without rerolling/overwriting any old business operation.
        seed=self.causal['seed'];prices={c:q.price for c,q in self.quotes.items()}
        self.causal=create(STOCK_POOL,prices,seed);init_venue(self.causal)
        self.causal['migration']='legacy-rebased-on-existing-quotes'
        self.causal_news_cursor=0
    def is_suspended(self,code):
        if super().is_suspended(code):return True
        if hasattr(self,'causal') and code in self.causal['profile']['codes']:
            return bool(self.causal['halt_days'][self.causal['profile']['codes'].index(code)]>0)
        return False
    def tick(self,pressures=None):
        if self.paused:return
        s=self.causal;codes=s['profile']['codes']
        s['alive']=np.array([c not in self.delisted for c in codes])
        blocked=np.array([self.is_suspended(c) for c in codes]);oldhalt=s['halt_days'].copy()
        s['halt_days']=np.maximum(s['halt_days'],blocked.astype(np.int64))
        previous=np.array([self.quotes[c].prev_close for c in codes])
        pct=np.array([self.quotes[c].limit_pct_of(STOCK_POOL[c]) for c in codes])
        limits=price_limits(previous,pct)
        pressure=np.array([(pressures or {}).get(c,0) for c in codes],dtype=float)
        prices,volumes=market_tick(s,self._tick_seconds/self._day_seconds,limits,pressure)
        s['halt_days']=oldhalt
        self.market_ret=float(np.mean(s['last_return']))
        self._bar_tick+=1;self._bar_roll=self._bar_tick>=self.ticks_per_bar
        if self._bar_roll:self._bar_seq+=1;self._bar_tick=0
        for i,c in enumerate(codes):
            q=self.quotes[c];new=float(prices[i]);self._raw[c]=float(s['reference'][i]);self.anchor[c]=float(s['value'][i])
            if volumes[i]:
                q.price=new;q.high=max(q.high,new);q.low=min(q.low,new);q.volume+=int(volumes[i])
            b=self.boards[c];b.state=BOARD_SEALED if int(tick_cents([q.price])[0])==int(limits[1][i]) else BOARD_NORMAL
            b.strength=0.;b.sealed_ticks+=int(b.state==BOARD_SEALED)
            self._append_bar(c,q,int(volumes[i]))
        up,_,down=self.advancers();self._senti=.98*self._senti+.02*(up-down)/max(len(codes),1)
        for c in list(self.suspended):
            self.suspended[c]-=self._tick_seconds/3
            if self.suspended[c]<=0:self.resume(c)
    def on_fill(self,code,quantity,price=None,side=None):
        super().on_fill(code,quantity)
        if price is not None:
            i=self.causal['profile']['codes'].index(code);q=self.quotes[code]
            q.price=float(price);q.high=max(q.high,q.price);q.low=min(q.low,q.price)
            self.causal['price'][i]=q.price
            self.causal['daily_volume'][i]+=quantity
    def reference_price(self,code):
        i=self.causal['profile']['codes'].index(code)
        return float(self.causal['reference'][i])
    def liquidity_caps(self,code,upper_price):
        s=self.causal;i=s['profile']['codes'].index(code)
        return int(s['house_cash'][i]//max(1,int(tick_cents([upper_price])[0]))),int(s['house_inventory'][i])
    def settle_house(self,code,side,price,quantity,fee=0):
        s=self.causal;i=s['profile']['codes'].index(code);amount=int(tick_cents([price])[0])*quantity
        if side=='buy':s['house_cash'][i]+=amount;s['house_inventory'][i]-=quantity
        else:s['house_cash'][i]-=amount;s['house_inventory'][i]+=quantity
        s['house_fees']+=int(tick_cents([fee])[0])
        if s['house_cash'][i]<0 or s['house_inventory'][i]<0:raise ValueError('finite market maker funding exhausted')
    def day_close(self):
        rows=super().day_close();self.causal['previous']=self.causal['price'].copy();begin_day(self.causal)
        return rows
    def adjust_price(self,code,delta=None,factor=None):
        before=self.quotes[code].price
        result=super().adjust_price(code,delta,factor)
        if result:
            s=self.causal;i=s['profile']['codes'].index(code);after=self.quotes[code].price
            s['price'][i]=after;s['reference'][i]=after;s['previous'][i]=self.quotes[code].prev_close
            if factor is not None:
                s['shares'][i]/=factor
                for name in ('public_event_value','pending_dividend','total_dividend'):s[name][i]*=factor
                for e in s['events']:
                    if e['i']==i:
                        for name in ('win','lose','actual','priced_value'):e[name]*=factor
            # A real dividend was already debited from corporate cash; corporate
            # code explicitly updates public cash after declaration.
        return result
    def apply_shock(self,pct,code=None,sector=None):
        """Compatibility/admin shocks enter PUBLIC valuation, once; no AR echo."""
        s=self.causal;p=s['profile']
        for i,c in enumerate(p['codes']):
            if (code and c!=code) or (sector and STOCK_POOL[c].sector!=sector):continue
            s['public_fcf'][i]*=max(.01,1+pct)
    def register(self,stock,price=None):
        added=super().register(stock,price)
        if added and hasattr(self,'causal'):
            self.causal=extend(self.causal,STOCK_POOL,{c:q.price for c,q in self.quotes.items()})
        return added
    def configure_listing(self,code,total_shares,allotted_shares=0,proceeds=0.):
        from .causal_state import accounting,valuation
        s=self.causal;i=s['profile']['codes'].index(code);old=s['shares'][i];ratio=total_shares/old
        for name in ('assets','debt','cash','inventory','receivables','payables','fixed','equity','revenue_level','core_profit','public_fcf','public_book','public_cash','public_debt','profit_window','event_window','revenue_window','public_event_cash','event_book'):
            s[name][i]*=ratio
        s['shares'][i]=total_shares;s['cash'][i]+=proceeds;s['public_cash'][i]+=proceeds;s['public_book'][i]+=proceeds;s['issuance_proceeds'][i]=proceeds
        available=max(0,total_shares-allotted_shares);cohort=(available//500)*100;house=cohort
        s['venue_inventory'][:,i]=cohort;s['venue_initial_inventory'][i]=cohort*2;s['house_inventory'][i]=house
        lending=(available//2000)*100;s['lending_inventory'][i]=lending;s['short_outstanding'][i]=0
        s['locked_inventory'][i]=available-cohort*2-house-lending
        budget=int(tick_cents([self.quotes[code].price])[0])*max(100,total_shares//10)
        s['venue_cash'][:,i]=budget;s['venue_initial_cash'][i]=budget*2;s['house_cash'][i]=budget
        accounting(s)
        # Issue price is the opening appraisal, with raised cash accounted once.
        oldscale=s['value_scale'][i];net=(s['public_cash'][i]-s['public_debt'][i])/total_shares
        core=(valuation(s)[i]-net)/oldscale
        s['value_scale'][i]=max(.001,(self.quotes[code].price-net)/max(core,.001))
        s['value'][i]=valuation(s)[i];s['last_public_value'][i]=s['value'][i]
        for release in s.get('pending_public',[]):
            for name,values in release['values'].items():
                if name!='public_macro':values[i]=s[name][i]
    def market_change(self):
        s=self.causal;codes=s['profile']['codes'];float_shares=s['shares']-s['locked_inventory']
        denominator=numerator=0.
        for i,c in enumerate(codes):
            if c in self.delisted:continue
            q=self.quotes[c];denominator+=q.prev_close*float_shares[i];numerator+=(q.price-q.prev_close)*float_shares[i]
        return float(numerator/max(denominator,.001)*100)
    def public_status(self,code):
        s=self.causal;i=s['profile']['codes'].index(code)
        return {'model':self.model_version,'public_seq':s['public_seq'],'virtual_day':s['day'],
                'last_report_day':int(s['last_report'][i]),'forecast_uncertainty':'公开信息估计，非保证价值',
                'published_annual_fcf':round(float(s['public_fcf'][i]),2),'published_book_equity':round(float(s['public_book'][i]),2)}
