"""Overview correctness, snapshot recovery and full PNG acceptance."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from astrbot_plugin_sharemarket.tests import test_market as fixtures
from astrbot_plugin_sharemarket.market import stocks
from astrbot_plugin_sharemarket.render.overview import dimensions

# Reuse the isolated market fixture without inheriting its test methods.
import unittest
class OverviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.MarketTests.asyncSetUp
    asyncTearDown = fixtures.MarketTests.asyncTearDown
    request = fixtures.MarketTests.request

    async def test_complete_snapshot_history_formula_and_dynamic_listing(self):
        code='600003'
        rows=[(code,'1d',i+1,100+i,100+i,100+i,100+i,0) for i in range(21)]
        # Another period must not contaminate daily history.
        rows.append((code,'1m',999,999,999,999,999,0))
        await self.r.db.insert_candles(rows)
        q=self.r.engine.get(code);q.price=126;q.prev_close=120
        self.r.engine.suspended[code]=10
        new=stocks.Stock('999999','测试新增股',stocks.BOARD_MAIN,stocks.SEC_TECH,'测试',10,.01,1)
        stocks.STOCK_POOL[new.code]=new
        result=await self.request('query',{'action':'overview','limit':1},opid='overview')
        snapshot=result['render']['snapshot'];self.assertEqual(len(snapshot['stocks']),len(stocks.STOCK_POOL))
        row=next(r for r in snapshot['stocks'] if r['code']==code)
        self.assertAlmostEqual(row['change_pct'],5)
        for n in (1,5,20):self.assertAlmostEqual(row['history_pct'][str(n)],(120/(120-n)-1)*100)
        self.assertIn('停牌',row['states']);self.assertEqual(len(row['history']),21)
        new_row=next(r for r in snapshot['stocks'] if r['code']==new.code)
        self.assertEqual(new_row['history_pct'],{'1':None,'5':None,'20':None})
        self.assertIsNone(new_row['price'])
        # Delisting does not silently drop the row.
        self.r.engine.delisted.add(code)
        changed=await self.request('query',{'action':'overview'})
        self.assertIn('退市',next(r for r in changed['render']['snapshot']['stocks'] if r['code']==code)['states'])
        q.price=90;await self.r.db.insert_candles([(code,'1d',1000,90,90,90,90,0)])
        replay=await self.request('query',{'action':'overview','limit':1},opid='overview')
        self.assertEqual(snapshot,replay['render']['snapshot'])
        self.assertLess(len(json.dumps(result).encode()),1024*1024)
        # Render after quote/history changes: descriptor remains frozen.
        rendered=await self.r.render(result)
        self.assertEqual(snapshot,rendered['render']['snapshot'])
        self.assertLess(Path(rendered['artifact']).stat().st_size,25*1024*1024)
        with Image.open(rendered['artifact']) as image:
            self.assertEqual(image.size,dimensions(__import__('astrbot_plugin_sharemarket.render.overview',fromlist=['partition_overview']).partition_overview(snapshot)[0]));image.verify()
        pages=rendered['artifacts']
        self.assertEqual(len(pages),len({r['sector'] for r in snapshot['stocks']}))
        for page in pages:self.assertTrue(Path(page).is_file())
        self.r.health['ticks']+=5
        self.assertEqual(rendered['artifact'],(await self.r.render(result))['artifact'])
        # Lost artifact is regenerated from the operation snapshot, including after restart.
        Path(rendered['artifact']).unlink();await self.r.close();await self.r.start(False)
        recovered=await self.r.render(replay)
        self.assertTrue(Path(recovered['artifact']).is_file())
        self.assertEqual(recovered['render']['snapshot'],snapshot)

    async def test_incomplete_history_does_not_fabricate_returns(self):
        code='600003'
        await self.r.db.insert_candles([(code,'1d',i+1,10,10,10,10+i,0) for i in range(5)])
        result=await self.request('query',{'action':'overview'})
        row=next(r for r in result['render']['snapshot']['stocks'] if r['code']==code)
        self.assertIsNotNone(row['history_pct']['1'])
        self.assertIsNone(row['history_pct']['5']);self.assertIsNone(row['history_pct']['20'])

    async def test_renderer_failure_returns_every_stock_and_retry_succeeds(self):
        result=await self.request('query',{'action':'overview'})
        with patch('astrbot_plugin_sharemarket.render.overview.render_overview',side_effect=OSError('disk/font unavailable')):
            fallback=await self.r.render(result)
        self.assertIn('render_error',fallback)
        for code in stocks.STOCK_POOL:self.assertIn(code,fallback['text'])
        self.assertNotIn('artifact',fallback)
        # Retry uses original descriptor, and no trade/price operation is invoked.
        with patch.object(self.r.engine,'get',side_effect=AssertionError('must not read live quotes')):
            retry=await self.r.render(result)
        self.assertTrue(Path(retry['artifact']).is_file())

    async def test_overview_broadcast_uses_same_long_image(self):
        service={'accountId':'default','scope':'group','identity':'service','groupId':'700000099','serviceJobId':'test-job'}
        result=await self.request('broadcast',{'action':'overview'},service)
        self.assertEqual(result['render']['kind'],'overview')
        a,b=await asyncio.gather(self.r.render(result),self.r.render(result))
        self.assertEqual(a['artifact'],b['artifact'])

    async def test_recovery_list_stays_bounded_with_many_full_history_snapshots(self):
        await self.r.db.insert_candles([(code,'1d',i+1,10,10,10,10+i,0) for code in stocks.STOCK_POOL for i in range(21)])
        for i in range(8):await self.request('query',{'action':'overview'},opid=f'long-{i}')
        pending=await self.r.execute({'method':'outbox','actor':self.actor})
        self.assertLess(len(json.dumps(pending).encode()),65536)
        self.assertEqual(len([r for r in pending['items'] if r['id'].startswith('long-')]),8)
        for row in pending['items']:self.assertNotIn('result',json.loads(row['payload']))
        result=await self.r.execute({'method':'result','actor':self.actor,'id':'long-0'})
        self.assertEqual(len(result['render']['snapshot']['stocks']),len(stocks.STOCK_POOL))

    async def test_negative_and_zero_baselines(self):
        from astrbot_plugin_sharemarket.render.overview import pct
        self.assertAlmostEqual(pct(80,100),-20)
        self.assertEqual(pct(100,100),0)
        self.assertIsNone(pct(100,0));self.assertIsNone(pct(None,100))

    async def test_analysis_public_snapshot_does_not_trade_or_expose_private_state(self):
        before=await (await self.r.db.conn.execute('SELECT COUNT(*) FROM trades')).fetchone()
        result=await self.request('query',{'action':'analyze','question':'推荐最近涨得快的科技股','sector':'科技'})
        self.assertTrue(result['analysis']);self.assertNotIn('render',result)
        self.assertTrue(all(row['sector']=='科技' for row in result['data']['snapshot']['stocks']))
        self.assertTrue(all('volume' in row for row in result['data']['snapshot']['stocks']))
        self.assertNotIn('truth',result['data']);self.assertNotIn('accounts',result['data'])
        after=await (await self.r.db.conn.execute('SELECT COUNT(*) FROM trades')).fetchone()
        self.assertEqual(before[0],after[0])

    async def test_missing_last_sector_image_regenerates_complete_set(self):
        result=await self.request('query',{'action':'overview'},opid='multi-page-loss')
        first=await self.r.render(result);self.assertGreater(len(first['artifacts']),1)
        Path(first['artifacts'][-1]).unlink()
        again=await self.r.render(result)
        self.assertEqual(len(again['artifacts']),len(first['artifacts']))
        self.assertTrue(all(Path(p).is_file() for p in again['artifacts']))
