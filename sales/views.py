"""Public sales views: printable invoice, customer ledger, AR aging,
plus the JSON endpoint that auto-fills unit_price in the admin."""
from decimal import Decimal
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from core.account_codes import SYSTEM_ACCOUNTS
from core.models import Company, JournalLine
from inventory.models import Item
from .models import Customer, SalesInvoice


@login_required
def item_default_price(request, pk):
    """Auto-fill price endpoint used by the admin JS.

    `?variant=<id>`  → returns the per-PIECE price plus the dozen/carton sizes,
                       so the admin JS can compute the price for the chosen unit
                       (piece / dozen / carton).
    no variant       → BUNDLE sale, returns Σ of per-piece SKU prices.
    """
    from inventory.models import ItemVariant
    it = get_object_or_404(Item.objects.prefetch_related('variants'), pk=pk)
    variants = list(it.variants.all())

    variant_id = request.GET.get('variant')
    if variant_id:
        try:
            v = ItemVariant.objects.get(pk=int(variant_id), item=it)
        except (ItemVariant.DoesNotExist, ValueError):
            v = None
        if v is not None:
            piece = Decimal(v.selling_price or 0).quantize(Decimal('0.01'))
            p = it.product
            return JsonResponse({
                'unit_price': str(piece),          # السعر الافتراضي = القطعة
                'piece_price': str(piece),
                'wholesale_unit': (p.wholesale_unit if p else 'DOZEN'),
                'wholesale_unit_label': (p.get_wholesale_unit_display() if p else 'دستة'),
                'wholesale_unit_size': (p.wholesale_unit_size if p else 12),
                'item_code': it.code,
                'item_name_ar': it.name_ar,
                'sale_type': 'piece',
                'size': v.size,
                'price_source': 'selling_price (piece)',
            })

    # Default — bundle sale: sum of per-piece SKU selling prices across sizes.
    bundle_size = len(variants) or 1
    bundle_price = sum((Decimal(v.selling_price or 0) for v in variants),
                       Decimal('0')).quantize(Decimal('0.01'))
    price_source = 'Σ selling_price (bundle)'

    return JsonResponse({
        'unit_price': str(bundle_price.quantize(Decimal('0.01'))),
        'item_code': it.code,
        'item_name_ar': it.name_ar,
        'bundle_size': bundle_size,
        'sizes': ', '.join(v.size for v in variants),
        'sale_type': 'bundle',
        'price_source': price_source,
    })


