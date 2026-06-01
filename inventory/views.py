"""Inventory reports."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum, DecimalField, ExpressionWrapper
from django.shortcuts import render

from core.account_codes import SYSTEM_ACCOUNTS
from core.models import Account, JournalLine
from .models import Item, ItemVariant


@login_required
def valuation_report(request):
    """Inventory valuation: per-SKU quantity × WAC = value, plus grand total.
    Compared against the Inventory GL balance to flag any reconciliation gap.
    """
    show_zero = request.GET.get('show_zero') == '1'

    qs = (ItemVariant.objects
          .select_related('item')
          .annotate(value=ExpressionWrapper(
              F('current_stock') * F('average_cost'),
              output_field=DecimalField(max_digits=18, decimal_places=4))))
    if not show_zero:
        qs = qs.exclude(current_stock=0, average_cost=0)
    qs = qs.order_by('-value', 'item__code', 'size')

    rows = list(qs)
    total_qty = sum((Decimal(r.current_stock) for r in rows), Decimal('0'))
    total_value = sum((Decimal(r.value or 0) for r in rows), Decimal('0'))

    # Compare to Inventory GL account balance (variance flags reconciliation issues)
    inv_account = Account.objects.filter(code=SYSTEM_ACCOUNTS['INVENTORY']).first()
    if inv_account:
        agg = JournalLine.objects.filter(
            account=inv_account, entry__status='POSTED'
        ).aggregate(d=Sum('debit'), c=Sum('credit'))
        gl_balance = (agg['d'] or Decimal('0')) - (agg['c'] or Decimal('0'))
    else:
        gl_balance = Decimal('0')

    variance = total_value - gl_balance

    return render(request, 'inventory/valuation.html', {
        'rows': rows,
        'total_qty': total_qty,
        'total_value': total_value,
        'gl_balance': gl_balance,
        'variance': variance,
        'show_zero': show_zero,
    })


@login_required
def products_report(request):
    """Visual report: every active item as a card with image + aggregated stock + value.
    The product photo is the primary identifier — code and name are below it.
    """
    show_inactive = request.GET.get('show_inactive') == '1'
    qs = Item.objects.all().prefetch_related('variants').order_by('code')
    if not show_inactive:
        qs = qs.filter(active=True)

    rows = []
    grand_pieces = Decimal('0')
    grand_value = Decimal('0')
    grand_dozens = Decimal('0')

    for it in qs:
        variants = list(it.variants.all())  # ordered S/M/L/XL via Meta
        total_pieces = sum((Decimal(v.current_stock) for v in variants), Decimal('0'))
        total_value = sum(
            (Decimal(v.current_stock) * Decimal(v.average_cost) for v in variants),
            Decimal('0')
        )
        # النظام كله شغّال بالدستة: عدد الدستات = إجمالي القطع ÷ عدد القطع في الدستة
        dozen_size = Decimal(it.dozen_size or 12)
        total_dozens = (total_pieces / dozen_size) if dozen_size else Decimal('0')
        rows.append({
            'item': it,
            'variants': variants,
            'total_pieces': total_pieces,
            'total_value': total_value,
            'total_dozens': total_dozens,
        })
        grand_pieces += total_pieces
        grand_value += total_value
        grand_dozens += total_dozens

    return render(request, 'inventory/products_report.html', {
        'rows': rows,
        'grand_pieces': grand_pieces,
        'grand_value': grand_value,
        'grand_dozens': grand_dozens,
        'show_inactive': show_inactive,
        'total_items': len(rows),
    })
