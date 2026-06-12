"""Posting services for fabric purchases + supplier payments + production orders.

Every state transition (purchase, payment, release, complete) goes through here
so the movement log, batch cache, and GL stay in sync atomically.
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.account_codes import get_system_account, SYSTEM_ACCOUNTS
from core.models import JournalEntry, JournalLine

from .models import (
    FabricBatch, FabricMovement, SupplierPayment, Supplier,
    ProductionOrder, FabricUsage,
    Accessory, AccessoryPurchase,
    FabricPurchaseInvoice, AccessoryPurchaseInvoice,
    ManufacturingWagePayment,
    fabric_available_kg, fabric_avg_cost,
)


class FabricPostingError(Exception):
    """Business-rule failure in fabric posting (e.g. send more than in stock)."""


def _q(v, places='0.01'):
    return Decimal(v).quantize(Decimal(places))


def _payment_credit_account(payment_method):
    """Pick the GL account to credit based on payment method."""
    if payment_method == 'CASH':
        return get_system_account('CASH')
    if payment_method == 'BANK':
        return get_system_account('BANK')
    # CREDIT
    return get_system_account('AP')


def _invoice_credit_account(payment_method, cash_account=None):
    """Credit account for a multi-line invoice.

    Same idea as `_payment_credit_account`, but if a specific CashAccount is
    chosen (e.g. a wallet) we credit *its* GL account instead of the generic
    system CASH/BANK account. CREDIT always goes to AP.
    """
    if payment_method == 'CREDIT':
        return get_system_account('AP')
    if cash_account is not None and getattr(cash_account, 'gl_account_id', None):
        return cash_account.gl_account
    if payment_method == 'BANK':
        return get_system_account('BANK')
    return get_system_account('CASH')


# ============================================================
#  1) Fabric purchase posting
# ============================================================

def _fabric_apply_stock_in(batch: FabricBatch, user=None):
    """Side-effects of receiving one fabric batch into stock (no GL):
      - create the PURCHASE_IN movement
      - set in_stock_qty_kg = purchase_qty_kg
    Returns the line's purchase_total (qty × unit_cost). The caller owns the JE
    so this can be reused by both single-purchase and multi-line invoice posting.
    """
    purchase_total = _q(batch.purchase_total)
    FabricMovement.objects.create(
        batch=batch,
        date=batch.purchase_date,
        movement_type='PURCHASE_IN',
        quantity_kg=batch.purchase_qty_kg,
        cost_per_kg_snapshot=batch.purchase_unit_cost,
        document_type='FabricBatch',
        document_id=batch.id,
        notes=f'شراء دفعة {batch.batch_no} من {batch.supplier.name}',
        created_by=user,
    )
    batch.in_stock_qty_kg = Decimal(batch.purchase_qty_kg)
    return purchase_total


@transaction.atomic
def post_fabric_purchase(batch: FabricBatch, user=None):
    """Post a single (standalone) FabricBatch:
      - Creates PURCHASE_IN movement
      - Sets in_stock_qty_kg = purchase_qty_kg
      - Creates a balanced JournalEntry:
          DR  Fabric Inventory (1330000)   purchase_total
          CR  AP / Cash / Bank             purchase_total
      - Flags the batch as posted, attaches the JE
    """
    if batch.is_posted:
        raise FabricPostingError(f'الدفعة {batch.batch_no} مرحّلة من قبل.')
    if batch.invoice_id:
        raise FabricPostingError(
            f'الدفعة {batch.batch_no} بند جوّه فاتورة شراء — رحّل الفاتورة كلها من '
            'شاشة "فواتير شراء القماش".')
    if Decimal(batch.purchase_qty_kg) <= 0:
        raise FabricPostingError('الكمية لازم تكون أكبر من صفر.')
    if Decimal(batch.purchase_unit_cost) <= 0:
        raise FabricPostingError('سعر الكيلو لازم يكون أكبر من صفر.')

    # 1 + 3. Stock-in side effects
    purchase_total = _fabric_apply_stock_in(batch, user)

    # 2. Journal entry: DR Fabric Inventory / CR (AP or Cash or Bank)
    je = JournalEntry.objects.create(
        date=batch.purchase_date,
        reference=batch.batch_no,
        description=f'شراء قماش — دفعة {batch.batch_no}',
        status='POSTED',
        source_doc_type='FabricBatch',
        source_doc_id=batch.id,
        created_by=user,
    )
    fabric_inv = get_system_account('FABRIC_INVENTORY')
    credit_acct = _payment_credit_account(batch.purchase_payment_method)

    JournalLine.objects.create(
        entry=je, account=fabric_inv,
        debit=purchase_total, credit=Decimal('0'),
        description=f'دفعة {batch.batch_no} — {batch.fabric_type.name_ar}',
        supplier=batch.supplier,
    )
    JournalLine.objects.create(
        entry=je, account=credit_acct,
        debit=Decimal('0'), credit=purchase_total,
        description=f'شراء قماش من {batch.supplier.name}',
        supplier=batch.supplier,
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'fabric purchase JE unbalanced'

    # 3. Flag batch posted
    batch.is_posted = True
    batch.purchase_journal_entry = je
    batch.save(update_fields=['in_stock_qty_kg', 'is_posted', 'purchase_journal_entry'])

    return je


@transaction.atomic
def post_fabric_purchase_invoice(invoice: FabricPurchaseInvoice, user=None):
    """Post a multi-line fabric purchase invoice as ONE balanced JournalEntry:
        DR  Fabric Inventory (1330000)   one line per fabric batch
        CR  AP / Cash / Bank / Wallet     grand total (single line)
    Every child FabricBatch gets its PURCHASE_IN movement + stock, and is flagged
    posted against the shared JE.
    """
    if invoice.is_posted:
        raise FabricPostingError(f'الفاتورة {invoice.invoice_no} مرحّلة من قبل.')
    lines = list(invoice.lines.select_related('fabric_type', 'color').all())
    if not lines:
        raise FabricPostingError('أضف بند واحد على الأقل قبل الترحيل.')
    for b in lines:
        if b.is_posted:
            raise FabricPostingError(f'البند {b.batch_no} مرحّل من قبل — راجع الفاتورة.')
        if Decimal(b.purchase_qty_kg or 0) <= 0:
            raise FabricPostingError(f'{b.fabric_type.name_ar}: الكمية لازم تكون أكبر من صفر.')
        if Decimal(b.purchase_unit_cost or 0) <= 0:
            raise FabricPostingError(f'{b.fabric_type.name_ar}: سعر الكيلو لازم يكون أكبر من صفر.')

    je = JournalEntry.objects.create(
        date=invoice.date,
        reference=invoice.invoice_no,
        description=f'فاتورة شراء قماش {invoice.invoice_no} — {invoice.supplier.name}',
        status='POSTED',
        source_doc_type='FabricPurchaseInvoice',
        source_doc_id=invoice.id,
        created_by=user,
    )
    fabric_inv = get_system_account('FABRIC_INVENTORY')
    grand_total = Decimal('0')
    for b in lines:
        line_total = _fabric_apply_stock_in(b, user)
        grand_total += line_total
        JournalLine.objects.create(
            entry=je, account=fabric_inv,
            debit=line_total, credit=Decimal('0'),
            description=f'دفعة {b.batch_no} — {b.fabric_type.name_ar}/{b.color.name_ar}',
            supplier=invoice.supplier,
        )
        b.is_posted = True
        b.purchase_journal_entry = je
        b.save(update_fields=['in_stock_qty_kg', 'is_posted', 'purchase_journal_entry'])

    credit_acct = _invoice_credit_account(invoice.payment_method, invoice.cash_account)
    JournalLine.objects.create(
        entry=je, account=credit_acct,
        debit=Decimal('0'), credit=_q(grand_total),
        description=f'شراء قماش من {invoice.supplier.name} — فاتورة {invoice.invoice_no}',
        supplier=invoice.supplier,
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'fabric invoice JE unbalanced'

    invoice.is_posted = True
    invoice.journal_entry = je
    invoice.save(update_fields=['is_posted', 'journal_entry'])
    return je


# ============================================================
#  1b) Accessory purchase posting (item 9)
# ============================================================

def _accessory_apply_stock_in(purchase: AccessoryPurchase):
    """Raise the accessory's current_stock + recompute its WAC for one line
    (no GL). Returns the line total (qty × unit_cost). The caller owns the JE.

    Purchase qty/cost are entered in the PURCHASE unit; stock + WAC are tracked
    in the CONSUMPTION unit. We convert via units_per_purchase (المعدل):
        stock_consumption += qty_purchase × المعدل
        cost_consumption   = cost_purchase ÷ المعدل
    The line total (qty_purchase × cost_purchase) is unchanged, so the GL is
    unaffected.
    """
    a = Accessory.objects.select_for_update().get(pk=purchase.accessory_id)
    qty_p = Decimal(purchase.quantity or 0)
    cost_p = Decimal(purchase.unit_cost or 0)
    total = _q(qty_p * cost_p)
    factor = Decimal(a.units_per_purchase or 0)
    if factor <= 0:
        factor = Decimal('1')
    qty = qty_p * factor                       # in consumption units
    unit_cost = cost_p / factor                # cost per consumption unit
    old_stock = Decimal(a.current_stock or 0)
    old_cost = Decimal(a.average_cost or 0)
    new_stock = old_stock + qty
    if new_stock > 0:
        a.average_cost = ((old_stock * old_cost) + (qty * unit_cost)) / new_stock
    a.current_stock = new_stock
    a.save(update_fields=['current_stock', 'average_cost'])
    return total


@transaction.atomic
def post_accessory_purchase(purchase: AccessoryPurchase, user=None):
    """Post a single (standalone) accessory purchase:
        DR  Accessory Inventory (1340000)   total
        CR  Cash account / AP(supplier)      total
    and raise the accessory's current_stock + recompute its WAC.
    """
    if purchase.is_posted:
        raise FabricPostingError(f'عملية الشراء {purchase.purchase_no} مرحّلة من قبل.')
    if purchase.invoice_id:
        raise FabricPostingError(
            f'الشراء {purchase.purchase_no} بند جوّه فاتورة — رحّل الفاتورة كلها من '
            'شاشة "فواتير شراء الإكسسوارات".')
    qty = Decimal(purchase.quantity or 0)
    unit_cost = Decimal(purchase.unit_cost or 0)
    if qty <= 0:
        raise FabricPostingError('الكمية لازم تكون أكبر من صفر.')
    if unit_cost < 0:
        raise FabricPostingError('سعر الوحدة لا يمكن أن يكون سالباً.')
    if purchase.payment_method == 'CASH' and not purchase.cash_account_id:
        raise FabricPostingError('اختار حساب الدفع (نقدية/بنك/محفظة).')
    if purchase.payment_method == 'CREDIT' and not purchase.supplier_id:
        raise FabricPostingError('اختار المورد للشراء الآجل.')

    total = _q(qty * unit_cost)
    acc_inv = get_system_account('ACCESSORY_INVENTORY')

    je = JournalEntry.objects.create(
        date=purchase.date,
        reference=purchase.purchase_no,
        description=f'شراء إكسسوار — {purchase.accessory.name_ar}',
        status='POSTED',
        source_doc_type='AccessoryPurchase',
        source_doc_id=purchase.id,
        created_by=user,
    )
    JournalLine.objects.create(
        entry=je, account=acc_inv,
        debit=total, credit=Decimal('0'),
        description=f'{purchase.accessory.name_ar} × {qty}',
    )
    if purchase.payment_method == 'CASH':
        JournalLine.objects.create(
            entry=je, account=purchase.cash_account.gl_account,
            debit=Decimal('0'), credit=total,
            description=f'دفع من {purchase.cash_account.name}',
        )
    else:
        JournalLine.objects.create(
            entry=je, account=get_system_account('AP'),
            debit=Decimal('0'), credit=total,
            description=f'شراء آجل من {purchase.supplier.name}',
            supplier=purchase.supplier,
        )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'accessory purchase JE unbalanced'

    _accessory_apply_stock_in(purchase)

    purchase.is_posted = True
    purchase.journal_entry = je
    purchase.save(update_fields=['is_posted', 'journal_entry'])
    return je


@transaction.atomic
def post_accessory_purchase_invoice(invoice: AccessoryPurchaseInvoice, user=None):
    """Post a multi-line accessory purchase invoice as ONE balanced JournalEntry:
        DR  Accessory Inventory (1340000)   one line per accessory
        CR  Cash account / AP(supplier)      grand total (single line)
    Every child line raises its accessory's stock + WAC, flagged against the
    shared JE.
    """
    if invoice.is_posted:
        raise FabricPostingError(f'الفاتورة {invoice.invoice_no} مرحّلة من قبل.')
    lines = list(invoice.lines.select_related('accessory').all())
    if not lines:
        raise FabricPostingError('أضف بند واحد على الأقل قبل الترحيل.')
    if invoice.payment_method == 'CASH' and not invoice.cash_account_id:
        raise FabricPostingError('اختار حساب الدفع (نقدية/بنك/محفظة) للفاتورة.')
    if invoice.payment_method == 'CREDIT' and not invoice.supplier_id:
        raise FabricPostingError('اختار المورد للفاتورة الآجلة.')
    for p in lines:
        if p.is_posted:
            raise FabricPostingError(f'البند {p.purchase_no} مرحّل من قبل — راجع الفاتورة.')
        if Decimal(p.quantity or 0) <= 0:
            raise FabricPostingError(f'{p.accessory.name_ar}: الكمية لازم تكون أكبر من صفر.')
        if Decimal(p.unit_cost or 0) < 0:
            raise FabricPostingError(f'{p.accessory.name_ar}: سعر الوحدة لا يمكن أن يكون سالباً.')

    acc_inv = get_system_account('ACCESSORY_INVENTORY')
    je = JournalEntry.objects.create(
        date=invoice.date,
        reference=invoice.invoice_no,
        description=f'فاتورة شراء إكسسوارات {invoice.invoice_no}',
        status='POSTED',
        source_doc_type='AccessoryPurchaseInvoice',
        source_doc_id=invoice.id,
        created_by=user,
    )
    grand_total = Decimal('0')
    for p in lines:
        line_total = _accessory_apply_stock_in(p)
        grand_total += line_total
        JournalLine.objects.create(
            entry=je, account=acc_inv,
            debit=line_total, credit=Decimal('0'),
            description=f'{p.accessory.name_ar} × {Decimal(p.quantity or 0)}',
        )
        p.is_posted = True
        p.journal_entry = je
        p.save(update_fields=['is_posted', 'journal_entry'])

    if invoice.payment_method == 'CASH':
        credit_acct = invoice.cash_account.gl_account
        credit_desc = f'دفع من {invoice.cash_account.name} — فاتورة {invoice.invoice_no}'
        credit_supplier = None
    else:
        credit_acct = get_system_account('AP')
        credit_desc = f'شراء آجل من {invoice.supplier.name} — فاتورة {invoice.invoice_no}'
        credit_supplier = invoice.supplier
    JournalLine.objects.create(
        entry=je, account=credit_acct,
        debit=Decimal('0'), credit=_q(grand_total),
        description=credit_desc,
        supplier=credit_supplier,
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'accessory invoice JE unbalanced'

    invoice.is_posted = True
    invoice.journal_entry = je
    invoice.save(update_fields=['is_posted', 'journal_entry'])
    return je


# ============================================================
#  2) Supplier payment posting
# ============================================================

@transaction.atomic
def post_supplier_payment(payment: SupplierPayment, user=None):
    """Post a payment to a fabric supplier or dyer:
        DR  AP (2110000) tagged with the vendor   amount
        CR  Cash / Bank                            amount
    The vendor's current_balance drops by `amount` because we credit-tagged
    them earlier on purchase (CR AP) and now debit-tag them on payment (DR AP).
    """
    if payment.status != 'DRAFT':
        raise FabricPostingError(f'سند الدفع {payment.payment_no} حالته {payment.status}، '
                                  'مش DRAFT.')
    if Decimal(payment.amount) <= 0:
        raise FabricPostingError('المبلغ لازم يكون أكبر من صفر.')
    if not payment.supplier_id:
        raise FabricPostingError('لازم تختار المورد.')
    if payment.method == 'CREDIT':
        raise FabricPostingError('سند الدفع لازم يكون CASH أو BANK أو CHEQUE — مش آجل.')

    amount = _q(payment.amount)

    je = JournalEntry.objects.create(
        date=payment.date,
        reference=payment.payment_no,
        description=f'سند دفع — {payment.party_label}',
        status='POSTED',
        source_doc_type='SupplierPayment',
        source_doc_id=payment.id,
        created_by=user,
    )
    ap = get_system_account('AP')
    if payment.cash_account_id:
        credit_acct = payment.cash_account.gl_account
    elif payment.method == 'BANK':
        credit_acct = get_system_account('BANK')
    else:  # CASH or CHEQUE → cash on hand (cheques tracked via reference)
        credit_acct = get_system_account('CASH')

    JournalLine.objects.create(
        entry=je, account=ap,
        debit=amount, credit=Decimal('0'),
        description=f'سداد لـ {payment.supplier}',
        supplier=payment.supplier,
    )
    JournalLine.objects.create(
        entry=je, account=credit_acct,
        debit=Decimal('0'), credit=amount,
        description=f'دفع {payment.get_method_display()} — {payment.payment_no}',
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'supplier-payment JE unbalanced'

    payment.status = 'POSTED'
    payment.journal_entry = je
    payment.save(update_fields=['status', 'journal_entry'])
    return je


# ============================================================
#  2b) Manufacturing wage payment (صرف مصنعيات) — Phase C
# ============================================================

def mfg_wages_accrued_balance():
    """رصيد «مصنعيات مستحقة» (2320000) الدائن الحالي = دائن − مدين (POSTED).
    موجب = لسه في مصنعية مستحقة (التزام في الميزانية)؛ صفر = اتسددت بالكامل."""
    from django.db.models import Sum
    agg = (JournalLine.objects
           .filter(account__code=SYSTEM_ACCOUNTS['MFG_WAGES_ACCRUED'],
                   entry__status='POSTED')
           .aggregate(d=Sum('debit'), c=Sum('credit')))
    return (agg['c'] or Decimal('0')) - (agg['d'] or Decimal('0'))


@transaction.atomic
def post_wage_payment(payment: ManufacturingWagePayment, user=None):
    """ترحيل سند صرف مصنعيات (شاشة «صرف مصنعيات»):
        DR  مصنعيات مستحقة (2320000)   بقدر الرصيد المستحق (حد أقصى = المبلغ)
        DR  فرق مصنعيات   (5360000)    أي زيادة فوق المستحق
        CR  النقدية/البنك               المبلغ كامل
    لو المبلغ أقل من المستحق، الباقي يفضل رصيد دائن في الميزانية.
    """
    if payment.status != 'DRAFT':
        raise FabricPostingError(f'سند الصرف {payment.payment_no} حالته {payment.status}، '
                                  'مش DRAFT.')
    if Decimal(payment.amount) <= 0:
        raise FabricPostingError('المبلغ لازم يكون أكبر من صفر.')

    amount = _q(payment.amount)
    accrued = mfg_wages_accrued_balance()
    accrued_portion = _q(min(amount, accrued)) if accrued > 0 else Decimal('0.00')
    expense_portion = _q(amount - accrued_portion)

    je = JournalEntry.objects.create(
        date=payment.date,
        reference=payment.payment_no,
        description=f'صرف مصنعيات — {payment.payee or payment.payment_no}',
        status='POSTED',
        source_doc_type='ManufacturingWagePayment',
        source_doc_id=payment.id,
        created_by=user,
    )
    accrued_acct = get_system_account('MFG_WAGES_ACCRUED')
    expense_acct = get_system_account('MFG_WAGES_EXPENSE')

    if payment.cash_account_id:
        credit_acct = payment.cash_account.gl_account
    elif payment.method == 'BANK':
        credit_acct = get_system_account('BANK')
    else:  # CASH or CHEQUE → cash on hand (cheques tracked via reference)
        credit_acct = get_system_account('CASH')

    if accrued_portion > 0:
        JournalLine.objects.create(
            entry=je, account=accrued_acct,
            debit=accrued_portion, credit=Decimal('0'),
            description=f'سداد مصنعيات مستحقة — {payment.payment_no}',
        )
    if expense_portion > 0:
        JournalLine.objects.create(
            entry=je, account=expense_acct,
            debit=expense_portion, credit=Decimal('0'),
            description=f'فرق مصنعيات (زيادة عن المستحق) — {payment.payment_no}',
        )
    JournalLine.objects.create(
        entry=je, account=credit_acct,
        debit=Decimal('0'), credit=amount,
        description=f'صرف {payment.get_method_display()} — {payment.payment_no}',
    )
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'wage-payment JE unbalanced'

    payment.status = 'POSTED'
    payment.accrued_portion = accrued_portion
    payment.expense_portion = expense_portion
    payment.journal_entry = je
    payment.save(update_fields=['status', 'accrued_portion', 'expense_portion',
                                'journal_entry'])
    return je


# ============================================================
#  6) Production order: release + cancel
# ============================================================

@transaction.atomic
def release_production_order(order: ProductionOrder, user=None):
    """Release a production order:
      1. Validate every FabricUsage has enough kg in stock on its batch.
      2. Snapshot cost_per_kg on each usage.
      3. Create one ISSUE_TO_PRODUCTION FabricMovement per usage.
      4. Decrement batch.in_stock_qty_kg.
      5. Post a JE: DR WIP / CR Fabric Inventory (total fabric value).
      6. Set order.status=RELEASED.
    """
    if order.status != 'DRAFT':
        raise FabricPostingError(
            f'أمر الإنتاج {order.order_no} حالته {order.status}، مش DRAFT.'
        )

    usages = list(order.fabric_usages.select_related('batch').all())
    if not usages:
        raise FabricPostingError('لا يمكن إفراج أمر بدون استهلاك قماش.')

    # Validate inventory for each usage (lock batches in primary-key order to
    # avoid potential deadlocks when releasing several orders concurrently).
    batch_ids = sorted({u.batch_id for u in usages})
    locked = {b.id: b for b in
              FabricBatch.objects.select_for_update().filter(id__in=batch_ids)}

    for u in usages:
        if u.planned_qty_kg <= 0:
            raise FabricPostingError(f'كمية القماش المخططة لازم تكون أكبر من صفر '
                                      f'(دفعة {u.batch.batch_no}).')
        b = locked[u.batch_id]
        if Decimal(b.in_stock_qty_kg) < Decimal(u.planned_qty_kg):
            raise FabricPostingError(
                f'دفعة {b.batch_no}: الرصيد بالمخزن ({b.in_stock_qty_kg} كجم) '
                f'أقل من المخطط ({u.planned_qty_kg} كجم).'
            )

    total_value = Decimal('0')
    for u in usages:
        b = locked[u.batch_id]
        cpk = Decimal(b.cost_per_kg)
        u.cost_per_kg_snapshot = cpk
        # Initialize actual to planned at release time; user can revise later.
        u.actual_qty_kg = u.planned_qty_kg
        u.save(update_fields=['cost_per_kg_snapshot', 'actual_qty_kg'])

        FabricMovement.objects.create(
            batch=b,
            date=order.date,
            movement_type='ISSUE_TO_PRODUCTION',
            quantity_kg=u.planned_qty_kg,
            cost_per_kg_snapshot=cpk,
            document_type='ProductionOrder',
            document_id=order.id,
            notes=f'صرف لأمر {order.order_no} — {order.title}',
            created_by=user,
        )
        b.in_stock_qty_kg = Decimal(b.in_stock_qty_kg) - Decimal(u.planned_qty_kg)
        b.save(update_fields=['in_stock_qty_kg'])

        total_value += (Decimal(u.planned_qty_kg) * cpk).quantize(Decimal('0.01'))

    total_value = total_value.quantize(Decimal('0.01'))

    # Journal: DR WIP / CR Fabric Inventory + (DR WIP / CR AP-or-Cash for accessories)
    je = JournalEntry.objects.create(
        date=order.date,
        reference=order.order_no,
        description=f'إفراج أمر إنتاج — {order.order_no} ({order.title})',
        status='POSTED',
        source_doc_type='ProductionOrder',
        source_doc_id=order.id,
        created_by=user,
    )
    wip = get_system_account('WIP')
    fabric_inv = get_system_account('FABRIC_INVENTORY')

    # 1) Fabric leg
    JournalLine.objects.create(entry=je, account=wip,
                                 debit=total_value, credit=Decimal('0'),
                                 description=f'استهلاك قماش — {order.order_no}')
    JournalLine.objects.create(entry=je, account=fabric_inv,
                                 debit=Decimal('0'), credit=total_value,
                                 description=f'صرف للإنتاج — {order.order_no}')

    # Accessories are NOT posted at release — they have no planned qty.
    # The user enters actual_qty after production ends, and complete_production_order
    # posts the accessory cost as DR WIP / CR (AP or Cash) right before the final
    # DR Inventory / CR WIP entry.

    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'release JE unbalanced'

    order.status = 'RELEASED'
    order.released_at = timezone.now()
    order.released_by = user
    order.released_journal_entry = je
    order.save(update_fields=['status', 'released_at', 'released_by',
                              'released_journal_entry'])
    return je


@transaction.atomic
def produce_production_order(order: ProductionOrder, user=None):
    """One-step production close (خطة → مكتمل) — the "انتج" action.

    الجديد: القماش والكميات بتيجي أوتوماتيك — المستخدم ميعملش حاجة. في معاملة واحدة:
      0. بيحمّل الإكسسوارات من وصفة المنتج تلقائياً، ويتأكد إن مخزونها يكفي.
      1. بياخد نوع القماش/الخامة من المنتج الرئيسي، ويحسب الكمية المستخدمة بالهالك
         من الوصفة، ويتأكد إن المتاح بالمخزن من النوع ده يكفي.
      2. بيخصم الكمية من دفعات نفس النوع (الأقدم أولاً) بتكلفة المتوسط المرجّح
         (average) — بيسجّل FabricUsage + ISSUE_TO_PRODUCTION لكل دفعة اتخصم منها.
      3. بيضيف القطع التامة للمخزون (لكل مقاس) بتكلفة الوحدة.
      4. بيرحّل قيد واحد متوازن:
           DR WIP / CR Fabric Inventory   (قيمة القماش بالمتوسط)
           DR WIP / CR AP-or-Cash         (تكلفة كل إكسسوار)
           DR Inventory / CR WIP          (إجمالي تكلفة الإنتاج)
         الـ WIP بيتصفّى لصفر.
      5. status=COMPLETED.
    """
    from inventory.models import ItemVariant, StockMovement

    if order.status != 'DRAFT':
        raise FabricPostingError(
            f'أمر الإنتاج {order.order_no} حالته {order.get_status_display()} — لازم يكون في مرحلة خطة.'
        )
    if not order.item_id:
        raise FabricPostingError('أمر الإنتاج مش مربوط بمنتج فرعي — اختار منتج فرعي أو سيب الاسم فاضي '
                                  'عشان يتعمل تلقائياً.')

    total_pieces = order.total_pieces
    if total_pieces <= 0:
        raise FabricPostingError('مفيش كميات مقاسات مسجلة. ادخل الكميات قبل الإنتاج.')

    # ---- الإكسسوارات: تتحمّل تلقائياً من وصفة المنتج (المستخدم ميعملش حاجة) ----
    for acc_id, qty in order.recipe_accessory_plan().items():
        qty = Decimal(qty).quantize(Decimal('0.001'))
        au = order.accessory_usages.filter(accessory_id=acc_id).first()
        if au is None:
            order.accessory_usages.create(accessory_id=acc_id, actual_qty=qty,
                                          notes='')
        elif not au.is_posted and Decimal(au.actual_qty or 0) <= 0:
            au.actual_qty = qty
            au.save(update_fields=['actual_qty'])

    accessory_usages = list(order.accessory_usages.select_related('accessory').all())

    # تأكد إن رصيد المخزون من كل إكسسوار يكفي الكمية المستهلكة (بند 9).
    short_acc = []
    for a in accessory_usages:
        if a.is_posted:
            continue
        need = Decimal(a.actual_qty or 0)
        have = Decimal(a.accessory.current_stock or 0)
        if need > have:
            short_acc.append(f'{a.accessory.name_ar} (متاح {have} {a.accessory.unit}، '
                             f'مطلوب {need})')
    if short_acc:
        raise FabricPostingError(
            'مفيش رصيد كافي من الإكسسوارات دي — اشتريها الأول من "مشتريات الإكسسوارات": '
            + '، '.join(short_acc) + '.'
        )

    # ---- القماش: ييجي تلقائياً من خامة المنتج الرئيسي + وصفته (المستخدم ميعملش حاجة) ----
    p = order.main_product
    if not p:
        raise FabricPostingError('الأمر مش مربوط بمنتج رئيسي له وصفة. اربط المنتج الفرعي '
                                 'بمنتج رئيسي معرّف له خامة ووصفة مقاسات الأول.')
    if not p.fabric_type_id:
        raise FabricPostingError(f'المنتج «{p.name_ar}» مالوش نوع قماش/خامة محدّد — '
                                 'حدّد الخامة على المنتج الرئيسي الأول.')
    if not order.has_recipe:
        raise FabricPostingError(
            f'المنتج «{p.name_ar}» مالوش وصفة للمقاسات اللي في الأمر — '
            'عرّف وصفة المقاسات (كمية القماش للمقاس) على المنتج الأول.'
        )

    need = order.recipe_actual_fabric_kg  # الكمية المستخدمة بالهالك — اللي بتتخصم فعلياً
    if need <= 0:
        raise FabricPostingError('كمية القماش المحسوبة من الوصفة = صفر — راجع وصفة المقاسات.')

    ft = p.fabric_type
    # لون القماش بييجي من المنتج الفرعي — الخصم بيكون من دفعات نفس اللون بس
    # (لو المنتج الفرعي مالوش لون، بنخصم من كل الألوان — توافق مع بيانات قديمة).
    color = order.fabric_color
    color_txt = f' (لون {color.name_ar})' if color else ''
    available = fabric_available_kg(ft, color)
    if available < need:
        raise FabricPostingError(
            f'القماش/الخامة «{ft.name_ar}»{color_txt}: المتاح بالمخزن ({available} كجم) أقل من '
            f'المطلوب للإنتاج بالهالك ({need} كجم). اشترِ قماش الأول من "مشتريات القماش".'
        )

    # المتوسط المرجّح لسعر الكيلو عبر دفعات نفس النوع/اللون = تكلفة الـ average
    # للإنتاج (مش تكلفة دفعة بعينها). ده اللي بيتسجّل كـ snapshot ويحسب قيمة القماش.
    avg_cost = fabric_avg_cost(ft, color)
    factor = Decimal('1') + (Decimal(p.waste_pct or 0) / Decimal('100'))

    # امسح أي بنود استهلاك قديمة (هتتولّد من جديد) — الأمر لسه DRAFT.
    order.fabric_usages.all().delete()

    # اخصم المطلوب من الدفعات المتاحة من نفس النوع/اللون — الأقدم أولاً (FIFO فعلي).
    batch_qs = (FabricBatch.objects.select_for_update()
                .filter(fabric_type_id=ft.pk, in_stock_qty_kg__gt=0))
    if color is not None:
        batch_qs = batch_qs.filter(color_id=color.pk)
    batches = list(batch_qs.order_by('purchase_date', 'id'))
    remaining = need
    total_fabric_value = Decimal('0')
    for b in batches:
        if remaining <= 0:
            break
        avail = Decimal(b.in_stock_qty_kg or 0)
        draw = (avail if avail < remaining else remaining).quantize(Decimal('0.001'))
        if draw <= 0:
            continue
        before_share = (draw / factor).quantize(Decimal('0.001')) if factor > 0 else draw
        FabricUsage.objects.create(
            order=order, fabric_type=ft, batch=b,
            planned_qty_kg=before_share, actual_qty_kg=draw,
            cost_per_kg_snapshot=avg_cost, notes='تلقائي من خامة المنتج',
        )
        FabricMovement.objects.create(
            batch=b, date=order.date, movement_type='ISSUE_TO_PRODUCTION',
            quantity_kg=draw, cost_per_kg_snapshot=avg_cost,
            document_type='ProductionOrder', document_id=order.id,
            notes=f'صرف لأمر {order.order_no} — {order.title}',
            created_by=user,
        )
        b.in_stock_qty_kg = avail - draw
        b.save(update_fields=['in_stock_qty_kg'])
        total_fabric_value += draw * avg_cost
        remaining -= draw

    if remaining > Decimal('0.001'):
        raise FabricPostingError(
            f'القماش/الخامة «{ft.name_ar}»: مقدرش يخصم كل المطلوب ({need} كجم) — '
            f'فاضل {remaining} كجم. راجع رصيد دفعات القماش.'
        )

    total_fabric_value = total_fabric_value.quantize(Decimal('0.01'))

    # total_cost = fabric value (just-saved actuals) + actual accessory cost + labor.
    total_cost = order.total_cost
    # تكلفة الوحدة المتوسطة — احتياطي للمقاسات اللي مالهاش وصفة بس.
    cost_per_piece = (total_cost / Decimal(total_pieces)).quantize(Decimal('0.0001'))

    # تكلفة كل مقاس لوحده (قماش+إكسسوار+مصنعية بوصفته) — مش متوسط موحّد.
    # Σ(تكلفة المقاس × كميته) = إجمالي تكلفة الأمر بالظبط.
    size_costs = order.recipe_cost_by_size()
    unit_by_code = {row['code']: row['unit'] for row in size_costs.values()}

    # Add finished goods to inventory, aggregated by size code, each at its OWN cost.
    by_size = {}
    for s in order.sizes.select_related('size').all():
        if s.quantity > 0:
            by_size[s.size.code] = by_size.get(s.size.code, 0) + s.quantity
    item = order.item
    for size_label, qty in by_size.items():
        unit_cost = unit_by_code.get(size_label, cost_per_piece)
        variant, created = ItemVariant.objects.get_or_create(item=item, size=size_label)
        StockMovement.objects.create(
            variant=variant,
            date=timezone.now().date(),
            movement_type='OPENING' if created and variant.current_stock == 0 else 'PURCHASE_IN',
            quantity=qty,
            unit_cost=unit_cost,
            document_type='ProductionOrder',
            document_id=order.id,
            notes=f'إنتاج — أمر {order.order_no} — مقاس {size_label}',
            created_by=user,
        ).apply_to_variant()

    # One combined, balanced journal entry.
    je = JournalEntry.objects.create(
        date=timezone.now().date(),
        reference=order.order_no,
        description=f'إنتاج أمر — {order.order_no} ({order.title})',
        status='POSTED',
        source_doc_type='ProductionOrder',
        source_doc_id=order.id,
        created_by=user,
    )
    wip = get_system_account('WIP')
    fabric_inv = get_system_account('FABRIC_INVENTORY')
    inventory = get_system_account('INVENTORY')

    # 1) Fabric: DR WIP / CR Fabric Inventory
    JournalLine.objects.create(entry=je, account=wip,
                                 debit=total_fabric_value, credit=Decimal('0'),
                                 description=f'استهلاك قماش — {order.order_no}')
    JournalLine.objects.create(entry=je, account=fabric_inv,
                                 debit=Decimal('0'), credit=total_fabric_value,
                                 description=f'صرف للإنتاج — {order.order_no}')

    # 2) Accessories: DR WIP / CR Accessory Inventory (consume from stock).
    acc_inv = get_system_account('ACCESSORY_INVENTORY')
    for a in order.accessory_usages.select_related('accessory').all():
        if a.is_posted or not a.actual_qty:
            continue
        cost = a.total_cost
        if cost <= 0:
            continue
        JournalLine.objects.create(
            entry=je, account=wip,
            debit=cost, credit=Decimal('0'),
            description=f'إكسسوار {a.accessory.name_ar} — {order.order_no}',
        )
        JournalLine.objects.create(
            entry=je, account=acc_inv,
            debit=Decimal('0'), credit=cost,
            description=f'صرف إكسسوار للإنتاج — {a.accessory.name_ar}',
        )
        # خصم الكمية من رصيد مخزون الإكسسوار
        acc = Accessory.objects.select_for_update().get(pk=a.accessory_id)
        acc.current_stock = Decimal(acc.current_stock or 0) - Decimal(a.actual_qty or 0)
        acc.save(update_fields=['current_stock'])
        a.is_posted = True
        a.save(update_fields=['is_posted'])

    # 2b) Labor (مصنعية): رسملة المصنعية في تكلفة المخزون مقابل استحقاق في الميزانية.
    #     DR WIP / CR مصنعيات مستحقة (2320000). بتتدفع لاحقاً من شاشة «صرف مصنعيات».
    labor_total = _q(order.recipe_labor_cost)
    if labor_total > 0:
        mfg_accrued = get_system_account('MFG_WAGES_ACCRUED')
        JournalLine.objects.create(
            entry=je, account=wip,
            debit=labor_total, credit=Decimal('0'),
            description=f'مصنعية — {order.order_no}',
        )
        JournalLine.objects.create(
            entry=je, account=mfg_accrued,
            debit=Decimal('0'), credit=labor_total,
            description=f'استحقاق مصنعيات — {order.order_no}',
        )

    # 3) Transfer WIP → Finished Goods (full total_cost)
    JournalLine.objects.create(entry=je, account=inventory,
                                 debit=total_cost, credit=Decimal('0'),
                                 description=f'إنتاج تام — {order.order_no}')
    JournalLine.objects.create(entry=je, account=wip,
                                 debit=Decimal('0'), credit=total_cost,
                                 description=f'تصفية WIP — {order.order_no}')

    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'produce JE unbalanced'

    now = timezone.now()
    order.status = 'COMPLETED'
    order.released_at = now
    order.released_by = user
    order.released_journal_entry = je
    order.completed_at = now
    order.completed_by = user
    order.completed_journal_entry = je
    order.save(update_fields=['status', 'released_at', 'released_by', 'released_journal_entry',
                              'completed_at', 'completed_by', 'completed_journal_entry'])
    return je


# ============================================================
#  6a-bis) Refresh the PLANNED fabric-usage row at SAVE time (round-5)
# ============================================================

@transaction.atomic
def refresh_planned_fabric_usage(order: ProductionOrder):
    """يعبّي جدول «استهلاكات القماش» في صفحة الأمر وقت الحفظ — مش بس وقت «انتج».

    بيمسح أي بنود مخططة قديمة ويعيد إنشاء صفّ واحد (batch=None) محسوب من خامة
    المنتج الرئيسي ووصفته:
      planned_qty_kg = القماش قبل الهالك،
      actual_qty_kg  = القماش بالهالك،
      cost_per_kg_snapshot = متوسط سعر الكيلو للنوع (للعرض فقط — مفيش خصم فعلي).

    بيشتغل في مرحلة الخطة (DRAFT) بس. وقت «انتج» الدالة produce_production_order
    بتمسح كل البنود دي وتعيد إنشاءها بالخصم الفعلي من الدفعات (FIFO) — فمفيش
    تعارض ولا خصم مزدوج (الصف المخطط batch=None ومش بيأثّر على رصيد المخزون).
    """
    if order.status != 'DRAFT':
        return
    # امسح أي بنود مخططة قديمة قبل ما نعيد الحساب.
    order.fabric_usages.all().delete()
    p = order.main_product
    if not p or not p.fabric_type_id or not order.has_recipe:
        return
    before = order.recipe_planned_fabric_kg
    after = order.recipe_actual_fabric_kg
    if before <= 0 and after <= 0:
        return
    ft = p.fabric_type
    FabricUsage.objects.create(
        order=order, fabric_type=ft, batch=None,
        planned_qty_kg=before, actual_qty_kg=after,
        cost_per_kg_snapshot=fabric_avg_cost(ft, order.fabric_color),
        notes='مخطط من وصفة المنتج (قبل الإنتاج)',
    )


# ============================================================
#  6b) Apply product recipe (BOM) to a production order (Phase 3/B)
# ============================================================

@transaction.atomic
def apply_recipe_to_order(order: ProductionOrder, user=None, overwrite=False):
    """يحمّل الإكسسوارات من وصفة المنتج الرئيسي إلى أمر الإنتاج، ويعرض المتوقع
    من القماش (مرحلة الخطة فقط):

      - القماش: ييجي تلقائياً وقت "انتج" من خامة المنتج الرئيسي ووصفته — مفيش
        إدخال يدوي. هنا بنعرض الكمية قبل الهالك وبالهالك كمعلومة + تنبيه لو
        المتاح بالمخزن أقل من المطلوب.
      - الإكسسوارات: ينشئ/يحدّث بنود استهلاك الإكسسوارات من الوصفة
        (الكمية = Σ كمية الإكسسوار للقطعة × عدد قطع كل مقاس).

    overwrite=False بيحافظ على أي قيم أدخلها المستخدم بنفسه (مش بيمسحها).
    بيرجّع dict ملخّص: planned_kg / actual_kg / labor_cost / fabric_applied /
    acc_created / acc_updated / warnings.
    """
    if order.status != 'DRAFT':
        raise FabricPostingError(
            f'أمر الإنتاج {order.order_no} مش في مرحلة خطة — مينفعش تحمّل الوصفة عليه.'
        )
    if not order.main_product:
        raise FabricPostingError(
            'الأمر مش مربوط بمنتج رئيسي له وصفة. اختار منتج فرعي تابع لمنتج '
            'معرّف له وصفة مقاسات الأول.'
        )
    if order.total_pieces <= 0:
        raise FabricPostingError('ادخل كميات المقاسات الأول قبل ما تحمّل الوصفة.')
    if not order.has_recipe:
        raise FabricPostingError(
            f'المنتج «{order.main_product.name_ar}» مالوش وصفة للمقاسات اللي في الأمر — '
            'عرّف وصفة المقاسات على المنتج الأول.'
        )

    summary = {
        'planned_kg': order.recipe_planned_fabric_kg,
        'actual_kg': order.recipe_actual_fabric_kg,
        'labor_cost': order.recipe_labor_cost,
        'fabric_applied': False,
        'acc_created': 0,
        'acc_updated': 0,
        'warnings': [],
    }

    missing = order.recipe_sizes_without_recipe
    if missing:
        summary['warnings'].append('مقاسات مالهاش وصفة (اتحسبتش): ' + '، '.join(missing) + '.')

    # ----- القماش: ييجي تلقائياً وقت الإنتاج من خامة المنتج — مفيش إدخال يدوي -----
    # بنعرض المتوقع من الوصفة كمعلومة بس (قبل الهالك / بالهالك)، والخصم الفعلي
    # بيحصل وقت "انتج" من دفعات نفس النوع بتكلفة المتوسط.
    summary['fabric_applied'] = True
    p = order.main_product
    if not p.fabric_type_id:
        summary['warnings'].append(
            'المنتج الرئيسي مالوش نوع قماش/خامة محدّد — حدّد الخامة عشان القماش '
            'يتخصم تلقائياً وقت الإنتاج.'
        )
    else:
        color = order.fabric_color
        color_txt = f' (لون {color.name_ar})' if color else ''
        if color is None:
            summary['warnings'].append(
                'المنتج الفرعي مالوش «لون قماش» محدّد — الخصم هيتم من كل ألوان الخامة. '
                'الأفضل تحدّد اللون على المنتج الفرعي عشان الخصم يبقى من نفس اللون.'
            )
        avail = fabric_available_kg(p.fabric_type, color)
        if avail < summary['actual_kg']:
            summary['warnings'].append(
                f'المتاح من «{p.fabric_type.name_ar}»{color_txt} ({avail} كجم) أقل من المطلوب '
                f'بالهالك ({summary["actual_kg"]} كجم) — اشترِ قماش قبل الإنتاج.'
            )

    # اعرض صفّ الاستهلاك المخطط في جدول «استهلاكات القماش» على طول.
    refresh_planned_fabric_usage(order)

    # ----- الإكسسوارات -----
    for acc_id, qty in order.recipe_accessory_plan().items():
        qty = Decimal(qty).quantize(Decimal('0.001'))
        au = order.accessory_usages.filter(accessory_id=acc_id).first()
        if au is None:
            order.accessory_usages.create(accessory_id=acc_id, actual_qty=qty,
                                          notes='')
            summary['acc_created'] += 1
        elif au.is_posted:
            continue
        elif overwrite or Decimal(au.actual_qty or 0) <= 0:
            au.actual_qty = qty
            au.save(update_fields=['actual_qty'])
            summary['acc_updated'] += 1

    return summary


@transaction.atomic
def cancel_production_order(order: ProductionOrder, user=None):
    """Cancel a production order.
      - DRAFT: just flip status.
      - RELEASED: reverse all fabric movements (put kg back), reverse JE.
      - COMPLETED: NOT supported (would need to also reverse finished goods).
    """
    if order.status == 'CANCELLED':
        return
    if order.status == 'COMPLETED':
        raise FabricPostingError(
            'لا يمكن إلغاء أمر إنتاج مكتمل — يجب إلغاء الإكمال أولاً.'
        )

    if order.status == 'RELEASED':
        # Reverse fabric movements
        usages = list(order.fabric_usages.select_related('batch').all())
        batch_ids = sorted({u.batch_id for u in usages})
        locked = {b.id: b for b in
                  FabricBatch.objects.select_for_update().filter(id__in=batch_ids)}

        for u in usages:
            b = locked[u.batch_id]
            FabricMovement.objects.create(
                batch=b,
                date=timezone.now().date(),
                movement_type='ADJUST_IN',
                quantity_kg=u.planned_qty_kg,
                cost_per_kg_snapshot=u.cost_per_kg_snapshot,
                document_type='ProductionOrder',
                document_id=order.id,
                notes=f'إلغاء إفراج أمر {order.order_no} — إعادة القماش',
                created_by=user,
            )
            b.in_stock_qty_kg = Decimal(b.in_stock_qty_kg) + Decimal(u.planned_qty_kg)
            b.save(update_fields=['in_stock_qty_kg'])

        # Reverse JE
        if order.released_journal_entry_id:
            original = order.released_journal_entry
            reverse_je = JournalEntry.objects.create(
                date=timezone.now().date(),
                reference=f'إلغاء {order.order_no}',
                description=f'عكس قيد إفراج — {order.order_no}',
                status='POSTED',
                source_doc_type='ProductionOrder',
                source_doc_id=order.id,
                created_by=user,
            )
            for line in original.lines.all():
                JournalLine.objects.create(
                    entry=reverse_je, account=line.account,
                    debit=line.credit, credit=line.debit,  # swap
                    description=f'عكس: {line.description}',
                )
            reverse_je.recalc_totals()

    order.status = 'CANCELLED'
    order.save(update_fields=['status'])
    return order


# ============================================================
#  7) Complete production order (Phase 2d)
# ============================================================

@transaction.atomic
def complete_production_order(order: ProductionOrder, user=None):
    """Final closing of a production order.
      1. Validate: status=RELEASED, has size rows with actual_quantity > 0,
         linked to an Item.
      2. Aggregate actual_quantity per size (sum across all sub-models).
      3. For each (item, size) pair: get_or_create ItemVariant,
         update current_stock + WAC using cost_per_piece.
      4. Post JE: DR INVENTORY (1310000) / CR WIP (1320000) for total_cost.
      5. Set status=COMPLETED.

    Note: Phase 2 simplification — we ignore sub-model colors when aggregating
    to ItemVariants (which only have size, not color). If we ever model
    colored variants we'll revisit.
    """
    from inventory.models import ItemVariant, StockMovement

    if order.status != 'RELEASED':
        raise FabricPostingError(
            f'لا يمكن ترحيل أمر إنتاج حالته {order.status} — لازم RELEASED.'
        )
    if not order.item_id:
        raise FabricPostingError('أمر الإنتاج مش مربوط بمنتج فرعي — اختار منتج فرعي أو سيب title فاضي '
                                  'عشان يتعمل تلقائياً.')

    total_actual = order.total_pieces
    if total_actual <= 0:
        raise FabricPostingError(
            'مفيش كميات مسجلة. ادخل الكميات لكل مقاس قبل الترحيل النهائي.'
        )

    total_cost = order.total_cost
    cost_per_piece = (total_cost / Decimal(total_actual)).quantize(Decimal('0.0001'))

    # Aggregate quantity by size code (sum across sub-models)
    by_size = {}
    for s in order.sizes.select_related('size').all():
        if s.quantity > 0:
            by_size[s.size.code] = by_size.get(s.size.code, 0) + s.quantity

    item = order.item

    for size_label, qty in by_size.items():
        variant, created = ItemVariant.objects.get_or_create(
            item=item, size=size_label,
        )
        StockMovement.objects.create(
            variant=variant,
            date=timezone.now().date(),
            movement_type='OPENING' if created and variant.current_stock == 0 else 'PURCHASE_IN',
            quantity=qty,
            unit_cost=cost_per_piece,
            document_type='ProductionOrder',
            document_id=order.id,
            notes=f'إنتاج نهائي — أمر {order.order_no} — مقاس {size_label}',
            created_by=user,
        ).apply_to_variant()

    # Journal: post any unposted accessory costs as DR WIP / CR (AP or Cash),
    # then transfer the full WIP balance for this order to Finished Goods.
    je = JournalEntry.objects.create(
        date=timezone.now().date(),
        reference=f'{order.order_no} (ترحيل نهائي)',
        description=f'استلام إنتاج نهائي — {order.order_no} ({order.title})',
        status='POSTED',
        source_doc_type='ProductionOrder',
        source_doc_id=order.id,
        created_by=user,
    )
    inventory = get_system_account('INVENTORY')
    wip = get_system_account('WIP')
    ap = get_system_account('AP')
    cash = get_system_account('CASH')

    # 1) Post unposted accessory usages (DR WIP / CR AP-or-Cash)
    # Cost + supplier come from the Accessory master, not from the usage row.
    for a in order.accessory_usages.select_related('accessory', 'accessory__supplier').all():
        if a.is_posted or not a.actual_qty:
            continue
        cost = a.total_cost
        if cost <= 0:
            continue
        JournalLine.objects.create(
            entry=je, account=wip,
            debit=cost, credit=Decimal('0'),
            description=f'إكسسوار {a.accessory.name_ar} — {order.order_no}',
        )
        sup = a.accessory.supplier
        if sup:
            JournalLine.objects.create(
                entry=je, account=ap,
                debit=Decimal('0'), credit=cost,
                description=f'إكسسوار آجل من {sup.name} ({a.accessory.name_ar})',
                supplier=sup,
            )
        else:
            JournalLine.objects.create(
                entry=je, account=cash,
                debit=Decimal('0'), credit=cost,
                description=f'إكسسوار كاش — {a.accessory.name_ar}',
            )
        a.is_posted = True
        a.save(update_fields=['is_posted'])

    # 2) Transfer WIP → Finished Goods (full total_cost)
    JournalLine.objects.create(entry=je, account=inventory,
                                 debit=total_cost, credit=Decimal('0'),
                                 description=f'إنتاج نهائي — {order.order_no}')
    JournalLine.objects.create(entry=je, account=wip,
                                 debit=Decimal('0'), credit=total_cost,
                                 description=f'تصفية WIP — {order.order_no}')
    je.recalc_totals()
    assert je.total_debit == je.total_credit, 'completion JE unbalanced'

    order.status = 'COMPLETED'
    order.completed_at = timezone.now()
    order.completed_by = user
    order.completed_journal_entry = je
    order.save(update_fields=['status', 'completed_at', 'completed_by',
                              'completed_journal_entry'])
    return je