@login_required
def performance_report(request):
    """Combined printable report: customers + visual sales + visual products + P&L.
    Date range applies to sales/customers/P&L sections; products section is current snapshot.
    """
    from datetime import date as _date
    from .models import Customer, SalesInvoice, Receipt, SalesInvoiceLine
    from inventory.models import Item
    from core.models import Account
    from core.reporting import all_account_balances_in_period, natural_balance
    from django.db.models import Sum, Max, Count
    from collections import defaultdict

    today = _date.today()

    def _parse(d, fallback):
        if not d:
            return fallback
        try:
            return _date.fromisoformat(d)
        except ValueError:
            return fallback

    date_from = _parse(request.GET.get('from'), today.replace(month=1, day=1))
    date_to = _parse(request.GET.get('to'), today)

    # ---------------- Section 1: Customers ----------------
    sales_by_cust = {
        r['customer_id']: r
        for r in (SalesInvoice.objects
                  .filter(status='POSTED', date__gte=date_from, date__lte=date_to)
                  .values('customer_id')
                  .annotate(total_sales=Sum('grand_total'), last_sale=Max('date')))
    }
    counts_by_cust = {
        r['customer_id']: r['n']
        for r in (SalesInvoice.objects.filter(status='POSTED',
                                               date__gte=date_from, date__lte=date_to)
                  .values('customer_id').annotate(n=Count('id')))
    }
    receipts_by_cust = {
        r['customer_id']: r
        for r in (Receipt.objects
                  .filter(status='POSTED', date__gte=date_from, date__lte=date_to)
                  .values('customer_id')
                  .annotate(total_payments=Sum('amount'), last_receipt=Max('date')))
    }

    customer_rows = []
    c_total_sales = c_total_payments = c_total_balance = Decimal('0')
    for c in Customer.objects.filter(active=True).order_by('code'):
        sd = sales_by_cust.get(c.id, {})
        rd = receipts_by_cust.get(c.id, {})
        sales = sd.get('total_sales') or Decimal('0')
        payments = rd.get('total_payments') or Decimal('0')
        balance = c.current_balance
        address = ' — '.join(x for x in (c.address, c.governorate) if x)
        customer_rows.append({
            'customer': c,
            'address': address,
            'phone': c.phone or '',
            'total_sales': sales,
            'last_sale': sd.get('last_sale'),
            'total_payments': payments,
            'last_receipt': rd.get('last_receipt'),
            'balance': balance,
        })
        c_total_sales += sales
        c_total_payments += payments
        c_total_balance += balance

    # ---------------- Section 2: Visual sales (net of trader discount) ----------------
    lines = list(SalesInvoiceLine.objects
                  .filter(invoice__status='POSTED',
                          invoice__date__gte=date_from,
                          invoice__date__lte=date_to)
                  .select_related('item', 'variant', 'invoice'))

    revenue_by_item = defaultdict(Decimal)
    cogs_by_item = defaultdict(Decimal)
    dozens_by_item = defaultdict(Decimal)
    pieces_by_item = defaultdict(Decimal)
    last_sold_by_item = {}

    for line in lines:
        inv = line.invoice
        if Decimal(inv.subtotal) > 0:
            ratio = Decimal(inv.grand_total) / Decimal(inv.subtotal)
        else:
            ratio = Decimal('1')
        line_net = (Decimal(line.line_total) * ratio).quantize(Decimal('0.01'))
        revenue_by_item[line.item_id] += line_net
        cogs_by_item[line.item_id] += Decimal(line.cogs_at_posting)
        # النظام بيبيع بالدستة: line.quantity = عدد الدستات، total_pieces = القطع الفعلية
        dozens_by_item[line.item_id] += Decimal(line.quantity)
        pieces_by_item[line.item_id] += Decimal(line.total_pieces)
        cur_last = last_sold_by_item.get(line.item_id)
        if cur_last is None or inv.date > cur_last:
            last_sold_by_item[line.item_id] = inv.date

    sales_rows = []
    s_total_dozens = s_total_pieces = s_total_revenue = s_total_cogs = Decimal('0')
    for it in Item.objects.all().prefetch_related('variants').order_by('code'):
        d = dozens_by_item.get(it.id, Decimal('0'))
        p = pieces_by_item.get(it.id, Decimal('0'))
        rev = revenue_by_item.get(it.id, Decimal('0'))
        cogs = cogs_by_item.get(it.id, Decimal('0'))
        last = last_sold_by_item.get(it.id)
        if rev == 0:
            continue
        profit = rev - cogs
        margin = (profit / rev * Decimal('100')) if rev > 0 else Decimal('0')
        sales_rows.append({
            'item': it,
            'dozens_sold': d, 'pieces_sold': p,
            'revenue': rev, 'cogs': cogs,
            'profit': profit, 'margin_pct': margin,
            'last_sold': last,
        })
        s_total_dozens += d
        s_total_pieces += p
        s_total_revenue += rev
        s_total_cogs += cogs
    sales_rows.sort(key=lambda r: r['revenue'], reverse=True)
    s_total_profit = s_total_revenue - s_total_cogs

    # ---------------- Section 3: Visual products (current snapshot) ----------------
    product_rows = []
    p_grand_pieces = p_grand_value = Decimal('0')
    p_grand_dozens = Decimal('0')
    for it in Item.objects.filter(active=True).prefetch_related('variants').order_by('code'):
        variants = list(it.variants.all())
        total_pieces = sum((Decimal(v.current_stock) for v in variants), Decimal('0'))
        total_value = sum(
            (Decimal(v.current_stock) * Decimal(v.average_cost) for v in variants),
            Decimal('0')
        )
        dozen_size = Decimal(it.dozen_size or 12)
        total_dozens = (total_pieces / dozen_size) if dozen_size else Decimal('0')
        product_rows.append({
            'item': it, 'variants': variants,
            'total_pieces': total_pieces, 'total_value': total_value,
            'total_dozens': total_dozens,
        })
        p_grand_pieces += total_pieces
        p_grand_value += total_value
        p_grand_dozens += total_dozens

    # ---------------- Section 4: P&L ----------------
    pnl_bal = all_account_balances_in_period(date_from, date_to)
    pnl_accounts = list(Account.objects.filter(is_group=False,
                                                 account_type__in=['REVENUE', 'EXPENSE']
                                                 ).order_by('code'))
    revenue_rows = []
    expense_rows = []
    pnl_rev_total = pnl_exp_total = Decimal('0')
    for a in pnl_accounts:
        d, c = pnl_bal.get(a.id, (Decimal('0'), Decimal('0')))
        amt = natural_balance(a, d, c)
        if amt == 0:
            continue
        if a.account_type == 'REVENUE':
            revenue_rows.append({'account': a, 'amount': amt})
            pnl_rev_total += amt
        else:
            expense_rows.append({'account': a, 'amount': amt})
            pnl_exp_total += amt
    net_income = pnl_rev_total - pnl_exp_total

    return render(request, 'sales/performance_report.html', {
        'today': today,
        'date_from': date_from,
        'date_to': date_to,

        # Customers section
        'customer_rows': customer_rows,
        'c_total_customers': len(customer_rows),
        'c_total_sales': c_total_sales,
        'c_total_payments': c_total_payments,
        'c_total_balance': c_total_balance,

        # Visual sales section
        'sales_rows': sales_rows,
        's_total_items': len(sales_rows),
        's_total_dozens': s_total_dozens,
        's_total_pieces': s_total_pieces,
        's_total_revenue': s_total_revenue,
        's_total_cogs': s_total_cogs,
        's_total_profit': s_total_profit,

        # Products section
        'product_rows': product_rows,
        'p_total_items': len(product_rows),
        'p_grand_pieces': p_grand_pieces,
        'p_grand_dozens': p_grand_dozens,
        'p_grand_value': p_grand_value,

        # P&L section
        'revenue_rows': revenue_rows,
        'expense_rows': expense_rows,
        'pnl_rev_total': pnl_rev_total,
        'pnl_exp_total': pnl_exp_total,
        'net_income': net_income,
    })


