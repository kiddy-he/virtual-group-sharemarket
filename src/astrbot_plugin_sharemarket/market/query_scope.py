"""Resolve public query ranges from the stock catalogue, never private model state."""
from .stocks import STOCK_POOL, Stock


class QueryScopeError(ValueError):
    """Expected public range errors; the socket must not expose arbitrary exceptions."""
    def __init__(self, message, code='market_scope_not_found'):
        super().__init__(message)
        self.public_error = {'code': code, 'message': str(message)[:400]}


def public_catalogue():
    return {'version': 1, 'stocks': [{key: getattr(stock, key) for key in
            ('code', 'short_code', 'name', 'sector', 'industry')}
            for stock in sorted(STOCK_POOL.values(), key=lambda stock: stock.code)]}


def _unique(value, values, label):
    value = str(value or '').strip()
    exact = [v for v in values if v.casefold() == value.casefold()]
    matches = exact or [v for v in values if value and value.casefold() in v.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise QueryScopeError(f'{label}“{value}”不明确，可选：' + '、'.join(sorted(matches)[:8]), 'market_scope_ambiguous')
    raise QueryScopeError(f'未找到{label}“{value}”，请提供有效名称或先搜索股票。')


def _stock(value):
    value = str(value or '').strip()
    stock = Stock.lookup(value.upper())
    if stock:
        return stock.code
    names = {s.name: s.code for s in STOCK_POOL.values()}
    return names[_unique(value, names, '股票')]


def resolve_scope(params):
    """All supplied filters intersect; an invalid filter must never broaden a query."""
    sectors = {s.sector for s in STOCK_POOL.values()}
    industries = {s.industry for s in STOCK_POOL.values()}
    filters = {}
    for key, values, label in (('sector', sectors, '板块'), ('industry', industries, '行业')):
        if key in params:
            filters[key] = _unique(params[key], values, label)
    if 'code' in params:
        filters['code'] = _stock(params['code'])
    if 'keyword' in params:
        word = str(params['keyword'] or '').strip()
        # Exact catalogue identifiers win over partial stock/industry matches.
        exact = []
        if word in sectors: exact.append(('sector', word))
        if word in industries: exact.append(('industry', word))
        stock = Stock.lookup(word.upper())
        named = [s for s in STOCK_POOL.values() if s.name.casefold() == word.casefold()]
        if stock: exact.append(('code', stock.code))
        else: exact.extend(('code', s.code) for s in named)
        candidates = exact or (
            [('sector', v) for v in sectors if word and word in v] +
            [('industry', v) for v in industries if word and word in v] +
            [('code', s.code) for s in STOCK_POOL.values() if word and word.casefold() in s.name.casefold()])
        if not candidates:
            raise QueryScopeError(f'未找到查询范围“{word}”，请提供板块、行业、股票名称或代码。')
        if len(candidates) != 1:
            raise QueryScopeError(f'查询范围“{word}”不明确，请指定板块、行业或准确股票名称/代码。', 'market_scope_ambiguous')
        key, value = candidates[0]
        if key in filters and filters[key] != value:
            raise QueryScopeError('查询范围相互冲突，请检查筛选条件。', 'market_scope_conflict')
        filters[key] = value
    selected = sorted((s for s in STOCK_POOL.values()
                       if all(getattr(s, key) == value for key, value in filters.items())),
                      key=lambda s: (s.sector, s.code))
    if filters and not selected:
        raise QueryScopeError('筛选条件没有共同匹配的股票，请检查板块、行业与股票是否一致。', 'market_scope_conflict')
    parts = []
    if filters.get('sector'): parts.append(filters['sector'] + '板块')
    if filters.get('industry'): parts.append(filters['industry'] + '行业')
    if filters.get('code'):
        s = STOCK_POOL[filters['code']]
        parts.append(f'{s.name}({s.code})')
    return {'filtered': bool(filters), 'label': ' · '.join(parts) or '全市场',
            'filters': filters, 'codes': [s.code for s in selected],
            'sectors': sorted({s.sector for s in selected})}
