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


# ------------------------------------------------- كروت جديدة: عملاء/موردين
@transaction.atomic
def create_customer(name, phone='', governorate='', opening_balance=0):
    from sales.models import Customer
    if Customer.objects.filter(name_ar=name).exists():
        raise ValueError(f'فيه عميل بالاسم ده خلاص: {name}')
    c = Customer.objects.create(name_ar=name, phone=phone, governorate=governorate,
                                opening_balance=Decimal(str(opening_balance or 0)))
    return f'اتعمل العميل {c.code} — {c.name_ar} (رصيد افتتاحي {money(c.opening_balance)})'


@transaction.atomic
def create_supplier(name, vendor_type, phone=''):
    """vendor_type: قماش / إكسسوارات / مكن / منتجات تامة"""
    from manufacturing.models import Supplier, VendorType
    m = {'قماش': 'FABRIC_SUPPLIER', 'اكسسوارات': 'ACCESSORIES',
         'إكسسوارات': 'ACCESSORIES', 'مكن': 'MACHINERY',
         'منتجات تامة': 'FINISHED_GOODS', 'تجارة': 'FINISHED_GOODS'}
    code = m.get((vendor_type or '').strip(), (vendor_type or '').upper())
    vt = VendorType.objects.filter(code=code).first()
    if not vt:
        have = '، '.join(f'{v.name_ar}' for v in VendorType.objects.all())
        raise ValueError(f'نوع المورد مش مظبوط. المتاح: {have}')
    if Supplier.objects.filter(name=name).exists():
        raise ValueError(f'فيه مورد بالاسم ده خلاص: {name}')
    s = Supplier.objects.create(name=name, vendor_type=vt, phone=phone)
    return f'اتعمل المورد {s.code} — {s.name} ({vt.name_ar})'


@transaction.atomic
def create_sub_product(main_product, name, fabric_color='', shorts_color=''):
    """منتج فرعي (موديل/نادي) تحت منتج رئيسي — بياخد وصفته وأسعاره منه."""
    from inventory.models import Product, Item
    from manufacturing.models import FabricColor
    p = Product.objects.filter(code__iexact=main_product).first() \
        or Product.objects.filter(name_ar__icontains=main_product).first()
    if not p:
        raise ValueError(f'مفيش منتج رئيسي «{main_product}».')
    if Item.objects.filter(name_ar=name).exists():
        raise ValueError(f'فيه منتج فرعي بالاسم ده خلاص: {name}')
    def col(n):
        if not n:
            return None
        c = FabricColor.objects.filter(name_ar__icontains=n).first()
        if not c:
            raise ValueError(f'مفيش لون «{n}».')
        return c
    it = Item.objects.create(product=p, name_ar=name, fabric_color=col(fabric_color),
                             shorts_fabric_color=col(shorts_color))
    it.refresh_from_db()
    return (f'اتعمل المنتج الفرعي {it.code} — {it.name_ar} تحت {p.name_ar} '
            f'({it.variants.count()} مقاس)')


# ------------------------------------------------- الوصفات والأسعار
@transaction.atomic
def set_prices(main_product, prices):
    """تعديل سعر البيع لمقاسات منتج رئيسي. prices = {"XL": 95, "M": 90}"""
    from inventory.models import Product
    from inventory.models import sync_variants_from_recipe
    p = Product.objects.filter(code__iexact=main_product).first() \
        or Product.objects.filter(name_ar__icontains=main_product).first()
    if not p:
        raise ValueError(f'مفيش منتج رئيسي «{main_product}».')
    rows = []
    for size, price in (prices or {}).items():
        r = p.size_recipes.filter(size__code=size).first()
        if not r:
            rows.append(f'  ⚠️ مقاس {size} مش في الوصفة')
            continue
        old = r.selling_price
        r.selling_price = Decimal(str(price))
        r.save(update_fields=['selling_price'])
        rows.append(f'  {size}: {money(old)} → {money(r.selling_price)}')
    for it in p.sub_products.all():
        sync_variants_from_recipe(it)
    return f'أسعار {p.name_ar}:\n' + '\n'.join(rows)