@login_required
def customers_report(request):
    """Per-customer summary: total sales, last invoice date, total payments,
    last receipt date, current balance.  Empty dates render as NA in the template."""
    from .models import Customer, SalesInvoice, Receipt
    from django.db.models import Sum, Max

    sales_by_cust = {
        r['customer_id']: r
        for r in (SalesInvoice.objects
                  .filter(status='POSTED')
                  .values('customer_id')
                  .annotate(total_sales=Sum('grand_total'),
                            last_sale=Max('date'),
                            invoice_count=Sum('grand_total') * 0 + 1))  # placeholder count
    }
    # Recompute invoice_count properly
    counts_qs = (SalesInvoice.objects
                 .filter(status='POSTED')
                 .values('customer_id')
                 .annotate(n=Sum('grand_total') * 0))  # not used
    from django.db.models import Count
    counts_by_cust = {
        r['customer_id']: r['n']
        for r in SalesInvoice.objects.filter(status='POSTED')
                  .values('customer_id').annotate(n=Count('id'))
    }

    receipts_by_cust = {
        r['customer_id']: r
        for r in (Receipt.objects
                  .filter(status='POSTED')
                  .values('customer_id')
                  .annotate(total_payments=Sum('amount'),
                            last_receipt=Max('date')))
    }

    show_inactive = request.GET.get('show_inactive') == '1'
    cust_qs = Customer.objects.all()
    if not show_inactive:
        cust_qs = cust_qs.filter(active=True)
    cust_qs = cust_qs.order_by('code')

    rows = []
    total_sales = Decimal('0')
    total_payments = Decimal('0')
    total_balance = Decimal('0')

    for c in cust_qs:
        sd = sales_by_cust.get(c.id, {})
        rd = receipts_by_cust.get(c.id, {})
        sales = sd.get('total_sales') or Decimal('0')
        payments = rd.get('total_payments') or Decimal('0')
        # Use the live current_balance property (= opening_balance + AR debits - AR credits)
        balance = c.current_balance

        # Compose address: address + governorate
        address_parts = []
        if c.address:
            address_parts.append(c.address)
        if c.governorate:
            address_parts.append(c.governorate)
        address_str = ' — '.join(address_parts) if address_parts else ''

        rows.append({
            'customer': c,
            'address': address_str,
            'phone': c.phone or '',
            'total_sales': sales,
            'invoice_count': counts_by_cust.get(c.id, 0),
            'last_sale': sd.get('last_sale'),
            'total_payments': payments,
            'last_receipt': rd.get('last_receipt'),
            'balance': balance,
        })
        total_sales += sales
        total_payments += payments
        total_balance += balance

    return render(request, 'sales/customers_report.html', {
        'rows': rows,
        'total_customers': len(rows),
        'total_sales': total_sales,
        'total_payments': total_payments,
        'total_balance': total_balance,
        'show_inactive': show_inactive,
    })


