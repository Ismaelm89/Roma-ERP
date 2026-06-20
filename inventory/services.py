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


# ------------------------------------------------------------------ Finished-goods purchase
class FinishedGoodsPostingError(Exception):
    """Business-rule failure surfaced to the user when posting a goods purchase."""


@transaction.atomic
def post_finished_goods_purchase_invoice(invoice, user=None):
    """Post a multi-line finished-goods (trading) purchase as ONE balanced JE:
        DR  Inventory                       grand total (one line per SKU)
        CR  Cash account / AP(supplier)      grand total (single line)
    Each line raises its SKU's stock + WAC via a PURCHASE_IN StockMovement.
    """
    from core.models import JournalEntry, JournalLine
    if invoice.is_posted:
        raise FinishedGoodsPostingError(f'الفاتورة {invoice.invoice_no} مرحّلة من قبل.')
    lines = list(invoice.lines.select_related('variant', 'variant__item').all())
    if not lines:
        raise FinishedGoodsPostingError('أضف بند واحد على الأقل قبل الترحيل.')
    if invoice.payment_method == 'CASH' and not invoice.cash_account_id:
        raise FinishedGoodsPostingError('اختار حساب الدفع (نقدية/بنك/محفظة) للفاتورة.')
    if invoice.payment_method == 'CREDIT' and not invoice.supplier_id:
        raise FinishedGoodsPostingError('اختار المورد للفاتورة الآجلة.')
    for p in lines:
        if p.is_posted:
            raise FinishedGoodsPostingError(f'البند {p.variant} مرحّل من قبل — راجع الفاتورة.')
        if Decimal(p.quantity or 0) <= 0:
            raise FinishedGoodsPostingError(f'{p.variant}: الكمية لازم تكون أكبر من صفر.')
        if Decimal(p.unit_cost or 0) < 0:
            raise FinishedGoodsPostingError(f'{p.variant}: تكلفة الوحدة لا يمكن أن تكون سالبة.')
        if p.purchase_unit == 'WHOLESALE' and p.unit_factor <= 0:
            raise FinishedGoodsPostingError(
                f'{p.variant}: حدد «وحدة الجملة» و«عدد القطع فيها» على المنتج الرئيسي '
                f'الأول عشان تشتري بالجملة.')

    inv_acct = get_system_account('INVENTORY')
    je = JournalEntry.objects.create(
        date=invoice.date,
        reference=invoice.invoice_no,
        description=f'فاتورة شراء منتجات تامة {invoice.invoice_no}',
        status='POSTED',
        source_doc_type='FinishedGoodsPurchaseInvoice',
        source_doc_id=invoice.id,
        created_by=user,
    )
    grand_total = Decimal('0')
    for p in lines:
        # المخزون بالقطعة: لو الشراء بوحدة جملة، نحوّل لقطع. تكلفة القطعة بتتحسب من
        # إجمالي البند مرة واحدة (تقريب واحد) عشان قيمة الحركة تطابق القيد بالظبط.
        pieces = p.pieces_in
        line_total = _q(Decimal(p.quantity) * Decimal(p.unit_cost))
        piece_cost = ((line_total / pieces).quantize(Decimal('0.0001'))
                      if pieces > 0 else Decimal('0'))
        grand_total += line_total
        mv = StockMovement.objects.create(
            variant=p.variant, date=invoice.date, movement_type='PURCHASE_IN',
            quantity=pieces, unit_cost=piece_cost,
            document_type='FinishedGoodsPurchase', document_id=invoice.id,
            notes=f'شراء منتج تام — فاتورة {invoice.invoice_no}', created_by=user,
        )
        mv.apply_to_variant()
        JournalLine.objects.create(
            entry=je, account=inv_acct, debit=line_total, credit=Decimal('0'),
            variant=p.variant, description=f'{p.variant} × {p.quantity} {p.get_purchase_unit_display()}',
        )
        p.is_posted = True
        p.save(update_fields=['is_posted'])

    if invoice.payment_method == 'CASH':
        credit_acct = invoice.cash_account.gl_account
        credit_desc = f'دفع من {invoice.cash_account.name} — فاتورة {invoice.invoice_no}'
        credit_supplier = None
    else:
        credit_acct = get_system_account('AP')
        credit_desc = f'شراء آجل من {invoice.supplier.name} — فاتورة {invoice.invoice_no}'
        credit_supplier = invoice.supplier
    JournalLine.objects.create(
        entry=je, account=credit_acct, debit=Decimal('0'), credit=_q(grand_total),
        description=credit_desc, supplier=credit_supplier,
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('finished-goods invoice JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    invoice.is_posted = True
    invoice.journal_entry = je
    invoice.save(update_fields=['is_posted', 'journal_entry'])
    return je


# ------------------------------------------------------------------ Stock-take
class StockTakePostingError(Exception):
    """Business-rule failure surfaced to the user when posting a stock-take."""


@transaction.atomic
def post_stock_take(stock_take, user=None):
    """رحّل جرد مخزون: لكل بند، ظبط رصيد الصنف على الكمية المعدودة بحركة ADJUST،
    ورحّل الفرق على «فروق جرد» في قيد واحد متوازن:
        زيادة (معدود > نظام): DR المخزون / CR فروق جرد
        عجز  (معدود < نظام): DR فروق جرد / CR المخزون
    """
    if stock_take.is_posted:
        raise StockTakePostingError(f'الجرد {stock_take.take_no} مرحّل من قبل.')
    lines = list(stock_take.lines.select_related('variant').all())
    if not lines:
        raise StockTakePostingError('أضف بند واحد على الأقل قبل الترحيل.')
    for l in lines:
        if Decimal(l.counted_qty or 0) < 0:
            raise StockTakePostingError(f'{l.variant}: الكمية المعدودة لا يمكن أن تكون سالبة.')

    inv_acct = get_system_account('INVENTORY')
    var_acct = get_system_account('INVENTORY_VARIANCE')
    je = JournalEntry.objects.create(
        date=stock_take.date, reference=stock_take.take_no,
        description=f'جرد مخزون {stock_take.take_no}',
        status='POSTED', source_doc_type='StockTake', source_doc_id=stock_take.id,
        created_by=user,
    )
    any_gl = False
    for l in lines:
        v = l.variant
        sys_qty = Decimal(v.current_stock or 0)
        counted = Decimal(l.counted_qty or 0)
        var = counted - sys_qty
        cost = Decimal(v.average_cost or 0)
        l.system_qty_at_post = sys_qty
        if var != 0:
            mv = StockMovement.objects.create(
                variant=v, date=stock_take.date,
                movement_type='ADJUST_IN' if var > 0 else 'ADJUST_OUT',
                quantity=abs(var), unit_cost=cost,
                document_type='StockTake', document_id=stock_take.id,
                notes=f'جرد {stock_take.take_no} — نظام {sys_qty}، معدود {counted}',
                created_by=user,
            )
            mv.apply_to_variant()
            value = _q(abs(var) * cost)
            if value > 0:
                any_gl = True
                if var > 0:   # زيادة: DR مخزون / CR فروق جرد
                    JournalLine.objects.create(entry=je, account=inv_acct, variant=v,
                        debit=value, credit=Decimal('0'), description=f'زيادة جرد — {v.sku_code}')
                    JournalLine.objects.create(entry=je, account=var_acct,
                        debit=Decimal('0'), credit=value, description=f'زيادة جرد — {v.sku_code}')
                else:          # عجز: DR فروق جرد / CR مخزون
                    JournalLine.objects.create(entry=je, account=var_acct,
                        debit=value, credit=Decimal('0'), description=f'عجز جرد — {v.sku_code}')
                    JournalLine.objects.create(entry=je, account=inv_acct, variant=v,
                        debit=Decimal('0'), credit=value, description=f'عجز جرد — {v.sku_code}')
        l.is_posted = True
        l.save(update_fields=['system_qty_at_post', 'is_posted'])

    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('stock-take JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    if not any_gl:          # مفيش فروق بقيمة — امسح القيد الفاضي
        je.delete()
        je = None
    stock_take.is_posted = True
    stock_take.journal_entry = je
    stock_take.save(update_fields=['is_posted', 'journal_entry'])
    return je
