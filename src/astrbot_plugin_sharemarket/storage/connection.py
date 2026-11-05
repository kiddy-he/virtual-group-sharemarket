"""No task can execute or commit on a connection owned by another transaction.

Autocommit handles standalone SQL. Multi-statement business writes always use
Database.transaction. A cursor eagerly buffers rows under the same lock so a
SELECT never leaks a transaction-owned cursor to an unrelated task.
"""
from ..locks import TaskLock

class Rows:
    def __init__(self, rows, cursor):
        self.rows = iter(rows)
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
    async def fetchone(self):
        return next(self.rows, None)
    async def fetchall(self):
        return list(self.rows)

class Connection:
    def __init__(self, raw):
        self.raw = raw
        self.lock = TaskLock()
    async def execute(self, sql, parameters=()):
        async with self.lock:
            cursor = await self.raw.execute(sql, parameters)
            rows = await cursor.fetchall() if cursor.description else []
            result = Rows(rows, cursor)
            await cursor.close()
            return result
    async def executemany(self, sql, parameters):
        async with self.lock:
            cursor = await self.raw.executemany(sql, parameters)
            result = Rows([], cursor)
            await cursor.close()
            return result
    async def executescript(self, sql):
        async with self.lock:
            return await self.raw.executescript(sql)
    async def commit(self):
        async with self.lock:
            await self.raw.commit()
    async def rollback(self):
        async with self.lock:
            await self.raw.rollback()
    async def close(self):
        async with self.lock:
            await self.raw.close()
