"""أدوات بوت العمليات — الحركات اليومية بس.

القاعدة: كل أداة هنا بتعمل حركة بيانات عادية (فواتير/إيصالات/إنتاج/تقارير).
مفيش أي أداة بتعدّل وصفات ولا أسعار منتجات ولا إعدادات ولا كود ولا بتحذف سجلات —
ده مقصود، عشان البوت ده ميقدرش يلخبط تكوين السيستم.

أي أداة مش في READ_ONLY بتتقفل ورا تأكيد: أول نداء بيرجّع ملخّص الحركة عشان
البوت يعرضه على المستخدم، ومبتتنفّذش غير لما المستخدم يقول تمام (confirm=true).
"""
import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


# ----------------------------------------------------------------- helpers
def money(x):
    """تنسيق أمريكي: 5,500.00 (فاصلة للآلاف، نقطة للكسر) — تفضيل المستخدم."""
    return '{:,.2f}'.format(Decimal(x or 0))


def _today():
    return timezone.now().date()


def _date(s):
    if not s:
        return _today()
    return datetime.date.fromisoformat(s)


def _customer(ref):
    from sales.models import Customer
    ref = (ref or '').strip()
    c = Customer.objects.filter(code__iexact=ref).first()
    if c:
        return c
    hits = list(Customer.objects.filter(name_ar__icontains=ref)[:6])
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f'مفيش عميل بالاسم/الكود «{ref}».')
    raise ValueError('فيه أكتر من عميل بالاسم ده، حدّد الكود: '
                     + '، '.join(f'{c.code} {c.name_ar}' for c in hits))


def _supplier(ref):
    from manufacturing.models import Supplier
    ref = (ref or '').strip()
    s = Supplier.objects.filter(code__iexact=ref).first()
    if s:
        return s
    hits = list(Supplier.objects.filter(name__icontains=ref)[:6])
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f'مفيش مورد بالاسم/الكود «{ref}».')
    raise ValueError('فيه أكتر من مورد بالاسم ده، حدّد الكود: '
                     + '، '.join(f'{s.code} {s.name}' for s in hits))


def _item(ref):
    from inventory.models import Item
    ref = (ref or '').strip()
    it = Item.objects.filter(code__iexact=ref).first()
    if it:
        return it
    hits = list(Item.objects.filter(name_ar__icontains=ref, active=True)[:8])
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f'مفيش منتج بالاسم/الكود «{ref}».')
    raise ValueError('فيه أكتر من منتج بالاسم ده، حدّد الكود: '
                     + '، '.join(f'{i.code} {i.name_ar}' for i in hits))


def _norm(s):
    return (s or '').strip().replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا') \
                    .replace('ة', 'ه').replace('ى', 'ي').upper()


def _variant(item, size):
    """بيدوّر على المقاس/اللون — بمطابقة مرنة (همزات/تاء مربوطة/حروف كبيرة)."""
    v = item.variants.filter(size=size).first()
    if v:
        return v
    target = _norm(size)
    for x in item.variants.all():
        if _norm(x.size) == target:
            return x
    have = '، '.join(x.size for x in item.variants.all()[:20]) or '—'
    raise ValueError(f'{item.name_ar}: مفيش مقاس «{size}». الموجود: {have}')


def _cash_account(ref):
    from core.models import CashAccount
    ref = (ref or '').strip()
    if not ref:
        raise ValueError('حدّد حساب الفلوس (بنك فيصل ولا الصندوق).')
    a = CashAccount.objects.filter(name__icontains=ref).first()
    if a:
        return a
    have = '، '.join(x.name for x in CashAccount.objects.all())
    raise ValueError(f'مفيش حساب اسمه «{ref}». المتاح: {have}')


# ----------------------------------------------------------------- read
def search_customers(query='', limit=15):
    from sales.models import Customer
    qs = Customer.objects.all()
    if query:
        qs = qs.filter(name_ar__icontains=query)
    rows = [f'{c.code} | {c.name_ar} | رصيد {money(c.current_balance)}'
            for c in qs[:limit]]
    return '\n'.join(rows) or 'مفيش نتايج.'


def customer_details(customer):
    from sales.models import SalesInvoice, ReceiptAllocation
    c = _customer(customer)
    out = [f'{c.code} — {c.name_ar}', f'الرصيد الحالي: {money(c.current_balance)}', '']
    out.append('الفواتير المرحّلة اللي لسه عليها متبقّي:')
    n = 0
    for inv in SalesInvoice.objects.filter(customer=c, status='POSTED').order_by('date'):
        paid = sum((Decimal(a.amount) for a in
                    ReceiptAllocation.objects.filter(invoice=inv)), Decimal('0'))
        due = Decimal(inv.grand_total) - paid
        if due > 0:
            n += 1
            out.append(f'  {inv.invoice_no} | {inv.date} | إجمالي {money(inv.grand_total)} '
                       f'| متبقّي {money(due)}')
    if not n:
        out.append('  مفيش')
    return '\n'.join(out)


