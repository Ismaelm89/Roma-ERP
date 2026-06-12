"""Roma Manufacturing — read-only reports for the fabric module."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date

from core.account_codes import SYSTEM_ACCOUNTS
from core.models import Company, JournalLine

from .models import (FabricBatch, FabricMovement, Supplier, ProductionOrder,
                     Size, Accessory)


@login_required
def fabric_on_hand(request):
    """Every batch with remaining qty > 0, plus headline totals."""
    show_at_dyer = request.GET.get('include_at_dyer', '1') == '1'

    qs = (FabricBatch.objects
          .filter(is_posted=True)
          .select_related('supplier', 'fabric_type', 'color')
          .order_by('-purchase_date', '-id'))

    batches = []
    total_in_stock_kg = Decimal('0')
    total_at_dyer_kg = Decimal('0')
    total_value = Decimal('0')

    for b in qs:
        in_stock = Decimal(b.in_stock_qty_kg)
        at_dyer = Decimal('0')
        remaining = in_stock + at_dyer
        if remaining <= 0:
            continue
        if not show_at_dyer and in_stock <= 0:
            continue
        # value of *what's left* = cost_per_kg × remaining
        value_left = (b.cost_per_kg * remaining).quantize(Decimal('0.01'))
        batches.append({
            'b': b,
            'in_stock_kg': in_stock,
            'at_dyer_kg': at_dyer,
            'remaining_kg': remaining,
            'cost_per_kg': b.cost_per_kg,
            'value_left': value_left,
        })
        total_in_stock_kg += in_stock
        total_at_dyer_kg += at_dyer
        total_value += value_left

    context = {
        'company': Company.objects.first(),
        'batches': batches,
        'total_in_stock_kg': total_in_stock_kg,
        'total_at_dyer_kg': total_at_dyer_kg,
        'total_remaining_kg': total_in_stock_kg + total_at_dyer_kg,
        'total_value': total_value,
        'show_at_dyer': show_at_dyer,
    }
    return render(request, 'manufacturing/fabric_on_hand.html', context)


@login_required
def fabric_movements(request):
    """Filterable movement log: date range + batch + type."""
    date_from = parse_date(request.GET.get('date_from', '')) if request.GET.get('date_from') else None
    date_to = parse_date(request.GET.get('date_to', '')) if request.GET.get('date_to') else None
    batch_id = request.GET.get('batch') or None
    mtype = request.GET.get('type') or None

    qs = (FabricMovement.objects
          .select_related('batch', 'batch__fabric_type', 'batch__color')
          .order_by('-date', '-id'))
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)
    if mtype:
        qs = qs.filter(movement_type=mtype)

    movements = qs[:500]  # cap to keep the page snappy
    type_options = FabricMovement.MOVEMENT_TYPES

    context = {
        'company': Company.objects.first(),
        'movements': movements,
        'count': qs.count(),
        'capped': qs.count() > 500,
        'date_from': date_from,
        'date_to': date_to,
        'batch_id': batch_id,
        'mtype': mtype,
        'type_options': type_options,
        'batches': FabricBatch.objects.filter(is_posted=True).order_by('-purchase_date')[:200],
    }
    return render(request, 'manufacturing/fabric_movements.html', context)


# ============================================================
#  Supplier / dyer reports
# ============================================================

@login_required
def supplier_ledger(request, pk):
    """Single ledger for any supplier (fabric, dyer, accessories, machinery, ...)."""
    supplier = get_object_or_404(Supplier, pk=pk)
    ap_code = SYSTEM_ACCOUNTS['AP']
    qs = (JournalLine.objects
          .filter(supplier=supplier, account__code=ap_code, entry__status='POSTED')
          .select_related('entry')
          .order_by('entry__date', 'entry__id', 'id'))

    rows = []
    running = Decimal('0')
    for line in qs:
        running += Decimal(line.credit) - Decimal(line.debit)
        rows.append({
            'date': line.entry.date,
            'reference': line.entry.reference,
            'description': line.description or line.entry.description,
            'debit': line.debit,
            'credit': line.credit,
            'balance': running,
        })

    return render(request, 'manufacturing/vendor_ledger.html', {
        'company': Company.objects.first(),
        'vendor': supplier,
        'vendor_kind': supplier.vendor_type.name_ar,
        'rows': rows,
        'closing_balance': running,
    })


@login_required
def dyer_ledger(request, pk):
    """Back-compat alias — /manufacturing/dyer/<pk>/ledger/ still works."""
    return supplier_ledger(request, pk)


@login_required
def suppliers_balances(request):
    """All suppliers (every vendor_type) with their live AP balance, grouped by type."""
    groups = []  # [{'vendor_type': vt, 'rows': [...], 'total': X}]
    grand_total = Decimal('0')
    seen_types = {}

    for s in Supplier.objects.filter(active=True).select_related('vendor_type').order_by(
            'vendor_type__sort_order', 'code'):
        bal = s.current_balance
        grand_total += bal
        bucket = seen_types.setdefault(s.vendor_type_id, {
            'vendor_type': s.vendor_type,
            'rows': [],
            'total': Decimal('0'),
        })
        bucket['rows'].append({
            'v': s,
            'balance': bal,
            'ledger_url': f'/manufacturing/supplier/{s.pk}/ledger/',
        })
        bucket['total'] += bal

    groups = sorted(seen_types.values(), key=lambda g: g['vendor_type'].sort_order)

    return render(request, 'manufacturing/suppliers_balances.html', {
        'company': Company.objects.first(),
        'groups': groups,
        'grand_total': grand_total,
    })


# ============================================================
#  Production order print (Phase 2c)
# ============================================================

def _production_order_context(order_pk):
    order = get_object_or_404(
        ProductionOrder.objects
            .select_related('item', 'customer')
            .prefetch_related('sub_models', 'sizes__size', 'sizes__sub_model',
                              'fabric_usages__batch',
                              'accessory_usages__accessory',
                              'printing_rows', 'operation_rows',
                              'quality_rows', 'ironing_rows'),
        pk=order_pk,
    )

    # Dynamic size columns: the distinct sizes actually used on this order,
    # ordered by the Size master's sort_order (handles letters + numbers).
    size_cols = list(
        Size.objects.filter(production_sizes__order=order)
        .distinct().order_by('sort_order', 'code')
    )

    # Matrix rows grouped by sub-model (product notes). Each row = one sub-model
    # with its quantities spread across the size columns + its cut data.
    groups_map = {}
    order_keys = []
    for ps in order.sizes.all():
        key = ps.sub_model_id
        if key not in groups_map:
            groups_map[key] = {'notes': ps.sub_model, 'by_size': {}, 'total': 0}
            order_keys.append(key)
        bucket = groups_map[key]
        bucket['by_size'][ps.size_id] = bucket['by_size'].get(ps.size_id, 0) + ps.quantity
        bucket['total'] += ps.quantity

    col_totals = {s.id: 0 for s in size_cols}
    matrix_rows = []
    for i, key in enumerate(order_keys, start=1):
        g = groups_map[key]
        cells = []
        for s in size_cols:
            q = g['by_size'].get(s.id, 0)
            cells.append(q or '')
            col_totals[s.id] += q
        notes = g['notes']
        no = notes.sub_model_no if (notes and notes.sub_model_no) else i
        matrix_rows.append({'no': no, 'notes': notes, 'cells': cells, 'total': g['total']})

    size_headers = [{'code': s.code, 'total': col_totals[s.id]} for s in size_cols]
    grand_total = sum(col_totals.values())

    # ---- استهلاكات القماش: الكمية «قبل الهالك» فقط، محسوبة من أمر الإنتاج ----
    # بعد الإنتاج: من البنود المتولّدة (planned_qty_kg = قبل الهالك).
    # في مرحلة الخطة (لسه مفيش بنود): من خامة المنتج الرئيسي ووصفته مباشرةً.
    fabric_rows = []
    usages = list(order.fabric_usages.select_related('batch', 'fabric_type').all())
    if usages:
        for u in usages:
            fabric_rows.append({
                'name': u.fabric_type.name_ar if u.fabric_type_id else '',
                'batch': u.batch,
                # لون القماش: من الدفعة لو متاحة، وإلا لون موديل الأمر.
                'color': (u.batch.color.name_ar if (u.batch and u.batch.color_id)
                          else (order.fabric_color.name_ar if order.fabric_color else '')),
                'qty_before': u.planned_qty_kg,
                # ملاحظات أمر الإنتاج اللي بيكتبها المستخدم على الأمر (مش نص تلقائي).
                'notes': order.notes,
            })
    else:
        p = order.main_product
        if p and p.fabric_type_id and order.has_recipe:
            fabric_rows.append({
                'name': p.fabric_type.name_ar,
                'batch': None,
                'color': order.fabric_color.name_ar if order.fabric_color else '',
                'qty_before': order.recipe_planned_fabric_kg,
                'notes': order.notes,
            })
    fabric_total_before = order.total_planned_fabric_kg

    # ---- الإكسسوارات: العدد ييجي تلقائياً من وصفة المنتج (مفيش إدخال يدوي) ----
    acc_plan = order.recipe_accessory_plan()  # {accessory_id: الكمية المخططة}
    acc_objs = {a.id: a for a in Accessory.objects.filter(id__in=list(acc_plan.keys()))}
    accessory_rows = []
    for acc_id, qty in acc_plan.items():
        a = acc_objs.get(acc_id)
        if a:
            accessory_rows.append({
                'name': a.name_ar, 'unit': a.unit,
                'qty': Decimal(qty).quantize(Decimal('0.001')),
            })

    # ---- مراحل الشغل الأربعة (طباعة / تشغيل / جودة / كوي) — جدول مستقل لكل
    # مرحلة بعدد صفوف ثابت (المملوء + الباقي فاضي للتعبئة باليد)، ومجموع كميات
    # كل مرحلة بيتقارن بإجمالي القطع. ----
    def _stage_rows(rel, min_rows, op=False):
        rows = []
        for r in rel.all():
            row = {'worker': r.worker, 'qty': r.qty or ''}
            if op:
                row.update({'stage_no': r.stage_no, 'stage_name': r.stage_name,
                            'machine': r.machine})
            rows.append(row)
        blank = ({'stage_no': '', 'stage_name': '', 'machine': '', 'worker': '', 'qty': ''}
                 if op else {'worker': '', 'qty': ''})
        while len(rows) < min_rows:
            rows.append(dict(blank))
        return rows

    stage_defs = (
        ('الطباعة', order.printing_rows),
        ('التشغيل', order.operation_rows),
        ('الجودة', order.quality_rows),
        ('الكوي', order.ironing_rows),
    )
    stage_totals = []
    for label, rel in stage_defs:
        tot = sum(r.qty or 0 for r in rel.all())
        stage_totals.append({
            'label': label,
            'total': tot,
            'match': (tot == grand_total) if tot else True,
        })

    printing_rows = _stage_rows(order.printing_rows, 5)
    operation_rows = _stage_rows(order.operation_rows, 15, op=True)
    quality_rows = _stage_rows(order.quality_rows, 5)
    ironing_rows = _stage_rows(order.ironing_rows, 5)

    return {
        'company': Company.objects.first(),
        'order': order,
        'size_headers': size_headers,
        'size_count': len(size_headers),
        'matrix_rows': matrix_rows,
        'grand_total': grand_total,
        'printing_rows': printing_rows,
        'operation_rows': operation_rows,
        'quality_rows': quality_rows,
        'ironing_rows': ironing_rows,
        'stage_totals': stage_totals,
        'fabric_rows': fabric_rows,
        'fabric_total_before': fabric_total_before,
        'accessory_rows': accessory_rows,
        # مرحلة "خطة" = لسه ما اتعملش إنتاج (للعرض فقط).
        'plan_stage': order.status == 'DRAFT',
    }


@login_required
def production_order_print(request, order_pk):
    """Full cutting sheet for a production order."""
    ctx = _production_order_context(order_pk)
    return render(request, 'manufacturing/production_order_print.html', ctx)
