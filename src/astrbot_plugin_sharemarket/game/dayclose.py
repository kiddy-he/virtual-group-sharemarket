"""Atomic, idempotent settlement identified by a durable trading-day token."""
import time
from .atomic import atomic
from ..config import CFG
from ..log import get_logger
log=get_logger('dayclose')

class DayCloseService:
    def __init__(self,db,engine,matcher,auction=None,corporate=None,news=None,margin=None,ipo=None):
        self.db,self.engine,self.matcher=db,engine,matcher
        self.auction,self.corporate,self.news,self.margin,self.ipo=auction,corporate,news,margin,ipo
        self._day_seq=0
        db.memory_objects.append((self,('_day_seq',)))

    @atomic
    async def run(self,leaderboard=None,price_of=None,token=None):
        current=int(await self.db.get_meta('trading_day_seq') or 0)
        token=str(token or f'virtual:{current+1}')
        existing=await (await self.db.conn.execute('SELECT state FROM settlements WHERE token=?',(token,))).fetchone()
        if existing and existing['state']=='complete':return 0
        self._day_seq=current+1
        day=self._day_seq
        await self.db.conn.execute("INSERT INTO settlements VALUES(?,?,'running',?)",(day,token,int(time.time())))
        if self.auction and self.auction.has_orders():await self.auction.run('收盘集合竞价')
        # Expire all live orders before corporate actions change quantities/prices.
        rows=await self.db.get_all_open_orders()
        trade=self.auction.trade if self.auction else getattr(self.margin,'trade',None)
        for row in rows:
            if trade:
                await trade._cancel_order_row(row)
            else:
                self.matcher.cancel(row['code'],row['order_id'])
                if row['side']=='buy' and row['frozen']:
                    acc=await self.db.get_account(row['user_id'])
                    await self.db.update_cash_full(row['user_id'],acc['cash_available']+row['frozen'],acc['cash_withdrawable']+row['settled_frozen']/100,acc['cash_frozen']-row['frozen'])
                    await self.db.update_order_frozen(row['order_id'],0)
        await self.db.expire_open_orders()
        if self.corporate:await self.corporate.run_day()
        if self.margin:
            await self.margin._accrue_day_nolock(day)
            await self.margin._check_margin_calls_nolock()
        await self.db.unlock_all_sellable()
        # Database and memory are within the same undo/checkpoint boundary.
        candles=self.engine.day_close()
        await self.db.insert_candles(candles)
        await self.db.upsert_prices(self.engine.snapshot_rows())
        if self.ipo:
            await self.ipo._on_day_start_nolock(day)
            ledger=await self.ipo._load()
            now=time.time()
            for ipo in list(ledger['ipos'].values()):
                if ipo['status']=='drawing' or (ipo['status']=='open' and (day>=ipo['close_day'] if 'close_day' in ipo else now>=ipo.get('close_ts',ipo['ts']+CFG.day_seconds))):
                    await self.ipo.draw(ipo['code'])
        await self.db.settle_withdrawable()
        if self.news:
            if hasattr(self.engine,'causal'):await self.news.maybe_generate()
            self.news.reset_day()
        if leaderboard and price_of:await leaderboard.snapshot_day(day,price_of)
        now=int(time.time())
        await self.db.set_meta('trading_day_seq',str(day))
        await self.db.set_meta('last_day_close',str(now))
        await self.db.conn.execute("UPDATE settlements SET state='complete' WHERE day_id=?",(day,))
        log.info('日终清算完成 day=%d token=%s expired=%d',day,token,len(rows))
        return len(rows)