def search_items(query='', limit=20):
    from inventory.models import Item
    qs = Item.objects.filter(active=True)
    if query:
        qs = qs.filter(name_ar__icontains=query)
    rows = [f'{i.code} | {i.name_ar}' for i in qs[:limit]]
    return '\n'.join(rows) or 'مفيش نتايج.'


def item_stock(item):
    it = _item(item)
    rows = [f'{it.code} — {it.name_ar}', 'المقاس | الرصيد | سعر البيع | متوسط التكلفة']
    for v in it.variants.all().order_by('size'):
        rows.append(f'  {v.size} | {money(v.current_stock)} | {money(v.selling_price)} '
                    f'| {money(v.average_cost)}')
    return '\n'.join(rows)


def list_invoices(status='', customer='', limit=15):
    from sales.models import SalesInvoice
    qs = SalesInvoice.objects.all().order_by('-date', '-id')
    if status:
        qs = qs.filter(status=status.upper())
    if customer:
        qs = qs.filter(customer=_customer(customer))
    rows = [f'{i.invoice_no} | {i.date} | {i.customer.name_ar} | '
            f'{i.get_status_display()} | {money(i.grand_total)}' for i in qs[:limit]]
    return '\n'.join(rows) or 'مفيش فواتير.'


def invoice_details(invoice_no):
    from sales.models import SalesInvoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    out = [f'{inv.invoice_no} | {inv.customer.name_ar} | {inv.date} | {inv.get_status_display()}',
           f'قبل الخصم {money(inv.subtotal)} | خصم {inv.doc_discount_percent}% '
           f'= {money(inv.doc_discount_amount)} | الإجمالي {money(inv.grand_total)}', '']
    for l in inv.lines.select_related('variant__item').all():
        out.append(f'  {l.variant.item.name_ar} | مقاس {l.variant.size} | '
                   f'{money(l.quantity)} {l.sale_unit_label} × {money(l.unit_price)} '
                   f'= {money(l.line_total)}')
    return '\n'.join(out)


def list_production_orders(status='', item='', customer='', invoiced='', limit=15):
    """أوامر الإنتاج — فلترة بالحالة/الصنف/العميل، أو اللي لسه متفوترتش."""
    from manufacturing.models import ProductionOrder
    qs = ProductionOrder.objects.select_related('item', 'customer', 'sales_invoice') \
                                .order_by('-date', '-id')
    if status:
        s = status.upper()
        aliases = {'خطة': 'DRAFT', 'مسودة': 'DRAFT', 'تم': 'COMPLETED',
                   'مكتمل': 'COMPLETED', 'ملغي': 'CANCELLED'}
        qs = qs.filter(status=aliases.get(status, s))
    if item:
        qs = qs.filter(item=_item(item))
    if customer:
        qs = qs.filter(customer=_customer(customer))
    if invoiced == 'no':
        qs = qs.filter(sales_invoice__isnull=True)
    elif invoiced == 'yes':
        qs = qs.filter(sales_invoice__isnull=False)
    rows = []
    for po in qs[:limit]:
        rows.append('%s | %s | %s | %s | %s قطعة | عميل: %s | فاتورة: %s' % (
            po.order_no, po.date, (po.item.name_ar if po.item_id else '—')[:24],
            po.get_status_display(), po.total_pieces,
            po.customer.name_ar if po.customer_id else '—',
            po.sales_invoice.invoice_no if po.sales_invoice_id else '—'))
    return '\n'.join(rows) or 'مفيش أوامر إنتاج بالشروط دي.'


def production_order_details(order_no):
    from manufacturing.models import ProductionOrder
    po = ProductionOrder.objects.get(order_no=order_no)
    out = ['%s | %s | %s | %s' % (po.order_no, po.date,
                                  po.item.name_ar if po.item_id else '—',
                                  po.get_status_display()),
           'العميل: %s | الفاتورة: %s | إجمالي القطع: %s' % (
               po.customer.name_ar if po.customer_id else '—',
               po.sales_invoice.invoice_no if po.sales_invoice_id else '—',
               po.total_pieces),
           'المقاسات:']
    for ps in po.sizes.select_related('size').all():
        out.append('  %s × %s' % (ps.size.code, ps.quantity))
    usages = po.fabric_usages.select_related('fabric_type', 'fabric_color').all()
    if usages:
        out.append('القماش:')
        for u in usages:
            out.append('  %s %s × %s' % (
                u.fabric_type.name_ar,
                u.fabric_color.name_ar if u.fabric_color_id else '',
                u.actual_qty_kg or u.planned_qty_kg))
    return '\n'.join(out)


