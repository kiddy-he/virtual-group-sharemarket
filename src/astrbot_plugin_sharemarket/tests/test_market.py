import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import fields
from astrbot_plugin_sharemarket.config import CFG,Config,validate_config
from astrbot_plugin_sharemarket.runtime import MarketRuntime
from astrbot_plugin_sharemarket.market import calendar,stocks
from astrbot_plugin_sharemarket.storage.db import Database
from astrbot_plugin_sharemarket.storage.money import cents
from astrbot_plugin_sharemarket.game.atomic import mutation
from astrbot_plugin_sharemarket.game.valuation import ValuationService
from astrbot_plugin_sharemarket.game.clock import day_key,TZ
from datetime import datetime

class MarketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original=copy.deepcopy(CFG)
        for field in fields(CFG):setattr(CFG,field.name,copy.deepcopy(getattr(Config(),field.name)))
        self.stock_pool=dict(stocks.STOCK_POOL);self.short_pool=dict(stocks.STOCK_BY_SHORT)
        self.tmp=tempfile.TemporaryDirectory();self.counter=0
        self.options={'rules':{'auction_enabled':False,'npc_count':0,'trade_cooldown_seconds':0,'dividend_prob':0,'suspend_prob':0,'st_prob':0,'delist_prob':0},'npcTrading':False}
        self.r=MarketRuntime(self.tmp.name,options=self.options)
        await self.r.start(False)
        self.actor={'senderId':'700000001','accountId':'default','scope':'private','identity':'admin','nickname':'Test'}
        self.other={**self.actor,'senderId':'700000002','identity':'member','nickname':'Other'}
        await self.request('account',{'action':'open'})
    async def asyncTearDown(self):
        await self.r.close();self.tmp.cleanup()
        for field in fields(CFG):setattr(CFG,field.name,getattr(self.original,field.name))
        stocks.STOCK_POOL.clear();stocks.STOCK_POOL.update(self.stock_pool)
        stocks.STOCK_BY_SHORT.clear();stocks.STOCK_BY_SHORT.update(self.short_pool)
    async def request(self,method,params,actor=None,opid=None):
        self.counter+=1
        return await self.r.execute({'method':method,'params':params,'actor':actor or self.actor,'operation_id':opid or f'op-{self.counter}'})
    async def acc(self,uid='700000001'):return dict(await self.r.db.get_account(uid))
    async def test_business_replies_only_advertise_fx_commands(self):
        opened=await self.request('account',{'action':'open'},actor=self.other)
        watch=await self.request('account',{'action':'watchlist'})
        issued=await self.request('play',{'action':'issue','name':'前缀验收','price':1,'quantity':100000})
        for response in (opened,watch,issued):
            self.assertIn('/fx ',response['text'])
            self.assertNotRegex(response['text'],r'/炒股|/打新')
        # Error and partial-fill branches must advertise the same supported entry.
        for path in Path(__file__).resolve().parents[1].joinpath('game').glob('*.py'):
            self.assertNotRegex(path.read_text(),r'/炒股|/打新',str(path))
    async def test_buy_sell_buy_uses_unsettled_cash(self):
        await self.request('trade',{'action':'buy','code':'600003','quantity':5000})
        await self.r.db.unlock_all_sellable();self.r.matcher.reset_liquidity()
        await self.request('trade',{'action':'sell','code':'600003','quantity':5000})
        self.r.matcher.reset_liquidity();await self.r.db.update_cash_full('700000001',(await self.acc())['cash_available'],0,0)
        await self.r.trade.buy('700000001','600003',100)
        self.assertEqual((await self.acc())['cash_withdrawable'],0)
        self.assertTrue((await self.r.db.audit())['ok'])
    async def test_failure_rolls_back_cash_positions_trades_and_book(self):
        before=await self.acc();rng=self.r.matcher.mm.rng.getstate()
        async def fail(*a,**kw):raise RuntimeError('injected SQL failure')
        with patch.object(self.r.db,'insert_trade',fail):
            with self.assertRaises(RuntimeError):await self.request('trade',{'action':'buy','code':'600003','quantity':100})
        self.assertEqual(await self.acc(),before)
        self.assertIsNone(await self.r.db.get_position('700000001','600003'))
        self.assertEqual(await self.r.db.get_all_open_orders(),[])
        self.assertEqual(self.r.matcher.mm.rng.getstate(),rng)
        self.assertFalse(self.r.matcher.books)
    async def test_transaction_owned_by_task(self):
        started=asyncio.Event();attempted=asyncio.Event()
        async def first():
            try:
                async with self.r.db.transaction():
                    await self.r.db.set_meta('A','1');started.set();await attempted.wait();await asyncio.sleep(.01);raise RuntimeError()
            except RuntimeError:pass
        async def second():
            await started.wait();attempted.set();await self.r.db.set_meta('B','2')
        await asyncio.gather(first(),second())
        self.assertIsNone(await self.r.db.get_meta('A'));self.assertEqual(await self.r.db.get_meta('B'),'2')
    async def test_cancelled_transaction_does_not_leak(self):
        started=asyncio.Event()
        async def task():
            async with mutation(self.r.db):
                await self.r.db.update_cash_full('700000001',1,1,0);self.r.engine.quotes['600003'].price=1
                started.set();await asyncio.Future()
        pending=asyncio.create_task(task());await started.wait();pending.cancel()
        with self.assertRaises(asyncio.CancelledError):await pending
        self.assertEqual((await self.acc())['cash_available'],1_000_000)
        self.assertNotEqual(self.r.engine.get('600003').price,1)
    async def test_idempotent_order_replay(self):
        params={'action':'buy','code':'600003','quantity':100}
        a,b=await asyncio.gather(self.request('trade',params,opid='same'),self.request('trade',params,opid='same'))
        self.assertEqual(a,b);self.assertEqual(len(await self.r.db.get_user_trades('700000001')),1)
    async def test_id_conflict_rejected(self):
        await self.request('query',{'action':'overview'},opid='same')
        with self.assertRaisesRegex(ValueError,'identity conflict'):await self.request('query',{'action':'news'},opid='same')
    async def test_two_users_concurrent(self):
        await self.request('account',{'action':'open'},self.other)
        await asyncio.gather(self.request('trade',{'action':'buy','code':'600003','quantity':100}),self.request('trade',{'action':'buy','code':'600003','quantity':100},self.other))
        self.assertEqual((await self.r.db.get_position('700000001','600003'))['quantity'],100)
        self.assertEqual((await self.r.db.get_position('700000002','600003'))['quantity'],100)
        self.assertTrue((await self.r.db.audit())['ok'])
    async def test_reserves_and_cancel_restore_settled_cash(self):
        price=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':price})
        orders=await self.r.db.get_user_open_orders('700000001');self.assertEqual(len(orders),1)
        acc=await self.acc();self.assertEqual(cents(acc['cash_available'])+cents(acc['cash_frozen']),100_000_000)
        self.assertEqual(cents(acc['cash_frozen']),cents(orders[0]['frozen']))
        await self.request('trade',{'action':'cancel','order_id':orders[0]['order_id']})
        self.assertEqual((await self.acc())['cash_available'],1_000_000)
        self.assertEqual((await self.acc())['cash_withdrawable'],1_000_000)
    async def test_maker_reserve_is_per_order(self):
        await self.request('account',{'action':'open'},self.other)
        await self.r.db.upsert_position('700000002','600003',100,100,8)
        p=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':p})
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':round(p*.99,2)})
        before=[dict(o) for o in await self.r.db.get_user_open_orders('700000001')]
        self.r.matcher.liquidity['600003']=[[],[]]
        await self.request('trade',{'action':'sell','code':'600003','quantity':100,'price':p},self.other)
        untouched=min(before,key=lambda r:r['price']);second=await self.r.db.get_order(untouched['order_id'])
        self.assertEqual(second['frozen'],untouched['frozen']);self.assertTrue((await self.r.db.audit())['ok'])
    async def test_self_trade_rejected_before_writes(self):
        p=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':p})
        await self.r.db.upsert_position('700000001','600003',100,100,8)
        before=await self.acc()
        with self.assertRaisesRegex(ValueError,'自己的'):await self.request('trade',{'action':'sell','code':'600003','quantity':100,'price':p})
        self.assertEqual(before,await self.acc())
    async def test_best_price_and_mm_depth_per_tick(self):
        m=self.r.matcher;m.restore(900,'other','600003','sell',9.2,100)
        fills=m.place(901,'buyer','600003','buy',9.6,100,8.8)
        self.assertLess(fills[0].price,9.2)
        total=sum(f.quantity for f in fills if f.maker_order_id is None)
        for i in range(10):total+=sum(f.quantity for f in m.place(902+i,'buyer','600003','buy',9.6,1000,8.8) if f.maker_order_id is None)
        self.assertLessEqual(total,CFG.mm_depth)
        levels=m.five_levels('600003',8.8)
        self.assertEqual(levels[0],sorted(levels[0],reverse=True));self.assertLessEqual(len(levels[0]),5)
    async def test_t_plus_one(self):
        await self.request('trade',{'action':'buy','code':'600003','quantity':100})
        with self.assertRaisesRegex(ValueError,'T\\+1'):await self.request('trade',{'action':'sell','code':'600003','quantity':100})
        await self.r.dayclose.run(self.r.board,self.r.price_of,'test-day')
        self.r.matcher.reset_liquidity();await self.request('trade',{'action':'sell','code':'600003','quantity':100})
    async def test_partial_fills_charge_minimum_commission_once(self):
        await self.request('account',{'action':'open'},self.other)
        await self.r.db.upsert_position('700000002','600003',200,200,8)
        p=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':200,'price':p})
        self.r.matcher.liquidity['600003']=[[],[]]
        await self.request('trade',{'action':'sell','code':'600003','quantity':100,'price':p},self.other)
        await self.request('trade',{'action':'sell','code':'600003','quantity':100,'price':p},self.other)
        fees=sum(t['fee'] for t in await self.r.db.get_user_trades('700000001'))
        self.assertLess(fees,6);self.assertTrue((await self.r.db.audit())['ok'])
    async def test_bad_numbers_never_create_orders(self):
        for p in [float('nan'),float('inf'),-1,True,0]:
            with self.assertRaises(ValueError):await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':p})
        for q in [True,1.5,-100,0,10**15]:
            with self.assertRaises(ValueError):await self.request('trade',{'action':'buy','code':'600003','quantity':q})
        self.assertEqual(await self.r.db.get_all_open_orders(),[])
    async def test_cannot_cancel_someone_else(self):
        p=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':p})
        oid=(await self.r.db.get_user_open_orders('700000001'))[0]['order_id']
        with self.assertRaises(ValueError):await self.request('trade',{'action':'cancel','order_id':oid},self.other)
    async def test_net_assets_do_not_increase_on_borrow(self):
        before=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']['net_assets']
        await self.r.margin.borrow_cash('700000001',100_000)
        after=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']
        self.assertEqual(before,after['net_assets']);self.assertEqual(after['debt'],100_000)
        self.assertEqual((await self.r.board.top(self.r.price_of))[0]['return_pct'],0)
    async def test_split_assets_preserved(self):
        await self.r.db.upsert_position('700000001','600003',1000,1000,8)
        before=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']['net_assets']
        with patch.object(self.r.corporate.rng,'uniform',return_value=.5):await self.r.corporate._stock_dividend('600003',self.r.engine.get('600003'),stocks.STOCK_POOL['600003'],{'split':0})
        after=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']['net_assets']
        self.assertAlmostEqual(before,after,places=2)
    async def test_dayclose_failure_retries_same_day(self):
        old=self.r.engine.get('600003').prev_close
        async def fail(*a):raise RuntimeError('candles failure')
        with patch.object(self.r.db,'insert_candles',fail):
            with self.assertRaises(RuntimeError):await self.r.dayclose.run(self.r.board,self.r.price_of,'same-day')
        self.assertEqual(self.r.dayclose._day_seq,0);self.assertEqual(self.r.engine.get('600003').prev_close,old)
        await self.r.dayclose.run(self.r.board,self.r.price_of,'same-day')
        await self.r.dayclose.run(self.r.board,self.r.price_of,'same-day')
        self.assertEqual(await self.r.db.get_meta('trading_day_seq'),'1')
    async def test_multiple_virtual_days_have_distinct_snapshots(self):
        for i in range(3):await self.r.dayclose.run(self.r.board,self.r.price_of,f'day-{i}')
        rows=await self.r.db.list_leaderboard_snapshots(14)
        self.assertEqual(len({r['day_ts'] for r in rows}),3)
    async def test_realtime_no_morning_or_lunch_settlement(self):
        CFG.market_mode='realtime';self.r.clock.mode='realtime'
        for hh,mm in [(8,0),(9,26),(11,31),(13,0)]:
            await self.r.tick(datetime(2026,11,2,hh,mm,tzinfo=TZ).timestamp())
            self.assertEqual(await self.r.db.get_meta('trading_day_seq'),None)
        await self.r.tick(datetime(2026,11,2,15,1,tzinfo=TZ).timestamp())
        await self.r.tick(datetime(2026,11,2,15,2,tzinfo=TZ).timestamp())
        self.assertEqual(await self.r.db.get_meta('trading_day_seq'),'1')
    async def test_restart_restores_state_day_and_open_orders(self):
        p=round(self.r.price_of('600003')*.95,2)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':p})
        async with mutation(self.r.db):self.r.engine.set_st('600003',True);self.r.engine.delist('600004');self.r.engine.suspend('600005',20);self.r.corporate._delisting['600006']=[1.0]
        started=self.r.clock.started
        await self.r.close();self.r=MarketRuntime(self.tmp.name,options=self.options);await self.r.start(False)
        self.assertTrue(self.r.engine.is_st('600003'));self.assertTrue(self.r.engine.is_delisted('600004'));self.assertTrue(self.r.engine.is_suspended('600005'))
        self.assertEqual(self.r.corporate._delisting['600006'],[1.0]);self.assertEqual(self.r.clock.started,started)
        self.assertEqual(len(self.r.matcher.book('600003').bids),1)
    async def test_auction_buy_sell_settle_and_recover(self):
        CFG.auction_enabled=True;self.r.clock.reset();calendar.SESSION=self.r.clock
        await self.request('account',{'action':'open'},self.other);await self.r.db.upsert_position('700000002','600003',100,100,8)
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':8.8})
        await self.request('trade',{'action':'sell','code':'600003','quantity':100,'price':8.8},self.other)
        await self.r.auction.run('test')
        self.assertEqual((await self.r.db.get_position('700000001','600003'))['quantity'],100)
        self.assertIsNone(await self.r.db.get_position('700000002','600003'));self.assertTrue((await self.r.db.audit())['ok'])
    async def test_checkin_concurrent_only_credits_once(self):
        results=await asyncio.gather(self.r.quest.handle_checkin('700000001'),self.r.quest.handle_checkin('700000001'))
        self.assertEqual(sum(r['reward'] for r in results),100);self.assertEqual((await self.acc())['cash_available'],1_000_100)
    async def test_task_count_is_snapshot_and_resets_without_breaking_streak(self):
        await self.r.quest.handle_checkin('700000001')
        await self.r.db.upsert_position('700000001','600003',100,100,8)
        for i in range(4):await self.r.quest.submit_task('700000001','position_count',{'position_count':999})
        task=next(t for t in await self.r.quest.get_daily_tasks('700000001') if t['task_id']=='position_count')
        self.assertEqual(task['progress'],1);self.assertFalse(task['claimed'])
        await self.r.db.conn.execute('UPDATE quest_days SET day_ts=0')
        await self.r.quest.settle_day('700000001')
        self.assertEqual((await self.r.quest.status('700000001'))['checkin_streak'],1)
        self.assertEqual(json.loads((await self.r.quest.status('700000001'))['daily_task_progress']),{})
    async def test_season_reward_list_compatible_and_credited_once(self):
        await self.r.db.conn.execute('UPDATE season_defs SET rewards=?',(json.dumps([100,300,600,1000,1500,2000]),))
        a=await self.r.season.get_season_reward('700000001');b=await self.r.season.get_season_reward('700000001')
        self.assertTrue(a['success']);self.assertFalse(b['success']);self.assertEqual((await self.acc())['cash_available'],1_000_100)
    async def test_ipo_issue_draw_list_and_restart(self):
        self.assertTrue((await self.r.ipo.issue_stock('700000001','测试公司',1,1000))[0])
        ledger=await self.r.ipo._load();code=next(iter(ledger['ipos'].values()))['code']
        await self.r.ipo.subscribe('700000001',code,1)
        await self.r.ipo.draw(code)
        self.assertIn(code,stocks.STOCK_POOL)
        self.assertEqual((await self.acc())['cash_frozen'],0)
        await self.r.close();self.r=MarketRuntime(self.tmp.name,options=self.options);await self.r.start(False)
        self.assertIn(code,stocks.STOCK_POOL)
    async def test_ipo_draw_is_automatically_scheduled(self):
        await self.r.ipo.issue_stock('700000001','测试公司',1,1000)
        ledger=await self.r.ipo._load();ipo=next(iter(ledger['ipos'].values()));ipo['close_ts']=0;await self.r.ipo._save(ledger)
        await self.r.dayclose.run(self.r.board,self.r.price_of,'ipo-day')
        self.assertEqual((await self.r.ipo._load())['ipos'][str(ipo['id'])]['status'],'drawn')
    async def test_private_results_and_group_membership(self):
        actor={**self.actor,'scope':'group','groupId':'700000099'}
        result=await self.request('account',{'action':'funds'},actor)
        self.assertTrue(result['private'])
        rank=await self.request('query',{'action':'rank'},actor);self.assertEqual(len(rank['data']),1)
    async def test_admin_cannot_be_claimed_through_params(self):
        with self.assertRaisesRegex(ValueError,'admin only'):await self.request('admin',{'action':'pause','identity':'admin'},self.other)
    async def test_outbox_ack_owner_and_pending_after_restart(self):
        result=await self.request('query',{'action':'overview'},opid='outbox')
        own=await self.r.execute({'method':'outbox','actor':self.actor});other=await self.r.execute({'method':'outbox','actor':self.other})
        self.assertTrue(own['items']);self.assertEqual(other['items'],[])
        with self.assertRaises(ValueError):await self.r.execute({'method':'ack','actor':self.other,'id':'outbox','receipt':{'id':1}})
        await self.r.execute({'method':'ack','actor':self.actor,'id':'outbox','receipt':{'id':1}})
        self.assertFalse(any(i['id']=='outbox' for i in (await self.r.execute({'method':'outbox','actor':self.actor}))['items']))
    async def test_plot_failure_keeps_text(self):
        result=await self.request('query',{'action':'chart','code':'600003'})
        result=await self.r.render(result);self.assertTrue(result['text'])
    async def test_integer_cents_and_no_mint_from_roundoff(self):
        for i in range(100):await self.r.db.grant_cash('700000001',.01,'compensation')
        self.assertEqual((await self.acc())['cash_available'],1_000_001)
        self.assertTrue((await self.r.db.audit())['ok'])
    async def test_config_and_probability_validation(self):
        bad=copy.deepcopy(CFG);bad.tick_seconds=0
        with self.assertRaises(ValueError):validate_config(bad)
        self.r.engine._tick_seconds=6
        self.assertAlmostEqual(self.r.engine.event_probability(.1),.19)
        self.assertEqual(day_key(datetime(2026,11,2,0,1,tzinfo=TZ).timestamp()),int(datetime(2026,11,2,tzinfo=TZ).timestamp()))
    async def test_database_backup_consistency(self):
        await self.r.db.backup();self.assertTrue(Path(self.r.db.backup_path()).is_file())

    async def test_admin_backup_and_replay(self):
        before=await self.acc()
        first=await self.request('admin',{'action':'backup'},opid='backup-once')
        self.assertEqual(first,await self.request('admin',{'action':'backup'},opid='backup-once'))
        import sqlite3
        with sqlite3.connect(self.r.db.backup_path()) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('SELECT cash_available_cents FROM accounts WHERE user_id=?',('700000001',)).fetchone()[0],cents(before['cash_available']))
        with self.assertRaisesRegex(ValueError,'private'):
            await self.request('admin',{'action':'backup'},{**self.actor,'scope':'group','groupId':'700000099'})
    async def test_backup_refuses_transaction_and_can_retry(self):
        async with self.r.db.transaction():
            with self.assertRaises(ValueError):await self.r.db.backup()
        await self.r.db.backup()
        self.assertTrue(Path(self.r.db.backup_path()).exists())
    async def test_reward_epoch_after_rebirth(self):
        await self.r.db.grant_cash('700000001',100,'reward')
        await self.r.db.do_rebirth('700000001',500_000,int(time.time()))
        value=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']
        self.assertEqual(value['investment_return_pct'],0)
        await self.r.db.grant_cash('700000001',20,'reward')
        value=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']
        self.assertEqual(value['investment_return_pct'],0)
        self.assertGreater(value['game_return_pct'],0)
    async def test_missing_quote_does_not_erase_liability_or_position(self):
        await self.r.trade.buy('700000001','600003',100)
        with self.assertRaisesRegex(ValueError,'行情'):
            await ValuationService(self.r.db).all(lambda code:None)
    async def test_fee_prop_changes_real_fee_once(self):
        bought=await self.r.props.buy_prop('700000001','fee_card',1);self.assertTrue(bought['ok'])
        used=await self.r.props.use_prop('700000001','fee_card');self.assertTrue(used['ok'])
        await self.r.trade.buy('700000001','600003',100)
        discounted=(await self.r.db.get_user_trades('700000001'))[0]['fee']
        self.r.matcher.reset_liquidity();await self.r.trade.buy('700000001','600003',100)
        normal=(await self.r.db.get_user_trades('700000001'))[0]['fee']
        self.assertLess(discounted,normal)
        self.assertLessEqual(abs(cents(discounted)*2-cents(normal)),1)
    async def test_concurrent_prop_use_does_not_duplicate_effect(self):
        await self.r.props.buy_prop('700000001','fee_card',1)
        results=await asyncio.gather(*(self.r.props.use_prop('700000001','fee_card') for _ in range(3)))
        self.assertEqual(sum(bool(r['ok']) for r in results),1)
    async def test_rebirth_removes_live_matching_orders(self):
        price=round(self.r.price_of('600003')*.95,2)
        await self.r.trade.buy('700000001','600003',100,price)
        await self.r.db.set_status('700000001','bankrupt',0)
        ok,_=await self.r.accounts.rebirth('700000001');self.assertTrue(ok)
        self.assertEqual(await self.r.db.get_all_open_orders(),[])
        self.assertFalse(any(book.bids or book.asks for book in self.r.matcher.books.values()))
        self.assertTrue((await self.r.db.audit())['ok'])
    async def test_interest_idempotent_after_restart(self):
        await self.r.margin.borrow_cash('700000001',10_000)
        await self.r.margin.accrue_day(1)
        before=await self.r.margin._load()
        await self.r.close();self.r=MarketRuntime(self.tmp.name,options=self.options);await self.r.start(False)
        await self.r.margin.accrue_day(1)
        self.assertEqual(before,await self.r.margin._load())
    async def test_start_failure_can_retry(self):
        await self.r.close()
        with patch.object(self.r.npc,'ensure_accounts',side_effect=RuntimeError('injected start failure')):
            with self.assertRaises(RuntimeError):await self.r.start(False)
        self.assertFalse(self.r._started);self.assertIsNone(self.r.db.conn)
        await self.r.start(False);self.assertTrue(self.r._started)
    async def test_real_png_is_durable_and_replay_uses_same_artifact(self):
        await self.r.tick()
        query=await self.request('query',{'action':'chart','code':'600003'},opid='chart-replay')
        result=await self.r.render(query)
        path=Path(result['artifact']);self.assertEqual(path.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(result['artifact'],(await self.r.render(query))['artifact'])
        replay=await self.r.execute({'method':'result','actor':self.actor,'id':'chart-replay'})
        self.assertEqual(result['artifact'],replay['artifact'])
        import os
        os.utime(path,(0,0));await self.r.cleanup_artifacts();self.assertTrue(path.exists())
    async def test_pending_receipts_not_starved_by_other_actors(self):
        await self.r.execute({'method':'ack','actor':self.actor,'id':'op-1','receipt':{}})
        for i in range(51):await self.request('query',{'action':'overview'},self.other)
        await self.request('query',{'action':'overview'},opid='mine')
        own=await self.r.execute({'method':'outbox','actor':self.actor})
        self.assertEqual([r['id'] for r in own['items']],['mine'])
        with self.assertRaises(ValueError):await self.r.execute({'method':'result','actor':self.other,'id':'mine'})
    async def test_replay_after_nickname_change(self):
        first=await self.request('trade',{'action':'buy','code':'600003','quantity':100},opid='renamed')
        second=await self.request('trade',{'action':'buy','code':'600003','quantity':100},{**self.actor,'nickname':'Changed'},opid='renamed')
        self.assertEqual(first,second)
        self.assertEqual(len(await self.r.db.get_user_trades('700000001')),1)
    async def test_calendar_overrides_and_future_years(self):
        try:
            with self.assertRaises(ValueError):calendar.is_trading_day(datetime(2027,1,4,tzinfo=TZ))
            calendar.configure({'coveredYears':[2027],'closedDates':['2027-01-04'],'openDates':['2027-01-09']})
            self.assertFalse(calendar.is_trading_day(datetime(2027,1,4,tzinfo=TZ)))
            self.assertTrue(calendar.is_trading_day(datetime(2027,1,9,tzinfo=TZ)))
        finally:calendar.configure({})
    async def test_migration_from_float_accounts(self):
        import sqlite3
        from astrbot_plugin_sharemarket.storage.db import SCHEMA
        path=str(Path(self.tmp.name)/'legacy.sqlite')
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA)
            conn.execute('INSERT INTO accounts(user_id,user_name,cash_available,cash_withdrawable,cash_frozen,initial_cash,created_ts) VALUES(?,?,?,?,?,?,?)',('700000003','Legacy',123.45,23.45,7.89,131.34,0))
        db=Database(path)
        try:
            await db.open();account=await db.get_account('700000003')
            self.assertEqual(account['cash_available'],123.45);self.assertEqual(account['cash_frozen'],7.89)
            self.assertTrue((await db.audit())['ok'])
            await db.close();await db.open()
            ledger=await (await db.conn.execute('SELECT COUNT(*) n FROM cash_ledger')).fetchone()
            self.assertEqual(ledger['n'],1)
        finally:await db.close()
    async def test_public_service_cannot_mutate_player_accounts(self):
        service={'identity':'service','serviceJobId':'fixture-job','accountId':'default','scope':'group','groupId':'700000099'}
        result=await self.request('broadcast',{'action':'overview'},service,opid='public-overview')
        self.assertTrue(result['ok'])
        with self.assertRaises(ValueError):await self.request('trade',{'action':'buy','code':'600003','quantity':100},service)
        with self.assertRaises(ValueError):await self.request('broadcast',{'action':'funds'},service)
        self.assertEqual(len(await self.r.db.list_accounts()),1)

    async def test_repeated_cancel_during_commit_keeps_memory_and_sql_consistent(self):
        started=asyncio.Event();release=asyncio.Event();original=self.r.db.conn.raw.commit
        async def delayed():
            started.set();await release.wait();await original()
        with patch.object(self.r.db.conn.raw,'commit',delayed):
            task=asyncio.create_task(self.request('admin',{'action':'pause'},opid='commit-cancel'))
            await started.wait();task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0);release.set()
            result=await task
        self.assertTrue(result['ok']);self.assertTrue(self.r.engine.paused)
        replay=await self.request('admin',{'action':'pause'},opid='commit-cancel');self.assertEqual(result,replay)
    async def test_short_split_preserves_net_assets(self):
        await self.r.margin.borrow_stock('700000001','600003',100)
        before=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']['net_assets']
        async with mutation(self.r.db):
            with patch.object(self.r.corporate.rng,'uniform',return_value=.5):
                await self.r.corporate._stock_dividend('600003',self.r.engine.get('600003'),stocks.STOCK_POOL['600003'],{'split':0})
        after=(await ValuationService(self.r.db).all(self.r.price_of))['700000001']['net_assets']
        self.assertEqual(before,after)
    async def test_auction_orders_restore_before_clearing(self):
        self.options['rules']['auction_enabled']=True;CFG.auction_enabled=True;self.r.clock.reset()
        await self.request('trade',{'action':'buy','code':'600003','quantity':100,'price':8.8})
        await self.r.close();self.r=MarketRuntime(self.tmp.name,options=self.options);await self.r.start(False)
        self.assertTrue(self.r.auction.has_orders())
        self.assertEqual(len(await self.r.db.get_all_open_orders()),1)
        await self.r.auction.run('recovered')
        self.assertFalse(self.r.auction.has_orders())
        self.assertTrue((await self.r.db.audit(strict_reserves=True))['ok'])
    async def test_achievements_claimed_atomically(self):
        before=(await self.acc())['cash_available']
        with patch.object(self.r.achieve,'list_achievements',return_value=[{'id':'fixture-achievement','done':True}]):
            results=await asyncio.gather(*(self.r.achieve.claim('700000001',self.r.price_of) for _ in range(3)))
        self.assertEqual(sum(r['reward'] for r in results),50)
        self.assertEqual((await self.acc())['cash_available'],before+50)
    async def test_strict_audit_includes_ipo_issuer_and_subscription_reserves(self):
        await self.r.ipo.issue_stock('700000001','测试发行',1,1000)
        ledger=await self.r.ipo._load();code=next(iter(ledger['ipos'].values()))['code']
        await self.r.ipo.subscribe('700000001',code,1)
        self.assertTrue((await self.r.db.audit(strict_reserves=True))['ok'])
        await self.r.ipo.draw(code)
        self.assertTrue((await self.r.db.audit(strict_reserves=True))['ok'])
    async def test_invalid_margin_ledger_is_rejected(self):
        await self.r.margin.borrow_cash('700000001',100)
        ledger=await self.r.margin._load();next(iter(ledger['loans'].values()))['principal']=-10
        await self.r.db.set_meta('margin.ledger.v1',json.dumps(ledger))
        with self.assertRaises(ValueError):await ValuationService(self.r.db).all(self.r.price_of)

    async def test_disabled_tasks_and_season_do_not_grant_trade_progress(self):
        self.r.options['features']['quests']=False;self.r.options['features']['season']=False
        with patch.object(self.r.quest,'submit_task',side_effect=AssertionError('disabled tasks')),patch.object(self.r.season,'update_season_points',side_effect=AssertionError('disabled season')):
            await self.request('trade',{'action':'buy','code':'600003','quantity':100})
            await self.request('query',{'action':'rank'})
    async def test_cash_journal_links_to_original_operation(self):
        await self.request('trade',{'action':'buy','code':'600003','quantity':100},opid='journal-order')
        rows=await (await self.r.db.conn.execute('SELECT * FROM cash_ledger WHERE operation_id=?',('journal-order',))).fetchall()
        self.assertGreaterEqual(len(rows),1)
        self.assertIsNone(self.r.db.operation_id)

    async def test_reload_respects_new_engine_rules_and_notice(self):
        await self.r.close()
        self.options['rules'].update({'tick_seconds':6,'market_paused':True,'notice':'暂停测试'})
        self.r=MarketRuntime(self.tmp.name,options=self.options);await self.r.start(False)
        self.assertEqual(self.r.engine._tick_seconds,6)
        self.assertTrue(self.r.engine.paused)
        self.assertEqual(await self.r.db.get_meta('notice'),'暂停测试')
    async def test_shutdown_during_commit_does_not_leave_tick_loop_running(self):
        started=asyncio.Event();release=asyncio.Event();original=self.r.db.conn.raw.commit
        async def delayed():started.set();await release.wait();await original()
        with patch.object(self.r.db.conn.raw,'commit',delayed):
            self.r._task=asyncio.create_task(self.r._loop())
            await started.wait();closing=asyncio.create_task(self.r.close())
            await asyncio.sleep(0);release.set();await asyncio.wait_for(closing,2)
        self.assertFalse(self.r._started)




    async def test_help_image_rules_cache_and_text_fallback(self):
        from PIL import Image
        from astrbot_plugin_sharemarket.render.help import help_text
        self.assertIsNone(await self.r.db.get_account(self.other['senderId']))
        newcomer=await self.request('query',{'action':'help'},actor=self.other,opid='newcomer-help')
        self.assertIn('/fx 开户',newcomer['text'])
        self.assertIsNone(await self.r.db.get_account(self.other['senderId']))
        result=await self.request('query',{'action':'help'},opid='help-card')
        self.assertIn('/fx 开户',result['text'])
        rendered=await self.r.render(result)
        self.assertTrue(Path(rendered['artifact']).is_file())
        with Image.open(rendered['artifact']) as image:
            self.assertEqual(image.format,'PNG')
            self.assertGreaterEqual(image.width,900)
            self.assertGreater(image.height,1500)
            image.verify()
        self.assertEqual(rendered['artifact'],(await self.r.render(result))['artifact'])
        other=await self.request('query',{'action':'help'},opid='help-cached')
        self.r.health['ticks']+=1
        self.assertEqual(rendered['artifact'],(await self.r.render(other))['artifact'])
        CFG.initial_cash=123456;CFG.day_seconds=900;CFG.lot_size=50
        text=help_text(CFG)
        self.assertIn('123,456',text);self.assertIn('15 分钟',text);self.assertIn('50 股',text)
        changed=await self.request('query',{'action':'help'},opid='help-changed')
        with patch('astrbot_plugin_sharemarket.render.help.render_help',side_effect=RuntimeError('test rendering failure')):
            fallback=await self.r.render(changed)
        self.assertNotIn('artifact',fallback)
        self.assertIn('/fx 开户',fallback['text'])
        self.assertIn('render_error',fallback)

if __name__=='__main__':unittest.main()
