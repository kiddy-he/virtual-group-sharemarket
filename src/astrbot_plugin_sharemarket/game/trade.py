"""Transactional orders, per-order reserves and cumulative per-order fees."""
from __future__ import annotations
import math
import time
from .atomic import atomic
from ..config import CFG
from ..market import calendar
from ..market.stocks import STOCK_POOL
from ..market.orderbook import Fill
from ..storage.money import cents, money, positive_int

class TradeError(ValueError):
    pass

def fees_buy(amount):
    return money(max(amount * CFG.commission_rate, CFG.commission_min) + amount * CFG.transfer_fee_rate)

def fees_sell(amount):
    return money(max(amount * CFG.commission_rate, CFG.commission_min) + amount * (CFG.transfer_fee_rate + CFG.stamp_tax_rate))

def freeze_estimate(price, qty):
    return money(price * qty + fees_buy(price * qty)) if qty else 0.0

class TradeService:
    def __init__(self, db, engine, matcher, auction=None):
        self.db,self.engine,self.matcher,self.auction=db,engine,matcher,auction
        if not db.memory_objects:
            db.memory_objects.extend([(engine,tuple(engine.__dict__)),(matcher,tuple(matcher.__dict__))])

    @atomic
    async def buy(self,user_id,code,quantity,price=None):
        return await self._place(user_id,code,'buy',quantity,price)

    @atomic
    async def sell(self,user_id,code,quantity,price=None):
        return await self._place(user_id,code,'sell',quantity,price)

    async def _place(self,user_id,code,side,quantity,price):
        self._validate(code,quantity,side)
        acc=await self._get_active_account(user_id)
        quote=self.engine.get(code); stock=STOCK_POOL[code]
        auction=calendar.SESSION.is_auction()
        if auction and price is None:
            raise TradeError('集合竞价仅接受明确价格的限价委托。')
        market=price is None
        if price is None: price=quote.limit_up(stock) if side=='buy' else quote.limit_down(stock)
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
            raise TradeError('价格必须为有限正数。')
        price=money(price)
        self._check_limit(stock,quote,price,side)
        phase=calendar.SESSION.phase() if auction else 'continuous'
        cur=await self.db.conn.execute("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status IN ('open','partial')",(user_id,))
        if (await cur.fetchone())['n']>=100:
            raise TradeError('未成交委托已达100笔，请先撤单。')
        # Same-user crossing is rejected before reserving or changing either book.
        for row in await self.db.get_user_open_orders(user_id):
            if row['code']==code and row['side']!=side and (price>=row['price'] if side=='buy' else price<=row['price']):
                raise TradeError('不能与自己的挂单成交，请先撤销反向委托。')
        discount=1.0
        effect=await (await self.db.conn.execute('SELECT * FROM fee_effects WHERE user_id=? AND remaining>0',(user_id,))).fetchone()
        if effect:
            discount=effect['discount']
            await self.db.conn.execute('UPDATE fee_effects SET remaining=remaining-1 WHERE user_id=?',(user_id,))
        oid=await self.db.insert_order(user_id,code,side,price,quantity,int(time.time()),phase)
        await self.db.conn.execute('UPDATE orders SET fee_discount=? WHERE order_id=?',(discount,oid))
        reserve=0.0
        if side=='buy':
            reserve=money(price*quantity+fees_buy(price*quantity)*discount)
            if cents(reserve)>cents(acc['cash_available']):
                raise TradeError(f'资金不足：需要 {reserve:,.2f}，可用 {acc["cash_available"]:,.2f}。')
            settled=min(cents(acc['cash_withdrawable']),cents(reserve))
            await self._move_cash(user_id,available=-reserve,withdrawable=-settled/100,frozen=reserve)
            await self.db.update_order_frozen(oid,reserve)
            await self.db.conn.execute('UPDATE orders SET settled_frozen=? WHERE order_id=?',(settled,oid))
        else:
            pos=await self.db.get_position(user_id,code)
            if not pos or quantity>pos['sellable']:
                raise TradeError('可卖持仓不足（今日买入受T+1限制，挂单股份已冻结）。')
            if quantity%CFG.lot_size and quantity!=pos['quantity']:
                raise TradeError('零股只能一次性清仓。')
            await self.db.upsert_position(user_id,code,pos['quantity'],pos['sellable']-quantity,pos['cost_price'])
        if auction:
            if self.auction is None: raise TradeError('竞价服务不可用。')
            self.auction.book(code).add(oid,user_id,side,price,quantity)
            return f'📋 集合竞价委托 #{oid}：{stock.name}（{code}）\n{quantity}股 @{price:.2f}，已进入竞价簿。'
        self.matcher.limits[code]=(quote.limit_down(stock),quote.limit_up(stock))
        if hasattr(self.engine,'liquidity_caps'):
            self.matcher.capacity[code]=self.engine.liquidity_caps(code,quote.limit_up(stock))
            state=self.engine.causal;i=state['profile']['codes'].index(code)
            stress=max(0.,float(state['public_macro'][3]))
            self.matcher.risk[code]=(1+stress*2, max(.15,1/(1+stress*3)))
            # Funding caps must apply even after an earlier cached book.
            self.matcher.cap_liquidity(code)
        fills=self.matcher.place(oid,user_id,code,side,price,quantity,self.engine.reference_price(code) if hasattr(self.engine,'reference_price') else quote.price)
        spent=gained=0.0
        for fill in fills:
            fee=await self._settle(oid,fill.price,fill.quantity)
            if side=='buy':spent+=fill.price*fill.quantity+fee
            else:gained+=fill.price*fill.quantity-fee
            if fill.maker_order_id:
                await self._settle(fill.maker_order_id,fill.price,fill.quantity)
            if hasattr(self.engine,'settle_house'):
                if not fill.maker_order_id:self.engine.settle_house(code,side,fill.price,fill.quantity,fee)
                self.engine.on_fill(code,fill.quantity,fill.price,side)
            else:self.engine.on_fill(code,fill.quantity)
        row=await self.db.get_order(oid)
        return self._fill_report('买入' if side=='buy' else '卖出',code,quantity,row['filled'],fills,oid,spent=money(spent),gained=money(gained),frozen=row['frozen'],market=market,limit_price=price)

    async def _order_fee(self,row,price,qty):
        previous=await (await self.db.conn.execute('SELECT COALESCE(SUM(price*quantity),0) amount, COALESCE(SUM(fee),0) fee FROM trades WHERE order_id=?',(row['order_id'],))).fetchone()
        amount=money(previous['amount']+price*qty)
        total=(fees_buy(amount) if row['side']=='buy' else fees_sell(amount))*row['fee_discount']
        return max(0.0,money(total-previous['fee']))

    async def _settle(self,oid,price,qty):
        row=await self.db.get_order(oid)
        if not row or row['status'] not in ('open','partial') or row['filled']+qty>row['quantity']:
            raise TradeError('委托状态与成交计划不一致。')
        fee=await self._order_fee(row,price,qty)
        amount=money(price*qty);uid=row['user_id'];code=row['code'];profit=0.0
        if row['side']=='buy':
            cost=money(amount+fee);held=cents(row['frozen']);need=cents(cost)
            if need>held:
                raise TradeError('该订单冻结资金不足，成交已回滚。')
            settled=row['settled_frozen'];used_settled=max(0,need-(held-settled))
            await self._move_cash(uid,frozen=-cost)
            await self.db.update_order_frozen(oid,(held-need)/100)
            await self.db.conn.execute('UPDATE orders SET settled_frozen=? WHERE order_id=?',(settled-used_settled,oid))
            await self._apply_buy_fill(uid,code,price,qty,fee)
        else:
            pos=await self.db.get_position(uid,code)
            if not pos or pos['quantity']<qty:
                raise TradeError('卖方持仓不足，成交已回滚。')
            profit=money(amount-fee-pos['cost_price']*qty)
            if not await self._apply_sell_fill(uid,code,qty):raise TradeError('持仓不一致。')
            await self._move_cash(uid,available=money(amount-fee))
        await self.db.insert_trade(oid,uid,code,row['side'],price,qty,fee,int(time.time()),profit)
        filled=row['filled']+qty
        await self.db.update_order(oid,filled,'filled' if filled==row['quantity'] else 'partial')
        if filled==row['quantity']:await self._release_reserve(oid)
        return fee

    async def _release_reserve(self,oid):
        row=await self.db.get_order(oid)
        if row['side']=='buy' and row['frozen']:
            await self._move_cash(row['user_id'],available=row['frozen'],frozen=-row['frozen'],withdrawable=row['settled_frozen']/100)
            await self.db.update_order_frozen(oid,0)
            await self.db.conn.execute('UPDATE orders SET settled_frozen=0 WHERE order_id=?',(oid,))

    @atomic
    async def cancel(self,user_id,order_id):
        row=await self.db.get_order(order_id)
        if not row or row['user_id']!=user_id:raise TradeError('只能撤销自己的有效委托。')
        if row['status'] not in ('open','partial'):raise TradeError(f'委托已是{row["status"]}。')
        if self.auction and self.auction.book(row['code']).get(order_id) and not calendar.SESSION.cancellable():
            raise TradeError('当前竞价阶段不可撤单。')
        await self._cancel_order_row(row)
        return f'已撤销委托 #{order_id}，未成交资金或股份已释放。'

    async def _cancel_order_row(self,row):
        if row['side']=='buy':await self._release_reserve(row['order_id'])
        else:
            pos=await self.db.get_position(row['user_id'],row['code'])
            if pos:
                await self.db.upsert_position(row['user_id'],row['code'],pos['quantity'],min(pos['quantity'],pos['sellable']+row['quantity']-row['filled']),pos['cost_price'])
        self.matcher.cancel(row['code'],row['order_id'])
        if self.auction:self.auction.book(row['code']).remove(row['order_id'])
        await self.db.update_order(row['order_id'],row['filled'],'cancelled')

    @atomic
    async def cancel_user_orders(self,user_id,side=None):
        rows=await self.db.get_user_open_orders(user_id)
        for row in rows:
            if side is None or row['side']==side:await self._cancel_order_row(row)
        return sum(side is None or r['side']==side for r in rows)

    @atomic
    async def place_auction(self,user_id,code,side,quantity,price):
        return await self._place(user_id,code,side,quantity,price)

    @atomic
    async def settle_auction_fill(self,code,order,price,qty):
        await self._settle(order.order_id,price,qty)
        if order.side=='buy':self.engine.on_fill(code,qty)

    async def _settle_sell_maker(self,user_id,order_id,code,price,qty):
        await self._settle(order_id,price,qty)
        return True

    async def _settle_buy_maker(self,user_id,order_id,code,price,qty):
        await self._settle(order_id,price,qty)

    async def _apply_sell_fill(self,user_id,code,qty):
        pos=await self.db.get_position(user_id,code)
        if not pos or pos['quantity']<qty:return False
        if pos['quantity']==qty:await self.db.delete_position(user_id,code)
        else:await self.db.upsert_position(user_id,code,pos['quantity']-qty,min(pos['sellable'],pos['quantity']-qty),pos['cost_price'])
        return True

    async def _apply_buy_fill(self,user_id,code,price,qty,fee=0):
        pos=await self.db.get_position(user_id,code)
        old_qty=pos['quantity'] if pos else 0
        cost=((pos['cost_price']*old_qty if pos else 0)+price*qty+fee)/(old_qty+qty)
        await self.db.upsert_position(user_id,code,old_qty+qty,pos['sellable'] if pos else 0,cost)

    def _validate(self,code,quantity,side):
        if code not in STOCK_POOL:raise TradeError('股票不存在。')
        try:positive_int(quantity)
        except ValueError as exc:raise TradeError(str(exc)) from exc
        if side=='buy' and quantity%CFG.lot_size:raise TradeError(f'买入数量须为{CFG.lot_size}股整数倍。')
        self._ensure_tradable(code)
        if not calendar.is_open():raise TradeError('当前非交易时段。')

    def _check_common(self,code,quantity):self._validate(code,quantity,'buy')

    def _ensure_tradable(self,code):
        ok,msg=self.engine.can_trade(code)
        if not ok:raise TradeError(msg)

    def _check_limit(self,stock,quote,price,side):
        if not quote.limit_down(stock)<=price<=quote.limit_up(stock):
            raise TradeError('委托价超出当日涨跌幅范围。')

    async def _get_active_account(self,user_id):
        acc=await self.db.get_account(user_id)
        if not acc or acc['status']!='active':raise TradeError('请先开户，且账户须处于正常状态。')
        return acc

    async def _move_cash(self,user_id,available=0.0,withdrawable=0.0,frozen=0.0):
        acc=await self.db.get_account(user_id)
        if not acc:raise TradeError('账户不存在。')
        await self.db.update_cash_full(user_id,(cents(acc['cash_available'])+cents(available))/100,max(0,(cents(acc['cash_withdrawable'])+cents(withdrawable))/100),(cents(acc['cash_frozen'])+cents(frozen))/100)

    async def _refresh_order(self,order_id):
        # Filled quantity comes from committed fills, never inferred from a book.
        row=await self.db.get_order(order_id)
        if row and row['filled']==row['quantity']:await self._release_reserve(order_id)

    async def _post_trade_bankruptcy_check(self,user_id):
        from .account import AccountService
        await AccountService(self.db).mark_bankrupt_if_l3(user_id,lambda c:self.engine.get(c).price if self.engine.get(c) else None)

    async def _record_trade(self,order_id,user_id,code,side,price,qty,fee,taker=False):
        await self.db.insert_trade(order_id,user_id,code,side,price,qty,fee,int(time.time()))

    def _fill_report(self, action: str, code: str, quantity: int,
                     filled_qty: int, fills: list[Fill], order_id: int,
                     spent: float = 0.0, gained: float = 0.0,
                     frozen: float = 0.0, market: bool = False,
                     limit_price: float | None = None) -> str:
        name = STOCK_POOL[code].name
        kind = "市价" if market else ""
        lines = [f"📋 {kind}{action}委托 #{order_id}：{name}（{code}）"]
        if filled_qty == 0:
            if market and limit_price is not None:
                lines.append(f"市价单未成交，{quantity} 股已按保护价 "
                             f"{limit_price:.2f} 挂单排队。")
            else:
                lines.append(f"未成交，{quantity} 股已挂单排队。")
            if frozen > 0:
                lines.append(f"已冻结资金 {frozen:,.2f} 元，撤单可释放。")
        else:
            avg = sum(f.price * f.quantity for f in fills) / filled_qty
            lines.append(f"成交 {filled_qty}/{quantity} 股，均价 {avg:.2f} 元")
            for f in fills[:3]:
                who = "做市商" if f.maker_user_id is None else "对手玩家"
                lines.append(f"  · {f.quantity} 股 @ {f.price:.2f}（对手：{who}）")
            if action == "买入":
                lines.append(f"支付 {spent:,.2f} 元（含佣金过户费）")
            else:
                lines.append(f"到账 {gained:,.2f} 元（已扣印花税佣金）")
            if filled_qty < quantity:
                lines.append(f"剩余 {quantity - filled_qty} 股挂单中，"
                             f"/fx 撤单 {order_id} 可撤销。")
                if market and limit_price is not None:
                    lines.append(f"市价单剩余按保护价 {limit_price:.2f} 排队。")
                if frozen > 0:
                    lines.append(f"挂单部分已冻结 {frozen:,.2f} 元。")
        return "\n".join(lines)
