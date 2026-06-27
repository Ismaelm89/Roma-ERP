"""Manual opening-balance entry screens (الأرصدة الافتتاحية).

Each screen prefills the values already posted (so it round-trips and can be
edited) and, on POST, calls the matching idempotent service in ``core.opening``.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .account_codes import get_system_account
from .models import Account, JournalEntry, JournalLine
from .opening import (
    SRC, OpeningError, opening_summary,
    post_customers_opening, post_suppliers_opening, post_cash_opening,
    post_assets_opening, post_inventory_opening, post_accessories_opening,
    post_fabric_opening, finalize_opening,
)


# ------------------------------------------------------------------
#  Small input helpers
# ------------------------------------------------------------------

def _dec(raw):
    """Parse a posted number (tolerating thousands commas / blanks) → Decimal."""
    if raw is None:
        return Decimal('0')
    s = str(raw).strip().replace(',', '')
    if not s:
        return Decimal('0')
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _parse_date(raw):
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return date.today()


def _fmt(value):
    """Plain <input> value: '' for zero, else a trimmed decimal string (no commas)."""
    d = Decimal(value or 0)
    if d == 0:
        return ''
    s = f'{d:.4f}'.rstrip('0').rstrip('.')
    return s or '0'


def _existing_date(src):
    je = JournalEntry.objects.filter(source_doc_type=src).order_by('id').first()
    return je.date if je else date.today()


# ------------------------------------------------------------------
#  Hub
# ------------------------------------------------------------------

@login_required
def hub(request):
    return render(request, 'opening/hub.html', {
        'active': 'hub',
        's': opening_summary(),
    })


# ------------------------------------------------------------------
#  1) Customers
# ------------------------------------------------------------------

@login_required
def customers(request):
    from sales.models import Customer
    custs = list(Customer.objects.all().order_by('code'))

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        rows = [(c, _dec(request.POST.get(f'amount_{c.id}'))) for c in custs]
        try:
            post_customers_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للعملاء.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:customers')

    ar = get_system_account('AR')
    current = {}
    for jl in JournalLine.objects.filter(entry__source_doc_type=SRC['customers'], account=ar):
        if jl.customer_id:
            current[jl.customer_id] = (jl.debit - jl.credit)
    rows = [{'obj': c, 'amount': _fmt(current.get(c.id, 0))} for c in custs]
    return render(request, 'opening/customers.html', {
        'active': 'customers', 'rows': rows,
        'ob_date': _existing_date(SRC['customers']),
    })


# ------------------------------------------------------------------
#  2) Suppliers
# ------------------------------------------------------------------

@login_required
def suppliers(request):
    from manufacturing.models import Supplier
    sups = list(Supplier.objects.select_related('vendor_type').filter(active=True).order_by('code'))

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        rows = [(s, _dec(request.POST.get(f'amount_{s.id}'))) for s in sups]
        try:
            post_suppliers_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للموردين.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:suppliers')

    ap = get_system_account('AP')
    current = {}
    for jl in JournalLine.objects.filter(entry__source_doc_type=SRC['suppliers'], account=ap):
        if jl.supplier_id:
            current[jl.supplier_id] = (jl.credit - jl.debit)
    rows = [{'obj': s, 'amount': _fmt(current.get(s.id, 0))} for s in sups]
    return render(request, 'opening/suppliers.html', {
        'active': 'suppliers', 'rows': rows,
        'ob_date': _existing_date(SRC['suppliers']),
    })


# ------------------------------------------------------------------
#  3) Inventory (finished goods)
# ------------------------------------------------------------------

@login_required
def inventory(request):
    from inventory.models import ItemVariant, StockMovement
    variants = list(ItemVariant.objects.select_related('item').order_by('item__code', 'size_order'))

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        rows = []
        for v in variants:
            qty = _dec(request.POST.get(f'qty_{v.id}'))
            cost = _dec(request.POST.get(f'cost_{v.id}'))
            rows.append((v, qty, cost))
        try:
            post_inventory_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للمخزون.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:inventory')

    mv = {m.variant_id: m for m in
          StockMovement.objects.filter(document_type='Opening:Inventory')}
    rows = []
    for v in variants:
        m = mv.get(v.id)
        rows.append({
            'v': v,
            'qty': _fmt(m.quantity) if m else '',
            'cost': _fmt(m.unit_cost) if m else '',
        })
    return render(request, 'opening/inventory.html', {
        'active': 'inventory', 'rows': rows,
        'ob_date': _existing_date(SRC['inventory']),
    })


# ------------------------------------------------------------------
#  Accessories (raw material)
# ------------------------------------------------------------------

@login_required
def accessories(request):
    from manufacturing.models import Accessory
    accs = list(Accessory.objects.filter(active=True).order_by('code'))

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        rows = []
        for a in accs:
            # المُدخل بوحدة الشراء — نحوّله لوحدة الاستهلاك قبل الترحيل.
            qty_p = _dec(request.POST.get(f'qty_{a.id}'))
            cost_p = _dec(request.POST.get(f'cost_{a.id}'))
            factor = Decimal(a.units_per_purchase or 0)
            if factor <= 0:
                factor = Decimal('1')
            qty = qty_p * factor                 # consumption units
            cost = (cost_p / factor) if factor else cost_p
            rows.append((a, qty, cost))
        try:
            post_accessories_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للإكسسوارات.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:accessories')

    # prefill: الإكسسوارات اللي ليها بند في قيد الافتتاح بترجّع كميتها وتكلفتها الافتتاحية
    # الأصلية (opening_stock الثابت — مش الرصيد الحالي اللي بينقص بالاستهلاك).
    # الافتتاحي مخزّن بوحدة الاستهلاك → نرجّعه لوحدة الشراء للعرض.
    opened = set(JournalLine.objects
                 .filter(entry__source_doc_type=SRC['accessories'])
                 .exclude(accessory__isnull=True)
                 .values_list('accessory_id', flat=True))
    rows = []
    for a in accs:
        on = a.id in opened
        rows.append({
            'a': a,
            'qty': _fmt(a.opening_in_purchase_unit) if on else '',
            'cost': _fmt(a.opening_cost_per_purchase_unit) if on else (_fmt(a.default_unit_cost) or ''),
        })
    return render(request, 'opening/accessories.html', {
        'active': 'accessories', 'rows': rows,
        'ob_date': _existing_date(SRC['accessories']),
    })


# ------------------------------------------------------------------
#  Fabric (raw material)
# ------------------------------------------------------------------

@login_required
def fabric(request):
    from manufacturing.models import (Supplier, FabricType, FabricColor,
                                       FabricBatch)
    sup_qs = (Supplier.objects.filter(vendor_type__code='FABRIC_SUPPLIER', active=True)
              .order_by('name'))
    ftype_qs = FabricType.objects.filter(active=True).order_by('name_ar')
    color_qs = FabricColor.objects.filter(active=True).order_by('name_ar')

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        n = 0
        try:
            n = int(request.POST.get('row_count') or 0)
        except (ValueError, TypeError):
            n = 0
        rows = []
        for i in range(n):
            sid = request.POST.get(f'supplier_{i}') or ''
            tid = request.POST.get(f'ftype_{i}') or ''
            cid = request.POST.get(f'color_{i}') or ''
            qty = _dec(request.POST.get(f'qty_{i}'))
            cost = _dec(request.POST.get(f'cost_{i}'))
            if qty <= 0 and not (sid or tid or cid):
                continue
            supplier = Supplier.objects.filter(pk=sid).first() if sid else None
            ftype = FabricType.objects.filter(pk=tid).first() if tid else None
            color = FabricColor.objects.filter(pk=cid).first() if cid else None
            rows.append((supplier, ftype, color, qty, cost))
        try:
            post_fabric_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للأقمشة.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:fabric')

    existing = (FabricBatch.objects
                .filter(movements__document_type='Opening:Fabric')
                .select_related('supplier', 'fabric_type', 'color')
                .distinct().order_by('id'))
    prefill = [{
        'supplier_id': b.supplier_id, 'ftype_id': b.fabric_type_id,
        'color_id': b.color_id, 'qty': _fmt(b.purchase_qty_kg),
        'cost': _fmt(b.purchase_unit_cost),
    } for b in existing]
    rows = prefill + [{} for _ in range(8)]
    return render(request, 'opening/fabric.html', {
        'active': 'fabric', 'rows': rows, 'row_count': len(rows),
        'suppliers': sup_qs, 'ftypes': ftype_qs, 'colors': color_qs,
        'ob_date': _existing_date(SRC['fabric']),
    })


# ------------------------------------------------------------------
#  4) Fixed assets
# ------------------------------------------------------------------

@login_required
def assets(request):
    from .models import FixedAsset
    categories = FixedAsset.CATEGORY_CHOICES

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        try:
            n = int(request.POST.get('row_count') or 0)
        except (ValueError, TypeError):
            n = 0
        rows = []
        for i in range(n):
            name = (request.POST.get(f'name_{i}') or '').strip()
            category = request.POST.get(f'category_{i}') or 'OTHER'
            cost = _dec(request.POST.get(f'cost_{i}'))
            if not name and cost == 0:
                continue
            rows.append((name, category, cost))
        try:
            post_assets_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للأصول الثابتة.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:assets')

    # prefill: أصول الافتتاح المسجّلة (المربوطة بقيد الافتتاح) عشان الشاشة تتعدّل وتتحفظ تاني.
    existing = (FixedAsset.objects
                .filter(journal_entry__source_doc_type=SRC['assets'])
                .order_by('id'))
    prefill = [{'name': a.name, 'category': a.category, 'cost': _fmt(a.cost)}
               for a in existing]
    rows = prefill + [{} for _ in range(5)]
    return render(request, 'opening/assets.html', {
        'active': 'assets', 'rows': rows, 'row_count': len(rows),
        'categories': categories,
        'ob_date': _existing_date(SRC['assets']),
    })


# ------------------------------------------------------------------
#  5) Cash / bank / wallet
# ------------------------------------------------------------------

@login_required
def cash(request):
    from .models import CashAccount
    accounts = list(CashAccount.objects.filter(active=True).order_by('account_type', 'name'))

    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        rows = [(ca, _dec(request.POST.get(f'amount_{ca.id}'))) for ca in accounts]
        try:
            post_cash_opening(rows, date=ob_date)
            messages.success(request, 'تم حفظ الأرصدة الافتتاحية للنقدية.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:cash')

    gl_net = {}
    for jl in JournalLine.objects.filter(entry__source_doc_type=SRC['cash']):
        gl_net[jl.account_id] = gl_net.get(jl.account_id, Decimal('0')) + (jl.debit - jl.credit)
    rows = [{'obj': ca, 'amount': _fmt(gl_net.get(ca.gl_account_id, 0))} for ca in accounts]
    return render(request, 'opening/cash.html', {
        'active': 'cash', 'rows': rows,
        'ob_date': _existing_date(SRC['cash']),
    })


# ------------------------------------------------------------------
#  6) Finalize → Capital + Partner Current
# ------------------------------------------------------------------

@login_required
def finalize(request):
    if request.method == 'POST':
        ob_date = _parse_date(request.POST.get('ob_date'))
        cap = _dec(request.POST.get('registered_capital'))
        try:
            finalize_opening(cap, date=ob_date)
            messages.success(request, 'تم إقفال الأرصدة الافتتاحية على رأس المال وجاري الشريك.')
        except OpeningError as e:
            messages.error(request, str(e))
        return redirect('opening:finalize')

    s = opening_summary()
    prefill_cap = _fmt(s['capital_total']) if s['finalized'] else ''
    return render(request, 'opening/finalize.html', {
        'active': 'finalize', 's': s, 'prefill_cap': prefill_cap,
        'ob_date': _existing_date(SRC['finalize']),
    })