def search_suppliers(query='', limit=15):
    from manufacturing.models import Supplier
    qs = Supplier.objects.all()
    if query:
        qs = qs.filter(name__icontains=query)
    rows = ['%s | %s | %s | رصيد %s' % (
        s.code, s.name, s.vendor_type.name_ar if s.vendor_type_id else '—',
        money(s.current_balance)) for s in qs[:limit]]
    return '\n'.join(rows) or 'مفيش نتايج.'


def list_receipts(customer='', limit=15):
    """آخر إيصالات القبض (كلها أو لعميل معيّن)."""
    from sales.models import Receipt
    qs = Receipt.objects.select_related('customer', 'cash_account') \
                        .order_by('-date', '-id')
    if customer:
        qs = qs.filter(customer=_customer(customer))
    rows = ['%s | %s | %s | %s | %s' % (
        r.receipt_no, r.date, r.customer.name_ar if r.customer_id else '—',
        money(r.amount), r.cash_account.name if r.cash_account_id else '—')
        for r in qs[:limit]]
    return '\n'.join(rows) or 'مفيش إيصالات.'


def stock_report():
    from decimal import Decimal as D
    from manufacturing.models import FabricBatch, Accessory
    from inventory.models import ItemVariant
    fab = sum((D(b.in_stock_qty_kg) * D(b.purchase_unit_cost or 0)
               for b in FabricBatch.objects.filter(is_posted=True, in_stock_qty_kg__gt=0)), D('0'))
    acc = sum((D(a.current_stock) * D(a.average_cost or 0)
               for a in Accessory.objects.filter(current_stock__gt=0)), D('0'))
    cost = sale = D('0')
    for v in ItemVariant.objects.filter(current_stock__gt=0):
        st = D(v.current_stock)
        cost += st * D(v.average_cost or 0)
        sale += st * D(v.selling_price or 0)
    return (f'قيمة القماش: {money(fab)}\nقيمة الإكسسوارات: {money(acc)}\n'
            f'المخزون التام (تكلفة): {money(cost)}\n'
            f'المخزون التام (سعر البيع): {money(sale)}\n'
            f'إجمالي المخزون بالتكلفة: {money(fab + acc + cost)}')


def balances_report(kind='customers', limit=25):
    if kind == 'suppliers':
        from manufacturing.models import Supplier
        rows, tot = [], Decimal('0')
        for s in Supplier.objects.all():
            b = Decimal(s.current_balance or 0)
            tot += b
            if b:
                rows.append((s.code, s.name, b))
    else:
        from sales.models import Customer
        rows, tot = [], Decimal('0')
        for c in Customer.objects.all():
            b = Decimal(c.current_balance or 0)
            tot += b
            if b:
                rows.append((c.code, c.name_ar, b))
    rows.sort(key=lambda r: -r[2])
    out = [f'{c} | {n} | {money(b)}' for c, n, b in rows[:limit]]
    out.append(f'— الإجمالي: {money(tot)}')
    return '\n'.join(out)


# ----------------------------------------------------------------- write
@transaction.atomic
def create_sales_invoice(customer, lines, date='', payment_type='CREDIT'):
    """lines = [{item, size, quantity, unit?}] — unit: PIECE (افتراضي) أو WHOLESALE."""
    from sales.models import SalesInvoice, SalesInvoiceLine
    c = _customer(customer)
    inv = SalesInvoice.objects.create(customer=c, date=_date(date), status='DRAFT',
                                      payment_type=(payment_type or 'CREDIT').upper())
    added, report = 0, []
    for ln in lines or []:
        it = _item(ln.get('item'))
        v = _variant(it, ln.get('size'))
        qty = Decimal(str(ln.get('quantity')))
        if qty <= 0:
            continue
        unit = (ln.get('unit') or 'PIECE').upper()
        row = SalesInvoiceLine.objects.create(invoice=inv, variant=v, sale_unit=unit,
                                              quantity=qty, unit_price=Decimal('0'))
        row.recalc()
        row.save(update_fields=['line_total'])
        added += 1
        report.append(f'  {it.name_ar} | {v.size} | {money(qty)} × {money(row.unit_price)}')
    inv.recalc_totals()
    inv.refresh_from_db()
    if not added:
        raise ValueError('مفيش بنود اتضافت — راجع الأصناف والمقاسات.')
    return (f'اتعملت مسودة {inv.invoice_no} للعميل {c.name_ar}\n'
            + '\n'.join(report)
            + f'\nعدد البنود {added} | الإجمالي {money(inv.grand_total)} (لسه مسودة)')