@login_required
def visual_sales_report(request):
    """Per-product sales (net of trader discount) over a date range.
    Revenue per item = Σ line_total × (invoice.grand_total / invoice.subtotal)
    so the totals match the customers report + P&L (both show net of discount).
    """
    from collections import defaultdict
    from datetime import date as _date
    from .models import SalesInvoiceLine
    from inventory.models import Item

    today = _date.today()

    def _parse(d, fallback):
        if not d:
            return fallback
        try:
            return _date.fromisoformat(d)
        except ValueError:
            return fallback

    default_from = today.replace(day=1)
    date_from = _parse(request.GET.get('from'), default_from)
    date_to = _parse(request.GET.get('to'), today)

    # Pull all matching lines in one query (with their invoice for proportional discount)
    lines = list(SalesInvoiceLine.objects
                  .filter(invoice__status='POSTED',
                          invoice__date__gte=date_from,
                          invoice__date__lte=date_to)
                  .select_related('item', 'variant', 'invoice'))

    revenue_by_item = defaultdict(Decimal)   # net of doc discount
    cogs_by_item = defaultdict(Decimal)
    dozens_by_item = defaultdict(Decimal)
    pieces_by_item = defaultdict(Decimal)
    last_sold_by_item = {}

    for line in lines:
        inv = line.invoice
        if Decimal(inv.subtotal) > 0:
            ratio = Decimal(inv.grand_total) / Decimal(inv.subtotal)
        else:
            ratio = Decimal('1')
        line_net = (Decimal(line.line_total) * ratio).quantize(Decimal('0.01'))

        revenue_by_item[line.item_id] += line_net
        cogs_by_item[line.item_id] += Decimal(line.cogs_at_posting)
        # النظام بيبيع بالدستة: line.quantity = عدد الدستات
        dozens_by_item[line.item_id] += Decimal(line.quantity)
        pieces_by_item[line.item_id] += Decimal(line.total_pieces)

        cur_last = last_sold_by_item.get(line.item_id)
        if cur_last is None or inv.date > cur_last:
            last_sold_by_item[line.item_id] = inv.date

    items = Item.objects.all().prefetch_related('variants').order_by('code')

    rows = []
    total_dozens = total_pieces = Decimal('0')
    total_revenue = total_cogs = Decimal('0')

    for it in items:
        d = dozens_by_item.get(it.id, Decimal('0'))
        p = pieces_by_item.get(it.id, Decimal('0'))
        rev = revenue_by_item.get(it.id, Decimal('0'))
        cogs = cogs_by_item.get(it.id, Decimal('0'))
        last = last_sold_by_item.get(it.id)
        profit = rev - cogs
        margin = (profit / rev * Decimal('100')) if rev > 0 else Decimal('0')

        if rev == 0 and request.GET.get('show_zero') != '1':
            continue

        rows.append({
            'item': it,
            'dozens_sold': d,
            'pieces_sold': p,
            'revenue': rev,
            'cogs': cogs,
            'profit': profit,
            'margin_pct': margin,
            'last_sold': last,
        })
        total_dozens += d
        total_pieces += p
        total_revenue += rev
        total_cogs += cogs

    rows.sort(key=lambda r: r['revenue'], reverse=True)

    total_profit = total_revenue - total_cogs
    total_margin = ((total_profit / total_revenue * Decimal('100'))
                    if total_revenue > 0 else Decimal('0'))

    return render(request, 'sales/visual_sales_report.html', {
        'rows': rows,
        'date_from': date_from,
        'date_to': date_to,
        'total_items': len(rows),
        'total_dozens': total_dozens,
        'total_pieces': total_pieces,
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'total_profit': total_profit,
        'total_margin': total_margin,
        'show_zero': request.GET.get('show_zero') == '1',
    })


