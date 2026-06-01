"""Money/number formatting filters: comma ',' thousands separator and a dot '.'
decimal separator (e.g. 5,500.00), regardless of the active locale.
Use `{{ value|money }}` (2dp) or `{{ value|money:0 }}` (0dp).
Loaded as a built-in template filter via TEMPLATES.OPTIONS.builtins.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def fmt_money(value, decimals=2):
    """Number string with ',' thousands separator and '.' decimal separator.

    Reusable from plain Python (e.g. admin list_display methods) so columns
    match the templates' `money` filter. Returns '' for blank/None.
    """
    if value is None or value == '':
        return ''
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    try:
        decimals = int(decimals)
    except (ValueError, TypeError):
        decimals = 2
    fmt = f'{{:,.{decimals}f}}' if decimals > 0 else '{:,.0f}'
    return fmt.format(d)  # Python default: ',' thousands, '.' decimal


@register.filter(name='money')
def money(value, decimals=2):
    """Format a number with ',' thousands separator and '.' decimal separator.

    Examples:
        {{ 1234.5|money }}      → 1,234.50
        {{ 1234.5|money:0 }}    → 1,235
        {{ 1234567|money:0 }}   → 1,234,567
        {{ None|money }}        → '' (blank)
    """
    return fmt_money(value, decimals)
