"""内存订单簿 + 撮合引擎（P0）。

结构：玩家委托为订单簿主体；做市商（MarketMaker）在玩家盘口之外补充五档流动性。
撮合规则：价格优先、时间优先；玩家单先与玩家对手单撮合，剩余与做市商成交。
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from dataclasses import dataclass, field

from ..config import CFG


@dataclass
class BookOrder:
    order_id: int
    user_id: str
    side: str          # "buy" / "sell"
    price: float
    remaining: int     # 剩余数量
    seq: int           # 时间优先序号


@dataclass
class Fill:
    """一笔成交。"""
    taker_order_id: int
    taker_user_id: str
    maker_order_id: int | None     # None = 对手是做市商
    maker_user_id: str | None
    price: float
    quantity: int


class OrderBook:
    """单个股票的订单簿。bids 降序、asks 升序。"""

    def __init__(self, code: str):
        self.code = code
        self.bids: list[BookOrder] = []
        self.asks: list[BookOrder] = []

    def add(self, o: BookOrder) -> None:
        book = self.bids if o.side == "buy" else self.asks
        book.append(o)
        # 价格优先，同价时间优先
        book.sort(key=lambda x: (-x.price if o.side == "buy" else x.price, x.seq))

    def remove(self, order_id: int) -> BookOrder | None:
        for book in (self.bids, self.asks):
            for i, o in enumerate(book):
                if o.order_id == order_id:
                    return book.pop(i)
        return None

    def best_bid(self) -> BookOrder | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> BookOrder | None:
        return self.asks[0] if self.asks else None

    def depth(self, side: str, levels: int = 5) -> list[tuple[float, int]]:
        """聚合五档：[(价格, 总量), ...]"""
        book = self.bids if side == "buy" else self.asks
        agg: dict[float, int] = defaultdict(int)
        for o in book:
            agg[o.price] += o.remaining
        prices = sorted(agg, reverse=(side == "buy"))[:levels]
        return [(p, agg[p]) for p in prices]


class MarketMaker:
    """虚拟做市商：围绕最新价挂五档，保证流动性。"""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def quote(self, mid: float) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
        """返回 (买盘五档, 卖盘五档)。"""
        bids, asks = [], []
        for lv in range(1, 6):
            off = CFG.mm_spread * lv
            bp = round(mid * (1 - off), 2)
            ap = round(mid * (1 + off), 2)
            qty = int(CFG.mm_depth / lv * self.rng.uniform(0.7, 1.3))
            bids.append((bp, qty))
            asks.append((ap, qty))
        return bids, asks

    def mm_price_for(self, side: str, mid: float, book: OrderBook) -> float:
        return round(mid * (1 + CFG.mm_spread if side == "buy" else 1 - CFG.mm_spread), 2)


class Matcher:
    """撮合器。持有所有股票的订单簿，统计净压力供价格引擎反馈。"""

    def __init__(self):
        self.books = {}
        self.mm = MarketMaker(random.Random())
        self._seq = itertools.count(1)
        self.pressure = defaultdict(int)
        self.liquidity = {}
        self.limits = {}
        self.capacity = {}
        self.risk = {}

    def book(self, code):
        return self.books.setdefault(code, OrderBook(code))

    def reset_liquidity(self):
        self.liquidity.clear()

    def _liquidity(self, code, mid):
        if code not in self.liquidity:
            sides = []
            low, high = self.limits.get(code, (CFG.price_tick, float('inf')))
            for side, levels in zip(('buy','sell'), self.mm.quote(mid)):
                spread,depth=self.risk.get(code,(1.,1.))
                remaining = min(int(CFG.mm_depth*depth),self.capacity.get(code,(2**60,2**60))[0 if side=='buy' else 1])
                normalized = []
                for index, (price, _) in enumerate(levels):
                    price = mid+(price-mid)*spread
                    price = round(min(high, max(low, price)),2)
                    qty = remaining if index == 4 else min(remaining, max(CFG.lot_size, (CFG.mm_depth // (index+2) // CFG.lot_size) * CFG.lot_size))
                    if qty:
                        normalized.append([price, qty])
                        remaining -= qty
                sides.append(normalized)
            self.liquidity[code] = sides
        return self.liquidity[code]

    def cap_liquidity(self,code):
        if code not in self.liquidity:return
        for levels,cap in zip(self.liquidity[code],self.capacity.get(code,(2**60,2**60))):
            for level in levels:
                level[1]=min(level[1],cap);cap-=level[1]

    def place(self, order_id, user_id, code, side, price, quantity, mid):
        book = self.book(code)
        order = BookOrder(order_id,user_id,side,price,quantity,next(self._seq))
        opposing = book.asks if side == 'buy' else book.bids
        crosses = lambda p: p <= price if side == 'buy' else p >= price
        if any(o.user_id == user_id and crosses(o.price) for o in opposing):
            raise ValueError('不能与自己的挂单成交，请先撤销反向委托。')
        levels = self._liquidity(code, mid)[1 if side == 'buy' else 0]
        fills = []
        while order.remaining:
            best = opposing[0] if opposing else None
            mm = next((level for level in levels if level[1] > 0), None)
            player_price = best.price if best else None
            mm_price = mm[0] if mm else None
            if player_price is None and mm_price is None:
                break
            use_player = best is not None and (mm is None or (player_price <= mm_price if side == 'buy' else player_price >= mm_price))
            fill_price = player_price if use_player else mm_price
            if not crosses(fill_price):
                break
            qty = min(order.remaining, best.remaining if use_player else mm[1])
            fills.append(Fill(order_id,user_id,best.order_id if use_player else None,best.user_id if use_player else None,fill_price,qty))
            order.remaining -= qty
            if use_player:
                best.remaining -= qty
                if not best.remaining:
                    opposing.pop(0)
            else:
                mm[1] -= qty
            self.pressure[code] += qty if side == 'buy' else -qty
        if order.remaining:
            book.add(order)
        return fills

    def cancel(self, code, order_id):
        return self.book(code).remove(order_id)

    def restore(self, order_id, user_id, code, side, price, remaining):
        self.book(code).add(BookOrder(order_id,user_id,side,price,remaining,next(self._seq)))

    def five_levels(self, code, mid):
        result=[]
        for side, mm in zip(('buy','sell'),self._liquidity(code,mid)):
            levels=defaultdict(int)
            for price, qty in self.book(code).depth(side,levels=1_000_000): levels[price]+=qty
            for price, qty in mm: levels[price]+=qty
            prices=sorted((p for p,q in levels.items() if q>0),reverse=side=='buy')[:5]
            result.append([(p,levels[p]) for p in prices])
        return tuple(result)

    def take_pressure(self, code):
        return self.pressure.pop(code,0)
