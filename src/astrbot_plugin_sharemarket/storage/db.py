"""SQLite 持久化层（aiosqlite）。P0 表：accounts / positions / orders / prices / meta。"""

from __future__ import annotations

import math
import asyncio
import json
from .connection import Connection
from .money import cents, money
import os
import sqlite3
import time
from contextlib import asynccontextmanager

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT PRIMARY KEY,
    user_name TEXT NOT NULL,
    cash_available REAL NOT NULL,
    cash_withdrawable REAL NOT NULL,
    cash_frozen REAL NOT NULL DEFAULT 0,        -- 挂单冻结
    initial_cash REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',      -- active / bankrupt / frozen
    rebirth_count INTEGER NOT NULL DEFAULT 0,
    last_rebirth_ts INTEGER,
    last_bankrupt_ts INTEGER,
    created_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    quantity INTEGER NOT NULL,       -- 总持仓
    sellable INTEGER NOT NULL,       -- 当前可卖（T+1 + 挂单冻结后）
    cost_price REAL NOT NULL,        -- 摊薄成本
    PRIMARY KEY (user_id, code)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,              -- buy / sell
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    filled INTEGER NOT NULL DEFAULT 0,
    frozen REAL NOT NULL DEFAULT 0,  -- 该买单当前冻结的资金
    status TEXT NOT NULL,            -- open/partial/filled/cancelled/expired
    phase TEXT NOT NULL DEFAULT 'continuous',  -- continuous / auction_open / auction_close
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_book ON orders(code, side, status);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);

CREATE TABLE IF NOT EXISTS prices (
    code TEXT PRIMARY KEY,
    price REAL NOT NULL,             -- 最新价
    prev_close REAL NOT NULL,        -- 昨收
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    side TEXT NOT NULL,              -- buy / sell
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    fee REAL NOT NULL,               -- 该笔成交的费用
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id, trade_id);
CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id);