@transaction.atomic
def set_recipe_size(main_product, size, fabric_qty=None, shorts_fabric_qty=None,
                    labor_cost=None, selling_price=None, reorder_level=None):
    """تعديل وصفة مقاس (قماش/مصنعية/سعر/حد الطلب) — اللي متبعتوش مبيتغيّرش."""
    from inventory.models import Product
    from inventory.models import sync_variants_from_recipe
    p = Product.objects.filter(code__iexact=main_product).first() \
        or Product.objects.filter(name_ar__icontains=main_product).first()
    if not p:
        raise ValueError(f'مفيش منتج رئيسي «{main_product}».')
    r = p.size_recipes.filter(size__code=size).first()
    if not r:
        raise ValueError(f'{p.name_ar}: مفيش وصفة لمقاس {size}.')
    changed = []
    for field, val in (('fabric_qty_kg', fabric_qty),
                       ('shorts_fabric_qty_kg', shorts_fabric_qty),
                       ('labor_cost', labor_cost), ('selling_price', selling_price),
                       ('reorder_level', reorder_level)):
        if val is not None:
            old = getattr(r, field)
            setattr(r, field, Decimal(str(val)))
            changed.append(f'  {field}: {old} → {val}')
    if not changed:
        raise ValueError('مبعتّش أي قيمة تتغيّر.')
    r.save()
    for it in p.sub_products.all():
        sync_variants_from_recipe(it)
    return f'وصفة {p.name_ar} مقاس {size}:\n' + '\n'.join(changed)


@transaction.atomic
def set_recipe_accessory(main_product, size, accessory, qty_per_piece):
    """تحديد/تعديل كمية إكسسوار في وصفة مقاس (0 = يشيله)."""
    from inventory.models import Product
    from manufacturing.models import Accessory, ProductSizeAccessory
    p = Product.objects.filter(code__iexact=main_product).first() \
        or Product.objects.filter(name_ar__icontains=main_product).first()
    if not p:
        raise ValueError(f'مفيش منتج رئيسي «{main_product}».')
    r = p.size_recipes.filter(size__code=size).first()
    if not r:
        raise ValueError(f'{p.name_ar}: مفيش وصفة لمقاس {size}.')
    a = Accessory.objects.filter(code__iexact=accessory).first() \
        or Accessory.objects.filter(name_ar__icontains=accessory).first()
    if not a:
        raise ValueError(f'مفيش إكسسوار «{accessory}».')
    q = Decimal(str(qty_per_piece))
    row = ProductSizeAccessory.objects.filter(recipe=r, accessory=a).first()
    if q <= 0:
        if row:
            row.delete()
            return f'اتشال {a.name_ar} من وصفة {p.name_ar} مقاس {size}'
        raise ValueError('الإكسسوار ده مش في الوصفة أصلاً.')
    if row:
        old = row.qty_per_piece
        row.qty_per_piece = q
        row.save(update_fields=['qty_per_piece'])
        return f'{p.name_ar} مقاس {size}: {a.name_ar} {old} → {q} {a.unit}'
    ProductSizeAccessory.objects.create(recipe=r, accessory=a, qty_per_piece=q)
    return f'{p.name_ar} مقاس {size}: اتضاف {a.name_ar} × {q} {a.unit}'


# ------------------------------------------------- المشتريات
def _pay(payment, account):
    if (payment or '').upper() in ('CREDIT', 'آجل', 'اجل'):
        return 'CREDIT', None
    acct = _cash_account(account)
    return ('BANK' if acct.pk != 1 else 'CASH'), acct


