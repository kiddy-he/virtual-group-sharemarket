"""Scoped overview/news: exact public relevance, LIMIT ordering and durable replay."""
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from astrbot_plugin_sharemarket.tests import test_market as legacy, test_causal as causal
from astrbot_plugin_sharemarket.market.query_scope import resolve_scope, public_catalogue, QueryScopeError
from astrbot_plugin_sharemarket.market.stocks import STOCK_POOL
from astrbot_plugin_sharemarket.render.overview import dimensions, fallback_text


class ScopeTests(unittest.TestCase):
    def test_catalogue_sector_industry_code_name_and_short_code(self):
        for params, predicate in [
            ({'sector':'金融'}, lambda s:s.sector=='金融'),
            ({'industry':'银行'}, lambda s:s.industry=='银行'),
            ({'keyword':'银行'}, lambda s:s.industry=='银行'),
            ({'code':'600003'}, lambda s:s.code=='600003'),
            ({'code':'东方银行'}, lambda s:s.code=='600003'),
            ({'code':STOCK_POOL['600003'].short_code.lower()},lambda s:s.code=='600003'),
        ]:
            with self.subTest(params=params):
                scope=resolve_scope(params)
                self.assertTrue(scope['filtered'])
                self.assertEqual(set(scope['codes']),{s.code for s in STOCK_POOL.values() if predicate(s)})
        self.assertGreater(len(resolve_scope({'sector':'金融'})['codes']),len(resolve_scope({'industry':'银行'})['codes']))
        self.assertFalse(resolve_scope({})['filtered'])
        self.assertEqual(len(resolve_scope({})['codes']),len(STOCK_POOL))

    def test_unknown_ambiguous_and_conflicting_filters_never_broaden(self):
        for params in [{'industry':'不存在'}, {'code':'银行'}, {'keyword':'东方'},
                       {'keyword':''}, {'sector':''}, {'code':'600003','industry':'证券'},
                       {'code':'600003','keyword':'000001'}, {'sector':'科技','industry':'银行'},
                       {'keyword':"' OR 1=1 --"}]:
            with self.subTest(params=params), self.assertRaises(ValueError):resolve_scope(params)

    def test_public_catalogue_contains_only_current_identifiers(self):
        result = public_catalogue()
        self.assertEqual(result['version'], 1)
        self.assertEqual(len(result['stocks']), len(STOCK_POOL))
        self.assertEqual({row['code'] for row in result['stocks']}, set(STOCK_POOL))
        for row in result['stocks']:
            self.assertEqual(set(row), {'code','short_code','name','sector','industry'})

    def test_public_scope_errors_are_typed_and_keep_the_specific_cause(self):
        for params, code in [({'code':'航天科技'},'market_scope_not_found'),
                             ({'keyword':'东方'},'market_scope_ambiguous'),
                             ({'sector':'科技','industry':'银行'},'market_scope_conflict')]:
            with self.subTest(params=params), self.assertRaises(QueryScopeError) as captured:
                resolve_scope(params)
            self.assertEqual(captured.exception.public_error['code'], code)
            self.assertEqual(captured.exception.public_error['message'], str(captured.exception))


class ScopedLegacyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=legacy.MarketTests.asyncSetUp
    asyncTearDown=legacy.MarketTests.asyncTearDown
    request=legacy.MarketTests.request

    async def test_catalogue_rpc_is_public_read_only_and_creates_no_business_operations(self):
        before = await (await self.r.db.conn.execute('SELECT COUNT(*) FROM business_operations')).fetchone()
        result = await self.r.execute({'method':'catalogue'})
        after = await (await self.r.db.conn.execute('SELECT COUNT(*) FROM business_operations')).fetchone()
        self.assertTrue(result['ok'])
        self.assertEqual(result['market_id'], self.r.market_id)
        self.assertEqual(before[0], after[0])
        self.assertEqual(set(result), {'ok','market_id','version','stocks'})
        self.assertEqual(set(result['stocks'][0]), {'code','short_code','name','sector','industry'})

    async def test_scoped_overview_statistics_png_replay_and_fallback(self):
        q=self.r.engine.get('600003');q.prev_close=10;q.price=11
        params={'action':'overview','code':'东方银行'}
        result=await self.request('query',params,opid='scoped-snapshot')
        snap=result['render']['snapshot']
        self.assertEqual([r['code'] for r in snap['stocks']],['600003'])
        self.assertAlmostEqual(snap['market_change'],10)
        self.assertEqual((snap['advancers'],snap['flat'],snap['decliners']),(1,0,0))
        self.assertIn('东方银行',result['text']);self.assertNotIn('大盘',result['text'])
        self.assertIn('东方银行',fallback_text(snap));self.assertNotIn('平安发展',fallback_text(snap))
        q.price=5
        replay=await self.request('query',params,opid='scoped-snapshot')
        self.assertEqual(replay['render']['snapshot'],snap)
        rendered=await self.r.render(replay)
        with Image.open(rendered['artifact']) as image:
            self.assertEqual(image.size,dimensions(snap));image.verify()
        Path(rendered['artifact']).unlink()
        await self.r.close();await self.r.start(False)
        replay=await self.request('query',params,opid='scoped-snapshot')
        self.assertEqual(replay['render']['snapshot'],snap)
        with patch('astrbot_plugin_sharemarket.render.overview.render_overview',side_effect=RuntimeError('injected')):
            rendered=await self.r.render(replay)
        self.assertIn('东方银行',rendered['text']);self.assertNotIn('平安发展',rendered['text'])

    async def test_industry_statistics_use_only_selected_quotes_and_no_quote_is_not_flat(self):
        scope=resolve_scope({'industry':'银行'})
        for code in scope['codes']:
            q=self.r.engine.get(code);q.prev_close=10;q.price=11
        self.r.engine.quotes.pop(scope['codes'][0])
        # An unrelated stock must not affect the selected average/counts.
        self.r.engine.get('300003').price=0
        result=await self.request('query',{'action':'overview','industry':'银行'})
        snap=result['render']['snapshot']
        self.assertEqual({r['industry'] for r in snap['stocks']},{'银行'})
        self.assertAlmostEqual(snap['market_change'],10)
        self.assertEqual(snap['advancers'],len(scope['codes'])-1)
        self.assertEqual(snap['unquoted_count'],1)
        self.assertEqual(snap['flat'],0)
        single=await self.request('query',{'action':'overview','code':scope['codes'][0]})
        self.assertIsNone(single['data']['market_change'])
        self.assertIn('暂无报价',single['text'])
        await self.r.render(single)  # no-quote summary is renderable, not a zero return

    async def test_legacy_news_filters_before_limit_and_keeps_sector_relevance(self):
        now=int(time.time())
        for scope,target,headline in [('stock','600003','银行个股旧闻'),('sector','金融','金融板块旧闻')]+[
            ('stock','300002','无关医药')]*35+[('market','','全市场宏观')]:
            await self.r.db.insert_news(now,scope,target,'test',headline,0)
        result=await self.request('query',{'action':'news','code':'600003','limit':2})
        self.assertEqual([r['headline'] for r in result['data']],['金融板块旧闻','银行个股旧闻'])
        self.assertIn('东方银行',result['text'])
        empty=await self.request('query',{'action':'news','industry':'白酒'})
        self.assertEqual(empty['data'],[]);self.assertIn('暂无该范围',empty['text'])
        global_news=await self.request('query',{'action':'news','limit':1})
        self.assertEqual(global_news['data'][0]['headline'],'全市场宏观')


class ScopedCausalTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=causal.RuntimeTests.asyncSetUp
    asyncTearDown=causal.RuntimeTests.asyncTearDown
    req=causal.RuntimeTests.req

    async def test_news_exact_public_targets_filter_before_limit_no_private_leak(self):
        await self.r.db.conn.execute('DELETE FROM causal_news')
        items=[(['600003'],'个股旧闻'),(['600003','300003'],'联合公告'),
               (['000001'],'另一家银行')]+[(['300002'],'无关医药')]*35+[
               (['6000030'],'代码前缀不能误匹配'),([], '全市场宏观无目标')]
        for seq,(targets,headline) in enumerate(items,1):
            row={'seq':seq,'stage':'confirmed','headline':headline,'targets':targets,'scope':'market' if len(targets)!=1 else 'stock'}
            await self.r.db.conn.execute('INSERT INTO causal_news(seq,published,payload) VALUES(?,?,?)',
                                         (seq,int(time.time()),json.dumps(row)))
        await self.r.db.conn.commit()
        result=await self.req('query',{'action':'news','code':'600003','limit':2})
        self.assertEqual([r['headline'] for r in result['data']],['联合公告','个股旧闻'])
        industry=await self.req('query',{'action':'news','industry':'银行','limit':3})
        self.assertEqual([r['headline'] for r in industry['data']],['另一家银行','联合公告','个股旧闻'])
        sector=await self.req('query',{'action':'news','sector':'金融','limit':1})
        self.assertEqual(sector['data'][0]['headline'],'另一家银行')
        all_news=await self.req('query',{'action':'news','limit':1})
        self.assertEqual(all_news['data'][0]['headline'],'全市场宏观无目标')
        empty=await self.req('query',{'action':'news','code':'600004'})
        self.assertEqual(empty['data'],[])
        self.assertNotIn('future',json.dumps(result))
        # Selection is based solely on public target arrays, not hidden event outcomes.
        self.assertEqual(set(result['scope']['codes']),{'600003'})

    async def test_daytime_ticks_change_prices_before_any_daily_settlement(self):
        from astrbot_plugin_sharemarket.config import CFG
        CFG.market_mode='247';self.r.clock.mode='247'
        day=self.r.dayclose._day_seq
        before={code:q.price for code,q in self.r.engine.quotes.items()}
        start=self.r.clock.started
        for tick in range(12):await self.r.tick(start+1+tick*3)
        self.assertEqual(self.r.dayclose._day_seq,day)
        self.assertEqual(await self.r.db.overview_candles(),{})
        changed=[c for c,p in before.items() if self.r.engine.get(c).price!=p]
        self.assertTrue(changed,'intra-day ticks must update at least one simulated quote')
        result=await self.req('query',{'action':'overview','code':changed[0]})
        live=result['render']['snapshot']['stocks'][0]['current_candle']
        q=self.r.engine.get(changed[0])
        self.assertEqual(live,{'open':q.open,'high':q.high,'low':q.low,'close':q.price})
