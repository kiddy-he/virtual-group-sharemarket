"""Recorded OHLC, live-day candles, frozen replay and legacy snapshot compatibility."""
import unittest
from pathlib import Path
from PIL import Image
from astrbot_plugin_sharemarket.tests import test_market as fixtures
from astrbot_plugin_sharemarket.render.overview import render_overview, dimensions


class CandleOverviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.MarketTests.asyncSetUp
    asyncTearDown=fixtures.MarketTests.asyncTearDown
    request=fixtures.MarketTests.request

    async def test_daily_ohlc_live_candle_and_frozen_render(self):
        code='600003'
        await self.r.db.insert_candles([(code,'1d',1,10,13,9,12,100),
                                      (code,'1d',2,12,14,8,10,300),
                                      (code,'1m',3,99,99,99,99,1)])
        q=self.r.engine.get(code);q.open=10;q.high=15;q.low=9;q.price=14
        result=await self.request('query',{'action':'overview','code':code},opid='candles')
        snap=result['render']['snapshot'];row=snap['stocks'][0]
        self.assertEqual(row['history'],[{'ts':1,'open':10,'high':13,'low':9,'close':12},
                                         {'ts':2,'open':12,'high':14,'low':8,'close':10}])
        self.assertEqual(row['current_candle'],{'open':10,'high':15,'low':9,'close':14})
        self.assertIn('未收盘K线',result['text'])
        # Price changes after the query must not change its historical or live OHLC.
        q.high=20;q.low=5;q.price=6
        replay=await self.request('query',{'action':'overview','code':code},opid='candles')
        self.assertEqual(replay['render']['snapshot'],snap)
        rendered=await self.r.render(replay)
        with Image.open(rendered['artifact']) as image:
            self.assertEqual(image.size,dimensions(snap))
            # Plot contains both rising and falling bodies, not a connecting line.
            colors=set(image.crop((636,636,1526,768)).getdata())
            self.assertIn((216,75,106),colors);self.assertIn((24,129,111),colors)
            self.assertIn((184,139,57),colors)  # current-day gold outline
        fresh=await self.request('query',{'action':'overview','code':code})
        self.assertEqual(fresh['render']['snapshot']['stocks'][0]['current_candle']['close'],6)
        Path(rendered['artifact']).unlink();await self.r.close();await self.r.start(False)
        recovered=await self.r.render(replay)
        self.assertEqual(recovered['render']['snapshot'],snap)
        self.assertTrue(Path(recovered['artifact']).is_file())

    async def test_live_only_and_unquoted_rows_do_not_fabricate_daily_history(self):
        result=await self.request('query',{'action':'overview','code':'600003'})
        row=result['render']['snapshot']['stocks'][0]
        self.assertEqual(row['history'],[]);self.assertIsNotNone(row['current_candle'])
        self.assertEqual(row['history_pct'],{'1':None,'5':None,'20':None})
        rendered=await self.r.render(result);self.assertTrue(Path(rendered['artifact']).is_file())
        self.r.engine.quotes.pop('600003')
        empty=await self.request('query',{'action':'overview','code':'600003'})
        self.assertIsNone(empty['render']['snapshot']['stocks'][0]['current_candle'])
        self.assertTrue(Path((await self.r.render(empty))['artifact']).is_file())

    async def test_old_close_only_snapshots_still_render_without_reading_current_state(self):
        result=await self.request('query',{'action':'overview','code':'600003'})
        snap=result['render']['snapshot'];snap.pop('scope')
        row=snap['stocks'][0];row.pop('current_candle');row['history']=[{'ts':1,'close':10},{'ts':2,'close':11}]
        target=Path(self.tmp.name)/'old-snapshot.png'
        render_overview(target,snap)
        with Image.open(target) as image:image.verify()