def buy_fabric(supplier, lines, payment='CREDIT', account='', date=''):
    """شراء قماش. lines = [{fabric, color, qty, unit_cost}] — وبيترحّل على طول."""
    from manufacturing.models import (FabricPurchaseInvoice, FabricBatch,
                                      FabricType, FabricColor)
    from manufacturing.services import post_fabric_purchase_invoice
    s = _supplier(supplier)
    method, acct = _pay(payment, account)
    with transaction.atomic():
        inv = FabricPurchaseInvoice.objects.create(
            supplier=s, date=_date(date), payment_method=method, cash_account=acct,
            notes='شراء من تليجرام')
        rows, total = [], Decimal('0')
        for ln in lines or []:
            ft = FabricType.objects.filter(name_ar__icontains=ln.get('fabric')).first()
            if not ft:
                raise ValueError(f'مفيش نوع قماش «{ln.get("fabric")}».')
            col = FabricColor.objects.filter(name_ar__icontains=ln.get('color', '')).first()
            if not col:
                raise ValueError(f'مفيش لون «{ln.get("color")}».')
            qty = Decimal(str(ln.get('qty')))
            cost = Decimal(str(ln.get('unit_cost')))
            FabricBatch.objects.create(invoice=inv, supplier=s, fabric_type=ft, color=col,
                                       purchase_date=inv.date, purchase_qty_kg=qty,
                                       purchase_unit_cost=cost,
                                       purchase_payment_method=method)
            total += qty * cost
            rows.append(f'  {ft.name_ar} {col.name_ar} — {qty} {ft.unit} × {money(cost)}')
        post_fabric_purchase_invoice(inv)
    return (f'اتعملت فاتورة شراء قماش {inv.invoice_no} من {s.name}\n'
            + '\n'.join(rows) + f'\nالإجمالي {money(total)} | {method}')


def buy_accessories(supplier, lines, payment='CREDIT', account='', date=''):
    """شراء إكسسوارات. lines = [{accessory, qty, unit_cost}] (بوحدة الشراء)."""
    from manufacturing.models import (AccessoryPurchaseInvoice, AccessoryPurchase,
                                      Accessory)
    from manufacturing.services import post_accessory_purchase_invoice
    s = _supplier(supplier)
    method, acct = _pay(payment, account)
    with transaction.atomic():
        inv = AccessoryPurchaseInvoice.objects.create(
            supplier=s, date=_date(date), payment_method=method, cash_account=acct,
            notes='شراء من تليجرام')
        rows, total = [], Decimal('0')
        for ln in lines or []:
            a = Accessory.objects.filter(code__iexact=ln.get('accessory')).first() \
                or Accessory.objects.filter(name_ar__icontains=ln.get('accessory')).first()
            if not a:
                raise ValueError(f'مفيش إكسسوار «{ln.get("accessory")}».')
            qty = Decimal(str(ln.get('qty')))
            cost = Decimal(str(ln.get('unit_cost')))
            AccessoryPurchase.objects.create(
                invoice=inv, accessory=a, supplier=s, date=inv.date, quantity=qty,
                unit_cost=cost, payment_method=method, cash_account=acct)
            total += qty * cost
            rows.append(f'  {a.name_ar} — {qty} {a.purchase_unit} × {money(cost)}')
        post_accessory_purchase_invoice(inv)
    return (f'اتعملت فاتورة شراء إكسسوارات {inv.invoice_no} من {s.name}\n'
            + '\n'.join(rows) + f'\nالإجمالي {money(total)} | {method}')


def buy_finished_goods(supplier, lines, payment='CREDIT', account='', date=''):
    """شراء منتجات تامة جاهزة. lines = [{item, size, qty, unit_cost}]."""
    from inventory.models import FinishedGoodsPurchaseInvoice as F
    from inventory.services import post_finished_goods_purchase_invoice
    s = _supplier(supplier)
    method, acct = _pay(payment, account)
    method = 'CASH' if method in ('CASH', 'BANK') else 'CREDIT'
    with transaction.atomic():
        inv = F.objects.create(supplier=s, date=_date(date), payment_method=method,
                               cash_account=acct, notes='شراء من تليجرام')
        rows, total = [], Decimal('0')
        for ln in lines or []:
            it = _item(ln.get('item'))
            v = _variant(it, ln.get('size'))
            qty = Decimal(str(ln.get('qty')))
            cost = Decimal(str(ln.get('unit_cost')))
            inv.lines.create(variant=v, purchase_unit='PIECE', quantity=qty,
                             unit_cost=cost)
            total += qty * cost
            rows.append(f'  {it.name_ar} {v.size} — {qty} × {money(cost)}')
        post_finished_goods_purchase_invoice(inv)
    return (f'اتعملت فاتورة شراء منتجات تامة {inv.invoice_no} من {s.name}\n'
            + '\n'.join(rows) + f'\nالإجمالي {money(total)} | {method}')


