"""Dashboard + financial reports: Trial Balance, P&L, Balance Sheet."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Count
from django.shortcuts import render

from .account_codes import SYSTEM_ACCOUNTS
from .models import Account
from .reporting import (
    account_balance_as_of,
    all_account_balances_as_of, all_account_balances_in_period, natural_balance,
)


def _parse_date(s, default):
    if not s:
        return default
    try:
        return date.fromisoformat(s)
    except ValueError:
        return default


def _start_of_year(d):
    return d.replace(month=1, day=1)


def _start_of_month(d):
    return d.replace(day=1)


def _last_n_months(n, today):
    """Return list of (year, month, start_date, end_date_exclusive, label) for the last n months ending in today's month."""
    out = []
    for i in range(n - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            y -= 1
            m += 12
        start = date(y, m, 1)
        ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
        end = date(ny, nm, 1)
        out.append((y, m, start, end, f'{m:02d}/{y}'))
    return out


# واجهة موحّدة: نفس تقسيم الـ sidebar — كل موديول مرة واحدة من غير تكرار.
# (label, app, model) — الترتيب مهم.
ADMIN_MODULES = [
    {
        'label': 'الأساسيات',
        'items': [
            ('بيانات الشركة', 'core', 'company'),
            ('دليل الحسابات', 'core', 'account'),
            ('قيود اليومية', 'core', 'journalentry'),
        ],
    },
    {
        'label': 'المخزون',
        'items': [
            ('المنتجات', 'inventory', 'product'),
            ('المنتجات الفرعية', 'inventory', 'item'),
            ('الـ SKUs (المقاسات)', 'inventory', 'itemvariant'),
            ('حركات المخزون', 'inventory', 'stockmovement'),
        ],
    },
    {
        'label': 'المبيعات',
        'items': [
            ('العملاء', 'sales', 'customer'),
            ('سندات القبض', 'sales', 'receipt'),
            ('فواتير المبيعات', 'sales', 'salesinvoice'),
            ('مرتجعات المبيعات', 'sales', 'salesreturn'),
        ],
    },
    {
        'label': 'الخزينة والمصروفات',
        'items': [
            ('حسابات النقدية/البنوك/المحافظ', 'core', 'cashaccount'),
            ('سندات صرف المصروفات', 'core', 'expensevoucher'),
            ('بنود المصروفات', 'core', 'expensecategory'),
            ('الأصول الثابتة', 'core', 'fixedasset'),
        ],
    },
    {
        'label': 'المشتريات',
        'items': [
            ('الموردون', 'manufacturing', 'supplier'),
            ('مشتريات القماش', 'manufacturing', 'fabricbatch'),
            ('مشتريات الإكسسوارات', 'manufacturing', 'accessorypurchase'),
            ('سندات دفع للموردين', 'manufacturing', 'supplierpayment'),
        ],
    },
    {
        'label': 'إدارة المصنع',
        'items': [
            ('وصفات المنتج', 'manufacturing', 'productsizerecipe'),
            ('أوامر الإنتاج', 'manufacturing', 'productionorder'),
            ('صرف المصنعيات', 'manufacturing', 'manufacturingwagepayment'),
            ('الإكسسوارات', 'manufacturing', 'accessory'),
            ('أنواع الأقمشة', 'manufacturing', 'fabrictype'),
            ('ألوان الأقمشة', 'manufacturing', 'fabriccolor'),
            ('المقاسات', 'manufacturing', 'size'),
        ],
    },
    {
        'label': 'المستخدمون',
        'items': [
            ('المستخدمون', 'auth', 'user'),
            ('المجموعات', 'auth', 'group'),
        ],
    },
]


def _build_admin_modules():
    """Return the admin nav structure with list/add URLs filled in."""
    modules = []
    for mod in ADMIN_MODULES:
        items = []
        for label, app, model in mod['items']:
            items.append({
                'label': label,
                'list_url': f'/admin/{app}/{model}/',
                'add_url': f'/admin/{app}/{model}/add/',
            })
        modules.append({'label': mod['label'], 'items': items})
    return modules


@login_required
def dashboard(request):
    """Home / landing page. KPIs + quick actions + report links + charts."""
    from inventory.models import ItemVariant
    from sales.models import SalesInvoice, SalesInvoiceLine

    today = date.today()
    month_start = _start_of_month(today)
    year_start = _start_of_year(today)

    # KPIs
    today_invoices = SalesInvoice.objects.filter(date=today, status='POSTED')
    today_sales_value = today_invoices.aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
    today_sales_count = today_invoices.count()

    mtd_invoices = SalesInvoice.objects.filter(
        date__gte=month_start, date__lte=today, status='POSTED',
    )
    mtd_sales_value = mtd_invoices.aggregate(s=Sum('grand_total'))['s'] or Decimal('0')

    # مبيعات العام (من بداية السنة لحد النهاردة)
    ytd_invoices = SalesInvoice.objects.filter(
        date__gte=year_start, date__lte=today, status='POSTED',
    )
    ytd_sales_value = ytd_invoices.aggregate(s=Sum('grand_total'))['s'] or Decimal('0')

    # النقدية/البنك: كل خزينة/حساب (CashAccount) ليه حساب خاص تحت 1190000، فلازم
    # نجمّع أرصدتهم — مش نقرأ الحساب النظامي القديم لوحده (اللي بيطلّع صفر).
    # بنضيف الحساب القديم 1110000/1120000 كمان عشان أي ترحيل قديم عليه ميضيعش.
    from .models import CashAccount, JournalLine
    cash_balance = Decimal('0')
    bank_balance = Decimal('0')
    wallet_balance = Decimal('0')
    # الحسابات اللي بتستخدمها الخزائن (CashAccount) — عشان منعدّش الحساب القديم مرتين.
    used_gl_ids = set(CashAccount.objects.filter(active=True)
                      .exclude(gl_account=None).values_list('gl_account_id', flat=True))
    # الحساب النظامي القديم 1110000/1120000 يُضاف فقط لو مفيش خزينة بتستخدمه
    # (الخزينة الافتراضية «الصندوق/البنك» بتستخدمه أصلاً، فبيتحسب من اللوب تحت).
    legacy_cash = Account.objects.filter(code=SYSTEM_ACCOUNTS['CASH']).first()
    legacy_bank = Account.objects.filter(code=SYSTEM_ACCOUNTS['BANK']).first()
    if legacy_cash and legacy_cash.id not in used_gl_ids:
        cash_balance += account_balance_as_of(legacy_cash, today)
    if legacy_bank and legacy_bank.id not in used_gl_ids:
        bank_balance += account_balance_as_of(legacy_bank, today)
    for ca in CashAccount.objects.filter(active=True).select_related('gl_account'):
        bal = account_balance_as_of(ca.gl_account, today) if ca.gl_account_id else Decimal('0')
        if ca.account_type == 'CASH':
            cash_balance += bal
        elif ca.account_type == 'WALLET':
            wallet_balance += bal
        else:  # BANK
            bank_balance += bal

    ar_account = Account.objects.filter(code=SYSTEM_ACCOUNTS['AR']).first()
    ar_balance = account_balance_as_of(ar_account, today) if ar_account else Decimal('0')

    # المستحق للموردين = (دائن − مدين) على حساب الموردين للموردين النشطين فقط —
    # نفس حساب صفحة أرصدة الموردين عشان قيمة الكارت تساوي إجمالي الصفحة بالظبط.
    ap_agg = (JournalLine.objects
              .filter(account__code=SYSTEM_ACCOUNTS['AP'], entry__status='POSTED',
                      supplier__active=True)
              .aggregate(d=Sum('debit'), c=Sum('credit')))
    ap_balance = (ap_agg['c'] or Decimal('0')) - (ap_agg['d'] or Decimal('0'))

    inv_value_agg = (ItemVariant.objects
                      .annotate(v=ExpressionWrapper(F('current_stock') * F('average_cost'),
                                                     output_field=DecimalField(max_digits=18, decimal_places=2)))
                      .aggregate(s=Sum('v')))
    inventory_value = (inv_value_agg['s'] or Decimal('0'))

    low_stock_count = (ItemVariant.objects
                        .filter(reorder_level__gt=0, current_stock__lt=F('reorder_level'))
                        .count())

    # Overdue: posted invoices where date + customer.payment_terms_days < today
    # AND balance_due > 0.  payment_terms_days lives on the customer FK.
    overdue_invoices = []
    posted_with_balance = (SalesInvoice.objects
                            .filter(status='POSTED')
                            .select_related('customer'))
    for inv in posted_with_balance:
        if inv.balance_due <= 0:
            continue
        due_date = inv.date + timedelta(days=inv.customer.payment_terms_days)
        if due_date < today:
            overdue_invoices.append(inv)
    overdue_count = len(overdue_invoices)
    overdue_total = sum((Decimal(i.balance_due) for i in overdue_invoices), Decimal('0'))

    # Top 5 items this month by qty of bundles sold
    top_items = (SalesInvoiceLine.objects
                  .filter(invoice__status='POSTED',
                          invoice__date__gte=month_start, invoice__date__lte=today)
                  .values('item__code', 'item__name_ar')
                  .annotate(qty=Sum('quantity'), revenue=Sum('line_total'))
                  .order_by('-qty')[:5])

    # Top 5 customers this month by revenue
    top_customers = (SalesInvoice.objects
                      .filter(status='POSTED',
                              date__gte=month_start, date__lte=today)
                      .values('customer__code', 'customer__name_ar')
                      .annotate(invoices=Count('id'), revenue=Sum('grand_total'))
                      .order_by('-revenue')[:5])

    recent_invoices = (SalesInvoice.objects
                        .filter(status='POSTED')
                        .select_related('customer')
                        .order_by('-date', '-id')[:8])

    # ---------------- Charts data ----------------
    # 1) Sales by month — last 6 months
    monthly_sales_labels = []
    monthly_sales_values = []
    for y, m, start, end, label in _last_n_months(6, today):
        total = SalesInvoice.objects.filter(
            status='POSTED', date__gte=start, date__lt=end,
        ).aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
        monthly_sales_labels.append(label)
        monthly_sales_values.append(float(total))

    # 2) Top customers by revenue (all time, top 8)
    top_cust_rows = (SalesInvoice.objects
                      .filter(status='POSTED')
                      .values('customer__name_ar')
                      .annotate(rev=Sum('grand_total'))
                      .order_by('-rev')[:8])
    top_cust_labels = [r['customer__name_ar'][:20] for r in top_cust_rows]
    top_cust_values = [float(r['rev'] or 0) for r in top_cust_rows]

    # 3) Top items by qty sold (all time, top 8)
    top_item_rows = (SalesInvoiceLine.objects
                      .filter(invoice__status='POSTED')
                      .values('item__code', 'item__name_ar')
                      .annotate(qty=Sum('quantity'))
                      .order_by('-qty')[:8])
    top_item_labels = [r['item__code'] for r in top_item_rows]
    top_item_values = [float(r['qty'] or 0) for r in top_item_rows]

    # 4) AR aging — split posted invoices' balance_due into 4 buckets
    aging_buckets = [0, 0, 0, 0]  # 0-30, 31-60, 61-90, 90+
    aging_labels = ['0-30', '31-60', '61-90', '90+']
    for inv in SalesInvoice.objects.filter(status='POSTED').select_related('customer'):
        bal = Decimal(inv.balance_due)
        if bal <= 0:
            continue
        age = (today - inv.date).days
        if age <= 30:
            idx = 0
        elif age <= 60:
            idx = 1
        elif age <= 90:
            idx = 2
        else:
            idx = 3
        aging_buckets[idx] += float(bal)

    return render(request, 'core/dashboard.html', {
        'today': today,
        'today_sales_value': today_sales_value,
        'today_sales_count': today_sales_count,
        'mtd_sales_value': mtd_sales_value,
        'ytd_sales_value': ytd_sales_value,
        'year_label': today.year,
        'cash_balance': cash_balance,
        'bank_balance': bank_balance,
        'wallet_balance': wallet_balance,
        'ar_balance': ar_balance,
        'ap_balance': ap_balance,
        'inventory_value': inventory_value,
        'low_stock_count': low_stock_count,
        'overdue_count': overdue_count,
        'overdue_total': overdue_total,
        'top_items': top_items,
        'top_customers': top_customers,
        'recent_invoices': recent_invoices,
        'admin_modules': _build_admin_modules(),
        # Chart datasets (JSON-encoded in the template via json_script)
        'chart_monthly_sales': {
            'labels': monthly_sales_labels,
            'values': monthly_sales_values,
        },
        'chart_top_customers': {
            'labels': top_cust_labels,
            'values': top_cust_values,
        },
        'chart_top_items': {
            'labels': top_item_labels,
            'values': top_item_values,
        },
        'chart_ar_aging': {
            'labels': aging_labels,
            'values': aging_buckets,
        },
    })


@login_required
def cash_balances(request):
    """رصيد كل خزينة/بنك/محفظة (live من القيود) — مجمّعين حسب النوع، مع فلتر بالنوع.

    بيوصلها كروت "النقدية" (?type=CASH) و"البنوك" (?type=BANK) و"المحافظ" (?type=WALLET)
    من لوحة التحكم — أو من غير فلتر بتعرض كل الأنواع مع الإجمالي العام. كل سطر بيبيّن
    رصيد الحساب لوحده عشان المستخدم يعرف كل خزنة/بنك/محفظة فيها كام.
    """
    from .models import CashAccount

    today = date.today()
    type_filter = (request.GET.get('type') or '').upper()
    if type_filter not in {'CASH', 'BANK', 'WALLET'}:
        type_filter = ''

    type_labels = dict(CashAccount.TYPE_CHOICES)
    type_order = ['CASH', 'BANK', 'WALLET']

    qs = CashAccount.objects.filter(active=True).select_related('gl_account')
    if type_filter:
        qs = qs.filter(account_type=type_filter)

    buckets = {}
    grand_total = Decimal('0')
    for ca in qs.order_by('account_type', 'name'):
        bal = account_balance_as_of(ca.gl_account, today) if ca.gl_account_id else Decimal('0')
        b = buckets.setdefault(ca.account_type, {
            'type': ca.account_type,
            'label': type_labels.get(ca.account_type, ca.account_type),
            'rows': [],
            'total': Decimal('0'),
        })
        b['rows'].append({'ca': ca, 'balance': bal})
        b['total'] += bal
        grand_total += bal

    groups = [buckets[t] for t in type_order if t in buckets]
    tabs = [
        {'key': '', 'label': 'الكل'},
        {'key': 'CASH', 'label': 'الخزائن النقدية'},
        {'key': 'BANK', 'label': 'البنوك'},
        {'key': 'WALLET', 'label': 'المحافظ'},
    ]

    return render(request, 'core/cash_balances.html', {
        'groups': groups,
        'grand_total': grand_total,
        'type_filter': type_filter,
        'tabs': tabs,
        'as_of': today,
    })


@login_required
def trial_balance(request):
    as_of = _parse_date(request.GET.get('as_of'), date.today())
    bal_map = all_account_balances_as_of(as_of)

    accounts = list(Account.objects.filter(is_group=False, is_active=True).order_by('code'))
    rows = []
    total_debit = total_credit = Decimal('0')
    for a in accounts:
        d, c = bal_map.get(a.id, (Decimal('0'), Decimal('0')))
        net = d - c
        if net == 0:
            continue
        if net > 0:
            rows.append({'account': a, 'debit': net, 'credit': Decimal('0')})
            total_debit += net
        else:
            rows.append({'account': a, 'debit': Decimal('0'), 'credit': -net})
            total_credit += -net

    return render(request, 'core/trial_balance.html', {
        'as_of': as_of,
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'balanced': total_debit == total_credit,
    })


def _grouped_by_type(accounts, balance_map):
    """Group leaf accounts by account_type with subtotals (natural-sign amount)."""
    by_type = defaultdict(list)
    type_totals = defaultdict(lambda: Decimal('0'))
    for a in accounts:
        d, c = balance_map.get(a.id, (Decimal('0'), Decimal('0')))
        if d == 0 and c == 0:
            continue
        natural = natural_balance(a, d, c)
        by_type[a.account_type].append({'account': a, 'amount': natural})
        type_totals[a.account_type] += natural
    return by_type, type_totals


@login_required
def pnl(request):
    today = date.today()
    date_from = _parse_date(request.GET.get('from'), _start_of_year(today))
    date_to = _parse_date(request.GET.get('to'), today)

    bal_map = all_account_balances_in_period(date_from, date_to)
    accounts = list(Account.objects.filter(
        is_group=False, account_type__in=['REVENUE', 'EXPENSE']
    ).order_by('code'))

    by_type, type_totals = _grouped_by_type(accounts, bal_map)
    revenue_total = type_totals.get('REVENUE', Decimal('0'))
    expense_total = type_totals.get('EXPENSE', Decimal('0'))
    net_income = revenue_total - expense_total

    return render(request, 'core/pnl.html', {
        'date_from': date_from,
        'date_to': date_to,
        'revenue_rows': by_type.get('REVENUE', []),
        'expense_rows': by_type.get('EXPENSE', []),
        'revenue_total': revenue_total,
        'expense_total': expense_total,
        'net_income': net_income,
    })


@login_required
def balance_sheet(request):
    as_of = _parse_date(request.GET.get('as_of'), date.today())

    bal_map = all_account_balances_as_of(as_of)
    bs_accounts = list(Account.objects.filter(
        is_group=False, account_type__in=['ASSET', 'LIABILITY', 'EQUITY']
    ).order_by('code'))
    by_type, type_totals = _grouped_by_type(bs_accounts, bal_map)

    # YTD net income (revenue - expenses) flows into equity for the snapshot
    ytd_from = _start_of_year(as_of)
    ie_bal = all_account_balances_in_period(ytd_from, as_of)
    ie_accounts = list(Account.objects.filter(
        is_group=False, account_type__in=['REVENUE', 'EXPENSE']
    ))
    _, ie_totals = _grouped_by_type(ie_accounts, ie_bal)
    ytd_net = ie_totals.get('REVENUE', Decimal('0')) - ie_totals.get('EXPENSE', Decimal('0'))

    assets_total = type_totals.get('ASSET', Decimal('0'))
    liabilities_total = type_totals.get('LIABILITY', Decimal('0'))
    equity_total = type_totals.get('EQUITY', Decimal('0')) + ytd_net
    le_total = liabilities_total + equity_total
    variance = assets_total - le_total

    return render(request, 'core/balance_sheet.html', {
        'as_of': as_of,
        'asset_rows': by_type.get('ASSET', []),
        'liability_rows': by_type.get('LIABILITY', []),
        'equity_rows': by_type.get('EQUITY', []),
        'assets_total': assets_total,
        'liabilities_total': liabilities_total,
        'equity_excluding_ytd': type_totals.get('EQUITY', Decimal('0')),
        'ytd_net': ytd_net,
        'equity_total': equity_total,
        'le_total': le_total,
        'variance': variance,
        'balanced': variance == 0,
    })
