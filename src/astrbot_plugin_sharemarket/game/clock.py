"""Natural-day keys (Asia/Shanghai), independent from virtual trading days."""
from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo('Asia/Shanghai')
def day_key(ts=None):
    dt = datetime.fromtimestamp(ts, TZ) if ts is not None else datetime.now(TZ)
    return int(dt.replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
