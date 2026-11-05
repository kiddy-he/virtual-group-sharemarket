"""Framework-independent persistent virtual market. One process per market.

Transport is a mode-0600 Unix socket. Only the trusted Bot adapter selects the
market, actor and destination; LLM tool parameters never contain identity IDs.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from .config import CFG,validate_config
from .storage.db import Database
from .storage.money import money,positive_int,cents
from .game.atomic import mutation
from .locks import trade_lock
from .game.recovery import Recovery
from .market import calendar
from .market.engine import PriceEngine
from .market.orderbook import Matcher
from .market.stocks import STOCK_POOL,Stock

def public_market_text(value):
    """Preserve simulation labels when presenting public fictional events."""
    return str(value)

from .market.query_scope import QueryScopeError,public_catalogue
from .game.trade import TradeService
from .game.auction import AuctionService
from .game.account import AccountService
from .game.ipo import IPOService
from .game.margin import MarginService
from .game.corporate import CorporateService
from .game.dayclose import DayCloseService
from .game.leaderboard import LeaderboardService
from .game.valuation import ValuationService
from .game.quest import QuestService
from .game.props import PropService
from .game.season import SeasonService
from .game.watchlist import WatchlistService
from .game.achieve import AchievementService
from .game.npc import NpcService
from .events.news import NewsService
log=logging.getLogger('sharemarket.runtime')

from .game.presentation import RETIRED_ACTIONS, play_text, health_text

class MarketRuntime:
    def __init__(self,state_dir,market_id='shared',options=None):
        self.path=Path(state_dir).resolve();self.market_id=market_id;self.options=options or {}
        self.options.setdefault('features',{'ipo':True,'margin':True,'props':True,'season':False,'quests':True})
        features=self.options['features']
        if not isinstance(features,dict) or set(features)-{'ipo','margin','props','season','quests'} or any(type(v) is not bool for v in features.values()):raise ValueError('invalid gameplay options')
        if type(self.options.get('npcTrading',True)) is not bool:raise ValueError('npcTrading must be boolean')
        for key,default,low,high in [('retentionDays',90,7,3650),('artifactRetentionHours',24,1,8760)]:
            value=self.options.get(key,default)
            if type(value) is not int or not low<=value<=high:raise ValueError(f'invalid {key}')
        for name,value in self.options.get('rules',{}).items():
            if not hasattr(CFG,name):raise ValueError(f'unknown market setting {name}')
            setattr(CFG,name,value)
        validate_config()
        database_name=self.options.get('databaseName','market.sqlite')
        if not isinstance(database_name,str) or Path(database_name).name!=database_name or database_name in ('','.','..'):
            raise ValueError('databaseName must be a local filename')
        self.db=Database(str(self.path/database_name))
        version=self.options.get('modelVersion','legacy')
        if version not in ('legacy','causal-v2'):raise ValueError('unsupported market model')
        if version=='causal-v2':
            from .market.causal_engine import CausalPriceEngine
            import secrets
            model_seed=self.options.get('modelSeed',secrets.randbits(64))
            if type(model_seed) is not int or not 0<=model_seed<2**64:raise ValueError('invalid modelSeed')
            self.engine=CausalPriceEngine(seed=model_seed)
        else:self.engine=PriceEngine()
        self.engine.paused=CFG.market_paused
        self.matcher=Matcher();self.trade=TradeService(self.db,self.engine,self.matcher)
        self.auction=AuctionService(self.db,self.engine,self.trade);self.trade.auction=self.auction
        self.ipo=IPOService(self.db,self.engine);self.margin=MarginService(self.db,self.engine,self.trade)
        self.accounts=AccountService(self.db,margin=self.margin,ipo=self.ipo,trade=self.trade)
        self.news=NewsService(self.db,self.engine);self.corporate=CorporateService(self.db,self.engine,self.news)
        self.board=LeaderboardService(self.db)
        self.quest=QuestService(self.db);self.props=PropService(self.db);self.season=SeasonService(self.db)
        self.watchlist=WatchlistService(self.db);self.achieve=AchievementService(self.db)
        self.npc=NpcService(self.db,self.engine,self.trade)
        self.dayclose=DayCloseService(self.db,self.engine,self.matcher,self.auction,self.corporate,self.news,self.margin,self.ipo)
        calendar.SESSION=calendar.SessionClock(CFG.market_mode)
        self.clock=calendar.SESSION
        self.recovery=Recovery(self.db,self.engine,self.matcher,self.auction,self.corporate,self.news,self.clock)
        self._phase=None;self._task=None;self._started=False;self._stopping=False;self._render_semaphore=asyncio.Semaphore(2)
        self.health={'ticks':0,'last_tick':None,'last_error':None,'settlement_failures':0,'queue_depth':0,'reconciled':False}
        self._rate={};self._render_cache={};self._render_locks={}
        crowd=self.npc._ensure_crowd()
        self.db.memory_objects.append((self.npc,('_crowd','_crowd_rng','_rng','_decisions')))
        self.recovery.objects['npc']=(self.npc,('_crowd','_crowd_rng','_rng','_decisions'))
        self.db.memory_objects.append((self,('_rate',)))
        calendar.configure(self.options.get('calendar',{}))
    async def start(self,background=True):
        if self._started:return
        self._stopping=False
        self.path.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            await self.db.open()
            await self.db.conn.execute('CREATE TABLE IF NOT EXISTS causal_news(seq INTEGER PRIMARY KEY, published INTEGER NOT NULL, payload TEXT NOT NULL)')
            await self.db.conn.execute("CREATE INDEX IF NOT EXISTS idx_causal_news_event ON causal_news(json_extract(payload,'$.event_id'),seq)")
            await self.props.ensure_schema();await self.quest.ensure_schema();await self.season.ensure_schema()
            await self.ipo.restore()
            restored=await self.recovery.restore()
            self.engine._tick_seconds=CFG.tick_seconds;self.engine._day_seconds=CFG.day_seconds;self.clock.mode=CFG.market_mode
            if not restored:
                self.engine.load_rows(await self.db.get_all_prices())
                if hasattr(self.engine,'causal'):self.engine.migrate_legacy()
                last=await self.db.get_meta('last_day_close')
                if last:self.clock.started=float(last)
            if hasattr(self.engine,'causal'):
                from .market.event_world import ensure_event_schema
                from .market.causal_state import VERSION
                ensure_event_schema(self.engine.causal);self.engine.model_version=VERSION
            if hasattr(self.engine,'causal') and not self.engine.causal.get('opening_reconciled'):
                # Existing player/NPC shares are part of issued capital, not an
                # extra issuance on top of the newly initialised venue.
                state=self.engine.causal
                rows=await (await self.db.conn.execute('SELECT code,SUM(quantity) quantity FROM positions GROUP BY code')).fetchall()
                for row in rows:
                    if row['code'] not in state['profile']['codes']:continue
                    i=state['profile']['codes'].index(row['code']);qty=int(row['quantity'])
                    if qty>state['locked_inventory'][i]:raise ValueError('legacy holdings exceed allocatable opening shares')
                    state['locked_inventory'][i]-=qty
                loans=await self.margin._load()
                for loan in self.margin._open_loans(loans):
                    if loan['kind']=='cash':state['lender_cash']-=cents(loan['principal'])
                    elif loan['code'] in state['profile']['codes']:
                        i=state['profile']['codes'].index(loan['code']);qty=loan['quantity']
                        if qty>state['lending_inventory'][i]:raise ValueError('legacy short claims exceed lending pool')
                        state['lending_inventory'][i]-=qty;state['house_inventory'][i]+=qty;state['short_outstanding'][i]+=qty
                if state['lender_cash']<0:raise ValueError('legacy credit claims exceed opening capital')
                state['opening_reconciled']=True
            self.dayclose._day_seq=int(await self.db.get_meta('trading_day_seq') or 0)
            self.matcher.books.clear();self.auction.books.clear()
            for row in sorted(await self.db.get_all_open_orders(),key=lambda r:(r['ts'],r['order_id'])):
                if row['code'] not in STOCK_POOL:raise ValueError('open order refers to missing stock')
                remaining=row['quantity']-row['filled']
                if row['phase'] in ('auction_open','auction_close'):
                    self.auction.book(row['code']).add(row['order_id'],row['user_id'],row['side'],row['price'],remaining)
                else:self.matcher.restore(row['order_id'],row['user_id'],row['code'],row['side'],row['price'],remaining)
            self._phase=await self.db.get_meta('session_phase')
            async with mutation(self.db):
                if 'market_paused' in self.options.get('rules',{}):self.engine.paused=CFG.market_paused
                await self.db.set_meta('notice',CFG.notice)
                if self.options['features'].get('season') and 'season' not in RETIRED_ACTIONS:await self.season.ensure_current()
                await self.npc.ensure_accounts()
                audit=await self.db.audit(strict_reserves=True)
                if not audit['ok']:raise ValueError('market reconciliation failed: '+json.dumps(audit['errors']))
            self.health['reconciled']=True
            self._started=True
            if background:self._task=asyncio.create_task(self._loop(),name=f'market:{self.market_id}')
        except BaseException:
            self.health['reconciled']=False
            self._started=False
            await self.db.close()
            raise
    async def close(self):
        self._stopping=True
        if self._task:
            self._task.cancel()
            try:await self._task
            except asyncio.CancelledError:pass
            self._task=None
        if self.db.conn:await self.db.close()
        self._started=False
    async def _loop(self):
        deadline=time.monotonic()
        while not self._stopping:
            deadline+=CFG.tick_seconds
            try:await self.tick()
            except asyncio.CancelledError:raise
            except Exception:
                self.health['last_error']='tick_failed';log.exception('market tick failed; transaction rolled back')
            if self._stopping:return
            await asyncio.sleep(max(0.05,deadline-time.monotonic()))
            if time.monotonic()-deadline>CFG.tick_seconds:deadline=time.monotonic()
    async def tick(self,now=None):
        now=time.time() if now is None else now
        dt=datetime.fromtimestamp(now,calendar.TZ)
        due=(now-self.clock.started>=CFG.day_seconds) if CFG.market_mode=='247' else (calendar.is_trading_day(dt) and dt.hour>=15)
        token=f'virtual:{int(await self.db.get_meta("trading_day_seq") or 0)+1}' if CFG.market_mode=='247' else f'realtime:{dt.date().isoformat()}'
        complete=await (await self.db.conn.execute("SELECT 1 FROM settlements WHERE token=? AND state='complete'",(token,))).fetchone()
        if due and not complete:
            try:
                async with mutation(self.db):
                    await self.dayclose.run(self.board,self.price_of,token)
                    self.clock.reset(now)
                    self.npc._crowd['net']=0;self.npc._crowd['turnover']=0
                    await self.db.set_meta('session_phase','')
                self._phase=None
            except BaseException:
                self.health['settlement_failures']+=1
                raise
        async with mutation(self.db):
            phase=self.clock.phase(now)
            previous=await self.db.get_meta('session_phase')
            if previous=='auction_open' and phase!='auction_open':await self.auction.run('开盘集合竞价')
            # After a restart, DB order phases still identify overdue opening orders.
            elif phase!='auction_open' and any(r['phase']=='auction_open' for r in await self.db.get_all_open_orders()):await self.auction.run('恢复开盘集合竞价')
            await self.db.set_meta('session_phase',phase)
            if not self.engine.paused and phase!='closed':
                pressures={code:self.matcher.take_pressure(code) for code in STOCK_POOL}
                if not hasattr(self.engine,'causal'):
                    for code,qty in self.npc.crowd_tick().items():pressures[code]=pressures.get(code,0)+qty
                self.engine.tick(pressures);self.matcher.reset_liquidity()
                await self.db.upsert_prices(self.engine.snapshot_rows())
                await self.news.maybe_generate()
                # Intraday risk checks use the same transaction as the new quotes.
                if self.options['features'].get('margin'):await self.margin._check_margin_calls_nolock()
            if hasattr(self.engine,'causal'):await self.news.maybe_generate()
            if 'season' not in RETIRED_ACTIONS and self.options['features'].get('season'):await self.season.reset_season()
        if self.options.get('npcTrading',True) and phase=='continuous' and not self.engine.paused:
            async with mutation(self.db):orders=await self.npc.tick()
            await self.npc.run_orders(orders)
        self.health['ticks']+=1;self.health['last_tick']=time.time();self.health['last_error']=None
        if hasattr(self.engine,'causal'):
            self.health.update({'model_version':self.engine.model_version,'virtual_day':self.engine.causal['day'],'public_seq':self.engine.causal['public_seq']})
        if self.health['ticks']==1 or self.health['ticks']%max(1,int(3600/CFG.tick_seconds))==0:
            await self.db.maybe_daily_backup();await self.db.retain(self.options.get('retentionDays',90));await self.cleanup_artifacts()
    def price_of(self,code):
        quote=self.engine.get(code)
        return quote.price if quote else None
    def resolve_code(self,value):
        value=str(value or '').strip()
        stock=Stock.lookup(value)
        if not stock:
            matches=[s for s in STOCK_POOL.values() if value and value.casefold() in s.name.casefold()]
            if len(matches)==1:stock=matches[0]
        if not stock:raise ValueError('股票代码或名称不明确，请先搜索个股。')
        return stock.code
    async def execute(self,request):
        if isinstance(request,dict) and request.get('method')=='admin' and (request.get('params') or {}).get('action')=='backup':
            actor=request.get('actor') or {}
            if actor.get('identity')!='admin' or actor.get('scope')!='private':raise ValueError('admin only; private scope required')
            if not request.get('operation_id'):raise ValueError('missing operation identity')
            async with trade_lock():
                old=await (await self.db.conn.execute('SELECT 1 FROM business_operations WHERE id=?',(request['operation_id'],))).fetchone()
                if not old:await self.db.backup()
                return await self._execute(request)
        return await self._execute(request)
    async def _execute(self,request):
        if not isinstance(request,dict):raise ValueError('request must be an object')
        if request.get('method')=='health':return {'ok':True,'market_id':self.market_id,'pid':os.getpid(),'options_hash':self.options_hash if hasattr(self,'options_hash') else None,**self.health,**({'model_version':self.engine.model_version,'virtual_day':self.engine.causal['day'],'public_seq':self.engine.causal['public_seq']} if hasattr(self.engine,'causal') else {})}
        if request.get('method')=='catalogue':
            # Mode-0600 socket: public identifiers only; no account, quotes or hidden simulation state.
            return {'ok':True,'market_id':self.market_id,**public_catalogue()}
        if request.get('method')=='news_feed':
            # Local mode-0600 socket capability: public facts only, no account or private world state.
            after=request.get('after',0);limit=request.get('limit',100)
            if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=200:raise ValueError('invalid news cursor')
            rows=await (await self.db.conn.execute('SELECT seq,published,payload FROM causal_news WHERE seq>? ORDER BY seq LIMIT ?',(after,limit))).fetchall()
            return {'ok':True,'items':[{**json.loads(r['payload']),'published_at':r['published']*1000} for r in rows],'latest_seq':getattr(self.engine,'causal',{}).get('public_seq',0)}
        if request.get('method')=='outbox':
            actor=request.get('actor') or {}
            # List metadata only; large frozen chart snapshots are fetched individually via result.
            rows=await (await self.db.conn.execute("SELECT id,json_remove(payload,'$.result') AS payload,state FROM outbox WHERE state!='accepted' AND json_extract(payload,'$.actor.senderId') IS ? ORDER BY ts",(actor.get('senderId'),))).fetchall()
            return {'ok':True,'items':[dict(r) for r in rows if self._same_actor(json.loads(r['payload']).get('actor',{}),actor)][:50]}
        if request.get('method')=='result':
            actor=request.get('actor') or {}
            row=await (await self.db.conn.execute('SELECT payload FROM outbox WHERE id=?',(request.get('id'),))).fetchone()
            if not row or not self._same_actor(json.loads(row['payload']).get('actor',{}),actor):raise ValueError('delivery actor mismatch')
            return json.loads(row['payload'])['result']
        if request.get('method')=='ack':
            actor=request.get('actor') or {}
            row=await (await self.db.conn.execute('SELECT payload FROM outbox WHERE id=?',(request.get('id'),))).fetchone()
            if not row or not self._same_actor(json.loads(row['payload']).get('actor',{}),actor):raise ValueError('delivery actor mismatch')
            await self.db.conn.execute("UPDATE outbox SET state='accepted',receipt=? WHERE id=?",(json.dumps(request.get('receipt')),request['id']))
            return {'ok':True}
        actor=request.get('actor') or {};uid=str(actor.get('senderId',''))
        broadcast=request.get('method')=='broadcast' and actor.get('serviceJobId') and actor.get('identity')=='service' and actor.get('scope')=='group'
        if not broadcast and (not uid.isdecimal() or not 5<=len(uid)<=20):raise ValueError('missing trusted actor')
        if actor.get('scope') not in ('private','group'):raise ValueError('invalid scope')
        method=request.get('method');params=request.get('params') or {};opid=str(request.get('operation_id',''))
        if not opid or len(opid)>160:raise ValueError('missing operation identity')
        fingerprint_actor={k:actor.get(k) for k in ('senderId','accountId','scope','groupId','serviceJobId')}
        fingerprint=hashlib.sha256(json.dumps({'method':method,'params':params,'actor':fingerprint_actor},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        self.health['queue_depth']+=1
        try:
            async with mutation(self.db):
                old=await (await self.db.conn.execute('SELECT fingerprint,result FROM business_operations WHERE id=?',(opid,))).fetchone()
                if old:
                    if old['fingerprint']!=fingerprint:raise ValueError('operation identity conflict')
                    return json.loads(old['result'])
                if uid and actor.get('groupId'):await self.db.conn.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)',(uid,str(actor['groupId'])))
                # A per-actor rate limit is separate from idempotent replay.
                if method=='trade':
                    previous=self._rate.get(uid,0)
                    if time.monotonic()-previous<CFG.trade_cooldown_seconds:raise ValueError('交易请求过于频繁，请稍候。')
                self.db.operation_id=opid
                try:result=await self._dispatch(method,params,uid,actor)
                finally:self.db.operation_id=None
                if method=='trade':self._rate[uid]=time.monotonic()
                result={'ok':True,'market_id':self.market_id,'operation_id':opid,**result}
                output=json.dumps(result,ensure_ascii=False,allow_nan=False)
                await self.db.conn.execute('INSERT INTO business_operations VALUES(?,?,?,?)',(opid,fingerprint,output,int(time.time())))
                event={'actor':actor,'method':method,'params':params,'result':result}
                await self.db.conn.execute('INSERT INTO outbox(id,operation_id,payload,ts) VALUES(?,?,?,?)',(opid,opid,json.dumps(event,ensure_ascii=False),int(time.time())))
                return result
        finally:self.health['queue_depth']-=1
    @staticmethod
    def _same_actor(left,right):
        return all(str(left.get(k,''))==str(right.get(k,'')) for k in ('senderId','accountId','scope','groupId','serviceJobId'))
    async def _dispatch(self,method,p,uid,actor):
        action=p.get('action')
        if method=='broadcast':
            if actor.get('identity')!='service' or not actor.get('serviceJobId'):raise ValueError('service grant required')
            if action not in ('overview','news','rank'):raise ValueError('public broadcast only')
            if action=='rank':
                entries=await self.board.top(self.price_of,limit=10,group_id=actor.get('groupId'))
                return {'text':'本群净资产榜：\n'+('\n'.join(f'{i}. {e["name"]} {e["return_pct"]:+.2f}%' for i,e in enumerate(entries,1)) or '暂无参与者。')}
            return await self.query(action,{},None,actor)
        if method=='query':return await self.query(action,p,uid,actor)
        if method=='account':
            if action=='open':return {'text':(await self.accounts.open_account(uid,actor.get('nickname',uid)))[1]}
            if action=='rebirth':return {'text':(await self.accounts.rebirth(uid))[1]}
            if action=='funds':
                account=await self.db.get_account(uid)
                if not account:raise ValueError('请先开户。')
                value=(await ValuationService(self.db).all(self.price_of))[uid]
                return {'data':{**dict(account),**value},'private':True,'text':f'可用{account["cash_available"]:,.2f}，冻结{account["cash_frozen"]:,.2f}，可取{account["cash_withdrawable"]:,.2f}，净资产{value["net_assets"]:,.2f}，负债{value["debt"]:,.2f}。'}
            if action=='portfolio':
                positions=[dict(r) for r in await self.db.get_positions(uid)]
                return {'data':positions,'private':True,'text':'我的持仓：\n'+('\n'.join(f'{STOCK_POOL[r["code"]].name}({r["code"]}) {r["quantity"]}股，可卖{r["sellable"]}，成本{r["cost_price"]:.2f}' for r in positions) or '暂无持仓。')}
            if action in ('orders','trades'):
                rows=await self.db.get_user_open_orders(uid) if action=='orders' else await self.db.get_user_trades(uid)
                return {'data':[dict(r) for r in rows],'private':True,'text':('当前委托' if action=='orders' else '最近成交')+'：\n'+('\n'.join(f'#{r["order_id"]} {r["code"]} {r["side"]} {r["quantity"]}股 @{r["price"]:.2f}' for r in rows) or '暂无记录。')}
            if action=='watchlist':return {'text':await self.watchlist.render(uid,self.price_of),'private':True}
            if action in ('watch_add','watch_remove'):
                fn=self.watchlist.add if action=='watch_add' else self.watchlist.remove
                return {'text':(await fn(uid,self.resolve_code(p.get('code'))))[1]}
        if method=='trade':
            if action=='cancel':return {'text':await self.trade.cancel(uid,positive_int(p.get('order_id'),'order_id'))}
            code=self.resolve_code(p.get('code'));qty=positive_int(p.get('quantity'))
            if action not in ('buy','sell'):raise ValueError('unknown trade action')
            # A changed default order type must not be guessed from vague speech.
            text=await (self.trade.buy if action=='buy' else self.trade.sell)(uid,code,qty,p.get('price'))
            return {'text':text}
        if method=='play':return await self.play(action,p,uid)
        if method=='admin':
            if actor.get('identity')!='admin' or actor.get('scope')!='private':raise ValueError('admin only; private scope required')
            reason=p.get('reason','')
            if action=='health':return {'data':self.health,'text':health_text(self.health)}
            if action=='audit':
                audit=await self.db.audit(strict_reserves=True);return {'data':audit,'text':'账本核对通过。' if audit['ok'] else '账本存在差异，请检查审计记录。'}
            if action=='pause':self.engine.paused=True
            elif action=='resume':self.engine.paused=False
            elif action=='settle':await self.dayclose.run(self.board,self.price_of,'manual:'+str(p.get('token') or uuid.uuid4()));self.clock.reset()
            elif action=='compensate':
                if not reason:raise ValueError('补偿必须提供原因。')
                await self.db.grant_cash(uid,positive_int(p.get('amount'),'amount',1_000_000),'compensation')
            elif action=='backup':return {'text':'一致性备份已完成并保存在本机受保护目录。'}
            else:raise ValueError('unknown admin action')
            return {'text':'市场管理操作已完成。','reason':reason}
        raise ValueError('unknown market operation')
    async def query(self,action,p,uid,actor):
        if action=='help':
            from .render.help import HELP_STYLE, help_text
            return {'text':help_text(CFG),'render':{'kind':'help','style':HELP_STYLE,'rules':asdict(CFG)}}
        if action in ('overview','analyze'):
            from .market.query_scope import resolve_scope
            from .render.overview import STYLE, stock_snapshot
            scope=resolve_scope(p)
            histories=await self.db.overview_candles()
            rows=[stock_snapshot(STOCK_POOL[code],self.engine.quotes.get(code),histories.get(code,[]),self.engine)
                  for code in scope['codes']]
            changes=[r['change_pct'] for r in rows if r['change_pct'] is not None]
            if scope['filtered']:
                up=sum(v>0 for v in changes);down=sum(v<0 for v in changes);flat=sum(v==0 for v in changes)
                change=sum(changes)/len(changes) if changes else None
            else:
                up,flat,down=self.engine.advancers();change=self.engine.market_change()
            data={'advancers':up,'decliners':down,'flat':flat,'market_change':change,
                  'scope':scope,'quoted_count':len(changes),'unquoted_count':len(rows)-len(changes),
                  'day':self.dayclose._day_seq,'phase':self.clock.phase(),'mode':CFG.market_mode,'day_seconds':CFG.day_seconds}
            snapshot={**data,'timestamp':time.time(),'tick':self.health['ticks'],'paused':self.engine.paused,'stocks':rows}
            # Persist this exact scope and snapshot; rendering/replay never read live quotes.
            label=scope['label']+'，共' if scope['filtered'] else '全部'
            average='所选股票等权涨幅' if scope['filtered'] else '大盘'
            change_text=f'{change:+.2f}%' if change is not None else '暂无报价'
            text=f'行情：{label}{len(rows)}只股票，上涨{up}只，下跌{down}只，平盘{flat}只，{average}{change_text}，交易日#{data["day"]}，阶段{data["phase"]}。行情按板块分别成图，包含实时涨幅、历史1/5/20日涨幅、放大历史日K线与当日未收盘K线。'
            if data['unquoted_count']:text+=f"另有{data['unquoted_count']}只暂无报价，不计入涨跌统计。"
            if action=='analyze':
                news=await self.query('news',{**p,'limit':30},uid,actor)
                for row in rows:
                    quote=self.engine.quotes.get(row['code'])
                    row['volume']=quote.volume if quote else None
                return {'analysis':True,'question':str(p.get('question',''))[:2000],
                        'data':{'snapshot':snapshot,'news':news['data']},'text':'只读市场分析数据已准备。'}
            return {'data':data,'text':text,'render':{'kind':'overview','style':STYLE,'snapshot':snapshot}}
        if action=='search':
            word=str(p.get('keyword','')).casefold();items=[{'code':s.code,'name':s.name} for s in STOCK_POOL.values() if word in (s.code+s.name+s.short_code).casefold()][:30]
            return {'data':items,'text':'\n'.join(f'{r["name"]} {r["code"]}' for r in items) or '没有匹配股票。'}
        if action in ('calendar','event','sector'):
            if not hasattr(self.engine,'causal'):raise ValueError('当前模型未启用事件信息查询。')
            from .market.causal_public import query_public
            if action=='event':
                # Durable public feed survives the in-memory 512-row window.
                eid=str(p.get('event_id') or '')
                if not eid or len(eid)>80:raise ValueError('请提供公开新闻中的事件编号。')
                saved=await (await self.db.conn.execute(
                    "SELECT payload FROM causal_news WHERE json_extract(payload,'$.event_id')=? ORDER BY seq DESC LIMIT 100",(eid,))).fetchall()
                if saved:
                    state={**self.engine.causal,'public_news':[json.loads(row['payload']) for row in reversed(saved)]}
                    return query_public(state,action,p,self.engine)
            return query_public(self.engine.causal,action,p,self.engine)
        if action in ('stock','book','chart'):
            code=self.resolve_code(p.get('code'));stock=STOCK_POOL[code];q=self.engine.get(code)
            if action=='book':
                self.matcher.limits[code]=(q.limit_down(stock),q.limit_up(stock));levels=self.matcher.five_levels(code,q.price)
                return {'data':{'bids':levels[0],'asks':levels[1]},'text':f'{stock.name}({code})五档：\n买盘'+str(levels[0])+'\n卖盘'+str(levels[1])}
            result={'data':{'code':code,'name':stock.name,'price':q.price,'change_pct':q.change_pct,'volume':q.volume,'suspended':self.engine.is_suspended(code),'delisted':self.engine.is_delisted(code)},'text':f'{stock.name}({code}) {q.price:.2f}元，{q.change_pct:+.2f}%。'}
            if action=='stock' and hasattr(self.engine,'public_status'):
                result['data']['public_financials']=self.engine.public_status(code)
                info=result['data']['public_financials']
                result['text']+=f'\n公开财务：最近报告日{info["last_report_day"]}，年化自由现金流估计{info["published_annual_fcf"]:,.2f}元；估计存在不确定性。'
            if action=='chart':result['render']={'kind':'chart','code':code}
            return result
        if action=='rank':
            entries=await self.board.top(self.price_of,limit=p.get('limit',10),group_id=actor.get('groupId') if p.get('local',True) else None)
            return {'data':entries,'text':'股市排行榜（净资产收益率）：\n'+('\n'.join(f'{i}. {e["name"]} {e["return_pct"]:+.2f}% 净资产{e["total"]:,.2f}' for i,e in enumerate(entries,1)) or '暂无参与者。')}
        if action=='history':return {'text':await self.board.render_history(p.get('limit',14)),'render':{'kind':'history'}}
        if action=='news':
            from .market.query_scope import resolve_scope
            scope=resolve_scope(p)
            limit=min(30,max(1,int(p.get('limit',10))))
            if hasattr(self.engine,'causal'):
                news=await self.db.query_causal_news(scope['codes'] if scope['filtered'] else None,limit)
                news=[{**r,'headline':public_market_text(r['headline'])} for r in news]
                lines=[f"#{r['seq']} [{r['stage']}] {r['headline']}" for r in news]
            else:
                news=await self.db.query_legacy_news(int(time.time())-86400,scope,limit)
                news=[{**r,'headline':public_market_text(r['headline'])} for r in news]
                lines=[r['headline'] for r in news]
            label=' · '+scope['label'] if scope['filtered'] else ''
            empty='暂无该范围的直接关联快讯。' if scope['filtered'] else '暂无快讯。'
            return {'data':news,'scope':scope,'news':True,'text':f'市场快讯{label}：\n'+('\n'.join(lines) or empty)}
        raise ValueError('unknown query action')
    async def play(self,action,p,uid):
        if action in RETIRED_ACTIONS:raise ValueError(RETIRED_ACTIONS[action])
        if not await self.db.get_account(uid):raise ValueError('请先开户。')
        group=('margin' if action in ('borrow_cash','repay_cash','borrow_stock','cover','margin_status') else 'ipo' if action in ('subscribe','issue','ipo') else 'props' if 'prop' in str(action) else 'season' if 'season' in str(action) else 'quests')
        if not self.options['features'].get(group,False):raise ValueError('该功能尚未启用。')
        if action=='checkin':data=await self.quest.handle_checkin(uid)
        elif action=='achievements':data=await self.achieve.claim(uid,self.price_of)
        elif action=='props':data={'shop':await self.props.get_shop(uid),'owned':await self.props.get_user_props(uid)}
        elif action=='buy_prop':data=await self.props.buy_prop(uid,p.get('prop_id'),p.get('quantity',1))
        elif action=='sell_prop':data=await self.props.sell_prop(uid,p.get('prop_id'),p.get('quantity',1))
        elif action=='use_prop':
            data=await self.props.use_prop(uid,p.get('prop_id'))
        elif action=='ipo':return {'text':await self.ipo.status_text(uid)}
        elif action=='subscribe':return {'text':await self.ipo.subscribe(uid,self.resolve_ipo(p.get('code')),p.get('quantity',1))}
        elif action=='issue':
            name=p.get('name');price=p.get('price');quantity=p.get('quantity')
            if not isinstance(name,str) or not 1<=len(name)<=20 or any(ord(c)<32 for c in name):raise ValueError('股票名称必须为1至20个普通字符。')
            positive_int(quantity)
            result=await self.ipo.issue_stock(uid,name,price,quantity)
            if not result[0]:raise ValueError(result[1])
            return {'text':result[1]}
        elif action=='borrow_cash':return {'text':await self.margin.borrow_cash(uid,p.get('amount'))}
        elif action=='repay_cash':return {'text':await self.margin.repay_cash(uid,p.get('amount'))}
        elif action=='borrow_stock':return {'text':await self.margin.borrow_stock(uid,self.resolve_code(p.get('code')),p.get('quantity'))}
        elif action=='cover':return {'text':await self.margin.cover(uid,self.resolve_code(p.get('code')),p.get('quantity'))}
        elif action=='margin_status':
            net=await self.margin.net_worth(uid);debt=await self.margin.debt(uid)
            return {'text':f'净资产{net:,.2f}，负债{debt:,.2f}。','private':True}
        else:raise ValueError('unknown gameplay action')
        if data.get('ok') is False or data.get('success') is False:raise ValueError(data.get('error') or data.get('msg') or '操作未完成。')
        return {'data':data,'text':play_text(action,data,CFG.currency)}
    def resolve_ipo(self,value):
        # Unlisted IPO codes are intentionally absent from STOCK_POOL.
        value=str(value or '')
        if not value.isdecimal() or len(value)!=6:raise ValueError('申购请填写六位发行代码。')
        return value
    async def render(self,result):
        opid=result.get('operation_id')
        if not opid:return await self._render(result)
        lock=self._render_locks.setdefault(opid,asyncio.Lock())
        async with lock:
            row=await (await self.db.conn.execute('SELECT result FROM business_operations WHERE id=?',(opid,))).fetchone()
            saved=json.loads(row['result']) if row else result
            if saved.get('artifact') and all(Path(p).is_file() for p in saved.get('artifacts',[saved['artifact']])):return saved
            rendered=await self._render(saved)
            if row and rendered.get('artifact'):
                async with self.db.transaction():
                    await self.db.conn.execute('UPDATE business_operations SET result=? WHERE id=?',(json.dumps(rendered,ensure_ascii=False),opid))
                    event=await (await self.db.conn.execute('SELECT payload FROM outbox WHERE id=?',(opid,))).fetchone()
                    if event:
                        payload=json.loads(event['payload']);payload['result']=rendered
                        await self.db.conn.execute('UPDATE outbox SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),opid))
            return rendered
    async def _render(self,result):
        descriptor=result.get('render')
        if not descriptor:return result
        async with self._render_semaphore:
            try:
                key=json.dumps([descriptor] if descriptor['kind'] in ('help','overview') else [descriptor,self.health['ticks'],self.dayclose._day_seq],sort_keys=True)
                cached=self._render_cache.get(key)
                if cached and all(Path(p).is_file() for p in (cached if isinstance(cached,list) else [cached])):
                    paths=cached if isinstance(cached,list) else [cached]
                    return {**result,'artifact':paths[0],'artifacts':paths,**({'text':'股市使用说明｜所有操作以 /fx 开头。'} if descriptor['kind']=='help' else {})}
                from .render import chart
                target=self.path/'artifacts'/(uuid.uuid4().hex+'.png');target.parent.mkdir(mode=0o700,exist_ok=True)
                if descriptor['kind']=='help':
                    from .render.help import render_help
                    from .config import Config
                    await asyncio.to_thread(render_help,target,Config(**descriptor['rules']))
                    result={**result,'text':'股市使用说明｜所有操作以 /fx 开头。'}
                elif descriptor['kind']=='overview':
                    from .render.overview import render_overview, partition_overview
                    paths=[]
                    try:
                        for index,snapshot in enumerate(partition_overview(descriptor['snapshot'])):
                            page=target.with_name(target.stem+f'-sector-{index+1}.png')
                            await asyncio.to_thread(render_overview,page,snapshot)
                            paths.append(str(page))
                    except Exception:
                        for page in paths:Path(page).unlink(missing_ok=True)
                        raise
                    self._render_cache[key]=paths
                    return {**result,'artifact':paths[0],'artifacts':paths}
                elif descriptor['kind']=='chart':
                    code=descriptor['code'];rows=await self.db.get_candles(code,limit=30)
                    bars=[dict(r) for r in rows]
                    from types import SimpleNamespace
                    bars=[SimpleNamespace(**r) for r in bars]
                    if not bars:bars=self.engine.intraday_bars(code)
                    if not bars:return {**result,'render_error':'尚无K线数据，已返回文字行情。'}
                    await asyncio.to_thread(chart.render_kline,target,STOCK_POOL[code].name,bars)
                elif descriptor['kind']=='history':
                    rows=await self.db.list_leaderboard_snapshots(14)
                    if not rows:return result
                    await asyncio.to_thread(chart.render_history_chart,target,rows)
                else:
                    raise ValueError('unknown render kind')
                self._render_cache[key]=str(target)
                return {**result,'artifact':str(target)}
            except Exception:
                log.exception('market render failed')
                if descriptor['kind']=='overview':
                    from .render.overview import fallback_text
                    result={**result,'text':result['text']+'\n'+fallback_text(descriptor['snapshot'])}
                return {**result,'render_error':'图片暂不可用，文字结果仍有效。'}
    async def cleanup_artifacts(self):
        cutoff=time.time()-self.options.get('artifactRetentionHours',24)*3600
        pending=[json.loads(r['payload']) for r in await (await self.db.conn.execute("SELECT payload FROM outbox WHERE state!='accepted'")).fetchall()]
        protected={path for p in pending for path in p.get('result',{}).get('artifacts',[p.get('result',{}).get('artifact')])}
        for path in (self.path/'artifacts').glob('*.png'):
            if str(path) not in protected and path.stat().st_mtime<cutoff:path.unlink(missing_ok=True)
        self._render_cache={k:v for k,v in self._render_cache.items() if all(Path(p).is_file() for p in (v if isinstance(v,list) else [v]))}
        self._render_locks={k:v for k,v in self._render_locks.items() if v.locked()}

async def serve(args):
    import fcntl
    os.umask(0o077)
    root=Path(args.state_dir);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(root/'runtime.lock').open('a')
    try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    options=json.loads(Path(args.config).read_text()) if args.config else {}
    runtime=MarketRuntime(root,args.market_id,options)
    from .log import setup_file_logging,set_level
    set_level(CFG.log_level);setup_file_logging(root,CFG.log_level)
    runtime.options_hash=hashlib.sha256(Path(args.config).read_bytes()).hexdigest() if args.config else None
    await runtime.start();socket=root/'runtime.sock';socket.unlink(missing_ok=True)
    clients=set()
    async def client(reader,writer):
        task=asyncio.current_task();clients.add(task)
        try:
            raw=await asyncio.wait_for(reader.readline(),timeout=5)
            if len(raw)>65536:raise ValueError('request too large')
            request=json.loads(raw)
            result=await asyncio.wait_for(runtime.execute(request),timeout=120)
            if result.get('render'):
                result=await runtime.render(result)
            writer.write((json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n').encode());await writer.drain()
        except Exception as exc:
            # Raw tracebacks stay in the local log; only bounded business errors leave.
            log.exception('market request failed')
            message=str(exc)[:300] if isinstance(exc,ValueError) else '市场操作未完成，请查询原订单状态。'
            writer.write((json.dumps({'ok':False,'error':message,**({'public_error':exc.public_error} if isinstance(exc,QueryScopeError) else {})},ensure_ascii=False)+'\n').encode())
            await writer.drain()
        finally:
            writer.close()
            try:await writer.wait_closed()
            finally:clients.discard(task)
    server=await asyncio.start_unix_server(client,path=socket,limit=65537)
    os.chmod(socket,0o600)
    stop=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stop.set)
    async with server:await stop.wait()
    server.close();await server.wait_closed()
    if clients:
        _,pending=await asyncio.wait(clients,timeout=30)
        for task in pending:task.cancel()
        if pending:await asyncio.gather(*pending,return_exceptions=True)
    await runtime.close();socket.unlink(missing_ok=True);lock.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['serve']);parser.add_argument('--state-dir',required=True);parser.add_argument('--market-id',default='shared');parser.add_argument('--config');args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    asyncio.run(serve(args))
if __name__=='__main__':main()
