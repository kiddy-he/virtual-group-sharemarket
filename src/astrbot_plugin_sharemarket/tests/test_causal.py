import asyncio
import copy
import json
import tempfile
import unittest
from dataclasses import fields
from unittest.mock import patch
import numpy as np
from astrbot_plugin_sharemarket.market.causal_state import create,init_venue,market_tick,price_limits,begin_day,valuation,declare_dividends,normal,VERSION
from astrbot_plugin_sharemarket.market.causal_events import create_event,advance_events,cashflows,queue_value,expected
from astrbot_plugin_sharemarket.market.causal_engine import CausalPriceEngine
from astrbot_plugin_sharemarket.market.stocks import STOCK_POOL,Stock,BOARD_MAIN,SEC_CONSUMER
from astrbot_plugin_sharemarket.market.causal_public import query_public
from astrbot_plugin_sharemarket.game.recovery import encode,decode
from astrbot_plugin_sharemarket.runtime import MarketRuntime
from astrbot_plugin_sharemarket.config import CFG,Config
from astrbot_plugin_sharemarket.game.atomic import mutation
from astrbot_plugin_sharemarket.storage.money import cents

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.s=create(STOCK_POOL,seed=181);init_venue(self.s)
    def test_adapter_and_long_run_core_share_identical_tick(self):
        e=CausalPriceEngine(seed=181,tick_seconds=3,day_seconds=1200)
        direct=decode(json.loads(json.dumps(encode(e.causal))))
        limits=price_limits(direct['price'],np.array([e.get(c).limit_pct_of(STOCK_POOL[c]) for c in direct['profile']['codes']]))
        for _ in range(20):
            e.tick();market_tick(direct,3/1200,limits)
        np.testing.assert_array_equal(e.causal['price'],direct['price'])
        np.testing.assert_array_equal(e.causal['venue_cash'],direct['venue_cash'])
    def test_total_physical_issued_shares(self):
        s=self.s
        np.testing.assert_array_equal(s['shares'],s['venue_inventory'].sum(axis=0)+s['house_inventory']+s['lending_inventory']+s['locked_inventory'])
    def test_distressed_penny_stock_does_not_pay_repeat_windfall(self):
        s=self.s;s['day']=63;s['price'][0]=.01;s['pending_dividend'][0]=1.
        before=s['cash'][0];a=declare_dividends(s)
        self.assertEqual(a[0],0);self.assertEqual(s['cash'][0],before)
        s['day']=126;s['public_book'][1]=-1;s['pending_dividend'][1]=1.
        self.assertEqual(declare_dividends(s)[1],0)
    def test_counter_stream_membership_and_order(self):
        keys=self.s['profile']['keys'];a=normal(72,92,keys,3)
        np.testing.assert_array_equal(a[::-1],normal(72,92,keys[::-1],3))
        np.testing.assert_array_equal(a[:20],normal(72,92,keys[:20],3))
        self.assertFalse(np.array_equal(a,normal(73,92,keys,3)))
    def test_initial_valuation_is_anchored_once(self):
        np.testing.assert_allclose(valuation(self.s),self.s['price'],rtol=1e-12)
    def test_hidden_financial_change_does_not_immediately_change_public_value(self):
        before=valuation(self.s).copy();self.s['cash']*=2;self.s['revenue_level']*=.2
        np.testing.assert_array_equal(before,valuation(self.s))
    def test_news_precedes_effective_tick(self):
        e=create_event(self.s,0);before=self.s['public_event_value'].copy()
        self.assertEqual(self.s['public_news'][-1]['effective_tick'],2)
        advance_events(self.s);np.testing.assert_array_equal(before,self.s['public_event_value'])
        self.s['tick']=1;advance_events(self.s);np.testing.assert_array_equal(before,self.s['public_event_value'])
        self.s['tick']=2;advance_events(self.s)
        self.assertNotEqual(self.s['public_event_value'][0],before[0])
    def test_resolved_value_vs_expectation_is_incremental(self):
        e=create_event(self.s,0);self.s['tick']=2;advance_events(self.s)
        old=self.s['public_event_value'][0]
        e['resolved']=True;e['actual']=e['win'];queue_value(self.s,e,expected(e))
        self.s['tick']=4;advance_events(self.s)
        self.assertAlmostEqual(self.s['public_event_value'][0],e['win'])
        self.assertNotAlmostEqual(self.s['public_event_value'][0],old+e['win'])
    def test_event_cashflow_is_not_counted_twice(self):
        e=create_event(self.s,0);e.update(resolved=True,actual=1.,resolution_day=0,duration=5,paid=0,priced_value=1.)
        self.s['pending_updates']=[]
        for day in range(1,6):
            self.s['day']=day;cashflows(self.s)
            total=self.s['public_event_value'][0]+self.s['public_event_cash'][0]/self.s['shares'][0]
            self.assertAlmostEqual(total,1.,places=10)
        self.assertEqual(len(self.s['events']),0)
    def test_venue_conserves_funded_accounts(self):
        initial_cash=self.s['venue_cash'].sum(axis=0).copy();initial_shares=self.s['venue_inventory'].sum(axis=0).copy()
        limits=price_limits(self.s['price'],np.full(len(initial_cash),.1))
        for _ in range(100):market_tick(self.s,1/400,limits)
        np.testing.assert_array_equal(initial_cash,self.s['venue_cash'].sum(axis=0))
        np.testing.assert_array_equal(initial_shares,self.s['venue_inventory'].sum(axis=0))
        self.assertGreaterEqual(self.s['venue_cash'].min(),0);self.assertGreaterEqual(self.s['venue_inventory'].min(),0)
        self.assertTrue(np.any(self.s['daily_volume']>0))
    def test_price_limits_integer_cents(self):
        low,high=price_limits(np.array([1.05,1.15,10.,2.]),np.array([.1,.1,.2,10.]))
        np.testing.assert_array_equal(high,np.array([116,127,1200,2200]));np.testing.assert_array_equal(low,np.array([95,104,800,1]))
        self.assertTrue(np.isfinite(low).all())
    def test_dividend_debits_cash_once_and_no_second_information_jump(self):
        self.s['day']=63;self.s['pending_dividend'][:]=.2
        before=self.s['cash'].copy();value=valuation(self.s).copy();last=self.s['last_public_value'].copy()
        a=declare_dividends(self.s)
        np.testing.assert_allclose(before-self.s['cash'],a*self.s['shares'])
        np.testing.assert_allclose(valuation(self.s),value-a,atol=1e-10)
        np.testing.assert_allclose(self.s['last_public_value'],last-a)
        np.testing.assert_array_equal(declare_dividends(self.s),np.zeros(len(a)))
    def test_ipo_during_pending_report_keeps_old_state_and_new_company_age(self):
        engine=CausalPriceEngine(seed=181);engine.causal['day']=1000
        begin_day(engine.causal)
        oldcodes=list(engine.causal['profile']['codes']);before=engine.causal['cash'].copy()
        stock=Stock('909999','虚拟测试公司',BOARD_MAIN,SEC_CONSUMER,'测试',17.,.01,1.)
        try:
            engine.register(stock,17.)
            for c,value in zip(oldcodes,before):self.assertEqual(engine.causal['cash'][engine.causal['profile']['codes'].index(c)],value)
            engine.tick();engine.tick()
            self.assertEqual(len(engine.causal['public_fcf']),len(engine.causal['price']))
            i=engine.causal['profile']['codes'].index(stock.code)
            self.assertGreater(engine.causal['debt_due'][i],engine.causal['day'])
        finally:STOCK_POOL.pop(stock.code,None)
    def test_roundtrip_checkpoint_and_replay(self):
        s=self.s;limits=price_limits(s['price'],np.full(len(s['price']),.1))
        for _ in range(5):market_tick(s,.0025,limits)
        clone=decode(json.loads(json.dumps(encode(s),allow_nan=False)))
        for _ in range(10):
            market_tick(s,.0025,limits);market_tick(clone,.0025,limits)
        self.assertEqual(json.dumps(encode(s),sort_keys=True),json.dumps(encode(clone),sort_keys=True))
    def test_public_projection_has_no_private_results(self):
        e=create_event(self.s,0)
        result=query_public(self.s,'event',{'event_id':e['id']},CausalPriceEngine(seed=181))
        text=json.dumps(result)
        for secret in ('"truth"','"actual"','"win"','"lose"','"seed"','"rng_namespace"'):self.assertNotIn(secret,text)
    def test_financial_days_balanced_and_finite(self):
        s=self.s;limits=price_limits(s['price'],np.full(len(s['price']),.1))
        for _ in range(100):
            for tick in range(4):market_tick(s,.25,limits)
            begin_day(s)
        for name in ('cash','debt','assets','equity','value'):self.assertTrue(np.isfinite(s[name]).all(),name)
        np.testing.assert_allclose(s['assets'],s['debt']+s['payables']+s['equity'],atol=.011)
        self.assertLess(s['audit']['accounting_max_error'],.011)

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old=copy.deepcopy(CFG)
        for f in fields(CFG):setattr(CFG,f.name,copy.deepcopy(getattr(Config(),f.name)))
        self.tmp=tempfile.TemporaryDirectory();self.seq=0
        self.options={'modelVersion':'causal-v2','modelSeed':101,'npcTrading':False,'rules':{'auction_enabled':False,'npc_count':0,'trade_cooldown_seconds':0}}
        self.r=MarketRuntime(self.tmp.name,options=copy.deepcopy(self.options));await self.r.start(False)
        self.actor={'senderId':'700000001','accountId':'default','scope':'private','identity':'admin','nickname':'fixture'}
        await self.req('account',{'action':'open'})
    async def asyncTearDown(self):
        await self.r.close();self.tmp.cleanup()
        for f in fields(CFG):setattr(CFG,f.name,getattr(self.old,f.name))
    async def req(self,method,params,opid=None):
        self.seq+=1
        return await self.r.execute({'method':method,'params':params,'actor':self.actor,'operation_id':opid or f'fixture-{self.seq}'})
    async def test_finite_cash_lender_repayment_and_interest_conserve(self):
        r=self.r;s=r.engine.causal;uid=self.actor['senderId']
        before=s['lender_cash']+cents((await r.db.get_account(uid))['cash_available'])
        await r.margin.borrow_cash(uid,5000)
        self.assertEqual(s['lender_cash']+cents((await r.db.get_account(uid))['cash_available']),before)
        await r.margin.accrue_day(1)
        await r.margin.repay_cash(uid,5000)
        self.assertEqual(s['lender_cash']+cents((await r.db.get_account(uid))['cash_available']),before)
        s['lender_cash']=0
        from astrbot_plugin_sharemarket.game.margin import MarginError
        with self.assertRaises(MarginError):await r.margin.borrow_cash(uid,1)
        self.assertEqual(await r.margin.debt(uid),0)
    async def test_short_and_cover_preserve_actual_cash_shares(self):
        r=self.r;s=r.engine.causal;uid=self.actor['senderId'];code='600003';i=s['profile']['codes'].index(code)
        before=s['lender_cash']+int(s['house_cash'][i])+cents((await r.db.get_account(uid))['cash_available'])+s['house_fees']
        shares=int(s['house_inventory'][i]+s['lending_inventory'][i]);cash=cents((await r.db.get_account(uid))['cash_available'])
        await r.margin.borrow_stock(uid,code,100)
        self.assertEqual(int(s['short_outstanding'][i]),100)
        await r.margin.cover(uid,code,100)
        self.assertEqual(int(s['short_outstanding'][i]),0)
        self.assertEqual(shares,int(s['house_inventory'][i]+s['lending_inventory'][i]))
        self.assertEqual(before,s['lender_cash']+int(s['house_cash'][i])+cents((await r.db.get_account(uid))['cash_available'])+s['house_fees'])
        self.assertLess(cents((await r.db.get_account(uid))['cash_available']),cash)
        self.assertEqual(await r.margin.debt(uid),0)
    async def test_failed_short_restores_lender_and_ledger(self):
        before=json.dumps(encode(self.r.engine.causal),sort_keys=True)
        async def fail(*a,**k):raise RuntimeError('sql fault')
        with patch.object(self.r.db,'insert_trade',fail):
            with self.assertRaises(RuntimeError):await self.r.margin.borrow_stock(self.actor['senderId'],'600003',100)
        self.assertEqual(before,json.dumps(encode(self.r.engine.causal),sort_keys=True))
        self.assertEqual(await self.r.margin.debt(self.actor['senderId']),0)
    async def test_credit_depth_and_pool_are_finite(self):
        from astrbot_plugin_sharemarket.game.margin import MarginError
        r=self.r;s=r.engine.causal;i=s['profile']['codes'].index('600003');s['lending_inventory'][i]=0
        with self.assertRaises(MarginError):await r.margin.borrow_stock(self.actor['senderId'],'600003',100)
        self.assertEqual(await r.margin.debt(self.actor['senderId']),0)
    async def test_forced_liquidation_keeps_unfillable_debt(self):
        r=self.r;uid=self.actor['senderId'];s=r.engine.causal;i=s['profile']['codes'].index('600003')
        await r.margin.borrow_stock(uid,'600003',100)
        acc=await r.db.get_account(uid)
        await r.db.update_cash_full(uid,0,0,0)
        s['house_inventory'][i]=0
        report=await r.margin.force_liquidate(uid)
        self.assertIn('剩余负债',report)
        self.assertGreater(await r.margin.debt(uid),0)
        self.assertEqual(s['short_outstanding'][i],100)
        self.assertEqual((await r.db.get_account(uid))['status'],'frozen')
    async def test_virtual_day_closes_ipo_without_wall_clock_wait(self):
        code='909991'
        try:
            await self.r.ipo.publish(code,'虚拟时钟测试',BOARD_MAIN,SEC_CONSUMER,'测试',10.,10000)
            await self.r.ipo.subscribe(self.actor['senderId'],code,1)
            ledger=await self.r.ipo._load();self.assertEqual(next(x for x in ledger['ipos'].values() if x['code']==code)['close_day'],1)
            await self.r.dayclose.run(token='test-virtual-day')
            ledger=await self.r.ipo._load();self.assertNotEqual(next(x for x in ledger['ipos'].values() if x['code']==code)['status'],'open')
            s=self.r.engine.causal;i=s['profile']['codes'].index(code)
            owned=sum(p['quantity'] for p in await self.r.db.get_position_holders(code))
            self.assertEqual(int(s['shares'][i]),10000)
            self.assertEqual(int(s['venue_inventory'][:,i].sum()+s['house_inventory'][i]+s['lending_inventory'][i]+s['locked_inventory'][i])+owned,10000)
            self.assertEqual(s['issuance_proceeds'][i],owned*10.)
        finally:
            STOCK_POOL.pop(code,None)
    async def test_repeated_house_roundtrip_cannot_ratchet_quote_up(self):
        uid=self.actor['senderId'];r=self.r;code='600003';before=(await r.db.get_account(uid))['cash_available']
        centre=r.engine.reference_price(code)
        for _ in range(5):
            await r.trade.buy(uid,code,100);await r.db.unlock_all_sellable()
            await r.trade.sell(uid,code,100)
        self.assertLess((await r.db.get_account(uid))['cash_available'],before)
        self.assertEqual(centre,r.engine.reference_price(code))
    async def test_retention_prunes_old_public_news_not_money_journals(self):
        await self.r.db.conn.execute("INSERT INTO causal_news VALUES(999999,1,'{}')")
        accounts=(await (await self.r.db.conn.execute('SELECT COUNT(*) n FROM accounts')).fetchone())['n']
        await self.r.db.retain(7)
        row=await (await self.r.db.conn.execute('SELECT COUNT(*) n FROM causal_news WHERE seq=999999')).fetchone()
        self.assertEqual(row['n'],0)
        self.assertEqual(accounts,(await (await self.r.db.conn.execute('SELECT COUNT(*) n FROM accounts')).fetchone())['n'])
    async def test_credit_rates_use_virtual_year_and_partial_cover_fee_base(self):
        r=self.r;uid=self.actor['senderId']
        await r.margin.borrow_cash(uid,10000)
        stats=await r.margin.accrue_day(1)
        self.assertEqual(stats['interest'],round(10000*getattr(CFG,'margin_cash_rate_annual',.08)/252,2))
        await r.margin.repay_cash(uid,10000)
        await r.margin.borrow_stock(uid,'600003',200)
        ledger=await r.margin._load();loan=next(x for x in r.margin._open_loans(ledger,uid) if x['kind']=='stock')
        original=loan['borrow_value']
        await r.margin.cover(uid,'600003',100)
        ledger=await r.margin._load();loan=next(x for x in r.margin._open_loans(ledger,uid) if x['kind']=='stock')
        self.assertEqual(loan['borrow_value'],round(original/2,2))
        stats=await r.margin.accrue_day(2)
        self.assertEqual(stats['interest'],round(original/2*getattr(CFG,'margin_stock_rate_annual',.10)/252,2))
        await r.margin.cover(uid,'600003',100)
        self.assertEqual((await r.margin.accrue_day(3))['interest'],0.)
    async def test_tick_persists_public_feed_and_prevents_secret_leak(self):
        async with mutation(self.r.db):create_event(self.r.engine.causal,0)
        await self.r.tick()
        feed=await self.r.execute({'method':'news_feed','after':0})
        self.assertTrue(feed['items'])
        self.assertNotIn('truth',json.dumps(feed));self.assertNotIn('"seed"',json.dumps(feed))
        news=await self.req('query',{'action':'news'})
        self.assertTrue(news['data'])
        self.assertNotIn('冲击',news['text'])
    async def test_real_trade_house_cash_stock_and_fees(self):
        code='600003';i=self.r.engine.causal['profile']['codes'].index(code);s=self.r.engine.causal
        before=int(s['house_cash'][i])+(cents((await self.r.db.get_account(self.actor['senderId']))['cash_available']))
        shares=int(s['house_inventory'][i])
        result=await self.req('trade',{'action':'buy','code':code,'quantity':100})
        self.assertTrue(result['ok']);pos=await self.r.db.get_position(self.actor['senderId'],code)
        self.assertEqual(int(s['house_inventory'][i])+pos['quantity'],shares)
        cash=int(s['house_cash'][i])+cents((await self.r.db.get_account(self.actor['senderId']))['cash_available'])
        rows=await self.r.db.get_user_trades(self.actor['senderId']);fees=sum(cents(r['fee']) for r in rows)
        self.assertEqual(before-cash,fees);self.assertTrue((await self.r.db.audit())['ok'])
    async def test_failure_restores_world_and_house(self):
        before=json.dumps(encode(self.r.engine.causal),sort_keys=True)
        async def fail(*args,**kw):raise RuntimeError('sql fault')
        with patch.object(self.r.db,'insert_trade',fail):
            with self.assertRaises(RuntimeError):await self.req('trade',{'action':'buy','code':'600003','quantity':100})
        self.assertEqual(before,json.dumps(encode(self.r.engine.causal),sort_keys=True))
    async def test_restart_keeps_model_and_event_state(self):
        async with mutation(self.r.db):create_event(self.r.engine.causal,0)
        for _ in range(3):await self.r.tick()
        before=json.dumps(encode(self.r.engine.causal),sort_keys=True)
        await self.r.close();self.r=MarketRuntime(self.tmp.name,options=copy.deepcopy(self.options));await self.r.start(False)
        self.assertEqual(before,json.dumps(encode(self.r.engine.causal),sort_keys=True))
        self.assertEqual((await self.r.execute({'method':'health'}))['model_version'],VERSION)
    async def test_funding_exhaustion_never_creates_money_or_inventory(self):
        i=self.r.engine.causal['profile']['codes'].index('600003');self.r.engine.causal['house_inventory'][i]=0
        await self.req('trade',{'action':'buy','code':'600003','quantity':100})
        self.assertIsNone(await self.r.db.get_position(self.actor['senderId'],'600003'))
        self.assertEqual(int(self.r.engine.causal['house_inventory'][i]),0)
    async def test_public_company_calendar_and_event_queries(self):
        a=await self.req('query',{'action':'stock','code':'600003'})
        self.assertIn('public_financials',a['data'])
        b=await self.req('query',{'action':'calendar'});self.assertTrue(b['ok'])
        for forbidden in ('"truth"','"core_profit"','"seed"'):self.assertNotIn(forbidden,json.dumps([a,b]))
    async def test_health_insolvency_uses_zero_recovery_not_price_floor(self):
        s=self.r.engine.causal;i=s['profile']['codes'].index('600003')
        await self.r.db.upsert_position(self.actor['senderId'],'600003',100,100,9)
        s['public_book'][i]=-1;s['credit_bad_days'][i]=40;s['cash'][i]=0;s['debt'][i]=s['assets'][i]*2
        async with mutation(self.r.db):await self.r.corporate.run_day()
        s['day']+=3
        async with mutation(self.r.db):await self.r.corporate.run_day()
        self.assertTrue(self.r.engine.is_delisted('600003'));self.assertIsNone(await self.r.db.get_position(self.actor['senderId'],'600003'))
    async def test_legacy_migration_keeps_prices_orders_cash(self):
        await self.r.close()
        path=self.tmp.name+'/old'
        legacy=MarketRuntime(path,options={'npcTrading':False,'rules':{'auction_enabled':False,'npc_count':0,'trade_cooldown_seconds':0}});await legacy.start(False)
        await legacy.execute({'method':'account','params':{'action':'open'},'actor':self.actor,'operation_id':'old-open'})
        before=legacy.engine.snapshot_rows();cash=dict(await legacy.db.get_account(self.actor['senderId']))
        await legacy.close()
        migrated=MarketRuntime(path,options=copy.deepcopy(self.options));await migrated.start(False)
        try:
            self.assertEqual(before,migrated.engine.snapshot_rows())
            self.assertEqual(cash,dict(await migrated.db.get_account(self.actor['senderId'])))
            self.assertEqual(migrated.engine.causal['migration'],'legacy-rebased-on-existing-quotes')
        finally:await migrated.close()

if __name__=='__main__':unittest.main()