@transaction.atomic
def add_invoice_lines(invoice_no, lines):
    from sales.models import SalesInvoice, SalesInvoiceLine
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    if inv.status != 'DRAFT':
        raise ValueError(f'{invoice_no} مش مسودة — مينفعش تتعدّل.')
    n = 0
    for ln in lines or []:
        it = _item(ln.get('item'))
        v = _variant(it, ln.get('size'))
        row = SalesInvoiceLine.objects.create(
            invoice=inv, variant=v, sale_unit=(ln.get('unit') or 'PIECE').upper(),
            quantity=Decimal(str(ln.get('quantity'))), unit_price=Decimal('0'))
        row.recalc()
        row.save(update_fields=['line_total'])
        n += 1
    inv.recalc_totals()
    inv.refresh_from_db()
    return f'اتضاف {n} بند لـ {invoice_no} | الإجمالي بقى {money(inv.grand_total)}'


@transaction.atomic
def remove_invoice_lines(invoice_no, item='', size=''):
    """بيشيل بنود من مسودة — بالصنف و/أو المقاس (مثلاً: شيل مقاس L)."""
    from sales.models import SalesInvoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    if inv.status != 'DRAFT':
        raise ValueError(f'{invoice_no} مش مسودة — مينفعش تتعدّل.')
    qs = inv.lines.all()
    if item:
        qs = qs.filter(variant__item=_item(item))
    if size:
        qs = qs.filter(variant__size=size)
    if not qs.exists():
        raise ValueError('مفيش بنود مطابقة للشرط ده.')
    removed = [f'{l.variant.item.name_ar} مقاس {l.variant.size} × {money(l.quantity)}'
               for l in qs]
    qs.delete()
    inv.recalc_totals()
    inv.refresh_from_db()
    return ('اتشال:\n  ' + '\n  '.join(removed)
            + f'\nالإجمالي بقى {money(inv.grand_total)}')


@transaction.atomic
def set_invoice_discount(invoice_no, percent):
    from sales.models import SalesInvoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    if inv.status != 'DRAFT':
        raise ValueError(f'{invoice_no} مش مسودة — الخصم بيتحط قبل الترحيل.')
    inv.doc_discount_percent = Decimal(str(percent))
    inv.recalc_totals()
    inv.doc_discount_percent = Decimal(str(percent))     # recalc مبيحفظش النسبة
    inv.save(update_fields=['doc_discount_percent'])
    inv.refresh_from_db()
    return (f'{invoice_no}: خصم {percent}% = {money(inv.doc_discount_amount)} | '
            f'قبل {money(inv.subtotal)} → بعد {money(inv.grand_total)}')


def check_invoice_stock(invoice_no):
    """بيقول البنود اللي رصيدها مش كفاية قبل الترحيل."""
    from collections import defaultdict
    from sales.models import SalesInvoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    need = defaultdict(Decimal)
    for l in inv.lines.all():
        need[l.variant_id] += Decimal(l.total_pieces)
    short, seen = [], set()
    for l in inv.lines.select_related('variant__item').all():
        if l.variant_id in seen:
            continue
        seen.add(l.variant_id)
        av = Decimal(l.variant.current_stock or 0)
        if av < need[l.variant_id]:
            short.append(f'  {l.variant.item.name_ar} مقاس {l.variant.size} — '
                         f'مطلوب {money(need[l.variant_id])} / متاح {money(av)}')
    if not short:
        return 'كل البنود رصيدها كفاية ✓'
    return 'بنود رصيدها ناقص:\n' + '\n'.join(short)


def post_invoice(invoice_no):
    from sales.models import SalesInvoice
    from sales.services import post_sales_invoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    short = check_invoice_stock(invoice_no)
    if short != 'كل البنود رصيدها كفاية ✓':
        return 'مش هيترحّل — ' + short
    with transaction.atomic():
        post_sales_invoice(inv)
    inv.refresh_from_db()
    return f'اترحّلت ✓ {invoice_no} | الإجمالي {money(inv.grand_total)}'


