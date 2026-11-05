"""Public gameplay lifecycle, retirement and readable-message acceptance."""
import copy,json,tempfile,unittest
from dataclasses import fields
from unittest.mock import patch
from astrbot_plugin_sharemarket.runtime import MarketRuntime
from astrbot_plugin_sharemarket.config import CFG,Config
from astrbot_plugin_sharemarket.game.presentation import play_text,RETIRED_ACTIONS
from astrbot_plugin_sharemarket.game.props import PROP_BY_ID,PropService

class PlayPresentationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved=copy.deepcopy(CFG)
        for f in fields(CFG):setattr(CFG,f.name,copy.deepcopy(getattr(Config(),f.name)))
        self.temp=tempfile.TemporaryDirectory();self.seq=0
        self.opts={'npcTrading':False,'rules':{'auction_enabled':False,'npc_count':0,'trade_cooldown_seconds':0,'dividend_prob':0,'suspend_prob':0,'st_prob':0,'delist_prob':0}}
        self.r=MarketRuntime(self.temp.name,options=copy.deepcopy(self.opts));await self.r.start(False)
        self.actor={'senderId':'700000001','accountId':'default','scope':'private','identity':'admin','nickname':'fixture'}
        await self.req('account','open')
    async def asyncTearDown(self):
        await self.r.close();self.temp.cleanup()
        for f in fields(CFG):setattr(CFG,f.name,getattr(self.saved,f.name))
    async def req(self,method,action,params=None,op=None):
        self.seq+=1
        out=await self.r.execute({'method':method,'params':{'action':action,**(params or {})},'actor':self.actor,'operation_id':op or f'projection-{self.seq}'})
        text=out.get('text','')
        self.assertFalse(text.lstrip().startswith(('{','[')))
        for private in ('user_id','daily_task_progress','quest_info','remaining_quantity','"effect"'):
            self.assertNotIn(private,text)
        return out
    async def cash(self):return (await self.r.db.get_account(self.actor['senderId']))['cash_available']
    async def test_retired_actions_reject_without_mutation_and_without_tracking(self):
        before=await self.cash()
        for action in RETIRED_ACTIONS:
            with self.assertRaisesRegex(ValueError,'已下线'):await self.req('play',action)
        with patch.object(self.r.quest,'submit_task',side_effect=AssertionError('retired task path')),patch.object(self.r.season,'update_season_points',side_effect=AssertionError('retired season path')):
            await self.req('trade','buy',{'code':'600003','quantity':100})
            await self.req('query','rank')
            await self.req('play','buy_prop',{'prop_id':'fee_card','quantity':1})
            await self.req('play','use_prop',{'prop_id':'fee_card'})
        self.assertTrue((await self.r.db.audit(strict_reserves=True))['ok'])
    async def test_retired_speed_card_not_sold_or_consumed_but_existing_inventory_can_be_sold(self):
        self.assertNotIn('speed_card',PropService.shop_ids(self.actor['senderId'],0))
        before=await self.cash()
        with self.assertRaisesRegex(ValueError,'已下线'):await self.req('play','buy_prop',{'prop_id':'speed_card','quantity':1})
        await self.r.db.conn.execute('INSERT INTO user_props VALUES(?,?,?)',(self.actor['senderId'],'speed_card',2))
        with self.assertRaisesRegex(ValueError,'已下线'):await self.req('play','use_prop',{'prop_id':'speed_card'})
        self.assertEqual(await self.cash(),before)
        sold=await self.req('play','sell_prop',{'prop_id':'speed_card','quantity':1})
        self.assertIn('已到账',sold['text']);self.assertEqual(await self.cash(),before+100)
    async def test_checkin_credit_duplicate_replay_and_persistence(self):
        before=await self.cash();first=await self.req('play','checkin',op='checkin-fixed')
        self.assertIn('连续签到1天',first['text']);self.assertEqual(await self.cash(),before+first['data']['reward'])
        again=await self.req('play','checkin',op='checkin-fixed');self.assertEqual(first,again)
        with self.assertRaisesRegex(ValueError,'已签到'):await self.req('play','checkin')
        await self.r.close();self.r=MarketRuntime(self.temp.name,options=copy.deepcopy(self.opts));await self.r.start(False)
        with self.assertRaisesRegex(ValueError,'已签到'):await self.req('play','checkin')
        self.assertEqual(await self.cash(),before+first['data']['reward'])
    async def test_achievements_show_real_progress_and_reward_only_once(self):
        await self.req('trade','buy',{'code':'600003','quantity':100})
        before=await self.cash();first=await self.req('play','achievements',op='achieve-fixed')
        self.assertIn('股市初体验：已达成',first['text']);self.assertGreaterEqual(first['data']['reward'],50)
        self.assertEqual(await self.cash(),before+first['data']['reward'])
        await self.req('play','achievements',op='achieve-fixed')
        second=await self.req('play','achievements');self.assertEqual(second['data']['reward'],0)
        self.assertEqual(await self.cash(),before+first['data']['reward'])
    async def test_shop_purchase_sale_inventory_and_balances(self):
        shop=await self.req('play','props');self.assertEqual(len(shop['data']['shop']['items']),3)
        self.assertNotIn('speed_card',[i['prop_id'] for i in shop['data']['shop']['items']])
        before=await self.cash();buy=await self.req('play','buy_prop',{'prop_id':'lucky_card','quantity':2},op='buy-fixed')
        self.assertIn('1,000',buy['text']);self.assertEqual(await self.cash(),before-1000)
        await self.req('play','buy_prop',{'prop_id':'lucky_card','quantity':2},op='buy-fixed');self.assertEqual(await self.cash(),before-1000)
        sale=await self.req('play','sell_prop',{'prop_id':'lucky_card','quantity':1});self.assertIn('250',sale['text']);self.assertEqual(await self.cash(),before-750)
        inv=(await self.req('play','props'))['data']['owned'];self.assertEqual(next(i['quantity'] for i in inv if i['prop_id']=='lucky_card'),1)
    async def test_lucky_reward_matches_credit_and_consumes_inventory_once(self):
        await self.req('play','buy_prop',{'prop_id':'lucky_card','quantity':1});before=await self.cash()
        used=await self.req('play','use_prop',{'prop_id':'lucky_card'},op='use-fixed');amount=used['data']['effect']['amount']
        self.assertEqual(await self.cash(),before+amount);self.assertIn(str(amount),used['text'])
        await self.req('play','use_prop',{'prop_id':'lucky_card'},op='use-fixed');self.assertEqual(await self.cash(),before+amount)
    async def test_shield_effect_reaches_real_order_fee_once(self):
        await self.req('play','buy_prop',{'prop_id':'shield','quantity':1})
        used=await self.req('play','use_prop',{'prop_id':'shield'});self.assertIn('提交委托时消耗',used['text'])
        await self.req('trade','buy',{'code':'600003','quantity':100})
        self.assertEqual((await self.r.db.get_user_trades(self.actor['senderId']))[0]['fee'],0)
        self.r.matcher.reset_liquidity();await self.req('trade','buy',{'code':'600003','quantity':100})
        self.assertGreater((await self.r.db.get_user_trades(self.actor['senderId']))[0]['fee'],0)
    async def test_fee_card_effect_survives_restart_and_applies_once(self):
        await self.req('play','buy_prop',{'prop_id':'fee_card','quantity':1});await self.req('play','use_prop',{'prop_id':'fee_card'})
        await self.r.close();self.r=MarketRuntime(self.temp.name,options=copy.deepcopy(self.opts));await self.r.start(False)
        await self.req('trade','buy',{'code':'600003','quantity':100});discounted=(await self.r.db.get_user_trades(self.actor['senderId']))[0]['fee']
        self.r.matcher.reset_liquidity();await self.req('trade','buy',{'code':'600003','quantity':100});normal=(await self.r.db.get_user_trades(self.actor['senderId']))[0]['fee']
        self.assertLess(discounted,normal);self.assertAlmostEqual(discounted*2,normal,delta=.01)
    async def test_info_samples_are_visible_with_no_future_prediction_claim(self):
        await self.req('play','buy_prop',{'prop_id':'info_card','quantity':1});out=await self.req('play','use_prop',{'prop_id':'info_card'})
        self.assertIn('不是本市场后续走势预测',out['text'])
        for sample in out['data']['effect']['preview']:self.assertIn(f'{sample["change_pct"]*100:+.2f}%',out['text'])
    async def test_review_matches_realized_trade_profit_and_error_does_not_consume(self):
        await self.req('trade','buy',{'code':'600003','quantity':100});await self.r.db.unlock_all_sellable();self.r.matcher.reset_liquidity()
        await self.req('trade','sell',{'code':'600003','quantity':100})
        await self.req('play','buy_prop',{'prop_id':'review_card','quantity':2})
        out=await self.req('play','use_prop',{'prop_id':'review_card'})
        self.assertEqual(out['data']['effect']['trades_count'],2)
        self.assertAlmostEqual(out['data']['effect']['total_pnl'],sum(t['profit'] for t in await self.r.db.get_user_trades(self.actor['senderId'])))
        before=await self.r.props.get_user_props(self.actor['senderId'])
        with patch.object(self.r.db,'get_user_trades',side_effect=RuntimeError('unavailable')):
            with self.assertRaisesRegex(ValueError,'未消耗'):await self.req('play','use_prop',{'prop_id':'review_card'})
        self.assertEqual(before,await self.r.props.get_user_props(self.actor['senderId']))
    async def test_health_hides_transport_fields_and_raw_error(self):
        self.r.health['last_error']='/private/fixture/secret traceback'
        health=await self.req('admin','health');self.assertIn('检测到运行错误',health['text']);self.assertNotIn('/private/fixture/',health['text'])
    async def test_unknown_projection_never_serializes_data(self):
        with self.assertRaises(ValueError):play_text('missing',{'secret':'do-not-display'})
        achievements=(await self.req('play','achievements'))['data']['achievements']
        named={i['id']:i['name'] for i in achievements}
        self.assertEqual(named['ten_trades'],'十笔成交');self.assertEqual(named['hundred_trades'],'百笔成交')