def cancel_fabric_purchase(invoice_no):
    from manufacturing.models import FabricPurchaseInvoice
    from manufacturing.services import cancel_fabric_purchase_invoice
    inv = FabricPurchaseInvoice.objects.get(invoice_no=invoice_no)
    with transaction.atomic():
        cancel_fabric_purchase_invoice(inv)
    return f'اتلغت فاتورة شراء القماش {invoice_no} — رجّع المخزون وعكس القيد.'


def list_purchases(kind='fabric', limit=15):
    """آخر فواتير الشراء: fabric / accessories / finished."""
    if kind == 'accessories':
        from manufacturing.models import AccessoryPurchaseInvoice as M
    elif kind == 'finished':
        from inventory.models import FinishedGoodsPurchaseInvoice as M
    else:
        from manufacturing.models import FabricPurchaseInvoice as M
    rows = []
    for i in M.objects.select_related('supplier').order_by('-date', '-id')[:limit]:
        flag = ' (ملغاة)' if getattr(i, 'is_cancelled', False) else ''
        rows.append('%s | %s | %s | %s%s' % (
            i.invoice_no, i.date, i.supplier.name if i.supplier_id else '—',
            i.payment_method, flag))
    return '\n'.join(rows) or 'مفيش فواتير شراء.'


def purchase_details(invoice_no):
    """بنود فاتورة شراء (قماش FPI-… / إكسسوارات / منتجات تامة FGP-…) وحالتها."""
    from manufacturing.models import FabricPurchaseInvoice, AccessoryPurchaseInvoice
    from inventory.models import FinishedGoodsPurchaseInvoice
    no = (invoice_no or '').strip().upper()
    for M in (FabricPurchaseInvoice, AccessoryPurchaseInvoice,
              FinishedGoodsPurchaseInvoice):
        inv = M.objects.filter(invoice_no__iexact=no).first()
        if not inv:
            continue
        state = 'مرحّلة' if inv.is_posted else 'مسودة'
        if getattr(inv, 'is_cancelled', False):
            state = 'ملغاة'
        out = ['%s | %s | المورد: %s | السداد: %s | %s' % (
            inv.invoice_no, inv.date,
            inv.supplier.name if inv.supplier_id else '—',
            inv.payment_method, state), 'البنود:']
        total = Decimal('0')
        for l in inv.lines.all():
            if hasattr(l, 'fabric_type'):                      # قماش
                qty, cost = Decimal(l.purchase_qty_kg), Decimal(l.purchase_unit_cost or 0)
                out.append('  %s %s | مشترى %s %s | متبقّي %s | × %s = %s' % (
                    l.fabric_type.name_ar,
                    l.color.name_ar if l.color_id else '', qty, l.fabric_type.unit,
                    l.in_stock_qty_kg, money(cost), money(qty * cost)))
            elif hasattr(l, 'accessory'):                      # إكسسوارات
                qty, cost = Decimal(l.quantity), Decimal(l.unit_cost or 0)
                out.append('  %s | %s %s × %s = %s' % (
                    l.accessory.name_ar, qty, l.accessory.purchase_unit,
                    money(cost), money(qty * cost)))
            else:                                              # منتجات تامة
                qty, cost = Decimal(l.quantity), Decimal(l.unit_cost or 0)
                out.append('  %s | مقاس %s | %s × %s = %s' % (
                    l.variant.item.name_ar, l.variant.size, qty, money(cost),
                    money(qty * cost)))
            total += qty * cost
        out.append('الإجمالي: %s' % money(total))
        return '\n'.join(out)
    raise ValueError(f'مفيش فاتورة شراء بالرقم «{invoice_no}».')