def cancel_invoice(invoice_no):
    from sales.models import SalesInvoice
    from sales.services import cancel_sales_invoice
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    with transaction.atomic():
        cancel_sales_invoice(inv)
    return f'اتلغت ✓ {invoice_no}'


def create_receipt(customer, amount, account, date=''):
    """إيصال قبض — بيتخصّص تلقائي على أقدم الفواتير (FIFO) وبيترحّل."""
    from sales.models import SalesInvoice, Receipt, ReceiptAllocation
    from sales.services import post_receipt
    c = _customer(customer)
    amt = Decimal(str(amount))
    if amt <= 0:
        raise ValueError('المبلغ لازم يكون أكبر من صفر.')
    acct = _cash_account(account)
    with transaction.atomic():
        rec = Receipt.objects.create(date=_date(date), customer=c,
                                     method='BANK' if acct.pk != 1 else 'CASH',
                                     cash_account=acct, amount=amt,
                                     notes=f'تحصيل — {acct.name} (تليجرام)')
        rem = amt
        for inv in SalesInvoice.objects.filter(customer=c, status='POSTED').order_by('date', 'id'):
            if rem <= 0:
                break
            paid = sum((Decimal(a.amount) for a in
                        ReceiptAllocation.objects.filter(invoice=inv)), Decimal('0'))
            due = Decimal(inv.grand_total) - paid
            if due <= 0:
                continue
            take = min(due, rem)
            ReceiptAllocation.objects.create(receipt=rec, invoice=inv, amount=take)
            rem -= take
        post_receipt(rec)
    c.refresh_from_db()
    return (f'اتعمل إيصال {rec.receipt_no} | {c.name_ar} | {money(amt)} | {acct.name}\n'
            f'تحت الحساب: {money(rem)} | رصيد العميل بقى {money(c.current_balance)}')


def create_supplier_payment(supplier, amount, account, date=''):
    from manufacturing.models import SupplierPayment
    from manufacturing.services import post_supplier_payment
    s = _supplier(supplier)
    amt = Decimal(str(amount))
    if amt <= 0:
        raise ValueError('المبلغ لازم يكون أكبر من صفر.')
    acct = _cash_account(account)
    with transaction.atomic():
        pay = SupplierPayment.objects.create(
            date=_date(date), supplier=s, method='BANK' if acct.pk != 1 else 'CASH',
            cash_account=acct, amount=amt, status='DRAFT',
            notes=f'سداد — {acct.name} (تليجرام)')
        post_supplier_payment(pay)
    s.refresh_from_db()
    return (f'اتعمل سند {pay.payment_no} | {s.name} | {money(amt)} | {acct.name}\n'
            f'رصيد المورد بقى {money(s.current_balance)}')


@transaction.atomic
def create_production_order(item, sizes, customer='', date=''):
    """sizes = {"XL": 12, "S": 6} — بيعمل أمر إنتاج ويحمّل الوصفة."""
    from manufacturing.models import ProductionOrder, Size
    from manufacturing.services import apply_recipe_to_order
    it = _item(item)
    po = ProductionOrder.objects.create(item=it, title=it.name_ar, date=_date(date),
                                        status='DRAFT')
    if customer:
        po.customer = _customer(customer)
        po.save(update_fields=['customer'])
    for code, qty in (sizes or {}).items():
        sz = Size.objects.filter(code=code).first()
        if not sz:
            raise ValueError(f'مفيش مقاس اسمه «{code}».')
        po.sizes.create(size=sz, quantity=int(qty))
    po.refresh_from_db()
    msg = [f'اتعمل أمر إنتاج {po.order_no} | {it.name_ar} | {po.total_pieces} قطعة (خطة)']
    try:
        s = apply_recipe_to_order(po)
        msg.append(f'الوصفة: قماش {s["actual_kg"]} | إكسسوار جديد {s["acc_created"]}')
        for w in s['warnings']:
            msg.append('⚠️ ' + w)
    except Exception as e:
        msg.append(f'⚠️ تحميل الوصفة وقف: {e}')
    return '\n'.join(msg)


def produce_order(order_no):
    from manufacturing.models import ProductionOrder
    from manufacturing.services import produce_production_order
    po = ProductionOrder.objects.get(order_no=order_no)
    with transaction.atomic():
        produce_production_order(po)
    po.refresh_from_db()
    return f'الإنتاج تم ✓ {order_no} | {po.total_pieces} قطعة دخلت المخزن'


