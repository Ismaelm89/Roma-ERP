"""Opening-balances posting services (الأرصدة الافتتاحية).

Lets the user enter starting balances through manual screens.  Every opening
balance posts ONE leg to the real account (AR / AP / Inventory / Fabric / Cash /
fixed-asset GL) and the OTHER leg to "حساب الأرصدة الافتتاحية" / Opening Balance
Equity (3310000).  After all balances are entered the *finalize* step splits the
net OBE balance into:

    - رأس المال / Capital (3110000) ........... the amount on the commercial register
    - جاري الشريك / Partner Current (3120000) .. the remainder (the balancing plug)

All postings are IDEMPOTENT: each "kind" owns a ``source_doc_type`` tag; re-posting
deletes the previous opening entry/entries for that kind first, then re-creates
them from the freshly-submitted values.  So the screens can be edited and saved
again as many times as needed until the books are right.

A dedicated, non-login user ("الأرصدة الافتتاحية") is the author (``created_by``)
of every opening journal entry, so opening entries stay clearly segregated.  The
user is inactive and has an unusable password — it can never be logged into.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .account_codes import get_system_account
from .models import Account, JournalEntry, JournalLine


class OpeningError(Exception):
    """Business-rule failure surfaced to the user during opening-balance entry."""


def _q(v):
    return Decimal(v or 0).quantize(Decimal('0.01'))


# ------------------------------------------------------------------
#  Dedicated opening-balances user (attribution only — cannot log in)
# ------------------------------------------------------------------

OPENING_USERNAME = 'opening_balances'


def get_opening_user():
    """Return (creating once) the dedicated opening-balances user."""
    User = get_user_model()
    user = User.objects.filter(username=OPENING_USERNAME).first()
    if user:
        return user
    user = User(
        username=OPENING_USERNAME,
        first_name='الأرصدة الافتتاحية',
        is_active=False,
        is_staff=False,
        is_superuser=False,
    )
    user.set_unusable_password()
    user.save()
    return user


# ------------------------------------------------------------------
#  Source-doc tags (one per kind) + idempotency helper
# ------------------------------------------------------------------

SRC = {
    'customers': 'Opening:Customers',
    'suppliers': 'Opening:Suppliers',
    'cash':      'Opening:Cash',
    'assets':    'Opening:Assets',
    'inventory':   'Opening:Inventory',
    'accessories': 'Opening:Accessories',
    'fabric':      'Opening:Fabric',
    'finalize':    'Opening:Finalize',
}


def _delete_opening(source_doc_type):
    """Remove any previously-posted opening JE(s) of this kind (idempotency).

    Deleting a JournalEntry cascades to its JournalLines.
    """
    JournalEntry.objects.filter(source_doc_type=source_doc_type).delete()


def _obe_net_credit():
    """Net credit balance of the Opening-Balance-Equity account (credit − debit)."""
    obe = get_system_account('OPENING_EQUITY')
    agg = (JournalLine.objects
           .filter(account=obe, entry__status='POSTED')
           .aggregate(d=Sum('debit'), c=Sum('credit')))
    return (agg['c'] or Decimal('0')) - (agg['d'] or Decimal('0'))


# ------------------------------------------------------------------
#  1) Customer opening balances — DR AR (tagged) / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_customers_opening(rows, date=None):
    """rows: iterable of (customer, amount).

    A positive amount = the customer owes us at opening (normal debit balance);
    a negative amount = the customer has a credit balance (advance/overpayment).
    """
    user = get_opening_user()
    date = date or timezone.now().date()
    ar = get_system_account('AR')
    obe = get_system_account('OPENING_EQUITY')

    _delete_opening(SRC['customers'])

    clean = [(c, _q(amt)) for c, amt in rows if _q(amt) != 0]
    if not clean:
        return None

    total = sum((amt for _, amt in clean), Decimal('0'))
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — عملاء',
        description='أرصدة افتتاحية للعملاء',
        status='POSTED', source_doc_type=SRC['customers'], source_doc_id=0,
        created_by=user,
    )
    for cust, amt in clean:
        JournalLine.objects.create(
            entry=je, account=ar,
            debit=amt if amt > 0 else Decimal('0'),
            credit=-amt if amt < 0 else Decimal('0'),
            customer=cust,
            description=f'رصيد افتتاحي — {cust.name_ar}',
        )
    JournalLine.objects.create(
        entry=je, account=obe,
        debit=-total if total < 0 else Decimal('0'),
        credit=total if total > 0 else Decimal('0'),
        description='مقابل أرصدة العملاء الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('customers opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  2) Supplier opening balances — CR AP (tagged) / DR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_suppliers_opening(rows, date=None):
    """rows: iterable of (supplier, amount).

    A positive amount = we owe the supplier at opening (normal credit balance).
    """
    user = get_opening_user()
    date = date or timezone.now().date()
    ap = get_system_account('AP')
    obe = get_system_account('OPENING_EQUITY')

    _delete_opening(SRC['suppliers'])

    clean = [(s, _q(amt)) for s, amt in rows if _q(amt) != 0]
    if not clean:
        return None

    total = sum((amt for _, amt in clean), Decimal('0'))
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — موردين',
        description='أرصدة افتتاحية للموردين',
        status='POSTED', source_doc_type=SRC['suppliers'], source_doc_id=0,
        created_by=user,
    )
    for sup, amt in clean:
        JournalLine.objects.create(
            entry=je, account=ap,
            debit=-amt if amt < 0 else Decimal('0'),
            credit=amt if amt > 0 else Decimal('0'),
            supplier=sup,
            description=f'رصيد افتتاحي — {sup.name}',
        )
    JournalLine.objects.create(
        entry=je, account=obe,
        debit=total if total > 0 else Decimal('0'),
        credit=-total if total < 0 else Decimal('0'),
        description='مقابل أرصدة الموردين الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('suppliers opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  3) Cash / bank / wallet opening balances — DR cash GL / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_cash_opening(rows, date=None):
    """rows: iterable of (CashAccount, amount).  DR the account's GL / CR OBE."""
    user = get_opening_user()
    date = date or timezone.now().date()
    obe = get_system_account('OPENING_EQUITY')

    _delete_opening(SRC['cash'])

    clean = [(ca, _q(amt)) for ca, amt in rows if _q(amt) != 0]
    if not clean:
        return None

    total = sum((amt for _, amt in clean), Decimal('0'))
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — نقدية',
        description='أرصدة افتتاحية للنقدية والبنوك والمحافظ',
        status='POSTED', source_doc_type=SRC['cash'], source_doc_id=0,
        created_by=user,
    )
    for ca, amt in clean:
        if not ca.gl_account_id:
            raise OpeningError(f'الحساب "{ca.name}" مش مربوط بحساب في دليل الحسابات.')
        JournalLine.objects.create(
            entry=je, account=ca.gl_account,
            debit=amt if amt > 0 else Decimal('0'),
            credit=-amt if amt < 0 else Decimal('0'),
            description=f'رصيد افتتاحي — {ca.name}',
        )
    JournalLine.objects.create(
        entry=je, account=obe,
        debit=-total if total < 0 else Decimal('0'),
        credit=total if total > 0 else Decimal('0'),
        description='مقابل أرصدة النقدية الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('cash opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  4) Fixed-asset opening balances — DR category GL / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_assets_opening(rows, date=None):
    """rows: iterable of (name, category_code, cost) — أصل ثابت واحد لكل سطر.

    بنسجّل كل أصل في سجل الأصول الثابتة (FixedAsset) بحالة "مرحّل" ومربوط بقيد
    الافتتاح، وبنرحّل:
        DR حساب فئة الأصل (1510000 ... 1590000)   تكلفة كل أصل
        CR حساب الأرصدة الافتتاحية (OBE)            الإجمالي
    """
    from .models import FixedAsset

    user = get_opening_user()
    date = date or timezone.now().date()
    obe = get_system_account('OPENING_EQUITY')

    valid_categories = dict(FixedAsset.CATEGORY_CHOICES)

    clean = []
    for name, category, cost in rows:
        name = (name or '').strip()
        cost = _q(cost)
        if not name and cost == 0:
            continue
        if not name:
            raise OpeningError('لازم تكتب اسم الأصل الثابت لكل سطر فيه قيمة.')
        if cost <= 0:
            raise OpeningError(f'قيمة الأصل "{name}" لازم تكون أكبر من صفر.')
        if category not in valid_categories:
            raise OpeningError(f'فئة الأصل "{name}" غير صحيحة.')
        gl_code = FixedAsset.CATEGORY_GL.get(category, '1590000')
        acct = Account.objects.filter(code=gl_code).first()
        if not acct:
            raise OpeningError(f'حساب فئة الأصل {gl_code} مش موجود في دليل الحسابات.')
        clean.append((name, category, cost, acct))

    # idempotency: امسح أصول الافتتاح القديمة (المربوطة بقيد الافتتاح) قبل القيد نفسه.
    # لازم نمسح الأصول الأول وقيد الافتتاح لسه موجود (الربط بيتفك لمّا القيد يتمسح).
    prior_je_ids = list(JournalEntry.objects
                        .filter(source_doc_type=SRC['assets'])
                        .values_list('id', flat=True))
    if prior_je_ids:
        FixedAsset.objects.filter(journal_entry_id__in=prior_je_ids).delete()
    _delete_opening(SRC['assets'])

    if not clean:
        return None

    total = sum((cost for _, _, cost, _ in clean), Decimal('0'))
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — أصول ثابتة',
        description='أرصدة افتتاحية للأصول الثابتة',
        status='POSTED', source_doc_type=SRC['assets'], source_doc_id=0,
        created_by=user,
    )
    for name, category, cost, acct in clean:
        FixedAsset.objects.create(
            name=name, category=category, acquisition_date=date, cost=cost,
            payment_method='CASH', status='POSTED',
            journal_entry=je, created_by=user, notes='رصيد افتتاحي',
        )
        JournalLine.objects.create(
            entry=je, account=acct, debit=cost, credit=Decimal('0'),
            description=f'رصيد افتتاحي — {name}',
        )
    JournalLine.objects.create(
        entry=je, account=obe, debit=Decimal('0'), credit=_q(total),
        description='مقابل أرصدة الأصول الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('assets opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  5) Inventory (finished goods) opening — DR Inventory (tagged) / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_inventory_opening(submitted, date=None):
    """submitted: iterable of (variant, qty, unit_cost) for EVERY variant shown on
    the screen (a blank row => qty 0).  Sets each variant's opening stock + WAC
    directly (opening is the base balance) and posts DR Inventory (tagged) / CR OBE.

    Opening must be entered BEFORE any other stock movement; a variant that already
    has real stock history is rejected so we never clobber it.
    """
    from inventory.models import ItemVariant, StockMovement

    user = get_opening_user()
    date = date or timezone.now().date()
    inv = get_system_account('INVENTORY')
    obe = get_system_account('OPENING_EQUITY')

    submitted = list(submitted)
    touched_ids = [v.id for v, _, _ in submitted]

    # Guard: refuse if any touched variant already has non-opening stock history.
    bad = (StockMovement.objects
           .filter(variant_id__in=touched_ids)
           .exclude(document_type='Opening:Inventory')
           .values_list('variant__sku_code', flat=True))
    bad = sorted(set(bad))
    if bad:
        raise OpeningError(
            'فيه حركات مخزون فعلية على الأصناف دي — مينفعش تظبط رصيدها الافتتاحي من هنا: '
            + '، '.join(bad) + '.'
        )

    # Idempotent rebuild: drop the prior opening JE + opening movements, then zero
    # the cache on every touched variant (safe — guarded against real history).
    _delete_opening(SRC['inventory'])
    StockMovement.objects.filter(
        variant_id__in=touched_ids, document_type='Opening:Inventory'
    ).delete()
    ItemVariant.objects.filter(id__in=touched_ids).update(
        current_stock=Decimal('0'), average_cost=Decimal('0'))

    clean = [(v, Decimal(q or 0), Decimal(c or 0)) for v, q, c in submitted
             if Decimal(q or 0) > 0]
    if not clean:
        return None

    total = Decimal('0')
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — مخزون',
        description='أرصدة افتتاحية للمخزون (منتجات تامة)',
        status='POSTED', source_doc_type=SRC['inventory'], source_doc_id=0,
        created_by=user,
    )
    for v, qty, cost in clean:
        if cost < 0:
            raise OpeningError(f'تكلفة سالبة للصنف {v.sku_code}.')
        value = _q(qty * cost)
        total += value
        ItemVariant.objects.filter(pk=v.pk).update(current_stock=qty, average_cost=cost)
        StockMovement.objects.create(
            variant=v, date=date, movement_type='OPENING',
            quantity=qty, unit_cost=cost,
            document_type='Opening:Inventory', document_id=v.pk,
            notes='رصيد افتتاحي', created_by=user,
        )
        JournalLine.objects.create(
            entry=je, account=inv, debit=value, credit=Decimal('0'),
            variant=v, description=f'رصيد افتتاحي — {v.sku_code}',
        )
    JournalLine.objects.create(
        entry=je, account=obe, debit=Decimal('0'), credit=_q(total),
        description='مقابل أرصدة المخزون الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('inventory opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  5b) Accessory (raw material) opening — DR Accessory Inventory (tagged) / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_accessories_opening(submitted, date=None):
    """submitted: iterable of (Accessory, qty, unit_cost) for every accessory shown.

    Sets each accessory's opening stock + WAC directly (opening is the base
    balance) and posts DR Accessory Inventory (tagged, accessory FK) / CR OBE.
    Idempotent: re-editing drops the prior opening JE, zeroes accessories that
    were opening-only and are no longer set, then re-applies the new rows.

    Opening must be entered BEFORE any real accessory movement; an accessory that
    already has a purchase/usage history is rejected so we never clobber it.
    """
    from manufacturing.models import Accessory, AccessoryPurchase, AccessoryUsage

    user = get_opening_user()
    date = date or timezone.now().date()
    acc_inv = get_system_account('ACCESSORY_INVENTORY')
    obe = get_system_account('OPENING_EQUITY')

    # Accessories that were part of the PRIOR opening (so we can reset removed ones).
    prior_ids = set(JournalLine.objects
                    .filter(entry__source_doc_type=SRC['accessories'])
                    .exclude(accessory__isnull=True)
                    .values_list('accessory_id', flat=True))

    clean = [(a, Decimal(q or 0), Decimal(c or 0)) for a, q, c in submitted
             if Decimal(q or 0) > 0]
    clean_ids = {a.id for a, _, _ in clean}

    # Guard: any accessory we're about to (re)write must have no real movement
    # history — only opening can touch its stock.
    touched = prior_ids | clean_ids
    if touched:
        bad = set(AccessoryPurchase.objects.filter(accessory_id__in=touched)
                  .values_list('accessory__name_ar', flat=True))
        bad |= set(AccessoryUsage.objects.filter(accessory_id__in=touched)
                   .values_list('accessory__name_ar', flat=True))
        bad = sorted(b for b in bad if b)
        if bad:
            raise OpeningError(
                'فيه حركات فعلية (شراء/صرف) على الإكسسوارات دي — مينفعش تظبط رصيدها '
                'الافتتاحي من هنا: ' + '، '.join(bad) + '.')

    # Idempotent rebuild.
    _delete_opening(SRC['accessories'])
    # Reset accessories that were opening-only and are no longer set.
    for aid in (prior_ids - clean_ids):
        Accessory.objects.filter(pk=aid).update(
            current_stock=Decimal('0'), average_cost=Decimal('0'))

    if not clean:
        return None

    total = Decimal('0')
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — إكسسوارات',
        description='أرصدة افتتاحية لمخزون الإكسسوارات',
        status='POSTED', source_doc_type=SRC['accessories'], source_doc_id=0,
        created_by=user,
    )
    for a, qty, cost in clean:
        if cost < 0:
            raise OpeningError(f'تكلفة سالبة للإكسسوار {a.name_ar}.')
        value = _q(qty * cost)
        total += value
        Accessory.objects.filter(pk=a.pk).update(current_stock=qty, average_cost=cost)
        JournalLine.objects.create(
            entry=je, account=acc_inv, debit=value, credit=Decimal('0'),
            accessory=a, description=f'رصيد افتتاحي — {a.name_ar}',
        )
    JournalLine.objects.create(
        entry=je, account=obe, debit=Decimal('0'), credit=_q(total),
        description='مقابل أرصدة الإكسسوارات الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('accessories opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  6) Fabric (raw material) opening — DR Fabric Inventory (tagged) / CR OBE
