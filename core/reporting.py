"""Shared accounting-report helpers used by Trial Balance, P&L, and Balance Sheet."""
from decimal import Decimal
from django.db.models import Sum


def _sum(qs):
    agg = qs.aggregate(d=Sum('debit'), c=Sum('credit'))
    return (agg['d'] or Decimal('0')), (agg['c'] or Decimal('0'))


def account_balance_as_of(account, as_of_date=None, status='POSTED'):
    """Net (debit - credit) balance on `account` through the end of `as_of_date`."""
    from core.models import JournalLine
    qs = JournalLine.objects.filter(account=account, entry__status=status)
    if as_of_date is not None:
        qs = qs.filter(entry__date__lte=as_of_date)
    d, c = _sum(qs)
    return d - c


def account_balance_in_period(account, date_from, date_to, status='POSTED'):
    """Net (debit - credit) on `account` for entries dated in [date_from, date_to]."""
    from core.models import JournalLine
    qs = JournalLine.objects.filter(
        account=account, entry__status=status,
        entry__date__gte=date_from, entry__date__lte=date_to,
    )
    d, c = _sum(qs)
    return d - c


def all_account_balances_as_of(as_of_date=None, status='POSTED'):
    """Returns {account_id: (debit_total, credit_total)} for all leaf accounts
    that have at least one journal line up to as_of_date. One DB hit, not N+1.
    """
    from core.models import JournalLine
    qs = JournalLine.objects.filter(entry__status=status)
    if as_of_date is not None:
        qs = qs.filter(entry__date__lte=as_of_date)
    rows = (qs.values('account_id')
              .annotate(d=Sum('debit'), c=Sum('credit')))
    return {r['account_id']: (r['d'] or Decimal('0'), r['c'] or Decimal('0'))
            for r in rows}


def all_account_balances_in_period(date_from, date_to, status='POSTED'):
    from core.models import JournalLine
    rows = (JournalLine.objects
            .filter(entry__status=status,
                    entry__date__gte=date_from, entry__date__lte=date_to)
            .values('account_id')
            .annotate(d=Sum('debit'), c=Sum('credit')))
    return {r['account_id']: (r['d'] or Decimal('0'), r['c'] or Decimal('0'))
            for r in rows}


# ---------- presentation helpers --------------------------------------------

# Sign rules: assets/expenses are debit-positive; liabilities/equity/revenue are credit-positive.
NATURAL_SIDE = {
    'ASSET':     'debit',
    'EXPENSE':   'debit',
    'LIABILITY': 'credit',
    'EQUITY':    'credit',
    'REVENUE':   'credit',
}


def natural_balance(account, d, c):
    """Convert a raw (d, c) pair into a single signed amount in the account's natural side."""
    if NATURAL_SIDE[account.account_type] == 'debit':
        return d - c
    return c - d