@transaction.atomic
def link_order_to_invoice(order_no, invoice_no):
    from manufacturing.models import ProductionOrder
    from sales.models import SalesInvoice
    po = ProductionOrder.objects.get(order_no=order_no)
    inv = SalesInvoice.objects.get(invoice_no=invoice_no)
    po.sales_invoice = inv
    if inv.customer_id and not po.customer_id:
        po.customer = inv.customer
    po.save(update_fields=['sales_invoice', 'customer'])
    return f'{order_no} اتربط بـ {invoice_no}'


def stock_take(item, counted):
    """جرد: counted = {"XL": 48} — بيظبط الرصيد على الكمية المعدودة."""
    from inventory.models import StockTake
    from inventory.services import post_stock_take
    it = _item(item)
    with transaction.atomic():
        st = StockTake.objects.create(date=_today(),
                                      notes=f'جرد {it.name_ar} — من تليجرام')
        before = {}
        for sz, qty in (counted or {}).items():
            v = _variant(it, sz)
            before[v.size] = Decimal(v.current_stock)
            st.lines.create(item=it, variant=v, counted_qty=Decimal(str(qty)))
        post_stock_take(st)
    rows = []
    for sz in counted or {}:
        v = _variant(it, sz)
        rows.append(f'  {v.size}: {money(before[v.size])} → {money(v.current_stock)}')
    return f'اتعمل جرد {st.take_no} على {it.name_ar}\n' + '\n'.join(rows)


# ----------------------------------------------------------------- schemas
def _t(name, desc, props, required=()):
    return {'name': name, 'description': desc,
            'input_schema': {'type': 'object', 'properties': props,
                             'required': list(required)}}


_STR = {'type': 'string'}
_NUM = {'type': 'number'}
_BOOL = {'type': 'boolean'}
_LINES = {'type': 'array', 'description': 'بنود: item + size + quantity',
          'items': {'type': 'object', 'properties': {
              'item': {'type': 'string', 'description': 'كود أو اسم المنتج'},
              'size': {'type': 'string', 'description': 'المقاس أو اللون'},
              'quantity': {'type': 'number'},
              'unit': {'type': 'string', 'enum': ['PIECE', 'WHOLESALE'],
                       'description': 'PIECE = قطعة (الافتراضي)، WHOLESALE = دستة'}},
              'required': ['item', 'size', 'quantity']}}