# ------------------------------------------------------------------

@transaction.atomic
def post_fabric_opening(submitted, date=None):
    """submitted: iterable of (supplier, fabric_type, color, qty_kg, unit_cost).

    Creates one opening FabricBatch per non-empty row (so the fabric can be
    consumed in production later) and posts DR Fabric Inventory (tagged supplier)
    / CR OBE.  Idempotent rebuild: removes prior opening batches + movements + JE.
    """
    from manufacturing.models import FabricBatch, FabricMovement, FabricUsage

    user = get_opening_user()
    date = date or timezone.now().date()
    fab = get_system_account('FABRIC_INVENTORY')
    obe = get_system_account('OPENING_EQUITY')

    # Identify prior opening batches via their opening movements.
    prior_ids = list(FabricMovement.objects
                     .filter(document_type='Opening:Fabric')
                     .values_list('batch_id', flat=True).distinct())
    if prior_ids and FabricUsage.objects.filter(batch_id__in=prior_ids).exists():
        raise OpeningError('بعض دفعات القماش الافتتاحية اتصرفت في الإنتاج بالفعل — '
                           'مينفعش تعيد ضبط الأرصدة الافتتاحية للقماش.')
    _delete_opening(SRC['fabric'])
    FabricMovement.objects.filter(batch_id__in=prior_ids).delete()
    FabricBatch.objects.filter(id__in=prior_ids).delete()

    clean = []
    for supplier, ftype, color, qty, cost in submitted:
        qty = Decimal(qty or 0)
        cost = Decimal(cost or 0)
        if qty <= 0:
            continue
        # المورد اختياري في الأرصدة الافتتاحية — المطلوب نوع القماش واللون فقط.
        if not (ftype and color):
            raise OpeningError('لكل سطر قماش بكمية: لازم تختار نوع القماش واللون.')
        if cost < 0:
            raise OpeningError('سعر الكيلو لا يمكن أن يكون سالباً.')
        clean.append((supplier, ftype, color, qty, cost))
    if not clean:
        return None

    total = Decimal('0')
    je = JournalEntry.objects.create(
        date=date, reference='رصيد افتتاحي — أقمشة',
        description='أرصدة افتتاحية لمخزون الأقمشة',
        status='POSTED', source_doc_type=SRC['fabric'], source_doc_id=0,
        created_by=user,
    )
    for supplier, ftype, color, qty, cost in clean:
        value = _q(qty * cost)
        total += value
        batch = FabricBatch.objects.create(
            supplier=supplier, fabric_type=ftype, color=color,
            purchase_date=date, purchase_qty_kg=qty, purchase_unit_cost=cost,
            purchase_payment_method='CREDIT', in_stock_qty_kg=qty,
            is_posted=True, notes='رصيد افتتاحي', created_by=user,
        )
        FabricMovement.objects.create(
            batch=batch, date=date, movement_type='PURCHASE_IN',
            quantity_kg=qty, cost_per_kg_snapshot=cost,
            document_type='Opening:Fabric', document_id=batch.id,
            notes='رصيد افتتاحي', created_by=user,
        )
        JournalLine.objects.create(
            entry=je, account=fab, debit=value, credit=Decimal('0'),
            supplier=supplier,
            description=f'رصيد افتتاحي — {batch.batch_no} {ftype.name_ar}/{color.name_ar}',
        )
        batch.purchase_journal_entry = je
        batch.save(update_fields=['purchase_journal_entry'])
    JournalLine.objects.create(
        entry=je, account=obe, debit=Decimal('0'), credit=_q(total),
        description='مقابل أرصدة الأقمشة الافتتاحية',
    )
    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('fabric opening JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  7) Finalize — split net OBE into Capital + Partner Current
# ------------------------------------------------------------------

@transaction.atomic
def finalize_opening(registered_capital, date=None):
    """Clear the net Opening-Balance-Equity and split it into:
        - رأس المال / Capital ......... the registered amount (commercial register)
        - جاري الشريك / Partner Current  the remainder (balancing plug)
    Idempotent: a prior finalize is removed first so OBE reflects only the real
    opening legs before we re-split it.
    """
    user = get_opening_user()
    date = date or timezone.now().date()
    obe = get_system_account('OPENING_EQUITY')
    capital = get_system_account('CAPITAL')
    partner = get_system_account('PARTNER_CURRENT')

    registered_capital = _q(registered_capital)
    if registered_capital < 0:
        raise OpeningError('رأس المال المسجّل لا يمكن أن يكون سالباً.')

    # Remove a prior finalize first, so OBE reflects only the real opening legs.
    _delete_opening(SRC['finalize'])

    obe_net = _obe_net_credit()  # credit − debit
    if obe_net == 0:
        raise OpeningError('رصيد حساب الأرصدة الافتتاحية = صفر، مفيش حاجة تتقفل. '
                           'ادخل الأرصدة الافتتاحية الأول.')

    je = JournalEntry.objects.create(
        date=date, reference='إقفال الأرصدة الافتتاحية',
        description='توزيع الأرصدة الافتتاحية على رأس المال وجاري الشريك',
        status='POSTED', source_doc_type=SRC['finalize'], source_doc_id=0,
        created_by=user,
    )
    # 1) Clear OBE (normal case: it has a net credit → debit it to zero).
    if obe_net > 0:
        JournalLine.objects.create(entry=je, account=obe, debit=obe_net, credit=Decimal('0'),
                                   description='إقفال حساب الأرصدة الافتتاحية')
    else:
        JournalLine.objects.create(entry=je, account=obe, debit=Decimal('0'), credit=-obe_net,
                                   description='إقفال حساب الأرصدة الافتتاحية')
    # 2) Capital — exactly the registered amount (credit, normal equity).
    if registered_capital > 0:
        JournalLine.objects.create(entry=je, account=capital, debit=Decimal('0'),
                                   credit=registered_capital,
                                   description='رأس المال المسجّل بالسجل التجاري')
    # 3) Partner Current — the balancing remainder.
    remainder = obe_net - registered_capital
    if remainder > 0:
        JournalLine.objects.create(entry=je, account=partner, debit=Decimal('0'),
                                   credit=remainder,
                                   description='جاري الشريك — باقي الأرصدة الافتتاحية')
    elif remainder < 0:
        JournalLine.objects.create(entry=je, account=partner, debit=-remainder,
                                   credit=Decimal('0'),
                                   description='جاري الشريك — عجز عن رأس المال المسجّل')

    je.recalc_totals()
    if je.total_debit != je.total_credit:
        raise AssertionError('finalize JE unbalanced' + f' ({je.total_debit} != {je.total_credit})')
    return je


# ------------------------------------------------------------------
#  Summary for the hub page
# ------------------------------------------------------------------

def _account_credit_balance(acct):
    agg = (JournalLine.objects
           .filter(account=acct, entry__status='POSTED')
           .aggregate(d=Sum('debit'), c=Sum('credit')))
    return (agg['c'] or Decimal('0')) - (agg['d'] or Decimal('0'))


def opening_summary():
    """Snapshot for the opening-balances hub: per-kind totals + OBE + finalize state."""
    obe = get_system_account('OPENING_EQUITY')
    capital = get_system_account('CAPITAL')
    partner = get_system_account('PARTNER_CURRENT')

    def _kind_total(src):
        # Each kind's JE has exactly one OBE leg; its magnitude == the kind total.
        agg = (JournalLine.objects
               .filter(entry__source_doc_type=src, entry__status='POSTED', account=obe)
               .aggregate(d=Sum('debit'), c=Sum('credit')))
        return (agg['d'] or Decimal('0')) + (agg['c'] or Decimal('0'))

    kinds = {}
    for key in ('customers', 'suppliers', 'cash', 'assets', 'inventory',
                'accessories', 'fabric'):
        src = SRC[key]
        kinds[key] = {
            'exists': JournalEntry.objects.filter(source_doc_type=src).exists(),
            'total': _kind_total(src),
        }
    return {
        'kinds': kinds,
        'obe_net': _obe_net_credit(),
        'finalized': JournalEntry.objects.filter(source_doc_type=SRC['finalize']).exists(),
        'capital_total': _account_credit_balance(capital),
        'partner_total': _account_credit_balance(partner),
    }