@login_required
def variants_for_item(request, pk):
    """Return the variants (sizes) belonging to a single item.
    Used by the admin JS to populate the variant dropdown per-line."""
    from inventory.models import Item
    it = get_object_or_404(Item.objects.prefetch_related('variants'), pk=pk)
    variants = list(it.variants.all())  # already in S/M/L/XL order
    return JsonResponse({
        'item_id': it.id,
        'item_code': it.code,
        'item_name_ar': it.name_ar,
        'variants': [
            {
                'id': v.id,
                'size': v.size,
                'sku_code': v.sku_code,
                'current_stock': str(v.current_stock),
                'selling_price': str(v.selling_price or 0),
            }
            for v in variants
        ],
    })


@login_required
def invoices_for_customer(request, pk):
    """Return POSTED invoices for a customer.  Used in the receipt
    allocation inline so the user only sees this customer's invoices."""
    from .models import SalesInvoice, Customer
    customer = get_object_or_404(Customer, pk=pk)
    invoices = (SalesInvoice.objects
                .filter(customer=customer, status='POSTED')
                .order_by('-date', '-id'))
    return JsonResponse({
        'customer_id': customer.id,
        'customer_name': customer.name_ar,
        'invoices': [
            {
                'id': inv.id,
                'invoice_no': inv.invoice_no,
                'date': inv.date.isoformat(),
                'grand_total': str(inv.grand_total),
                'balance_due': str(inv.balance_due),
            }
            for inv in invoices
        ],
    })


@login_required
def create_return_from_invoice(request, pk):
    """Create a DRAFT SalesReturn pre-filled with this invoice's customer +
    original_invoice, then redirect to its change view so the user can pick
    which lines to return (or click "نسخ بنود الفاتورة الأصلية" for a full return).
    """
    from datetime import date as _date
    from .models import SalesInvoice, SalesReturn
    inv = get_object_or_404(SalesInvoice, pk=pk)
    if inv.status != 'POSTED':
        from django.contrib import messages as _msgs
        _msgs.error(request, 'يمكن إنشاء مرتجع من فاتورة مرحّلة فقط.')
        return HttpResponseRedirect(reverse('admin:sales_salesinvoice_change', args=[pk]))

    today = _date.today()
    # Generate a unique return_no: RET-<invoice_no>-NN  (NN = next sequence)
    base = f'RET-{inv.invoice_no}'
    n = 1
    while SalesReturn.objects.filter(return_no=f'{base}-{n:02d}').exists():
        n += 1
    ret = SalesReturn.objects.create(
        return_no=f'{base}-{n:02d}',
        date=today,
        customer=inv.customer,
        original_invoice=inv,
        created_by=request.user,
    )
    return HttpResponseRedirect(reverse('admin:sales_salesreturn_change', args=[ret.pk]))


