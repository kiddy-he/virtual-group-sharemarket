"""Money is persisted in integer cents; float values are compatibility projections."""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import math

def cents(value):
    if isinstance(value, bool):
        raise ValueError('amount must be a finite number')
    try:number = Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise ValueError('amount must be a finite number')
    if not number.is_finite() or abs(number)>Decimal('90000000000000000'):
        raise ValueError('amount must be a finite number')
    return int((number * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def money(value):
    return cents(value) / 100

def positive_int(value, name='quantity', maximum=1_000_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ValueError(f'{name} must be an integer in 1..{maximum}')
    return value
