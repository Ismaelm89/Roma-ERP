"""Posting and cancellation services for sales documents.

Each sales invoice line represents N bundles of one Item, where a bundle =
1 piece of each variant (size) of that item.  Posting:
  - Creates one SALES_OUT StockMovement per variant of the item (qty = N)
  - COGS captured as N × Σ(variant.average_cost)
  - Journal entry: DR AR / CR Sales,  DR COGS / CR Inventory   (no VAT)

Document-level discount ("خصم التاجر") reduces the grand total directly.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from core.account_codes import get_system_account
from core.models import JournalEntry, JournalLine
from inventory.models import StockMovement


def _q(v):
    return Decimal(v).quantize(Decimal('0.01'))


class PostingError(Exception):
    """Business-rule failure that should be surfaced to the user."""


# ------------------------------------------------------------------ Sales Invoice

@transaction.atomic
def post_sales_invoice(invoice, user=None):
    if invoice.status != 'DRAFT':
        raise PostingError(f'Invoice {invoice.invoice_no} is {invoice.status}, not DRAFT.')

    lines = list(invoice.lines.select_related('item').all())
    if not lines:
        raise PostingError('لا يمكن ترحيل فاتورة بدون بنود.')

    for line in lines:
        if line.quantity <= 0:
            raise PostingError('عدد القطع يجب أن يكون أكبر من صفر.')
        if line.unit_price < 0:
            raise PostingError('سعر القطعة لا يمكن أن يكون سالباً.')
        if not line.variant_id:
            raise PostingError('لازم تختار المقاس في كل بند (البيع بالقطعة من مقاس محدد).')
        if line.sale_unit == 'WHOLESALE' and line.unit_factor <= 0:
            raise PostingError(
                f'{line.variant}: حدد «وحدة الجملة» وعدد القطع فيها على المنتج الرئيسي '
                'الأول عشان تبيع بالجملة (دلوقتي القيمة صفر فالبند هيتباع من غير ما يخصم مخزون).')
        line.recalc()

    # ----- Item 4a: امنع البيع لو الرصيد مش كفاية -----
    # بنجمّع المطلوب لكل مقاس (المقاس ممكن يتكرر في أكتر من بند) ونقارن بالرصيد.
    needed = {}
    for line in lines:
        variant, qty = needed.get(line.variant_id, (line.variant, Decimal('0')))
        needed[line.variant_id] = (variant, qty + Decimal(line.total_pieces))
    shortages = []
    for variant, qty_needed in needed.values():
        available = Decimal(variant.current_stock or 0)
        if qty_needed > available:
            label = f'{variant.item.name_ar} مقاس {variant.size}'
            shortages.append(
                f'{label}: متاح {int(available)} قطعة، مطلوب {int(qty_needed)} قطعة'
            )
    if shortages:
        raise PostingError(
            'الرصيد مش كفاية للبيع — لازم يكون عندك رصيد كافي قبل الترحيل:\n'
            + '\n'.join('• ' + s for s in shortages)
        )

    total_cogs = Decimal('0')
    for line in lines:
        item = line.item
        # خصم القطع الفعلية للمقاس (العدد × عدد القطع في وحدة البيع).
        v = line.variant
        pieces = line.total_pieces
        line_cogs = _q(Decimal(v.average_cost) * Decimal(pieces))
        line.cogs_at_posting = line_cogs
        total_cogs += line_cogs
        line.save()

        mv = StockMovement.objects.create(
            variant=v,
            date=invoice.date,
            movement_type='SALES_OUT',
            quantity=pieces,
            unit_cost=Decimal(v.average_cost),
            document_type='SalesInvoice',
            document_id=invoice.id,
            notes=f'فاتورة {invoice.invoice_no} — {item.code} مقاس {v.size} '
                  f'({line.quantity} {line.sale_unit_label} = {pieces} قطعة)',
            created_by=user,
        )
        mv.apply_to_variant()

    invoice.recalc_totals()

    je = JournalEntry.objects.create(
        date=invoice.date,
        reference=invoice.invoice_no,
        description=f'فاتورة مبيعات للعميل {invoice.customer.name_ar}',
        status='POSTED',
        source_doc_type='SalesInvoice',
        source_doc_id=invoice.id,
        created_by=user,
    )

    ar = get_system_account('AR')
    sales = get_system_account('SALES_REVENUE')
    cogs = get_system_account('COGS')
    inv_acct = get_system_account('INVENTORY')

    net_sales = _q(Decimal(invoice.subtotal) - Decimal(invoice.doc_discount_amount))

    JournalLine.objects.create(entry=je, account=ar,
        debit=_q(invoice.grand_total), credit=Decimal('0'),
        customer=invoice.customer,
        description=f'AR — {invoice.invoice_no}')
    JournalLine.objects.create(entry=je, account=sales,
        debit=Decimal('0'), credit=net_sales,
        description=f'Sales — {invoice.invoice_no}')
    if total_cogs > 0:
        JournalLine.objects.create(entry=je, account=cogs,
            debit=_q(total_cogs), credit=Decimal('0'),
            description=f'COGS — {invoice.invoice_no}')
        JournalLine.objects.create(entry=je, account=inv_acct,
            debit=Decimal('0'), credit=_q(total_cogs),
            description=f'Inventory — {invoice.invoice_no}')
    je.recalc_totals()

    invoice.status = 'POSTED'
    invoice.posted_at = timezone.now()
    invoice.posted_by = user
    invoice.journal_entry = je
    invoice.save(update_fields=['status', 'posted_at', 'posted_by', 'journal_entry'])

    # بيع نقدي → تحصيل فوري بالكامل: سند قبض تلقائي بيدخل الفلوس الخزنة/البنك ويقفل المستحق.
    if getattr(invoice, 'payment_type', 'CREDIT') == 'CASH' and Decimal(invoice.grand_total) > 0:
        from .models import Receipt, ReceiptAllocation
        rec = Receipt.objects.create(
            date=invoice.date, customer=invoice.customer, method='CASH',
            cash_account=invoice.cash_account, amount=_q(invoice.grand_total),
            reference=invoice.invoice_no, notes=f'تحصيل نقدي تلقائي — فاتورة {invoice.invoice_no}',
            status='DRAFT', auto_generated=True, created_by=user)
        ReceiptAllocation.objects.create(receipt=rec, invoice=invoice, amount=_q(invoice.grand_total))
        post_receipt(rec, user=user)
    return je


@transaction.atomic
def cancel_sales_invoice(invoice, user=None):
    if invoice.status != 'POSTED':
        raise PostingError(f'Only POSTED invoices can be cancelled (current: {invoice.status}).')

    today = timezone.now().date()

    # لو كان بيع نقدي وله سند تحصيل تلقائي — نلغيه الأول عشان نعكس دخول الفلوس والـ AR.
    from .models import Receipt
    auto_recs = (Receipt.objects.filter(auto_generated=True, status='POSTED',
                                        allocations__invoice=invoice).distinct())
    for rec in auto_recs:
        cancel_receipt(rec, user=user)
    for line in invoice.lines.select_related('item', 'variant').all():
        if line.quantity <= 0 or not line.variant_id:
            continue
        # رجّع القطع للمخزون بنفس تكلفة القطعة وقت الترحيل (= cogs_at_posting ÷ القطع)،
        # عشان مزج المتوسط المرجّح يعيد بناء متوسط التكلفة الصح بالظبط.
        v = line.variant
        pieces = line.total_pieces
        per_piece_cost = (Decimal(line.cogs_at_posting) / Decimal(pieces)
                           if pieces else Decimal('0'))
        mv = StockMovement.objects.create(
            variant=v,
            date=today,
            movement_type='SALES_RETURN_IN',
            quantity=pieces,
            unit_cost=per_piece_cost,
            document_type='SalesInvoice.Cancel',
            document_id=invoice.id,
            notes=f'إلغاء فاتورة {invoice.invoice_no} — {line.item.code} مقاس {v.size} '
                  f'({line.quantity} {line.sale_unit_label} = {pieces} قطعة)',
            created_by=user,
        )
        mv.apply_to_variant()

    orig = invoice.journal_entry
    rev = JournalEntry.objects.create(
        date=today,
        reference=f'CANCEL-{invoice.invoice_no}',
        description=f'إلغاء فاتورة مبيعات {invoice.invoice_no}',
        status='POSTED',
        source_doc_type='SalesInvoice.Cancel',
        source_doc_id=invoice.id,
        created_by=user,
    )
    if orig:
        for line in orig.lines.all():
            JournalLine.objects.create(
                entry=rev, account=line.account,
                debit=line.credit, credit=line.debit,
                description=f'إلغاء — {line.description}',
                customer=line.customer, variant=line.variant,
            )
    rev.recalc_totals()
    invoice.status = 'CANCELLED'
    invoice.save(update_fields=['status'])
    return rev


# ------------------------------------------------------------------ Receipt
# (Unchanged from the prior version — receipts have no VAT/bundle concerns.)

@transaction.atomic
def post_receipt(receipt, user=None):
    if receipt.status != 'DRAFT':
        raise PostingError(f'Receipt {receipt.receipt_no} is {receipt.status}, not DRAFT.')
    if Decimal(receipt.amount) <= 0:
        raise PostingError('قيمة السند يجب أن تكون أكبر من صفر.')

    allocs = list(receipt.allocations.all())
    alloc_sum = sum((Decimal(a.amount) for a in allocs), Decimal('0'))
    if alloc_sum > Decimal(receipt.amount):
        raise PostingError(
            f'إجمالي التخصيصات ({alloc_sum}) أكبر من قيمة السند ({receipt.amount}).'
        )
    for a in allocs:
        if a.invoice.customer_id != receipt.customer_id:
            raise PostingError(
                f'الفاتورة {a.invoice.invoice_no} ليست لنفس العميل.'
            )
        # امنع تخصيص أكتر من المتبقّي على الفاتورة (يمنع رصيد مدفوع أكبر من الإجمالي).
        due = Decimal(a.invoice.balance_due)
        if Decimal(a.amount) > due:
            raise PostingError(
                f'الفاتورة {a.invoice.invoice_no}: المبلغ المخصّص ({a.amount}) أكبر من '
                f'المتبقّي عليها ({due}).'
            )

    if receipt.cash_account_id:
        debit_acct = receipt.cash_account.gl_account
    else:
        cash_or_bank_key = 'CASH' if receipt.method == 'CASH' else 'BANK'
        debit_acct = get_system_account(cash_or_bank_key)
    ar = get_system_account('AR')

    je = JournalEntry.objects.create(
        date=receipt.date,
        reference=receipt.receipt_no,
        description=f'سند قبض من {receipt.customer.name_ar}',
        status='POSTED',
        source_doc_type='Receipt',
        source_doc_id=receipt.id,
        created_by=user,
    )
    JournalLine.objects.create(entry=je, account=debit_acct,
        debit=_q(receipt.amount), credit=Decimal('0'),
        description=f'تحصيل — {receipt.receipt_no}')
    JournalLine.objects.create(entry=je, account=ar,
        debit=Decimal('0'), credit=_q(receipt.amount),
        customer=receipt.customer,
        description=f'تحصيل — {receipt.receipt_no}')
    je.recalc_totals()

    receipt.status = 'POSTED'
    receipt.posted_at = timezone.now()
    receipt.journal_entry = je
    receipt.save(update_fields=['status', 'posted_at', 'journal_entry'])
    return je


@transaction.atomic
def cancel_receipt(receipt, user=None):
    if receipt.status != 'POSTED':
        raise PostingError(f'Only POSTED receipts can be cancelled (current: {receipt.status}).')

    orig = receipt.journal_entry
    rev = JournalEntry.objects.create(
        date=timezone.now().date(),
        reference=f'CANCEL-{receipt.receipt_no}',
        description=f'إلغاء سند قبض {receipt.receipt_no}',
        status='POSTED',
        source_doc_type='Receipt.Cancel',
        source_doc_id=receipt.id,
        created_by=user,
    )
    if orig:
        for line in orig.lines.all():
            JournalLine.objects.create(
                entry=rev, account=line.account,
                debit=line.credit, credit=line.debit,
                description=f'إلغاء — {line.description}',
                customer=line.customer,
            )
    rev.recalc_totals()
    receipt.status = 'CANCELLED'
    receipt.save(update_fields=['status'])
    return rev


# ------------------------------------------------------------------ Sales Return

@transaction.atomic
def post_sales_return(return_doc, user=None):
    """Post a sales return — receives items back into stock and reduces customer's debt.

    Journal:
      DR Sales Returns  (contra-revenue)  = subtotal
      CR AR (customer)                    = subtotal
      DR Inventory                        = total_cogs
      CR COGS                             = total_cogs
    """
    if return_doc.status != 'DRAFT':
        raise PostingError(f'Return {return_doc.return_no} is {return_doc.status}, not DRAFT.')

    lines = list(return_doc.lines.select_related('item', 'variant').all())
    if not lines:
        raise PostingError('لا يمكن ترحيل مرتجع بدون بنود.')

    for line in lines:
        if line.quantity <= 0:
            raise PostingError('عدد القطع/المجموعات يجب أن يكون أكبر من صفر.')
        if line.unit_price < 0:
            raise PostingError('سعر الوحدة لا يمكن أن يكون سالباً.')
        line.recalc()

    total_cogs = Decimal('0')
    for line in lines:
        item = line.item
        if not line.variant_id:
            raise PostingError('لازم تختار المقاس في كل بند مرتجع.')
        v = line.variant
        pieces = line.total_pieces
        line_cogs = _q(Decimal(v.average_cost) * Decimal(pieces))
        line.cogs_at_posting = line_cogs
        total_cogs += line_cogs
        line.save()

        mv = StockMovement.objects.create(
            variant=v,
            date=return_doc.date,
            movement_type='SALES_RETURN_IN',
            quantity=pieces,
            unit_cost=Decimal(v.average_cost),
            document_type='SalesReturn',
            document_id=return_doc.id,
            notes=f'مرتجع {return_doc.return_no} — {item.code} مقاس {v.size} '
                  f'({line.quantity} دستة = {pieces} قطعة)',
            created_by=user,
        )
        mv.apply_to_variant()

    return_doc.recalc_totals()

    je = JournalEntry.objects.create(
        date=return_doc.date,
        reference=return_doc.return_no,
        description=f'مرتجع مبيعات من العميل {return_doc.customer.name_ar}',
        status='POSTED',
        source_doc_type='SalesReturn',
        source_doc_id=return_doc.id,
        created_by=user,
    )
    ar = get_system_account('AR')
    sales_returns = get_system_account('SALES_RETURNS')
    cogs = get_system_account('COGS')
    inv_acct = get_system_account('INVENTORY')

    refund = _q(return_doc.grand_total)

    JournalLine.objects.create(entry=je, account=sales_returns,
        debit=refund, credit=Decimal('0'),
        description=f'مرتجع مبيعات — {return_doc.return_no}')
    JournalLine.objects.create(entry=je, account=ar,
        debit=Decimal('0'), credit=refund,
        customer=return_doc.customer,
        description=f'تخفيض ذمم — مرتجع {return_doc.return_no}')
    if total_cogs > 0:
        JournalLine.objects.create(entry=je, account=inv_acct,
            debit=_q(total_cogs), credit=Decimal('0'),
            description=f'استرداد مخزون — مرتجع {return_doc.return_no}')
        JournalLine.objects.create(entry=je, account=cogs,
            debit=Decimal('0'), credit=_q(total_cogs),
            description=f'خصم COGS — مرتجع {return_doc.return_no}')
    je.recalc_totals()

    return_doc.status = 'POSTED'
    return_doc.posted_at = timezone.now()
    return_doc.posted_by = user
    return_doc.journal_entry = je
    return_doc.save(update_fields=['status', 'posted_at', 'posted_by', 'journal_entry'])
    return je


@transaction.atomic
def cancel_sales_return(return_doc, user=None):
    """Cancel a posted return — reverses stock + journal."""
    if return_doc.status != 'POSTED':
        raise PostingError(f'Only POSTED returns can be cancelled (current: {return_doc.status}).')

    today = timezone.now().date()
    for line in return_doc.lines.select_related('item', 'variant').all():
        if line.quantity <= 0 or not line.variant_id:
            continue
        v = line.variant
        pieces = line.total_pieces
        per_piece_cost = (Decimal(line.cogs_at_posting) / Decimal(pieces)
                           if pieces else Decimal('0'))
        mv = StockMovement.objects.create(
            variant=v,
            date=today,
            movement_type='SALES_OUT',  # remove from stock again
            quantity=pieces,
            unit_cost=per_piece_cost,
            document_type='SalesReturn.Cancel',
            document_id=return_doc.id,
            notes=f'إلغاء مرتجع {return_doc.return_no} — {line.item.code} مقاس {v.size} '
                  f'({line.quantity} دستة = {pieces} قطعة)',
            created_by=user,
        )
        mv.apply_to_variant()

    orig = return_doc.journal_entry
    rev = JournalEntry.objects.create(
        date=today,
        reference=f'CANCEL-{return_doc.return_no}',
        description=f'إلغاء مرتجع {return_doc.return_no}',
        status='POSTED',
        source_doc_type='SalesReturn.Cancel',
        source_doc_id=return_doc.id,
        created_by=user,
    )
    if orig:
        for line in orig.lines.all():
            JournalLine.objects.create(
                entry=rev, account=line.account,
                debit=line.credit, credit=line.debit,
                description=f'إلغاء — {line.description}',
                customer=line.customer,
            )
    rev.recalc_totals()
    return_doc.status = 'CANCELLED'
    return_doc.save(update_fields=['status'])
    return rev


def add_orders_to_invoice(invoice, orders, user=None):
    """يبني بنود فاتورة بيع من أوامر إنتاج مكتملة (مقاس + كمية لكل أمر) ويربط كل أمر بالفاتورة.
    السعر بيتملأ تلقائياً من وصفة المنتج (piece price). بيرجّع عدد البنود المضافة.

    آمن ضد الإضافة المزدوجة: بيقفل صفوف الأوامر (select_for_update) وبيتجاهل أي أمر
    مربوط بفاتورة قبل كده — فلو الفورم اتبعت مرتين (double-submit) مش هتتكرر البنود."""
    from decimal import Decimal
    from django.db import transaction
    from manufacturing.models import Size, ProductionOrder
    from inventory.models import ItemVariant
    from .models import SalesInvoiceLine
    added = 0
    order_ids = [o.pk for o in orders]
    with transaction.atomic():
        # نعيد جلب الأوامر مع قفل الصفوف داخل المعاملة عشان أي طلب متزامن يستنّى
        locked = list(ProductionOrder.objects.select_for_update()
                      .filter(pk__in=order_ids))
        # بنجمّع الكمية لكل مقاس (variant) — لو نفس المنتج/المقاس اتنتج في أكتر من أمر
        # بنحطّه في بند واحد بمجموع الكمية، بدل بند مكرر لكل أمر (كان بيبان زي التكرار).
        agg = {}  # variant -> qty
        for o in locked:
            item = o.item
            if not item:
                continue
            if o.sales_invoice_id is not None:
                # اتفوتر قبل كده (أو في طلب متزامن سبقنا) — نتجاهله عشان ميتكررش
                continue
            for size_id, qty in o._pieces_by_size().items():
                if not qty:
                    continue
                size = Size.objects.filter(pk=size_id).first()
                if not size:
                    continue
                variant = ItemVariant.objects.filter(item=item, size=size.code).first()
                if not variant:
                    continue
                agg[variant] = agg.get(variant, Decimal('0')) + Decimal(qty)
            o.sales_invoice = invoice
            o.save(update_fields=['sales_invoice'])
        # بند واحد لكل مقاس — ولو الفاتورة فيها نفس المقاس قبل كده بنزوّد كميته مش بند جديد
        for variant, qty in agg.items():
            line = invoice.lines.filter(variant=variant, sale_unit='PIECE').first()
            if line:
                line.quantity = Decimal(line.quantity or 0) + qty
            else:
                line = SalesInvoiceLine(invoice=invoice, variant=variant,
                                        sale_unit='PIECE', quantity=qty, unit_price=Decimal('0'))
            line.save()                         # بيملأ السعر تلقائياً من الوصفة لو 0
            line.recalc()                       # يحسب line_total = سعر × كمية
            line.save(update_fields=['line_total'])
            added += 1
    invoice.recalc_totals()
    return added