CREATE TABLE IF NOT EXISTS candles (
    code TEXT NOT NULL,
    period TEXT NOT NULL,            -- 1d = 日K（分时只在内存里，日终落库）
    ts INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (code, period, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles ON candles(code, period, ts);

CREATE TABLE IF NOT EXISTS news (
    news_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    scope TEXT NOT NULL,             -- market / sector / stock
    target TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,              -- 利好 / 利空
    headline TEXT NOT NULL,
    impact REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(ts);

CREATE TABLE IF NOT EXISTS watchlist (
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    created_ts INTEGER NOT NULL,
    PRIMARY KEY (user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);

CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
    day_ts INTEGER NOT NULL,        -- 当日零点时间戳（与 DayCloseService._day_seq 对齐的单调日键）
    rank INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    total REAL NOT NULL,            -- 当日总资产（可用+持仓市值，不含 withdrawable）
    cash REAL NOT NULL,             -- 当日可用资金快照
    mv REAL NOT NULL,               -- 当日持仓市值
    return_pct REAL NOT NULL,       -- 相对 initial_cash 的收益率 %
    status TEXT NOT NULL,           -- active / bankrupt
    rebirth_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day_ts, rank)
);
CREATE INDEX IF NOT EXISTS idx_lbsnap_day ON leaderboard_snapshots(day_ts);

CREATE TABLE IF NOT EXISTS player_ipos (
    issuer TEXT NOT NULL,             -- 发行发起人 user_id
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    price REAL NOT NULL,              -- 发行价（>0 有限实数）
    total_shares INTEGER NOT NULL,    -- 发行总股数（>0）
    lot_size INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'draft',   -- draft / listed / delisted
    created_ts INTEGER NOT NULL,
    PRIMARY KEY (issuer, code)
);
CREATE INDEX IF NOT EXISTS idx_player_ipo_issuer ON player_ipos(issuer);
CREATE INDEX IF NOT EXISTS idx_player_ipo_code ON player_ipos(code);
"""

# 已存在的旧库升级（新库 SCHEMA 已含这些列，ALTER 会报 duplicate column，忽略）
MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN settled_frozen INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN fee_discount REAL NOT NULL DEFAULT 1",
    "ALTER TABLE accounts ADD COLUMN cash_frozen REAL NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN frozen REAL NOT NULL DEFAULT 0",
    "ALTER TABLE orders ADD COLUMN phase TEXT NOT NULL DEFAULT 'continuous'",
]


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self._owner = None
        self.operation_id = None
        self.memory_objects = []
        self.checkpoint = None
        self._backup_day: str | None = None   # 已成功备份的自然日（进程内缓存）

    async def open(self) -> None:
        raw = await aiosqlite.connect(self.path, isolation_level=None)
        raw.row_factory = aiosqlite.Row
        self.conn = Connection(raw)
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=FULL")
        await self.conn.execute("PRAGMA busy_timeout=10000")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(SCHEMA)
        async with self.transaction():
            for migration in MIGRATIONS:
                try:
                    await self.conn.execute(migration)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            columns = {r["name"] for r in await (await self.conn.execute("PRAGMA table_info(accounts)")).fetchall()}
            for field in ("cash_available", "cash_withdrawable", "cash_frozen"):
                if field + "_cents" not in columns:
                    await self.conn.execute(f"ALTER TABLE accounts ADD COLUMN {field}_cents INTEGER NOT NULL DEFAULT 0")
                    await self.conn.execute(f"UPDATE accounts SET {field}_cents=CAST(ROUND({field}*100) AS INTEGER)")
            trade_columns = {r["name"] for r in await (await self.conn.execute("PRAGMA table_info(trades)")).fetchall()}
            if "profit" not in trade_columns:
                await self.conn.execute("ALTER TABLE trades ADD COLUMN profit REAL NOT NULL DEFAULT 0")
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS cash_ledger (
              id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, operation_id TEXT,
              available_cents INTEGER NOT NULL, frozen_cents INTEGER NOT NULL,
              reason TEXT NOT NULL, ts INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_cash_ledger_user ON cash_ledger(user_id,id);
            CREATE TABLE IF NOT EXISTS business_operations (
              id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL, ts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
              id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, payload TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'pending', receipt TEXT, ts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS settlements (
              day_id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, state TEXT NOT NULL, ts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships (
              user_id TEXT NOT NULL, group_id TEXT NOT NULL, PRIMARY KEY(user_id,group_id));
            CREATE TABLE IF NOT EXISTS fee_effects (
              user_id TEXT PRIMARY KEY, discount REAL NOT NULL, remaining INTEGER NOT NULL);
        """)
        await self.conn.execute("INSERT INTO cash_ledger(user_id,available_cents,frozen_cents,reason,ts) SELECT user_id,cash_available_cents,cash_frozen_cents,'migration_opening',? FROM accounts a WHERE NOT EXISTS (SELECT 1 FROM cash_ledger l WHERE l.user_id=a.user_id)",(int(time.time()),))

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ── 事务边界 ───────────────────────────────────────────
    @property
    def in_transaction(self):
        return self._owner is asyncio.current_task()

    @asynccontextmanager
    async def transaction(self):
        async with self.conn.lock:
            if self.in_transaction:
                yield self
                return
            self._owner = asyncio.current_task()
            try:
                await self.conn.execute("BEGIN IMMEDIATE")
                yield self
                # Cancellation waits for commit or rollback before releasing ownership.
                task = asyncio.create_task(self.conn.raw.commit())
                # Once COMMIT starts, finish it even after repeated cancellation.
                # A committed operation must never restore pre-commit memory.
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                task.result()
            except BaseException:
                task = asyncio.create_task(self.conn.raw.rollback())
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                task.result()
                raise
            finally:
                self._owner = None

    async def _commit(self):
        # Standalone SQL is autocommit. Never commit somebody else's transaction.
        return

    # ── 账户 ──────────────────────────────────────────────
    async def get_account(self, user_id: str):
        cur = await self.conn.execute(
            "SELECT user_id,user_name,cash_available_cents/100.0 AS cash_available, cash_withdrawable_cents/100.0 AS cash_withdrawable,cash_frozen_cents/100.0 AS cash_frozen,initial_cash,status,rebirth_count,last_rebirth_ts,last_bankrupt_ts,created_ts FROM accounts WHERE user_id=?", (user_id,))
        return await cur.fetchone()

    async def create_account(self, user_id, user_name, cash, ts):
        amount = cents(cash)
        if amount < 0:
            raise ValueError("cash cannot be negative")
        await self.conn.execute(
            "INSERT INTO accounts(user_id,user_name,cash_available,cash_withdrawable,cash_frozen,initial_cash,created_ts,cash_available_cents,cash_withdrawable_cents,cash_frozen_cents) VALUES(?,?,?,?,0,?,?,?, ?,0)",
            (user_id, str(user_name)[:80], amount/100, amount/100, amount/100, ts, amount, amount))
        await self.conn.execute("INSERT INTO cash_ledger(user_id,operation_id,available_cents,frozen_cents,reason,ts) VALUES(?,?,?,0,'initial',?)",(user_id,self.operation_id,amount,ts))

    async def update_cash(self, user_id, available, withdrawable):
        acc = await self.get_account(user_id)
        await self.update_cash_full(user_id, available, withdrawable, acc["cash_frozen"])

    async def update_cash_full(self, user_id, available, withdrawable, frozen):
        av, wd, fr = cents(available), cents(withdrawable), cents(frozen)
        if min(av, wd, fr) < 0:
            raise ValueError("cash cannot be negative")
        wd = min(wd, av)
        async with self.transaction():
            old = await self.get_account(user_id)
            if not old:
                raise ValueError("account not found")
            await self.conn.execute(
                "UPDATE accounts SET cash_available=?,cash_withdrawable=?,cash_frozen=?,cash_available_cents=?,cash_withdrawable_cents=?,cash_frozen_cents=? WHERE user_id=?",
                (av/100,wd/100,fr/100,av,wd,fr,user_id))
            await self.conn.execute("INSERT INTO cash_ledger(user_id,operation_id,available_cents,frozen_cents,reason,ts) VALUES(?,?,?,?,'mutation',?)",(user_id,self.operation_id,av-cents(old["cash_available"]),fr-cents(old["cash_frozen"]),int(time.time())))

    async def set_status(self, user_id: str, status: str,
                         ts: int | None = None) -> None:
        if status == "bankrupt":
            await self.conn.execute(
                "UPDATE accounts SET status=?, last_bankrupt_ts=? WHERE user_id=?",
                (status, ts, user_id))
        else:
            await self.conn.execute(
                "UPDATE accounts SET status=? WHERE user_id=?", (status, user_id))
        await self._commit()

    async def do_rebirth(self, user_id: str, cash: float, ts: int) -> None:
        await self.update_cash_full(user_id, cash, cash, 0)
        await self.conn.execute(
            "UPDATE accounts SET status='active', cash_available=?, "
            "cash_withdrawable=?, cash_frozen=0, initial_cash=?, "
            "rebirth_count=rebirth_count+1, last_rebirth_ts=? WHERE user_id=?",
            (cash, cash, cash, ts, user_id))
        await self.conn.execute("INSERT INTO cash_ledger(user_id,available_cents,frozen_cents,reason,ts) VALUES(?,0,0,'rebirth_epoch',?)", (user_id, ts))
        await self.conn.execute("DELETE FROM positions WHERE user_id=?", (user_id,))
        await self.conn.execute(
            "UPDATE orders SET status='cancelled', frozen=0 WHERE user_id=? AND "
            "status IN ('open','partial')", (user_id,))
        await self._commit()

    async def list_accounts(self, is_npc: bool | None = None):
        """列出全部账户。

        is_npc 参数（P4 模拟股民警隔离，hang_analyst 核实结论）：
        - True  → 只返回 user_id 以 `npc:` 开头的 NPC 账户；
        - False → 只返回真实玩家账户（排行榜/统计口径用这个）；
        - None  → 全部（仅内部全表扫描用）。
        NPC 账户必须隔离在 accounts 表的统计口径之外，否则会污染
        开户数、破产统计与收益率榜。
        """
        if is_npc is True:
            sql = "SELECT * FROM accounts WHERE user_id LIKE 'npc:%'"
        elif is_npc is False:
            sql = "SELECT * FROM accounts WHERE user_id NOT LIKE 'npc:%'"
        else:
            sql = "SELECT * FROM accounts"
        cur = await self.conn.execute(sql)
        return await cur.fetchall()

    async def settle_withdrawable(self) -> None:
        """日终：可用资金全部转为可取。"""
        await self.conn.execute(
            "UPDATE accounts SET cash_withdrawable=cash_available, cash_withdrawable_cents=cash_available_cents")
        await self._commit()

    # ── 持仓 ──────────────────────────────────────────────
    async def get_position(self, user_id: str, code: str):
        cur = await self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND code=?", (user_id, code))
        return await cur.fetchone()

    async def get_positions(self, user_id: str):
        cur = await self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND quantity>0", (user_id,))
        return await cur.fetchall()

    async def upsert_position(self, user_id: str, code: str, quantity: int,
                              sellable: int, cost_price: float) -> None:
        if not 0 <= sellable <= quantity or not math.isfinite(cost_price) or cost_price < 0:
            raise ValueError("invalid position")
        await self.conn.execute(
            "INSERT INTO positions(user_id,code,quantity,sellable,cost_price) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id,code) DO UPDATE SET "
            "quantity=?, sellable=?, cost_price=?",
            (user_id, code, quantity, sellable, cost_price,
             quantity, sellable, cost_price))
        await self._commit()

    async def delete_position(self, user_id: str, code: str) -> None:
        await self.conn.execute(
            "DELETE FROM positions WHERE user_id=? AND code=?", (user_id, code))
        await self._commit()

    async def get_position_holders(self, code: str):
        """持有某只股票的所有账户（分红送股/退市清算用）。"""
        cur = await self.conn.execute(
            "SELECT * FROM positions WHERE code=? AND quantity>0", (code,))
        return await cur.fetchall()

    async def unlock_all_sellable(self) -> None:
        """日终 T+1 解锁：所有持仓全部可卖。"""
        await self.conn.execute("UPDATE positions SET sellable=quantity")
        await self._commit()

    # ── 委托 ──────────────────────────────────────────────
    async def insert_order(self, user_id: str, code: str, side: str,
                           price: float, quantity: int, ts: int,
                           phase: str = "continuous") -> int:
        if not math.isfinite(price) or price <= 0 or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("invalid order price or quantity")
        cur = await self.conn.execute(
            "INSERT INTO orders(user_id,code,side,price,quantity,status,phase,ts) "
            "VALUES(?,?,?,?,?,'open',?,?)",
            (user_id, code, side, price, quantity, phase, ts))
        await self._commit()
        return cur.lastrowid

    async def update_order(self, order_id: int, filled: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE orders SET filled=?, status=? WHERE order_id=?",
            (filled, status, order_id))
        await self._commit()

    async def update_order_frozen(self, order_id: int, frozen: float) -> None:
        if not math.isfinite(frozen) or frozen < -0.005:
            raise ValueError("negative order reserve")
        await self.conn.execute(
            "UPDATE orders SET frozen=? WHERE order_id=?",
            (money(max(frozen, 0.0)), order_id))
        await self._commit()

    async def get_order(self, order_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM orders WHERE order_id=?", (order_id,))
        return await cur.fetchone()

    async def get_user_open_orders(self, user_id: str):
        cur = await self.conn.execute(
            "SELECT * FROM orders WHERE user_id=? AND status IN ('open','partial') "
            "ORDER BY order_id DESC", (user_id,))
        return await cur.fetchall()

    async def get_all_open_orders(self):
        cur = await self.conn.execute(
            "SELECT * FROM orders WHERE status IN ('open','partial')")
        return await cur.fetchall()

    async def expire_open_orders(self) -> None:
        """日终：未成交委托全部过期（当日有效）。"""
        await self.conn.execute(
            "UPDATE orders SET status='expired', frozen=0 "
            "WHERE status IN ('open','partial')")
        await self._commit()

    async def get_book_orders(self, code: str, side: str):
        """取某股票某方向所有未成交玩家委托，用于重启恢复与盘口展示。"""
        cur = await self.conn.execute(
            "SELECT * FROM orders WHERE code=? AND side=? AND "
            "status IN ('open','partial')", (code, side))
        return await cur.fetchall()

    # ── 价格 ──────────────────────────────────────────────
    async def upsert_price(self, code: str, price: float, prev_close: float,
                           open_: float, high: float, low: float,
                           volume: int) -> None:
        await self.conn.execute(
            "INSERT INTO prices(code,price,prev_close,open,high,low,volume) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET "
            "price=?, prev_close=?, open=?, high=?, low=?, volume=?",
            (code, price, prev_close, open_, high, low, volume,
             price, prev_close, open_, high, low, volume))

    async def commit_prices(self) -> None:
        await self._commit()

    async def day_close_prices(self) -> None:
        """日终：收盘价转为昨收，重置日内数据。"""
        await self.conn.execute(
            "UPDATE prices SET prev_close=price, open=price, high=price, "
            "low=price, volume=0")
        await self._commit()

    async def get_price(self, code: str):
        cur = await self.conn.execute(
            "SELECT * FROM prices WHERE code=?", (code,))
        return await cur.fetchone()

    async def get_all_prices(self):
        cur = await self.conn.execute("SELECT * FROM prices")
        return await cur.fetchall()

    # ── 成交流水（对账用）────────────────────────────────
    async def insert_trade(self, order_id: int | None, user_id: str, code: str,
                           side: str, price: float, quantity: int, fee: float,
                           ts: int, profit: float = 0.0) -> None:
        await self.conn.execute(
            "INSERT INTO trades(order_id,user_id,code,side,price,quantity,fee,ts,profit) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (order_id, user_id, code, side, price, quantity, money(fee), ts, money(profit)))
        await self._commit()

    async def get_user_trades(self, user_id: str, limit: int = 10):
        cur = await self.conn.execute(
            "SELECT * FROM trades WHERE user_id=? ORDER BY trade_id DESC LIMIT ?",
            (user_id, limit))
        return await cur.fetchall()

    async def stats(self) -> dict:
        """运行统计（心跳 / 状态指令用）。用列别名取值，兼容不同驱动。

        NPC 账户（user_id 以 `npc:` 开头）不计入 accounts/active/bankrupt
        —— 那是模拟股民警的虚拟账户，混进统计会虚增开户数与破产数。
        """
        async def one(sql: str) -> int:
            cur = await self.conn.execute(sql)
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

        npc_filter = "WHERE user_id NOT LIKE 'npc:%'"
        return {
            "accounts": await one(f"SELECT COUNT(*) AS n FROM accounts {npc_filter}"),
            "active": await one(
                f"SELECT COUNT(*) AS n FROM accounts {npc_filter} AND status='active'"),
            "bankrupt": await one(
                f"SELECT COUNT(*) AS n FROM accounts {npc_filter} AND status='bankrupt'"),
            "positions": await one("SELECT COUNT(*) AS n FROM positions"),
            "open_orders": await one(
                "SELECT COUNT(*) AS n FROM orders WHERE status IN ('open','partial')"),
            "trades": await one("SELECT COUNT(*) AS n FROM trades"),
            "frozen_total": await one(
                f"SELECT COALESCE(SUM(cash_frozen),0) AS n FROM accounts {npc_filter}"),
        }

    # ── K 线 ──────────────────────────────────────────────
    async def insert_candles(self, rows) -> None:
        """rows: (code, period, ts, open, high, low, close, volume) 列表。"""
        if not rows:
            return
        await self.conn.executemany(
            "INSERT INTO candles(code,period,ts,open,high,low,close,volume) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code,period,ts) DO NOTHING",
            rows)
        await self._commit()

    async def get_candles(self, code: str, period: str = "1d", limit: int = 30):
        """最近 limit 根 K 线（按时间升序返回）。"""
        cur = await self.conn.execute(
            "SELECT * FROM candles WHERE code=? AND period=? "
            "ORDER BY ts DESC LIMIT ?", (code, period, limit))
        rows = await cur.fetchall()
        return list(reversed(rows))

    async def overview_candles(self, limit: int = 21):
        """One bounded batch: newest completed daily closes per stock, ascending."""
        rows = await (await self.conn.execute(
            "SELECT code,ts,open,high,low,close FROM (SELECT code,ts,open,high,low,close,"
            "ROW_NUMBER() OVER (PARTITION BY code ORDER BY ts DESC) AS n "
            "FROM candles WHERE period='1d') WHERE n<=? ORDER BY code,ts", (limit,))).fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row['code'], []).append(dict(row))
        return grouped

    # ── 新闻 ──────────────────────────────────────────────
    async def insert_news(self, ts: int, scope: str, target: str, kind: str,
                          headline: str, impact: float) -> None:
        await self.conn.execute(
            "INSERT INTO news(ts,scope,target,kind,headline,impact) "
            "VALUES(?,?,?,?,?,?)",
            (ts, scope, target, kind, headline, round(impact, 6)))
        await self._commit()

    async def get_news_since(self, ts: int, limit: int = 50):
        cur = await self.conn.execute(
            "SELECT * FROM news WHERE ts>=? ORDER BY news_id DESC LIMIT ?",
            (ts, limit))
        return await cur.fetchall()

    async def query_causal_news(self, codes, limit):
        # Filter on exact PUBLIC targets before LIMIT, never hidden event state/headlines.
        where = ""
        args = []
        if codes is not None:
            where = ("WHERE EXISTS (SELECT 1 FROM json_each(causal_news.payload,'$.targets') t "
                     "JOIN json_each(?) s ON t.value=s.value) ")
            args.append(json.dumps(codes))
        args.append(limit)
        rows = await (await self.conn.execute(
            "SELECT payload FROM causal_news " + where + "ORDER BY seq DESC LIMIT ?", args)).fetchall()
        return [json.loads(r['payload']) for r in rows]

    async def query_legacy_news(self, since, scope, limit):
        where = "ts>=?"
        args = [since]
        if scope['filtered']:
            where += (" AND ((scope='stock' AND target IN (SELECT value FROM json_each(?)))"
                      " OR (scope='sector' AND target IN (SELECT value FROM json_each(?))))")
            args.extend((json.dumps(scope['codes']), json.dumps(scope['sectors'])))
        args.append(limit)
        rows = await (await self.conn.execute(
            "SELECT * FROM news WHERE " + where + " ORDER BY news_id DESC LIMIT ?", args)).fetchall()
        return [dict(r) for r in rows]

    # ── 元数据 ────────────────────────────────────────────
    async def get_meta(self, key: str) -> str | None:
        cur = await self.conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None

    async def set_meta(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=?",
            (key, value, value))
        await self._commit()

    # ── 每日自动备份（DESIGN.md §16）────────────────────────
    def backup_path(self) -> str:
        """备份文件路径：<库路径>.bak（sharemarket.db → sharemarket.db.bak）。"""
        return self.path + ".bak"

    async def backup(self) -> str:
        """把当前库一致性快照写到 <path>.bak，返回备份路径。

        VACUUM INTO 生成一致性快照（含未落盘数据的已提交状态）到 .bak.tmp，
        再 os.replace 原子替换 .bak：中途失败时旧 .bak 仍然可用，不会留下
        半截备份。VACUUM INTO 要求目标文件不存在，故先清残留 tmp。
        不能在 transaction() 内调用（VACUUM 不能跑在事务里）。
        """
        if self.in_transaction:
            raise ValueError("backup cannot run inside a transaction")
        from ..locks import trade_lock
        async with trade_lock(), self.conn.lock:
            target = self.backup_path()
            tmp = target + ".tmp"
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                await self.conn.execute("VACUUM INTO ?", (tmp,))
                os.chmod(tmp, 0o600)
                os.replace(tmp, target)
                return target
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    async def maybe_daily_backup(self) -> bool:
        """每日自动备份入口：每个自然日第一次调用执行备份，同日重复 no-op。

        _backup_day 是进程内缓存，把每 tick 一次的调用挡成纯字符串比较；
        跨重启判重靠 meta['backup_last_date']（今天已备过则只补缓存）。
        失败不写缓存也不写 meta，下次调用自动重试（失败日志去重由调用方负责）。
        """
        from ..game.clock import TZ
        from datetime import datetime
        today = datetime.now(TZ).date().isoformat()
        if self._backup_day == today:
            return False
        if await self.get_meta("backup_last_date") == today:
            self._backup_day = today
            return False
        await self.backup()
        await self.set_meta("backup_last_date", today)
        self._backup_day = today
        return True

    # ── 自选股 ──────────────────────────────────────────────
    async def watchlist_add(self, user_id: str, code: str, ts: int) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO watchlist(user_id,code,created_ts) "
            "VALUES(?,?,?)",
            (user_id, code, ts))
        await self._commit()

    async def watchlist_remove(self, user_id: str, code: str) -> None:
        await self.conn.execute(
            "DELETE FROM watchlist WHERE user_id=? AND code=?",
            (user_id, code))
        await self._commit()

    async def watchlist_list(self, user_id: str) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM watchlist WHERE user_id=? ORDER BY created_ts",
            (user_id,))
        rows = await cur.fetchall()
        # 离线测试的 shim 返回 dict 子类（见 .dsh-code/sim_test.py:32）；
        # 真实 aiosqlite 返回 sqlite3.Row，dict(row) 同样适用。
        return [dict(r) for r in rows]

    async def watchlist_contains(self, user_id: str, code: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM watchlist WHERE user_id=? AND code=?",
            (user_id, code))
        return await cur.fetchone() is not None

    # ── 排行榜快照 ──────────────────────────────────────────
    async def insert_leaderboard_snapshot(self, day_ts: int, rank: int,
                                         user_id: str, user_name: str,
                                         total: float, cash: float, mv: float,
                                         return_pct: float, status: str,
                                         rebirth_count: int) -> None:
        """一日一行（幂等：同日同 rank 重跑覆盖，不重复记）。

        rank 是当日名次，与 (day_ts, rank) 一起构成主键。
        """
        await self.conn.execute(
            "INSERT OR REPLACE INTO leaderboard_snapshots"
            "(day_ts,rank,user_id,user_name,total,cash,mv,return_pct,"
            "status,rebirth_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (day_ts, rank, user_id, user_name, round(total, 2), round(cash, 2),
             round(mv, 2), round(return_pct, 4), status, int(rebirth_count)))
        await self._commit()

    async def list_leaderboard_snapshots(self, limit_days: int = 14) -> list[dict]:
        """最近 limit_days 个交易日的全部快照（按 day_ts DESC, rank）。"""
        cur = await self.conn.execute(
            "SELECT * FROM leaderboard_snapshots "
            "WHERE day_ts IN (SELECT DISTINCT day_ts FROM leaderboard_snapshots "
            "ORDER BY day_ts DESC LIMIT ?) ORDER BY day_ts DESC, rank",
            (limit_days,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def latest_snapshot_day(self) -> int | None:
        cur = await self.conn.execute(
            "SELECT MAX(day_ts) AS m FROM leaderboard_snapshots")
        row = await cur.fetchone()
        return row["m"] if row else None

    # ── 玩家自发行股票 ──────────────────────────────────────
    async def insert_player_ipo(self, issuer: str, code: str, name: str,
                                price: float, total_shares: int,
                                lot_size: int = 100) -> None:
        """登记一笔玩家自发行（幂等：同 issuer+code 覆盖）。

        C2 防线：price/total_shares 必须为有限正数（NaN 的 <=0 比较为
        False，会穿过朴素的负值检查，故先过 isfinite）。
        """
        price = float(price)
        total_shares = int(total_shares)
        lot_size = int(lot_size)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("player ipo price must be a positive number")
        if not math.isfinite(float(total_shares)) or total_shares <= 0:
            raise ValueError("player ipo total_shares must be a positive integer")
        if lot_size <= 0:
            raise ValueError("player ipo lot_size must be positive")
        await self.conn.execute(
            "INSERT OR REPLACE INTO player_ipos"
            "(issuer,code,name,price,total_shares,lot_size,created_ts) "
            "VALUES(?,?,?,?,?,?,?)",
            (issuer, code, name, round(price, 2), total_shares, lot_size,
             int(time.time())))
        await self._commit()

    async def get_player_ipo(self, issuer: str, code: str) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM player_ipos WHERE issuer=? AND code=?", (issuer, code))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_player_ipos(self, issuer: str) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM player_ipos WHERE issuer=? "
            "ORDER BY created_ts DESC, code", (issuer,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_player_ipo_status(self, issuer: str, code: str,
                                       status: str) -> None:
        await self.conn.execute(
            "UPDATE player_ipos SET status=? WHERE issuer=? AND code=?",
            (status, issuer, code))
        await self._commit()


    async def grant_cash(self, user_id, amount, reason="reward"):
        async with self.transaction():
            acc = await self.get_account(user_id)
            await self.update_cash_full(user_id, money(acc["cash_available"]+amount), money(acc["cash_withdrawable"]+amount), acc["cash_frozen"])
            await self.conn.execute("UPDATE cash_ledger SET reason=? WHERE id=(SELECT MAX(id) FROM cash_ledger WHERE user_id=?)", (reason,user_id))

    async def upsert_prices(self, rows):
        await self.conn.executemany("INSERT INTO prices(code,price,prev_close,open,high,low,volume) VALUES(?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET price=excluded.price,prev_close=excluded.prev_close,open=excluded.open,high=excluded.high,low=excluded.low,volume=excluded.volume",rows)

    async def audit(self,strict_reserves=False):
        errors=[];warnings=[];reserves={}
        ipo_raw=await self.get_meta('ipo.ledger.v1')
        if ipo_raw:
            ledger=json.loads(ipo_raw)
            for sub in ledger['subs'].values():
                if sub['state']!='settled':reserves[sub['user_id']]=reserves.get(sub['user_id'],0)+cents(sub['amount'])
            for ipo in ledger['ipos'].values():
                if ipo.get('issuer') and not ipo.get('reserve_released'):
                    uid=ipo['issuer'];reserves[uid]=reserves.get(uid,0)+cents(ipo.get('reserve',0))
        for acc in await self.list_accounts():
            uid=acc["user_id"]
            if min(acc["cash_available_cents"],acc["cash_frozen_cents"],acc["cash_withdrawable_cents"])<0:
                errors.append({"user_id":uid,"error":"negative_balance"})
            if acc['cash_withdrawable_cents']>acc['cash_available_cents']:
                errors.append({'user_id':uid,'error':'withdrawable_exceeds_available'})
            row=await (await self.conn.execute("SELECT COALESCE(SUM(available_cents),0) av,COALESCE(SUM(frozen_cents),0) fr FROM cash_ledger WHERE user_id=?",(uid,))).fetchone()
            if (row["av"],row["fr"])!=(acc["cash_available_cents"],acc["cash_frozen_cents"]):
                errors.append({"user_id":uid,"error":"cash_ledger_mismatch"})
            held=await (await self.conn.execute("SELECT COALESCE(SUM(frozen),0) held FROM orders WHERE user_id=? AND status IN ('open','partial')",(uid,))).fetchone()
            expected=cents(held['held'])+reserves.get(uid,0)
            if expected!=acc['cash_frozen_cents']:
                (errors if strict_reserves or expected>acc['cash_frozen_cents'] else warnings).append({'user_id':uid,'error':'frozen_reserve_mismatch','expected_cents':expected,'actual_cents':acc['cash_frozen_cents']})
        positions=await (await self.conn.execute("SELECT user_id,code FROM positions WHERE quantity<0 OR sellable<0 OR sellable>quantity")).fetchall()
        errors.extend({"user_id":p["user_id"],"code":p["code"],"error":"invalid_position"} for p in positions)
        return {"ok":not errors,"errors":errors,"warnings":warnings}

    async def retain(self, days=90):
        cutoff=int(time.time())-max(7,days)*86400
        async with self.transaction():
            await self.conn.execute("DELETE FROM news WHERE ts<?",(cutoff,))
            if await (await self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='causal_news'")).fetchone():
                await self.conn.execute("DELETE FROM causal_news WHERE published<?",(cutoff,))
            await self.conn.execute("DELETE FROM candles WHERE ts<?",(cutoff,))
            await self.conn.execute("DELETE FROM outbox WHERE state='accepted' AND ts<?",(cutoff,))
            # Operation IDs and cash/trade journals are retained: removing them can
            # turn old platform redeliveries into new trades or break reconciliation.