@never_cache
@login_required
def print_return(request, pk):
    """Render a sales return for print (أصل/صورة copies, same UX as invoice)."""
    from .models import SalesReturn
    ret = get_object_or_404(
        SalesReturn.objects.select_related('customer', 'original_invoice')
                          .prefetch_related('lines__item__variants', 'lines__variant'),
        pk=pk,
    )
    company = Company.objects.first()
    copy_param = request.GET.get('copy')
    if copy_param in COPY_PARAM_MAP:
        copies = [COPY_PARAM_MAP[copy_param]]
    else:
        copies = ['أصل', 'صورة']
    return render(request, 'sales/return_print.html', {
        'return_doc': ret,
        'company': company,
        'copies': copies,
    })


COPY_PARAM_MAP = {'original': 'أصل', 'copy': 'صورة'}


@never_cache
@login_required
def print_receipt(request, pk):
    """Render a payment receipt for print.
    `?copy=original|copy` to filter to one page, otherwise both."""
    from .models import Receipt
    receipt = get_object_or_404(
        Receipt.objects.select_related('customer').prefetch_related('allocations__invoice'),
        pk=pk,
    )
    company = Company.objects.first()
    copy_param = request.GET.get('copy')
    if copy_param in COPY_PARAM_MAP:
        copies = [COPY_PARAM_MAP[copy_param]]
    else:
        copies = ['أصل', 'صورة']
    return render(request, 'sales/receipt_print.html', {
        'receipt': receipt,
        'company': company,
        'copies': copies,
    })


@never_cache
@login_required
def print_invoice(request, pk):
    """Render a single invoice for print.
    `?copy=original` → only the أصل page.
    `?copy=copy`     → only the صورة page.
    No parameter     → both pages (default).
    """
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related('customer').prefetch_related('lines__item__variants'),
        pk=pk,
    )
    company = Company.objects.first()
    copy_param = request.GET.get('copy')
    if copy_param in COPY_PARAM_MAP:
        copies = [COPY_PARAM_MAP[copy_param]]
    else:
        copies = ['أصل', 'صورة']
    return render(request, 'sales/invoice_print.html', {
        'invoice': invoice,
        'company': company,
        'copies': copies,
    })


@never_cache
@login_required
def bulk_print_copies(request):
    """Render multiple invoices' "صورة" copies, one per page.
    URL: /sales/invoices/bulk-print-copies/?ids=1,2,3
    """
    ids_str = request.GET.get('ids', '')
    try:
        ids = [int(x) for x in ids_str.split(',') if x.strip()]
    except ValueError:
        ids = []
    invoices = (SalesInvoice.objects
                .filter(pk__in=ids)
                .select_related('customer')
                .prefetch_related('lines__item__variants')
                .order_by('invoice_no'))
    company = Company.objects.first()
    return render(request, 'sales/invoice_bulk_copies.html', {
        'invoices': invoices,
        'company': company,
    })


