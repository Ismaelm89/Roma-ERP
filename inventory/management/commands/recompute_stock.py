"""Rebuild ItemVariant.current_stock + average_cost from the StockMovement log.

Use this when there's a drift between physical inventory value (qty × WAC)
and the Inventory GL balance — typically caused by cancelled/deleted
movements that left the cached WAC in a transient state.

The movement log is the source of truth.  Cached fields on ItemVariant get
rebuilt by replaying every movement in chronological order using the
Weighted Average Cost formula.

Usage:
    python manage.py recompute_stock           # all variants
    python manage.py recompute_stock CS0010    # only variants of one item
    python manage.py recompute_stock --dry-run # show diffs without writing
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import ItemVariant, StockMovement


def replay(variant):
    """Compute final (stock, WAC) by replaying movements oldest-first."""
    stock = Decimal('0')
    wac = Decimal('0')
    for m in variant.movements.order_by('id'):
        qty = Decimal(m.quantity)
        cost = Decimal(m.unit_cost)
        if m.is_inbound:
            new_stock = stock + qty
            if new_stock > 0:
                wac = ((stock * wac) + (qty * cost)) / new_stock
            stock = new_stock
        else:
            stock = stock - qty
            # WAC unchanged on outbound
    return stock.quantize(Decimal('0.01')), wac.quantize(Decimal('0.0001'))


class Command(BaseCommand):
    help = 'Rebuild ItemVariant.current_stock + average_cost from movements.'

    def add_arguments(self, parser):
        parser.add_argument('item_code', nargs='?', default=None,
                             help='Optional: limit to one item by code')
        parser.add_argument('--dry-run', action='store_true',
                             help='Show what would change without writing')

    @transaction.atomic
    def handle(self, *args, **opts):
        qs = ItemVariant.objects.select_related('item')
        if opts['item_code']:
            qs = qs.filter(item__code=opts['item_code'])

        fixed = unchanged = 0
        for v in qs.order_by('item__code', 'size_order'):
            stock, wac = replay(v)
            cur_stock = Decimal(v.current_stock).quantize(Decimal('0.01'))
            cur_wac = Decimal(v.average_cost).quantize(Decimal('0.0001'))
            if cur_stock == stock and cur_wac == wac:
                unchanged += 1
                continue

            fixed += 1
            self.stdout.write(
                f'  {v.sku_code:22s} stock: {cur_stock} → {stock}   '
                f'WAC: {cur_wac} → {wac}'
            )
            if not opts['dry_run']:
                v.current_stock = stock
                v.average_cost = wac
                v.save(update_fields=['current_stock', 'average_cost'])

        if opts['dry_run']:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                f'DRY RUN — would fix {fixed} variant(s), {unchanged} already correct.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Rebuilt {fixed} variant(s), {unchanged} already correct.'
            ))