# ------------------------------------------------- حذف (مسودات بس)
def delete_draft(doc_no):
    """حذف مستند **مسودة** (فاتورة بيع / أمر إنتاج). المرحّل مبيتحذفش — يتلغي."""
    from sales.models import SalesInvoice
    from manufacturing.models import ProductionOrder
    doc_no = (doc_no or '').strip().upper()
    if doc_no.startswith('INV'):
        d = SalesInvoice.objects.get(invoice_no=doc_no)
        if d.status != 'DRAFT':
            raise ValueError(f'{doc_no} مش مسودة ({d.get_status_display()}) — '
                             f'المرحّل بيتلغي مش بيتحذف، استخدم إلغاء الفاتورة.')
        with transaction.atomic():
            d.lines.all().delete()
            d.delete()
        return f'اتحذفت المسودة {doc_no}'
    if doc_no.startswith('PO'):
        d = ProductionOrder.objects.get(order_no=doc_no)
        if d.status != 'DRAFT':
            raise ValueError(f'{doc_no} مش خطة ({d.get_status_display()}) — '
                             f'اللي اتنتج مينفعش يتحذف.')
        with transaction.atomic():
            d.delete()
        return f'اتحذف أمر الإنتاج {doc_no}'
    raise ValueError('اكتب رقم فاتورة بيع (INV-...) أو أمر إنتاج (PO-...).')


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

    # --- كروت جديدة ---
    _t('create_customer', 'إضافة عميل جديد.',
       {'name': _STR, 'phone': _STR, 'governorate': _STR,
        'opening_balance': _NUM, 'confirm': _BOOL}, ['name']),
    _t('create_supplier', 'إضافة مورد جديد. vendor_type: قماش / إكسسوارات / مكن / '
       'منتجات تامة.',
       {'name': _STR, 'vendor_type': _STR, 'phone': _STR, 'confirm': _BOOL},
       ['name', 'vendor_type']),
    _t('create_sub_product', 'إضافة منتج فرعي (موديل/نادي) تحت منتج رئيسي — '
       'بياخد الوصفة والأسعار والمقاسات منه تلقائي.',
       {'main_product': _STR, 'name': _STR, 'fabric_color': _STR,
        'shorts_color': _STR, 'confirm': _BOOL}, ['main_product', 'name']),

    # --- الوصفات والأسعار ---
    _t('set_prices', 'تعديل أسعار البيع لمقاسات منتج رئيسي. '
       'prices = {"XL": 95, "M": 90} — بيتطبّق على كل المنتجات الفرعية.',
       {'main_product': _STR, 'prices': {'type': 'object'}, 'confirm': _BOOL},
       ['main_product', 'prices']),
    _t('set_recipe_size', 'تعديل وصفة مقاس: كمية القماش/قماش الشورت/المصنعية/'
       'سعر البيع/حد إعادة الطلب. اللي متبعتوش مبيتغيّرش.',
       {'main_product': _STR, 'size': _STR, 'fabric_qty': _NUM,
        'shorts_fabric_qty': _NUM, 'labor_cost': _NUM, 'selling_price': _NUM,
        'reorder_level': _NUM, 'confirm': _BOOL}, ['main_product', 'size']),
    _t('set_recipe_accessory', 'تحديد كمية إكسسوار في وصفة مقاس (0 = يشيله).',
       {'main_product': _STR, 'size': _STR, 'accessory': _STR,
        'qty_per_piece': _NUM, 'confirm': _BOOL},
       ['main_product', 'size', 'accessory', 'qty_per_piece']),

    # --- المشتريات ---
    _t('buy_fabric', 'فاتورة شراء قماش (بتترحّل على طول). '
       'lines = [{fabric, color, qty, unit_cost}] · payment: CREDIT آجل أو CASH/BANK '
       'مع account (بنك فيصل / الصندوق).',
       {'supplier': _STR, 'lines': {'type': 'array', 'items': {'type': 'object'}},
        'payment': _STR, 'account': _STR, 'date': _STR, 'confirm': _BOOL},
       ['supplier', 'lines']),
    _t('buy_accessories', 'فاتورة شراء إكسسوارات. lines = [{accessory, qty, unit_cost}] '
       '(الكمية بوحدة الشراء).',
       {'supplier': _STR, 'lines': {'type': 'array', 'items': {'type': 'object'}},
        'payment': _STR, 'account': _STR, 'date': _STR, 'confirm': _BOOL},
       ['supplier', 'lines']),
    _t('buy_finished_goods', 'فاتورة شراء منتجات تامة جاهزة (تجارة). '
       'lines = [{item, size, qty, unit_cost}].',
       {'supplier': _STR, 'lines': {'type': 'array', 'items': {'type': 'object'}},
        'payment': _STR, 'account': _STR, 'date': _STR, 'confirm': _BOOL},
       ['supplier', 'lines']),
    _t('cancel_fabric_purchase', 'إلغاء فاتورة شراء قماش مرحّلة (يرجّع المخزون '
       'ويعكس القيد). مينفعش لو القماش اتصرف في الإنتاج.',
       {'invoice_no': _STR, 'confirm': _BOOL}, ['invoice_no']),
    _t('purchase_details', 'بنود فاتورة شراء وحالتها (FPI-… قماش / FGP-… منتجات تامة / إكسسوارات).',
       {'invoice_no': _STR}, ['invoice_no']),
    _t('list_purchases', 'آخر فواتير الشراء: kind = fabric / accessories / finished.',
       {'kind': {'type': 'string', 'enum': ['fabric', 'accessories', 'finished']},
        'limit': {'type': 'integer'}}),

    # --- حذف ---
    _t('delete_draft', 'حذف مستند **مسودة** بس (فاتورة بيع INV-… أو أمر إنتاج PO-…). '
       'المرحّل مبيتحذفش — بيتلغي.',
       {'doc_no': _STR, 'confirm': _BOOL}, ['doc_no']),
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
    'create_customer': create_customer,
    'create_supplier': create_supplier,
    'create_sub_product': create_sub_product,
    'set_prices': set_prices,
    'set_recipe_size': set_recipe_size,
    'set_recipe_accessory': set_recipe_accessory,
    'buy_fabric': buy_fabric,
    'buy_accessories': buy_accessories,
    'buy_finished_goods': buy_finished_goods,
    'cancel_fabric_purchase': cancel_fabric_purchase,
    'purchase_details': purchase_details,
    'list_purchases': list_purchases,
    'delete_draft': delete_draft,
}