@login_required
def customer_ledger(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    ar_code = SYSTEM_ACCOUNTS['AR']

    qs = (JournalLine.objects
          .filter(customer=customer, account__code=ar_code, entry__status='POSTED')
          .select_related('entry', 'account')
          .order_by('entry__date', 'entry__id', 'id'))

    rows = []
    running = Decimal(customer.opening_balance or 0)
    if running != 0:
        rows.append({
            'date': '—',
            'reference': '—',
            'description': 'الرصيد الافتتاحي',
            'debit': running if running > 0 else Decimal('0'),
            'credit': -running if running < 0 else Decimal('0'),
            'balance': running,
        })

    for line in qs:
        running += Decimal(line.debit) - Decimal(line.credit)
        rows.append({
            'date': line.entry.date,
            'reference': line.entry.reference,
            'description': line.description or line.entry.description,
            'debit': line.debit,
            'credit': line.credit,
            'balance': running,
        })

    return render(request, 'sales/customer_ledger.html', {
        'customer': customer,
        'rows': rows,
        'closing_balance': running,
        'today': date.today(),
        'company': Company.objects.first(),
    })


@login_required
def aging_report(request):
    """AR aging by customer × bucket (0-30 / 31-60 / 61-90 / 90+).

    Invoice-based amounts are aged by invoice date.  Any remaining receivable that
    isn't tied to an invoice — opening balances, on-account movements — is added and
    aged by the customer's opening entry date, so the report total reconciles to the
    AR control account (and the «المستحق من العملاء» dashboard figure)."""
    from django.db.models import Min
    today = date.today()
    buckets = [(0, 30), (31, 60), (61, 90), (91, 10_000)]
    bucket_labels = ['0-30', '31-60', '61-90', '90+']
    ar_code = SYSTEM_ACCOUNTS['AR']

    def bucket_idx_for(age):
        for i, (lo, hi) in enumerate(buckets):
            if lo <= age <= hi:
                return i
        return len(buckets) - 1  # older than the last range → oldest bucket

    open_invoices = (SalesInvoice.objects
                     .filter(status='POSTED')
                     .select_related('customer'))

    by_customer = {}
    invoiced_due = {}  # customer_id → Σ invoice balance_due (netted against current_balance)
    for inv in open_invoices:
        outstanding = Decimal(inv.balance_due)
        if outstanding <= 0:
            continue
        idx = bucket_idx_for((today - inv.date).days)
        row = by_customer.setdefault(inv.customer, {'total': Decimal('0'),
                                                       'buckets': [Decimal('0')] * len(buckets)})
        row['buckets'][idx] += outstanding
        row['total'] += outstanding
        invoiced_due[inv.customer_id] = invoiced_due.get(inv.customer_id, Decimal('0')) + outstanding

    # Opening / un-invoiced receivable = current_balance − Σ(invoice balance_due).
    # Captures opening balances and any on-account amounts not attached to an invoice,
    # so a customer who only has an opening balance still shows up here.
    opening_dates = {
        r['customer_id']: r['first']
        for r in (JournalLine.objects
                  .filter(account__code=ar_code, entry__status='POSTED', customer__isnull=False)
                  .values('customer_id')
                  .annotate(first=Min('entry__date')))
    }
    for c in Customer.objects.all():
        unbilled = Decimal(c.current_balance or 0) - invoiced_due.get(c.id, Decimal('0'))
        if unbilled <= 0:
            continue
        op_date = opening_dates.get(c.id)
        idx = bucket_idx_for((today - op_date).days) if op_date else len(buckets) - 1
        row = by_customer.setdefault(c, {'total': Decimal('0'),
                                          'buckets': [Decimal('0')] * len(buckets)})
        row['buckets'][idx] += unbilled
        row['total'] += unbilled

    customer_rows = sorted(by_customer.items(), key=lambda kv: -kv[1]['total'])

    totals = {'grand': Decimal('0'),
              'buckets': [Decimal('0')] * len(buckets)}
    for _, row in customer_rows:
        totals['grand'] += row['total']
        for i, b in enumerate(row['buckets']):
            totals['buckets'][i] += b

    return render(request, 'sales/aging_report.html', {
        'today': today,
        'bucket_labels': bucket_labels,
        'rows': customer_rows,
        'totals': totals,
    })