TOOLS = [
    _t('search_customers', 'بحث في العملاء بالاسم + أرصدتهم.',
       {'query': _STR, 'limit': {'type': 'integer'}}),
    _t('customer_details', 'تفاصيل عميل: رصيده وفواتيره اللي عليها متبقّي.',
       {'customer': _STR}, ['customer']),
    _t('search_items', 'بحث في المنتجات بالاسم (بيرجّع الكود والاسم).',
       {'query': _STR, 'limit': {'type': 'integer'}}),
    _t('item_stock', 'أرصدة وأسعار كل مقاسات منتج.', {'item': _STR}, ['item']),
    _t('list_invoices', 'قايمة فواتير البيع (فلترة بالحالة DRAFT/POSTED أو بالعميل).',
       {'status': _STR, 'customer': _STR, 'limit': {'type': 'integer'}}),
    _t('invoice_details', 'تفاصيل فاتورة ببنودها.', {'invoice_no': _STR}, ['invoice_no']),
    _t('list_production_orders', 'أوامر الإنتاج — فلترة بالحالة (DRAFT خطة / '
       'COMPLETED تم الإنتاج) أو الصنف أو العميل، و invoiced=no للأوامر اللي '
       'لسه متفوترتش.',
       {'status': _STR, 'item': _STR, 'customer': _STR,
        'invoiced': {'type': 'string', 'enum': ['yes', 'no']},
        'limit': {'type': 'integer'}}),
    _t('production_order_details', 'تفاصيل أمر إنتاج: المقاسات والقماش والحالة.',
       {'order_no': _STR}, ['order_no']),
    _t('search_suppliers', 'بحث في الموردين بالاسم + أرصدتهم.',
       {'query': _STR, 'limit': {'type': 'integer'}}),
    _t('list_receipts', 'آخر إيصالات القبض (كلها أو لعميل معيّن).',
       {'customer': _STR, 'limit': {'type': 'integer'}}),
    _t('stock_report', 'قيمة المخزون: قماش + إكسسوارات + منتج تام (تكلفة وبيع).', {}),
    _t('balances_report', 'أرصدة العملاء أو الموردين.',
       {'kind': {'type': 'string', 'enum': ['customers', 'suppliers']},
        'limit': {'type': 'integer'}}),

    _t('create_sales_invoice', 'إنشاء فاتورة بيع جديدة كمسودة ببنودها. '
       'الأسعار بتتجاب تلقائي من السيستم.',
       {'customer': _STR, 'lines': _LINES, 'date': _STR,
        'payment_type': {'type': 'string', 'enum': ['CREDIT', 'CASH']},
        'confirm': _BOOL}, ['customer', 'lines']),
    _t('add_invoice_lines', 'إضافة بنود لفاتورة مسودة.',
       {'invoice_no': _STR, 'lines': _LINES, 'confirm': _BOOL},
       ['invoice_no', 'lines']),
    _t('remove_invoice_lines', 'شيل بنود من مسودة (بالصنف و/أو المقاس).',
       {'invoice_no': _STR, 'item': _STR, 'size': _STR, 'confirm': _BOOL},
       ['invoice_no']),
    _t('set_invoice_discount', 'خصم تاجر % على فاتورة مسودة.',
       {'invoice_no': _STR, 'percent': _NUM, 'confirm': _BOOL},
       ['invoice_no', 'percent']),
    _t('check_invoice_stock', 'فحص إن رصيد بنود الفاتورة كفاية قبل الترحيل.',
       {'invoice_no': _STR}, ['invoice_no']),
    _t('post_invoice', 'ترحيل فاتورة (يخصم المخزون ويعمل القيود).',
       {'invoice_no': _STR, 'confirm': _BOOL}, ['invoice_no']),
    _t('cancel_invoice', 'إلغاء فاتورة مرحّلة (يرجّع المخزون ويعكس القيد).',
       {'invoice_no': _STR, 'confirm': _BOOL}, ['invoice_no']),

    _t('create_receipt', 'إيصال قبض من عميل — بيتخصّص على أقدم الفواتير وبيترحّل. '
       'account = بنك فيصل أو الصندوق.',
       {'customer': _STR, 'amount': _NUM, 'account': _STR, 'date': _STR,
        'confirm': _BOOL}, ['customer', 'amount', 'account']),
    _t('create_supplier_payment', 'سند صرف لمورد.',
       {'supplier': _STR, 'amount': _NUM, 'account': _STR, 'date': _STR,
        'confirm': _BOOL}, ['supplier', 'amount', 'account']),

    _t('create_production_order', 'أمر إنتاج جديد (خطة) + تحميل الوصفة. '
       'sizes = {"XL": 12, "S": 6}',
       {'item': _STR, 'sizes': {'type': 'object'}, 'customer': _STR, 'date': _STR,
        'confirm': _BOOL}, ['item', 'sizes']),
    _t('produce_order', 'تنفيذ الإنتاج (يخصم القماش ويدخّل المنتج التام).',
       {'order_no': _STR, 'confirm': _BOOL}, ['order_no']),
    _t('link_order_to_invoice', 'ربط أمر إنتاج بفاتورة بيع.',
       {'order_no': _STR, 'invoice_no': _STR, 'confirm': _BOOL},
       ['order_no', 'invoice_no']),
    _t('stock_take', 'جرد مخزون لمنتج: counted = {"XL": 48}.',
       {'item': _STR, 'counted': {'type': 'object'}, 'confirm': _BOOL},
       ['item', 'counted']),
]

HANDLERS = {
    'search_customers': search_customers,
    'customer_details': customer_details,
    'search_items': search_items,
    'item_stock': item_stock,
    'list_invoices': list_invoices,
    'invoice_details': invoice_details,
    'list_production_orders': list_production_orders,
    'production_order_details': production_order_details,
    'search_suppliers': search_suppliers,
    'list_receipts': list_receipts,
    'stock_report': stock_report,
    'balances_report': balances_report,
    'create_sales_invoice': create_sales_invoice,
    'add_invoice_lines': add_invoice_lines,
    'remove_invoice_lines': remove_invoice_lines,
    'set_invoice_discount': set_invoice_discount,
    'check_invoice_stock': check_invoice_stock,
    'post_invoice': post_invoice,
    'cancel_invoice': cancel_invoice,
    'create_receipt': create_receipt,
    'create_supplier_payment': create_supplier_payment,
    'create_production_order': create_production_order,
    'produce_order': produce_order,
    'link_order_to_invoice': link_order_to_invoice,
    'stock_take': stock_take,
}

# الأدوات اللي بتقرا بس — بتتنفّذ على طول من غير موافقة.
# أي أداة تانية بتغيّر بيانات → لازم موافقة صاحب النظام قبل التنفيذ.
READ_ONLY = {
    'search_customers', 'customer_details', 'search_items', 'item_stock',
    'list_invoices', 'invoice_details', 'stock_report', 'balances_report',
    'check_invoice_stock', 'list_production_orders', 'production_order_details',
    'search_suppliers', 'list_receipts',
}