# الأدوات اللي بتقرا بس — بتتنفّذ على طول من غير موافقة.
# أي أداة تانية بتغيّر بيانات → لازم موافقة صاحب النظام قبل التنفيذ.
READ_ONLY = {
    'search_customers', 'customer_details', 'search_items', 'item_stock',
    'list_invoices', 'invoice_details', 'stock_report', 'balances_report',
    'check_invoice_stock', 'list_production_orders', 'production_order_details',
    'search_suppliers', 'list_receipts', 'list_purchases', 'purchase_details',
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
    if tool == 'create_customer':
        return (f'عميل جديد: {a.get("name")}'
                + (f'\nتليفون: {a.get("phone")}' if a.get('phone') else '')
                + (f'\nرصيد افتتاحي: {money(a.get("opening_balance"))}'
                   if a.get('opening_balance') else ''))
    if tool == 'create_supplier':
        return f'مورد جديد: {a.get("name")} ({a.get("vendor_type")})'
    if tool == 'create_sub_product':
        return (f'منتج فرعي جديد: {a.get("name")}\nتحت: {a.get("main_product")}'
                + (f'\nلون القماش: {a.get("fabric_color")}'
                   if a.get('fabric_color') else ''))
    if tool == 'set_prices':
        return f'⚠️ تعديل أسعار {a.get("main_product")}\n{a.get("prices")}'
    if tool == 'set_recipe_size':
        vals = {k: v for k, v in a.items()
                if k not in ('main_product', 'size') and v is not None}
        return f'⚠️ تعديل وصفة {a.get("main_product")} مقاس {a.get("size")}\n{vals}'
    if tool == 'set_recipe_accessory':
        return (f'⚠️ وصفة {a.get("main_product")} مقاس {a.get("size")}: '
                f'{a.get("accessory")} = {a.get("qty_per_piece")}')
    if tool in ('buy_fabric', 'buy_accessories', 'buy_finished_goods'):
        label = {'buy_fabric': 'قماش', 'buy_accessories': 'إكسسوارات',
                 'buy_finished_goods': 'منتجات تامة'}[tool]
        items = '، '.join(str(x) for x in (a.get('lines') or [])[:8]) or '—'
        return (f'🧾 فاتورة شراء {label}\nالمورد: {a.get("supplier")}\n'
                f'البنود: {items}\nالسداد: {a.get("payment", "CREDIT")}'
                + (f' — {a.get("account")}' if a.get('account') else ''))
    if tool == 'cancel_fabric_purchase':
        return f'⚠️ إلغاء فاتورة شراء قماش {a.get("invoice_no")}'
    if tool == 'delete_draft':
        return f'🗑️ حذف المسودة {a.get("doc_no")} — الحذف نهائي'
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
