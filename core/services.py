"""Posting services for treasury-side documents: expense vouchers + fixed-asset
purchases. Each posting creates a balanced JournalEntry atomically.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .account_codes import get_system_account
from .models import Account, JournalEntry, JournalLine


class CorePostingError(Exception):
    """Business-rule failure surfaced to the user during a core posting."""


def _q(v):
    return Decimal(v).quantize(Decimal('0.01'))


# ============================================================
#  Expense voucher
# ============================================================

@transaction.atomic
def post_expense_voucher(voucher, user=None):
    """Post an expense voucher:  DR expense category / CR cash account."""
    if voucher.status != 'DRAFT':
        raise CorePostingError(f'سند الصرف {voucher.voucher_no} حالته '
                               f'{voucher.get_status_display()}، مش مسودة.')
    if Decimal(voucher.amount) <= 0:
        raise CorePostingError('المبلغ لازم يكون أكبر من صفر.')
    if not voucher.cash_account_id:
        raise CorePostingError('لازم تختار حساب الدفع (نقدية/بنك/محفظة).')

    amount = _q(voucher.amount)
    je = JournalEntry.objects.create(
        date=voucher.date,
        reference=voucher.voucher_no,
        description=f'مصروف — {voucher.category.name_ar}'
                    + (f' ({voucher.description})' if voucher.description else ''),
        status='POSTED',
        source_doc_type='ExpenseVoucher',
        source_doc_id=voucher.id,
        created_by=user,
    )
    JournalLine.objects.create(
        entry=je, account=voucher.category.gl_account,
        debit=amount, credit=Decimal('0'),
        description=voucher.description or voucher.category.name_ar,
    )
    JournalLine.objects.create(
        entry=je, account=voucher.cash_account.gl_account,
        debit=Decimal('0'), credit=amount,
        description=f'صرف من {voucher.cash_account.name}',
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'expense JE unbalanced'

    voucher.status = 'POSTED'
    voucher.journal_entry = je
    voucher.save(update_fields=['status', 'journal_entry'])
    return je


@transaction.atomic
def cancel_expense_voucher(voucher, user=None):
    if voucher.status != 'POSTED':
        raise CorePostingError('لا يمكن إلغاء سند غير مرحّل.')
    orig = voucher.journal_entry
    rev = JournalEntry.objects.create(
        date=timezone.now().date(),
        reference=f'CANCEL-{voucher.voucher_no}',
        description=f'إلغاء سند صرف {voucher.voucher_no}',
        status='POSTED',
        source_doc_type='ExpenseVoucher.Cancel',
        source_doc_id=voucher.id,
        created_by=user,
    )
    if orig:
        for line in orig.lines.all():
            JournalLine.objects.create(
                entry=rev, account=line.account,
                debit=line.credit, credit=line.debit,
                description=f'إلغاء — {line.description}',
            )
    rev.recalc_totals()
    voucher.status = 'CANCELLED'
    voucher.save(update_fields=['status'])
    return rev


# ============================================================
#  Fixed-asset purchase
# ============================================================

@transaction.atomic
def post_fixed_asset(asset, user=None):
    """Post a fixed-asset purchase: DR fixed-asset GL / CR cash or AP(supplier)."""
    if asset.status != 'DRAFT':
        raise CorePostingError(f'الأصل {asset.asset_no} حالته '
                               f'{asset.get_status_display()}، مش مسودة.')
    if Decimal(asset.cost) <= 0:
        raise CorePostingError('تكلفة الأصل لازم تكون أكبر من صفر.')

    if asset.payment_method == 'CASH':
        if not asset.cash_account_id:
            raise CorePostingError('اختار حساب الدفع (نقدية/بنك/محفظة) للأصل المدفوع.')
        credit_account = asset.cash_account.gl_account
        credit_supplier = None
        credit_desc = f'دفع من {asset.cash_account.name}'
    else:  # CREDIT
        if not asset.supplier_id:
            raise CorePostingError('اختار المورد للأصل المشترى آجلاً.')
        credit_account = get_system_account('AP')
        credit_supplier = asset.supplier
        credit_desc = f'شراء آجل من {asset.supplier.name}'

    cost = _q(asset.cost)
    asset_acct = Account.objects.get(code=asset.gl_code)

    je = JournalEntry.objects.create(
        date=asset.acquisition_date,
        reference=asset.asset_no,
        description=f'شراء أصل ثابت — {asset.name}',
        status='POSTED',
        source_doc_type='FixedAsset',
        source_doc_id=asset.id,
        created_by=user,
    )
    JournalLine.objects.create(
        entry=je, account=asset_acct,
        debit=cost, credit=Decimal('0'),
        description=f'{asset.name} ({asset.get_category_display()})',
    )
    JournalLine.objects.create(
        entry=je, account=credit_account,
        debit=Decimal('0'), credit=cost,
        description=credit_desc,
        supplier=credit_supplier,
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'fixed-asset JE unbalanced'

    asset.status = 'POSTED'
    asset.journal_entry = je
    asset.save(update_fields=['status', 'journal_entry'])
    return je
