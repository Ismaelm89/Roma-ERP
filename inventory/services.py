"""Inventory posting services.  Inbound non-purchase movements create both a
StockMovement and a balanced JournalEntry in one atomic transaction.

| Movement type      | Debit              | Credit                 |
|--------------------|--------------------|------------------------|
| OPENING            | Inventory          | Opening Balance Equity |
| ADJUST_IN          | Inventory          | Inventory Gain         |
| ADJUST_OUT         | Inventory Loss     | Inventory              |
| WASTE              | Inventory Loss     | Inventory              |

Sales-side movements (SALES_OUT, SALES_RETURN_IN) are still posted by
`sales/services.py:post_sales_invoice` / `cancel_sales_invoice`.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from core.account_codes import get_system_account
from core.models import JournalEntry, JournalLine
from .models import StockMovement


def _q(v):
    return Decimal(v).quantize(Decimal('0.01'))


@transaction.atomic
def post_opening_balance(variant, quantity, unit_cost, date=None, user=None, notes=''):
    """Record an opening stock balance for a variant.

    Idempotent guard at the caller side — this function always creates a NEW
    movement row; the seed command checks for an existing OpeningStock movement
    before calling it.
    """
    quantity = Decimal(quantity)
    unit_cost = Decimal(unit_cost)
    value = _q(quantity * unit_cost)
    date = date or timezone.now().date()

    mv = StockMovement.objects.create(
        variant=variant, date=date, movement_type='OPENING',
        quantity=quantity, unit_cost=unit_cost,
        document_type='OpeningStock', document_id=variant.pk,
        notes=notes or 'رصيد افتتاحي', created_by=user,
    )
    mv.apply_to_variant()

    je = JournalEntry.objects.create(
        date=date,
        reference=f'OPEN-{variant.sku_code}',
        description=f'رصيد افتتاحي — {variant.sku_code}',
        status='POSTED',
        source_doc_type='OpeningStock',
        source_doc_id=variant.pk,
        created_by=user,
    )
    JournalLine.objects.create(
        entry=je, account=get_system_account('INVENTORY'),
        debit=value, credit=Decimal('0'),
        variant=variant,
        description=f'رصيد افتتاحي — {variant.sku_code}',
    )
    JournalLine.objects.create(
        entry=je, account=get_system_account('OPENING_EQUITY'),
        debit=Decimal('0'), credit=value,
        description=f'رصيد افتتاحي — {variant.sku_code}',
    )
    je.recalc_totals()
    return mv, je
