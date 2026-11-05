"""One business mutation owns the market lock, SQL transaction and memory undo.

A rollback restores the snapshot before releasing the lock; a process crash is
recovered from the durable runtime checkpoint. No task-local flag alone is used
as database isolation.
"""
from contextlib import asynccontextmanager
from functools import wraps
import copy
from ..locks import trade_lock

@asynccontextmanager
async def mutation(db):
    async with trade_lock():
        outer = db.in_transaction
        snapshots = []
        if not outer:
            for obj, fields in db.memory_objects:
                snapshots.append((obj, {k: copy.deepcopy(getattr(obj, k)) for k in fields}))
        try:
            async with db.transaction():
                yield
                if not outer and db.checkpoint is not None:
                    await db.checkpoint()
        except BaseException:
            if not outer:
                for obj, state in snapshots:
                    for key, value in state.items():
                        current = getattr(obj,key)
                        if isinstance(current,dict) and isinstance(value,dict):
                            current.clear(); current.update(value)
                        elif isinstance(current,set) and isinstance(value,set):
                            current.clear(); current.update(value)
                        else:
                            setattr(obj, key, value)
            raise

def atomic(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with mutation(self.db):
            return await method(self, *args, **kwargs)
    return wrapped
