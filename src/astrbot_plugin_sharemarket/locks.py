"""Task-owned reentrant locks; separate market processes own separate locks."""
from __future__ import annotations
import asyncio

class TaskLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.owner = None
        self.depth = 0

    async def __aenter__(self):
        task = asyncio.current_task()
        if self.owner is task:
            self.depth += 1
            return self
        await self._lock.acquire()
        self.owner, self.depth = task, 1
        return self

    async def __aexit__(self, *exc):
        if self.owner is not asyncio.current_task():
            raise RuntimeError('lock released by another task')
        self.depth -= 1
        if not self.depth:
            self.owner = None
            self._lock.release()

from weakref import WeakKeyDictionary
_locks = WeakKeyDictionary()

def trade_lock():
    loop=asyncio.get_running_loop()
    if loop not in _locks:_locks[loop]=TaskLock()
    return _locks[loop]
