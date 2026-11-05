"""JSON checkpoints with an explicit allowlist; no pickle or dynamic imports."""
import dataclasses
import itertools
import random
from collections import defaultdict
from ..market import engine,orderbook,auction,stocks
from ..events.news import News
TYPES={c.__name__:c for c in (engine.Quote,engine.MainForce,engine.LimitBoard,engine.Bar,orderbook.BookOrder,auction.AucOrder,stocks.Stock,News)}

def encode(value):
    if type(value).__module__.startswith('numpy'):
        import numpy as np
        if isinstance(value,np.ndarray):return {'$array':value.tolist(),'dtype':str(value.dtype)}
        if isinstance(value,np.generic):return value.item()
    if dataclasses.is_dataclass(value):return {'$type':type(value).__name__,'value':{f.name:encode(getattr(value,f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value,random.Random):return {'$random':encode(value.getstate())}
    if isinstance(value,itertools.count):return {'$count':list(value.__reduce__()[1])}
    if isinstance(value,set):return {'$set':[encode(v) for v in sorted(value)]}
    if isinstance(value,tuple):return {'$tuple':[encode(v) for v in value]}
    if isinstance(value,list):return [encode(v) for v in value]
    if isinstance(value,dict):return {str(k):encode(v) for k,v in value.items()}
    if value is None or isinstance(value,(int,float,str,bool)):return value
    raise TypeError(f'unsupported checkpoint type {type(value).__name__}')

def decode(value):
    if isinstance(value,list):return [decode(v) for v in value]
    if not isinstance(value,dict):return value
    if '$array' in value:
        import numpy as np
        if value.get('dtype') not in ('float64','int64','uint64','bool'):raise ValueError('unsupported array type')
        return np.array(value['$array'],dtype=value['dtype'])
    if '$type' in value:return TYPES[value['$type']](**{k:decode(v) for k,v in value['value'].items()})
    if '$tuple' in value:return tuple(decode(v) for v in value['$tuple'])
    if '$set' in value:return set(decode(v) for v in value['$set'])
    if '$count' in value:return itertools.count(*value['$count'])
    if '$random' in value:
        rng=random.Random();rng.setstate(decode(value['$random']));return rng
    return {k:decode(v) for k,v in value.items()}

class Recovery:
    key='runtime.checkpoint.v2'
    def __init__(self,db,price_engine,matcher,auction_service,corporate,news,clock):
        self.db=db
        self.objects={'engine':(price_engine,tuple(price_engine.__dict__)), 'corporate':(corporate,('_delisting','rng')), 'news':(news,('today','count_today','rng')), 'clock':(clock,('started','mode')), 'matcher':(matcher,('liquidity','limits','pressure','_seq'))}
        self.objects['market_maker']=(matcher.mm,('rng',))
        for obj,fields in self.objects.values():
            if not any(o is obj for o,_ in db.memory_objects):db.memory_objects.append((obj,fields))
        if not any(o is auction_service for o,_ in db.memory_objects):db.memory_objects.append((auction_service,('books',)))
        if not any(o is stocks for o,_ in db.memory_objects):db.memory_objects.append((stocks,('STOCK_POOL','STOCK_BY_SHORT')))
        db.checkpoint=self.save
    async def save(self):
        import json
        payload={key:{field:encode(getattr(obj,field)) for field in fields} for key,(obj,fields) in self.objects.items()}
        await self.db.set_meta(self.key,json.dumps({'version':2,'state':payload},ensure_ascii=False,allow_nan=False))
    async def restore(self):
        import json
        raw=await self.db.get_meta(self.key)
        if not raw:return False
        data=json.loads(raw)
        if data.get('version')!=2:raise ValueError('unsupported market checkpoint')
        for key,(obj,fields) in self.objects.items():
            if key in ('npc','market_maker') and key not in data['state']:continue
            state=data['state'][key]
            for field in fields:
                if field not in state:
                    if key=='engine' and field in ('causal','model_version','quote_kind','causal_news_cursor'):continue
                    raise ValueError('checkpoint field missing: '+key+'.'+field)
                value=decode(state[field])
                if key=='matcher' and field=='pressure':value=defaultdict(int,value)
                setattr(obj,field,value)
        if hasattr(self.objects['engine'][0],'causal') and 'causal' not in data['state']['engine']:
            self.objects['engine'][0].migrate_legacy()
        return True