def summarize(tool, args):
    """وصف عربي مفهوم للحركة — بيتبعت لصاحب النظام عشان يوافق وهو فاهم."""
    a = args or {}

    def _lines(v):
        return '، '.join(f'{x.get("item")} {x.get("size")}×{x.get("quantity")}'
                         for x in (v or [])[:12]) or '—'

    if tool == 'create_sales_invoice':
        return (f'فاتورة بيع جديدة (مسودة)\nالعميل: {a.get("customer")}\n'
                f'البنود: {_lines(a.get("lines"))}')
    if tool == 'add_invoice_lines':
        return f'إضافة بنود على {a.get("invoice_no")}\n{_lines(a.get("lines"))}'
    if tool == 'remove_invoice_lines':
        return (f'شيل بنود من {a.get("invoice_no")}'
                + (f' | صنف: {a.get("item")}' if a.get('item') else '')
                + (f' | مقاس: {a.get("size")}' if a.get('size') else ''))
    if tool == 'set_invoice_discount':
        return f'خصم {a.get("percent")}% على {a.get("invoice_no")}'
    if tool == 'post_invoice':
        return f'⚠️ ترحيل فاتورة {a.get("invoice_no")} (هيخصم المخزون ويعمل القيود)'
    if tool == 'cancel_invoice':
        return f'⚠️ إلغاء فاتورة {a.get("invoice_no")} (هيرجّع المخزون ويعكس القيد)'
    if tool == 'create_receipt':
        return (f'💰 إيصال قبض\nالعميل: {a.get("customer")}\n'
                f'المبلغ: {money(a.get("amount"))}\nالحساب: {a.get("account")}')
    if tool == 'create_supplier_payment':
        return (f'💸 سند صرف لمورد\nالمورد: {a.get("supplier")}\n'
                f'المبلغ: {money(a.get("amount"))}\nالحساب: {a.get("account")}')
    if tool == 'create_production_order':
        return (f'أمر إنتاج: {a.get("item")}\nالمقاسات: {a.get("sizes")}'
                + (f'\nالعميل: {a.get("customer")}' if a.get('customer') else ''))
    if tool == 'produce_order':
        return f'⚠️ تنفيذ إنتاج {a.get("order_no")} (هيخصم قماش ويدخّل منتج تام)'
    if tool == 'link_order_to_invoice':
        return f'ربط {a.get("order_no")} بفاتورة {a.get("invoice_no")}'
    if tool == 'stock_take':
        return f'⚠️ جرد {a.get("item")}\nالمعدود: {a.get("counted")}'
    return f'{tool}: {a}'


SYSTEM = """إنت مساعد العمليات في نظام «روما للملابس» (ERP جملة ملابس).

- اتكلم **مصري عامي** دايماً، ومختصر وواضح.
- الأرقام بصيغة 5,500.00 (فاصلة للآلاف، نقطة للكسر).
- استخدم الأدوات للبيانات الحقيقية — **متخمّنش** أرقام أو أكواد من دماغك أبداً.
- لو الاسم مش واضح أو فيه أكتر من نتيجة، اسأل المستخدم يحدّد.
- الأسعار بتتجاب أوتوماتيك من السيستم — متحطّش أسعار بنفسك.
- قبل ترحيل فاتورة اتأكد إن الرصيد كفاية (check_invoice_stock).
- **مهم — التأكيد قبل التنفيذ:** أي حركة بتغيّر بيانات (فاتورة/إيصال/صرف/إنتاج/جرد)
  لازم تتأكد من المستخدم الأول. الأداة أول ما تنادي عليها هترجّعلك ملخّص الحركة —
  **اعرض الملخّص ده على المستخدم بالتفصيل واسأله «تمام؟»**. أول ما يقول تمام/أيوه/ماشي،
  نادي على نفس الأداة تاني بنفس البيانات + confirm=true عشان تتنفّذ.
- لو المستخدم قال لأ أو غيّر رأيه، متنفّذش وابدأ من الأول.
- استخدم أدوات القراءة براحتك (من غير تأكيد) عشان تتأكد من البيانات قبل ما تجهّز الحركة.
- إنت مالكش دعوة بالكود ولا الوصفات ولا أسعار المنتجات ولا الإعدادات — لو حد طلب حاجة
  من دول قوله إن ده من البوت التاني (بوت المدير).
- بعد أي حركة تتنفّذ، اذكر رقم المستند (فاتورة/إيصال/أمر) والإجمالي."""
