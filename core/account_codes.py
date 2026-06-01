"""System-account-code lookup for posting logic.

Posting code (sales services, receipts, adjustments) MUST reference accounts via
the symbolic keys defined here rather than hardcoding numeric codes throughout
the codebase.  If you re-chart the COA, change the value here in one place.
"""
from django.core.exceptions import ObjectDoesNotExist

# Symbolic key → code in the seeded COA. Keep in sync with `seed_coa.py`.
SYSTEM_ACCOUNTS = {
    'CASH':            '1110000',
    'BANK':            '1120000',
    'AR':              '1210000',
    'INVENTORY':       '1310000',
    'WIP':              '1320000',  # إنتاج تحت التشغيل (Work In Progress)
    'FABRIC_INVENTORY': '1330000',  # مخزون الأقمشة (manufacturing — raw material)
    'ACCESSORY_INVENTORY': '1340000',  # مخزون الإكسسوارات
    'VAT_INPUT':       '1420000',
    'AP':              '2110000',
    'VAT_OUTPUT':      '2210000',
    'WHT_PAYABLE':     '2310000',
    'MFG_WAGES_ACCRUED': '2320000',  # مصنعيات مستحقة (labor capitalized into inventory, not yet paid)
    'CAPITAL':         '3110000',
    'PARTNER_CURRENT': '3120000',
    'OPENING_EQUITY':  '3310000',
    'SALES_REVENUE':   '4110000',
    'SALES_RETURNS':   '4120000',
    'COGS':            '5110000',
    'INVENTORY_LOSS':  '5210000',
    'INVENTORY_GAIN':  '5220000',
    'MFG_WAGES_EXPENSE': '5370000',  # فرق مصنعيات (over-spend above accrued wages)
}


def get_system_account(key):
    """Look up an Account by its symbolic key.  Raises a clear error if missing."""
    from core.models import Account  # local import to avoid app-loading order issues
    try:
        code = SYSTEM_ACCOUNTS[key]
    except KeyError:
        raise ValueError(f'Unknown system account key: {key!r}. '
                          f'Available: {sorted(SYSTEM_ACCOUNTS)}')
    try:
        return Account.objects.get(code=code)
    except ObjectDoesNotExist:
        raise RuntimeError(
            f'Account code {code} ({key}) is not in the database. '
            f'Run: python manage.py seed_coa'
        )
